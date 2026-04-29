# xlx-bot 原始碼使用與架構說明

`xlx-bot` 是台北市健言社／小龍蝦社團知識聊天機器人。它使用 Flask 接收 LINE Messaging API webhook，讀取本地 Markdown 知識庫，必要時透過 OpenClaw 查詢已核可官方來源，再交給可用的 AI provider 產生繁體中文回答。

本專案的優先順序是：

1. 先正確，再完整。
2. 先使用本地正式知識，再查核官方來源。
3. 本地與官方查核都不足時，明確說資料不足。
4. 不自行編造幹部、公告、課程、活動、時間或來源。

## 給拿到原始碼的人

如果你是第一次使用這份原始碼，建議照這個順序理解：

1. 先讀本檔，確認如何啟動、設定與除錯。
2. 再讀 `architecture.md`，看完整架構圖與 OpenClaw dispatcher 設計。
3. 再讀 `PROJECT_SPEC.md`，理解產品目標、反幻覺規則與維護原則。
4. 修改前讀 `AGENTS.md`，遵守「先理解，再修改」的專案工作流程。
5. 若要改回答內容，先看 `knowledge/` 與 `skills/`，不要直接改 prompt 或亂補資料。

最常見的使用情境：

- 本機開發：使用 `python3 main.py` 啟動 Flask 服務。
- Docker 開發：使用 `docker compose up -d` 同時啟動 bot、Ollama 與 ngrok。
- LINE 串接：讓 LINE webhook 指到公開的 `https://.../callback`。
- 官方資料查核：啟用 sidecar/OpenClaw，讓本地知識不足時可查核核可來源。

## 系統在做什麼

主要能力：

- 接收 LINE 訊息 webhook。
- 載入 `knowledge/` 與 `knowledge.txt` 作為正式社團知識來源。
- 依問題意圖挑選相關知識片段與回答規則。
- 本地知識不足、過期或只有待補標記時，透過 OpenClaw 查詢已核可官方來源。
- 使用 provider chain 呼叫可用模型，例如 Ollama、Gemini、Groq、xAI、GitHub Models。
- 用 `tool_registry`、`policy_engine`、`approval_gate` 控制任務型請求風險。
- 記錄 learning events、lessons、troubleshooting 與 pending review 知識。
- 提供 `/health`、`/sync-webhook` 與本機 OpenClaw 相容端點。

## 架構速覽

簡化流程如下：

```text
LINE 使用者
  -> LINE Messaging API
  -> Flask /callback
  -> Router 意圖判斷
  -> Knowledge Service 讀取 knowledge/
  -> 本地不足時 Sidecar Dispatcher 呼叫 OpenClaw
  -> Provider Service 呼叫可用模型
  -> Learning Service 記錄決策與待審核資料
  -> LINE 回覆使用者
```

主要檔案與目錄：

- `main.py`：啟動入口。
- `xlxbot/application.py`：Flask app、LINE webhook、health check、OpenClaw 相容端點。
- `xlxbot/router.py`：意圖分類、知識切用、OpenClaw 觸發、provider chain 串接。
- `xlxbot/config.py`：環境變數與預設值集中管理。
- `xlxbot/providers.py`：AI provider 與官方網站查詢 helper。
- `xlxbot/knowledge.py`：本地知識載入。
- `xlxbot/sidecar/`：OpenClaw sidecar gateway、dispatcher、schema。
- `xlxbot/policy_engine.py`：工具風險決策。
- `xlxbot/approval_gate.py`：依風險輸出允許、pending review 或禁止。
- `xlxbot/learning.py`：學習事件、待審核知識與維運記錄。
- `knowledge/`：正式社團知識，一個主題一個 Markdown 檔。
- `skills/`：演講、講評、主持、簡報、訓練邏輯等技能規則。
- `memory/`：日誌、經驗與錯誤整理，不等同正式社團知識。
- `config/tool_registry.yaml`：受控工具註冊與風險標記。
- `docs/sidecar_design.md`：sidecar/OpenClaw 設計細節。
- `docs/openclaw_setup_runbook.md`：OpenClaw 設定與操作 runbook。

更完整的 Mermaid 架構圖請看 `architecture.md`。

## OpenClaw 是什麼

在本專案裡，OpenClaw 不是讓模型自由上網亂找資料，而是「本地知識不足時，查詢已核可官方來源的受控查核層」。

OpenClaw 主要用在：

- 最新公告。
- 近期或本週課程活動。
- 現任幹部、理事會、歷任理事長及社長。
- 使用者提供官方連結，要求摘要或查核。
- 本地知識只有 `[待補資料]`、`[目前知識庫沒有這項資訊]` 之類缺口標記。

核可官方來源預設包含：

- `https://tmc1974.com/`
- `https://tmc1974.com/schedule/`
- `https://tmc1974.com/presidents/`
- `https://tmc1974.com/leaders/`
- `https://tmc1974.com/board-members/`
- `https://www.instagram.com/taipeitoastmasters/`
- `https://www.youtube.com/@1974toastmaster/videos`
- `https://www.facebook.com/tmc1974`
- `https://www.flickr.com/photos/133676498@N06/albums/`

重要限制：

- OpenClaw 查到的資料可用於單次回答，但不會自動寫入正式 `knowledge/`。
- 查到的新資料若要保存，會先進 `learned_knowledge.txt` 的 pending review。
- 正式寫入 `knowledge/` 前必須人工審核。
- 查不到可信來源時，bot 必須回答資料不足，不可用模型推測補完。

## OpenClaw 模式

OpenClaw 由 sidecar dispatcher 控制，常見模式如下：

- `SIDECAR_MODE=mock`：安全模擬模式，不呼叫真正 OpenClaw，適合初次開發與測試流程。
- `SIDECAR_MODE=openclaw`：呼叫 `OPENCLAW_BASE_URL + OPENCLAW_ENDPOINT_PATH` 的實際 gateway。

OpenClaw phase：

- `OPENCLAW_PHASE=observe`：只觀測與記錄，不提供自動建議。
- `OPENCLAW_PHASE=suggest`：可提供查核或建議，但中高風險仍 pending review。
- `OPENCLAW_PHASE=assist`：保留給更進一步受控協助；仍需遵守 policy 與 approval gate。

目前建議原始碼使用者先用：

```env
SIDECAR_ENABLED=true
SIDECAR_MODE=mock
OPENCLAW_PHASE=suggest
```

確認主流程正常後，再改成：

```env
SIDECAR_ENABLED=true
SIDECAR_MODE=openclaw
OPENCLAW_BASE_URL=http://127.0.0.1:8080
OPENCLAW_ENDPOINT_PATH=/v1/sidecar/dispatch
OPENCLAW_HEALTH_PATH=/v1/openclaw/health
OPENCLAW_PHASE=suggest
```

> 目前 `application.py` 內有本機相容端點 `/v1/sidecar/dispatch` 與 `/v1/openclaw/health`，可用來驗證 sidecar 流程；若你有外部 OpenClaw gateway，請把 `OPENCLAW_BASE_URL` 指到該服務。

## 快速啟動

### 1. 建立 `.env`

在 repo 根目錄建立 `.env`。最小本機開發範例：

```env
LINE_ACCESS_TOKEN=
LINE_CHANNEL_SECRET=
OLLAMA_API_URL=http://127.0.0.1:11434/api/generate
OLLAMA_MODEL_NAME=qwen2:0.5b
ROUTER_ENABLED=true
LOG_LEVEL=INFO
SIDECAR_ENABLED=true
SIDECAR_MODE=mock
OPENCLAW_PHASE=suggest
OFFICIAL_SITE_RETRIEVAL_ENABLED=true
```

若要接 LINE，必須填入：

```env
LINE_ACCESS_TOKEN=你的_LINE_access_token
LINE_CHANNEL_SECRET=你的_LINE_channel_secret
PUBLIC_BASE_URL=https://你的公開網址
LINE_WEBHOOK_AUTO_UPDATE=true
WEBHOOK_SYNC_TOKEN=請換成自己的安全字串
```

### 2. 安裝相依套件

```bash
cd /home/myclaw/xlx-bot
python3 -m pip install --user -r requirements.txt
```

### 3. 準備 Ollama 模型

若使用本機 Ollama，請先啟動 Ollama，並拉取 `.env` 指定的模型：

```bash
ollama pull qwen2:0.5b
```

也可以改用其他模型，但 `.env` 的 `OLLAMA_MODEL_NAME` 必須一致。

### 4. 啟動 bot

```bash
python3 main.py
```

預設會啟動在：

```text
http://0.0.0.0:8080
```

### 5. 檢查健康狀態

```bash
curl http://127.0.0.1:8080/health
```

健康檢查會回報 LINE、provider、sidecar/OpenClaw、記憶目錄等狀態。若 `SIDECAR_ENABLED=true` 但 OpenClaw 設定不完整，health 會顯示 degraded 或 sidecar not ready。

## 使用 Docker Compose

Docker Compose 會啟動三個服務：

- `ollama-server`：Ollama 模型服務。
- `xlx-workstation`：Flask bot。
- `ngrok-tunnel`：本地公開網址，供 LINE webhook 使用。

啟動：

```bash
cd /home/myclaw/xlx-bot
docker compose up -d
```

查看服務：

```bash
docker compose ps
```

查看 bot 日誌：

```bash
docker logs xlx-bot
```

若你使用 compose 內的 Ollama，`.env` 可用：

```env
OLLAMA_API_URL=http://ollama-server:11434/api/generate
OLLAMA_MODEL_NAME=qwen2:0.5b
```

## 重要環境變數

LINE：

- `LINE_ACCESS_TOKEN`：LINE Messaging API access token。
- `LINE_CHANNEL_SECRET`：LINE channel secret。
- `PUBLIC_BASE_URL`：固定公開網址，會組成 `PUBLIC_BASE_URL + /callback`。
- `LINE_WEBHOOK_AUTO_UPDATE`：是否自動同步 LINE webhook。
- `WEBHOOK_SYNC_TOKEN`：手動同步 webhook 時使用的保護 token。
- `NGROK_API_URL`：ngrok API，例如 `http://127.0.0.1:4040/api/tunnels`。

模型與 provider：

- `OLLAMA_API_URL`：Ollama API endpoint。
- `OLLAMA_MODEL_NAME`：Ollama 模型名稱。
- `ROUTER_ENABLED`：是否啟用智慧路由。
- `ROUTER_MODEL_NAME`：路由分類使用模型。
- `GEMINI_API_KEY`：Gemini provider 金鑰。
- `GROQ_API_KEY`、`GROQ_MODEL_NAME`：Groq provider。
- `XAI_API_KEY`、`XAI_MODEL_NAME`：xAI provider。
- `GITHUB_MODELS_TOKEN`、`GITHUB_MODELS_NAME`：GitHub Models provider。
- `PROVIDER_TIMEOUT_SECONDS`：provider 請求 timeout。

OpenClaw / sidecar：

- `SIDECAR_ENABLED`：是否啟用 sidecar dispatcher。
- `SIDECAR_MODE`：`mock` 或 `openclaw`。
- `SIDECAR_TIMEOUT_SECONDS`：sidecar 呼叫 timeout。
- `OPENCLAW_BASE_URL`：OpenClaw gateway base URL。
- `OPENCLAW_ENDPOINT_PATH`：預設 `/v1/sidecar/dispatch`。
- `OPENCLAW_HEALTH_PATH`：預設 `/v1/openclaw/health`。
- `OPENCLAW_API_KEY`：OpenClaw bearer token，若 gateway 需要驗證才填。
- `OPENCLAW_PHASE`：`observe`、`suggest` 或 `assist`。
- `OPENCLAW_MAX_OUTPUTS`：單次查核最多回傳片段數。
- `OPENCLAW_CONFIDENCE_OK`：查核可信門檻。
- `OPENCLAW_CONFIDENCE_DEGRADED`：查核不足時的信心分數。
- `OPENCLAW_AUDIT_ENABLED`：是否產生 audit ref。
- `OPENCLAW_LEARNING_ENABLED`：是否允許查核結果進 pending review。
- `OPENCLAW_OFFICIAL_SOURCES`：逗號分隔的核可官方來源。
- `OFFICIAL_SITE_RETRIEVAL_ENABLED`：是否啟用官方網站查詢 helper。

記憶與日誌：

- `MEMORY_DIR`：預設 `memory`。
- `MEMORY_SUMMARIZE_ENABLED`：是否整理 lessons/troubleshooting。
- `LOG_FILE`：預設 `xlx-bot.log`。
- `LOG_LEVEL`：預設 `INFO`。
- `LOG_MAX_BYTES`、`LOG_BACKUP_COUNT`：log rotation 設定。

實驗功能：

- `AGENT_PATH_ENABLED`：啟用 agent path 實驗骨架。
- `TEACHING_PLANNER_ENABLED`：啟用回答前教學規劃提示。

## OpenClaw 驗證方式

啟動服務後，可先看 health：

```bash
curl http://127.0.0.1:8080/health
```

再看 OpenClaw health：

```bash
curl http://127.0.0.1:8080/v1/openclaw/health
```

測試 sidecar dispatch：

```bash
curl -X POST http://127.0.0.1:8080/v1/sidecar/dispatch \
  -H 'Content-Type: application/json' \
  -d '{
    "user_input": "請查詢本週課程",
    "task_type": "lookup",
    "intent": "COURSE_QUERY",
    "trace_id": "manual-test",
    "context": {
      "needs_official_lookup": true
    }
  }'
```

預期結果：

- `status` 應為 `ok` 或可解釋的 degraded/fallback。
- `outputs` 應提供查核或保守建議。
- `audit_ref` 應存在，方便追蹤。
- 若查不到官方資料，回答必須保守，不可假裝已查到。

## 回答與知識維護規則

正式社團事實來源優先順序：

1. `knowledge/` Markdown 檔。
2. `knowledge.txt`，若仍作為索引或補充。
3. OpenClaw 查到且可標示來源的已核可官方內容。
4. `skills/` 只提供回答方法與訓練技巧，不可當作最新社團事實。

維護 `knowledge/` 時請遵守：

- 一個主題一個檔案。
- 補資料要標明來源與最後確認日期。
- 不知道就保留 `[待補資料]` 或 `[目前知識庫沒有這項資訊]`。
- 現任幹部、最新公告、近期活動不得用推測補。
- OpenClaw 查到的新資料先進 pending review，不直接寫正式知識庫。

目前重要知識檔：

- `knowledge/10_club_basic.md`：社團基本資料。
- `knowledge/20_history.md`：社團沿革。
- `knowledge/30_org_structure.md`：組織架構模板。
- `knowledge/40_current_officers.md`：現任幹部，目前多數待補。
- `knowledge/50_programs_and_events.md`：課程與近期活動。
- `knowledge/60_announcements.md`：公告。
- `knowledge/70_culture.md`：社團文化。
- `knowledge/80_faq.md`：FAQ。
- `knowledge/90_club_manual.md`：規則、流程、職責模板。
- `knowledge/99_data_todo.md`：資料缺口。

## 測試

執行全部測試：

```bash
python3 -m unittest discover -s tests -v
```

目前測試涵蓋：

- 基本啟動與 health。
- LINE callback 與 webhook sync。
- router 與回答策略。
- 官方課表/公告查詢 helper。
- sidecar/OpenClaw dispatcher。
- agent path 與受控工具決策。

若只修改 README，通常不需要完整回歸測試；但若同時改了 router、provider、sidecar 或 config，請跑完整測試。

## 常見問題排查

`/health` 不通：

- 確認 `python3 main.py` 或容器是否正在執行。
- 確認 port 是 `8080`，或檢查 `FLASK_PORT`。

LINE 沒有回覆：

- 確認 `LINE_ACCESS_TOKEN` 與 `LINE_CHANNEL_SECRET`。
- 確認 webhook URL 是公開可達的 `https://.../callback`。
- 若使用 ngrok，確認公開網址變更後 webhook 已同步。

模型無法回答：

- 確認 Ollama 服務已啟動。
- 確認 `OLLAMA_API_URL` 與 `OLLAMA_MODEL_NAME` 正確。
- 若使用外部 provider，確認 API key 與模型名稱可用。

OpenClaw 沒有被呼叫：

- 確認 `SIDECAR_ENABLED=true`。
- 若使用真實 OpenClaw，確認 `SIDECAR_MODE=openclaw` 與 `OPENCLAW_BASE_URL`。
- 確認問題屬於需要官方查核的類型，例如最新、現任、公告、課程異動。
- 查看 `xlx-bot.log` 中的 `OPENCLAW_USAGE_CHECK` 與 `OPENCLAW_USAGE_DECISION`。

bot 亂答或編造：

- 先確認 `knowledge/` 是否有明確資料。
- 若本地不足，確認 OpenClaw 是否可查核已核可官方來源。
- 檢查回答是否把 `skills/` 的通用技巧誤當社團事實。
- 對最新與現任資訊，不能只靠舊知識或模型記憶。

## 目前限制

- 向量式 RAG 尚未完成。
- OpenClaw 查核結果不會自動寫入正式 `knowledge/`。
- 中高風險任務仍需 pending review 或禁止。
- LINE webhook 需要公開網址；本機未公開時只能測 health 與本機端點。
- 官方社群頁若因登入、反爬或網路限制無法讀取，系統必須保守回覆資料不足。

## 後續建議

- 補完整 OpenClaw 查核結果的人工審核流程。
- 補 `knowledge_schema.md` 與 `answering_rules.md`，讓知識維護與回答規則更集中。
- 補更多回答品質回歸測試，尤其是「最新、現任、公告、活動」類問題。
- 若導入 RAG，仍需保留來源、標題與本地優先規則。
