# Kotlin 其他功能集群

## 已交付模組

- `offline_geo_resolution/` 已交付：可注入的地址 key policy 與座標驗證器、離線 exact-first lookup、唯一放寬解析及歧義拒絕。詳見 [offline_geo_resolution/README.md](offline_geo_resolution/README.md)。

本項交付取代本文件中將 Kotlin 一概視為「尚未交付」的規劃性敘述；其餘候選仍須另行走規格、工單與核准流程。

此目錄保存與 Android／Kotlin 生態相容、但不依賴 Android Runtime 的通用能力。

## 責任

- 建立 `offline_geo_resolution/`，提供地址 key 正規化、離線 lookup 介面與座標範圍驗證。
- 使用 data class、sealed interface 與 enum class 表達值物件與解析結果。

## 來源追溯

參考 來源專案C 的離線地址解析與位置分類概念；不帶入 Android Context、asset、定位權限、網路或實際地理資料。

## 禁止用途

- 不得修改 來源專案C Android app、資產、Manifest、服務、位置資料或任何來源檔案。
- 不得連線地圖／定位 Provider，也不得保存精確位置或真實使用者資料。
- 不得讓未命中的地址推測成真實座標。
