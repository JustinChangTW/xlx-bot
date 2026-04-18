import os
import sys
import logging
import traceback
from flask import Flask, request, abort, jsonify
import requests
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

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


def validate_environment():
    load_dotenv(ENV_FILE)
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        logger.error('Missing required environment variables: %s', missing)
        if not os.path.exists(ENV_FILE):
            logger.error('Expected .env file at %s', ENV_FILE)
        logger.error('Please set these variables in the environment or in %s before running.', ENV_FILE)
        raise RuntimeError('Missing required environment variables')


def check_ollama_service():
    """檢查 Ollama 服務是否可用"""
    try:
        response = requests.get('http://127.0.0.1:11434/', timeout=5)
        if response.status_code == 200:
            logger.info('Ollama service is running')
            return True
        else:
            logger.error('Ollama service returned status %s', response.status_code)
            return False
    except requests.RequestException as e:
        logger.error('Cannot connect to Ollama service: %s', e)
        return False


def check_ollama_model(model_name):
    """檢查指定的 Ollama 模型是否存在"""
    try:
        response = requests.post(
            'http://127.0.0.1:11434/v1/completions',
            json={'model': model_name, 'prompt': 'test', 'stream': False},
            timeout=10
        )
        if response.status_code == 200:
            logger.info('Ollama model %s is available', model_name)
            return True
        elif response.status_code == 404:
            error_data = response.json()
            if 'model' in error_data.get('error', {}).get('message', ''):
                logger.warning('Ollama model %s not found. Attempting to pull...', model_name)
                if pull_ollama_model(model_name):
                    logger.info('Successfully pulled Ollama model %s', model_name)
                    return True
                else:
                    logger.error('Failed to pull Ollama model %s', model_name)
                    return False
            else:
                logger.error('Ollama model %s error: %s', model_name, error_data)
                return False
        else:
            logger.error('Ollama model %s check failed with status %s', model_name, response.status_code)
            return False
    except requests.RequestException as e:
        logger.error('Cannot check Ollama model %s: %s', model_name, e)
        return False


def pull_ollama_model(model_name):
    """自動下載 Ollama 模型"""
    import subprocess
    try:
        logger.info('Pulling Ollama model %s...', model_name)
        result = subprocess.run(
            ['/usr/local/bin/ollama', 'pull', model_name],
            capture_output=True,
            text=True,
            timeout=600  # 10 分鐘超時
        )
        if result.returncode == 0:
            logger.info('Successfully pulled model %s', model_name)
            return True
        else:
            logger.error('Failed to pull model %s: %s', model_name, result.stderr)
            return False
    except subprocess.TimeoutExpired:
        logger.error('Timeout while pulling model %s', model_name)
        return False
    except Exception as e:
        logger.error('Error pulling model %s: %s', model_name, e)
        return False


def check_knowledge_file():
    """檢查知識庫檔案是否存在"""
    if os.path.exists(KNOWLEDGE_FILE):
        try:
            with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    logger.info('Knowledge file %s loaded (%d chars)', KNOWLEDGE_FILE, len(content))
                    return True
                else:
                    logger.warning('Knowledge file %s is empty', KNOWLEDGE_FILE)
                    return False
        except Exception as e:
            logger.error('Cannot read knowledge file %s: %s', KNOWLEDGE_FILE, e)
            return False
    else:
        logger.error('Knowledge file %s not found', KNOWLEDGE_FILE)
        return False


validate_environment()

LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', 'http://127.0.0.1:11434/v1/completions')
KNOWLEDGE_FILE = os.getenv('KNOWLEDGE_FILE', 'knowledge.txt')
MODEL_NAME = os.getenv('MODEL_NAME', 'gemma:2b')

# 啟動前環境檢查
logger.info('Starting environment checks...')
if not check_ollama_service():
    logger.error('Ollama service check failed. Please ensure Ollama is running.')
    sys.exit(1)

if not check_ollama_model(MODEL_NAME):
    logger.error('Ollama model check failed. Please install the model with: ollama pull %s', MODEL_NAME)
    sys.exit(1)

if not check_knowledge_file():
    logger.error('Knowledge file check failed. Please ensure %s exists and contains content.', KNOWLEDGE_FILE)
    sys.exit(1)

logger.info('All environment checks passed. Starting bot...')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


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


def build_prompt(user_input, knowledge_content):
    return (
        '你現在是「健言小龍蝦」，請參考以下社團知識回答問題。\n\n'
        f'知識內容：\n{knowledge_content}\n\n'
        f'使用者問題：{user_input}\n\n'
        '請用熱情且專業的繁體中文回答：'
    )


def ask_ai(user_input):
    try:
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            kb_content = f.read().strip()
    except FileNotFoundError:
        logger.exception('Knowledge file not found: %s', KNOWLEDGE_FILE)
        return '小龍蝦找不到知識庫，請稍後再試。'
    except Exception:
        logger.exception('Failed to read knowledge file: %s', KNOWLEDGE_FILE)
        return '讀取知識庫時發生錯誤，請稍後再試。'

    prompt = build_prompt(user_input, kb_content)
    logger.info('Sending prompt to Ollama: model=%s url=%s', MODEL_NAME, OLLAMA_API_URL)

    try:
        response = requests.post(
            OLLAMA_API_URL,
            json={
                'model': MODEL_NAME,
                'prompt': prompt,
                'stream': False
            },
            timeout=30
        )
        try:
            response.raise_for_status()
        except requests.HTTPError:
            body = response.text[:2000]
            logger.error(
                'Ollama HTTP error status=%s url=%s model=%s response=%s',
                response.status_code,
                OLLAMA_API_URL,
                MODEL_NAME,
                body
            )
            logger.exception('Ollama request failed')
            return '小龍蝦連線到 AI 服務失敗，請稍後再試。'

        data = response.json()
        ai_text = extract_ollama_response(data)
        logger.info('Ollama reply length=%s', len(ai_text or ''))
        if ai_text:
            return ai_text

        logger.warning('Unexpected Ollama response payload: %s', data)
        return '小龍蝦收到了不正確的回應，請稍後再試。'
    except requests.RequestException:
        logger.exception('Ollama request failed')
        return '小龍蝦連線到 AI 服務失敗，請稍後再試。'
    except ValueError:
        logger.exception('Invalid JSON from Ollama response')
        return '小龍蝦讀取 AI 回應失敗，請稍後再試。'


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


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text
    user_id = getattr(event.source, 'user_id', None)
    logger.info('Received text message from user_id=%s text=%s', user_id, user_text)

    ai_response = ask_ai(user_text)
    logger.info('Replying to LINE user_id=%s response_length=%s', user_id, len(ai_response))

    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=ai_response)
        )
    except Exception:
        logger.exception('Failed to send LINE reply')


if __name__ == '__main__':
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '8080'))
    logger.info('Starting Flask app on %s:%s', host, port)
    app.run(host=host, port=port)
