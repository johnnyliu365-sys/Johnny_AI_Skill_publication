# Event Timeline Audit（Python）

此模組提供無時鐘、無 I/O 的通用事件重播核心。它以固定事件列舉與不可變 audit 重建狀態，並為完整輸出產生 deterministic SHA-256 指紋。

## 可公用的能力

- `KnownTimelineEvent`：通用的 `START`、`ADVANCE`、`FINISH` 有限事件，不帶 payload 或領域資料。
- `UnknownTimelineEvent`：以 `UnknownEventCode` 保留未識別事件，重播結果為 `UNRESOLVED`，不會建立或猜測狀態。
- `TimelineConfiguration`：明確指定初始狀態；沒有隱含環境、時鐘或外部設定。
- `replay_timeline()`：對 tuple 事件序列產生最終狀態、不可變 `TimelineAuditEntry`、計數摘要與 `TimelineOutputHash`。
- 不合法順序與重複 event ID 以 `CONFLICT` audit 保留，既有狀態維持不變。

## 使用方式

```python
from library.功能集群.python.event_timeline_audit import (
    KnownTimelineEvent,
    TimelineConfiguration,
    TimelineEventId,
    TimelineEventKind,
    TimelineState,
    replay_timeline,
)

result = replay_timeline(
    configuration=TimelineConfiguration(initial_state=TimelineState.NOT_STARTED),
    events=(
        KnownTimelineEvent(
            event_id=TimelineEventId(value="local-event-001"),
            kind=TimelineEventKind.START,
        ),
    ),
)
```

相同的 configuration 與事件 tuple 會得到相同的 `final_state`、audit、summary 與 `output_hash`。呼叫端必須將 `UNRESOLVED`／`CONFLICT` 視為需要處理的結果，不能自動補值。

## 邊界與限制

- 不讀取 raw event、資料庫、報表、log、租戶資料、排程器或來源專案。
- 沒有 timestamp、背景重播、派單規則、Shadow Judge、持久化、併發控制或自動化。
- unknown code 與 event ID 僅接受小寫英數、`-`、`_` 的短識別碼，不能放入 payload、PII、token、exception 或 Provider response。
- 若需要真實事件匯入、儲存或領域轉換，必須在核准的外部 adapter 進行驗證與正規化。
