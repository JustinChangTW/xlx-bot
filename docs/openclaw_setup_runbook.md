# OpenClaw Setup Runbook

本文件記錄 xlx-bot 串接 OpenClaw 的安裝、啟動、驗證與故障排查流程。

定位：

- 這是維運 runbook，不是社團正式知識。
- 社團事實仍以 `knowledge/` 與 OpenClaw 查核到的官方來源為準。
- OpenClaw 查到的新資料只能進 pending review，不可直接寫入正式 `knowledge/`。

最後整理日期：2026-04-26

## 目前目標

xlx-bot 的 OpenClaw 整合目標是：

1. 本地 `knowledge/` 優先回答。
2. 本地資料不足、過期、只有待補標記，或問題涉及「目前 / 最新 / 現任 / 本週」時，透過 OpenClaw 查詢已核可官方來源。
3. OpenClaw 查核成功時，回答需帶可追溯來源。
4. OpenClaw 查核失敗時，回到保守回答，不可自行推測人名、公告、活動或時間。

## 重要路徑

```text
/home/myclaw/.openclaw/bin/openclaw
/home/myclaw/.openclaw/openclaw.json
/home/myclaw/xlx-bot/openclaw-workspace/
/home/myclaw/xlx-bot/openclaw-workspace/.openclaw/workspace-state.json
/tmp/openclaw-gateway.out
/tmp/xlx-bot.out
```

xlx-bot 相關程式：

```text
xlxbot/config.py
xlxbot/application.py
xlxbot/router.py
xlxbot/sidecar/dispatcher.py
xlxbot/sidecar/gateway.py
config/tool_registry.yaml
```

相關文件：

```text
docs/sidecar_contract.md
docs/sidecar_design.md
docs/sidecar_trigger_rules.md
```

## OpenClaw 設定重點

`/home/myclaw/.openclaw/openclaw.json` 目前重點設定：

```json
{
  "agents": {
    "defaults": {
      "workspace": "/home/myclaw/xlx-bot/openclaw-workspace"
    }
  },
  "gateway": {
    "mode": "local",
    "auth": {
      "mode": "token"
    },
    "port": 18789,
    "bind": "loopback"
  }
}
```

xlx-bot `.env` 需要的 OpenClaw / sidecar 設定：

```env
SIDECAR_ENABLED=true
SIDECAR_MODE=openclaw
OPENCLAW_BASE_URL=http://127.0.0.1:8080
OPENCLAW_ENDPOINT_PATH=/v1/sidecar/dispatch
OPENCLAW_HEALTH_PATH=/v1/openclaw/health
OPENCLAW_PHASE=suggest
OFFICIAL_SITE_RETRIEVAL_ENABLED=true
```

注意：目前 xlx-bot 的 `OPENCLAW_BASE_URL` 指向 `http://127.0.0.1:8080`，也就是 xlx-bot 自己提供的本機 OpenClaw-compatible HTTP endpoint：

- `GET /v1/openclaw/health`
- `POST /v1/sidecar/dispatch`

OpenClaw gateway 本身使用 WebSocket gateway：

```text
ws://127.0.0.1:18789
```

## 啟動流程

### 1. 補齊 OpenClaw runtime 目錄

第一次啟動時可能遇到 runtime deps 或 stability log 目錄不存在。先建立：

```bash
mkdir -p /home/myclaw/.openclaw/plugin-runtime-deps/openclaw-2026.4.23-8530132b1672/dist/extensions /home/myclaw/.openclaw/logs/stability
```

### 2. 啟動 OpenClaw gateway

建議用 `gateway run` 子命令長駐。若要背景執行：

```bash
setsid /home/myclaw/.openclaw/bin/openclaw gateway run --force --port 18789 >/tmp/openclaw-gateway.out 2>&1 < /dev/null &
```

查看 log：

```bash
tail -n 80 /tmp/openclaw-gateway.out
```

看到類似以下內容表示 gateway 已完成啟動：

```text
[gateway] ready
[browser/server] Browser control listening on http://127.0.0.1:18791/ (auth=token)
```

### 3. 檢查 OpenClaw gateway

```bash
/home/myclaw/.openclaw/bin/openclaw health
/home/myclaw/.openclaw/bin/openclaw status
```

健康狀態正常時，`status` 應顯示：

```text
Gateway local · ws://127.0.0.1:18789 ... reachable
```

### 4. 啟動 xlx-bot

```bash
cd /home/myclaw/xlx-bot
setsid python3 main.py >/tmp/xlx-bot.out 2>&1 < /dev/null &
```

查看 bot log：

```bash
tail -n 80 /tmp/xlx-bot.out
```

正常啟動時應看到：

```text
All environment checks passed. Starting bot...
Starting Flask app on 0.0.0.0:8080
Running on http://127.0.0.1:8080
```

## 驗證指令

### xlx-bot health

```bash
python3 -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5); print(r.status); print(r.read().decode()[:2000])"
```

預期重點：

```json
{
  "status": "ok",
  "checks": {
    "sidecar": {
      "enabled": true,
      "mode": "openclaw",
      "phase": "suggest",
      "ready": true,
      "missing": []
    }
  }
}
```

### xlx-bot OpenClaw health

```bash
python3 -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/v1/openclaw/health', timeout=5); print(r.status); print(r.read().decode()[:2000])"
```

預期重點：

```json
{
  "status": "ok",
  "gateway": "local-openclaw",
  "mode": "openclaw",
  "phase": "suggest",
  "ready": true,
  "missing": []
}
```

### sidecar dispatch 查核測試

```bash
python3 -c "import json, urllib.request; payload=json.dumps({'user_input':'現在社長是誰？','task_type':'lookup','intent':'MEMBER_QUERY','trace_id':'manual-president-check','context':{}}).encode(); req=urllib.request.Request('http://127.0.0.1:8080/v1/sidecar/dispatch', data=payload, headers={'Content-Type':'application/json'}, method='POST'); data=json.loads(urllib.request.urlopen(req, timeout=10).read().decode()); print(json.dumps(data, ensure_ascii=False, indent=2)[:5000])"
```

2026-04-26 的實測結果重點：

```json
{
  "status": "ok",
  "task_type": "lookup",
  "confidence": 0.84,
  "risk_level": "low",
  "requires_approval": false
}
```

輸出曾成功包含官方頁面：

```text
https://tmc1974.com/leaders/
楊朝富 第159期社長
```

注意：這類新查核結果可作為單次回答依據，但正式寫入 `knowledge/40_current_officers.md` 前仍需人工審核。

## 實際遇到的問題與處理

### 問題 1：OpenClaw 已安裝但 gateway unreachable

現象：

```text
Gateway local · ws://127.0.0.1:18789 ... unreachable
```

或：

```text
gateway closed (1006 abnormal closure)
```

處理：

1. 確認 `/home/myclaw/.openclaw/openclaw.json` 存在。
2. 建立 runtime 目錄。
3. 用 `openclaw gateway run --force --port 18789` 重啟 gateway。
4. 等 log 出現 `[gateway] ready` 後再跑 health。

### 問題 2：缺少 plugin runtime deps 目錄

現象：

```text
failed to install bundled runtime deps
ENOENT: no such file or directory, mkdir '/home/myclaw/.openclaw/plugin-runtime-deps/...'
failed to write stability bundle
```

處理：

```bash
mkdir -p /home/myclaw/.openclaw/plugin-runtime-deps/openclaw-2026.4.23-8530132b1672/dist/extensions /home/myclaw/.openclaw/logs/stability
```

### 問題 3：在 sandbox 內檢查 port 或 curl 失敗

現象：

```text
Cannot open netlink socket: Operation not permitted
snap-confine is packaged without necessary permissions
PermissionError: [Errno 1] Operation not permitted
```

原因：

- Codex sandbox 內限制網路/socket/netlink。
- `/snap/bin/curl` 或 snap-confine 在 sandbox 內可能無法執行。

處理：

- 需要 host socket 或本機 HTTP 檢查時，用核准後的 sandbox 外命令。
- 避免用 snap curl；可改用 Python `urllib.request`。

### 問題 4：gateway 啟動太早檢查會誤判

現象：

```text
gateway closed (1006 abnormal closure)
connect ECONNREFUSED 127.0.0.1:18789
```

原因：

- OpenClaw gateway 第一次啟動會安裝 bundled runtime deps。
- 在 log 出現 `[gateway] ready` 前打 health 可能失敗。

處理：

```bash
tail -n 80 /tmp/openclaw-gateway.out
/home/myclaw/.openclaw/bin/openclaw health
```

等 ready 後再驗證。

### 問題 5：`openclaw gateway --port 18789` 不適合背景長駐

現象：

- 直接跑 `openclaw gateway --port 18789` 可進入啟動流程，但不如 `gateway run` 明確。
- 用背景方式啟動時，PID 可能很快退出。

處理：

使用文件列出的子命令：

```bash
setsid /home/myclaw/.openclaw/bin/openclaw gateway run --force --port 18789 >/tmp/openclaw-gateway.out 2>&1 < /dev/null &
```

### 問題 6：OpenClaw workspace 尚未完成 bootstrap

現象：

```text
Agents 1 · 1 bootstrap file present
```

且檔案仍存在：

```text
openclaw-workspace/BOOTSTRAP.md
```

意義：

- OpenClaw gateway 可以啟動。
- 但 workspace 的初始身份、記憶與長期設定尚未完成。

後續可處理：

1. 完成 `openclaw-workspace/IDENTITY.md`、`USER.md`、`SOUL.md` 的初始化。
2. 確認是否需要刪除 `BOOTSTRAP.md`。
3. 再檢查 `openclaw status` 中的 memory 狀態。

## 常用檢查指令

查 OpenClaw 狀態：

```bash
/home/myclaw/.openclaw/bin/openclaw status
/home/myclaw/.openclaw/bin/openclaw health
```

查 gateway log：

```bash
tail -n 80 /tmp/openclaw-gateway.out
```

查 bot log：

```bash
tail -n 80 /tmp/xlx-bot.out
```

查程序：

```bash
ps -ef | rg 'openclaw|python3 main.py|ngrok'
```

查 Git 狀態：

```bash
git status --short
```

## 已知限制

- OpenClaw 查核到的新資料不會自動寫入正式 `knowledge/`。
- `formal_knowledge_write`、`code_change`、`deploy` 屬高風險工具，預設禁止或需人工核准。
- OpenClaw workspace bootstrap 尚未完成時，agent 記憶與個人化能力可能不可用。
- 若 gateway 未啟動，xlx-bot 仍應走保守 fallback，不得生成未查核事實。

## 建議下一步

1. 完成 OpenClaw workspace bootstrap。
2. 從 LINE 實際發問「現在社長是誰？」驗證完整 webhook 路徑。
3. 若回答正確，再檢查 `learned_knowledge.txt` 是否正確記錄 pending review。
4. 規劃人工審核流程，再決定是否把查核結果整理進 `knowledge/40_current_officers.md`。
