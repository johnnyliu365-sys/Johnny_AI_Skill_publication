# NLP 功能集群

本目錄放置可解釋的文字理解能力，以及可插拔且預設停用的模型／多模態 provider 邊界。

## 責任

- 定義文字輸入、正規化結果、欄位抽取結果與歧義結果的強型別契約。
- 提供規則式、可重現的分類與欄位抽取能力。
- 為未來模型 provider 提供驗證與 fail-closed 的 port，不綁定特定模型供應商。

## 公開模組規劃

- `python/text_contracts/`：文字與欄位 DTO、正規化與驗證。
- `python/rule_parser/`：規則式分類與欄位抽取。
- `python/provider_ports/`：fake-backed 的模型／多模態 provider 契約。

## 來源追溯

參考 來源專案C 的規則式訂單文字解析、來源專案D 的文字 evidence／收件解析，以及 來源專案A 的結構化 AI 結果與失敗分類；所有實作均在本專案重新建立。

## 禁止用途

- 不得複製或修改任一來源 parser、模型服務、prompt、圖片、LINE webhook 或資料庫。
- 不得讓模型輸出自行補造領域事實、控制對外訊息或改變來源專案行為。
- 不得使用真實 API key、影像、使用者文字或個人資料做測試。
