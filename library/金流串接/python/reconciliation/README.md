# 付款對帳狀態機

## 責任

以不可變 `ReconciliationJournal` 記錄已套用的 provider 事件，並在檢查付款意圖、idempotency key、交易最終狀態與既有帳本後，回傳套用、已處理或人工審查結果。

## 公用方式

將 `ProviderEventSuccess` 或 `ProviderFailure` 交給 `reconcile_provider_event`，並同時提供目前的 `PaymentIntent`、`SubscriptionLedger` 與 `ReconciliationJournal`。呼叫端必須使用回傳的新快照；`MANUAL_REVIEW` 不得自動視為付款成功。

相同 event ID 只會得到 `ReconciliationAlreadyProcessed`，不會再次寫入帳本。逾時、未知交易、所有權不符、最終狀態衝突或帳本拒絕一律保留為人工審查。

## 來源追溯

設計僅參考 來源專案A 對帳／續訂流程的狀態分解，以及 來源專案D 的 expected-state 概念。未複製 Provider API、簽章、資料表、續訂排程、設定或來源程式碼；所有來源專案持續唯讀。

## 禁止用途

本模組不是正式對帳服務，不含資料庫、排程、HTTP、Webhook、Provider SDK、發票、憑證或自動人工審查處置。
