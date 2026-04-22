# xlx-bot AGENTS.md

## Mission
你正在協助維護 `xlx-bot` 專案。

本專案最重要的原則：
- 先理解，再修改
- 先正確，再完整
- 先可用，再優化
- 不亂編，不亂改，不亂擴充

---

## Mandatory Workflow
每次接手新任務時，必須依照以下流程：

### Step 1 — Read Before Edit
先閱讀下列檔案，再開始任何修改：

1. `README.md`
2. `architecture.md`
3. `.codex/PROJECT_SPEC.md`
4. `.codex/AGENTS.md`
5. `knowledge/` 目錄
6. `skills/` 目錄
7. 與任務直接相關的 Python 檔案

在完成閱讀前，不要直接改程式碼。

---

### Step 2 — Restate Understanding
先用自己的話整理：

1. 這個專案的目標
2. 這次任務的目標
3. 目前系統大致流程
4. 可能的風險與限制

若需求不清楚，先指出不確定點，不要自行假設。

---

### Step 3 — Plan Before Edit
開始修改前，必須先列出：

1. 最小可行修改方案
2. 會修改哪些檔案
3. 每個檔案為什麼要改
4. 如何驗證修改是否成功

若任務很大，優先拆成小步驟。

---

### Step 4 — Edit Conservatively
修改原則：

- 小步修改
- 優先局部調整
- 優先沿用現有結構
- 除非必要，不大改架構
- 除非任務要求，不新增無關功能

---

### Step 5 — Report Clearly
修改完成後，必須提供：

1. 需求理解
2. 問題分析
3. 修改內容
4. 修改檔案清單
5. 測試方式
6. 已知限制
7. 後續建議

---

## Project-Specific Priorities

### Priority 1: Reduce hallucination
若任務涉及 bot 回答，第一優先是降低幻覺：
- 僅依據知識回答
- 無資料時明確說資料不足
- 不得自造人名、活動、時間、幹部、公告

### Priority 2: Improve answer relevance
若任務涉及回答品質：
- 先對焦使用者問題
- 不要用空泛介紹取代精準回答
- 事實查詢優先短答
- 再視需要補充

### Priority 3: Keep knowledge maintainable
若任務涉及知識庫：
- 保持 Markdown 可讀性
- 結構清楚
- 支援未來持續擴充
- 缺資料時用待補標記，而不是虛構內容

---

## Forbidden Behaviors
除非使用者明確要求，否則禁止：

- 不經分析直接大改
- 隨意重命名大量檔案
- 引入過重依賴
- 為了炫技新增複雜架構
- 修改與任務無關的檔案
- 自行虛構社團資料
- 把推測寫成事實

---

## When Working on Knowledge
若任務與社團知識有關：

1. 先檢查 `knowledge/` 現有結構
2. 判斷缺的是內容、格式、還是檢索方式
3. 優先補強結構與回答規則
4. 缺少真實資料時，用明確 TODO / 待補資料標記
5. 不可自行補造「現任幹部」「最新公告」「課程活動」等真實資訊

---

## When Working on Answer Flow
若任務與回答流程有關：

1. 優先檢查 prompt 組裝方式
2. 檢查是否有明確 anti-hallucination 規則
3. 檢查是否有根據問題類型分流
4. 檢查是否有「找不到就拒答 / 資料不足」機制
5. 回答設計要先短答再補充

---

## When Working on Retrieval / RAG
若任務與 RAG 或檢索有關：

1. 知識切段要保留標題與來源
2. 回答時只用最相關片段
3. 若檢索結果不足，不可硬答
4. 優先做最小可行版本
5. 不要為了導入 RAG 而把專案搞複雜

---

## Preferred Response Style
對使用者回報時：

- 直接
- 清楚
- 結構化
- 不空談
- 不模糊
- 不誇大成果

---

## Approval Rule
若使用者要求先分析再動手，則在獲得明確許可前，不得開始實作。

建議等待以下類型訊號後再改：
- 「開始實作」
- 「請修改」
- 「照這個方案做」

---

## Default Task Split
若任務過大，優先拆成以下類型：

- knowledge 重構
- answer flow 修正
- anti-hallucination 規則
- retrieval / RAG
- bug fix
- deployment / config

不要一次把多個大任務混在同一次修改。