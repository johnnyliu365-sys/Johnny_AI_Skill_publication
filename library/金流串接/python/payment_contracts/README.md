# 付款契約

## 責任

提供不可變且強型別的 `Money`、幣別、付款意圖、idempotency key、訂閱權益識別與付款狀態轉換。金額只使用整數最小貨幣單位，絕不接受浮點數。

## 公用方式

建立 `PaymentIntent` 時必須提供 `PaymentIntentId`、`IdempotencyKey`、正整數 `Money` 與 `EntitlementId`。狀態只允許 `PENDING → CONFIRMED／CANCELLED`、`CONFIRMED → REFUNDED`，實際帳本寫入由 `subscription_ledger/` 處理。

## 來源追溯

設計僅參考 來源專案A 的訂閱／交易邊界與預期狀態模式。未複製資料表、會員、經銷、分潤、發票、支付provider丙、支付provider甲或 provider 設定；所有來源專案持續唯讀。

## 禁止用途

本模組不連線付款 provider、資料庫、發票、LINE、Webhook 或 Secret，也不代表可直接進行收款、退款或訂閱計費。
