"""Effect-free composition root binding the validated Johnny Router components."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from library.workflow_router.profile import (
    ProjectWorkflowProfile,
    build_plugin_distribution_profile,
)

from .git_handoff_event_adapter import ReceiptBoundGitEventAdapter
from .plugin_bundle_builder import PluginBundleBuilder
from .project_runner_registry import ProjectRunnerRegistry, RunnerLifecyclePort
from .project_subscription_runtime import ProjectSubscriptionRuntime
from .role_wake_composition import (
    DurableRoleWakeAttemptStore,
    RoleWakeAttemptBoundaryPort,
    RoleWakeCoordinator,
    RoleWakePort,
)
from .runtime_dependency_lock import RuntimeDependencyLock, build_approved_runtime_lock
from .senior_review_inbox import (
    ReviewClusterBindingResolverPort,
    SeniorReviewInboxCoordinator,
    SeniorReviewInboxStorePort,
)


class JohnnyRouterCompositionStatus(str, Enum):
    """Finite outcomes of one composition attempt."""

    COMPOSED = "COMPOSED"
    BLOCKED = "BLOCKED"


class JohnnyRouterCompositionFailure(str, Enum):
    """Finite, dependency-ordered reasons the root refuses to compose."""

    PROFILE_MISMATCH = "PROFILE_MISMATCH"
    RUNTIME_LOCK_MISMATCH = "RUNTIME_LOCK_MISMATCH"
    RUNNER_PORT_UNAVAILABLE = "RUNNER_PORT_UNAVAILABLE"
    GIT_ADAPTER_UNAVAILABLE = "GIT_ADAPTER_UNAVAILABLE"
    REVIEW_STORE_UNAVAILABLE = "REVIEW_STORE_UNAVAILABLE"
    REVIEW_RESOLVER_UNAVAILABLE = "REVIEW_RESOLVER_UNAVAILABLE"
    WAKE_ATTEMPT_BOUNDARY_UNAVAILABLE = "WAKE_ATTEMPT_BOUNDARY_UNAVAILABLE"
    HOST_WAKE_PORT_UNAVAILABLE = "HOST_WAKE_PORT_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class JohnnyRouterCompositionPorts:
    """The injected effect-owning boundaries; composition never invokes them."""

    runner_lifecycle: RunnerLifecyclePort | None
    git_adapter: ReceiptBoundGitEventAdapter | None
    review_store: SeniorReviewInboxStorePort | None
    review_resolver: ReviewClusterBindingResolverPort | None
    wake_attempt_boundary: RoleWakeAttemptBoundaryPort | None
    host_wake_port: RoleWakePort | None


@dataclass(frozen=True, slots=True)
class JohnnyRouterComposition:
    """Every bound component of one validated Johnny Router root."""

    profile: ProjectWorkflowProfile
    runtime_lock: RuntimeDependencyLock
    runner_registry: ProjectRunnerRegistry
    subscription_runtime: ProjectSubscriptionRuntime
    review_inbox: SeniorReviewInboxCoordinator
    role_wake: RoleWakeCoordinator
    bundle_builder: PluginBundleBuilder


@dataclass(frozen=True, slots=True)
class JohnnyRouterCompositionResult:
    """Exactly one composed root or exactly one finite failure."""

    status: JohnnyRouterCompositionStatus
    composition: JohnnyRouterComposition | None
    failure: JohnnyRouterCompositionFailure | None


_RUNNER_LIFECYCLE_METHODS = ("start", "stop")
_REVIEW_STORE_METHODS = (
    "admit_event",
    "settle_wake",
    "claim_batch",
    "record_inspection",
    "decide_batch",
    "read_state",
)
_REVIEW_RESOLVER_METHODS = ("resolve",)
_WAKE_ATTEMPT_BOUNDARY_METHODS = (
    "claim_role_wake_attempt",
    "settle_role_wake_attempt",
)
_HOST_WAKE_PORT_METHODS = ("wake",)


def _blocked(failure: JohnnyRouterCompositionFailure) -> JohnnyRouterCompositionResult:
    return JohnnyRouterCompositionResult(
        status=JohnnyRouterCompositionStatus.BLOCKED,
        composition=None,
        failure=failure,
    )


def _conforms(candidate: object, method_names: tuple[str, ...]) -> bool:
    """Reject a malformed port whose declared boundary methods are not callable."""

    return all(callable(getattr(candidate, name, None)) for name in method_names)


def build_johnny_router(
    profile: ProjectWorkflowProfile,
    runtime_lock: RuntimeDependencyLock,
    ports: JohnnyRouterCompositionPorts,
) -> JohnnyRouterCompositionResult:
    """Validate every dependency in declared order, then bind without effects."""

    if (
        type(profile) is not ProjectWorkflowProfile
        or profile != build_plugin_distribution_profile()
    ):
        return _blocked(JohnnyRouterCompositionFailure.PROFILE_MISMATCH)
    if (
        type(runtime_lock) is not RuntimeDependencyLock
        or runtime_lock != build_approved_runtime_lock()
    ):
        return _blocked(JohnnyRouterCompositionFailure.RUNTIME_LOCK_MISMATCH)
    if type(ports) is not JohnnyRouterCompositionPorts:
        # A foreign container proves no port; the first dependency is unavailable.
        return _blocked(JohnnyRouterCompositionFailure.RUNNER_PORT_UNAVAILABLE)

    runner_lifecycle = ports.runner_lifecycle
    if runner_lifecycle is None or not _conforms(
        runner_lifecycle, _RUNNER_LIFECYCLE_METHODS
    ):
        return _blocked(JohnnyRouterCompositionFailure.RUNNER_PORT_UNAVAILABLE)
    git_adapter = ports.git_adapter
    if git_adapter is None or type(git_adapter) is not ReceiptBoundGitEventAdapter:
        return _blocked(JohnnyRouterCompositionFailure.GIT_ADAPTER_UNAVAILABLE)
    review_store = ports.review_store
    if review_store is None or not _conforms(review_store, _REVIEW_STORE_METHODS):
        return _blocked(JohnnyRouterCompositionFailure.REVIEW_STORE_UNAVAILABLE)
    review_resolver = ports.review_resolver
    if review_resolver is None or not _conforms(
        review_resolver, _REVIEW_RESOLVER_METHODS
    ):
        return _blocked(JohnnyRouterCompositionFailure.REVIEW_RESOLVER_UNAVAILABLE)
    wake_attempt_boundary = ports.wake_attempt_boundary
    if wake_attempt_boundary is None or not _conforms(
        wake_attempt_boundary, _WAKE_ATTEMPT_BOUNDARY_METHODS
    ):
        return _blocked(
            JohnnyRouterCompositionFailure.WAKE_ATTEMPT_BOUNDARY_UNAVAILABLE
        )
    host_wake_port = ports.host_wake_port
    if host_wake_port is None or not _conforms(host_wake_port, _HOST_WAKE_PORT_METHODS):
        return _blocked(JohnnyRouterCompositionFailure.HOST_WAKE_PORT_UNAVAILABLE)

    runner_registry = ProjectRunnerRegistry(runner_lifecycle)
    subscription_runtime = ProjectSubscriptionRuntime(runner_registry, git_adapter)
    attempt_store = DurableRoleWakeAttemptStore(wake_attempt_boundary)
    role_wake = RoleWakeCoordinator(attempt_store, host_wake_port)
    review_inbox = SeniorReviewInboxCoordinator(
        review_store, review_resolver, role_wake
    )
    return JohnnyRouterCompositionResult(
        status=JohnnyRouterCompositionStatus.COMPOSED,
        composition=JohnnyRouterComposition(
            profile=profile,
            runtime_lock=runtime_lock,
            runner_registry=runner_registry,
            subscription_runtime=subscription_runtime,
            review_inbox=review_inbox,
            role_wake=role_wake,
            bundle_builder=PluginBundleBuilder(),
        ),
        failure=None,
    )


__all__ = [
    "JohnnyRouterComposition",
    "JohnnyRouterCompositionFailure",
    "JohnnyRouterCompositionPorts",
    "JohnnyRouterCompositionResult",
    "JohnnyRouterCompositionStatus",
    "build_johnny_router",
]
