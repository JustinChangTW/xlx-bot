# Troubleshooting（自動整理）

- 更新時間：2026-04-25

## 重複錯誤與建議處理
- allow_policy intent=knowledge_qa action=knowledge_lookup risk=low tool=knowledge_lookup（最近 3 次）
- insufficient_data（最近 2 次）
- pending_review_policy intent=command action=sidecar_dispatch risk=medium tool=sidecar_dispatch（最近 2 次）

## 建議
- 若同類錯誤連續發生，先檢查對應知識檔是否缺資料。
- 將新資訊先記錄到 pending review，不直接併入正式 knowledge。
