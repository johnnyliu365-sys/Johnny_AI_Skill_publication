# Ticket Element 索引規範

`modules/element/` 是工單與實際程式碼之間的可審閱索引，不得複製正式原始碼。

固定路徑：`modules/element/<language>/<feature>/<ticket-id>/`。

- `typescript/`、`python/`、`java/` 為目前核准語言目錄。
- 每個 element 必須列出領域型別、應用流程、基礎設施、對外入口、實際原始碼路徑、公開契約、TDD 與驗證證據。
- element 與 ticket、SPEC、CHG 的引用必須可追溯；實際原始碼仍只能存在於既有語言根目錄。
