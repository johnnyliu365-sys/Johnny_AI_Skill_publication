package reusable.offlinegeo

private object TestAddressKeyPolicy : AddressKeyPolicy {
    override fun normalize(rawKey: RawAddressKey): NormalizedAddressKey? {
        val compactValue = rawKey.value.trim().lowercase().replace(Regex("\\s+"), " ")
        return compactValue.takeIf { it.isNotEmpty() }?.let(::NormalizedAddressKey)
    }

    override fun relaxedKey(normalizedKey: NormalizedAddressKey): RelaxedAddressKey? {
        val segments = normalizedKey.value.split("|")
        return when {
            segments.size == 4 && segments.all { it.isNotBlank() } -> {
                RelaxedAddressKey("${segments[0]}|${segments[2]}|${segments[3]}")
            }

            segments.size == 3 && segments.all { it.isNotBlank() } -> {
                RelaxedAddressKey(normalizedKey.value)
            }

            else -> null
        }
    }
}

private fun <ValueType> assertEquals(expected: ValueType, actual: ValueType, message: String): Unit {
    check(expected == actual) { "$message: expected=$expected actual=$actual" }
}

private fun buildOf(vararg entries: OfflineGeoEntry): OfflineGeoIndexBuildResult {
    return OfflineGeoResolver.fromEntries(
        entries = entries.asList(),
        addressKeyPolicy = TestAddressKeyPolicy,
        coordinateValidator = FiniteCoordinateValidator,
    )
}

private fun resolverOf(vararg entries: OfflineGeoEntry): OfflineGeoResolver {
    return when (val buildResult = buildOf(*entries)) {
        is OfflineGeoIndexBuildResult.Built -> buildResult.resolver
        is OfflineGeoIndexBuildResult.Rejected -> {
            error("expected a valid offline geo index, but got ${buildResult.reason}")
        }
    }
}

private fun entry(rawKey: String, latitude: Double, longitude: Double): OfflineGeoEntry {
    return OfflineGeoEntry(
        rawKey = RawAddressKey(rawKey),
        coordinate = GeoCoordinate(latitude = latitude, longitude = longitude),
    )
}

private fun normalizedKeyUsesExactFixture(): Unit {
    val expectedCoordinate = GeoCoordinate(latitude = 10.5, longitude = 20.5)
    val resolver = resolverOf(entry("zone alpha / route one / unit 7", 10.5, 20.5))

    val result = resolver.resolve(RawAddressKey("  ZONE   ALPHA / ROUTE ONE / UNIT 7  "))

    assertEquals(
        GeoResolutionResult.Resolved(
            coordinate = expectedCoordinate,
            matchKind = GeoMatchKind.EXACT,
        ),
        result,
        "normalized exact key must resolve the fixture",
    )
}

private fun uniqueRelaxedKeyResolvesWithoutGuessing(): Unit {
    val expectedCoordinate = GeoCoordinate(latitude = 11.0, longitude = 21.0)
    val resolver = resolverOf(entry("region-a|subregion-a|route-1|unit-1", 11.0, 21.0))

    val result = resolver.resolve(RawAddressKey("region-a|route-1|unit-1"))

    assertEquals(
        GeoResolutionResult.Resolved(
            coordinate = expectedCoordinate,
            matchKind = GeoMatchKind.RELAXED_UNIQUE,
        ),
        result,
        "a unique relaxed key must resolve",
    )
}

private fun ambiguousRelaxedKeyNeverChoosesCandidate(): Unit {
    val resolver = resolverOf(
        entry("region-a|subregion-a|route-1|unit-1", 11.0, 21.0),
        entry("region-a|subregion-b|route-1|unit-1", 12.0, 22.0),
    )

    val result = resolver.resolve(RawAddressKey("region-a|route-1|unit-1"))

    assertEquals(
        GeoResolutionResult.AmbiguousRelaxedKey,
        result,
        "an ambiguous relaxed key must not select a coordinate",
    )
}

private fun blankKeyAndInvalidCoordinateAreRejected(): Unit {
    assertEquals(
        OfflineGeoIndexBuildResult.Rejected(OfflineGeoIndexRejectionReason.INVALID_ADDRESS_KEY),
        buildOf(entry("   ", 11.0, 21.0)),
        "a blank address key must reject index construction",
    )
    assertEquals(
        OfflineGeoIndexBuildResult.Rejected(OfflineGeoIndexRejectionReason.INVALID_COORDINATE),
        buildOf(entry("region-a|subregion-a|route-1|unit-1", Double.NaN, 21.0)),
        "an invalid coordinate must reject index construction",
    )
}

private fun duplicateExactKeyIsRejected(): Unit {
    val result = buildOf(
        entry("region-a|subregion-a|route-1|unit-1", 11.0, 21.0),
        entry("region-a|subregion-a|route-1|unit-1", 12.0, 22.0),
    )

    assertEquals(
        OfflineGeoIndexBuildResult.Rejected(OfflineGeoIndexRejectionReason.DUPLICATE_EXACT_KEY),
        result,
        "a duplicate normalized exact key must reject index construction",
    )
}

object OfflineGeoResolverTest {
    @JvmStatic
    fun main(args: Array<String>): Unit {
        normalizedKeyUsesExactFixture()
        uniqueRelaxedKeyResolvesWithoutGuessing()
        ambiguousRelaxedKeyNeverChoosesCandidate()
        blankKeyAndInvalidCoordinateAreRejected()
        duplicateExactKeyIsRejected()
    }
}
