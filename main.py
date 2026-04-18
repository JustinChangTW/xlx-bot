from flask import Flask, request, abort
import requests
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# LINE 憑證 (已根據你先前的資料填入)
line_bot_api = LineBotApi('/8QC8ngAFK7NpMEcWHGy9RV8+o1d/tFkgXtAKINkQ+hpyT1NNjmes1OjOdWF3Ziuufywxzo6fWEXQUPmoqAKex8eXT3e3DTqD3Z01iJNBQ4nyL51fcquRq0qK8URtq0fRRPCQ6nJF+S8gsh+0LyECAdB04t89/1O/w1cDnyilFU=')
handler = WebhookHandler('4f2e027d9e316bc9d47b6af0747fc212')

def ask_ai(user_input):
    # 讀取知識庫內容
    with open("knowledge.txt", "r", encoding="utf-8") as f:
        kb_content = f.read()
    
    # 組合 Prompt：給予身分、背景知識與問題
    prompt = f"你現在是『健言小龍蝦』，請參考以下社團知識回答問題。\n\n知識內容：\n{kb_content}\n\n使用者問題：{user_input}\n\n請用熱情且專業的繁體中文回答："
    
    # 向本地 Ollama 請求 (確保 docker-compose 內的 ollama-server 名稱正確)
    response = requests.post(
        "http://ollama-server:11434/api/generate",
        json={"model": "gemma:2b", "prompt": prompt, "stream": False}
    )
    return response.json().get('response', '小龍蝦在思考中斷線了...')

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # 讓 AI 思考並產生回應
    ai_response = ask_ai(event.message.text)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=ai_response)
    )

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
