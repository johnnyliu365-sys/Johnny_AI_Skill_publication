"""Settle one admitted registration-compensation claim through composition."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import ValidationError

from .codex_compensation_composition import compose_codex_compensation
from .codex_compensation_port import (
    CodexCompensationPortCapability,
    CodexCompensationPortManifest,
    CodexCompensationPortRejected,
    CodexCompensationPortRequest,
    admit_codex_compensation_port,
)
from .codex_compensation_reducer import (
    CodexCompensationBlockReason,
    CodexCompensationBlocked,
    CodexCompensationPlan,
    CodexCompensationResult,
    build_compensation_plan,
)
from .codex_registration_port import (
    CodexRegistrationPortRequest,
    CodexRegistrationPortValueRejected,
    revalidate_registration_port_request,
)
from .codex_registration_reducer import CodexRegistrationCompensationRequired
from .codex_registration_settlement_authority import (
    CodexRegistrationSettlementClaimBlocked,
    consume_codex_registration_compensation_claim,
)
from .codex_registration_transaction import CodexRegistrationAddRecovery


CodexRegistrationCompensationSettlement: TypeAlias = (
    CodexCompensationPortRejected
    | CodexRegistrationSettlementClaimBlocked
    | CodexCompensationResult
)


def settle_codex_registration_compensation(
    claim: object,
    port_candidate: object,
) -> CodexRegistrationCompensationSettlement:
    """Consume one exact compensation claim only after local port admission."""

    admitted_port = admit_codex_compensation_port(port_candidate)
    if type(admitted_port) is CodexCompensationPortRejected:
        return admitted_port
    if type(admitted_port) is not CodexCompensationPortCapability:
        return _plan_invalid()

    consumed = consume_codex_registration_compensation_claim(claim)
    if type(consumed) is CodexRegistrationSettlementClaimBlocked:
        return consumed
    if type(consumed) is CodexRegistrationCompensationRequired:
        context = _terminal_context(consumed)
    elif type(consumed) is CodexRegistrationAddRecovery:
        context = _recovery_context(consumed)
    else:
        return _plan_invalid()

    if isinstance(context, CodexCompensationBlocked):
        return context
    request, plan = context
    return compose_codex_compensation(admitted_port, request, plan)


def _terminal_context(
    decision: CodexRegistrationCompensationRequired,
) -> tuple[CodexCompensationPortRequest, CodexCompensationPlan] | CodexCompensationBlocked:
    """Use only the consumed terminal decision's exact request and plan."""

    try:
        owned_request = decision.request
        owned_plan = decision.plan
    except AttributeError:
        return _plan_invalid()
    if type(owned_request) is not CodexRegistrationPortRequest:
        return _plan_invalid()
    if type(owned_plan) is not CodexCompensationPlan:
        return _plan_invalid()
    port_request = _port_request_from_owned_request(owned_request)
    if isinstance(port_request, CodexCompensationBlocked):
        return port_request
    return port_request, owned_plan


def _recovery_context(
    recovery: CodexRegistrationAddRecovery,
) -> tuple[CodexCompensationPortRequest, CodexCompensationPlan] | CodexCompensationBlocked:
    """Rebuild the sole recovery plan from the consumed request and journal."""

    try:
        owned_request = recovery.request
        owned_journal = recovery.journal
    except AttributeError:
        return _plan_invalid()
    if type(owned_request) is not CodexRegistrationPortRequest:
        return _plan_invalid()
    port_request = _port_request_from_owned_request(owned_request)
    if isinstance(port_request, CodexCompensationBlocked):
        return port_request

    rebuilt_request = revalidate_registration_port_request(owned_request)
    if isinstance(rebuilt_request, CodexRegistrationPortValueRejected):
        return _plan_invalid()
    plan = build_compensation_plan(
        owned_journal,
        rebuilt_request.preflight,
        rebuilt_request.attempt_id,
    )
    if type(plan) is not CodexCompensationPlan:
        return _plan_invalid()
    return port_request, plan


def _port_request_from_owned_request(
    value: CodexRegistrationPortRequest,
) -> CodexCompensationPortRequest | CodexCompensationBlocked:
    """Rebuild every manifest field from the claim-owned registration request."""

    rebuilt = revalidate_registration_port_request(value)
    if isinstance(rebuilt, CodexRegistrationPortValueRejected):
        return _plan_invalid()
    try:
        manifest = CodexCompensationPortManifest(
            installation_id=rebuilt.preflight.installation_id,
            root=rebuilt.preflight.root,
            marketplace=rebuilt.preflight.marketplace,
            marketplace_source=rebuilt.preflight.marketplace_source,
            plugin_id=rebuilt.expected_plugin_id,
            plugin=rebuilt.preflight.plugin,
            version=rebuilt.expected_version,
            installed_locator=rebuilt.installed_locator,
            auth_policy=rebuilt.expected_auth_policy,
            digest=rebuilt.digest,
        )
        return CodexCompensationPortRequest(manifest=manifest)
    except (AttributeError, TypeError, ValidationError, ValueError):
        return _plan_invalid()


def _plan_invalid() -> CodexCompensationBlocked:
    return CodexCompensationBlocked(
        status="COMPENSATION_BLOCKED",
        reason=CodexCompensationBlockReason.PLAN_INVALID,
    )
