# NLP 規則式欄位抽取器

## 責任

以固定、可解釋的標記與分隔符，從 `NormalizedText` 擷取同一 frame 內的具名欄位。結果一律包含 `COMPLETE`、`INCOMPLETE`、`AMBIGUOUS` 或 `REJECTED` 狀態，以及可機器判讀的解析理由。

## 公用方式

以 `FieldRule` 定義欄位名稱與標記、以 `RuleSet` 定義欄位及 frame 分隔符，再呼叫 `parse_fields`。例如規則 `pickup=`、`dropoff=` 搭配 `;` 與 `|`，可解析 `pickup=Home;dropoff=Station`。

同一 frame 的全部必填欄位才可得到 `COMPLETE`。跨 frame 出現的欄位不會合併；缺欄位、重複標記、空值或未知內容會得到明確理由，不補造資料。

## 來源追溯

設計僅參考 來源專案C 的訊息／frame 邊界規則與 來源專案D 的客戶輸入 parser 邊界。未複製、搬移或連結任何來源專案程式碼；所有來源專案持續唯讀。

## 禁止用途

本模組不辨識自由意圖、不呼叫 LLM、HTTP、LINE、資料庫或派單系統，也不包含地址資料、業務規則或自動執行動作。
