# Python 其他功能集群

此目錄保存 Python 的通用可靠性與事件能力；各子模組必須以公開型別、fake adapter 與 deterministic 測試隔離來源專案。

## 責任

- 提供 `reliability_core/` 的不可變 outbox、單一 claim、版本化狀態保護、fake sender 與緊急停止稽核。
- 提供 `line_transport/` 的明確 scope／identity 訊息 request、redacted failure 與 deterministic fake transport。
- 提供 `identity_resolution/` 的穩定 identity、顯示名稱 fallback 與未知 identity fail-closed 解析。
- 提供 `event_timeline_audit/` 的通用事件重播、不可變 audit、unresolved／conflict 與 deterministic output hash。
- 提供 `engagement_rules/` 的可設定資格、進度、獎勵允許上限、stable event 去重與 fail-closed 結果。
- 將 outbox、worker、狀態轉換、停止控制與 identity display 等能力維持在無特定租戶／Provider 的邊界。

## 來源追溯

主要參考 來源專案D 的可靠性模式與 來源專案A 的推薦／獎勵規則分解；實作與測試只存在於本專案。

## 禁止用途

- 不得發送 LINE 訊息、處理真實租戶、讀取資料庫或啟用自動化。
- 不得使用未驗證動態事件、原始 payload、使用者 ID 或來源專案報表。
- 不得直接複製來源專案程式碼或測試 fixture。
