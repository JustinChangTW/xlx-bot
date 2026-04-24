import os
from dataclasses import dataclass


def load_dotenv(path, logger):
    # 用最簡單的方式讀 .env，避免額外依賴 python-dotenv。
    if not os.path.exists(path):
        logger.warning('.env file not found: %s', path)
        return {}

    loaded = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if not key or key in os.environ:
                    continue
                os.environ[key] = value
                loaded[key] = value
    except Exception:
        logger.exception('Failed to read .env file: %s', path)
        return {}

    logger.info('Loaded %s env vars from %s', len(loaded), path)
    return loaded


@dataclass
class AppConfig:
    log_file: str
    env_file: str
    log_level: str
    log_max_bytes: int
    log_backup_count: int
    line_access_token: str
    line_channel_secret: str
    line_api_base_url: str
    ollama_api_url: str
    ollama_model_name: str
    knowledge_file: str
    gemini_api_key: str
    llm_chain: list[str]
    router_model_name: str
    router_enabled: bool
    groq_api_key: str
    groq_api_url: str
    groq_model_name: str
    xai_api_key: str
    xai_api_url: str
    xai_model_name: str
    github_models_token: str
    github_models_api_url: str
    github_models_api_version: str
    github_models_name: str
    public_base_url: str
    line_webhook_path: str
    line_webhook_auto_update: bool
    webhook_sync_interval_seconds: int
    webhook_sync_startup_delay_seconds: int
    line_webhook_test_enabled: bool
    ngrok_api_url: str
    webhook_sync_token: str
    memory_dir: str
    soul_file: str
    agents_file: str
    user_file: str
    long_term_memory_file: str
    daily_memory_lookback_days: int
    max_memory_file_chars: int
    memory_summarize_enabled: bool
    flask_host: str
    flask_port: int
    sidecar_enabled: bool
    sidecar_mode: str
    sidecar_timeout_seconds: int
    openclaw_base_url: str
    openclaw_endpoint_path: str
    openclaw_api_key: str
    required_env_vars: tuple[str, ...] = ('LINE_ACCESS_TOKEN', 'LINE_CHANNEL_SECRET')

    @property
    def line_integration_enabled(self) -> bool:
        # LINE 功能是否可用，取決於 access token 與 channel secret 是否都存在。
        return bool(self.line_access_token and self.line_channel_secret)

    @classmethod
    def from_env(cls):
        # 統一在這裡收斂所有環境變數，避免其他模組各自讀 env。
        ollama_model_name = os.getenv('OLLAMA_MODEL_NAME', 'qwen2:0.5b')
        return cls(
            log_file=os.getenv('LOG_FILE', 'xlx-bot.log'),
            env_file=os.getenv('ENV_FILE', '.env'),
            log_level=os.getenv('LOG_LEVEL', 'INFO').upper(),
            log_max_bytes=int(os.getenv('LOG_MAX_BYTES', str(256 * 1024))),
            log_backup_count=int(os.getenv('LOG_BACKUP_COUNT', '2')),
            line_access_token=os.getenv('LINE_ACCESS_TOKEN', ''),
            line_channel_secret=os.getenv('LINE_CHANNEL_SECRET', ''),
            line_api_base_url='https://api.line.me/v2/bot/channel/webhook',
            ollama_api_url=os.getenv('OLLAMA_API_URL', 'http://127.0.0.1:11434/api/generate'),
            ollama_model_name=ollama_model_name,
            knowledge_file=os.getenv('KNOWLEDGE_FILE', 'knowledge.txt'),
            gemini_api_key=os.getenv('GEMINI_API_KEY', ''),
            llm_chain=os.getenv('LLM_CHAIN', 'ollama,gemini').split(','),
            router_model_name=os.getenv('ROUTER_MODEL_NAME', ollama_model_name),
            router_enabled=os.getenv('ROUTER_ENABLED', 'true').lower() in ('1', 'true', 'yes'),
            groq_api_key=os.getenv('GROQ_API_KEY', '').strip(),
            groq_api_url=os.getenv('GROQ_API_URL', 'https://api.groq.com/openai/v1/chat/completions').strip(),
            groq_model_name=os.getenv('GROQ_MODEL_NAME', '').strip(),
            xai_api_key=os.getenv('XAI_API_KEY', '').strip(),
            xai_api_url=os.getenv('XAI_API_URL', 'https://api.x.ai/v1/responses').strip(),
            xai_model_name=os.getenv('XAI_MODEL_NAME', 'grok-4.20-reasoning').strip(),
            github_models_token=os.getenv('GITHUB_MODELS_TOKEN', '').strip(),
            github_models_api_url=os.getenv('GITHUB_MODELS_API_URL', 'https://models.github.ai/inference/chat/completions').strip(),
            github_models_api_version=os.getenv('GITHUB_MODELS_API_VERSION', '2026-03-10').strip(),
            github_models_name=os.getenv('GITHUB_MODELS_NAME', 'openai/gpt-4o').strip(),
            public_base_url=os.getenv('PUBLIC_BASE_URL', '').strip().rstrip('/'),
            line_webhook_path=os.getenv('LINE_WEBHOOK_PATH', '/callback').strip() or '/callback',
            line_webhook_auto_update=os.getenv('LINE_WEBHOOK_AUTO_UPDATE', 'true').lower() in ('1', 'true', 'yes'),
            webhook_sync_interval_seconds=int(os.getenv('WEBHOOK_SYNC_INTERVAL_SECONDS', '30')),
            webhook_sync_startup_delay_seconds=int(os.getenv('WEBHOOK_SYNC_STARTUP_DELAY_SECONDS', '5')),
            line_webhook_test_enabled=os.getenv('LINE_WEBHOOK_TEST_ENABLED', 'true').lower() in ('1', 'true', 'yes'),
            ngrok_api_url=os.getenv('NGROK_API_URL', '').strip(),
            webhook_sync_token=os.getenv('WEBHOOK_SYNC_TOKEN', '').strip(),
            memory_dir=os.getenv('MEMORY_DIR', 'memory'),
            soul_file=os.getenv('SOUL_FILE', 'SOUL.md'),
            agents_file=os.getenv('AGENTS_FILE', 'AGENTS.md'),
            user_file=os.getenv('USER_FILE', 'USER.md'),
            long_term_memory_file=os.getenv('LONG_TERM_MEMORY_FILE', 'memory.md'),
            daily_memory_lookback_days=int(os.getenv('DAILY_MEMORY_LOOKBACK_DAYS', '2')),
            max_memory_file_chars=int(os.getenv('MAX_MEMORY_FILE_CHARS', '20000')),
            memory_summarize_enabled=os.getenv('MEMORY_SUMMARIZE_ENABLED', 'true').lower() in ('1', 'true', 'yes'),
            flask_host=os.getenv('FLASK_HOST', '0.0.0.0'),
            flask_port=int(os.getenv('FLASK_PORT', '8080')),
            sidecar_enabled=os.getenv('SIDECAR_ENABLED', 'false').lower() in ('1', 'true', 'yes'),
            sidecar_mode=os.getenv('SIDECAR_MODE', 'mock').strip() or 'mock',
            sidecar_timeout_seconds=int(os.getenv('SIDECAR_TIMEOUT_SECONDS', '8')),
            openclaw_base_url=os.getenv('OPENCLAW_BASE_URL', '').strip().rstrip('/'),
            openclaw_endpoint_path=os.getenv('OPENCLAW_ENDPOINT_PATH', '/v1/sidecar/dispatch').strip() or '/v1/sidecar/dispatch',
            openclaw_api_key=os.getenv('OPENCLAW_API_KEY', '').strip(),
        )


def validate_environment(config, logger):
    # LINE 憑證改成可降級的警告，不再讓整體服務因此無法啟動。
    missing = [name for name in config.required_env_vars if not os.getenv(name)]
    if missing:
        logger.warning('Missing optional LINE environment variables: %s', missing)
        if not os.path.exists(config.env_file):
            logger.warning('Expected .env file at %s', config.env_file)
        logger.warning('LINE webhook features will be disabled until these variables are set in %s.', config.env_file)
