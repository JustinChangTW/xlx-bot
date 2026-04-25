# Lessons Learned（自動整理）

- 更新時間：2026-04-25
- 近期事件統計：ANSWER_SENT=40, ANSWER_WITH_INSUFFICIENT_DATA=8, TOOL_DECISION=21, SIDECAR_DECISION=2, OPENCLAW_LEARNING_CAPTURED=4, PENDING_KNOWLEDGE_CAPTURED=1

## 回答前必做
- 優先回答使用者核心問題，避免離題。
- 若本地知識不足，先透過 OpenClaw 查詢已核可官方來源；仍不足才回覆資料不足，不可補完推測。
- 涉及規則/課程/組織時先查 club_manual，查不到就透過 OpenClaw 查核官方來源；仍不足才明確拒答。

## 最近高頻失敗提醒
- allow_policy intent=knowledge_qa action=knowledge_lookup risk=low tool=knowledge_lookup（最近 16 次）
- insufficient_data（最近 8 次）
- openclaw_pending_review（最近 4 次）
- missing_env_constraints:SIDECAR_ENABLED（最近 3 次）
- pending_review_policy intent=command action=sidecar_dispatch risk=medium tool=sidecar_dispatch（最近 2 次）
