# Engagement Rules（Python）

此模組提供可設定、純本地的推薦資格、任務進度與獎勵「允許」規則。它只計算不可變狀態與解釋性結果，絕不建立會員、點數、帳戶、推播或實際權益。

## 可公用的能力

- `EngagementPolicy`：以具名的資格事件數、進度目標與獎勵上限定義通用規則。
- `EngagementPolicyCatalog`：只評估已註冊的 policy；未知 policy 預設回傳 `UNKNOWN_POLICY`。
- `EngagementState`：保存單一 policy 的資格、進度、已允許獎勵數與不可變 `frozenset` 已接受事件 key；每次變更回傳新快照。
- `KnownEngagementEvent`：`QUALIFICATION`、`PROGRESS`、`REWARD_REQUEST` 三種有限事件。
- 重複 event key、未知事件、不合格狀態、不可能的外部 state、未達目標與上限已滿皆回傳 `EngagementEvaluationRejected`，不變更 state。
- `REWARD_PERMITTED` 僅代表規則允許一次；沒有價值、點數、折扣、帳戶或外部副作用。

## 使用方式

```python
from library.功能集群.python.engagement_rules import (
    EngagementPolicy,
    EngagementPolicyCatalog,
    EngagementPolicyId,
    EngagementState,
    ProgressTarget,
    QualificationRequirement,
    RewardCap,
)

policy = EngagementPolicy(
    policy_id=EngagementPolicyId(value="local-policy"),
    qualification_requirement=QualificationRequirement(value=1),
    progress_target=ProgressTarget(value=2),
    reward_cap=RewardCap(value=1),
)
catalog = EngagementPolicyCatalog(policies=(policy,))
state = EngagementState.initial(policy=policy)
```

呼叫端必須檢查 `EngagementEvaluationAccepted`／`EngagementEvaluationRejected`，並只使用 accepted result 的新 state。event 與 policy ID 只接受小寫英數、`-`、`_` 的短識別碼。

## 邊界與限制

- 不讀取或寫入健康資料、會員、經銷、點數、帳戶、通知、資料庫、provider、來源專案或 raw event。
- `UnknownEventCode` 只是安全識別碼，不能放 payload、PII、token、exception 或 provider response。
- 沒有時間、排程、持久化、跨程序去重、併發鎖、真實獎勵發放、推薦內容生成或商業規則。
- 真實資料與權益效果必須在已核准的外部 adapter 驗證、正規化及執行。
