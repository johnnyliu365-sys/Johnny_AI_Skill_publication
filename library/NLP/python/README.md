# Python NLP 模組

此目錄是 Python NLP 實作的語言根目錄。各子模組須有自己的 README、明確 DTO、單元測試與不含網路的 fake provider 測試。

## 責任

- 使用 dataclass、Enum、Protocol 與顯式 nullability 表達所有公開資料契約。
- 在輸入邊界驗證動態文字資料，轉換後才交給規則或 provider port。
- 保持相同輸入、設定與 fixture 下的結果可重現。

## 公開模組

- `text_contracts/`：驗證與正規化文字、分類及欄位 DTO，以及具名拒絕結果。
- `rule_parser/`：以固定標記與分隔符擷取欄位，保留完整、不完整、歧義或拒絕理由，且不跨 frame 補值。
- `provider_ports/`：模型分析 provider 的請求、已驗證結果與失敗分類；只提供結構 validator 與不連網 fake adapter。

## 來源追溯

僅以使用者授權的 來源專案C、來源專案D 與 來源專案A 實作作行為參考；Python 檔案只能在本專案建立。

## 禁止用途

- 不得以 `Any`、未驗證 `dict` 或字串慣例跨公開模組邊界。
- 不得連線來源專案、外部模型、資料庫或訊息 Provider。
- 不得搬入來源專案的領域詞彙、業務規則、測試資料或 secrets。
