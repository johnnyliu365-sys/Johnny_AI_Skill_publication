# 新專案工作環境 Bootstrap 模板庫

本目錄是新專案建立時的受版控模板庫；通用發行版必須附帶同一份 `template/` 目錄。

## 固定結構

```text
<project-root>/
├─ Workflow.md
├─ AGENTS.md
├─ CONTEXT.md
├─ PRD.md                         # active requirement root index
├─ ProjectSchedule.md
├─ modules/
│  ├─ spec/
│  ├─ tickets/
│  └─ element/{typescript,python,java}/
└─ doc/
   ├─ context/                    # architecture feature Context leaves
   ├─ requirements/
   │  └─ active/<year>/<domain>/
   ├─ archive/
   │  └─ requirements/<year>/
   ├─ reviews/
   ├─ adr/
   ├─ RequirementChangeLog.md
   ├─ WorkProgressReport.md
   └─ security-agent-boundary.md
```

## 建置順序

1. 從通用發行版複製 `Workflow.md` 與 `AGENTS.md` 至新專案根目錄。
2. 建立上方固定目錄；不得建立 `doc/specs/` 或 `doc/tickets/`。
3. 複製並填寫 `CONTEXT.TEMPLATE.md`、`doc/context/TEMPLATE.md`、`doc/RequirementChangeLog.TEMPLATE.md`、
   `doc/requirements/REQ.TEMPLATE.md`、`doc/archive/requirements/ARCH-REQ.TEMPLATE.md`、`modules/spec/TEMPLATE.md`、
   `modules/tickets/TEMPLATE.md`、`doc/reviews/TEMPLATE.md`、`doc/adr/TEMPLATE.md` 與相符語言的 element 模板。
4. 先完成 `CONTEXT.md`、`PRD.md`、`ProjectSchedule.md`、需求變更與安全邊界的最小內容，再開始第一個 Grill。

## Policy and dispatch safety

Templates keep policy reads metadata-only: raw document text, prompts, paths,
URIs, secrets and PII do not enter Router models or handoff evidence. A fixed
dispatch response is produced only from the live Private Router pending
descriptor and its reviewed ticket/handoff receipt. A copied, replayed, absent
or mismatched descriptor is fail-closed. `COMMERCIAL` is not an implied
objective; use `POC` unless an approved Profile and change record establish
another stage.
