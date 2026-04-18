# xlx-bot

這是一個使用 Flask + LINE Messaging API + Ollama 的小龍蝦聊天機器人。

## 主要功能

- 接收 LINE 訊息 webhook
- 讀取 `knowledge.txt` 中的社團知識
- 組成 prompt 並呼叫本地 Ollama AI
- 回傳 AI 生成的繁體中文回答
- 內建 logging 與 `/health` 健康檢查

## 專案結構

- `main.py`：機器人主程式
- `knowledge.txt`：社團知識庫內容
- `SOUL.md`：Agent 的核心人格與行為指令（可選）
- `AGENTS.md`：啟動流程與記憶讀取規則（可選）
- `USER.md`：使用者偏好與個人化資訊（可選）
- `memory/`：每日對話日誌檔案
- `memory.md`：長期記憶摘要檔案
- `Dockerfile`：建置容器映像
- `docker-compose.yml`：本地開發與部署設定
- `.env`：LINE 憑證與設定
- `requirements.txt`：Python 相依套件

## 需要的環境變數

請在 `.env` 中填入：

- `LINE_ACCESS_TOKEN`
- `LINE_CHANNEL_SECRET`
- `OLLAMA_API_URL` （預設可用 `http://127.0.0.1:11434/v1/completions`，適合本機直接執行）
- `OLLAMA_MODEL_NAME` （預設 `qwen2:0.5b`，可改為 `gemma:2b`、`gemma:3-1b` 等）
- `MEMORY_DIR` （可選，預設 `memory`）
- `MEMORY_SUMMARIZE_ENABLED` （可選，預設 `true`，啟用日誌摘要到 long-term memory）

> 建議：如果你有 Gemini API 的免費額度，可優先使用 `gemma-3-27b-instruct` / `gemma-3-12b-instruct` / `gemma-3-4b-instruct` / `gemma-3-1b-instruct`，這些 Gemma 3 指令型模型的免費請求額度較高。

範例：

```env
LINE_ACCESS_TOKEN=你的LINE_ACCESS_TOKEN
LINE_CHANNEL_SECRET=你的LINE_CHANNEL_SECRET
OLLAMA_API_URL=http://ollama-server:11434/api/generate
MODEL_NAME=gemma:2b
```
> 注意：不要把 `.env` 公開到版本控制系統中。

## 直接執行

如果你想直接在本機執行，不使用 Docker，可執行：

```bash
cd /home/myclaw/xlx-bot
python3 -m pip install --user -r requirements.txt
python3 main.py
```

啟動前請確定：

1. `.env` 已經存在且填入正確的 LINE 憑證。
2. Ollama 服務可用，且 `OLLAMA_API_URL` 指向正確位置。
3. **安裝 AI 模型**（重要！）：
   ```bash
   /usr/local/bin/ollama pull gemma:2b
   ```
   或其他你想要的模型，然後在 `.env` 設定 `OLLAMA_MODEL_NAME`。

執行後，服務會在 `http://0.0.0.0:8080` 上啟動。

## 使用 Docker

### 方式 1：使用 Docker Compose

```bash
cd /home/myclaw/xlx-bot
sudo docker compose up -d
```

### 方式 2：手動建置並執行

```bash
cd /home/myclaw/xlx-bot
sudo docker build -t xlx-bot-agent .
sudo docker run -d --name xlx-bot --restart always -p 8080:8080 --env-file .env xlx-bot-agent
```

## 日誌與健康檢查

- 應用程式日誌：`xlx-bot.log`
- 健康檢查：`http://localhost:8080/health`

## 其他備註

- 如果你使用 Docker Compose，`docker-compose.yml` 會同時啟動 `ollama-server` 和 `xlx-workstation`。
- 若要偵錯 LINE webhook，可查看 `xlx-bot.log` 或容器日誌。
