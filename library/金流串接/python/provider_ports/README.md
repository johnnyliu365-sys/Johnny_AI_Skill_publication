# 付款 Fake Provider 邊界

## 責任

定義付款 provider 的授權、確認、退款結果與失敗分類，並提供不連網的 `FakePaymentProvider`。公開輸入與輸出只含強型別付款意圖、交易 ID、事件 ID 與最終狀態。

## 公用方式

透過 `PaymentProviderPort` 依序呼叫 `authorize`、`confirm`、`refund`。測試使用 `FakePaymentProvider` 模擬成功、逾時與未知交易；其結果必須交給 `reconciliation/` 判定是否可寫入本地帳本。

## 來源追溯

設計僅參考 來源專案A 的付款流程狀態分解。未複製 支付provider丙、支付provider甲、支付provider乙 的路由、簽章、HTTP、Webhook、憑證、請求格式或來源程式碼；所有來源專案持續唯讀。

## 禁止用途

本模組不含真實 provider、HTTP、Webhook、發票、Secret、Token、交易資料或任何收款／退款操作；`FakePaymentProvider` 只能用於本地測試。
