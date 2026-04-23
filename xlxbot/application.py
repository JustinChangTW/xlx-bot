import errno
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
from .knowledge import append_memory_entry, check_knowledge_file
from .learning import (
    append_learning_event,
    append_pending_knowledge,
    detect_user_correction,
    load_pre_answer_lessons,
    parse_learned_tags,
    rebuild_lessons_and_troubleshooting,
)
from .providers import ProviderService, check_ollama_model, check_ollama_service
from .router import ask_ai
from .runtime import RuntimeState
from .sidecar import SidecarDispatcher
from .webhook_sync import get_desired_webhook_url, sync_line_webhook, webhook_sync_worker


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
        self.sidecar_dispatcher = SidecarDispatcher(self.logger)
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
            self.logger.error('Knowledge file check failed. Please ensure %s exists and contains content.', self.config.knowledge_file)
            raise SystemExit(1)
        self.logger.info('All environment checks passed. Starting bot...')

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

    def _register_routes(self):
        @self.app.route('/health', methods=['GET'])
        def health_check():
            return jsonify({'status': 'ok'})

        @self.app.route('/sync-webhook', methods=['POST'])
        def sync_webhook():
            # 手動同步 webhook 前先驗證保護 token，避免外部任意觸發。
            if not self.config.webhook_sync_token or request.headers.get('X-Webhook-Sync-Token', '') != self.config.webhook_sync_token:
                return jsonify({'error': 'forbidden'}), 403
            updated = sync_line_webhook(self.config, self.state, self.logger, force=True)
            desired_url = get_desired_webhook_url(self.config, self.state, self.logger)
            return jsonify({'updated': updated, 'webhook_url': desired_url})

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

    def _register_handlers(self):
        @self.handler.add(MessageEvent, message=TextMessageContent)
        def handle_message(event):
            def process_message():
                user_text = event.message.text
                user_id = getattr(event.source, 'user_id', None)
                self.logger.info('Received text message from user_id=%s text=%s', user_id, user_text)

                # 每位使用者保留一段簡短對話歷史，提供後續回答上下文。
                if user_id not in self.state.conversation_history:
                    self.state.conversation_history[user_id] = []
                history = self.state.conversation_history[user_id]

                if detect_user_correction(user_text):
                    append_learning_event(
                        self.config,
                        self.logger,
                        event_type='USER_CORRECTION',
                        user_id=user_id,
                        user_input=user_text,
                        details={'category': 'user_feedback'}
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
                    lessons_guidance=lessons_guidance
                )
                if self.state.last_agent_decision:
                    append_learning_event(
                        self.config,
                        self.logger,
                        event_type='AGENT_DECISION',
                        user_id=user_id,
                        user_input=user_text,
                        details=self.state.last_agent_decision
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

                if '資料不足' in ai_response or '查不到' in ai_response:
                    append_learning_event(
                        self.config,
                        self.logger,
                        event_type='ANSWER_WITH_INSUFFICIENT_DATA',
                        user_id=user_id,
                        user_input=user_text,
                        bot_response=ai_response,
                        details={'category': 'insufficient_data'}
                    )
                elif '無法連線到任何 AI 服務' in ai_response:
                    append_learning_event(
                        self.config,
                        self.logger,
                        event_type='ANSWER_FAILURE',
                        user_id=user_id,
                        user_input=user_text,
                        bot_response=ai_response,
                        details={'reason': 'provider_chain_failed'}
                    )

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
                    bot_response=ai_response
                )
                rebuild_lessons_and_troubleshooting(self.config, self.logger)

                try:
                    with ApiClient(self.line_bot_configuration) as api_client:
                        line_bot_api = MessagingApi(api_client)
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[TextMessage(text=ai_response)]
                            )
                        )
                except Exception as e:
                    append_learning_event(
                        self.config,
                        self.logger,
                        event_type='SYSTEM_ERROR',
                        user_id=user_id,
                        user_input=user_text,
                        bot_response=ai_response,
                        details={'error_type': 'send_line_reply_failed', 'reason': str(e)[:200]}
                    )
                    self.logger.exception('Failed to send LINE reply')

            # LINE webhook 應盡快回 200，實際 AI 處理改到背景執行。
            thread = threading.Thread(target=process_message)
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
