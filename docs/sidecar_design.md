# Sidecar Dispatcher Design（Phase 0/1）

本文件補充 sidecar dispatcher 的觸發、契約、錯誤處理與回退機制。
核心原則：**本地知識優先、OpenClaw 查核補足、不阻塞主流程、失敗可回退、回覆要保守**。

## 1) Request / Response Schema

### Request Schema

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

### Response Schema

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

---

## 2) Dispatcher 觸發條件

### 2.1 本地優先

以下 intent 先走本地回答流程；若本地知識不足、過期、只有待補標記或需要現況查核，必須呼叫 OpenClaw 查詢已核可官方來源：

- `FACT_QUERY`
- `MEMBER_QUERY`
- `ACTIVITY_QUERY`
- `ANNOUNCEMENT_QUERY`
- `HISTORY_INTRO`
- `GENERAL_OVERVIEW`

已核可官方來源優先包含：

- `https://tmc1974.com/`
- `https://tmc1974.com/schedule/`
- `https://tmc1974.com/leaders/`
- `https://tmc1974.com/board-members/`
- `https://www.instagram.com/taipeitoastmasters/`
- `https://www.youtube.com/user/1974toastmaster`
- `https://www.flickr.com/photos/133676498@N06/albums/`
- 官網公告與課程分類頁

### 2.2 任務型請求

當使用者輸入命中任務關鍵字時，也可觸發 sidecar：

- `lookup`：本地不足時查詢官方來源
- `analyze`：問題分析、資料交叉比對、來源確認
- `plan`：計畫、規劃、roadmap、里程碑
- `suggest`：建議、方案、草稿、怎麼做
- `debug`：debug、除錯、修復、錯誤、故障
- `project`：專案、任務、重構、整合

> OpenClaw 可用於低風險官方來源查核與中風險建議草稿；不得自動執行高風險動作或直接寫入正式 knowledge。

---

## 3) 超時策略（Timeout Policy）

- `SIDECAR_TIMEOUT_SECONDS` 預設為 `8` 秒。
- 只要超時即視為 sidecar 失敗（`E_SIDECAR_TIMEOUT`）。
- 超時後不得重試阻塞主線；直接記錄 warning 並走保守回答。
- webhook ACK 與 LINE reply 主流程不得等待 sidecar 完成。

---

## 4) 錯誤碼與語意（Error Codes）

| Error Code | 說明 | 系統行為 |
|---|---|---|
| `E_SIDECAR_TIMEOUT` | sidecar 呼叫逾時 | fallback 到保守回答 |
| `E_SIDECAR_UNAVAILABLE` | sidecar 連線失敗/不可用 | fallback 到保守回答 |
| `E_SIDECAR_BAD_RESPONSE` | sidecar 回傳格式不合法 | fallback 到保守回答 |
| `E_SIDECAR_EXCEPTION` | sidecar 執行期間拋出例外 | fallback 到保守回答 |
| `E_SIDECAR_DISABLED` | sidecar 功能關閉 | 僅能使用本地知識；不足時回覆查核服務不可用或資料不足 |

---

## 5) 回退機制（Fallback）

當 sidecar 失敗（timeout / exception / invalid response）時：

1. **必須回到保守回答路徑**（local-first + anti-hallucination）。
2. 對使用者輸出**保守訊息**，不可假裝 sidecar 成功。
3. 可附加簡短說明，例如：
   - 「目前官方查核服務暫時無法使用，我先依本地資料提供保守回答。」
4. 不得因 sidecar 失敗而遺失主流程回覆。

---

## 6) 不可攔截/阻塞的基本流程

sidecar 僅為輔助路徑，**不可攔截或阻塞**：

1. webhook ACK（接收事件後的快速確認）
2. LINE reply 基本流程（主路徑回覆）

換言之，sidecar 必須採「best effort」策略：成功時補充官方查核結果或建議，失敗時保守回退，不影響核心訊息處理可用性。
