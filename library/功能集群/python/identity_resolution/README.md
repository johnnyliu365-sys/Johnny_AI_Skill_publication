# Identity Resolution（Python）

此模組將穩定 identity 與顯示名稱徹底分開。`StableIdentityId` 是唯一識別鍵；`DisplayLabel` 只用於呈現，沒有授權、租戶或路由意義。

## 可公用的能力

- `IdentityDirectory`：不可變、本地記憶體的 identity 註冊與解析快照。
- `enroll()`：同一 `StableIdentityId` 只能註冊一次；新的顯示名稱無法覆寫既有記錄。
- `resolve()`：已知 identity 回傳 `ResolvedIdentity`；未知 identity 回傳 `IdentityUnknown`，不猜測、不自動建立。
- 未提供顯示名稱的已知 identity 會使用固定的 `UNKNOWN_DISPLAY_LABEL`；此 fallback 不包含 identity 值。

## 使用方式

```python
from library.功能集群.python.identity_resolution import (
    DisplayLabel,
    IdentityDirectory,
    StableIdentityId,
)

identity_id = StableIdentityId(value="local-user-001")
directory = IdentityDirectory.empty()
enrolled = directory.enroll(
    identity_id=identity_id,
    display_label=DisplayLabel(value="Local user"),
)
```

呼叫端必須處理 `IdentityEnrollmentAccepted`／`IdentityEnrollmentRejected` 與 `ResolvedIdentity`／`IdentityUnknown` 聯集型別，不得從顯示名稱反推或授權 identity。

## 邊界與限制

- 不讀取資料庫、LINE profile、租戶設定、raw payload、PII 或來源專案資料。
- 不將 identity 視為登入、授權、角色或訊息投遞權限。
- 沒有同步、合併、改名或刪除功能；需要持久化或外部 identity provider 時，須另行取得核准。
