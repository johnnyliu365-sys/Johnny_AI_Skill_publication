# NLP Provider 邊界

## 責任

定義不連網的模型／多模態分析 provider port、文字分析請求、已驗證成功結果、具名失敗分類，以及唯一可接收原始 payload 的結構 validator。所有公開結果都以 DTO、Enum 或具名值物件表示。

## 公用方式

呼叫端建立 `TextAnalysisRequest` 後，僅透過 `AnalysisProviderPort.analyze` 取得 `ProviderSuccess` 或 `ProviderFailure`。測試可使用 `FakeAnalysisProvider` 模擬成功、暫時失敗、永久失敗、逾時、驗證失敗與限流。

實體 adapter 若必須處理 JSON，必須立即在 `ProviderPayloadValidator.validate(raw_payload, request)` 完成驗證；原始 `object` 不得進入其他公開模型或領域邏輯。未知欄位、缺欄、未允許標籤與不合法信心值一律回傳 `INVALID_STRUCTURE`。

## 來源追溯

設計僅參考 來源專案A `來源專案的AI服務層` 的錯誤分類與結構化輸出邊界。未複製 prompt、健康／營養規則、影像資料、HTTP 實作、API key 或來源專案程式碼；所有來源專案持續唯讀。

## 禁止用途

本模組不含 Gemini 或任何真實 provider、HTTP、圖片／影像資料、憑證、prompt、個人化、營養或健康規則。它不是可直接上線的 provider adapter。
