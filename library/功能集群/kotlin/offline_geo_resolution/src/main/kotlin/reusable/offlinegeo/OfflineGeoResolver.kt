package reusable.offlinegeo

@JvmInline
value class RawAddressKey(val value: String)

@JvmInline
value class NormalizedAddressKey(val value: String)

@JvmInline
value class RelaxedAddressKey(val value: String)

data class GeoCoordinate(
    val latitude: Double,
    val longitude: Double,
)

data class OfflineGeoEntry(
    val rawKey: RawAddressKey,
    val coordinate: GeoCoordinate,
)

fun interface CoordinateValidator {
    fun accepts(coordinate: GeoCoordinate): Boolean
}

data object FiniteCoordinateValidator : CoordinateValidator {
    override fun accepts(coordinate: GeoCoordinate): Boolean {
        return coordinate.latitude.isFinite() && coordinate.longitude.isFinite()
    }
}

interface AddressKeyPolicy {
    fun normalize(rawKey: RawAddressKey): NormalizedAddressKey?

    fun relaxedKey(normalizedKey: NormalizedAddressKey): RelaxedAddressKey?
}

enum class GeoMatchKind {
    EXACT,
    RELAXED_UNIQUE,
}

sealed interface GeoResolutionResult {
    data class Resolved(
        val coordinate: GeoCoordinate,
        val matchKind: GeoMatchKind,
    ) : GeoResolutionResult

    data object InvalidAddressKey : GeoResolutionResult

    data object UnknownAddressKey : GeoResolutionResult

    data object AmbiguousRelaxedKey : GeoResolutionResult
}

enum class OfflineGeoIndexRejectionReason {
    INVALID_ADDRESS_KEY,
    INVALID_COORDINATE,
    DUPLICATE_EXACT_KEY,
}

sealed interface OfflineGeoIndexBuildResult {
    data class Built(val resolver: OfflineGeoResolver) : OfflineGeoIndexBuildResult

    data class Rejected(val reason: OfflineGeoIndexRejectionReason) : OfflineGeoIndexBuildResult
}

private sealed interface RelaxedLookup {
    data class Unique(val coordinate: GeoCoordinate) : RelaxedLookup

    data object Ambiguous : RelaxedLookup
}

class OfflineGeoResolver private constructor(
    private val exactCoordinates: Map<NormalizedAddressKey, GeoCoordinate>,
    private val relaxedCoordinates: Map<RelaxedAddressKey, RelaxedLookup>,
    private val addressKeyPolicy: AddressKeyPolicy,
) {
    fun resolve(rawKey: RawAddressKey): GeoResolutionResult {
        val normalizedKey = addressKeyPolicy.normalize(rawKey)
            ?.takeIf { it.value.isNotBlank() }
            ?: return GeoResolutionResult.InvalidAddressKey

        exactCoordinates[normalizedKey]?.let { coordinate: GeoCoordinate ->
            return GeoResolutionResult.Resolved(
                coordinate = coordinate,
                matchKind = GeoMatchKind.EXACT,
            )
        }

        val relaxedKey = addressKeyPolicy.relaxedKey(normalizedKey)
            ?.takeIf { it.value.isNotBlank() }
            ?: return GeoResolutionResult.UnknownAddressKey

        return when (val relaxedLookup = relaxedCoordinates[relaxedKey]) {
            is RelaxedLookup.Unique -> GeoResolutionResult.Resolved(
                coordinate = relaxedLookup.coordinate,
                matchKind = GeoMatchKind.RELAXED_UNIQUE,
            )

            RelaxedLookup.Ambiguous -> GeoResolutionResult.AmbiguousRelaxedKey
            null -> GeoResolutionResult.UnknownAddressKey
        }
    }

    companion object {
        fun fromEntries(
            entries: Iterable<OfflineGeoEntry>,
            addressKeyPolicy: AddressKeyPolicy,
            coordinateValidator: CoordinateValidator,
        ): OfflineGeoIndexBuildResult {
            val exactCoordinates = linkedMapOf<NormalizedAddressKey, GeoCoordinate>()
            val relaxedCandidates = linkedMapOf<RelaxedAddressKey, LinkedHashSet<GeoCoordinate>>()

            for (entry: OfflineGeoEntry in entries) {
                if (!coordinateValidator.accepts(entry.coordinate)) {
                    return OfflineGeoIndexBuildResult.Rejected(
                        OfflineGeoIndexRejectionReason.INVALID_COORDINATE,
                    )
                }

                val normalizedKey = addressKeyPolicy.normalize(entry.rawKey)
                    ?.takeIf { it.value.isNotBlank() }
                    ?: return OfflineGeoIndexBuildResult.Rejected(
                        OfflineGeoIndexRejectionReason.INVALID_ADDRESS_KEY,
                    )

                if (exactCoordinates.containsKey(normalizedKey)) {
                    return OfflineGeoIndexBuildResult.Rejected(
                        OfflineGeoIndexRejectionReason.DUPLICATE_EXACT_KEY,
                    )
                }
                exactCoordinates[normalizedKey] = entry.coordinate

                val relaxedKey = addressKeyPolicy.relaxedKey(normalizedKey)
                    ?.takeIf { it.value.isNotBlank() }
                    ?: continue
                relaxedCandidates.getOrPut(relaxedKey) { linkedSetOf() }.add(entry.coordinate)
            }

            val relaxedCoordinates = linkedMapOf<RelaxedAddressKey, RelaxedLookup>()
            for ((relaxedKey: RelaxedAddressKey, candidates: LinkedHashSet<GeoCoordinate>) in relaxedCandidates) {
                relaxedCoordinates[relaxedKey] = when (candidates.size) {
                    1 -> RelaxedLookup.Unique(candidates.first())
                    else -> RelaxedLookup.Ambiguous
                }
            }

            return OfflineGeoIndexBuildResult.Built(
                OfflineGeoResolver(
                    exactCoordinates = exactCoordinates.toMap(),
                    relaxedCoordinates = relaxedCoordinates.toMap(),
                    addressKeyPolicy = addressKeyPolicy,
                ),
            )
        }

        fun empty(addressKeyPolicy: AddressKeyPolicy): OfflineGeoResolver {
            return OfflineGeoResolver(
                exactCoordinates = emptyMap(),
                relaxedCoordinates = emptyMap(),
                addressKeyPolicy = addressKeyPolicy,
            )
        }
    }
}
