# xlx-bot

這是一個使用 Flask + LINE Messaging API、多模型 provider 與模組化知識庫的小龍蝦聊天機器人。

## 主要功能

- 接收 LINE 訊息 webhook
- 讀取 `knowledge/` 與 `knowledge.txt` 中的正式社團知識
- 依問題類型挑選相關知識片段並組成 prompt
- 呼叫本地 Ollama 與其他可用 provider 產生回答
- 在知識不足時優先明確拒答，不亂編現況資訊
- 回傳 AI 生成的繁體中文回答
- 內建 logging 與 `/health` 健康檢查

## 新手快速上手（先看這段）

如果你是第一次接觸這個專案，建議照這個順序：

1. **先準備 `.env`**：至少填好 `LINE_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET`、`OLLAMA_API_URL`、`OLLAMA_MODEL_NAME`。
2. **確認 AI 服務可用**：本專案仰賴模型服務（如 Ollama）；若模型沒啟動，機器人就無法正常回答。
3. **先跑健康檢查**：啟動後先打 `http://localhost:8080/health`，確定服務真的活著。
4. **最後再接 LINE webhook**：先把本地服務跑穩，再串接外部平台，除錯會簡單很多。

> 新手提醒：最常見問題是「環境變數沒設好」和「模型服務沒啟動」。

## 特色亮點（你會用到的）

- **模組化知識庫**：`knowledge/` 一主題一檔案，方便維護與擴充。
- **模組化技能層**：`skills/` 可拆分不同能力，便於迭代。
- **智慧路由**：可依請求類型分流到不同模型/供應商，提升穩定性。
- **自動回退機制**：外部模型失敗時可自動切換到下一個 provider。
- **可觀測性**：內建 logging 與 `/health`，方便部署後排查問題。

## 使用前注意事項（避免踩雷）

- **不要把 `.env` 提交到 Git**：裡面有金鑰與敏感資訊。
- **先確認 webhook URL 是公開可達**：LINE 無法打到你的 `/callback` 就不會有回應。
- **ngrok 變更網址要同步**：若公開網址變動，請確認 webhook 已更新。
- **先看日誌再猜問題**：`xlx-bot.log` 通常可以直接看出是驗證、網路或模型錯誤。
- **Docker 與本機設定不要混用**：先選一種方式跑通，再切換另一種方式。

## 專案結構

- `main.py`：機器人主程式
- `knowledge/`：模組化知識檔案目錄（一個主題一個 `.md`）
- `knowledge.txt`：知識索引說明檔
- `skills/`：模組化技能檔案目錄（一個 skill 一個 `.md`）
- `SOUL.md`：Agent 的核心人格與行為指令（可選）
- `AGENTS.md`：啟動流程與記憶讀取規則（可選）
- `USER.md`：使用者偏好與個人化資訊（可選）
- `memory/`：每日對話日誌檔案
- `memory.md`：長期記憶摘要檔案
- `Dockerfile`：建置容器映像
- `docker-compose.yml`：本地開發與部署設定
- `.env`：LINE 憑證與設定
- `requirements.txt`：Python 相依套件

## 知識模組化

- `knowledge/` 採用一個主題一個檔的設計，回答流程會把它視為正式社團知識來源。
- `knowledge.txt` 可保留作為補充索引或過渡內容，但回答時仍以 `knowledge/` 為主。
- `skills/` 採用一個 skill 一個檔的設計，但目前不直接當作社團事實知識來源。
- `knowledge/` 與 `skills/` 建議用檔名前綴序號控制載入順序，例如 `10_...`、`20_...`、`30_...`。
- `memory/` 與 `memory.md` 屬於記憶/維運資料，現階段不直接當作正式社團事實回答來源。
- `AGENTS.md`、`SOUL.md`、`USER.md` 與 `learned_knowledge.txt` 也屬於輔助資料，不直接進正式知識池。

## 目前回答流程

1. 收到 LINE 訊息後，先做 webhook 驗證，再交給背景執行緒處理。
2. 系統會載入正式知識來源，也就是 `knowledge/` 與 `knowledge.txt`。
3. Router 會先判斷問題意圖，例如規則、課程、組織、活動、公告、事實查詢。
4. 若是規則 / 課程 / 組織類問題，會優先使用 `knowledge/90_club_manual.md`。
5. 若命中的知識只有待補欄位、模板或資料不足標記，系統會直接回覆資料不足，而不是把空白交給模型自由生成。
6. 若有足夠知識，再依 route 選擇可用 provider chain，例如 Groq、xAI、GitHub Models、Gemini、Ollama。

## 回答原則

- 正式回答只依據已明確記載的社團知識內容。
- 若知識不足，直接回答「目前知識庫沒有這項資訊」或「目前提供的社團資料不足以確認」。
- 問到 `目前 / 最新 / 現任 / 最近` 時，只能使用知識檔內已標示為現況的內容。
- `90_club_manual.md` 只用來回答規則、訓練流程與職責模板，不可拿來推測現任名單或最新公告。
- `40_current_officers.md`、`50_programs_and_events.md`、`60_announcements.md` 已明確標示各自的可回答邊界。

## 架構文件

- `architecture.md`：完整架構說明（Mermaid 可編輯版本）
- `knowledge_schema.md`：知識欄位規格與維護流程
- `answering_rules.md`：回答策略與反幻覺規範

## 需要的環境變數

請在 `.env` 中填入：

- `LINE_ACCESS_TOKEN`
- `LINE_CHANNEL_SECRET`
- `OLLAMA_API_URL` （預設可用 `http://127.0.0.1:11434/v1/completions`，適合本機直接執行）
- `OLLAMA_MODEL_NAME` （預設 `qwen2:0.5b`，可改為 `gemma:2b`、`gemma:3-1b` 等）
- `MEMORY_DIR` （可選，預設 `memory`）
- `MEMORY_SUMMARIZE_ENABLED` （可選，預設 `true`，啟用日誌摘要到 long-term memory）
- `LOG_LEVEL` （可選，預設 `INFO`）
- `LOG_MAX_BYTES` （可選，預設 `1048576`，單一 log 檔超過後自動輪替）
- `LOG_BACKUP_COUNT` （可選，預設 `3`，保留幾份舊 log）
- `ROUTER_ENABLED` （可選，預設 `true`，啟用智慧分類器）
- `ROUTER_MODEL_NAME` （可選，預設與 `OLLAMA_MODEL_NAME` 相同，用本地模型做 `GENERAL/EXPERT/LOCAL` 分類）
- `GROQ_API_KEY` （可選，一般技巧型請求的高速路由）
- `GROQ_MODEL_NAME` （可選，例如依你的 Groq 帳號可用模型設定）
- `XAI_API_KEY` （可選，供 `x.ai / Grok` 路由使用）
- `XAI_MODEL_NAME` （可選，預設 `grok-4.20-reasoning`）
- `GITHUB_MODELS_TOKEN` （可選，供複雜邏輯與寫程式任務使用）
- `GITHUB_MODELS_NAME` （可選，預設 `openai/gpt-4o`）
- `LINE_WEBHOOK_AUTO_UPDATE` （可選，預設 `true`，自動同步 LINE webhook URL）
- `NGROK_API_URL` （可選，若未填會自動嘗試 `127.0.0.1:4040`、`localhost:4040`、`ngrok-tunnel:4040`）
- `PUBLIC_BASE_URL` （可選，若你有固定公開網址，可直接指定，例如 `https://your-domain.example.com`）
- `WEBHOOK_SYNC_TOKEN` （可選，用於手動呼叫 `/sync-webhook` 的保護 token）
- `SIDECAR_ENABLED` （可選，預設 `false`，啟用 sidecar dispatcher）
- `SIDECAR_MODE` （可選，預設 `mock`，目前僅提供建議草稿）
- `SIDECAR_TIMEOUT_SECONDS` （可選，預設 `8`）

> 建議：如果你有 Gemini API 的免費額度，可優先使用 `gemma-3-27b-instruct` / `gemma-3-12b-instruct` / `gemma-3-4b-instruct` / `gemma-3-1b-instruct`，這些 Gemma 3 指令型模型的免費請求額度較高。

範例：

```env
LINE_ACCESS_TOKEN=你的LINE_ACCESS_TOKEN
LINE_CHANNEL_SECRET=你的LINE_CHANNEL_SECRET
OLLAMA_API_URL=http://ollama-server:11434/api/generate
MODEL_NAME=gemma:2b
LOG_LEVEL=INFO
LOG_MAX_BYTES=1048576
LOG_BACKUP_COUNT=3
ROUTER_ENABLED=true
ROUTER_MODEL_NAME=llama3.2:3b
GROQ_API_KEY=你的GROQ金鑰
GROQ_MODEL_NAME=你的Groq模型名稱
XAI_API_KEY=你的xAI金鑰
XAI_MODEL_NAME=grok-4.20-reasoning
GITHUB_MODELS_TOKEN=你的GitHubModelsToken
GITHUB_MODELS_NAME=openai/gpt-4o
LINE_WEBHOOK_AUTO_UPDATE=true
NGROK_API_URL=http://127.0.0.1:4040/api/tunnels
WEBHOOK_SYNC_TOKEN=請換成你自己的安全字串
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
- 手動同步 LINE webhook：`POST http://localhost:8080/sync-webhook` 並帶上 header `X-Webhook-Sync-Token: 你的 token`

## 其他備註

- 如果你使用 Docker Compose，`docker-compose.yml` 會同時啟動 `ollama-server` 和 `xlx-workstation`。
- `ngrok` 重新連線導致公開網址改變時，程式會定期偵測並自動把 LINE 的 webhook URL 更新成最新的 `https://.../callback`。
- 智慧調配邏輯預設為：`GENERAL -> Groq -> xAI -> GitHub Models -> Gemini -> Ollama`、`EXPERT -> GitHub Models -> xAI -> Gemini -> Ollama -> Groq`、`LOCAL -> Ollama`。
- 若 `Groq`、`xAI` 或 `GitHub Models` 未設定金鑰或暫時失敗，系統會自動避讓到下一個可用 provider。
- 若要偵錯 LINE webhook，可查看 `xlx-bot.log` 或容器日誌。
