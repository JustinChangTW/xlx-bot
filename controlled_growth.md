# 受控自我成長機制（MVP）

## 目標
- 記錄使用者糾正、回答失敗、系統錯誤。
- 將事件整理為 lessons learned 與 troubleshooting。
- 在下次回答前先套用 lessons，降低重複犯錯。
- 本地知識不足時，透過 OpenClaw 查詢已核可官方來源，避免過早拒答或自行編造。
- OpenClaw 查到的答案先寫入 `learned_knowledge.txt` 的 `PENDING_REVIEW`，等待人工審核。
- 新知識先進入待審核區，不直接污染正式知識庫。

## 檔案
- `memory/learning_events.jsonl`：學習事件原始資料
- `memory/lessons_learned.md`：回答前提示
- `memory/troubleshooting.md`：重複錯誤建議
- `learned_knowledge.txt`：待審核知識（PENDING_REVIEW）

## 流程
1. 使用者輸入若像是更正語句，記錄 `USER_CORRECTION`。
2. 回答前先載入 `lessons_learned.md` 並注入 prompt。
3. 回答後記錄 `ANSWER_SENT`/`ANSWER_FAILURE`/`SYSTEM_ERROR`。
4. `<LEARNED>` 內容寫入 `learned_knowledge.txt`，標記 `PENDING_REVIEW`。
5. 每輪重建 lessons 與 troubleshooting（基於近期 events）。

## 安全邊界
- `learned_knowledge.txt` 不再被視為正式知識來源。
- 主要回答流程先使用 `knowledge/`，不足時使用 OpenClaw 查詢已核可官方來源。
- OpenClaw 查詢結果可用於當次回答，但寫入正式 `knowledge/` 前需人工審核。
- 自我學習的目標是讓 bot 越來越像成熟的台北市健言社前輩與老師：能拆解問題、確認來源、提醒限制，並給出可執行的下一步。

## 目前實作狀態
- 已完成：learning events、lessons、troubleshooting、自動重建
- 已完成：使用者更正與回答結果的事件記錄
- 已完成：待審核知識只寫入 `learned_knowledge.txt`
- 已完成：受控工具與 policy/approval 骨架
- 尚未完成：formal review workflow UI / 向量式 RAG / 核准後自動執行
