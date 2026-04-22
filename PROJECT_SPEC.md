# xlx-bot Project Spec

## 1. Project Purpose
xlx-bot 是一個以台北市健言社／小龍蝦社團知識為核心的聊天機器人。

主要用途：
- 回答社團相關問題
- 提供課程、規則、訓練、組織、活動等資訊
- 依據知識庫內容產生繁體中文回答
- 降低幻覺，避免答非所問

目前系統整合：
- Flask
- LINE Messaging API webhook
- LLM / Ollama provider
- knowledge/ 模組化知識檔案
- skills/ 模組化技能檔案
- memory/ 對話記憶

---

## 2. Core Product Goal
本專案的第一優先目標不是「回答很華麗」，而是：

1. 回答正確
2. 回答貼題
3. 沒有根據時不亂編
4. 知識結構可長期維護
5. 系統可穩定運作

---

## 3. Source of Truth
回答社團問題時，優先依據以下來源：

1. `knowledge/` 內的 Markdown 知識檔
2. `knowledge.txt`（若仍作為索引或補充）
3. `skills/` 內的回答規則與行為說明
4. `architecture.md`（僅用於開發理解，不作為社團事實回答來源）

注意：
- `architecture.md` 是系統架構文件，不是社團事實資料來源
- 若知識檔沒有明確記載，不可自行腦補事實

---

## 4. Current Product Problems
目前已知問題包括：

1. 社團知識不完整
   - 缺少或不足：社團沿革、組織架構、現任幹部、課程活動、花絮、公告、FAQ

2. Bot 容易幻覺
   - 在知識不足時仍會編造答案

3. Bot 容易答非所問
   - 沒有先對焦問題意圖
   - 會用泛泛介紹取代精準回答

4. 知識結構尚未完全以「查詢」為中心設計
   - 對 LLM 可讀，不一定對檢索最佳化

---

## 5. Expected Knowledge Design
知識系統應朝以下方向維護：

### Required Knowledge Categories
- 社團基本資料
- 社團沿革
- 組織架構
- 現任幹部
- 課程與活動
- 公告
- 花絮 / 社團文化
- FAQ
- 回答規則 / anti-hallucination rules

### Knowledge Design Principles
- 一主題一檔案或一區塊
- 標題清楚
- 內容可檢索
- 區分「目前資訊」與「歷史資訊」
- 缺資料時明確標示待補
- 不得用虛構資料補空白

---

## 6. Answering Rules
當 bot 回答問題時，必須遵守：

1. 只根據提供的知識內容回答
2. 若知識不足，直接說明資料不足
3. 不得把推測當成事實
4. 先回答使用者真正問的問題
5. 事實型問題：優先短答 + 依據
6. 介紹型問題：可整理成條列
7. 若問題包含「目前 / 最新 / 現任 / 最近」，優先找最新或現況資料
8. 找不到時不得自行生成人名、時間、活動、公告內容

---

## 7. Development Priorities
Codex 在此專案的修改優先順序：

1. 正確性
2. 可維護性
3. 可觀測性
4. 穩定性
5. 效能
6. UI / 美化

---

## 8. Non-Goals
除非任務明確要求，否則本專案目前不優先：

- 複雜前端 UI
- 大規模重構成微服務
- 引入不必要的大型框架
- 新增與社團知識無關的功能
- 為了看起來厲害而犧牲可維護性

---

## 9. Definition of Done
一個任務可視為完成，至少要符合：

1. 有明確對應到本專案目標
2. 修改範圍清楚且合理
3. 不破壞現有 bot 基本流程
4. 能說明修改原因
5. 能提供測試方式
6. 若涉及回答品質，需能說明如何降低幻覺或改善貼題性
7. 若資料仍不足，需留下 TODO 或待補標記

---

## 10. File Reading Priority for New Tasks
Codex 開始新任務時，應優先閱讀：

1. `README.md`
2. `architecture.md`
3. `PROJECT_SPEC.md`
4. `AGENTS.md`
5. `knowledge/`
6. `skills/`
7. 與當前任務直接相關的程式檔案

---

## 11. Required Output Format for Codex
每次任務都應以以下格式回報：

1. 需求理解
2. 現況分析
3. 問題點
4. 修改計畫
5. 會動到的檔案
6. 實際修改內容
7. 測試方式
8. 已知限制
9. 後續建議
