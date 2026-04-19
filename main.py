import os
import sys
import logging
import traceback
import subprocess
import datetime
import re
from flask import Flask, request, abort, jsonify
from urllib.parse import urlparse, urlunparse
import requests
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# 嘗試載入 Google Gemini 的 Python SDK，如果沒有安裝則後續會跳過 Gemini
try:
    import google.generativeai as genai
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
REQUIRED_ENV_VARS = ['LINE_ACCESS_TOKEN', 'LINE_CHANNEL_SECRET']

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)
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

if GENAI_AVAILABLE and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

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

# 保留的歷史訊息筆數上限，避免 prompt 過長影響性能
MAX_HISTORY_LENGTH = 10


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

# 初始化 LINE Bot API 客戶端和 webhook handler
line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

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
    if not GEMINI_API_KEY:
        logger.warning('GEMINI_API_KEY not set, skipping Gemini')
        return None

    try:
        # 嘗試多個模型，按優先順序
        # 先使用 Gemma 3 指令型模型，因為免費額度較充足
        models_to_try = [
            'gemma-3-27b-instruct',
            'gemma-3-12b-instruct',
            'gemma-3-4b-instruct',
            'gemma-3-1b-instruct',
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
                
                # 若模型名稱包含 gemini，則啟用 Google 搜尋 Grounding 功能
                # 這樣能讓模型在上網查資料時，根據提示詞自行搜尋
                tools = 'google_search_retrieval' if 'gemini' in model_name else None
                model = genai.GenerativeModel(model_name, tools=tools)
                
                response = model.generate_content(prompt, stream=False)
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
    try:
        response = requests.post(
            OLLAMA_API_URL,
            json={
                'model': OLLAMA_MODEL_NAME,
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
                OLLAMA_MODEL_NAME,
                body
            )
            return None

        data = response.json()
        ai_text = extract_ollama_response(data)
        if ai_text:
            logger.info('Ollama reply length=%s', len(ai_text))
            return ai_text
        else:
            logger.warning('Ollama returned empty response')
            return None
    except requests.RequestException as e:
        logger.error('Ollama request failed: %s', e)
        return None
    except ValueError as e:
        logger.error('Invalid JSON from Ollama: %s', e)
        return None


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

    prompt = build_prompt(user_input, kb_content, history)
    
    # 按照 LLM_CHAIN 優先順序嘗試，最多重試3次
    logger.info('Trying LLM chain: %s', LLM_CHAIN)
    for attempt in range(3):
        logger.info('Attempt %d/3', attempt + 1)
        for llm_name in LLM_CHAIN:
            llm_name = llm_name.strip().lower()
            logger.info('Attempting %s...', llm_name)
            
            if llm_name == 'gemini':
                result = ask_gemini(prompt)
                if result:
                    logger.info('Success with Gemini')
                    return result
                else:
                    logger.warning('Gemini failed, trying next in chain')
                    
            elif llm_name == 'ollama':
                result = ask_ollama(prompt)
                if result:
                    logger.info('Success with Ollama')
                    return result
                else:
                    logger.warning('Ollama failed, trying next in chain')
        
        logger.warning('All LLMs failed in attempt %d, retrying...', attempt + 1)
        import time
        time.sleep(2)  # 等待2秒後重試
    
    # 所有嘗試都失敗
    logger.error('All LLMs failed after 3 attempts: %s', LLM_CHAIN)
    return '小龍蝦無法連線到任何 AI 服務，請稍後再試。'


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'})


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
import threading

@handler.add(MessageEvent, message=TextMessage)
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
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=ai_response)
            )
        except Exception:
            logger.exception('Failed to send LINE reply')

    # 使用獨立執行緒處理以避免 LINE webhook 逾時
    thread = threading.Thread(target=process_message)
    thread.start()


if __name__ == '__main__':
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '8080'))
    logger.info('Starting Flask app on %s:%s', host, port)
    app.run(host=host, port=port)
