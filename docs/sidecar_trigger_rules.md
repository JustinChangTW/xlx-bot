# Sidecar Trigger Rules（Phase 0/1）

## 原則

1. 先保住主流程（local-first + anti-hallucination）
2. sidecar / OpenClaw 處理本地不足的官方來源查核，也處理任務型建議草稿
3. sidecar 失敗必須可無痛回退

## 本地優先，必要時觸發 sidecar

- FACT_QUERY
- MEMBER_QUERY
- ACTIVITY_QUERY
- ANNOUNCEMENT_QUERY
- HISTORY_INTRO
- GENERAL_OVERVIEW

以上類型先查本地 `knowledge/`。若本地資料不足、過期、只有待補標記，或使用者詢問「現任 / 最新 / 最近 / 本週」等現況資訊，應透過 OpenClaw 查詢已核可官方來源。

## 可觸發 sidecar（關鍵字命中）

- plan：計畫、規劃、roadmap、里程碑
- suggest：建議、方案、草稿、怎麼做
- debug：debug、除錯、修復、錯誤、故障
- project：專案、任務、重構、整合
- lookup：本地不足時查詢官方來源
- analyze：問題分析、資料交叉比對、來源確認

## Fallback 規則

- 若 sidecar timeout / failed / invalid，記錄 warning 後回保守回答流程
- 不可因 sidecar 出錯導致使用者收不到主流程回覆

## 版本策略

- `SIDECAR_ENABLED=false`：不觸發 OpenClaw，只能依本地知識保守回答
- `SIDECAR_ENABLED=true` + `SIDECAR_MODE=mock`：只提供建議草稿
- `SIDECAR_ENABLED=true` + `SIDECAR_MODE=openclaw`：呼叫 OpenClaw gateway，可做官方來源查核與建議草稿，但不自動執行高風險動作或寫入正式 knowledge
