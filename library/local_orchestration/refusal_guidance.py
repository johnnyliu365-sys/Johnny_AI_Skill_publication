"""Say what to do next, for refusals that until now said only what went wrong.

Every gate in this repository refuses with a finite named code, and a code is
where the answer stops. `INSTALL_BLOCKED_INSIDE_REPOSITORY` is exact, durable
and completely opaque to the person who double-clicked the installer inside
their own project folder: the rule it names -- do not bootstrap from inside a
Git checkout -- is not a rule they could have known.

**The reader that matters is an agent, and that is what shapes this module.**
A vibe coder meets these refusals through Claude Code or Codex. They will not
read `RULE_AND_SUBJECT_IN_ONE_CHANGE`; the agent will. So the goal is not
friendlier prose. It is to carry enough structure that an agent can tell
whether the refusal is its to settle -- because the expensive failure here is
not an agent that gives up, it is an agent that helps.

**The three categories, and why confusing them is the whole risk.**

`AGENT_MAY_RESOLVE` -- do it, then say you did. An unclean worktree gets
committed or stashed; the wrong branch gets checked out. Afterwards the
condition is genuinely gone and nothing about the record is false.

`OWNER_MUST_DECIDE` -- stop, and name what a person has to supply. Whether to
install Git on this machine is not the decision of whatever is holding the
keyboard.

`NEVER_AUTO_RESOLVE` -- stop and explain; going around it is the disaster. An
agent that meets `DIGEST_MISMATCH` and produces a fresh digest has ended the
supply-chain check, will report the matter resolved, and has left a state
nobody can distinguish from a verified install. That is governance ticket 04
wearing a new face: there, our own documents narrated a wake-up that never
happened; here, a helpful agent we failed to stop narrates a repair that never
happened.

**Where the line around `NEVER_AUTO_RESOLVE` is drawn.** One test, three arms.
A code belongs to this category when at least one action that would silence the
refusal is an edit to *what the check reads* -- the rule, the pinned reference
value, or the evidence -- rather than to *what the check is about*, and the
check cannot tell afterwards which action was taken.

- The *rule* arm: a boundary violation is silenced either by leaving the file
  alone or by adding it to the declaration. The gate sees only that it passes.
- The *reference* arm: a stale policy pin is silenced either by getting the
  text approved or by producing a pin from the new text. A digest here is not
  a checksum against corruption, it is the record that a specific text was read
  and approved, and a pin made from the text it is meant to certify records
  nobody having read anything.
- The *evidence* arm: a declined confirmation is silenced either by a person
  agreeing or by something typing into a prompt that exists to reach a person.

The mirror question separates this category from `OWNER_MUST_DECIDE`: is there
a value a person is entitled to hand this call that makes the refusal genuinely
inapplicable? For `PYTHON_311_UNAVAILABLE` there is -- they install Python and
the condition is over. For `DIGEST_MISMATCH` there is not: nobody can decide
that the archive matches. The refusal is a verdict about the world, and every
sanctioned move is outside this call.

Two consequences worth stating, because they look like inconsistencies:

`RULE_AND_SUBJECT_IN_ONE_CHANGE` is `AGENT_MAY_RESOLVE` even though it guards
the control plane. Its sanctioned repair -- two commits instead of one -- is
named in the door it belongs to, and after the split the thing the rule stands
in for still holds: a reviewer really can accept one half without the other.
Nothing was traded for silence.

`USER_DECLINED` is `NEVER_AUTO_RESOLVE` even though it looks like a person
supplying a value, which is the shape of `OWNER_MUST_DECIDE`. The difference
is where the value lands. Under `OWNER_MUST_DECIDE` a person decides and an
agent may then act on it elsewhere. Here the prompt is authenticating a human
at the keyboard, so a relayed answer is not consent being carried, it is
consent being manufactured.

**Guidance for `NEVER_AUTO_RESOLVE` must not carry the way around.** Pinned by
`never_auto_resolve_violations`: no term from `BYPASS_TERMS` may appear, even
inside a prohibition. "Do not recompute the digest" still hands over the verb
and the object, and an agent skimming for an action finds one. The category
also has to earn its name positively -- the first step stops, and some step
routes to a person -- because a lexicon can only refuse phrasings it was told
about.

**Classification has no default, at either layer.** `RefusalGuidance.category`
carries no default value, so an entry that omits it does not construct. And
`audit_classification` reads the codes that exist -- from the enum sources by
syntax, and from the installer scripts by their call sites -- and reports any
that no entry covers. Forgetting is therefore loud; if it were quiet, and the
quiet answer were the permissive category, forgetting would mean admitting.

**The enums nobody has classified yet are reported, not hidden.** This module
covers five surfaces: the two installer entry points, the two mutation gates,
and its own lookup failures. That leaves forty-five of the forty-eight
`Failure` enums under `library/` for later batches. The audit accounts for
every one of them as covered or uncovered and refuses to balance if one is
neither, so an empty uncovered list cannot be arranged -- it can only be true.

**Sources are read as text, never imported.** A checker that had to import
forty-seven modules to count their failure codes would fail whenever any of
them failed to import, and would fail in a way that looks like a
classification problem.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------
# The taxonomy
# --------------------------------------------------------------------------


class RefusalCategory(str, Enum):
    """What an agent that meets this refusal is allowed to do about it.

    Three values, never two and never four. Collapsing the last two into
    "stop" would erase the difference between waiting for a person and being
    refused outright, which is the difference between an install that resumes
    and a supply chain that was never checked.
    """

    AGENT_MAY_RESOLVE = "AGENT_MAY_RESOLVE"
    OWNER_MUST_DECIDE = "OWNER_MUST_DECIDE"
    NEVER_AUTO_RESOLVE = "NEVER_AUTO_RESOLVE"


class RefusalGuidance(BaseModel):
    """One refusal code, its category, and the way out of it.

    `category` has no default. A new code whose entry forgets it raises at
    construction rather than landing in whichever category was cheapest to
    write down, and the cheapest default to write down is always the
    permissive one.

    `next_steps` has no empty form either. An entry that classified a code and
    then said nothing would satisfy every count in the audit while delivering
    exactly what this module exists to replace.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    surface: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=1, max_length=128)
    category: RefusalCategory
    next_steps: tuple[str, ...] = Field(min_length=1)

    @property
    def key(self) -> tuple[str, str]:
        return self.surface, self.code


# --------------------------------------------------------------------------
# Surfaces
# --------------------------------------------------------------------------

#: The two installer entry points. They are not Python enums, they are the
#: only refusals a person sees before any of this repository is on their disk,
#: and they are the reason this ticket exists.
INSTALL_SCRIPT_SURFACE = "install.ps1"
INSTALL_WRAPPER_SURFACE = "johnny-install.cmd"

DOCUMENT_GATE_SURFACE = (
    "library/local_orchestration/document_mutation_gate.py::DocumentMutationFailure"
)
CONTROL_PLANE_SURFACE = (
    "library/local_orchestration/control_plane_mutation.py::ControlPlaneMutationFailure"
)

#: This module raises refusals of its own, and the module that exists to stop
#: refusals from arriving unclassified does not get to arrive unclassified.
LOOKUP_SURFACE = (
    "library/local_orchestration/refusal_guidance.py::GuidanceLookupFailure"
)

#: Surfaces whose codes must be classified exhaustively. Adding a surface here
#: without classifying its codes turns the audit red, which is the point.
COVERED_SURFACES: tuple[str, ...] = (
    INSTALL_SCRIPT_SURFACE,
    INSTALL_WRAPPER_SURFACE,
    DOCUMENT_GATE_SURFACE,
    CONTROL_PLANE_SURFACE,
    LOOKUP_SURFACE,
)


def _steps(*lines: str) -> tuple[str, ...]:
    return tuple(lines)


_A = RefusalCategory.AGENT_MAY_RESOLVE
_O = RefusalCategory.OWNER_MUST_DECIDE
_N = RefusalCategory.NEVER_AUTO_RESOLVE


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------
#
# Guidance text is ASCII and carries no quote, apostrophe or backslash. It is
# transported through a JSON literal built by string formatting in PowerShell
# and through single-quoted PowerShell literals, and a checker that had to
# reason about escaping in two languages would eventually get one of them
# wrong. `guidance_is_transport_safe` pins the constraint.

GUIDANCE: tuple[RefusalGuidance, ...] = (
    # -- install.ps1 -------------------------------------------------------
    RefusalGuidance(
        surface=INSTALL_SCRIPT_SURFACE,
        code="INSTALL_BLOCKED_INSIDE_REPOSITORY",
        category=_A,
        next_steps=_steps(
            "The installer refuses to bootstrap from inside a Git checkout, and the "
            "folder it was started in is one.",
            "Move the release zip and the installer into a folder that is not inside "
            "any Git checkout, such as a new folder on the Desktop, and start it "
            "again from there.",
            "Nothing is written into the folder it is launched from either way; the "
            "install goes to the per-user root under LOCALAPPDATA.",
        ),
    ),
    RefusalGuidance(
        surface=INSTALL_SCRIPT_SURFACE,
        code="GIT_UNAVAILABLE",
        category=_O,
        next_steps=_steps(
            "Stop: the installer needs the git command and this machine has none on "
            "PATH.",
            "Ask the person running this whether to install Git for Windows. "
            "Installing software on their machine is theirs to decide.",
            "After they install it, open a new terminal so PATH is picked up, then "
            "start the installer again.",
        ),
    ),
    RefusalGuidance(
        surface=INSTALL_SCRIPT_SURFACE,
        code="BUNDLE_NOT_FOUND",
        category=_A,
        next_steps=_steps(
            "The release zip named on the command line is not there.",
            "Put the published zip beside the installer under exactly the name it "
            "was published with, and start the installer again from that folder.",
            "Do not reach for a different archive: the digest check refuses one, and "
            "that refusal is not yours to settle.",
        ),
    ),
    RefusalGuidance(
        surface=INSTALL_SCRIPT_SURFACE,
        code="PYTHON_311_UNAVAILABLE",
        category=_O,
        next_steps=_steps(
            "Stop: the control runtime needs Python 3.11 reachable as py -3.11, and "
            "this machine has no such interpreter.",
            "Ask the person running this whether to install Python 3.11 from "
            "python.org with the py launcher enabled. That is a change to their "
            "machine and theirs to decide.",
            "After they install it, start the installer again.",
        ),
    ),
    RefusalGuidance(
        surface=INSTALL_SCRIPT_SURFACE,
        code="RUNTIME_LOCK_MISSING",
        category=_N,
        next_steps=_steps(
            "Stop. The archive holds no dependency lock, and the published release "
            "holds one, so this archive is not the published release.",
            "What is missing is the list of exact versions and artifact hashes the "
            "install was going to be held to. Supplying that list locally would "
            "produce an install held to whatever was supplied.",
            "Tell the person running this that the archive they have is not the "
            "approved release, show them this code, and let them fetch the release "
            "again from where the owner published it.",
        ),
    ),
    RefusalGuidance(
        surface=INSTALL_SCRIPT_SURFACE,
        code="USER_DECLINED",
        category=_N,
        next_steps=_steps(
            "Stop. A person read the exact dependency plan and did not type the "
            "confirmation word, so consent for this install does not exist.",
            "That prompt is there to reach a human at the keyboard. Whatever an "
            "agent puts into it is not consent carried, it is consent manufactured, "
            "and afterwards nothing tells an unconsented install apart from a "
            "consented one.",
            "Tell the person what the plan contained and let them decide. If they "
            "want it, they start the installer themselves.",
        ),
    ),
    RefusalGuidance(
        surface=INSTALL_SCRIPT_SURFACE,
        code="BOOTSTRAP_MISSING",
        category=_N,
        next_steps=_steps(
            "Stop. The archive holds no bootstrap module, and the published release "
            "holds one, so this archive is not the published release.",
            "The bootstrap is the code that builds the hash-locked control venv. An "
            "archive missing it and an archive carrying a different one look the "
            "same from here.",
            "Tell the person running this that the archive they have is not the "
            "approved release, show them this code, and let them fetch the release "
            "again from where the owner published it.",
        ),
    ),
    # -- johnny-install.cmd ------------------------------------------------
    RefusalGuidance(
        surface=INSTALL_WRAPPER_SURFACE,
        code="BUNDLE_NOT_FOUND",
        category=_A,
        next_steps=_steps(
            "The wrapper looks for the release zip in its own folder and it is not "
            "there.",
            "Put the published zip beside johnny-install.cmd under exactly the name "
            "the wrapper prints, then double-click the wrapper again.",
            "Do not reach for a different archive: the digest check refuses one, and "
            "that refusal is not yours to settle.",
        ),
    ),
    RefusalGuidance(
        surface=INSTALL_WRAPPER_SURFACE,
        code="DIGEST_MISMATCH",
        category=_N,
        next_steps=_steps(
            "Stop. The SHA-256 of the archive on disk is not the digest this release "
            "was approved as. The wrapper printed both values.",
            "This is the supply-chain check, and it has one meaning. The pinned "
            "value is a record that a specific artifact was approved, so a value "
            "taken from the artifact in front of it would be a record of nothing.",
            "Tell the person running this, quote both digests, and let them fetch "
            "the release again from where it was published.",
        ),
    ),
    RefusalGuidance(
        surface=INSTALL_WRAPPER_SURFACE,
        code="INSTALL_SCRIPT_MISSING",
        category=_N,
        next_steps=_steps(
            "Stop. The archive passed the digest check but holds no install.ps1, "
            "which the published release holds.",
            "A digest that matches and contents that do not is the shape of a pinned "
            "value that no longer describes the release it names, and only the owner "
            "can say which of the two is wrong.",
            "Tell the person running this, show them this code, and let them fetch "
            "the release again from where the owner published it.",
        ),
    ),
    # -- document_mutation_gate --------------------------------------------
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="REQUEST_INVALID",
        category=_A,
        next_steps=_steps(
            "The object handed to the gate is not a DocumentMutationRequest. This "
            "gate matches its request type by identity and will not read the "
            "control-plane request, which is structurally close.",
            "Build a DocumentMutationRequest and call admit_document_mutation again.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="REPOSITORY_UNREADABLE",
        category=_A,
        next_steps=_steps(
            "Read the detail field: it names which precondition failed.",
            "An unclean integration worktree gets committed or stashed. A wrong "
            "checked-out branch gets the integration branch checked out. A candidate "
            "sharing no history gets fetched.",
            "Call the gate again, and say which of those you did.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="TICKET_UNREADABLE",
        category=_O,
        next_steps=_steps(
            "Stop and report which ticket path failed to resolve on the integration "
            "branch; offending_path names it.",
            "It means one of two things and only a person can say which: the request "
            "names the wrong path, or the ticket has not been accepted onto the "
            "integration branch yet.",
            "The second is the control plane to settle, because implementers do not "
            "land tickets. Ask before doing anything else.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="BOUNDARY_UNDECLARED",
        category=_N,
        next_steps=_steps(
            "Stop. The ticket on the integration branch declares no johnny-boundary "
            "block, so nothing states what this change was allowed to touch.",
            "That declaration is the rule this change is measured against. A change "
            "that arrives carrying its own rule has been measured by nothing.",
            "Tell the person that the ticket needs a declared boundary, and let the "
            "control plane put one on the integration branch where it is reviewed on "
            "its own.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="BOUNDARY_UNPARSABLE",
        category=_N,
        next_steps=_steps(
            "Stop. The ticket declares a boundary block that does not parse; the "
            "detail field names the line that failed.",
            "A malformed declaration is not a smaller version of a correct one. "
            "Nothing here can tell whether a repaired block would hold the same "
            "authority or more of it.",
            "Report the detail to the person and let the control plane mend the "
            "ticket on the integration branch.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="PATH_NOT_REPOSITORY_RELATIVE",
        category=_A,
        next_steps=_steps(
            "offending_path names an entry that is not a repository-relative POSIX "
            "path: absolute, carrying a backslash, or walking outside the "
            "repository.",
            "Take that entry out of the change and commit the file under its "
            "repository-relative path, then call the gate again.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="REDIRECTION_ENTRY_NOT_ADMISSIBLE",
        category=_A,
        next_steps=_steps(
            "offending_path names a symlink or a submodule entry. The gate can bound "
            "the path but not whatever it points at.",
            "Replace it with a regular file and call the gate again.",
            "If the change genuinely needs a redirection entry, that is a change to "
            "the rule and it stops here. Say so and ask.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="PATH_FORBIDDEN",
        category=_N,
        next_steps=_steps(
            "Stop. The change touched a path the forbid list of the ticket names, "
            "and offending_path says which.",
            "Two different actions would each end this refusal: leaving that file "
            "alone, or moving the entry that names it. One keeps the change clear of "
            "what was prohibited; the other moves the prohibition. The gate cannot "
            "tell them apart on the next run.",
            "Report the path and the ticket to the person and let them say which was "
            "meant.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="MODIFICATION_OUTSIDE_BOUNDARY",
        category=_N,
        next_steps=_steps(
            "Stop. The change modified a path the ticket never declared, and "
            "offending_path says which.",
            "Two different actions would each end this refusal: reverting that file, "
            "or listing it in the ticket. One keeps the change inside what was "
            "authorised; the other moves the authorisation. The gate cannot tell "
            "them apart on the next run.",
            "Report the path and let the person say which was meant.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="CREATION_NOT_AUTHORIZED",
        category=_N,
        next_steps=_steps(
            "Stop. The change created a file no ticket authorised, and "
            "offending_path says which.",
            "Two different actions would each end this refusal: not creating the "
            "file, or listing it in the ticket. One keeps the change inside what was "
            "authorised; the other moves the authorisation. The gate cannot tell "
            "them apart on the next run.",
            "Report the path and let the person say which was meant.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="DELETION_NOT_AUTHORIZED",
        category=_N,
        next_steps=_steps(
            "Stop. The change deleted a file no ticket authorised, and "
            "offending_path says which.",
            "Deletion is the one threshold with no way back, which is why the ticket "
            "has to name each deleted file exactly. Listing it after the fact and "
            "never deleting it look identical to the gate on the next run.",
            "Report the path and let the person say whether that file was meant to "
            "go.",
        ),
    ),
    RefusalGuidance(
        surface=DOCUMENT_GATE_SURFACE,
        code="INTEGRATION_FAILED",
        category=_A,
        next_steps=_steps(
            "The candidate does not fast-forward the integration branch, which means "
            "the branch moved after the candidate left it.",
            "Rebase the candidate onto the integration branch without altering the "
            "change set, then call the gate again.",
            "Say that you rebased. The gate judged the change set it saw, and after "
            "a rebase it judges a different one.",
        ),
    ),
    # -- control_plane_mutation --------------------------------------------
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="REQUEST_INVALID",
        category=_A,
        next_steps=_steps(
            "The object handed to the door is not a ControlPlaneMutationRequest. "
            "This door matches its request type by identity and will not read the "
            "implementer request, which is structurally close.",
            "Build a ControlPlaneMutationRequest and call "
            "admit_control_plane_mutation again.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="PRINCIPAL_UNDECLARED",
        category=_A,
        next_steps=_steps(
            "The request carries no principal, and every line in the journal is "
            "attributed to one.",
            "Set principal to the account this process runs as. The door reads the "
            "host account itself and compares, so exactly one value is accepted and "
            "you are not the one choosing it.",
            "Then call the door again.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="PRINCIPAL_NOT_HOST",
        category=_A,
        next_steps=_steps(
            "The declared principal is not the account this process runs as. A "
            "journal line attributed to somebody who was not at this machine reads "
            "as evidence while being false.",
            "Set principal to the host account. The door takes that value from the "
            "host rather than from the request, so there is nothing to choose.",
            "If you think the host account itself is wrong, that is a question about "
            "the machine and not about the request. Say so and ask.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="CANDIDATE_NOT_CONTROL_PLANE",
        category=_N,
        next_steps=_steps(
            "Stop. The candidate ref does not belong at this door: it sits outside "
            "the control namespace, or it carries an implementer namespace as one of "
            "its components.",
            "The ref name is the only thing deciding which door judges a change, and "
            "a name is the one part of a branch that moves without its contents "
            "moving. The two doors ask different questions on purpose: this one asks "
            "for no ticket and no declared boundary.",
            "Report the ref and let the person route it. Implementer work belongs at "
            "the ticket-bounded gate, which asks what this door does not.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="REPOSITORY_UNREADABLE",
        category=_A,
        next_steps=_steps(
            "Read the detail field: it names which precondition failed.",
            "An unclean integration worktree gets committed or stashed. A wrong "
            "checked-out branch gets the integration branch checked out. A ref that "
            "names no commit gets corrected.",
            "Call the door again, and say which of those you did.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="NOTHING_TO_INTEGRATE",
        category=_A,
        next_steps=_steps(
            "The candidate holds nothing the integration branch does not already "
            "have.",
            "Check the ref you named. Usually the work already landed, or the ref "
            "points at the integration branch itself.",
            "If it already landed, say so rather than calling the door again. There "
            "is nothing here to record.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="PATH_NOT_REPOSITORY_RELATIVE",
        category=_A,
        next_steps=_steps(
            "offending_path names an entry that is not a repository-relative POSIX "
            "path: absolute, carrying a backslash, or walking outside the "
            "repository.",
            "Take that entry out of the change and commit the file under its "
            "repository-relative path, then call the door again.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="REDIRECTION_ENTRY_NOT_ADMISSIBLE",
        category=_A,
        next_steps=_steps(
            "offending_path names a symlink or a submodule entry. The door can bound "
            "the path but not whatever it points at.",
            "Replace it with a regular file and call the door again.",
            "If the change genuinely needs a redirection entry, that is a change to "
            "the rule and it stops here. Say so and ask.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="RULE_AND_SUBJECT_IN_ONE_CHANGE",
        category=_A,
        next_steps=_steps(
            "One commit changed both library code and a ticket, so nobody can accept "
            "half of it. offending_path names the library path and detail names the "
            "ticket it moved with.",
            "Split that commit into two, one per tree, then call the door again. The "
            "rule is written per commit, and two separately reviewable commits are "
            "admissible by design rather than by exception.",
            "Say that you split it and which commit became which.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="POLICY_REPIN_STALE",
        category=_N,
        next_steps=_steps(
            "Stop. A digest-pinned policy document arrived with a pin that does not "
            "describe it. The detail field names the document and what the pin "
            "currently says.",
            "That digest is not a checksum against corruption. It is the record that "
            "one specific text was read and approved, so a pin derived from the text "
            "it is meant to certify would be a record of nobody having read "
            "anything.",
            "Report the document and both values to the person, and let the approval "
            "happen before the pin does.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="JOURNAL_UNWRITABLE",
        category=_N,
        next_steps=_steps(
            "Stop. The decision line could not reach the disk, and this door exists "
            "so that nothing reaches the integration branch unrecorded.",
            "The refusal has already happened and the integration branch has not "
            "moved. Sending the record somewhere else would let the write succeed "
            "and leave the merge unfindable, and the door cannot tell that apart "
            "from a mended disk.",
            "Report the journal path to the person and let them restore it where it "
            "belongs.",
        ),
    ),
    RefusalGuidance(
        surface=CONTROL_PLANE_SURFACE,
        code="INTEGRATION_FAILED",
        category=_A,
        next_steps=_steps(
            "Either the candidate does not fast-forward the integration branch, or "
            "the branch did not land on the admitted commit. The detail field says "
            "which.",
            "For the first, rebase the candidate and call the door again.",
            "For the second, stop: something moved the integration branch between "
            "the decision and the merge, and a person should look at that before "
            "anything else runs.",
        ),
    ),
    # -- refusal_guidance itself -------------------------------------------
    RefusalGuidance(
        surface=LOOKUP_SURFACE,
        code="REQUEST_INVALID",
        category=_A,
        next_steps=_steps(
            "The surface or the code handed to guidance_for is not a string.",
            "Pass the surface id and the code value as strings and call it again. "
            "COVERED_SURFACES lists every surface id that resolves today.",
        ),
    ),
    RefusalGuidance(
        surface=LOOKUP_SURFACE,
        code="SURFACE_UNKNOWN",
        category=_A,
        next_steps=_steps(
            "No entry names that surface at all, which usually means the surface id "
            "was spelled differently rather than that the code is unclassified.",
            "Check the id against COVERED_SURFACES and call guidance_for again.",
            "If the surface really has no entries, its enum is one of the batches "
            "still waiting for a ticket. audit_classification lists them under "
            "uncovered_enums.",
        ),
    ),
    RefusalGuidance(
        surface=LOOKUP_SURFACE,
        code="CODE_UNCLASSIFIED",
        category=_O,
        next_steps=_steps(
            "Stop: the surface is covered but nobody has classified this code, so "
            "nothing here says whether the refusal underneath is yours to settle.",
            "Do not read the silence as permission. An unclassified code is the one "
            "state this module refuses to guess about, because the guess that costs "
            "least to make is the one that lets an agent carry on.",
            "Report the surface and the code to the person, together with whatever "
            "the underlying gate said, and let them decide the category. A code "
            "gets a category through a ticket, not through the run that met it.",
        ),
    ),
    RefusalGuidance(
        surface=LOOKUP_SURFACE,
        code="REGISTRY_UNREADABLE",
        category=_N,
        next_steps=_steps(
            "Stop. The classification table itself could not be read, so every "
            "answer about every code is unavailable rather than permissive.",
            "This is the failure that has an obvious wrong answer: treat the codes "
            "as resolvable and carry on. Every refusal in this repository would then "
            "be settled by whoever met it, and the run would look exactly like a run "
            "where nothing was ever refused.",
            "Report this to the person and let them find out why the table would not "
            "load before anything else runs.",
        ),
    ),
)


def _build_registry(
    entries: tuple[RefusalGuidance, ...],
) -> Mapping[tuple[str, str], RefusalGuidance]:
    """Index the table, refusing to silently keep the last of two entries.

    A duplicated key is two people disagreeing about one code. Last-wins would
    resolve that at import time, invisibly, in favour of whoever typed lower
    in the file.
    """

    registry: dict[tuple[str, str], RefusalGuidance] = {}
    for entry in entries:
        if entry.key in registry:
            raise ValueError(f"duplicate guidance entry: {entry.surface}::{entry.code}")
        registry[entry.key] = entry
    return registry


REGISTRY: Mapping[tuple[str, str], RefusalGuidance] = _build_registry(GUIDANCE)


# --------------------------------------------------------------------------
# Lookup
# --------------------------------------------------------------------------


class GuidanceLookupStatus(str, Enum):
    FOUND = "FOUND"
    UNAVAILABLE = "UNAVAILABLE"


class GuidanceLookupFailure(str, Enum):
    """Why a lookup produced nothing. Never a category.

    Each of these once had an obvious wrong answer -- return the permissive
    category and let the caller get on with it. That answer is wrong in the
    same way for all three: it converts "this module does not know" into "this
    module says go ahead".
    """

    REQUEST_INVALID = "REQUEST_INVALID"
    SURFACE_UNKNOWN = "SURFACE_UNKNOWN"
    CODE_UNCLASSIFIED = "CODE_UNCLASSIFIED"
    REGISTRY_UNREADABLE = "REGISTRY_UNREADABLE"


class GuidanceLookupResult(BaseModel):
    """One guidance, or one named failure. Never both and never neither."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: GuidanceLookupStatus
    guidance: RefusalGuidance | None = None
    failure: GuidanceLookupFailure | None = None

    @classmethod
    def found(cls, guidance: RefusalGuidance) -> Self:
        return cls(status=GuidanceLookupStatus.FOUND, guidance=guidance)

    @classmethod
    def unavailable(cls, failure: GuidanceLookupFailure) -> Self:
        return cls(status=GuidanceLookupStatus.UNAVAILABLE, failure=failure)


def guidance_for(
    surface: str,
    code: str,
    registry: Mapping[tuple[str, str], RefusalGuidance] | None = None,
) -> GuidanceLookupResult:
    """Look one refusal up. Fails closed, and closed is never a category.

    The surface is part of the key because a bare code is ambiguous across the
    forty-seven failure enums in this repository: `REQUEST_INVALID` alone names
    a code in both mutation gates, and `INTEGRATION_FAILED` names one in each
    as well. Answering from the wrong surface would be worse than answering
    nothing, because it would look like an answer.
    """

    table = REGISTRY if registry is None else registry
    if not isinstance(surface, str) or not isinstance(code, str):
        return GuidanceLookupResult.unavailable(GuidanceLookupFailure.REQUEST_INVALID)
    if not isinstance(table, Mapping):
        return GuidanceLookupResult.unavailable(
            GuidanceLookupFailure.REGISTRY_UNREADABLE
        )
    try:
        known_surfaces = {key[0] for key in table if isinstance(key, tuple) and key}
        entry = table.get((surface, code))
    except (TypeError, AttributeError):
        # A table that cannot be read is not a table that says yes.
        return GuidanceLookupResult.unavailable(
            GuidanceLookupFailure.REGISTRY_UNREADABLE
        )
    if entry is None:
        if surface not in known_surfaces:
            return GuidanceLookupResult.unavailable(
                GuidanceLookupFailure.SURFACE_UNKNOWN
            )
        return GuidanceLookupResult.unavailable(
            GuidanceLookupFailure.CODE_UNCLASSIFIED
        )
    if type(entry) is not RefusalGuidance:
        return GuidanceLookupResult.unavailable(
            GuidanceLookupFailure.REGISTRY_UNREADABLE
        )
    return GuidanceLookupResult.found(entry)


# --------------------------------------------------------------------------
# The prohibition on carrying the way around
# --------------------------------------------------------------------------

#: Terms that turn guidance into a route around the refusal. Banned outright
#: in `NEVER_AUTO_RESOLVE` guidance, including inside a prohibition: an agent
#: skimming for an action finds one either way, and "do not repin the digest"
#: has already said repin and digest in the same breath.
#:
#: These are the verbs that generalise. A phrase this list cannot catch is a
#: phrase somebody had to invent; a phrase on this list is one an agent could
#: have assembled from the guidance alone.
BYPASS_TERMS: tuple[str, ...] = (
    "bypass",
    "circumvent",
    "disable",
    "exempt",
    "force",
    "ignore",
    "no-verify",
    "opt out",
    "override",
    "recalculate",
    "recompute",
    "regenerate",
    "re-pin",
    "relax",
    "repin",
    "skip",
    "suppress",
    "temporarily",
    "turn off",
    "waive",
    "whitelist",
    "widen",
    "work around",
    "workaround",
)

#: `NEVER_AUTO_RESOLVE` has to earn its name positively too. A lexicon can only
#: refuse phrasings somebody thought of, so the category also owes a first step
#: that stops and some step that routes to a person.
_STOP_PREFIX = "stop"
_ESCALATION_TERMS: tuple[str, ...] = (
    "ask",
    "let the owner",
    "let them",
    "let the person",
    "the person",
    "a person",
    "tell the person",
    "the owner",
)

_TRANSPORT_UNSAFE = ('"', "'", "\\")


def bypass_terms_in(text: str) -> tuple[str, ...]:
    """Every banned term appearing in one string, in a stable order.

    Anchored at the start of a word and open at the end, so `forced`, `skipped`
    and `widening` all count while `enforcement` does not. Inflections are the
    normal way these verbs appear in a sentence, and a matcher that only saw
    the bare stem would miss most real phrasings.

    The looseness cuts one way on purpose. A false alarm costs somebody a
    rewording; a miss costs the category its meaning. Multi-word terms tolerate
    a hyphen or a line wrap between the words, because a literal broken across
    two source lines is not a different phrase.
    """

    folded = text.casefold()
    hits: list[str] = []
    for term in BYPASS_TERMS:
        pattern = r"\b" + r"[\s-]+".join(
            re.escape(part) for part in term.replace("-", " ").split()
        )
        if re.search(pattern, folded):
            hits.append(term)
    return tuple(hits)


def guidance_is_transport_safe(entry: RefusalGuidance) -> bool:
    """Whether every step survives a JSON literal and a PowerShell literal."""

    for step in entry.next_steps:
        if not step.isascii():
            return False
        if any(character in step for character in _TRANSPORT_UNSAFE):
            return False
    return True


def never_auto_resolve_violations(
    entries: tuple[RefusalGuidance, ...] = GUIDANCE,
) -> tuple[str, ...]:
    """Every way a `NEVER_AUTO_RESOLVE` entry fails its own contract.

    Reported rather than raised, so the audit can carry all of them at once
    instead of stopping at whichever happened to sort first.
    """

    violations: list[str] = []
    for entry in entries:
        if entry.category is not RefusalCategory.NEVER_AUTO_RESOLVE:
            continue
        name = f"{entry.surface}::{entry.code}"
        joined = " ".join(entry.next_steps)
        for term in bypass_terms_in(joined):
            violations.append(f"{name}: guidance carries the bypass term {term!r}")
        first = entry.next_steps[0].strip().casefold()
        if not first.startswith(_STOP_PREFIX):
            violations.append(f"{name}: the first step does not stop")
        if not any(term in joined.casefold() for term in _ESCALATION_TERMS):
            violations.append(f"{name}: no step routes this to a person")
    return tuple(violations)


# --------------------------------------------------------------------------
# Discovery: what codes exist, read as text
# --------------------------------------------------------------------------

_FAILURE_SUFFIX = "Failure"

#: `Write-TypedResult -Status 'BLOCKED' -Code 'X'` -- what install.ps1 can
#: actually emit. Read from the call sites rather than from the guidance table
#: inside the script, so a new refusal that forgets the table is caught by the
#: same pass that would catch a table entry for a refusal nobody raises.
_PS_CALL_SITE = re.compile(
    r"Write-TypedResult\s+-Status\s+'[A-Z_]+'\s+-Code\s+'(?P<code>[A-Z0-9_]+)'"
)

#: One entry of the guidance table inside install.ps1.
_PS_TABLE_ENTRY = re.compile(
    r"'(?P<code>[A-Z0-9_]+)'\s*=\s*@\{\s*"
    r"Category\s*=\s*'(?P<category>[A-Z_]+)'\s*"
    r"NextSteps\s*=\s*@\(\s*(?P<steps>.*?)\s*\)\s*\}",
    re.DOTALL,
)
_PS_STRING = re.compile(r"'(?P<text>[^']*)'")

#: `{"status":"BLOCKED","code":"X"}` as the cmd wrapper writes it, where the
#: quotes are backslash-escaped inside a PowerShell one-liner.
_CMD_CODE = re.compile(r'\\?"code\\?"\s*:\s*\\?"(?P<code>[A-Z0-9_]+)\\?"')


def _is_str_enum_base(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in ("str", "Enum")
    if isinstance(node, ast.Attribute):
        return node.attr == "Enum"
    return False


def _enum_members(node: ast.ClassDef) -> tuple[str, ...]:
    members: list[str] = []
    for statement in node.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        value = statement.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
            if isinstance(value.value, str):
                members.append(value.value)
    return tuple(members)


def discover_failure_enums(repository_root: Path) -> dict[str, tuple[str, ...]]:
    """Every `Failure` string enum under `library/`, by surface id.

    Parsed, never imported. Forty-seven modules that all have to import
    successfully before anybody can be told which failure codes lack guidance
    is a checker whose reliability is the product of everything it inspects.
    """

    discovered: dict[str, tuple[str, ...]] = {}
    library = repository_root / "library"
    for path in sorted(library.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        relative = path.relative_to(repository_root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.endswith(_FAILURE_SUFFIX):
                continue
            if len(node.bases) != 2 or not all(
                _is_str_enum_base(base) for base in node.bases
            ):
                continue
            discovered[f"{relative}::{node.name}"] = _enum_members(node)
    return discovered


def discover_install_script_codes(path: Path) -> tuple[str, ...] | None:
    """Codes install.ps1 can emit, or None when the script cannot be read."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return tuple(sorted({match.group("code") for match in _PS_CALL_SITE.finditer(text)}))


def discover_install_wrapper_codes(path: Path) -> tuple[str, ...] | None:
    """Codes johnny-install.cmd can emit, or None when it cannot be read."""

    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return None
    return tuple(sorted({match.group("code") for match in _CMD_CODE.finditer(text)}))


def parse_install_script_guidance(path: Path) -> dict[str, RefusalGuidance] | None:
    """The guidance table inside install.ps1, or None when it cannot be read.

    The script carries its own copy because PowerShell cannot reach into this
    module, and a copy is a drift risk. It is not left to a person to keep the
    two in step: `test_refusal_guidance` compares them.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    parsed: dict[str, RefusalGuidance] = {}
    for match in _PS_TABLE_ENTRY.finditer(text):
        steps = tuple(
            item.group("text") for item in _PS_STRING.finditer(match.group("steps"))
        )
        if not steps:
            continue
        try:
            category = RefusalCategory(match.group("category"))
        except ValueError:
            continue
        parsed[match.group("code")] = RefusalGuidance(
            surface=INSTALL_SCRIPT_SURFACE,
            code=match.group("code"),
            category=category,
            next_steps=steps,
        )
    return parsed


# --------------------------------------------------------------------------
# The audit
# --------------------------------------------------------------------------


class ClassificationAuditStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class ClassificationAudit(BaseModel):
    """What is classified, what is not, and what could not be read.

    `uncovered_enums` is a first-class field rather than a remainder somebody
    can compute. Ticket 22 covers five surfaces and leaves forty-five enums for
    later batches; those forty-five are a known state, and a known state has to
    be printable. `unaccounted_enums` is what stops the list from being emptied
    instead of shrunk.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: ClassificationAuditStatus
    unclassified_codes: tuple[str, ...] = ()
    orphan_entries: tuple[str, ...] = ()
    unreadable_surfaces: tuple[str, ...] = ()
    guidance_violations: tuple[str, ...] = ()
    unaccounted_enums: tuple[str, ...] = ()
    covered_enums: tuple[str, ...] = ()
    uncovered_enums: tuple[str, ...] = ()
    discovered_enums: tuple[str, ...] = ()


def audit_classification(
    repository_root: Path,
    entries: tuple[RefusalGuidance, ...] = GUIDANCE,
) -> ClassificationAudit:
    """Read the codes that exist and report every one no entry covers.

    Both directions are reported. A code with no entry is the failure mode this
    ticket exists for; an entry with no code is the quieter one, and it is how
    a renamed enum value would look -- guidance still present, pointing at a
    string nothing raises any more, while the code that replaced it is silently
    unclassified.
    """

    registry = _build_registry(entries)
    discovered = discover_failure_enums(repository_root)

    members: dict[str, tuple[str, ...] | None] = dict(discovered)
    members[INSTALL_SCRIPT_SURFACE] = discover_install_script_codes(
        repository_root / INSTALL_SCRIPT_SURFACE
    )
    members[INSTALL_WRAPPER_SURFACE] = discover_install_wrapper_codes(
        repository_root / INSTALL_WRAPPER_SURFACE
    )

    unclassified: list[str] = []
    orphans: list[str] = []
    unreadable: list[str] = []

    for surface in COVERED_SURFACES:
        actual = members.get(surface)
        if actual is None:
            # A covered surface that cannot be read is not a covered surface
            # with nothing in it. Treating an unreadable file as an empty one
            # would report full coverage of a script nobody could open.
            unreadable.append(surface)
            continue
        registered = {code for (known, code) in registry if known == surface}
        for code in sorted(set(actual) - registered):
            unclassified.append(f"{surface}::{code}")
        for code in sorted(registered - set(actual)):
            orphans.append(f"{surface}::{code}")

    for known_surface, code in sorted(registry):
        if known_surface not in COVERED_SURFACES:
            orphans.append(f"{known_surface}::{code} (surface is not declared covered)")

    covered_enums = tuple(
        sorted(surface for surface in COVERED_SURFACES if surface in discovered)
    )
    uncovered_enums = tuple(
        sorted(surface for surface in discovered if surface not in COVERED_SURFACES)
    )
    accounted = set(covered_enums) | set(uncovered_enums)
    unaccounted = tuple(sorted(set(discovered) ^ accounted))

    violations = never_auto_resolve_violations(entries)

    complete = not (
        unclassified or orphans or unreadable or violations or unaccounted
    )
    return ClassificationAudit(
        status=(
            ClassificationAuditStatus.COMPLETE
            if complete
            else ClassificationAuditStatus.INCOMPLETE
        ),
        unclassified_codes=tuple(unclassified),
        orphan_entries=tuple(orphans),
        unreadable_surfaces=tuple(unreadable),
        guidance_violations=violations,
        unaccounted_enums=unaccounted,
        covered_enums=covered_enums,
        uncovered_enums=uncovered_enums,
        discovered_enums=tuple(sorted(discovered)),
    )


__all__ = [
    "BYPASS_TERMS",
    "CONTROL_PLANE_SURFACE",
    "COVERED_SURFACES",
    "ClassificationAudit",
    "ClassificationAuditStatus",
    "DOCUMENT_GATE_SURFACE",
    "GUIDANCE",
    "GuidanceLookupFailure",
    "GuidanceLookupResult",
    "GuidanceLookupStatus",
    "INSTALL_SCRIPT_SURFACE",
    "INSTALL_WRAPPER_SURFACE",
    "LOOKUP_SURFACE",
    "REGISTRY",
    "RefusalCategory",
    "RefusalGuidance",
    "audit_classification",
    "bypass_terms_in",
    "discover_failure_enums",
    "discover_install_script_codes",
    "discover_install_wrapper_codes",
    "guidance_for",
    "guidance_is_transport_safe",
    "never_auto_resolve_violations",
    "parse_install_script_guidance",
]
