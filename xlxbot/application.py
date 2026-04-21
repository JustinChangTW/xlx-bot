import datetime
import re
import threading

from flask import Flask, abort, jsonify, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from .config import AppConfig, load_dotenv, validate_environment
from .knowledge import append_memory_entry, check_knowledge_file
from .providers import ProviderService, check_ollama_model, check_ollama_service
from .router import ask_ai
from .runtime import RuntimeState
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
            self.logger.info('Received LINE webhook body=%s signature=%s', body[:200], signature)
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

                ai_response = ask_ai(self.config, self.state, self.logger, self.providers, user_text, history)
                learned_matches = re.findall(r'<LEARNED>(.*?)</LEARNED>', ai_response, re.IGNORECASE | re.DOTALL)
                if learned_matches:
                    try:
                        # 模型可主動把值得記住的新知識包在 <LEARNED> 標籤中，這裡會抽出後落盤。
                        with open('learned_knowledge.txt', 'a', encoding='utf-8') as f:
                            for match in learned_matches:
                                fact = match.strip()
                                if fact:
                                    f.write(f"- {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}: {fact}\n")
                                    self.logger.info('Saved new knowledge: %s', fact)
                        ai_response = re.sub(r'<LEARNED>.*?</LEARNED>', '', ai_response, flags=re.IGNORECASE | re.DOTALL).strip()
                    except Exception as e:
                        self.logger.error('Failed to save learned knowledge: %s', e)

                self.logger.info('Replying to LINE user_id=%s response_length=%s', user_id, len(ai_response))
                history.append((user_text, ai_response))
                if len(history) > self.state.max_history_length:
                    history.pop(0)

                # 每次互動都寫入每日記憶檔，後續可再彙整成長期記憶。
                append_memory_entry(self.config, self.logger, self.providers.ask_ollama, user_id, user_text, ai_response)

                try:
                    with ApiClient(self.line_bot_configuration) as api_client:
                        line_bot_api = MessagingApi(api_client)
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[TextMessage(text=ai_response)]
                            )
                        )
                except Exception:
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
