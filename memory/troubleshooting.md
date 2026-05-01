# Troubleshooting（自動整理）

- 更新時間：2026-04-30

## 重複錯誤與建議處理
- allow_policy intent=knowledge_qa action=knowledge_lookup risk=low tool=knowledge_lookup（最近 51 次）
- openclaw_pending_review（最近 36 次）
- official-lookup（最近 33 次）
- pending_review_policy intent=command action=sidecar_dispatch risk=medium tool=sidecar_dispatch（最近 11 次）
- insufficient_data（最近 8 次）

## 建議
- 若同類錯誤連續發生，先檢查對應知識檔是否缺資料，並確認 OpenClaw 官方查核是否可用。
- 將新資訊先記錄到 pending review，不直接併入正式 knowledge。
