# 金流串接功能集群

本目錄保存可測試的金流核心契約與 fake provider 邊界；它不是付款啟用、商業收款或任何既有商家的整合設定。

## 責任

- 提供不可變金額、付款意圖、交易狀態、idempotency key、訂閱權益與帳本事件模型。
- 提供 provider port、fake provider、退款結果與可重複對帳的通用狀態機。
- 將金流決策與特定 Router、資料表、前端付款流程及憑證完全分離。

## 公開模組規劃

- `python/payment_contracts/`：金額、交易與帳本契約。
- `python/subscription_ledger/`：訂閱權益與 append-only 事件。
- `python/provider_ports/`：fake payment provider。
- `python/reconciliation/`：對帳、重播與衝突結果。

## 來源追溯

參考 來源專案A 的付款、訂閱、退款與對帳切分，以及 來源專案D 的 idempotency／狀態轉換模式；本專案不承接任何來源的業務資料或 Provider 設定。

## 禁止用途

- 不得使用 支付provider丙、支付provider甲、支付provider乙 或任何真實付款 Provider 的憑證、網址、簽章與 API 呼叫。
- 不得使用浮點數表示金額、信任前端金額，或把取消、退款與權益撤銷混為同一事件。
- 不得修改、讀取或搬移 來源專案A 的付款原始碼、資料庫、環境檔或文件內容。
