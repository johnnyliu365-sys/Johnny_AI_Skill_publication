# Reliability Core（Python）

此模組提供可攜、純記憶體的可靠性核心：outbox 工作、一次性鍵、單一 worker claim、版本化狀態保護、fake sender 與緊急停止稽核。所有狀態轉換皆回傳新的不可變 `InMemoryReliabilityCore` 快照。

## 可公用的能力

- `WorkScopeId`、`WorkIdempotencyKey`、`OutboxJobId`、`WorkerId`、`JobVersion`：具名值物件，避免以裸字串或整數傳遞領域資料。
- `InMemoryReliabilityCore`：僅允許已註冊 scope 建立工作；同一 idempotency key 只能建立一次。
- `claim()` 與 `process_claimed()`：限制一個 worker 取得工作，並在處理前驗證 worker 擁有權與預期版本。
- `OutboxWorker`：帶有固定 worker 身分的薄型 façade，可套用到任意本地執行模型。
- `FakeOutboxSender`：只回傳成功或失敗的 deterministic fake outcome，絕不發送網路訊息。
- `activate_emergency_stop()`：封鎖所有未完成工作、拒絕後續 enqueue／claim，並保留 `AuditEntry`。

## 使用方式

```python
from library.功能集群.python.reliability_core import (
    FakeOutboxSender,
    FakeSenderScenario,
    InMemoryReliabilityCore,
    JobDescription,
    WorkIdempotencyKey,
    WorkScopeId,
)

scope = WorkScopeId(value="local-sandbox")
core = InMemoryReliabilityCore.with_scopes(scopes=(scope,))
result = core.enqueue(
    scope=scope,
    idempotency_key=WorkIdempotencyKey(value="local-job-001"),
    description=JobDescription(value="local-only action"),
)
```

完成 enqueue 後，呼叫端必須先處理 `EnqueueAccepted`／`EnqueueRejected` 聯集型別；只有 accepted 情況能取得下一個 core 快照與 job。claim 與 process 亦遵循相同模式。

## 邊界與限制

- 沒有資料庫、排程器、佇列、網路、LINE、Provider 或真實租戶整合。
- `JobDescription` 只適合非敏感的本地說明，不能放入原始 payload、使用者資料或 secret。
- fake sender 的計數僅用於測試「未嘗試發送」；它不是實際投遞紀錄。
- 真正的持久化、重試、授權與外部服務適配，必須由採用端在已核准的邊界另行實作。
