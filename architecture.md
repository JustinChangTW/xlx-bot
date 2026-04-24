# 系統架構分析

本文件提供 Mermaid 可編輯版本，便於版本控管與後續維護。

> 備註：因 PR 流程限制（不納入二進位檔），本次僅保留文字與 Mermaid 原始碼。

## Mermaid（可編輯版本）

```mermaid
flowchart TD
    %% ========== 使用者層 ==========
    subgraph L1[使用者層]
        U[User<br/>使用者發送訊息]
    end

    %% ========== 平台層 ==========
    subgraph L2[平台層]
        MP[Messaging Platform / Chat Platform<br/>接收訊息並觸發 webhook]
    end

    %% ========== 入口層 ==========
    subgraph L3[入口層]
        WH[Webhook Endpoint / Bot Controller<br/>接收事件 / 驗證 / 回應 ACK]
    end

    %% ========== 路由層 ==========
    subgraph L4[路由層]
        EP[Event Parser<br/>解析事件與訊息內容]
        MR[Message Router<br/>判斷訊息類型與路徑]
        CD[Command Dispatcher<br/>分派命令到對應 Handler]
    end

    %% ========== 應用層 ==========
    subgraph L5[應用層]
        CH[Command Handlers<br/>處理指令與輸入驗證]
        AS[Application Services<br/>協調流程與業務邏輯]
    end

    %% ========== 核心邏輯層 ==========
    subgraph L6[核心邏輯層]
        DL[Domain Logic / Business Rules<br/>核心規則與邏輯處理]
    end

    %% ========== 整合層 ==========
    subgraph L7[整合層]
        OA[OpenAI API<br/>AI 推論與生成]
        TP[Third-party APIs<br/>外部服務整合]
        NS[Notification Services<br/>通知推播服務]
    end

    %% ========== 資料層 ==========
    subgraph L8[資料層]
        DB[Database<br/>持久化資料]
        CA[Cache<br/>快取提升效能]
        FS[File Storage<br/>檔案儲存]
    end

    %% ========== 支援層 ==========
    subgraph L9[支援層]
        CFG[Config<br/>系統設定管理]
        SEC[Secrets<br/>金鑰與憑證]
        LOG[Logging<br/>紀錄與追蹤]
        MON[Monitoring<br/>監控與告警]
    end

    %% ========== 主流程 ==========
    U -->|使用者送出訊息| MP
    MP -->|觸發 Webhook| WH
    WH -->|接收事件| EP
    EP --> MR
    MR --> CD
    CD -->|分派命令| CH
    CH --> AS
    AS --> DL

    %% ========== Service 呼叫 ==========
    AS -->|呼叫 API| OA
    AS -->|呼叫 API| TP
    AS -->|發送通知| NS

    AS -->|讀寫資料| DB
    AS --> CA
    AS --> FS

    %% ========== 回傳流程 ==========
    DL --> AS
    AS --> CH
    CH --> WH
    WH -->|回傳結果| MP
    MP --> U

    %% ========== 支援層關聯 ==========
    CFG -.-> WH
    SEC -.-> WH
    LOG -.-> AS
    MON -.-> AS
```

## Sidecar Dispatcher 設計（Phase 0/1）

為避免 sidecar 影響主流程，dispatcher 設計採用 **best effort + fail-open fallback**：

- 僅任務型請求觸發 sidecar；事實查詢與公告查詢預設不觸發。
- sidecar timeout / exception / invalid response 時，必須立即回到本地回答路徑。
- sidecar 不可攔截或阻塞 webhook ACK 與 LINE reply 基本流程。
- sidecar 失敗時，對使用者必須使用保守訊息（例如：建議服務暫時不可用，先提供本地保守回答）。

詳細 request/response schema、超時策略、錯誤碼與回退機制請見：`docs/sidecar_design.md`。

## Controlled OpenClaw / Tool Policy（目前實作）

目前程式已落地的控制鏈如下：

1. Router 先區分請求型態：
   - `knowledge_qa`
   - `command`
   - `error_report`
   - `user_correction`
   - `docs_request`
2. 每類請求都必須先對應已註冊工具（`config/tool_registry.yaml`）。
3. `policy_engine` 依工具風險做決策：
   - `low` -> 允許
   - `medium` -> `pending review`
   - `high` -> 禁止
4. `approval_gate` 將 policy 決策轉成最終回應與 fallback。
5. 所有 tool / sidecar / agent 決策都寫入 learning event，保留審計線索。

目前限制：

- 尚未完成真正的外部工具執行
- sidecar / OpenClaw 仍以建議與受控接線為主
- 高風險行為仍固定禁止
