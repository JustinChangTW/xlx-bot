# Sidecar Trigger Rules（Phase 0/1）

## 1) 目標

以「主流程優先、失敗可回退」為核心，定義 sidecar 何時可建議啟用。

## 2) 不走 Sidecar（硬規則）

以下意圖一律走本地 answer path：

- `FACT`
- `CONCEPT`

理由：這兩類問題屬於知識查詢與說明，應遵循 knowledge-first + anti-hallucination 的本地流程。

## 3) 可建議走 Sidecar（軟規則）

以下意圖可建議走 sidecar（僅建議，不可強制）：

- `PROJECT`
- `DEBUG`

觸發後仍需滿足：

- `SIDECAR_ENABLED=true`
- sidecar 可用
- 不影響 webhook / LINE reply 主流程

## 4) Fallback（強制）

sidecar 若出現以下任一情況，必須立即回本地 answer path：

1. timeout
2. invalid response
3. service down

不得因 sidecar 失敗而中斷本地回答。

## 5) Non-goals（明定）

sidecar 不在本規則範圍內的能力：

1. 不接管 webhook
2. 不阻斷 LINE reply

## 6) Decision Matrix

| Intent | Sidecar Policy | 失敗時行為 |
|---|---|---|
| FACT | 禁止 | 本地 answer path |
| CONCEPT | 禁止 | 本地 answer path |
| PROJECT | 可建議 | 本地 answer path |
| DEBUG | 可建議 | 本地 answer path |
| OTHER | 預設不啟用（可由後續版本擴充） | 本地 answer path |
