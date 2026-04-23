# OpenClaw Sidecar Contract（Phase 0/1）

本文件定義 xlx-bot 與 sidecar 的最小契約，目標是「不破壞主流程、可回退、可審計」。

## Request Schema

```json
{
  "user_input": "string",
  "task_type": "plan|suggest|debug|project",
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
  "task_type": "plan|suggest|debug|project",
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

- Phase 1 僅允許 `suggest/plan/debug/project` 草案輸出
- 不允許自動 execute
- 高風險動作需 `requires_approval=true`
