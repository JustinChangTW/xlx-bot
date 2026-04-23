# OpenClaw Sidecar Contract（Phase 0/1）

本文件定義 xlx-bot 與 sidecar 的最小契約，目標是「不破壞主流程、可回退、可審計」。

## 1) Request Schema

```json
{
  "trace_id": "string",
  "timestamp": "2026-04-23T12:34:56Z",
  "user_input": "string",
  "intent": "PROJECT|DEBUG|FACT|CONCEPT|OTHER",
  "task_type": "project|debug|suggest|plan",
  "context": {
    "route_intent": "string",
    "locale": "zh-TW"
  },
  "audit": {
    "caller": "xlx-bot",
    "session_id": "string",
    "request_id": "string"
  }
}
```

## 2) Response Schema

```json
{
  "trace_id": "string",
  "status": "ok|degraded|failed",
  "task_type": "project|debug|suggest|plan",
  "confidence": 0.66,
  "outputs": ["string"],
  "risk_level": "low|medium|high",
  "requires_approval": true,
  "error": {
    "code": "E_SIDECAR_TIMEOUT",
    "message": "string"
  },
  "audit": {
    "provider": "sidecar-mock",
    "latency_ms": 1200,
    "decision_ref": "string"
  }
}
```

## 3) Error Codes

| Error Code | 意義 | 必要行為 |
|---|---|---|
| `E_SIDECAR_TIMEOUT` | sidecar 逾時 | 立即 fallback 到本地 answer path |
| `E_SIDECAR_BAD_RESPONSE` | 回傳 schema 不合法或欄位缺漏 | 立即 fallback 到本地 answer path |
| `E_SIDECAR_UNAVAILABLE` | sidecar service down / 連線失敗 | 立即 fallback 到本地 answer path |
| `E_SIDECAR_EXCEPTION` | sidecar 執行中例外 | 立即 fallback 到本地 answer path |
| `E_SIDECAR_DISABLED` | sidecar 關閉 | 直接走本地 answer path（非錯誤） |

## 4) Fallback Policy（明定）

以下情境一律回到本地 answer path，不可嘗試攔截主流程：

1. timeout
2. invalid response
3. service down

可附帶保守訊息（例如「建議服務暫時不可用，先提供本地回答」），但不得假裝 sidecar 成功。

## 5) Audit 欄位要求

Request/Response 都必須帶 `audit` 欄位：

- Request audit：追蹤呼叫來源與請求識別（`caller/session_id/request_id`）
- Response audit：追蹤執行結果（`provider/latency_ms/decision_ref`）

若缺少必要 audit 欄位，視為 `E_SIDECAR_BAD_RESPONSE`。

## 6) Non-goals（明定）

sidecar 在 Phase 0/1 **不負責也不得接管**：

1. webhook 接收與 ACK
2. LINE reply 主回覆流程

換言之：sidecar 是 best-effort 建議器，不是主流程控制器。
