# Architecture feature Context 模板

> 檔案路徑：`doc/context/<feature>/<worktree-id>.md`
> 僅供 architecture/Grill 收斂一個 feature；進入 SPEC 前封存。這不是 implementer
> 的 ticket Context，也不得覆寫共同 `CONTEXT.md` 或既有已核准規格。

| 欄位 | 內容 |
| --- | --- |
| 功能集群 | `<feature>` |
| Agent／worktree | `<AI>／<branch-or-worktree>` |
| 共同基準 | `<commit SHA>` |
| 狀態 | `ARCHITECTURE_DRAFT`／`SEALED`／`SUPERSEDED`／`BLOCKED` |
| 責任邊界 | `<In Scope>` |
| 禁止修改 | `<Out of Scope>` |

## 共用 Context 引用

- 共同基準 commit：`<SHA>`
- `CONTEXT.md` 章節：`<heading hierarchy>`
- 引用錨點：`<heading hierarchy> › <entry name>`
- 引用指紋：`<sha256-8>`（錨點行起至下一空行之文字）
- 行號（非規範性提示，可省略）：`<line>`

## 既有規格前置查核

| 產物 | 狀態 | 可沿用／不可改寫範圍 | 本次處置 |
| --- | --- | --- | --- |
| `modules/spec/<feature>.md` | `APPROVED`／`BLOCKED`／`SUPERSEDED` | `<facts>` | `<reuse/change/ignore>` |
| `modules/tickets/<feature>/` | `<status>` | `<facts>` | `<action>` |

## 已確認事實與約束

- `<fact>`

## 待決事項與跨集群依賴

- `<decision owner / impact / BLOCKED condition>`

## Seal and downstream binding

- Feature Context revision／digest：`<revision / sha256>`
- 共用 Context sealed revision／digest：`<revision / sha256>`
- PRD／需求變更：`PRD-YYYYMMDD-NNN`／`CHG-YYYYMMDD-NNN`
- Emitted SPEC ID／path：`<SPEC-ID / modules/spec/<feature>.md>`
- 封存後不得回寫；新事實以 `REQUIREMENT_CHANGED` 建立新 architecture revision。
