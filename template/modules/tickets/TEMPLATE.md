# NN｜<垂直切片名稱>

| 欄位 | 內容 |
| --- | --- |
| 對應規格 ID | 完整 `SPEC-<PROJECT>-<FEATURE>-<YYYYMMDD>-<ULID>`（`§x、AC-y`） |
| 規格撰寫 AI | `<AI>` |
| 第一步排查起點 | `doc/context/<feature>/<worktree-id>.md` |
| PRD 索引 | `PRD-YYYYMMDD-NNN`／不適用 |
| 需求變更 | `CHG-YYYYMMDD-NNN`／不適用 |
| Sealed Context binding | `<shared revision/digest + exact feature Context revision/digest>`／不適用 |
| Agent Context binding | `<ticket revision / receipt / owner / worktree / branch / baseline / side_context_id>` |
| 實作語言 | 填入 `CONTEXT.md` › `## 實作語言規範` 的**統一後端語言**（不是從清單挑選）。偏離須先滿足該節觸發條件、有實測依據並經需求變更核准。**實作者不得自行決定**；未填不得進入 `implement`，審閱一律 `BLOCKED`。 |
| 狀態 | `PLANNED`／`IN_PROGRESS`／`BLOCKED`／`DONE`／`SUPERSEDED` |
| 共同基準 | `<docs-only commit SHA>` |
| 實作者 | `<AI／worktree>` |
| 審閱者 | `<AI／worktree>` |
| 責任邊界 | `<In Scope>` |
| 禁止修改 | `<Out of Scope>` |
| 環境 | `LOCAL`／`STAGING`／`PRODUCTION` |

## 使用者拍板與可觀察結果

## 實作範圍、依賴與 ticket elements

- element 路徑：`modules/element/<language>/<feature>/<ticket-id>/`
- 實際原始碼路徑：`<paths>`
- 公開契約／資料模型：`<types and ports>`

## TDD 設計

1. 正常行為：`<red test>`
2. 規則違反／輸入錯誤：`<red test>`
3. 外部失敗／fail-closed：`<red test>`
4. 回歸保護：`<test>`

### 適用的缺陷類別（依 `CodeReview.md` §2.1，逐一列出必要案例，不適用者寫明理由）

| # | 類別 | 是否適用 | 本工單的必要案例 |
| --- | --- | --- | --- |
| 1 | 路徑前綴誤匹配 | `是／否` | `<七種邊界：相等、多一字元、尾斜線、大小寫、URL 編碼、路徑遍歷、空路徑>` |
| 2 | null／空字串／陣列 | `是／否` | `<五種：null、undefined、''、純空白、空容器；並註明哪些等價>` |
| 3 | 權限繞過 | `是／否` | `<直接存取 + 間接存取（其他入口／內部呼叫／背景工作）>` |
| 4 | Token 格式與比較 | `是／否` | `<格式案例 + 來源斷言未用 ===／== 比對憑證>` |
| 5 | 錯誤碼是否一致 | `是／否` | `<對外碼固定不可區分 + 對內原因碼唯一；註明哪些原因必須保持可區分>` |
| 6 | 例外是否會拋出 | `是／否` | `<每個外部依賴注入失敗：主流程行為 + 是否傳播>` |

> 第 7 類「測試是否真的涵蓋描述」由審閱者負責，不在本表。
> **未列出的類別若事後成為缺陷，根因記為工單缺陷。**

## 完成定義與證據

- `<tests / typecheck / build / manual acceptance>`
- **紅燈輸出**：`<每個行為第一次失敗的測試名稱與失敗原因；缺此項不得宣稱依 TDD 完成>`

## 正式環境移植 SOP

- Migration、環境變數名稱、順序、驗證、回滾／forward-fix：`<details>`

## 完成回寫

- 實際檔案：`<paths>`
- commit：`<SHA>`
- WorkProgress：`PRG-YYYYMMDD-NNN`
