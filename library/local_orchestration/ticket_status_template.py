"""Turn the ticket status document into the one page the owner opens.

This module is the *page*, and nothing else. It reads no git, parses no ticket,
decides no ticket's state and writes no file. It receives the document the
pipeline produced -- plain JSON-shaped `dict`, stdlib types only -- and returns
the HTML string. Everything it knows, it was told.

Three rules shape every line below.

**Every string in the document is untrusted.** Titles come from files and
commit subjects come from `git log`; both are written by whoever last touched
the repository. A subject containing `<script>` renders as those characters,
never as markup, and that holds inside attribute values too, which is where
escaping is usually forgotten.

**Every nullable field will actually be null.** A ticket opened five minutes
ago has no commit, no release, and no stages. It must still render as a
complete row, and the absences must be *stated* rather than left as gaps --
"no commit yet" is a real answer, an empty space is an ambiguous one.

**A short list must never be short because something failed to parse.** When
`unreadable` is non-empty the page says so above the tickets, with a count, on
an inverted slab that no state row wears. An owner who glances at a short page
and sees no `NEEDS_OWNER` row will stop watching; if one of the sources that
failed held a ticket waiting on them, a page that stayed calm about it has
done more damage than no page at all. That is the defect in
`modules/tickets/workflow-governance/04-...` wearing a new costume, and family
C of the pitfall register is the rest of its wardrobe.

The layout and density come from `v2-approved-mockup.html`. The palette is the
owner's: DONE a grey ground, REJECTED red, APPROVED blue, IN_PROGRESS grass
green, and NEEDS_OWNER white with a warning triangle.

Two of the five states are now achromatic, which changes what the tests have
to measure. Hue separates red from green from blue; it says nothing at all
about white against grey, so those two are held apart by brightness instead,
and the suite checks each pair by the rule that actually applies to it. A cell
that only measured hue would stay green while NEEDS_OWNER and DONE collapsed
into the same tone.

The rest follows from having only three hues left to spend. NEEDS_OWNER spends
none: its signal is a drawn triangle, which also makes the state that most
wants the owner the one state legible with no colour vision at all. Stage chips
spend none either -- and since DONE went grey they cannot be separated from the
verdict badge by tone (both are forced into the same narrow band by their own
legibility floors, about 1.10:1 apart), so the separation is form: a filled
pill is a verdict, a chip is a stage, always. The unreadable slab inverts
rather than tints, so it can never be read as a sixth state.

Form then has to do a second job, because the same squeeze that separates a
chip from a badge also separates the two chips from each other. An unfinished
stage has to be worth looking at, and neither of the usual channels is open to
it: a hue would re-enter the collision the chips were made achromatic to
escape, and tone runs out before it arrives. The binding measurement is in dark
mode, where a chip ink must stay legible on the grey DONE ground as well as on
the card; that floor caps the gap between the two chip greys at 2.873:1 even
when the other one is pure white, against the 3.0 this design requires of two
achromatic things that must read apart. So the difference is carried by
enclosure and weight: finished stages give up their box and read as plain
words, and the unfinished chip is the only boxed thing in its row, doubled and
bold. Nothing on the page changed colour to achieve it, which is why it cannot
collide with a state colour at all.
"""

from __future__ import annotations

import html
from datetime import datetime

_PAGE_TITLE = "Johnny 工單狀態"

# Five states, because finished is not accepted. DONE is work waiting for a
# verdict; APPROVED and REJECTED are the two verdicts. Collapsing DONE into
# APPROVED would hide the queue of work waiting on a review nobody has done,
# which is the whole reason the owner split them.
_STATE = {
    "NEEDS_OWNER": ("needs-owner", "等你決定"),
    "REJECTED": ("rejected", "未通過／須修正"),
    "DONE": ("done", "完成待審"),
    "IN_PROGRESS": ("in-progress", "進行中"),
    "APPROVED": ("approved", "已通過"),
}

# The two states a human has to clear. The contract requires a reason for both,
# so the block is drawn for both -- and says so when the reason is missing,
# rather than showing a row that says work failed without saying what to fix.
_REASON_STATES = ("NEEDS_OWNER", "REJECTED")
_WHY_LABEL = {"NEEDS_OWNER": "為什麼等你：", "REJECTED": "為什麼沒通過："}
_NO_REASON = "這一列沒有附原因。照契約這不該發生，請直接開工單檔確認。"

_STAGE_SLUG = {"DONE": "done", "OPEN": "open"}

# Drawn, not typed. `⚠` and its emoji cousins render as a different glyph on
# every platform and several fonts colour them themselves, which would put a
# colour nobody chose beside a state whose colour the owner did choose. This is
# three paths and it looks the same everywhere. It carries no xmlns on purpose:
# inline SVG in HTML needs none, and the namespace URL would be the only
# http:// on a page that must never reach for the network.
_WARNING_GLYPH = (
    '<svg class="warn" width="17" height="17" viewBox="0 0 20 20" '
    'role="img" aria-label="等你決定">'
    '<path d="M10 1.7 19.2 17.6H0.8Z" fill="var(--warn-fill)" '
    'stroke="var(--warn-edge)" stroke-width="1.2" stroke-linejoin="round"/>'
    '<path d="M10 7v4.9" stroke="var(--warn-glyph)" stroke-width="2" '
    'stroke-linecap="round"/>'
    '<circle cx="10" cy="14.9" r="1.15" fill="var(--warn-glyph)"/>'
    "</svg>"
)

# Absences the page states out loud rather than leaving as a gap.
_NO_TICKETS = "沒有工單——這是讀得到的來源給出的答案，不是猜的。"
_NO_COMMIT = "尚未有 commit"
_NO_STAGES = "尚未列出階段"
_NO_RELEASE = "尚未發行"
_NO_ROLLBACK = "尚無回滾點"

_FOOT = "每一列都來自 git 與工單檔本身。讀不到的來源會就地標示，不會靜靜地變成空白。"


def _esc(value: object) -> str:
    """Everything from the document goes through here, attributes included."""

    return html.escape("" if value is None else str(value), quote=True)


def _mapping(value: object) -> dict:
    """A nullable object field is a missing field, not a crash."""

    return value if isinstance(value, dict) else {}


def _sequence(value: object) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _stamp(raw: object) -> tuple[str, str]:
    """Return (machine, human); the exact ISO text survives in the attribute.

    The offset the pipeline wrote is the offset displayed. Converting to this
    process's local zone would make the page say a different time depending on
    which machine rendered it, which is not a property a status page may have.
    """

    text = _text(raw)
    try:
        moment = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return text, text
    return text, moment.strftime("%Y-%m-%d %H:%M")


def _bar(document: dict) -> str:
    """The one strip that answers "which tree am I looking at"."""

    head = _mapping(document.get("head"))
    release = _mapping(document.get("release"))
    rollback = _mapping(document.get("rollback"))
    machine, human = _stamp(document.get("generated_at"))

    parts = [f'<div class="bar"><h1>{_esc(_PAGE_TITLE)}</h1>']
    parts.append(
        f'<span class="kv">{_esc(head.get("branch"))} '
        f'<code>{_esc(head.get("commit"))}</code></span>'
    )
    if release:
        parts.append(
            f'<span class="kv">發行 <b>{_esc(release.get("version"))}</b> '
            f'<code>{_esc(release.get("commit"))}</code></span>'
        )
    else:
        parts.append(f'<span class="kv">發行 <b>{_esc(_NO_RELEASE)}</b></span>')
    if rollback:
        parts.append(
            f'<span class="kv">回滾點 <code>{_esc(rollback.get("commit"))}</code></span>'
        )
    else:
        parts.append(f'<span class="kv">回滾點 <b>{_esc(_NO_ROLLBACK)}</b></span>')
    parts.append(
        '<span class="kv">更新於 <b>'
        f'<time datetime="{_esc(machine)}">{_esc(human)}</time></b></span>'
    )
    parts.append("</div>")
    return "".join(parts)


def _unreadable(sources: list) -> str:
    """The block that outranks the layout. Empty list, no block; never silent."""

    if not sources:
        return ""
    rows = []
    for source in sources:
        source = _mapping(source)
        rows.append(
            "<li>"
            f'<span class="src">{_esc(source.get("label"))}</span>'
            f'<code>{_esc(source.get("path"))}</code>'
            f'<span class="reason">{_esc(source.get("reason"))}</span>'
            "</li>"
        )
    return (
        f'<section class="unreadable" data-unreadable="{len(sources)}">'
        f"<h2>有 {len(sources)} 個來源讀不到，本頁不完整。</h2>"
        "<p>下面的工單清單短，可能是因為這些來源讀不到，"
        "<strong>不是因為沒事</strong>。少掉的工單裡可能就有在等你的。</p>"
        f'<ul>{"".join(rows)}</ul>'
        "</section>"
    )


def _stages(stages: list) -> str:
    chips = []
    for stage in stages:
        stage = _mapping(stage)
        ref = _text(stage.get("ref")).strip()
        label = _text(stage.get("label")).strip()
        caption = f"{ref} {label}".strip() if label else ref
        slug = _STAGE_SLUG.get(_text(stage.get("state")), "unknown")
        chips.append(f'<span class="st" data-s="{_esc(slug)}">{_esc(caption)}</span>')
    if not chips:
        chips.append(f'<span class="none">{_esc(_NO_STAGES)}</span>')
    return f'<div class="stages"><span class="lab">階段</span>{"".join(chips)}</div>'


def _where(ticket: dict) -> str:
    """Where the ticket stands. The commit cell is always drawn, even empty."""

    commit = _mapping(ticket.get("commit"))
    cells = []
    if commit:
        cells.append(
            '<div class="cell"><span class="lab">停在</span>'
            f'<span class="val">{_esc(commit.get("sha"))}</span>'
            f'<span class="sub">{_esc(commit.get("subject"))}</span></div>'
        )
    else:
        cells.append(
            '<div class="cell"><span class="lab">停在</span>'
            f'<span class="val" data-empty="yes">{_esc(_NO_COMMIT)}</span></div>'
        )
    released = ticket.get("released_in")
    if released:
        cells.append(
            '<div class="cell"><span class="lab">已發行於</span>'
            f'<span class="val">{_esc(released)}</span></div>'
        )
    path = ticket.get("ticket_path")
    if path:
        cells.append(
            '<div class="cell"><span class="lab">工單</span>'
            f'<span class="sub">{_esc(path)}</span></div>'
        )
    return f'<div class="where">{"".join(cells)}</div>'


def _why(state: str, reason: object) -> str:
    """The reason block, drawn for every state the contract requires one for.

    A REJECTED row that names no correction is the same defect as a calm page
    over an unread file: it tells the owner something failed and leaves them
    without the one thing they need to act. The pipeline refuses to emit that,
    so this states the gap loudly if one ever arrives anyway.
    """

    text = _text(reason).strip()
    if not text and state not in _REASON_STATES:
        return ""
    label = _WHY_LABEL.get(state, "為什麼：")
    if not text:
        return (
            f'<div class="why" data-missing="yes"><b>{_esc(label)}</b>'
            f"{_esc(_NO_REASON)}</div>"
        )
    return f'<div class="why"><b>{_esc(label)}</b>{_esc(text)}</div>'


def _ticket(ticket: object) -> str:
    ticket = _mapping(ticket)
    state = _text(ticket.get("state"))
    slug, caption = _STATE.get(state, ("unknown", state or "未標示狀態"))
    need = "yes" if state in _REASON_STATES else "no"
    # The waiting state is white, so its signal is a shape rather than a hue --
    # which also makes it the one state legible without colour vision at all.
    glyph = _WARNING_GLYPH if state == "NEEDS_OWNER" else ""

    identity = " · ".join(
        part
        for part in (_text(ticket.get("id")).strip(), _text(ticket.get("module")).strip())
        if part
    )

    parts = [
        f'<article class="ticket" data-state="{_esc(slug)}" data-need="{need}">'
    ]
    parts.append(
        f'<div class="who"><div class="id">{_esc(identity)}</div>'
        f'<p class="name">{glyph}{_esc(ticket.get("title"))}</p></div>'
    )
    parts.append(f'<span class="badge" data-state="{_esc(slug)}">{_esc(caption)}</span>')
    parts.append(_stages(_sequence(ticket.get("stages"))))
    parts.append(_why(state, ticket.get("reason")))
    parts.append(_where(ticket))

    handoff = ticket.get("handoff_command")
    if handoff:
        parts.append(
            '<div class="handoff"><span class="lab">要接手就把這行給對話</span>'
            f"<code>{_esc(handoff)}</code></div>"
        )
    parts.append("</article>")
    return "".join(parts)


# Ported from v2-approved-mockup.html. Every colour is a token on bare :root;
# the two dark blocks redefine those tokens and introduce none of their own, so
# light, dark, and the unstamped "system" state all resolve to a real value.
_STYLE = """
:root{
  --bg:#f2f3f5; --card:#ffffff; --strip:#e9ebef; --line:#d5d9e0;
  --ink:#12161c; --dim:#5c6672; --faint:#858e9a;
  --accent:#3a4fb8;
  --need:#ffffff; --need-bg:#f5f6f8; --need-ink:#12161c; --need-edge:#b3bac4;
  --rejected:#c0271f; --rejected-bg:#fdeceb;
  --done:#4e5763; --done-bg:#dfe4ea; --done-ink:#ffffff;
  --approved:#2563c4;
  --open:#38801f;
  --stage-done:#545d69; --stage-open:#12161c;
  --badge-ink:#ffffff;
  --warn-fill:#f5c518; --warn-glyph:#12161c; --warn-edge:#7a5f00;
  --alarm:#1b1f27; --alarm-ink:#f4f6f9; --alarm-dim:#aab4c0;
  --mono:ui-monospace,"Cascadia Mono",Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0f1216; --card:#171b21; --strip:#1d222a; --line:#2c333d;
    --ink:#e8ecf1; --dim:#98a2ad; --faint:#7a848f;
    --accent:#8b9bf0;
    --need:#e8ecf1; --need-bg:#202632; --need-ink:#12161c; --need-edge:#4a5360;
    --rejected:#f08a8a; --rejected-bg:#3a1c1c;
    --done:#545e6b; --done-bg:#2b323c; --done-ink:#e8ecf1;
    --approved:#7fb0f8;
    --open:#8fd35c;
    --stage-done:#98a2ad; --stage-open:#e8ecf1;
    --badge-ink:#12161c;
    --alarm:#e9edf3; --alarm-ink:#12161c; --alarm-dim:#545d69;
  }
}
:root[data-theme="dark"]{
  --bg:#0f1216; --card:#171b21; --strip:#1d222a; --line:#2c333d;
  --ink:#e8ecf1; --dim:#98a2ad; --faint:#7a848f;
  --accent:#8b9bf0;
  --need:#e8ecf1; --need-bg:#202632; --need-ink:#12161c; --need-edge:#4a5360;
  --rejected:#f08a8a; --rejected-bg:#3a1c1c;
  --done:#545e6b; --done-bg:#2b323c; --done-ink:#e8ecf1;
  --approved:#7fb0f8;
  --open:#8fd35c;
  --stage-done:#98a2ad; --stage-open:#e8ecf1;
  --badge-ink:#12161c;
  --alarm:#e9edf3; --alarm-ink:#12161c; --alarm-dim:#545d69;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Segoe UI","Microsoft JhengHei",system-ui,sans-serif;
  font-size:15px;line-height:1.5}
.wrap{max-width:1080px;margin:0 auto;padding:22px 18px 44px;
  display:flex;flex-direction:column;gap:16px}

.bar{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 20px;
  background:var(--strip);border:1px solid var(--line);border-radius:7px;
  padding:11px 14px}
.bar h1{font-size:16px;margin:0;letter-spacing:.02em;margin-right:auto}
.bar .kv{font-size:12.5px;color:var(--dim);font-variant-numeric:tabular-nums}
.bar .kv b{color:var(--ink);font-weight:600}
.bar code{font-family:var(--mono);font-size:12px;color:var(--accent)}

/* Inverted slab on purpose. Every state row is a light card on a light ground
   (or dark on dark); this is the only element that flips, so it cannot be
   mistaken for a sixth state, and it stays unmistakable beside a yellow DONE
   row without spending one of the five state hues. */
.unreadable{background:var(--alarm);color:var(--alarm-ink);
  border:1px solid var(--alarm);border-radius:7px;padding:13px 15px}
.unreadable h2{font-size:14px;margin:0;color:var(--alarm-ink);
  letter-spacing:.02em}
.unreadable p{margin:6px 0 0;font-size:13px;color:var(--alarm-ink)}
.unreadable strong{color:var(--alarm-ink);text-decoration:underline;
  text-underline-offset:3px}
.unreadable ul{margin:9px 0 0;padding:0;list-style:none;
  display:flex;flex-direction:column;gap:6px}
.unreadable li{display:flex;flex-wrap:wrap;gap:2px 12px;align-items:baseline;
  min-width:0}
.unreadable .src{font-size:13px;font-weight:600;color:var(--alarm-ink)}
.unreadable code{font-family:var(--mono);font-size:11.5px;
  color:var(--alarm-dim);word-break:break-all}
.unreadable .reason{font-size:12.5px;color:var(--alarm-dim)}

.ticket{background:var(--card);border:1px solid var(--line);border-radius:7px;
  padding:14px 15px;display:grid;gap:11px;
  grid-template-columns:minmax(0,1fr) auto;align-items:start}
/* Three row treatments, so the five states separate at a glance: an edge bar
   for the two a human must clear, a filled ground for finished-awaiting-verdict,
   and a plain card for the two that want nothing. */
.ticket[data-state="needs-owner"]{border-color:var(--need-edge)}
.ticket[data-state="rejected"]{border-color:var(--rejected);
  box-shadow:inset 3px 0 0 var(--rejected)}
.ticket[data-state="done"]{background:var(--done-bg);border-color:var(--done)}
/* In flight, so the edge is not closed yet. Dashed is already this design's
   word for a softer line (the .where separator uses it), it survives being
   converted to greyscale, and it is the one mark quiet enough to give a state
   that asks nothing of the owner. APPROVED deliberately gets nothing at all:
   accepted work is the quietest row on the page, and having no mark is what
   distinguishes it from the one beside it. */
.ticket[data-state="in-progress"]{border-style:dashed}

.who{grid-column:1;min-width:0}
.id{font-family:var(--mono);font-size:11.5px;color:var(--faint);
  letter-spacing:.06em}
.name{font-size:15px;font-weight:600;margin:1px 0 0;text-wrap:balance}
.warn{vertical-align:-3px;margin-right:6px;flex:none}
/* Every state badge is a filled pill and no stage chip ever is. That is the
   whole separation between the two vocabularies now that both wear grey: the
   verdict grey and the stage grey are forced into the same narrow tonal band
   by their own legibility floors (measured 1.10:1 apart), so tone cannot tell
   them apart and form has to. An unrecognised state falls through to the
   alarm treatment, because it is a defect rather than a sixth state. */
.badge{grid-column:2;grid-row:1;justify-self:end;font-size:12px;font-weight:700;
  padding:3px 10px;border-radius:4px;white-space:nowrap;
  border:1px solid transparent;
  background:var(--alarm);color:var(--alarm-ink)}
.badge[data-state="needs-owner"]{background:var(--need);color:var(--need-ink);
  border-color:var(--need-edge)}
.badge[data-state="rejected"]{background:var(--rejected);color:var(--badge-ink)}
.badge[data-state="done"]{background:var(--done);color:var(--done-ink)}
.badge[data-state="in-progress"]{background:var(--open);color:var(--badge-ink)}
.badge[data-state="approved"]{background:var(--approved);color:var(--badge-ink)}

.stages{grid-column:1 / -1;display:flex;flex-wrap:wrap;gap:5px;align-items:center}
.stages .lab{font-size:11px;color:var(--faint);margin-right:3px;
  letter-spacing:.05em}
.stages .none{font-size:11px;color:var(--faint)}
/* The base treatment is deliberately the *unclassified* one: a faint edge and
   dim ink. A stage state the page does not recognise is a defect, and the one
   direction it must never fail in is looking finished, so it keeps an edge
   that finished work has given up. */
.st{font-family:var(--mono);font-size:11px;padding:2px 7px;border-radius:3px;
  border:1px solid var(--line);color:var(--dim)}
/* Never filled -- see the badge block. A stage being finished says nothing
   about the ticket's verdict, and a chip that is not a filled pill can sit on
   a grey DONE row without reading as a second verdict badge.

   Which chip gets the box is the whole signal. Hue is spent (chips are
   achromatic so they cannot collide with a state colour) and tone is not
   merely tight but provably short: an ink light enough to stay legible on the
   dark DONE ground caps the gap between the two chip greys at 2.873:1 against
   pure white, under the 3.0 this suite requires of any two achromatic things
   that must read apart. Tone therefore cannot carry this, and no amount of
   nudging the greys will change that -- so form carries it. Finished work
   gives up its enclosure entirely and settles into plain words; the unfinished
   chip is the only boxed thing in the row, and its box is doubled. Enclosure
   is the channel the amber outline was really using: the colour only made the
   box visible, and being the *sole* box does the same work without a hue. */
.st[data-s="done"]{border-color:transparent;color:var(--stage-done)}
/* Padding pays back the extra border so the chips keep one baseline. */
.st[data-s="open"]{border-width:2px;padding:1px 6px;
  border-color:var(--stage-open);color:var(--stage-open);
  font-weight:700}

.where{grid-column:1 / -1;display:flex;flex-wrap:wrap;gap:6px 22px;
  border-top:1px dashed var(--line);padding-top:10px}
.cell{min-width:0}
.cell .lab{display:block;font-size:11px;color:var(--faint);letter-spacing:.05em}
.cell .val{font-family:var(--mono);font-size:12.5px;color:var(--ink)}
.cell .val[data-empty="yes"]{font-family:inherit;color:var(--faint)}
.cell .sub{font-size:12px;color:var(--dim)}

.handoff{grid-column:1 / -1;background:var(--strip);border:1px solid var(--line);
  border-radius:5px;padding:8px 10px;overflow-x:auto}
.handoff .lab{font-size:11px;color:var(--faint);letter-spacing:.05em}
.handoff code{display:block;margin-top:3px;font-family:var(--mono);
  font-size:12.5px;color:var(--ink);white-space:pre}

.why{grid-column:1 / -1;background:var(--strip);border:1px solid var(--line);
  border-radius:5px;padding:9px 11px;font-size:13px;color:var(--ink)}
.why b{color:var(--ink)}
[data-state="needs-owner"] .why{background:var(--need-bg);
  border-color:var(--need-edge)}
[data-state="needs-owner"] .why b{color:var(--ink)}
[data-state="rejected"] .why{background:var(--rejected-bg);
  border-color:var(--rejected)}
[data-state="rejected"] .why b{color:var(--rejected)}
.why[data-missing="yes"]{font-style:italic}

.empty{margin:0;color:var(--faint);font-size:13px}
.foot{color:var(--faint);font-size:12px;border-top:1px solid var(--line);
  padding-top:11px}
@media (max-width:640px){
  .ticket{grid-template-columns:1fr}
  .badge{grid-column:1;grid-row:auto;justify-self:start}
}
"""


def render(document: dict) -> str:
    """Render the whole page. Pure: same document in, same bytes out.

    The order of `tickets` is the pipeline's promise (NEEDS_OWNER first) and is
    reproduced exactly. Re-sorting here would put two different orderings in
    the system and make the contract untestable from either side.
    """

    document = _mapping(document)
    tickets = _sequence(document.get("tickets"))
    unreadable = _sequence(document.get("unreadable"))

    body = [_bar(document)]
    banner = _unreadable(unreadable)
    if banner:
        body.append(banner)
    body.extend(_ticket(ticket) for ticket in tickets)
    if not tickets and not unreadable:
        # Genuinely empty, and only ever said when nothing failed to parse.
        body.append(f'<p class="empty">{_esc(_NO_TICKETS)}</p>')
    body.append(f'<p class="foot">{_esc(_FOOT)}</p>')
    blocks = "\n".join(body)

    return (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(_PAGE_TITLE)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f'<div class="wrap">{blocks}</div>'
        "</body></html>"
    )
