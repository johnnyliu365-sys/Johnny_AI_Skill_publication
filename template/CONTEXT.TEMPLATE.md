# <專案名稱>

本檔案是 architecture/Grill 階段建立的共用專案事實來源。進入 SPEC 前必須封存
精確 revision/digest；後續角色只能引用，不能追加進度、ticket、commit、review
或新事實。缺失／變更事實必須回到 change control 建立新 revision。

| 欄位 | 內容 |
| --- | --- |
| Lifecycle | `ARCHITECTURE_DRAFT`／`SEALED`／`SUPERSEDED` |
| Context revision | `<opaque revision ID>` |
| Content digest | `<sha256>` |
| Architecture owner | `<owner ID>` |
| Active change authority | `<CHG-YYYYMMDD-NNN>` |

## 已確認事實與共同邊界

- `<fact / decision / boundary>`

## 識別碼登錄

- SPEC 專案代號：`<PROJECT>`（全大寫 kebab-case）。
- SPEC 功能鍵：全大寫 kebab-case，穩定對應 `modules/spec/<feature>.md`；不得因 AI、worktree 或修訂變更。
- SPEC 格式：`SPEC-<PROJECT>-<FEATURE>-<YYYYMMDD>-<ULID>`；新規格的 ULID 由所屬 worktree 以 CSPRNG 產生，完整 ID 不含 AI／worktree。
- 發布前查核：讀取本檔衍生 SPEC 索引與 `modules/spec/`，不得重用 ID 或新增仍有效功能集群的第二份規格。

## 實作語言規範

> 本節是本專案依 `Workflow.md` §9 通用條件所做的**實例決定**；通用條件不在此重複。

| 欄位 | 內容 |
| --- | --- |
| 專案類型 | `<workload shape：I/O bound／CPU bound／高併發；延遲由什麼主導>` |
| **統一後端語言** | `<language>` |
| 前端／行動端 | `<language>`（平台決定，非選擇） |
| 資料庫 | `SQL`（不計入語言選擇） |
| 法規／成熟度綁定例外 | `<domain → language>`／無 |
| 閘門生效階段 | `<例如：POC 豁免，MVP 起強制>` |

### 為何統一而非按領域分派

| 分歧領域 | 按適用性會選 | 實際決定 | 依據（須為實測或可查證事實） |
| --- | --- | --- | --- |
| `<domain>` | `<language>` | `<language>` | `<evidence>` |

### 偏離統一語言的觸發條件

偏離須有**實測依據**，不接受預期或偏好；觸發後仍須經需求變更紀錄與核准。

| 語言 | 觸發條件 |
| --- | --- |
| `<language>` | `<measurable trigger>` |

## Architecture feature index

> 本索引與同一 Context revision 一起封存；只列 direct child，不回填後續產物。

| Feature ID | Active PRD / CHG | Exact architecture Context leaf |
| --- | --- | --- |
| `<feature-id>` | `PRD-YYYYMMDD-NNN` / `CHG-YYYYMMDD-NNN` | `doc/context/<feature>/<worktree-id>.md` |

## Seal record

- Seal event／authority：`<event ID / owner authority>`
- Sealed revision／digest：`<revision / sha256>`
- 後續 SPEC、ticket、Agent Context 與 review 只保存此 revision/digest 參照，不回寫本檔。
