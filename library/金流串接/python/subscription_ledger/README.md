# 訂閱帳本

## 責任

以不可變、連續序號的事件 tuple 表達付款確認、訂閱授與、取消、退款與到期。每一次操作都回傳新的 `SubscriptionLedger` 快照；既有事件不會被修改或刪除。

## 公用方式

從 `SubscriptionLedger.empty()` 開始，呼叫 `confirm_payment`、`cancel_payment`、`refund_payment` 或 `expire_entitlement`。結果為 `LedgerAccepted` 或 `LedgerRejected`；呼叫端必須採用回傳的新帳本快照。

確認付款會原子地新增 `PAYMENT_CONFIRMED` 與 `SUBSCRIPTION_GRANTED` 兩個事件。既有 idempotency key 不會再次授與權益；重複退款、非法狀態、未知權益與重複到期均 fail closed。

## 來源追溯

設計僅參考 來源專案A 的訂閱／交易邊界與 來源專案D 的 expected-state、append-only outbox 概念。未複製資料表、會員、分潤、Provider、資料庫或外部服務程式碼；所有來源專案持續唯讀。

## 禁止用途

本模組是本地記憶體值物件，不是資料庫帳本，也不會付款、退款、開立發票、發送訊息或授權真實會員權益。
