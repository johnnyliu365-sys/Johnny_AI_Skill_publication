# 通用功能模組庫

本目錄保存只在本專案重新實作、可跨專案套用的功能模組。它不包含任何來源專案的程式碼複本、設定、資料、憑證或部署內容。

## 責任

- 提供樹狀索引，不在根目錄重複展開每張模組卡。
- 對每個模組記錄公開契約、相依、測試命令、來源追溯與適用限制。
- 讓後續工單在獨立資料夾內實作強型別、可測試的通用能力。

## AI 最小載入入口

新 Agent 不得先讀完整 `library/`。先讀取 [MODULE_CATALOG.md](MODULE_CATALOG.md)，再沿一個 capability partition 到一個 exact leaf；只載入命中 leaf 指定的 README、公開 `__init__.py` 與必要契約。正式採用仍須走目標專案自己的 Wayfinder、Grill、SPEC 與 ticket。

## 目錄

- `NLP/`：規則式文字理解、欄位抽取與模型 provider 邊界。
- `金流串接/`：付款契約、帳本、fake provider 與對帳能力。
- `功能集群/`：可靠性、訊息 transport、事件時間線、互動規則、地理與遊戲規則能力。
- `workflow_router/`、`local_orchestration/`：流程控制與本機 orchestration 邊界。

## 來源追溯

設計參考僅來自使用者授權的 來源專案A、來源專案B、來源專案C 與 來源專案D 本機專案；它們永遠是唯讀來源。

## 禁止用途

- 不得修改、搬移、新增或刪除任何來源專案的檔案。
- 不得複製來源專案的原始碼、資料、schema、環境檔、秘密、PII、Provider 設定或測試資料。
- 不得以本目錄程式直接發送 LINE 訊息、付款、退款、部署、連線資料庫或呼叫真實 AI Provider。
