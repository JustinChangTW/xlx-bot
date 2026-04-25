# OpenClaw Sidecar Contract（Phase 0/1）

本文件定義 xlx-bot 與 sidecar 的最小契約，目標是「本地知識優先、OpenClaw 查核補足、不破壞主流程、可回退、可審計」。

## Request Schema

```json
{
  "user_input": "string",
  "task_type": "lookup|analyze|plan|suggest|debug|project",
  "intent": "string",
  "trace_id": "string",
  "context": {
    "route_intent": "string"
  }
}
```

## Response Schema

```json
{
  "status": "ok|degraded|failed",
  "task_type": "lookup|analyze|plan|suggest|debug|project",
  "confidence": 0.66,
  "outputs": ["string"],
  "risk_level": "low|medium|high",
  "requires_approval": true,
  "audit_ref": "string",
  "error": "string"
}
```

## Error Handling

- timeout / exception / invalid response 一律視為 `failed`
- 主系統必須 fallback 到既有回答路徑
- sidecar 不可阻斷 LINE webhook ack 與回覆

## Safety Constraints

- OpenClaw 可用於低風險官方來源查核與問題分析，以及 `lookup/analyze/suggest/plan/debug/project` 草案輸出
- 不允許自動 execute
- 高風險動作與正式 knowledge 寫入需 `requires_approval=true`


## Runtime Config (Phase 2)

- `SIDECAR_MODE=openclaw` 時，需設定 `OPENCLAW_BASE_URL`。
- 可用 `OPENCLAW_ENDPOINT_PATH` 指定 dispatch API 路徑。
- 可用 `OPENCLAW_API_KEY` 傳送 bearer token。
