# Offline Geo Resolution（Kotlin）

此模組是離線 key 到座標的純 Kotlin 解析核心。它以 來源專案C 專案的 `OfflineAddressResolver` 為唯讀行為參照，重實作「精確命中優先、唯一放寬才可命中、歧義絕不猜測」的演算法；不複製來源程式碼、地址資料或 Android 整合。

## 可公用的能力

- `OfflineGeoResolver`：由本地 `OfflineGeoEntry` 建立不可變查詢索引，並提供 `resolve()`。
- `AddressKeyPolicy`：將專案自己的 raw key 正規化，並定義何時可產生放寬 key。核心不假設語言、行政區、道路格式或資料來源。
- `CoordinateValidator`：由採用端決定可接受的座標範圍；內建 `FiniteCoordinateValidator` 只接受有限數值，不內建任何國家或商業地域。
- `OfflineGeoIndexBuildResult`：以 `Built`／`Rejected(reason)` 表達索引是否可安全建立；空 key、無效座標與重複 exact key 一律拒絕。
- `GeoResolutionResult`：以 sealed result 明確表達 `Resolved`、`InvalidAddressKey`、`UnknownAddressKey` 與 `AmbiguousRelaxedKey`，呼叫端不可把歧義當作成功結果。

## 解析規則

1. 先以 `AddressKeyPolicy.normalize()` 產生精確 key；空白或無法正規化的輸入回傳 `InvalidAddressKey`。
2. 精確 key 命中時立即回傳 `GeoMatchKind.EXACT`。
3. 未命中時，只有 policy 明確提供放寬 key 才會查詢；唯一候選回傳 `GeoMatchKind.RELAXED_UNIQUE`。
4. 同一放寬 key 對應多個不同座標時回傳 `AmbiguousRelaxedKey`，不挑選任一候選。
5. 建表時空白／無法正規化 key、validator 拒絕的座標及重複正規化 exact key 均回傳具名 `Rejected` 結果，不產生部分索引。這是 Ticket 11 對通用採用邊界的 fail-closed 要求；查詢的 exact-first、unique-relaxed 與 ambiguous-reject 語義仍依來源參照。

## 使用方式

採用端必須提供自己的 key 語法與座標範圍；不要把真實地址、使用者定位或 Provider payload 直接傳入此核心。

```kotlin
val buildResult = OfflineGeoResolver.fromEntries(
    entries = localEntries,
    addressKeyPolicy = projectAddressKeyPolicy,
    coordinateValidator = projectCoordinateValidator,
)

when (buildResult) {
    is OfflineGeoIndexBuildResult.Built -> {
        when (val result = buildResult.resolver.resolve(RawAddressKey("safe-local-key"))) {
            is GeoResolutionResult.Resolved -> useCoordinate(result.coordinate)
            GeoResolutionResult.InvalidAddressKey,
            GeoResolutionResult.UnknownAddressKey,
            GeoResolutionResult.AmbiguousRelaxedKey -> handleUnresolvedLocation()
        }
    }

    is OfflineGeoIndexBuildResult.Rejected -> handleInvalidOfflineIndex(buildResult.reason)
}
```

## 驗證

此模組不依賴 Gradle、JUnit、Android 或網路。安裝 Kotlin CLI 後，可執行：

```text
kotlinc -Werror src/main/kotlin/reusable/offlinegeo/OfflineGeoResolver.kt src/test/kotlin/reusable/offlinegeo/OfflineGeoResolverTest.kt -include-runtime -d offline-geo-resolution-test.jar
java -jar offline-geo-resolution-test.jar
```

## 邊界與限制

- 不讀取 Android `Context`、asset、資料庫、檔案、網路、Provider、GPS 或使用者位置。
- 不含任何地址、座標、國家界限、地名、行政區、道路或來源專案 fixture。
- 不解析自由文字地址；其正規化與放寬規則必須在採用端的 `AddressKeyPolicy` 明確實作與驗證。
- 不提供地理編碼、反向地理編碼、導航、快取、持久化、並發同步或權限判斷。
