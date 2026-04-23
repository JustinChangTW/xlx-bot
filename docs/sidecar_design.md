# Sidecar Dispatcher Design（Phase 0/1）

本文件補充 sidecar dispatcher 的觸發、契約、錯誤處理與回退機制。
核心原則：**不阻塞主流程、失敗可回退、回覆要保守**。

## 1) Request / Response Schema

### Request Schema

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

### Response Schema

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

---

## 2) Dispatcher 觸發條件

### 2.1 預設不觸發（主流程優先）

以下 intent 一律走本地回答流程，不呼叫 sidecar：

- `FACT_QUERY`
- `MEMBER_QUERY`
- `ACTIVITY_QUERY`
- `ANNOUNCEMENT_QUERY`
- `HISTORY_INTRO`
- `GENERAL_OVERVIEW`

### 2.2 可觸發（任務型請求）

當使用者輸入命中任務關鍵字時，可觸發 sidecar：

- `plan`：計畫、規劃、roadmap、里程碑
- `suggest`：建議、方案、草稿、怎麼做
- `debug`：debug、除錯、修復、錯誤、故障
- `project`：專案、任務、重構、整合

> sidecar 在 Phase 0/1 僅可輸出「建議草稿」，不得自動執行動作。

---

## 3) 超時策略（Timeout Policy）

- `SIDECAR_TIMEOUT_SECONDS` 預設為 `8` 秒。
- 只要超時即視為 sidecar 失敗（`E_SIDECAR_TIMEOUT`）。
- 超時後不得重試阻塞主線；直接記錄 warning 並走本地回答。
- webhook ACK 與 LINE reply 主流程不得等待 sidecar 完成。

---

## 4) 錯誤碼與語意（Error Codes）

| Error Code | 說明 | 系統行為 |
|---|---|---|
| `E_SIDECAR_TIMEOUT` | sidecar 呼叫逾時 | 立即 fallback 到本地回答 |
| `E_SIDECAR_UNAVAILABLE` | sidecar 連線失敗/不可用 | 立即 fallback 到本地回答 |
| `E_SIDECAR_BAD_RESPONSE` | sidecar 回傳格式不合法 | 立即 fallback 到本地回答 |
| `E_SIDECAR_EXCEPTION` | sidecar 執行期間拋出例外 | 立即 fallback 到本地回答 |
| `E_SIDECAR_DISABLED` | sidecar 功能關閉 | 直接走本地回答（非錯誤） |

---

## 5) 回退機制（Fallback）

當 sidecar 失敗（timeout / exception / invalid response）時：

1. **必須回到本地回答路徑**（knowledge-first + anti-hallucination）。
2. 對使用者輸出**保守訊息**，不可假裝 sidecar 成功。
3. 可附加簡短說明，例如：
   - 「目前建議服務暫時無法使用，我先依現有資料提供保守建議。」
4. 不得因 sidecar 失敗而遺失主流程回覆。

---

## 6) 不可攔截/阻塞的基本流程

sidecar 僅為輔助路徑，**不可攔截或阻塞**：

1. webhook ACK（接收事件後的快速確認）
2. LINE reply 基本流程（主路徑回覆）

換言之，sidecar 必須採「best effort」策略：成功時補充建議，失敗時靜默回退，不影響核心訊息處理可用性。
