# Sidecar Trigger Rules（Phase 0/1）

## 原則

1. 先保住主流程（knowledge-first + anti-hallucination）
2. sidecar 只處理任務型需求，且先給建議草稿
3. sidecar 失敗必須可無痛回退

## 預設不觸發 sidecar

- FACT_QUERY
- MEMBER_QUERY
- ACTIVITY_QUERY
- ANNOUNCEMENT_QUERY
- HISTORY_INTRO
- GENERAL_OVERVIEW

以上類型以既有回答流程為主。

## 可觸發 sidecar（關鍵字命中）

- plan：計畫、規劃、roadmap、里程碑
- suggest：建議、方案、草稿、怎麼做
- debug：debug、除錯、修復、錯誤、故障
- project：專案、任務、重構、整合

## Fallback 規則

- 若 sidecar timeout / failed / invalid，記錄 warning 後回既有流程
- 不可因 sidecar 出錯導致使用者收不到主流程回覆

## 版本策略

- `SIDECAR_ENABLED=false`：完全不觸發（預設）
- `SIDECAR_ENABLED=true` + `SIDECAR_MODE=mock`：只提供建議草稿
- `SIDECAR_ENABLED=true` + `SIDECAR_MODE=openclaw`：呼叫 OpenClaw gateway（仍僅提供建議，不自動執行）
