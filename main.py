import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import traceback
import subprocess
import datetime
import re
import threading
from flask import Flask, request, abort, jsonify
from urllib.parse import urlparse, urlunparse
import requests
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# 嘗試載入 Google Gemini 的 Python SDK，如果沒有安裝則後續會跳過 Gemini
try:
    from google import genai
    from google.genai import types as genai_types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

# 嘗試載入 BeautifulSoup，用於解析網頁
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# 建立 Flask 應用
app = Flask(__name__)

# 日誌、.env 檔案和必要環境變數設定
LOG_FILE = os.getenv('LOG_FILE', 'xlx-bot.log')
ENV_FILE = os.getenv('ENV_FILE', '.env')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', str(1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', '3'))
REQUIRED_ENV_VARS = ['LINE_ACCESS_TOKEN', 'LINE_CHANNEL_SECRET']
LINE_API_BASE_URL = 'https://api.line.me/v2/bot/channel/webhook'

log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding='utf-8'
)
file_handler.setFormatter(log_formatter)

root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
root_logger.handlers.clear()
root_logger.addHandler(stream_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

# 讀取 .env 檔案的輔助函式，將環境變數載入 os.environ
# 這裡只會載入尚未存在於環境中的變數，避免覆寫現有設定

def load_dotenv(path):
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

# 驗證必要的環境變數是否已設定，若缺少則停止程式

def validate_environment():
    load_dotenv(ENV_FILE)
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        logger.error('Missing required environment variables: %s', missing)
        if not os.path.exists(ENV_FILE):
            logger.error('Expected .env file at %s', ENV_FILE)
        logger.error('Please set these variables in the environment or in %s before running.', ENV_FILE)
        raise RuntimeError('Missing required environment variables')


# 下面是 Ollama 相關的檢查流程，用來確保本地模型服務可用並且所需模型已就緒

def check_ollama_service():
    """檢查 Ollama 服務是否可用"""
    # 從 OLLAMA_API_URL 解析出主機位置，使其在 Docker 環境中也能正常運作
    try:
        parsed_url = urlparse(OLLAMA_API_URL)
        base_url = urlunparse((parsed_url.scheme, parsed_url.netloc, '/', '', '', ''))
        response = requests.get(base_url, timeout=5)
        if response.status_code == 200:
            logger.info('Ollama service is running at %s', base_url)
            return True
        else:
            logger.error('Ollama service at %s returned status %s', base_url, response.status_code)
            return False
    except requests.RequestException as e:
        logger.error('Cannot connect to Ollama service at %s: %s', OLLAMA_API_URL, e)
        return False

# 檢查指定模型能否在 Ollama 中執行，若沒有則嘗試自動下載

def check_ollama_model(model_name):
    """檢查指定的 Ollama 模型是否存在"""
    # 使用 /api/show 端點來檢查模型是否存在，這是更可靠的方法
    # 並且移除在機器人容器內執行 ollama pull 的不可行邏輯
    try:
        parsed_url = urlparse(OLLAMA_API_URL)
        check_url = urlunparse((parsed_url.scheme, parsed_url.netloc, '/api/show', '', '', ''))
        response = requests.post(
            check_url,
            json={'name': model_name},
            timeout=10
        )
        if response.status_code == 200:
            logger.info('Ollama model %s is available', model_name)
            return True
        elif response.status_code == 404:
            logger.error('Ollama model "%s" not found on the Ollama server.', model_name)
            logger.error('Please pull the model on the Ollama server machine, e.g., `docker exec -it ollama-server ollama pull %s`', model_name)
            return False
        else:
            logger.error('Ollama model %s check failed with status %s. Response: %s', model_name, response.status_code, response.text[:200])
            return False
    except requests.RequestException as e:
        logger.error('Cannot check Ollama model %s: %s', model_name, e)
        return False


# 載入知識庫文件，將多個來源合併成一個 prompt 內容
# 這樣在構建問題時就能一起參考課程、記憶、核心指令與社團資料
def load_knowledge_base():
    """載入所有知識庫文件"""
    ensure_memory_dirs()
    kb_files = get_knowledge_files()
    all_content = []

    for kb_file in kb_files:
        content = read_text_file(kb_file, max_chars=15000 if kb_file.startswith(MEMORY_DIR) or 'memory' in kb_file else None)
        if content:
            all_content.append(f"--- 來自 {kb_file} ---\n{content}")
            logger.info('Loaded knowledge file: %s (%d chars)', kb_file, len(content))
        elif os.path.exists(kb_file):
            # get_knowledge_files 確保了檔案存在，這裡只處理空檔案的情況
            logger.warning('Knowledge file %s is empty', kb_file)

    if not all_content:
        logger.error('No knowledge files with content were loaded!')
        return None

    combined = '\n\n'.join(all_content)
    logger.info('Total knowledge base size: %d chars', len(combined))
    return combined

# 檔案記憶支持的輔助函式

def ensure_memory_dirs():
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        logger.info('Memory directory ready: %s', MEMORY_DIR)
    except Exception as e:
        logger.error('Cannot create memory directory %s: %s', MEMORY_DIR, e)


def get_daily_memory_path(days_ago=0):
    date_str = (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()
    return os.path.join(MEMORY_DIR, f'{date_str}.md')


def read_text_file(file_path, max_chars=None):
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return None

            if max_chars and len(content) > max_chars:
                logger.info('Truncating %s to last %s chars for prompt', file_path, max_chars)
                return content[-max_chars:]

            return content
    except Exception as e:
        logger.error('Cannot read file %s: %s', file_path, e)
        return None


def refresh_memory_if_needed():
    if not MEMORY_SUMMARIZE_ENABLED:
        return

    daily_path = get_daily_memory_path(0)
    if not os.path.exists(daily_path):
        return

    try:
        file_size = os.path.getsize(daily_path)
        if file_size < MAX_MEMORY_FILE_CHARS:
            return

        logger.info('Daily memory size %s exceeds threshold %s, summarizing to %s', file_size, MAX_MEMORY_FILE_CHARS, LONG_TERM_MEMORY_FILE)
        content = read_text_file(daily_path)
        if not content:
            return

        summary_prompt = (
            '你是一個記憶管理系統。請閱讀以下今日日誌，提煉出最重要的資訊，'
            '並生成一個簡短、清楚的長期記憶摘要，適合儲存在 memory.md。'
            '請使用繁體中文，不要加入執行步驟說明。\n\n'
            f'=== 今日日誌 ===\n{content}\n\n'
        )

        summary = ask_ollama(summary_prompt)
        if summary:
            with open(LONG_TERM_MEMORY_FILE, 'a', encoding='utf-8') as f:
                f.write('\n\n--- 自動記憶摘要 {} ---\n{}'.format(datetime.datetime.now().isoformat(), summary.strip()))
            logger.info('Appended memory summary to %s', LONG_TERM_MEMORY_FILE)
        else:
            logger.warning('Memory summarization returned no result')
    except Exception as e:
        logger.error('Failed to refresh memory: %s', e)


def append_memory_entry(user_id, user_input, ai_response):
    ensure_memory_dirs()
    daily_path = get_daily_memory_path(0)
    try:
        with open(daily_path, 'a', encoding='utf-8') as f:
            f.write('### {} user_id={}\n'.format(datetime.datetime.now().isoformat(), user_id or 'unknown'))
            f.write('- 用戶：{}\n'.format(user_input.replace('\n', ' ')))
            f.write('- 小龍蝦：{}\n\n'.format(ai_response.replace('\n', ' ')))
        logger.info('Appended conversation to %s', daily_path)
        refresh_memory_if_needed()
    except Exception as e:
        logger.error('Cannot append memory entry: %s', e)

def get_knowledge_files():
    """回傳所有存在的知識庫檔案的路徑列表。"""
    potential_files = [
        KNOWLEDGE_FILE,
        SOUL_FILE,
        AGENTS_FILE,
        USER_FILE,
        LONG_TERM_MEMORY_FILE,
        'skills.md',
        'courses.md',
        'learned_knowledge.txt'
    ]
    for days_ago in range(DAILY_MEMORY_LOOKBACK_DAYS):
        potential_files.append(get_daily_memory_path(days_ago))
    
    existing_files = [f for f in potential_files if f and os.path.exists(f)]
    logger.debug('Found potential knowledge files: %s', existing_files)
    return existing_files

# 簡單檢查至少有一個知識庫檔案存在且有內容
# 只作預檢查，實際讀取知識時還會再次載入內容
def check_knowledge_file():
    """檢查知識庫檔案是否存在且至少有一個有內容"""
    ensure_memory_dirs()
    kb_files = get_knowledge_files()

    if not kb_files:
        logger.error('No knowledge files found. Please check file paths and names in your configuration.')
        return False

    for kb_file in kb_files:
        if os.path.getsize(kb_file) > 0:
            logger.info('Knowledge file check passed. Found content in %s', kb_file)
            return True
    
    logger.error('All found knowledge files are empty: %s', kb_files)
    return False


# 先載入環境變數並檢查必要設定
# 這裡會從 .env 檔案讀取，並確保 LINE 基本金鑰已設定
validate_environment()

# 進一步讀取其他運行時設定，例如 Ollama API 位置和模型名稱
LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', 'http://127.0.0.1:11434/api/generate')
OLLAMA_MODEL_NAME = os.getenv('OLLAMA_MODEL_NAME', 'qwen2:0.5b')
KNOWLEDGE_FILE = os.getenv('KNOWLEDGE_FILE', 'knowledge.txt')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
LLM_CHAIN = os.getenv('LLM_CHAIN', 'ollama,gemini').split(',')
ROUTER_MODEL_NAME = os.getenv('ROUTER_MODEL_NAME', OLLAMA_MODEL_NAME)
ROUTER_ENABLED = os.getenv('ROUTER_ENABLED', 'true').lower() in ('1', 'true', 'yes')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '').strip()
GROQ_API_URL = os.getenv('GROQ_API_URL', 'https://api.groq.com/openai/v1/chat/completions').strip()
GROQ_MODEL_NAME = os.getenv('GROQ_MODEL_NAME', '').strip()
XAI_API_KEY = os.getenv('XAI_API_KEY', '').strip()
XAI_API_URL = os.getenv('XAI_API_URL', 'https://api.x.ai/v1/responses').strip()
XAI_MODEL_NAME = os.getenv('XAI_MODEL_NAME', 'grok-4.20-reasoning').strip()
GITHUB_MODELS_TOKEN = os.getenv('GITHUB_MODELS_TOKEN', '').strip()
GITHUB_MODELS_API_URL = os.getenv('GITHUB_MODELS_API_URL', 'https://models.github.ai/inference/chat/completions').strip()
GITHUB_MODELS_API_VERSION = os.getenv('GITHUB_MODELS_API_VERSION', '2026-03-10').strip()
GITHUB_MODELS_NAME = os.getenv('GITHUB_MODELS_NAME', 'openai/gpt-4o').strip()
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').strip().rstrip('/')
LINE_WEBHOOK_PATH = os.getenv('LINE_WEBHOOK_PATH', '/callback').strip() or '/callback'
LINE_WEBHOOK_AUTO_UPDATE = os.getenv('LINE_WEBHOOK_AUTO_UPDATE', 'true').lower() in ('1', 'true', 'yes')
WEBHOOK_SYNC_INTERVAL_SECONDS = int(os.getenv('WEBHOOK_SYNC_INTERVAL_SECONDS', '30'))
WEBHOOK_SYNC_STARTUP_DELAY_SECONDS = int(os.getenv('WEBHOOK_SYNC_STARTUP_DELAY_SECONDS', '5'))
LINE_WEBHOOK_TEST_ENABLED = os.getenv('LINE_WEBHOOK_TEST_ENABLED', 'true').lower() in ('1', 'true', 'yes')
NGROK_API_URL = os.getenv('NGROK_API_URL', '').strip()
WEBHOOK_SYNC_TOKEN = os.getenv('WEBHOOK_SYNC_TOKEN', '').strip()

if GENAI_AVAILABLE and GEMINI_API_KEY:
    GEMINI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)
else:
    GEMINI_CLIENT = None

# 設定檔案為先的記憶層架構
MEMORY_DIR = os.getenv('MEMORY_DIR', 'memory')
SOUL_FILE = os.getenv('SOUL_FILE', 'SOUL.md')
AGENTS_FILE = os.getenv('AGENTS_FILE', 'AGENTS.md')
USER_FILE = os.getenv('USER_FILE', 'USER.md')
LONG_TERM_MEMORY_FILE = os.getenv('LONG_TERM_MEMORY_FILE', 'memory.md')
DAILY_MEMORY_LOOKBACK_DAYS = int(os.getenv('DAILY_MEMORY_LOOKBACK_DAYS', '2'))
MAX_MEMORY_FILE_CHARS = int(os.getenv('MAX_MEMORY_FILE_CHARS', '20000'))
MEMORY_SUMMARIZE_ENABLED = os.getenv('MEMORY_SUMMARIZE_ENABLED', 'true').lower() in ('1', 'true', 'yes')

# 紀錄每個用戶對話歷史，用於後續 prompt 的上下文延續
conversation_history = {}

# 紀錄目前可成功運作的 Gemini 模型，避免每次都從頭輪詢
WORKING_GEMINI_MODEL = None

# 紀錄最近一次同步後的 webhook URL，避免重複刷 API
LAST_SYNCED_WEBHOOK_URL = None
LAST_DETECTED_NGROK_URL = None

# 保留的歷史訊息筆數上限，避免 prompt 過長影響性能
MAX_HISTORY_LENGTH = 10

ROUTE_GENERAL = 'GENERAL'
ROUTE_EXPERT = 'EXPERT'
ROUTE_LOCAL = 'LOCAL'


# 啟動前檢查流程：Ollama 服務、模型是否可用，以及知識庫檔案是否存在
logger.info('Starting environment checks...')
if not check_ollama_service():
    logger.error('Ollama service check failed. Please ensure Ollama is running.')
    sys.exit(1)

if not check_ollama_model(OLLAMA_MODEL_NAME):
    logger.error('Ollama model check failed. Please install the model with: ollama pull %s', OLLAMA_MODEL_NAME)
    sys.exit(1)

if not check_knowledge_file():
    logger.error('Knowledge file check failed. Please ensure %s exists and contains content.', KNOWLEDGE_FILE)
    sys.exit(1)

logger.info('All environment checks passed. Starting bot...')

# 初始化 LINE Bot API 客戶端設定和 webhook handler
line_bot_configuration = Configuration(access_token=LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


def build_line_headers():
    return {
        'Authorization': f'Bearer {LINE_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }


def get_ngrok_api_candidates():
    candidates = []
    if NGROK_API_URL:
        candidates.append(NGROK_API_URL)

    candidates.extend([
        'http://127.0.0.1:4040/api/tunnels',
        'http://localhost:4040/api/tunnels',
        'http://ngrok-tunnel:4040/api/tunnels'
    ])

    # 去重但保留順序
    deduped = []
    seen = set()
    for candidate in candidates:
        if candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


def discover_ngrok_public_url():
    global LAST_DETECTED_NGROK_URL
    app_port = str(os.getenv('FLASK_PORT', '8080'))
    last_error = None

    for api_url in get_ngrok_api_candidates():
        try:
            response = requests.get(api_url, timeout=5)
            response.raise_for_status()
            payload = response.json()
            tunnels = payload.get('tunnels', [])
            if not tunnels:
                continue

            ranked = []
            for tunnel in tunnels:
                public_url = (tunnel or {}).get('public_url', '').strip()
                config = (tunnel or {}).get('config', {})
                addr = str(config.get('addr', ''))
                proto = str((tunnel or {}).get('proto', ''))

                if not public_url.startswith('https://'):
                    continue

                score = 0
                if proto == 'https':
                    score += 4
                if app_port and app_port in addr:
                    score += 2
                if 'xlx-workstation' in addr or 'localhost' in addr or '127.0.0.1' in addr:
                    score += 1

                ranked.append((score, public_url))

            if ranked:
                ranked.sort(reverse=True)
                selected_url = ranked[0][1].rstrip('/')
                if LAST_DETECTED_NGROK_URL != selected_url:
                    logger.info('Detected ngrok public URL from %s: %s', api_url, selected_url)
                    LAST_DETECTED_NGROK_URL = selected_url
                else:
                    logger.debug('ngrok public URL unchanged: %s', selected_url)
                return selected_url
        except Exception as e:
            last_error = e

    if last_error:
        logger.warning('Unable to discover ngrok public URL: %s', last_error)
    return None


def get_desired_webhook_url():
    base_url = PUBLIC_BASE_URL or discover_ngrok_public_url()
    if not base_url:
        return None

    webhook_path = LINE_WEBHOOK_PATH if LINE_WEBHOOK_PATH.startswith('/') else f'/{LINE_WEBHOOK_PATH}'
    return f'{base_url}{webhook_path}'


def get_line_webhook_info():
    response = requests.get(
        f'{LINE_API_BASE_URL}/endpoint',
        headers=build_line_headers(),
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def set_line_webhook_endpoint(endpoint_url):
    response = requests.put(
        f'{LINE_API_BASE_URL}/endpoint',
        headers=build_line_headers(),
        json={'endpoint': endpoint_url},
        timeout=10
    )
    response.raise_for_status()
    return response.json() if response.content else {}


def test_line_webhook_endpoint(endpoint_url=None):
    payload = {'endpoint': endpoint_url} if endpoint_url else {}
    response = requests.post(
        f'{LINE_API_BASE_URL}/test',
        headers=build_line_headers(),
        json=payload,
        timeout=15
    )
    response.raise_for_status()
    return response.json()


def sync_line_webhook(force=False):
    global LAST_SYNCED_WEBHOOK_URL

    desired_url = get_desired_webhook_url()
    if not desired_url:
        logger.info('Webhook sync skipped because no public URL is available yet')
        return False

    if not force and LAST_SYNCED_WEBHOOK_URL == desired_url:
        return False

    try:
        current_info = get_line_webhook_info()
        current_url = (current_info or {}).get('endpoint', '').rstrip('/')

        if not force and current_url == desired_url:
            LAST_SYNCED_WEBHOOK_URL = desired_url
            return False

        logger.info('Updating LINE webhook URL to %s', desired_url)
        set_line_webhook_endpoint(desired_url)
        LAST_SYNCED_WEBHOOK_URL = desired_url

        if LINE_WEBHOOK_TEST_ENABLED:
            test_result = test_line_webhook_endpoint()
            logger.info('LINE webhook test result: success=%s status=%s',
                        test_result.get('success'),
                        test_result.get('statusCode'))

        return True
    except Exception as e:
        logger.warning('Failed to sync LINE webhook URL: %s', e)
        return False


def webhook_sync_worker():
    if WEBHOOK_SYNC_STARTUP_DELAY_SECONDS > 0:
        logger.info('Webhook sync worker will start in %s seconds', WEBHOOK_SYNC_STARTUP_DELAY_SECONDS)
        threading.Event().wait(WEBHOOK_SYNC_STARTUP_DELAY_SECONDS)

    while True:
        try:
            sync_line_webhook()
        except Exception:
            logger.exception('Unexpected error in webhook sync worker')

        threading.Event().wait(max(WEBHOOK_SYNC_INTERVAL_SECONDS, 5))

# 解析 Ollama API 回傳的結構，支援多種返回格式
# 有些版本會直接回傳 'response' 或 'completion'，有些則包在 'choices' 裡面

def extract_ollama_response(payload):
    if not isinstance(payload, dict):
        return None

    if 'response' in payload and isinstance(payload['response'], str):
        return payload['response']

    if 'completion' in payload and isinstance(payload['completion'], str):
        return payload['completion']

    if 'result' in payload:
        return extract_ollama_response(payload['result'])

    if 'choices' in payload and isinstance(payload['choices'], list) and payload['choices']:
        first = payload['choices'][0]
        if isinstance(first, dict):
            if 'message' in first and isinstance(first['message'], dict):
                return first['message'].get('content')
            return first.get('text') or first.get('content')

    return None


def extract_xai_response(payload):
    if not isinstance(payload, dict):
        return None

    if isinstance(payload.get('output_text'), str) and payload.get('output_text').strip():
        return payload['output_text']

    output_items = payload.get('output')
    if isinstance(output_items, list):
        chunks = []
        for item in output_items:
            if not isinstance(item, dict):
                continue
            content_items = item.get('content')
            if not isinstance(content_items, list):
                continue
            for content in content_items:
                if not isinstance(content, dict):
                    continue
                text_value = content.get('text')
                if isinstance(text_value, str) and text_value.strip():
                    chunks.append(text_value)
        if chunks:
            return '\n'.join(chunks).strip()

    return extract_ollama_response(payload)


def ask_ollama_with_model(prompt, model_name):
    """使用指定的本地 Ollama 模型回答"""
    try:
        response = requests.post(
            OLLAMA_API_URL,
            json={
                'model': model_name,
                'prompt': prompt,
                'stream': False
            },
            timeout=60
        )
        try:
            response.raise_for_status()
        except requests.HTTPError:
            body = response.text[:2000]
            logger.error(
                'Ollama HTTP error status=%s model=%s response=%s',
                response.status_code,
                model_name,
                body
            )
            return None

        data = response.json()
        ai_text = extract_ollama_response(data)
        if ai_text:
            logger.info('Ollama model %s reply length=%s', model_name, len(ai_text))
            return ai_text
        logger.warning('Ollama model %s returned empty response', model_name)
        return None
    except requests.RequestException as e:
        logger.error('Ollama request failed for model %s: %s', model_name, e)
        return None
    except ValueError as e:
        logger.error('Invalid JSON from Ollama model %s: %s', model_name, e)
        return None


def ask_openai_compatible_chat(api_url, api_key, model_name, prompt, extra_headers=None):
    if not api_key or not model_name:
        return None

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        'model': model_name,
        'messages': [
            {'role': 'system', 'content': '你是健言小龍蝦的推理引擎，請使用繁體中文回覆。'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.4,
        'stream': False
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
        try:
            response.raise_for_status()
        except requests.HTTPError:
            logger.warning('Provider HTTP error url=%s model=%s status=%s body=%s',
                           api_url,
                           model_name,
                           response.status_code,
                           response.text[:1000])
            return None

        data = response.json()
        return extract_ollama_response(data)
    except requests.RequestException as e:
        logger.warning('Provider request failed url=%s model=%s error=%s', api_url, model_name, e)
        return None
    except ValueError as e:
        logger.warning('Provider JSON parse failed url=%s model=%s error=%s', api_url, model_name, e)
        return None


def ask_xai(prompt):
    if not XAI_API_KEY or not XAI_MODEL_NAME:
        return None

    headers = {
        'Authorization': f'Bearer {XAI_API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = {
        'model': XAI_MODEL_NAME,
        'input': prompt
    }

    try:
        response = requests.post(XAI_API_URL, headers=headers, json=payload, timeout=60)
        try:
            response.raise_for_status()
        except requests.HTTPError:
            logger.warning('xAI HTTP error url=%s model=%s status=%s body=%s',
                           XAI_API_URL,
                           XAI_MODEL_NAME,
                           response.status_code,
                           response.text[:1000])
            return None

        data = response.json()
        return extract_xai_response(data)
    except requests.RequestException as e:
        logger.warning('xAI request failed model=%s error=%s', XAI_MODEL_NAME, e)
        return None
    except ValueError as e:
        logger.warning('xAI JSON parse failed model=%s error=%s', XAI_MODEL_NAME, e)
        return None


def ask_groq(prompt):
    return ask_openai_compatible_chat(
        GROQ_API_URL,
        GROQ_API_KEY,
        GROQ_MODEL_NAME,
        prompt
    )


def ask_github_models(prompt):
    return ask_openai_compatible_chat(
        GITHUB_MODELS_API_URL,
        GITHUB_MODELS_TOKEN,
        GITHUB_MODELS_NAME,
        prompt,
        extra_headers={
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': GITHUB_MODELS_API_VERSION
        }
    )


# 嘗試從台北市健言社官網取得課程相關資訊，作為回答參考來源
def query_course_info(user_input):
    """
    動態查詢 台北市健言社 官網的最新課程與公告。
    使用 BeautifulSoup 解析 HTML。
    """
    course_keywords = ['課程', '課表', '公告', '最新', '活動', 'pathways', 'project', '教育', 'training', '學習', '健言', 'tmc']
    if not any(keyword in user_input.lower() for keyword in course_keywords):
        return None
    
    if not BS4_AVAILABLE:
        logger.warning('BeautifulSoup4 is not installed. Skipping dynamic course query.')
        return None

    try:
        url = 'https://tmc1974.com/'
        logger.info('Querying latest courses from %s for: %s', url, user_input)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'lxml')
        
        posts_container = soup.find('div', class_='elementor-posts-container')
        if not posts_container:
            logger.warning('Could not find posts container on the website. The site structure may have changed.')
            return None

        articles = posts_container.find_all('article', class_='elementor-post', limit=5)
        if not articles:
            logger.warning('No articles found in the posts container.')
            return None

        scraped_courses = []
        for article in articles:
            title_element = article.find('h3', class_='elementor-post__title')
            date_element = article.find('span', class_='elementor-post-date')
            
            if title_element and date_element:
                title = title_element.get_text(strip=True)
                date = date_element.get_text(strip=True)
                scraped_courses.append(f"- {date}: {title}")

        if scraped_courses:
            course_summary = "根據台北市健言社官網最新公告：\n" + "\n".join(scraped_courses)
            course_summary += f"\n\n更多詳情請訪問官網：{url}"
            logger.info('Successfully scraped %d course/event items.', len(scraped_courses))
            return course_summary
        else:
            logger.warning('Found articles but could not extract title and date.')
            return None

    except requests.RequestException as e:
        logger.error('Error querying course info from website: %s', e)
    except Exception as e:
        logger.error('An unexpected error occurred during web scraping: %s', e)
    
    return None


def classify_request_with_rules(user_input):
    text = (user_input or '').lower()

    local_keywords = [
        '私密', '隱私', '保密', '機密', '內部', '個資', '公司背景', '講師手冊',
        '學員回饋', '回饋紀錄', '內網', '私房教材', 'sensitive', 'private'
    ]
    expert_keywords = [
        '程式', 'code', 'python', 'javascript', 'bug', '除錯', 'debug',
        '架構', '邏輯', '辯論', '講稿架構', '深度講評', '分析', '設計',
        '演算法', 'api', 'prompt', 'router', 'routing'
    ]
    general_keywords = [
        '開場', '破冰', '金句', '手勢', '聲音', '文案', '海報', '修辭',
        '短文', '標題', '口號'
    ]

    if any(keyword in text for keyword in local_keywords):
        return ROUTE_LOCAL, 'keyword:private'
    if any(keyword in text for keyword in expert_keywords):
        return ROUTE_EXPERT, 'keyword:expert'
    if any(keyword in text for keyword in general_keywords):
        return ROUTE_GENERAL, 'keyword:general'
    return None, None


def classify_request_with_model(user_input):
    if not ROUTER_ENABLED:
        return None, None

    router_prompt = (
        '你是請求分類器，請只回傳一個標籤，不要解釋。\n'
        '可選標籤只有：GENERAL、EXPERT、LOCAL。\n'
        '判斷規則：\n'
        '- GENERAL：一般閒聊、技巧型訓練、速度優先、需要多樣點子。\n'
        '- EXPERT：複雜邏輯、程式、辯論推理、講稿架構、深度分析。\n'
        '- LOCAL：涉及私密資料、公司背景、學員回饋、講師手冊、不可外送資訊。\n'
        f'使用者請求：{user_input}\n'
        '請只輸出 GENERAL 或 EXPERT 或 LOCAL'
    )
    result = ask_ollama_with_model(router_prompt, ROUTER_MODEL_NAME)
    if not result:
        return None, None

    label = result.strip().upper()
    for candidate in (ROUTE_GENERAL, ROUTE_EXPERT, ROUTE_LOCAL):
        if candidate in label:
            return candidate, 'model:router'
    return None, None


def classify_request(user_input):
    rule_label, rule_reason = classify_request_with_rules(user_input)
    if rule_label:
        return rule_label, rule_reason

    model_label, model_reason = classify_request_with_model(user_input)
    if model_label:
        return model_label, model_reason

    return ROUTE_GENERAL, 'default:general'


def get_route_provider_chain(route_label):
    route_map = {
        ROUTE_GENERAL: ['groq', 'xai', 'github', 'gemini', 'ollama'],
        ROUTE_EXPERT: ['github', 'xai', 'gemini', 'ollama', 'groq'],
        ROUTE_LOCAL: ['ollama']
    }
    return route_map.get(route_label, ['ollama', 'gemini'])


def build_route_prompt(route_label, user_input, knowledge_content, history=None):
    route_note_map = {
        ROUTE_GENERAL: '本題屬於一般訓練或技巧型需求，請優先提供快速、實用、多樣的建議。',
        ROUTE_EXPERT: '本題屬於深度分析或複雜邏輯需求，請優先提供嚴謹、條理清楚、可推演的回答。',
        ROUTE_LOCAL: '本題涉及私密或內部資料，請以保密、謹慎、不外送敏感資訊為最高原則。'
    }
    routed_knowledge = (
        f"--- 請求路由判定 ---\n"
        f"分類：{route_label}\n"
        f"原則：{route_note_map.get(route_label, '')}\n\n"
        f"{knowledge_content}"
    )
    return build_prompt(user_input, routed_knowledge, history)


# 將知識庫內容、對話歷史與使用者問題組裝成一個完整的 prompt
# 這是傳給 LLM 的主要上下文，幫助模型理解任務與先前對話

def build_prompt(user_input, knowledge_content, history=None):
    prompt_parts = [
        '你現在是「健言小龍蝦」，請參考以下社團知識回答問題。\n'
        '【重要規則】\n'
        '1. 絕對不要捏造不存在的資訊（不可有幻覺）。如果你上網搜尋後還是找不到相關資料，請明確且老實地回答：「我目前查不到相關資訊」。\n'
        '2. 若遇到不知道的問題，請善用搜尋工具上網查詢，並優先搜尋與「台北市健言社」相關的官方網站及網路社群媒體資料。\n'
        '3. 如果你從用戶的對話中，或是上網搜尋後，獲得了未來可能會用到的「台北市健言社」新知識，請在你的回答最後加上：\n'
        '<LEARNED>這裡寫下你想記住的具體事實（一句話或條列式）</LEARNED>\n'
        '這會被系統自動記錄下來，成為你未來的知識。\n\n'
        f'知識內容：\n{knowledge_content}\n\n'
    ]
    
    if history:
        prompt_parts.append('對話歷史：\n')
        for i, (user_msg, ai_msg) in enumerate(history[-MAX_HISTORY_LENGTH:], 1):
            prompt_parts.append(f'{i}. 用戶：{user_msg}\n   小龍蝦：{ai_msg}\n')
        prompt_parts.append('\n')
    
    prompt_parts.append(f'當前用戶問題：{user_input}\n\n')
    prompt_parts.append('請用熱情且專業的繁體中文回答：')
    
    return ''.join(prompt_parts)


# Gemini API 呼叫函式，依序嘗試多個模型，遇到失敗就換下一個
# 這裡的優先順序可以透過 LLM_CHAIN 與模型列表調整

def ask_gemini(prompt):
    """使用 Google Gemini AI 回答"""
    global WORKING_GEMINI_MODEL
    if not GENAI_AVAILABLE:
        logger.warning('genai module not available, skipping Gemini')
        return None
    if not GEMINI_API_KEY or not GEMINI_CLIENT:
        logger.warning('GEMINI_API_KEY not set, skipping Gemini')
        return None

    try:
        # 使用目前仍可用的 Gemini API 模型，避免已下線或不支援的舊名稱
        models_to_try = [
            'gemini-2.5-flash',
            'gemini-2.0-flash',
            'gemini-2.5-pro',
            'gemini-2.0-flash-001'
        ]
        
        # 若之前有成功使用的模型，將其移到列表最前面優先測試
        if WORKING_GEMINI_MODEL in models_to_try:
            models_to_try.remove(WORKING_GEMINI_MODEL)
            models_to_try.insert(0, WORKING_GEMINI_MODEL)
        
        for model_name in models_to_try:
            try:
                logger.info('Trying Gemini model: %s', model_name)

                response = GEMINI_CLIENT.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        tools=[
                            genai_types.Tool(
                                google_search=genai_types.GoogleSearch()
                            )
                        ]
                    )
                )

                if response.text:
                    logger.info('Gemini (%s) reply length=%s', model_name, len(response.text))
                    # 紀錄目前成功運作的模型
                    if WORKING_GEMINI_MODEL != model_name:
                        WORKING_GEMINI_MODEL = model_name
                        logger.info('Cached working Gemini model: %s', WORKING_GEMINI_MODEL)
                    return response.text
                else:
                    logger.warning('Gemini (%s) returned empty response', model_name)
            except Exception as e:
                logger.warning('Gemini model %s failed: %s', model_name, str(e)[:200])
                continue
        
        logger.error('All Gemini models failed')
        return None
    except Exception as e:
        logger.error('Gemini request failed: %s', e)
        return None


# Ollama 本地模型呼叫函式，用來向本地部署的模型傳送 prompt
# 若 Ollama API 回傳錯誤，則記錄並回傳 None

def ask_ollama(prompt):
    """使用本地 Ollama AI 回答"""
    return ask_ollama_with_model(prompt, OLLAMA_MODEL_NAME)


# 主問答函式，先載入知識庫內容，再選擇最適合的 LLM 進行回應
# 會根據 LLM_CHAIN 設定順序嘗試不同模型，並進行重試機制
def ask_ai(user_input, history=None):
    kb_content = load_knowledge_base()
    if not kb_content:
        logger.error('Cannot load knowledge base')
        return '小龍蝦找不到知識庫，請稍後再試。'

    # 查詢課程資訊
    course_info = query_course_info(user_input)
    if course_info:
        kb_content += f'\n\n--- 來自 台北市健言社官網 ---\n{course_info}'

    route_label, route_reason = classify_request(user_input)
    prompt = build_route_prompt(route_label, user_input, kb_content, history)
    provider_chain = get_route_provider_chain(route_label)

    logger.info('Router selected route=%s reason=%s providers=%s', route_label, route_reason, provider_chain)

    # 依照路由規則嘗試，最多重試3次
    for attempt in range(3):
        logger.info('Route attempt %d/3 route=%s', attempt + 1, route_label)
        for provider_name in provider_chain:
            logger.info('Attempting provider=%s route=%s', provider_name, route_label)

            result = None
            if provider_name == 'groq':
                result = ask_groq(prompt)
            elif provider_name == 'xai':
                result = ask_xai(prompt)
            elif provider_name == 'github':
                result = ask_github_models(prompt)
            elif provider_name == 'gemini':
                result = ask_gemini(prompt)
            elif provider_name == 'ollama':
                result = ask_ollama(prompt)

            if result:
                logger.info('Success with provider=%s route=%s', provider_name, route_label)
                return result

            logger.warning('Provider failed provider=%s route=%s, trying next fallback', provider_name, route_label)

        logger.warning('All providers failed in attempt %d for route=%s, retrying...', attempt + 1, route_label)
        import time
        time.sleep(2)  # 等待2秒後重試
    
    # 所有嘗試都失敗
    logger.error('All providers failed after 3 attempts for route=%s chain=%s', route_label, provider_chain)
    return '小龍蝦無法連線到任何 AI 服務，請稍後再試。'


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'})


@app.route('/sync-webhook', methods=['POST'])
def sync_webhook():
    if not WEBHOOK_SYNC_TOKEN or request.headers.get('X-Webhook-Sync-Token', '') != WEBHOOK_SYNC_TOKEN:
        return jsonify({'error': 'forbidden'}), 403

    updated = sync_line_webhook(force=True)
    desired_url = get_desired_webhook_url()
    return jsonify({
        'updated': updated,
        'webhook_url': desired_url
    })


@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    logger.info('Received LINE webhook body=%s signature=%s', body[:200], signature)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning('Invalid LINE signature')
        abort(400)
    except Exception:
        logger.exception('Failed to handle LINE request')
        abort(500)

    return 'OK'


# LINE 消息事件處理器，收到文字訊息後呼叫 ask_ai 生成回覆

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    def process_message():
        user_text = event.message.text
        user_id = getattr(event.source, 'user_id', None)
        logger.info('Received text message from user_id=%s text=%s', user_id, user_text)

        # 獲取用戶歷史
        if user_id not in conversation_history:
            conversation_history[user_id] = []
        
        history = conversation_history[user_id]

        ai_response = ask_ai(user_text, history)
        
        # 提取學習到的新知識
        learned_matches = re.findall(r'<LEARNED>(.*?)</LEARNED>', ai_response, re.IGNORECASE | re.DOTALL)
        if learned_matches:
            try:
                with open('learned_knowledge.txt', 'a', encoding='utf-8') as f:
                    for match in learned_matches:
                        fact = match.strip()
                        if fact:
                            f.write(f"- {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}: {fact}\n")
                            logger.info('Saved new knowledge: %s', fact)
                # 移除回應中的標籤，不顯示給用戶
                ai_response = re.sub(r'<LEARNED>.*?</LEARNED>', '', ai_response, flags=re.IGNORECASE | re.DOTALL).strip()
            except Exception as e:
                logger.error('Failed to save learned knowledge: %s', e)

        logger.info('Replying to LINE user_id=%s response_length=%s', user_id, len(ai_response))

        # 保存到歷史
        history.append((user_text, ai_response))
        # 保持歷史長度不超過限制
        if len(history) > MAX_HISTORY_LENGTH:
            history.pop(0)

        # 追加到檔案記憶，支援日誌與長期記憶摘要
        append_memory_entry(user_id, user_text, ai_response)

        try:
            with ApiClient(line_bot_configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=ai_response)]
                    )
                )
        except Exception:
            logger.exception('Failed to send LINE reply')

    # 使用獨立執行緒處理以避免 LINE webhook 逾時
    thread = threading.Thread(target=process_message)
    thread.start()


if __name__ == '__main__':
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '8080'))
    if LINE_WEBHOOK_AUTO_UPDATE:
        threading.Thread(target=webhook_sync_worker, daemon=True).start()
        logger.info('LINE webhook auto-sync is enabled')
    logger.info('Starting Flask app on %s:%s', host, port)
    app.run(host=host, port=port)
