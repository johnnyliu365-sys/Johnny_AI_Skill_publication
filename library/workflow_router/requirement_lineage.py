"""Pure, bounded validation of active and retired requirement lineage branches."""

from __future__ import annotations

from .artifact_tree import ArtifactTreeResolver
from .contracts import (
    ArtifactTreeDecisionKind,
    ArtifactTreeFamily,
    ArtifactTreeLifecycle,
    ArtifactTreeNodeKind,
    OpaqueMetadataId,
    RequirementArchiveBundle,
    RequirementLineageDecisionKind,
    RequirementLineageInvalidReason,
    RequirementLineageValidationDecision,
    RequirementLineageValidationRequest,
    RequirementLifecycle,
    RequirementChangeId,
    RequirementId,
)


class RequirementLineageGate:
    """Validate one caller-selected requirement or retirement lineage branch."""

    @staticmethod
    def validate(
        request: RequirementLineageValidationRequest,
    ) -> RequirementLineageValidationDecision:
        """Return the finite lineage result without discovering any other branch."""

        if not RequirementLineageGate._request_binding_is_exact(request):
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.REQUEST_BINDING_MISMATCH,
            )
        if not RequirementLineageGate._identifier_pair_matches(
            request.lineage.prd_id,
            request.lineage.change_id,
        ):
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.IDENTIFIER_PAIR_MISMATCH,
            )
        if request.lineage.lifecycle is RequirementLifecycle.ACTIVE:
            return RequirementLineageGate._validate_active(request)

        bundle = request.archive_bundle
        if bundle is None:
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.ARCHIVE_BUNDLE_MISMATCH,
            )
        if not RequirementLineageGate._replacement_pair_matches(bundle):
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.REPLACEMENT_PAIR_MISMATCH,
            )
        if not RequirementLineageGate._archive_bundle_matches(request, bundle):
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.ARCHIVE_BUNDLE_MISMATCH,
            )
        return RequirementLineageGate._validate_retirement(request, bundle)

    @staticmethod
    def _request_binding_is_exact(request: RequirementLineageValidationRequest) -> bool:
        """Bind roots, families and expected leaves before any resolver call."""

        if request.prd_root_ref == request.change_root_ref:
            return False
        prd_path = request.prd_active_path
        change_path = request.change_active_path
        if (
            prd_path.family is not ArtifactTreeFamily.REQUIREMENT_CHANGE
            or change_path.family is not ArtifactTreeFamily.REQUIREMENT_CHANGE
            or prd_path.root_ref != request.prd_root_ref
            or change_path.root_ref != request.change_root_ref
        ):
            return False
        if request.lineage.lifecycle is RequirementLifecycle.ACTIVE:
            active_leaf_ref = request.lineage.active_leaf_ref
            if active_leaf_ref is None:
                return False
            return (
                prd_path.expected_leaf_ref == active_leaf_ref
                and change_path.expected_leaf_ref == active_leaf_ref
                and request.archive_root_ref is None
                and request.archive_path is None
                and request.archive_bundle is None
            )

        bundle = request.archive_bundle
        archive_root_ref = request.archive_root_ref
        archive_path = request.archive_path
        if bundle is None or archive_root_ref is None or archive_path is None:
            return False
        return (
            prd_path.expected_leaf_ref == bundle.retired_leaf_ref
            and change_path.expected_leaf_ref == bundle.retired_leaf_ref
            and archive_path.family is ArtifactTreeFamily.ARCHIVE_LIBRARY
            and archive_path.root_ref == archive_root_ref
            and archive_path.expected_leaf_ref == bundle.archive_leaf_ref
        )

    @staticmethod
    def _identifier_pair_matches(prd_id: RequirementId, change_id: RequirementChangeId) -> bool:
        """Require the PRD and CHG date/sequence suffixes to be identical."""

        return prd_id[4:] == change_id[4:]

    @staticmethod
    def _replacement_pair_matches(bundle: RequirementArchiveBundle) -> bool:
        """Require replacement identifiers to be absent or one matching pair."""

        replacement_prd_id = bundle.replacement_prd_id
        replacement_change_id = bundle.replacement_change_id
        if replacement_prd_id is None or replacement_change_id is None:
            return replacement_prd_id is None and replacement_change_id is None
        return replacement_prd_id[4:] == replacement_change_id[4:]

    @staticmethod
    def _validate_active(
        request: RequirementLineageValidationRequest,
    ) -> RequirementLineageValidationDecision:
        """Resolve both active paths and require one exact active leaf."""

        prd_result = ArtifactTreeResolver.resolve(request.prd_active_path)
        change_result = ArtifactTreeResolver.resolve(request.change_active_path)
        if (
            prd_result.decision is not ArtifactTreeDecisionKind.RESOLVED
            or change_result.decision is not ArtifactTreeDecisionKind.RESOLVED
        ):
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.ACTIVE_PATH_INVALID,
            )
        prd_leaf_ref = prd_result.resolved_leaf_ref
        change_leaf_ref = change_result.resolved_leaf_ref
        expected_leaf_ref = request.lineage.active_leaf_ref
        prd_leaf = request.prd_active_path.path_nodes[-1]
        change_leaf = request.change_active_path.path_nodes[-1]
        if (
            prd_leaf_ref is None
            or change_leaf_ref is None
            or expected_leaf_ref is None
            or prd_leaf_ref != change_leaf_ref
            or prd_leaf_ref != expected_leaf_ref
            or prd_leaf.node_ref != prd_leaf_ref
            or change_leaf.node_ref != change_leaf_ref
            or prd_leaf.node_kind is not ArtifactTreeNodeKind.LEAF
            or change_leaf.node_kind is not ArtifactTreeNodeKind.LEAF
            or prd_leaf.lifecycle is not ArtifactTreeLifecycle.ACTIVE
            or change_leaf.lifecycle is not ArtifactTreeLifecycle.ACTIVE
        ):
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.ACTIVE_LEAF_MISMATCH,
            )
        return RequirementLineageGate._valid(
            request,
            RequirementLineageDecisionKind.ACTIVE_PAIR_VALID,
            prd_leaf_ref,
        )

    @staticmethod
    def _archive_bundle_matches(
        request: RequirementLineageValidationRequest,
        bundle: RequirementArchiveBundle,
    ) -> bool:
        """Bind the supplied immutable archive bundle to the lineage record."""

        lineage = request.lineage
        return (
            lineage.archive_id is not None
            and lineage.archive_leaf_ref is not None
            and bundle.archive_id == lineage.archive_id
            and bundle.archive_leaf_ref == lineage.archive_leaf_ref
            and bundle.retired_prd_id == lineage.prd_id
            and bundle.retired_change_id == lineage.change_id
        )

    @staticmethod
    def _validate_retirement(
        request: RequirementLineageValidationRequest,
        bundle: RequirementArchiveBundle,
    ) -> RequirementLineageValidationDecision:
        """Require absent former active paths and one exact archived bundle leaf."""

        prd_result = ArtifactTreeResolver.resolve(request.prd_active_path)
        change_result = ArtifactTreeResolver.resolve(request.change_active_path)
        if (
            prd_result.decision is ArtifactTreeDecisionKind.ARTIFACT_TREE_INVALID
            or change_result.decision is ArtifactTreeDecisionKind.ARTIFACT_TREE_INVALID
        ):
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.ACTIVE_PATH_INVALID,
            )
        if (
            prd_result.decision is ArtifactTreeDecisionKind.RESOLVED
            or change_result.decision is ArtifactTreeDecisionKind.RESOLVED
        ):
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.RETIRED_PATH_STILL_ACTIVE,
            )
        if (
            prd_result.decision is not ArtifactTreeDecisionKind.ARTIFACT_PATH_NOT_FOUND
            or change_result.decision is not ArtifactTreeDecisionKind.ARTIFACT_PATH_NOT_FOUND
        ):
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.ACTIVE_PATH_INVALID,
            )

        archive_path = request.archive_path
        if archive_path is None:
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.ARCHIVE_PATH_INVALID,
            )
        archive_result = ArtifactTreeResolver.resolve(archive_path)
        archive_leaf = archive_path.path_nodes[-1]
        if (
            archive_result.decision is not ArtifactTreeDecisionKind.RESOLVED
            or archive_result.resolved_leaf_ref != bundle.archive_leaf_ref
            or archive_leaf.node_ref != bundle.archive_leaf_ref
            or archive_leaf.node_kind is not ArtifactTreeNodeKind.LEAF
            or archive_leaf.lifecycle is not ArtifactTreeLifecycle.ARCHIVED
            or archive_leaf.content_digest != bundle.content_digest
        ):
            return RequirementLineageGate._invalid(
                request,
                RequirementLineageInvalidReason.ARCHIVE_PATH_INVALID,
            )
        return RequirementLineageGate._valid(
            request,
            RequirementLineageDecisionKind.RETIREMENT_VALID,
            bundle.archive_leaf_ref,
        )

    @staticmethod
    def _invalid(
        request: RequirementLineageValidationRequest,
        reason: RequirementLineageInvalidReason,
    ) -> RequirementLineageValidationDecision:
        """Build one rejected result without exposing a lineage leaf."""

        return RequirementLineageValidationDecision(
            request_ref=request.request_ref,
            lineage_ref=request.lineage.lineage_ref,
            decision=RequirementLineageDecisionKind.REQUIREMENT_LINEAGE_INVALID,
            invalid_reason=reason,
            resolved_lineage_leaf_ref=None,
        )

    @staticmethod
    def _valid(
        request: RequirementLineageValidationRequest,
        decision: RequirementLineageDecisionKind,
        leaf_ref: OpaqueMetadataId,
    ) -> RequirementLineageValidationDecision:
        """Build one exact valid active or retirement result."""

        return RequirementLineageValidationDecision(
            request_ref=request.request_ref,
            lineage_ref=request.lineage.lineage_ref,
            decision=decision,
            invalid_reason=None,
            resolved_lineage_leaf_ref=leaf_ref,
        )
