# Line Transport（Python）

此模組是「LINE 類型出站訊息」的通用、本地 fake transport 邊界；它不包含 LINE SDK、HTTP、Webhook、帳號、憑證、Token 或訊息發送能力。

## 可公用的能力

- `OutboundMessageRequest`：要求呼叫端明確提供 `MessageRequestId`、`MessageScopeId`、`StableIdentityId` 與 `MessageContent`。
- `MessageTransport`：provider-free 的 transport port；結果只會是 `TransportSuccess` 或具有限定分類的 `TransportFailure`。
- `FakeLineTransport`：只計數本地嘗試，並以 `SUCCESS` 或 `PROVIDER_FAILURE` 回傳 deterministic 結果。
- `TransportFailure`：只保留 request ID 與安全分類，沒有 Provider response、例外訊息或敏感細節。

## 使用方式

```python
from library.功能集群.python.identity_resolution import StableIdentityId
from library.功能集群.python.line_transport import (
    FakeLineTransport,
    FakeTransportScenario,
    MessageContent,
    MessageRequestId,
    MessageScopeId,
    OutboundMessageRequest,
)

request = OutboundMessageRequest(
    request_id=MessageRequestId(value="local-request-001"),
    scope_id=MessageScopeId(value="local-sandbox"),
    recipient_identity=StableIdentityId(value="local-user-001"),
    content=MessageContent(value="Local-only message"),
)
result = FakeLineTransport(scenario=FakeTransportScenario.SUCCESS).send(request)
```

## 邊界與限制

- request 沒有 token、authorization、tenant、display label 或隱含身份授權欄位。
- 此模組不解析 identity；必須先由 `identity_resolution/` 以穩定 identity fail-closed 地處理。
- 不會連線、發送 LINE／簡訊／email、讀取設定檔、處理 webhook 或保存訊息。
- 真實 transport、授權、簽章、重試、outbox 串接與 Provider 特有格式，均需另行取得核准並在外部 adapter 實作。
