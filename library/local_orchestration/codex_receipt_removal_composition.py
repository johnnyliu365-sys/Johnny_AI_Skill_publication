"""Exact composition of a receipt-removal request and admitted port."""

from __future__ import annotations

from enum import Enum
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict

from .codex_compensation_composition import (
    CodexCompensationObservationRejected,
    CodexCompensationObservationResult,
    observe_codex_compensation_operation,
)
from .codex_compensation_port import (
    CodexCompensationPortCapability,
    CodexCompensationPortOperation,
    CodexCompensationPortRequest,
    admit_codex_compensation_port,
)
from .codex_compensation_reducer import (
    CodexCompensationStep,
    CodexInstalledLocationProof,
    CodexMarketplaceProof,
    CodexPluginListsProof,
    CodexProofTruth,
    CodexRemovalConfirmed,
)
from .codex_receipt_removal_request import (
    CodexReceiptRemovalBlockReason,
    CodexReceiptRemovalBlocked,
    CodexReceiptRemovalReady,
    build_codex_receipt_removal_request,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


class CodexReceiptRemovalCompositionBlockReason(str, Enum):
    INVALID_INVOCATION = "INVALID_INVOCATION"
    INVALID_RECEIPT = "INVALID_RECEIPT"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"
    INVALID_PORT = "INVALID_PORT"
    PRE_REMOVAL_EVIDENCE_INVALID = "PRE_REMOVAL_EVIDENCE_INVALID"
    PLUGIN_REMOVAL_FAILED = "PLUGIN_REMOVAL_FAILED"
    MARKETPLACE_REMOVAL_FAILED = "MARKETPLACE_REMOVAL_FAILED"
    POST_REMOVAL_EVIDENCE_INVALID = "POST_REMOVAL_EVIDENCE_INVALID"


class CodexReceiptRemovalNotInstalled(_StrictModel):
    status: Literal["NOT_INSTALLED"] = "NOT_INSTALLED"


class CodexReceiptRemovalRemoved(_StrictModel):
    status: Literal["REMOVED"] = "REMOVED"


class CodexReceiptRemovalCompositionBlocked(_StrictModel):
    status: Literal["UNINSTALL_BLOCKED"] = "UNINSTALL_BLOCKED"
    reason: CodexReceiptRemovalCompositionBlockReason


CodexReceiptRemovalCompositionResult: TypeAlias = (
    CodexReceiptRemovalNotInstalled
    | CodexReceiptRemovalRemoved
    | CodexReceiptRemovalCompositionBlocked
)


class _EvidenceState(str, Enum):
    ABSENT = "ABSENT"
    RESIDUE = "RESIDUE"
    INVALID = "INVALID"


def compose_codex_receipt_removal(
    invocation: object,
    port_candidate: object,
) -> CodexReceiptRemovalCompositionResult:
    """Execute one exact receipt-bound removal transaction."""

    request_result = build_codex_receipt_removal_request(invocation)
    if type(request_result) is CodexReceiptRemovalBlocked:
        return _map_request_block(request_result)
    if type(request_result) is not CodexReceiptRemovalReady:
        return _blocked(CodexReceiptRemovalCompositionBlockReason.INVALID_INVOCATION)

    port_admission = admit_codex_compensation_port(port_candidate)
    if type(port_admission) is not CodexCompensationPortCapability:
        return _blocked(CodexReceiptRemovalCompositionBlockReason.INVALID_PORT)

    request = request_result.request
    pre_plugin = _observe(
        CodexCompensationPortOperation.LIST_PLUGINS,
        port_admission.list_plugins(request),
        request,
    )
    pre_marketplace = _observe(
        CodexCompensationPortOperation.LIST_MARKETPLACES,
        port_admission.list_marketplaces(request),
        request,
    )
    pre_path = _observe(
        CodexCompensationPortOperation.PROVE_INSTALLED_PATH_ABSENT,
        port_admission.prove_installed_path_absent(request),
        request,
    )

    pre_plugin_state = _plugin_state(pre_plugin)
    pre_marketplace_state = _marketplace_state(pre_marketplace)
    pre_path_state = _path_state(pre_path)
    if (
        pre_plugin_state is _EvidenceState.INVALID
        or pre_marketplace_state is _EvidenceState.INVALID
        or pre_path_state is _EvidenceState.INVALID
    ):
        return _blocked(CodexReceiptRemovalCompositionBlockReason.PRE_REMOVAL_EVIDENCE_INVALID)
    if (
        pre_plugin_state is _EvidenceState.ABSENT
        and pre_marketplace_state is _EvidenceState.ABSENT
        and pre_path_state is _EvidenceState.ABSENT
    ):
        return CodexReceiptRemovalNotInstalled()

    plugin_removal = _observe(
        CodexCompensationPortOperation.REMOVE_PLUGIN,
        port_admission.remove_plugin(request),
        request,
    )
    if type(plugin_removal) is not CodexRemovalConfirmed:
        return _blocked(CodexReceiptRemovalCompositionBlockReason.PLUGIN_REMOVAL_FAILED)

    marketplace_removal = _observe(
        CodexCompensationPortOperation.REMOVE_MARKETPLACE,
        port_admission.remove_marketplace(request),
        request,
    )
    if type(marketplace_removal) is not CodexRemovalConfirmed:
        return _blocked(CodexReceiptRemovalCompositionBlockReason.MARKETPLACE_REMOVAL_FAILED)

    post_plugin = _observe(
        CodexCompensationPortOperation.LIST_PLUGINS,
        port_admission.list_plugins(request),
        request,
    )
    post_marketplace = _observe(
        CodexCompensationPortOperation.LIST_MARKETPLACES,
        port_admission.list_marketplaces(request),
        request,
    )
    post_path = _observe(
        CodexCompensationPortOperation.PROVE_INSTALLED_PATH_ABSENT,
        port_admission.prove_installed_path_absent(request),
        request,
    )
    if (
        _plugin_state(post_plugin) is _EvidenceState.ABSENT
        and _marketplace_state(post_marketplace) is _EvidenceState.ABSENT
        and _path_state(post_path) is _EvidenceState.ABSENT
    ):
        return CodexReceiptRemovalRemoved()
    return _blocked(CodexReceiptRemovalCompositionBlockReason.POST_REMOVAL_EVIDENCE_INVALID)


def _map_request_block(value: CodexReceiptRemovalBlocked) -> CodexReceiptRemovalCompositionBlocked:
    if value.reason is CodexReceiptRemovalBlockReason.INVALID_INVOCATION:
        reason = CodexReceiptRemovalCompositionBlockReason.INVALID_INVOCATION
    elif value.reason is CodexReceiptRemovalBlockReason.INVALID_RECEIPT:
        reason = CodexReceiptRemovalCompositionBlockReason.INVALID_RECEIPT
    elif value.reason is CodexReceiptRemovalBlockReason.RECEIPT_MISMATCH:
        reason = CodexReceiptRemovalCompositionBlockReason.RECEIPT_MISMATCH
    else:
        raise AssertionError("unknown receipt-removal request block reason")
    return _blocked(reason)


def _blocked(reason: CodexReceiptRemovalCompositionBlockReason) -> CodexReceiptRemovalCompositionBlocked:
    return CodexReceiptRemovalCompositionBlocked(
        status="UNINSTALL_BLOCKED",
        reason=reason,
    )


def _observe(
    operation: CodexCompensationPortOperation,
    value: object,
    request: CodexCompensationPortRequest,
) -> CodexCompensationObservationResult:
    return observe_codex_compensation_operation(operation, value, request)


def _plugin_state(value: CodexCompensationObservationResult) -> _EvidenceState:
    if type(value) is CodexCompensationObservationRejected:
        return _EvidenceState.INVALID
    if type(value) is not CodexPluginListsProof:
        return _EvidenceState.INVALID
    if value.step is not CodexCompensationStep.PROVE_PLUGIN_LISTS_ABSENT:
        return _EvidenceState.INVALID
    truths = (value.installed, value.available)
    if all(truth is CodexProofTruth.PROVED_ABSENT for truth in truths):
        return _EvidenceState.ABSENT
    if any(truth is CodexProofTruth.RESIDUE for truth in truths):
        if all(
            truth is CodexProofTruth.PROVED_ABSENT or truth is CodexProofTruth.RESIDUE
            for truth in truths
        ):
            return _EvidenceState.RESIDUE
    return _EvidenceState.INVALID


def _marketplace_state(value: CodexCompensationObservationResult) -> _EvidenceState:
    if type(value) is CodexCompensationObservationRejected:
        return _EvidenceState.INVALID
    if type(value) is not CodexMarketplaceProof:
        return _EvidenceState.INVALID
    if value.step is not CodexCompensationStep.PROVE_MARKETPLACE_ABSENT:
        return _EvidenceState.INVALID
    if value.truth is CodexProofTruth.PROVED_ABSENT:
        return _EvidenceState.ABSENT
    if value.truth is CodexProofTruth.RESIDUE:
        return _EvidenceState.RESIDUE
    return _EvidenceState.INVALID


def _path_state(value: CodexCompensationObservationResult) -> _EvidenceState:
    if type(value) is CodexCompensationObservationRejected:
        return _EvidenceState.INVALID
    if type(value) is not CodexInstalledLocationProof:
        return _EvidenceState.INVALID
    if value.step is not CodexCompensationStep.PROVE_INSTALLED_LOCATION_ABSENT:
        return _EvidenceState.INVALID
    if value.truth is CodexProofTruth.PROVED_ABSENT:
        return _EvidenceState.ABSENT
    if value.truth is CodexProofTruth.RESIDUE:
        return _EvidenceState.RESIDUE
    return _EvidenceState.INVALID
