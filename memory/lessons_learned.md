# Lessons Learned（自動整理）

- 更新時間：2026-04-25
- 近期事件統計：ANSWER_SENT=25, ANSWER_WITH_INSUFFICIENT_DATA=2, TOOL_DECISION=6

## 回答前必做
- 優先回答使用者核心問題，避免離題。
- 若知識不足，直接回覆資料不足，不可補完推測。
- 涉及規則/課程/組織時先查 club_manual，查不到就明確拒答。

## 最近高頻失敗提醒
- allow_policy intent=knowledge_qa action=knowledge_lookup risk=low tool=knowledge_lookup（最近 3 次）
- insufficient_data（最近 2 次）
- pending_review_policy intent=command action=sidecar_dispatch risk=medium tool=sidecar_dispatch（最近 2 次）
