# NLP 文字契約

## 責任

提供純 Python、不可變且強型別的文字輸入、正規化結果、分類結果與欄位擷取 DTO。`normalize_text` 是唯一文字驗證入口：只接受已在本地驗證的來源，並以具名拒絕原因 fail closed。

## 公用方式

匯入 `library.NLP.python.text_contracts` 後，先建立 `TextInput`，再呼叫 `normalize_text`。呼叫端必須以 `NormalizationAccepted` 或 `NormalizationRejected` 分支處理結果；不得以例外或未驗證的 `dict`、字串慣例傳遞文字狀態。

## 驗證規則

- 空白、控制字元、正規化後超過 2,000 個字元，皆回傳 `NormalizationRejected`。
- `EXTERNAL_UNVALIDATED` 一律回傳 `UNVALIDATED_ORIGIN`；外部資料必須先在自己的邊界完成驗證。
- 接受的文字會以 Unicode NFKC、空白折疊與前後截除正規化，因而可重複套用並取得穩定結果。

## 來源追溯

設計僅參考 來源專案C 的訂單文字契約與 來源專案D 的客戶輸入結果模型。未複製、搬移或連結任何來源專案的程式碼；所有來源專案持續唯讀。

## 禁止用途

本模組不解析業務意圖、不呼叫 LLM 或 HTTP、不存取資料庫，也不判定派單、健康、支付或身分狀態。
