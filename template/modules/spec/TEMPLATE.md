# <功能名稱> 規格

| 欄位 | 內容 |
| --- | --- |
| 規格 ID | `SPEC-<PROJECT>-<FEATURE>-<YYYYMMDD>-<ULID>`（例如 `SPEC-FM-P0-SEARCH-CONTROL-20260730-01KYS2QPQCZTY7GBZKW4K175NW`） |
| 規格狀態 | `DRAFT`／`APPROVED`／`SUPERSEDED` |
| 撰寫 AI 簽名 | `<AI>／<worktree>／基準 <commit SHA>` |
| 排查起點 Context | `doc/context/<feature>/<worktree-id>.md` |
| PRD 索引 | `PRD-YYYYMMDD-NNN`／不適用 |
| 需求變更 | `CHG-YYYYMMDD-NNN`／不適用 |
| Sealed Context binding | `<shared revision/digest + exact feature Context revision/digest>`／不適用 |
| 實作語言 | 本功能集群的實作語言，依 `CONTEXT.md` › `## 實作語言規範` 的統一後端語言。若本集群主張偏離，須在「風險」段落列出實測依據與對應的需求變更紀錄。 |

## 問題、目標與不做範圍

## 使用者流程與驗收條件

## 領域模型、資料流與責任邊界

## API／事件、資料庫、快取、Provider、權限與維運

## 測試切點與 TDD 設計

## 風險、相容性、回滾與部署前提

## 收斂與 lineage

- Sealed shared/feature Context binding：`<revision / digest / exact source refs>`
- Active requirement leaf：`<PRD/CHG IDs and REQ leaf path>`
- 關聯 CHG 的 SPEC 收斂結果：`<section / 不適用>`
- 新事實或缺口：`<REQUIREMENT_CHANGED / none>`；不得回寫 sealed Context。

## 修訂簽名

| 日期 | AI／worktree／基準 SHA | 摘要 |
| --- | --- | --- |
| `<ISO-8601>` | `<signature>` | `<revision>` |

## 核准紀錄

- 決策者：`<name>`
- 日期：`<Asia/Taipei date>`
- 核准範圍：`<scope>`
