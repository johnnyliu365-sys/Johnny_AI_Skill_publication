"""Transactional target-owned documents and handoff-tree plan rendering."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile

from library.workflow_router.role_supervision_contracts import (
    ArtifactKind,
    ArtifactLifecycle,
    HandoffChildRef,
    HandoffIndex,
    HandoffRootManifest,
)
from library.workflow_router.target_document_contracts import (
    ArtifactDocumentKind,
    DocumentMutationMode,
    DocumentWriteFailure,
    DocumentWriteResult,
    DocumentWriteStatus,
    HandoffTreeBootstrapRequest,
    TargetDocumentMutation,
    TargetDocumentPlan,
    derive_document_digest,
)


@dataclass(frozen=True, slots=True)
class TargetWorkspace:
    """Exact existing Git worktree root used only by the filesystem adapter."""

    root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise TypeError("target workspace root must be a Path")
        if not self.root.is_absolute():
            raise ValueError("target workspace root must be absolute")
        resolved = self.root.resolve(strict=True)
        if resolved != self.root or not resolved.is_dir():
            raise ValueError("target workspace root must be an existing resolved directory")
        completed = subprocess.run(
            ("git", "-C", str(resolved), "rev-parse", "--show-toplevel"),
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if completed.returncode != 0:
            raise ValueError("target workspace must be a readable Git worktree")
        if Path(completed.stdout.strip()).resolve(strict=True) != resolved:
            raise ValueError("target workspace must equal the Git top level")


def _write_result(failure: DocumentWriteFailure) -> DocumentWriteResult:
    status = (
        DocumentWriteStatus.STORAGE_UNAVAILABLE
        if failure is DocumentWriteFailure.STORAGE_UNAVAILABLE
        else DocumentWriteStatus.REJECTED
    )
    return DocumentWriteResult(status=status, failure=failure)


class TransactionalTargetDocumentWriter:
    """Apply an exact finite CAS plan without scanning or staging the repository."""

    def __init__(self, workspace: TargetWorkspace) -> None:
        if type(workspace) is not TargetWorkspace:
            raise TypeError("document writer requires an exact TargetWorkspace")
        self._root = workspace.root

    def _head(self) -> str | None:
        try:
            completed = subprocess.run(
                ("git", "-C", str(self._root), "rev-parse", "HEAD"),
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    def _target(self, relative_path: str) -> Path | None:
        relative = PurePosixPath(relative_path)
        candidate = self._root.joinpath(*relative.parts)
        existing_ancestor = candidate.parent
        while not existing_ancestor.exists() and existing_ancestor != self._root:
            existing_ancestor = existing_ancestor.parent
        try:
            ancestor = existing_ancestor.resolve(strict=True)
            ancestor.relative_to(self._root)
            if candidate.exists() or candidate.is_symlink():
                candidate.resolve(strict=True).relative_to(self._root)
        except (OSError, RuntimeError, ValueError):
            return None
        return candidate

    def apply(self, plan: TargetDocumentPlan) -> DocumentWriteResult:
        if type(plan) is not TargetDocumentPlan:
            return _write_result(DocumentWriteFailure.PATH_STATE_MISMATCH)
        if self._head() != plan.baseline_commit:
            return _write_result(DocumentWriteFailure.BASELINE_MISMATCH)

        targets: list[tuple[TargetDocumentMutation, Path, bytes | None]] = []
        for mutation in plan.mutations:
            target = self._target(mutation.path)
            if target is None:
                return _write_result(DocumentWriteFailure.PATH_ESCAPE)
            exists = target.exists() or target.is_symlink()
            if mutation.mode is DocumentMutationMode.CREATE:
                if exists:
                    return _write_result(DocumentWriteFailure.PATH_STATE_MISMATCH)
                prior = None
            else:
                if not exists or not target.is_file() or target.is_symlink():
                    return _write_result(DocumentWriteFailure.PATH_STATE_MISMATCH)
                try:
                    prior = target.read_bytes()
                except OSError:
                    return _write_result(DocumentWriteFailure.STORAGE_UNAVAILABLE)
                if derive_document_digest(prior.decode("utf-8")) != mutation.expected_current_digest:
                    return _write_result(DocumentWriteFailure.PATH_STATE_MISMATCH)
            targets.append((mutation, target, prior))

        temporary_paths: list[Path] = []
        replacements: list[tuple[Path, bytes | None]] = []
        try:
            prepared: list[tuple[TargetDocumentMutation, Path, Path, bytes | None]] = []
            for mutation, target, prior in targets:
                target.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=".target-document-",
                    suffix=".tmp",
                    dir=target.parent,
                )
                temporary_path = Path(temporary_name)
                temporary_paths.append(temporary_path)
                with os.fdopen(descriptor, "wb") as temporary:
                    temporary.write(mutation.content.encode("utf-8"))
                    temporary.flush()
                    os.fsync(temporary.fileno())
                prepared.append((mutation, target, temporary_path, prior))
            for mutation, target, temporary_path, prior in prepared:
                del mutation
                os.replace(temporary_path, target)
                replacements.append((target, prior))
            return DocumentWriteResult(
                status=DocumentWriteStatus.APPLIED,
                written_paths=tuple(mutation.path for mutation in plan.mutations),
                written_digests=tuple(
                    mutation.content_digest for mutation in plan.mutations
                ),
            )
        except (OSError, UnicodeError):
            self._rollback(replacements)
            return _write_result(DocumentWriteFailure.STORAGE_UNAVAILABLE)
        finally:
            for temporary_path in temporary_paths:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _rollback(replacements: list[tuple[Path, bytes | None]]) -> None:
        for target, prior in reversed(replacements):
            try:
                if prior is None:
                    target.unlink(missing_ok=True)
                    continue
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=".target-document-rollback-",
                    suffix=".tmp",
                    dir=target.parent,
                )
                temporary_path = Path(temporary_name)
                try:
                    with os.fdopen(descriptor, "wb") as temporary:
                        temporary.write(prior)
                        temporary.flush()
                        os.fsync(temporary.fileno())
                    os.replace(temporary_path, target)
                finally:
                    temporary_path.unlink(missing_ok=True)
            except OSError:
                continue


def _revision_from_digest(digest: str) -> str:
    return "rev-" + digest.removeprefix("sha256_")[:16]


def _model_text(model: HandoffIndex | HandoffRootManifest) -> str:
    return model.model_dump_json(indent=2) + "\n"


def _readme_section(request: HandoffTreeBootstrapRequest) -> str:
    return (
        "\n## Receipt-bound project handoff\n\n"
        f"- Approved behavior: [{request.spec_path}]({request.spec_path}).\n"
        "- Machine-readable handoff entry: [doc/handoffs/index.json](doc/handoffs/index.json).\n"
        "- A shell or IDE restart inside the same admitted task does not transfer ownership.\n"
        "- A task, writer, host, or machine change requires old-writer revocation before replacement.\n"
        "- Model escalation is limited to the current ticket; the next ticket returns to its profile default.\n"
        "- One ticket/worktree has one active writer; reviewer and architecture roles stay read-only.\n"
        "- No heartbeat, scheduled polling, or recurring watcher is authorized.\n"
        "- Deployment remains separate and requires its own explicit effect authority.\n"
        "- External control-plane removal is unconditional and does not alter project files.\n"
        "- A successor may use any workflow or optionally re-adopt this protocol with fresh live authority.\n"
    )


def _readme(title: str, child: str) -> str:
    return (
        f"# {title}\n\n"
        "This directory is project-owned handoff evidence. Details live only in the exact child "
        f"referenced by `{child}`; this README is an operation entry, not an event ledger.\n"
    )


def _mutation(
    *,
    path: str,
    kind: ArtifactDocumentKind,
    content: str,
    mode: DocumentMutationMode = DocumentMutationMode.CREATE,
    expected: str | None = None,
    sealed: bool = False,
) -> TargetDocumentMutation:
    return TargetDocumentMutation(
        path=path,
        artifact_kind=kind,
        mode=mode,
        expected_current_digest=expected,
        content=content,
        content_digest=derive_document_digest(content),
        sealed=sealed,
    )


def build_handoff_tree_bootstrap_plan(
    request: HandoffTreeBootstrapRequest,
) -> TargetDocumentPlan:
    """Render the default direct-child tree and concise root operation entry."""

    year = str(request.year)
    feature = request.feature_slug
    ticket = request.ticket_slug
    leaf = request.leaf
    root_index_path = "doc/handoffs/index.json"
    year_index_path = f"doc/handoffs/{year}/index.json"
    feature_index_path = f"doc/handoffs/{year}/{feature}/index.json"
    ticket_index_path = f"doc/handoffs/{year}/{feature}/{ticket}/index.json"
    leaf_path = f"doc/handoffs/{year}/{feature}/{ticket}/{leaf.handoff_id}.json"

    leaf_text = leaf.model_dump_json(indent=2) + "\n"
    leaf_document_digest = derive_document_digest(leaf_text)
    leaf_child = HandoffChildRef(
        child_id=leaf.handoff_id,
        child_kind=ArtifactKind.HANDOFF_LEAF,
        revision=leaf.ticket_revision,
        content_digest=leaf_document_digest,
        lifecycle=ArtifactLifecycle.ACTIVE,
        target_ref=leaf_path,
    )
    ticket_index = HandoffIndex(
        index_id=f"index-{ticket}",
        index_ref=ticket_index_path,
        revision=_revision_from_digest(leaf_document_digest),
        direct_child_refs=(leaf_child,),
    )
    ticket_index_text = _model_text(ticket_index)
    ticket_index_digest = derive_document_digest(ticket_index_text)
    ticket_child = HandoffChildRef(
        child_id=ticket,
        child_kind=ArtifactKind.TICKET_INDEX,
        revision=_revision_from_digest(ticket_index_digest),
        content_digest=ticket_index_digest,
        lifecycle=ArtifactLifecycle.ACTIVE,
        target_ref=ticket_index_path,
    )
    feature_index = HandoffIndex(
        index_id=f"index-{feature}",
        index_ref=feature_index_path,
        revision=_revision_from_digest(ticket_index_digest),
        direct_child_refs=(ticket_child,),
    )
    feature_index_text = _model_text(feature_index)
    feature_index_digest = derive_document_digest(feature_index_text)
    feature_child = HandoffChildRef(
        child_id=feature,
        child_kind=ArtifactKind.FEATURE_INDEX,
        revision=_revision_from_digest(feature_index_digest),
        content_digest=feature_index_digest,
        lifecycle=ArtifactLifecycle.ACTIVE,
        target_ref=feature_index_path,
    )
    year_index = HandoffIndex(
        index_id=f"index-partition-{year}",
        index_ref=year_index_path,
        revision=_revision_from_digest(feature_index_digest),
        direct_child_refs=(feature_child,),
    )
    year_index_text = _model_text(year_index)
    year_index_digest = derive_document_digest(year_index_text)
    year_child = HandoffChildRef(
        child_id=f"partition-{year}",
        child_kind=ArtifactKind.PARTITION_INDEX,
        revision=_revision_from_digest(year_index_digest),
        content_digest=year_index_digest,
        lifecycle=ArtifactLifecycle.ACTIVE,
        target_ref=year_index_path,
    )
    manifest = HandoffRootManifest(
        project_id=request.project_id,
        handoff_protocol_id=request.protocol_id,
        schema_revision=request.schema_revision,
        minimum_compatible_revision=request.compatibility_revision,
        manifest_revision=_revision_from_digest(year_index_digest),
        direct_child_refs=(year_child,),
        active_leaf_refs=(leaf_child,),
        minimum_adoption_capabilities=request.minimum_adoption_capabilities,
        last_observed_control_plane_state=request.control_plane_state,
        last_observation_revision=_revision_from_digest(leaf_document_digest),
        last_non_replayable_receipt_ref=leaf.router_receipt_ref,
    )
    root_readme = request.root_readme_content.rstrip() + "\n" + _readme_section(request)
    mutations = (
        _mutation(
            path="README.md",
            kind=ArtifactDocumentKind.ROOT_README,
            content=root_readme,
            mode=DocumentMutationMode.UPDATE,
            expected=request.root_readme_digest,
        ),
        _mutation(
            path="doc/handoffs/README.md",
            kind=ArtifactDocumentKind.HANDOFF_README,
            content=_readme("Project handoffs", root_index_path),
        ),
        _mutation(
            path=root_index_path,
            kind=ArtifactDocumentKind.HANDOFF_INDEX,
            content=manifest.model_dump_json(indent=2) + "\n",
        ),
        _mutation(
            path=f"doc/handoffs/{year}/README.md",
            kind=ArtifactDocumentKind.HANDOFF_README,
            content=_readme(f"Handoffs {year}", year_index_path),
        ),
        _mutation(
            path=year_index_path,
            kind=ArtifactDocumentKind.HANDOFF_INDEX,
            content=year_index_text,
        ),
        _mutation(
            path=f"doc/handoffs/{year}/{feature}/README.md",
            kind=ArtifactDocumentKind.HANDOFF_README,
            content=_readme(f"Handoff feature {feature}", feature_index_path),
        ),
        _mutation(
            path=feature_index_path,
            kind=ArtifactDocumentKind.HANDOFF_INDEX,
            content=feature_index_text,
        ),
        _mutation(
            path=f"doc/handoffs/{year}/{feature}/{ticket}/README.md",
            kind=ArtifactDocumentKind.HANDOFF_README,
            content=_readme(f"Handoff ticket {ticket}", ticket_index_path),
        ),
        _mutation(
            path=ticket_index_path,
            kind=ArtifactDocumentKind.HANDOFF_INDEX,
            content=ticket_index_text,
        ),
        _mutation(
            path=leaf_path,
            kind=ArtifactDocumentKind.HANDOFF_LEAF,
            content=leaf_text,
            sealed=True,
        ),
    )
    return TargetDocumentPlan(
        project_id=request.project_id,
        baseline_commit=request.baseline_commit,
        mutations=mutations,
    )


def detach_target_documents() -> tuple[TargetDocumentMutation, ...]:
    """Detachment is deliberately a target-filesystem no-op."""

    return ()


__all__ = [
    "TargetWorkspace",
    "TransactionalTargetDocumentWriter",
    "build_handoff_tree_bootstrap_plan",
    "detach_target_documents",
]
