import errno
import datetime
import os
import re
import signal
import socket
import threading
import time

from flask import Flask, abort, jsonify, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from .config import AppConfig, load_dotenv, validate_environment
from .knowledge import append_memory_entry, check_knowledge_file, get_formal_knowledge_files
from .learning import (
    append_learning_event,
    append_pending_knowledge,
    detect_user_correction,
    load_pre_answer_lessons,
    parse_learned_tags,
    rebuild_lessons_and_troubleshooting,
)
from .approval_gate import ApprovalGate
from .policy_engine import PolicyEngine
from .providers import ProviderService, check_ollama_model, check_ollama_service
from .router import ask_ai
from .runtime import RuntimeState
from .sidecar import SidecarDispatcher
from .tool_executor import ToolExecutor
from .tool_registry import load_tool_registry
from .webhook_sync import get_desired_webhook_url, sync_line_webhook, webhook_sync_worker


USER_VISIBLE_CITATION_RE = re.compile(
    r'(?:"{3}\s*)?\[cite:\s*[^\]]+\](?:\s*"{3})?',
    flags=re.IGNORECASE,
)


def sanitize_user_visible_response(text):
    cleaned = USER_VISIBLE_CITATION_RE.sub('', text or '')
    cleaned = re.sub(r'[ \t]+\n', '\n', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


class BotApplication:
    def __init__(self, logger):
        self.logger = logger
        # 讀兩次設定是為了先拿到 .env 路徑，再把 .env 內容灌回環境變數後重新組態。
        self.config = AppConfig.from_env()
        load_dotenv(self.config.env_file, self.logger)
        self.config = AppConfig.from_env()
        validate_environment(self.config, self.logger)

        self.app = Flask(__name__)
        self.state = RuntimeState()
        self.providers = ProviderService(self.config, self.state, self.logger)
        self.tool_registry = load_tool_registry()
        self.policy_engine = PolicyEngine()
        self.approval_gate = ApprovalGate()
        self.tool_executor = ToolExecutor(self.tool_registry, self.logger)
        self.sidecar_dispatcher = SidecarDispatcher(self.logger, config=self.config, tool_executor=self.tool_executor)
        self.line_bot_configuration = None
        self.handler = None
        if self.config.line_integration_enabled:
            # 只有 LINE 憑證齊全時才啟用 webhook handler，避免服務直接起不來。
            self.line_bot_configuration = Configuration(access_token=self.config.line_access_token)
            self.handler = WebhookHandler(self.config.line_channel_secret)
        else:
            self.logger.warning('LINE integration is disabled because credentials are missing')
        self._register_routes()
        if self.handler is not None:
            self._register_handlers()

    def run_startup_checks(self):
        self.logger.info('Starting environment checks...')
        self.state.startup_checks_completed = True
        self.state.startup_checks_passed = False
        self.state.last_startup_error = None
        try:
            self._run_preflight_checks()
            # Ollama 失敗時改成降級，不阻止整體服務啟動。
            if not check_ollama_service(self.config, self.logger):
                self.logger.warning('Ollama service check failed. The bot will continue with non-Ollama providers if available.')
            elif not check_ollama_model(self.config, self.logger, self.config.ollama_model_name):
                self.logger.warning(
                    'Ollama model check failed. The bot will continue with non-Ollama providers if available. Install with: ollama pull %s',
                    self.config.ollama_model_name
                )
            if not check_knowledge_file(self.config, self.logger):
                error_message = f'Knowledge file check failed. Please ensure {self.config.knowledge_file} exists and contains content.'
                self.logger.error(error_message)
                self.state.last_startup_error = error_message
                raise SystemExit(1)
            self.state.startup_checks_passed = True
            self.logger.info('All environment checks passed. Starting bot...')
        except SystemExit:
            if self.state.last_startup_error is None:
                self.state.last_startup_error = 'startup_checks_exited'
            raise
        except Exception as exc:
            self.state.last_startup_error = str(exc)[:200]
            self.logger.exception('Unexpected startup failure')
            raise

    def _run_preflight_checks(self):
        self.logger.info(
            'Preflight config host=%s port=%s line_enabled=%s model=%s knowledge_file=%s',
            self.config.flask_host,
            self.config.flask_port,
            self.config.line_integration_enabled,
            self.config.ollama_model_name,
            self.config.knowledge_file
        )
        self._ensure_port_is_available()

    def _ensure_port_is_available(self):
        listeners = self._find_port_listeners(self.config.flask_port)
        if not listeners:
            bind_error = self._get_bind_error()
            if bind_error is None:
                self.logger.info('Port preflight passed on %s:%s', self.config.flask_host, self.config.flask_port)
                return
            if isinstance(bind_error, PermissionError):
                self.logger.warning(
                    'Port bind probe skipped on %s:%s due to environment permission limits. No existing listener was detected.',
                    self.config.flask_host,
                    self.config.flask_port
                )
                return
            if bind_error.errno != errno.EADDRINUSE:
                self.logger.error(
                    'Port preflight failed on %s:%s: %s',
                    self.config.flask_host,
                    self.config.flask_port,
                    bind_error
                )
                raise SystemExit(1)
            self.logger.error(
                'Port %s appears occupied, but the listening process could not be identified.',
                self.config.flask_port
            )
            raise SystemExit(1)

        stale_bot_pids = [pid for pid in listeners if self._looks_like_stale_bot_process(pid)]
        foreign_pids = [pid for pid in listeners if pid not in stale_bot_pids]

        if foreign_pids:
            details = ', '.join(f'pid={pid} cmd="{self._read_cmdline(pid)}"' for pid in foreign_pids)
            self.logger.error('Port %s is occupied by another process: %s', self.config.flask_port, details)
            raise SystemExit(1)

        for pid in stale_bot_pids:
            self.logger.warning('Port %s is occupied by a stale xlx-bot process pid=%s. Terminating it.', self.config.flask_port, pid)
            self._terminate_process(pid)

        remaining = self._find_port_listeners(self.config.flask_port)
        if remaining:
            details = ', '.join(f'pid={pid} cmd="{self._read_cmdline(pid)}"' for pid in remaining)
            self.logger.error(
                'Port %s is still occupied after cleanup: %s',
                self.config.flask_port,
                details
            )
            raise SystemExit(1)

        self.logger.info('Port %s became available after stale-process cleanup', self.config.flask_port)

    def _get_bind_error(self):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.config.flask_host, self.config.flask_port))
            return None
        except OSError as exc:
            return exc
        finally:
            if sock is not None:
                sock.close()

    def _find_port_listeners(self, port):
        socket_inodes = self._read_listening_socket_inodes(port)
        if not socket_inodes:
            return []

        listeners = []
        for pid_name in os.listdir('/proc'):
            if not pid_name.isdigit():
                continue
            pid = int(pid_name)
            if pid == os.getpid():
                continue
            fd_dir = f'/proc/{pid}/fd'
            try:
                for fd_name in os.listdir(fd_dir):
                    fd_path = os.path.join(fd_dir, fd_name)
                    try:
                        target = os.readlink(fd_path)
                    except OSError:
                        continue
                    if not target.startswith('socket:['):
                        continue
                    inode = target[8:-1]
                    if inode in socket_inodes:
                        listeners.append(pid)
                        break
            except OSError:
                continue
        return sorted(set(listeners))

    def _read_listening_socket_inodes(self, port):
        inodes = set()
        for proc_file in ('/proc/net/tcp', '/proc/net/tcp6'):
            try:
                with open(proc_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[1:]
            except OSError:
                continue
            for line in lines:
                parts = line.split()
                if len(parts) < 10:
                    continue
                local_address = parts[1]
                state = parts[3]
                inode = parts[9]
                try:
                    _, port_hex = local_address.split(':')
                except ValueError:
                    continue
                if state == '0A' and int(port_hex, 16) == port:
                    inodes.add(inode)
        return inodes

    def _read_cmdline(self, pid):
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                raw = f.read().replace(b'\x00', b' ').decode('utf-8', errors='ignore').strip()
                return raw or '[unknown]'
        except OSError:
            return '[unreadable]'

    def _looks_like_stale_bot_process(self, pid):
        cmdline = self._read_cmdline(pid).lower()
        markers = ('xlx-bot', '/home/myclaw/xlx-bot', 'python3 main.py', 'python main.py', 'xlxbot.application')
        return any(marker in cmdline for marker in markers)

    def _terminate_process(self, pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError as exc:
            self.logger.error('Failed to terminate pid=%s: %s', pid, exc)
            raise SystemExit(1)

        deadline = time.time() + 5
        while time.time() < deadline:
            if not os.path.exists(f'/proc/{pid}'):
                return
            time.sleep(0.2)

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError as exc:
            self.logger.error('Failed to force kill pid=%s: %s', pid, exc)
            raise SystemExit(1)

        time.sleep(0.2)

    def _utcnow_iso(self):
        return datetime.datetime.now().isoformat()

    def _preview_text(self, text, max_chars=120):
        return (text or '').replace('\n', ' ')[:max_chars]

    def _mark_message_received(self, user_id, user_text):
        self.state.last_message_received_at = self._utcnow_iso()
        self.state.last_message_user_id = user_id or 'unknown'
        self.state.last_message_preview = self._preview_text(user_text)

    def _mark_message_replied(self):
        self.state.last_message_replied_at = self._utcnow_iso()
        self.state.last_message_failed_at = None
        self.state.last_message_error = None

    def _mark_message_failed(self, reason):
        self.state.last_message_failed_at = self._utcnow_iso()
        self.state.last_message_error = (reason or 'unknown_error')[:200]

    def _build_health_payload(self):
        provider_status = {
            name: self.providers.is_provider_available(name)
            for name in ('ollama', 'gemini', 'groq', 'xai', 'github')
        }
        formal_knowledge_files = get_formal_knowledge_files(self.config, self.logger)
        sidecar_ready, sidecar_missing = self.sidecar_dispatcher.is_ready()
        sidecar_phase = self.config.openclaw_phase if self.config.openclaw_phase in {'observe', 'suggest', 'assist'} else 'suggest'

        # 獲取最新的請求追蹤摘要
        current_request_summary = None
        if self.state.last_request_tracker:
            try:
                current_request_summary = self.state.last_request_tracker()
            except Exception:
                current_request_summary = None

        status = 'ok'
        reasons = []
        if self.state.last_startup_error:
            status = 'error'
            reasons.append('startup_error')
        elif not formal_knowledge_files:
            status = 'error'
            reasons.append('knowledge_missing')
        elif not self.config.line_integration_enabled or not any(provider_status.values()) or (self.config.sidecar_enabled and not sidecar_ready):
            status = 'degraded'
            if not self.config.line_integration_enabled:
                reasons.append('line_disabled')
            if not any(provider_status.values()):
                reasons.append('no_provider_available')
            if self.config.sidecar_enabled and not sidecar_ready:
                reasons.append('sidecar_not_ready')

        # 檢查最近錯誤是否影響健康狀態
        recent_critical_errors = [
            err for err in self.state.recent_errors[-10:]  # Last 10 errors
            if time.time() - err['timestamp'] < 300  # Within last 5 minutes
            and err['type'] in ['provider_chain_failed', 'unexpected_error']
        ]
        if recent_critical_errors:
            status = 'degraded'
            reasons.append('recent_critical_errors')

        return {
            'status': status,
            'reasons': reasons,
            'checks': {
                'startup_checks_completed': self.state.startup_checks_completed,
                'startup_checks_passed': self.state.startup_checks_passed,
                'line_integration_enabled': self.config.line_integration_enabled,
                'formal_knowledge_files': len(formal_knowledge_files),
                'providers': provider_status,
                'sidecar': {
                    'enabled': self.config.sidecar_enabled,
                    'mode': self.sidecar_dispatcher.mode,
                    'phase': sidecar_phase,
                    'ready': sidecar_ready,
                    'missing': sidecar_missing,
                },
                'webhook': {
                    'auto_update': self.config.line_webhook_auto_update,
                    'last_detected_ngrok_url': self.state.last_detected_ngrok_url,
                    'last_synced_webhook_url': self.state.last_synced_webhook_url,
                },
                'observability': {
                    'provider_health_status': self.state.provider_health_status,
                    'recent_errors_count': len(self.state.recent_errors),
                    'recent_critical_errors': len(recent_critical_errors),
                    'current_request_active': current_request_summary is not None,
                    'current_request_duration': current_request_summary.get('total_duration') if current_request_summary else None,
                },
            },
            'last_message': {
                'user_id': self.state.last_message_user_id,
                'preview': self.state.last_message_preview,
                'received_at': self.state.last_message_received_at,
                'replied_at': self.state.last_message_replied_at,
                'failed_at': self.state.last_message_failed_at,
                'error': self.state.last_message_error,
            },
            'current_request_summary': current_request_summary,
        }

    def _reply_to_line(self, reply_token, text):
        with ApiClient(self.line_bot_configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=text)]
                )
            )

    def _register_routes(self):
        @self.app.route('/health', methods=['GET'])
        def health_check():
            payload = self._build_health_payload()
            http_status = 200 if payload['status'] != 'error' else 503
            return jsonify(payload), http_status

        @self.app.route('/sync-webhook', methods=['POST'])
        def sync_webhook():
            # 手動同步 webhook 前先驗證保護 token，避免外部任意觸發。
            if not self.config.webhook_sync_token or request.headers.get('X-Webhook-Sync-Token', '') != self.config.webhook_sync_token:
                return jsonify({'error': 'forbidden'}), 403
            updated = sync_line_webhook(self.config, self.state, self.logger, force=True)
            desired_url = get_desired_webhook_url(self.config, self.state, self.logger)
            return jsonify({'updated': updated, 'webhook_url': desired_url})

        @self.app.route('/v1/sidecar/dispatch', methods=['POST'])
        def openclaw_sidecar_dispatch():
            payload = request.get_json(silent=True) or {}
            user_input = str(payload.get('user_input') or '')
            task_type = str(payload.get('task_type') or 'lookup')
            intent = str(payload.get('intent') or 'unknown')
            trace_id = str(payload.get('trace_id') or '')

            if not user_input.strip():
                return jsonify({
                    'status': 'failed',
                    'task_type': task_type,
                    'confidence': 0.0,
                    'outputs': [],
                    'risk_level': 'low',
                    'requires_approval': False,
                    'audit_ref': trace_id or 'local-openclaw',
                    'error': 'empty_user_input',
                }), 400

            outputs = self._build_local_openclaw_outputs(user_input, task_type, intent)
            is_lookup = task_type in {'lookup', 'analyze'}
            status = 'ok' if outputs else 'degraded'

            return jsonify({
                'status': status,
                'task_type': task_type,
                'confidence': getattr(self.config, 'openclaw_confidence_ok', 0.84) if outputs else getattr(self.config, 'openclaw_confidence_degraded', 0.2),
                'outputs': outputs,
                'risk_level': 'low' if is_lookup else 'medium',
                'requires_approval': False if is_lookup else True,
                'audit_ref': self._build_openclaw_audit_ref(trace_id),
                'error': '' if outputs else 'no_official_source_result',
            })

        @self.app.route('/v1/openclaw/health', methods=['GET'])
        def openclaw_health_check():
            sidecar_ready, sidecar_missing = self.sidecar_dispatcher.is_ready()
            return jsonify({
                'status': 'ok' if sidecar_ready else 'degraded',
                'gateway': 'local-openclaw',
                'mode': self.sidecar_dispatcher.mode,
                'phase': self.config.openclaw_phase,
                'dispatch_path': self.config.openclaw_endpoint_path,
                'health_path': getattr(self.config, 'openclaw_health_path', '/v1/openclaw/health'),
                'timeout_seconds': self.config.sidecar_timeout_seconds,
                'max_outputs': getattr(self.config, 'openclaw_max_outputs', 5),
                'confidence_ok': getattr(self.config, 'openclaw_confidence_ok', 0.84),
                'confidence_degraded': getattr(self.config, 'openclaw_confidence_degraded', 0.2),
                'audit_enabled': getattr(self.config, 'openclaw_audit_enabled', True),
                'learning_enabled': getattr(self.config, 'openclaw_learning_enabled', True),
                'official_sources': getattr(self.config, 'openclaw_official_sources', []),
                'ready': sidecar_ready,
                'missing': sidecar_missing,
            }), 200 if sidecar_ready else 503

        @self.app.route('/callback', methods=['POST'])
        def callback():
            if self.handler is None:
                self.logger.warning('LINE callback received while LINE integration is disabled')
                return jsonify({'error': 'line integration disabled'}), 503
            # LINE webhook 需要用簽章驗證請求是否真的來自 LINE。
            signature = request.headers.get('X-Line-Signature', '')
            body = request.get_data(as_text=True)
            self.logger.debug('Received LINE webhook body_length=%s signature_present=%s', len(body), bool(signature))
            try:
                self.handler.handle(body, signature)
            except InvalidSignatureError:
                self.logger.warning('Invalid LINE signature')
                abort(400)
            except Exception:
                self.logger.exception('Failed to handle LINE request')
                abort(500)
            return 'OK'

    def _build_local_openclaw_outputs(self, user_input, task_type, intent):
        outputs = []
        try:
            if task_type in {'lookup', 'analyze'}:
                course_info = self.providers.query_course_info(user_input)
                if course_info:
                    outputs.append(f'官方課表/課程查核：\n{course_info}')

                news_info = self.providers.query_latest_news(user_input)
                if news_info:
                    outputs.append(f'官方公告/文宣查核：\n{news_info}')

                site_info = self.providers.query_official_site_map(user_input, intent)
                if site_info:
                    outputs.append(f'官方網站查核：\n{site_info}')

                if not outputs:
                    outputs.append(
                        '已完成本地 OpenClaw 查核流程，但目前未從已核可官方來源取得足夠資料；'
                        '請回到保守回答，明確說明本地與官方查核都不足。'
                    )
                return outputs[:getattr(self.config, 'openclaw_max_outputs', 5)]

            outputs.extend([
                '先拆解使用者真正要解決的問題、交付物與限制。',
                '先用本地知識確認事實；若本地不足，改用 OpenClaw 官方查核結果補足。',
                '用成熟台北市健言社前輩與老師的口吻，給短答、依據、風險提醒與下一步。',
            ])
            return outputs
        except Exception as exc:
            self.logger.warning('Local OpenClaw dispatch failed: %s', exc)
            return []

    def _build_openclaw_audit_ref(self, trace_id):
        if not getattr(self.config, 'openclaw_audit_enabled', True):
            return trace_id or 'local-openclaw-audit-disabled'
        return trace_id or f'local-openclaw-{int(time.time())}'

    def _register_handlers(self):
        @self.handler.add(MessageEvent, message=TextMessageContent)
        def handle_message(event):
            def process_message():
                user_text = event.message.text
                user_id = getattr(event.source, 'user_id', None)
                self.logger.info('Received text message from user_id=%s text=%s', user_id, user_text)
                self._mark_message_received(user_id, user_text)

                try:
                    # 每位使用者保留一段簡短對話歷史，提供後續回答上下文。
                    if user_id not in self.state.conversation_history:
                        self.state.conversation_history[user_id] = []
                    history = self.state.conversation_history[user_id]

                    if detect_user_correction(user_text):
                        correction_decision = self.policy_engine.evaluate(
                            intent='user_feedback',
                            action='capture_correction',
                            risk='low',
                        )
                        correction_approval = self.approval_gate.decide(correction_decision)
                        append_learning_event(
                            self.config,
                            self.logger,
                            event_type='USER_CORRECTION',
                            user_id=user_id,
                            user_input=user_text,
                            details={'category': 'user_feedback'},
                            intent='user_feedback',
                            action='capture_correction',
                            risk='low',
                            approval='required' if correction_approval.requires_approval else 'not_required',
                            fallback=correction_approval.fallback,
                        )

                    lessons_guidance = load_pre_answer_lessons(self.config, self.logger)
                    ai_response = ask_ai(
                        self.config,
                        self.state,
                        self.logger,
                        self.providers,
                        user_text,
                        history,
                        dispatcher=self.sidecar_dispatcher,
                        lessons_guidance=lessons_guidance,
                        tool_registry=self.tool_registry,
                        policy_engine=self.policy_engine,
                        approval_gate=self.approval_gate,
                    )

                    # 記錄請求追蹤摘要到狀態
                    if self.state.last_request_tracker:
                        try:
                            tracker_summary = self.state.last_request_tracker()
                            if tracker_summary.get('errors_count', 0) > 0:
                                self.state.add_recent_error(
                                    'request_processing_error',
                                    f'Request had {tracker_summary["errors_count"]} errors',
                                    {'request_id': tracker_summary.get('request_id'), 'errors': tracker_summary.get('errors')}
                                )
                        except Exception as e:
                            self.logger.warning('Failed to record request tracker: %s', e)

                    if self.state.last_tool_decision:
                        append_learning_event(
                            self.config,
                            self.logger,
                            event_type='TOOL_DECISION',
                            user_id=user_id,
                            user_input=user_text,
                            details=self.state.last_tool_decision,
                            intent=self.state.last_tool_decision.get('task_type', 'unknown'),
                            action=self.state.last_tool_decision.get('tool_name', 'unknown'),
                            risk=self.state.last_tool_decision.get('risk', 'unknown'),
                            approval='required' if self.state.last_tool_decision.get('requires_approval') else 'not_required',
                            fallback=self.state.last_tool_decision.get('fallback', 'none'),
                        )
                    if self.state.last_agent_decision:
                        append_learning_event(
                            self.config,
                            self.logger,
                            event_type='AGENT_DECISION',
                            user_id=user_id,
                            user_input=user_text,
                            details=self.state.last_agent_decision,
                            intent=self.state.last_agent_decision.get('intent', 'unknown'),
                            action=self.state.last_agent_decision.get('action', 'unknown'),
                            risk='medium' if self.state.last_agent_decision.get('action') == 'execute' else 'low',
                            approval='required' if self.state.last_agent_decision.get('action') == 'execute' else 'not_required',
                            fallback=self.state.last_agent_decision.get('dispatch_reason', 'none'),
                        )
                    if self.state.last_sidecar_decision:
                        append_learning_event(
                            self.config,
                            self.logger,
                            event_type='SIDECAR_DECISION',
                            user_id=user_id,
                            user_input=user_text,
                            details=self.state.last_sidecar_decision,
                            intent=self.state.last_sidecar_decision.get('task_type', 'unknown'),
                            action='sidecar_dispatch',
                            risk='medium',
                            approval='required' if self.state.last_sidecar_decision.get('requires_approval') else 'not_required',
                            fallback=self.state.last_sidecar_decision.get('fallback', self.state.last_sidecar_decision.get('reason', 'none')),
                        )
                        if self.state.last_sidecar_decision.get('learnable'):
                            audit_ref = self.state.last_sidecar_decision.get('audit_ref') or 'unknown'
                            for item in self.state.last_sidecar_decision.get('outputs', []):
                                fact = str(item).strip()
                                if not fact:
                                    continue
                                append_pending_knowledge(
                                    self.config,
                                    self.logger,
                                    fact,
                                    source=f'openclaw:{audit_ref}',
                                    user_id=user_id,
                                )
                                append_learning_event(
                                    self.config,
                                    self.logger,
                                    event_type='OPENCLAW_LEARNING_CAPTURED',
                                    user_id=user_id,
                                    user_input=user_text,
                                    details={
                                        'category': 'openclaw_pending_review',
                                        'audit_ref': audit_ref,
                                        'fact': fact[:200],
                                    },
                                    intent=self.state.last_sidecar_decision.get('task_type', 'unknown'),
                                    action='capture_openclaw_lookup_result',
                                    risk='low',
                                    approval='not_required',
                                    fallback='pending_review',
                                )

                    learned_matches = parse_learned_tags(ai_response)
                    if learned_matches:
                        for match in learned_matches:
                            fact = match.strip()
                            if not fact:
                                continue
                            append_pending_knowledge(self.config, self.logger, fact, user_id=user_id)
                            append_learning_event(
                                self.config,
                                self.logger,
                                event_type='PENDING_KNOWLEDGE_CAPTURED',
                                user_id=user_id,
                                user_input=user_text,
                                details={'category': 'pending_review', 'fact': fact[:200]}
                            )
                            self.logger.info('Saved pending-review knowledge: %s', fact)
                        ai_response = re.sub(r'<LEARNED>.*?</LEARNED>', '', ai_response, flags=re.IGNORECASE | re.DOTALL).strip()

                    sanitized_response = sanitize_user_visible_response(ai_response)
                    if sanitized_response != ai_response:
                        self.logger.info('Removed internal citation markers from user-visible response')
                        ai_response = sanitized_response

                    if '資料不足' in ai_response or '查不到' in ai_response:
                        insufficient_decision = self.policy_engine.evaluate(
                            intent='qa_response',
                            action='answer_with_insufficient_data',
                            risk='low',
                        )
                        insufficient_approval = self.approval_gate.decide(insufficient_decision)
                        append_learning_event(
                            self.config,
                            self.logger,
                            event_type='ANSWER_WITH_INSUFFICIENT_DATA',
                            user_id=user_id,
                            user_input=user_text,
                            bot_response=ai_response,
                            details={'category': 'insufficient_data'},
                            intent='qa_response',
                            action='answer_with_insufficient_data',
                            risk='low',
                            approval='required' if insufficient_approval.requires_approval else 'not_required',
                            fallback=insufficient_approval.fallback,
                        )
                    elif '無法連線到任何 AI 服務' in ai_response:
                        failure_decision = self.policy_engine.evaluate(
                            intent='provider_runtime',
                            action='provider_chain_failed',
                            risk='medium',
                        )
                        failure_approval = self.approval_gate.decide(failure_decision)
                        append_learning_event(
                            self.config,
                            self.logger,
                            event_type='ANSWER_FAILURE',
                            user_id=user_id,
                            user_input=user_text,
                            bot_response=ai_response,
                            details={'reason': 'provider_chain_failed'},
                            intent='provider_runtime',
                            action='provider_chain_failed',
                            risk='medium',
                            approval='required' if failure_approval.requires_approval else 'not_required',
                            fallback=failure_approval.fallback,
                        )
                        # 記錄 provider 鏈失敗到狀態
                        self.state.add_recent_error('provider_chain_failed', 'All providers failed', {'user_input': user_text[:100]})

                    self.logger.info('Replying to LINE user_id=%s response_length=%s', user_id, len(ai_response))
                    history.append((user_text, ai_response))
                    if len(history) > self.state.max_history_length:
                        history.pop(0)

                    # 每次互動都寫入每日記憶檔，後續可再彙整成長期記憶。
                    append_memory_entry(self.config, self.logger, self.providers.ask_ollama, user_id, user_text, ai_response)
                    append_learning_event(
                        self.config,
                        self.logger,
                        event_type='ANSWER_SENT',
                        user_id=user_id,
                        user_input=user_text,
                        bot_response=ai_response,
                        intent='qa_response',
                        action='answer_sent',
                        risk='low',
                        approval='not_required',
                        fallback='none',
                    )
                    rebuild_lessons_and_troubleshooting(self.config, self.logger)

                    try:
                        self._reply_to_line(event.reply_token, ai_response)
                        self._mark_message_replied()
                    except Exception as e:
                        self._mark_message_failed(f'send_line_reply_failed:{str(e)[:180]}')
                        send_error_decision = self.policy_engine.evaluate(
                            intent='line_delivery',
                            action='send_line_reply',
                            risk='medium',
                        )
                        send_error_approval = self.approval_gate.decide(send_error_decision)
                        append_learning_event(
                            self.config,
                            self.logger,
                            event_type='SYSTEM_ERROR',
                            user_id=user_id,
                            user_input=user_text,
                            bot_response=ai_response,
                            details={'error_type': 'send_line_reply_failed', 'reason': str(e)[:200]},
                            intent='line_delivery',
                            action='send_line_reply',
                            risk='medium',
                            approval='required' if send_error_approval.requires_approval else 'not_required',
                            fallback=send_error_approval.fallback,
                        )
                        self.logger.exception('Failed to send LINE reply')
                except Exception as e:
                    self._mark_message_failed(f'process_message_failed:{str(e)[:180]}')
                    self.state.add_recent_error('process_message_failed', str(e), {'user_input': user_text[:100]})
                    append_learning_event(
                        self.config,
                        self.logger,
                        event_type='SYSTEM_ERROR',
                        user_id=user_id,
                        user_input=user_text,
                        details={'error_type': 'process_message_failed', 'reason': str(e)[:200]},
                        intent='message_runtime',
                        action='process_message',
                        risk='medium',
                        approval='not_required',
                        fallback='reply_with_safe_error',
                    )
                    self.logger.exception('Unhandled exception while processing LINE message')
                    safe_reply = '小龍蝦目前處理訊息時發生錯誤，請稍後再試。'
                    try:
                        self._reply_to_line(event.reply_token, safe_reply)
                    except Exception:
                        self.logger.exception('Failed to send safe fallback LINE reply')

            # LINE webhook 應盡快回 200，實際 AI 處理改到背景執行。
            thread = threading.Thread(target=process_message, daemon=True)
            thread.start()

    def run(self):
        self.run_startup_checks()
        if self.config.line_integration_enabled and self.config.line_webhook_auto_update:
            # webhook 自動同步獨立成背景執行緒，避免阻塞主服務啟動。
            threading.Thread(
                target=webhook_sync_worker,
                args=(self.config, self.state, self.logger),
                daemon=True
            ).start()
            self.logger.info('LINE webhook auto-sync is enabled')
        elif self.config.line_webhook_auto_update:
            self.logger.warning('LINE webhook auto-sync skipped because LINE integration is disabled')

        self.logger.info('Starting Flask app on %s:%s', self.config.flask_host, self.config.flask_port)
        self.app.run(host=self.config.flask_host, port=self.config.flask_port)
