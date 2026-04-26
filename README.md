# xlx-bot

這是一個使用 Flask + LINE Messaging API、多模型 provider、模組化知識庫與 OpenClaw 驅動資料查核流程的小龍蝦聊天機器人。

## 主要功能

- 接收 LINE 訊息 webhook
- 讀取 `knowledge/` 與 `knowledge.txt` 中的正式社團知識
- 依問題類型挑選相關知識片段並組成 prompt
- 呼叫本地 Ollama 與其他可用 provider 產生回答
- 在本地知識不足時透過 OpenClaw 查詢已核可官方來源，仍不足才明確拒答
- 以 `tool_registry` + `policy_engine` + `approval_gate` 控制任務型請求
- 記錄 `learning_events`、產生 `lessons_learned` 與 `troubleshooting`
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
- **OpenClaw 查核能力**：本地知識不足時，可透過 OpenClaw 查詢官網等已核可來源；任務型請求仍依風險分級控管。
- **自我成長**：保留 learning events、lessons 與 pending review 知識，不直接污染正式知識。
- **可觀測性**：內建 logging 與 `/health`，方便部署後排查問題。

## 使用前注意事項（避免踩雷）

- **不要把 `.env` 提交到 Git**：裡面有金鑰與敏感資訊。
- **先確認 webhook URL 是公開可達**：LINE 無法打到你的 `/callback` 就不會有回應。
- **ngrok 變更網址要同步**：若公開網址變動，請確認 webhook 已更新。
- **先看日誌再猜問題**：`xlx-bot.log` 通常可以直接看出是驗證、網路或模型錯誤。
- **Docker 與本機設定不要混用**：先選一種方式跑通，再切換另一種方式。

## 專案結構

- `main.py`：機器人主程式
- `xlxbot/`：核心模組目錄
  - `application.py`：Flask 應用與 LINE webhook 處理
  - `config.py`：配置管理
  - `knowledge.py`：知識載入與管理
  - `learning.py`：學習與記憶處理
  - `logging_setup.py`：日誌設定
  - `policy_engine.py`：政策引擎
  - `providers.py`：AI provider 服務
  - `response_strategy.py`：回應策略
  - `router.py`：訊息路由
  - `runtime.py`：運行狀態
  - `teaching_planner.py`：教學規劃
  - `tool_registry.py`：工具註冊
  - `webhook_sync.py`：webhook 同步
  - `agent/`：代理層
    - `action_layer.py`：動作層
    - `intent_classifier.py`：意圖分類器
    - `task_dispatcher.py`：任務分派
  - `sidecar/`：sidecar 模組
    - `dispatcher.py`：dispatcher
    - `gateway.py`：gateway
    - `schemas.py`：schemas
- `knowledge/`：模組化知識檔案目錄（一個主題一個 `.md`）
- `knowledge.txt`：知識索引說明檔
- `skills/`：模組化技能檔案目錄（一個 skill 一個 `.md`）
- `memory/`：每日對話日誌檔案
- `learned_knowledge.txt`：學習到的知識
- `AGENTS.md`：啟動流程與記憶讀取規則
- `config/`：配置檔案目錄
  - `config.yaml`：基本配置
  - `tool_registry.yaml`：工具註冊
- `docs/`：文檔目錄
- `tests/`：測試檔案目錄
- `Dockerfile`：建置容器映像
- `docker-compose.yml`：本地開發與部署設定
- `.env`：LINE 憑證與設定
- `requirements.txt`：Python 相依套件

## 知識模組化

- `knowledge/` 採用一個主題一個檔的設計，回答流程會優先使用本地正式社團知識。
- `knowledge.txt` 可保留作為補充索引或過渡內容，但回答時仍以 `knowledge/` 為第一順位。
- `skills/` 採用一個 skill 一個檔的設計，但目前不直接當作社團事實知識來源。
- `knowledge/` 與 `skills/` 建議用檔名前綴序號控制載入順序，例如 `10_...`、`20_...`、`30_...`。
- `memory/` 與 `memory.md` 屬於記憶/維運資料，不直接當作正式社團事實回答來源。
- `AGENTS.md`、`SOUL.md`、`USER.md` 與 `learned_knowledge.txt` 也屬於輔助資料，不直接進本地正式知識池。
- 若本地知識不足，系統應透過 OpenClaw 查詢已核可官方來源，例如台北市健言社官網 `https://tmc1974.com/`、課表 `https://tmc1974.com/schedule/`、歷任理事長及社長 `https://tmc1974.com/presidents/`、當期幹部 `https://tmc1974.com/leaders/`、理事會 `https://tmc1974.com/board-members/`、Instagram `https://www.instagram.com/taipeitoastmasters/`、YouTube `https://www.youtube.com/@1974toastmaster/videos`、Facebook `https://www.facebook.com/tmc1974`、Flickr 相簿 `https://www.flickr.com/photos/133676498@N06/albums/`、公告或課程分類頁；查詢結果必須帶來源並避免寫回正式知識庫，除非經人工審核。

## 目前回答流程

1. 收到 LINE 訊息後，先做 webhook 驗證，再交給背景執行緒處理。
2. 系統會先載入本地正式知識來源，也就是 `knowledge/` 與 `knowledge.txt`。
3. Router 會先判斷問題意圖，例如規則、課程、組織、活動、公告、事實查詢。
4. 若是規則 / 課程 / 組織類問題，會優先使用 `knowledge/90_club_manual.md`。
5. 若命中的知識只有待補欄位、模板或資料不足標記，系統會交由 OpenClaw 查詢已核可官方來源，而不是把空白交給模型自由生成。
6. Router 會先判斷這是知識問答、指令、錯誤回報、使用者更正，還是文件需求，再對應受控工具。
7. 若 OpenClaw 查不到可信來源、來源內容不足或查詢失敗，才回覆資料不足。
8. 若請求屬於中風險任務（例如文件草稿、sidecar 建議），系統回覆 `pending review`；若屬於高風險（改程式、deploy、寫正式 knowledge），系統直接禁止。
9. 若有足夠知識或 OpenClaw 查核結果，再依 route 選擇可用 provider chain，例如 Groq、xAI、GitHub Models、Gemini、Ollama。

## 回答原則

- 回答優先依據本地已明確記載的社團知識內容。
- 若本地知識不足，必須透過 OpenClaw 查詢已核可官方來源；OpenClaw 查不到可信資料時，才回答「目前知識庫與可查核官方來源都沒有這項資訊」或「目前提供的社團資料不足以確認」。
- 問到 `目前 / 最新 / 現任 / 最近` 時，先使用本地已標示為現況的內容；若本地不足，透過 OpenClaw 查詢官網現況頁。
- `90_club_manual.md` 只用來回答規則、訓練流程與職責模板，不可拿來推測現任名單或最新公告；缺口應交由 OpenClaw 查核對應官方頁面。
- `40_current_officers.md`、`50_programs_and_events.md`、`60_announcements.md` 已明確標示各自的可回答邊界。

## 受控 OpenClaw 能力

目前系統已具備受控骨架：

- 任務辨識：區分 `knowledge_qa`、`command`、`error_report`、`user_correction`、`docs_request`
- 工具註冊：僅允許 `config/tool_registry.yaml` 內已註冊工具
- 風險分級：
  - `low`：本地知識查詢、OpenClaw 官方來源查核、回答、learning/troubleshooting 記錄
  - `medium`：文件草稿、sidecar/OpenClaw 建議
  - `high`：改程式、deploy、寫正式 knowledge
- 執行規則：
  - `low`：可直接進回答流程；本地不足時可呼叫 OpenClaw 做官方來源查核
  - `medium`：`pending review`
  - `high`：直接禁止

目前尚未完成：

- 官網查詢結果自動轉入正式 knowledge 的審核流程
- 受核准後的自動執行
- 向量式 RAG

以上未完成項目都不應視為已上線功能。

## 自我成長機制

- 原始事件：`memory/learning_events.jsonl`
- 回答前提示：`memory/lessons_learned.md`
- 錯誤聚合：`memory/troubleshooting.md`
- 待審核知識：`learned_knowledge.txt`

設計原則：

- 記錄錯誤與使用者更正
- 本地知識不足且 OpenClaw 查到可用官方答案時，將查核結果寫入 `learned_knowledge.txt` 的 `PENDING_REVIEW`
- 重新整理 lessons/troubleshooting
- 新知識只進 `pending review`
- 不直接寫入 `knowledge/`

## RAG 說明

目前狀態：`TODO`

- 目前正式回答仍以檔案載入與規則式切用為主；檔案不足時改由 OpenClaw 查詢已核可官方來源
- 尚未完成 Chroma / FAISS 向量索引
- 後續若加入 RAG，仍必須遵守：本地 `knowledge/` 優先、OpenClaw 官方來源查核作為補充、保留來源、結果不足就拒答

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
- `SIDECAR_ENABLED` （可選，建議 `true`，啟用 sidecar dispatcher；OpenClaw 查核流程需啟用）
- `SIDECAR_MODE` （可選，預設 `mock`，可選 `mock` 或 `openclaw`）
- `SIDECAR_TIMEOUT_SECONDS` （可選，預設 `8`）
- `OPENCLAW_BASE_URL` （可選，當 `SIDECAR_MODE=openclaw` 時必填）
- `OPENCLAW_ENDPOINT_PATH` （可選，預設 `/v1/sidecar/dispatch`）
- `OPENCLAW_HEALTH_PATH` （可選，預設 `/v1/openclaw/health`，本機 OpenClaw gateway 健康檢查）
- `OPENCLAW_API_KEY` （可選，OpenClaw gateway bearer token）
- `OPENCLAW_PHASE` （可選，預設 `suggest`，可選 `observe` / `suggest` / `assist`）
- `OPENCLAW_MAX_OUTPUTS` （可選，預設 `5`，限制單次查核回傳片段數）
- `OPENCLAW_CONFIDENCE_OK` （可選，預設 `0.84`，查到官方資料時的信心分數）
- `OPENCLAW_CONFIDENCE_DEGRADED` （可選，預設 `0.2`，查核不足時的信心分數）
- `OPENCLAW_AUDIT_ENABLED` （可選，預設 `true`，產生 OpenClaw audit ref）
- `OPENCLAW_LEARNING_ENABLED` （可選，預設 `true`，允許查核結果進 pending review）
- `OPENCLAW_OFFICIAL_SOURCES` （可選，逗號分隔的核可官方來源清單）
- `AGENT_PATH_ENABLED` （可選，預設 `false`，啟用 agent path 實驗骨架）
- `TEACHING_PLANNER_ENABLED` （可選，預設 `true`，啟用回答前教學規劃提示）
- `OFFICIAL_SITE_RETRIEVAL_ENABLED` （可選，建議 `true`，允許透過 OpenClaw 查詢已核可官方來源補充回答）

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
SIDECAR_ENABLED=true
SIDECAR_MODE=openclaw
SIDECAR_TIMEOUT_SECONDS=8
OPENCLAW_BASE_URL=http://127.0.0.1:8080
OPENCLAW_ENDPOINT_PATH=/v1/sidecar/dispatch
OPENCLAW_HEALTH_PATH=/v1/openclaw/health
OPENCLAW_PHASE=suggest
OPENCLAW_MAX_OUTPUTS=5
OPENCLAW_CONFIDENCE_OK=0.84
OPENCLAW_CONFIDENCE_DEGRADED=0.2
OPENCLAW_AUDIT_ENABLED=true
OPENCLAW_LEARNING_ENABLED=true
OPENCLAW_OFFICIAL_SOURCES=https://tmc1974.com/,https://tmc1974.com/schedule/,https://tmc1974.com/presidents/,https://tmc1974.com/leaders/,https://tmc1974.com/board-members/,https://www.instagram.com/taipeitoastmasters/,https://www.youtube.com/@1974toastmaster/videos,https://www.facebook.com/tmc1974,https://www.flickr.com/photos/133676498@N06/albums/
OFFICIAL_SITE_RETRIEVAL_ENABLED=true
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

## 測試

```bash
cd /home/myclaw/xlx-bot
python3 -m unittest discover -s tests -v
```

目前測試涵蓋：

- 基本啟動與 health
- LINE callback 與 webhook sync
- 課表/公告抓取 helper
- sidecar/OpenClaw dispatcher
- agent path 與受控工具決策

## Troubleshooting

- `/health` 不通：先確認服務是否真的啟動在 `8080`
- LINE 無回應：先檢查 `LINE_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET`、webhook URL
- provider 全失敗：系統會回覆「無法連線到任何 AI 服務」，請檢查 Ollama / API key
- bot 亂答：先確認 `knowledge/` 是否有對應資料、OpenClaw 是否可查到已核可官方來源，以及回答是否有保留來源
- ngrok 無法連線：請用 `.env` 或 shell env 提供 `NGROK_AUTHTOKEN`，不要硬編在 repo

## TODO

- 完成向量式 RAG
- 補完整的 formal knowledge 審核流程
- 補 OpenClaw 查詢結果進入正式 knowledge 的人工審核流程
- 補更多行為回歸測試
- 持續同步 README 與程式實作

## 其他備註

- 如果你使用 Docker Compose，`docker-compose.yml` 會同時啟動 `ollama-server` 和 `xlx-workstation`。
- `ngrok` 重新連線導致公開網址改變時，程式會定期偵測並自動把 LINE 的 webhook URL 更新成最新的 `https://.../callback`。
- 智慧調配邏輯預設為：`GENERAL -> Groq -> xAI -> GitHub Models -> Gemini -> Ollama`、`EXPERT -> GitHub Models -> xAI -> Gemini -> Ollama -> Groq`、`LOCAL -> Ollama`。
- 若 `Groq`、`xAI` 或 `GitHub Models` 未設定金鑰或暫時失敗，系統會自動避讓到下一個可用 provider。
- 若要偵錯 LINE webhook，可查看 `xlx-bot.log` 或容器日誌。
