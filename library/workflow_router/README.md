# Workflow Router POC

此模組是「可套用於不同專案的流程引擎」POC，不是任何專案的產品實作。

## 節點與責任

- `contracts.py`：Pydantic 強型別的 `RouterState`、`RouterEvent`、`RouterDecision`、`ContextView` 與引用邊。
- `profile.py`：個別專案的 POC／MVP／商用關卡、來源需求和 capability allowlist；核心不硬編碼商業規則。
- `router.py`：純 transition、最小來源選擇、暫存 Context packet 和 metadata-only citation ledger。
- `graph.py`：LangGraph 只在 `complete`／`blocked` 的封閉分支中執行 transition。
- `integrations.py`：OpenAI Agents SDK 只解析已選中的 capability；MCP 只讀已選中的 source URI。
- `temporal_runtime.py`：Temporal signal、query 和持久化 human wait；不在 Workflow 內執行 I/O。

原文只存在 `ContextPacket`，此物件不可放入 graph state、checkpoint、Temporal history 或 `CitationLedger`。Ledger 只投影：

```text
source + revision + span → side_context_id → consumer_fingerprint → target_artifact
```

本 POC 不啟動模型、Temporal worker 或 MCP server。

## Context-load telemetry

Router POC 可將 baseline 與 Router run 的安全 measurement 寫成 local JSONL。記錄只包含 source fingerprint、revision、span、token count、ContextView ID、Agent fingerprint、provider usage 與驗收結果；不包含 `SourceSnippet.text`、prompt、source URI、Secret 或公司程式。

> 隔離修訂已核准但尚未實作：現有 `JsonlContextUsageStore.append(path=...)` 只可用於 disposable test fixture 或 Johnny 自己開發 repository 內的測試路徑，不得指向受控 target project。正式接管使用必須等待 `modules/spec/context-load-telemetry.md` Revision 02 完成 reviewer 拆票、實作、獨立審閱與整合。

1. 由 Johnny-owned adapter 在 per-user Johnny root 解析不透明 `TelemetryStorageRef`；不得在目標專案建立 `.johnny-router`、ignore rule 或任何 telemetry path。
2. baseline 完成後，以 `ContextUsageRecord.from_baseline(...)` 建立一筆紀錄；Router run 完成後，以 `ContextUsageRecord.from_router(...)` 建立另一筆。兩筆必須使用相同的 `comparison_group_id`、`attempt`、`project_snapshot_id`、provider 與 model。
3. 將完成後的 provider 回報 input/output token 放在 `AgentUsage`。沒有 `provider_input_tokens` 時，記錄仍可保存，但驗證器拒絕任何「已降低 context」宣告。
4. Revision 02 完成前，不得把 raw-path POC API 接到受控專案；完成後由 storage adapter append 到已驗證的 Johnny-owned stream。
5. 現有 CLI 僅供 Johnny 開發／disposable fixture 驗證：

```powershell
python -m library.workflow_router.telemetry_cli <johnny-internal-or-disposable-jsonl> --minimum-reduction-bps 5000
```

Revision 02 完成後，正式受控專案入口必須改收 opaque storage ref（例如
`--storage-ref tel-...`），由 adapter 解析 owned path；在實作完成前不要把這個
尚不存在的入口視為可用功能。

`5000` 代表 Router 組中位數 input token 至少降低 50%。命令只有在 pairing、Router guard 與品質都有效，而且達到門檻時才以 exit code `0` 結束。Raw JSONL 留在 Johnny-owned storage；輸出的 aggregate JSON report 經驗證、去識別化並取得獨立 artifact authority 後，才可作為 target-owned review evidence。不要提供原始 ContextPacket。

Telemetry 不會自行攔截任意 Agent 的讀檔；它量測接入 Router 的 run，並 fail-closed 拒絕預算超額、未宣告來源、shared state raw-text、缺 provider usage、不完整配對或品質退化的 reduction claim.
