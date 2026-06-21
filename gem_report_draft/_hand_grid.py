"""Hand-grid table rendering (key decisions, structured notes, action pills)."""

import html as _html_mod
import json as _json_mod
import re as _re_mod

from gem_report_draft._helpers import (_hand_ref, _hand_ref_short, _xref,
    _outcome_label, _run_emoji, _street_cards)
from gem_report_draft._html import (_cards_str_to_pills, _card_html,
    _cards_html, _md_inline, _cards_text_to_pills, _sort_cards_desc,
    _describe_made_hand, _KD_CLASS_PATTERNS, _KD_CLASS_VERB, Doc)
from gem_report_draft import _state
# v8.14.1 rev-3 (Blocker 4): human-readable chart labels in the REAL hand-detail
# push/call-jam verdict path (this is the lazy-hand-card render — raw chart ids
# like PUSH_10BB_UTG / CALLJAM_12BB_vsBTN were leaking here, not just sections_xiv).
from gem_chart_labels import chart_display_label as _cdl_hg


_VERDICT_HUMAN = {
    'I.7': 'Cooler', 'III.0': 'GTO-Standard', 'III.1': 'Punt',
    'III.2': 'Mistake', 'III.3': 'Cleared', 'III.4': 'Read-Dependent',
    'III.5': 'Justified', 'III.8': 'Pick', 'III.9': 'Pick',
}
_VERDICT_RE = _re_mod.compile(
    r'\b(III\.\d|I\.7)\b')

def _humanize_verdicts(text):
    """Replace internal verdict codes (III.2, I.7, …) with labels."""
    if not text:
        return text
    return _VERDICT_RE.sub(
        lambda m: _VERDICT_HUMAN.get(m.group(1), m.group(1)), text)


# v8.12.12 (Obj-H): strip the leading internal verdict code from a SINGLE
# verdict label so user-facing copy reads "Punt", not "III.1 Punt". The codes
# stay in the analyst JSON + taxonomy (this only touches display strings); use
# _humanize_verdicts() instead for free-form prose that may embed a code.
_VERDICT_CODE_PREFIX = _re_mod.compile(r'^\s*(III\.\d+|I\.7)\b[\s:.–—\-]*')


def _verdict_display_label(verdict):
    """'III.1 Punt' -> 'Punt'; 'III.4 Read-dependent' -> 'Read-dependent';
    'I.7 Cooler' -> 'Cooler'; bare 'III.2' -> 'Mistake'. Anything without a
    leading code (already-clean labels, '—', emoji statuses) is returned as-is.
    """
    if not verdict:
        return verdict
    m = _VERDICT_CODE_PREFIX.match(verdict)
    if not m:
        return verdict
    rest = verdict[m.end():].strip()
    return rest or _VERDICT_HUMAN.get(m.group(1), verdict)


def _effective_amt(nominal_amt, remaining_actions, hero_eff_cap=None):
    """Compute effective (callable) amount for an all-in bet/raise.
    The uncalled portion above the deepest live opponent stack is
    never contested — the measured size must use the effective figure.
    Returns (eff_amt, was_capped).

    v8.14.1 P0-4: `hero_eff_cap` (Hero's eff_stack_bb_at_decision) is supplied
    only for Hero's preflop jam. When every opponent FOLDS to the jam,
    remaining_actions carries no live stack, so the stack-based cap below never
    fires and a fold-through SB jam rendered Hero's full nominal stack
    (e.g. 32.5BB) instead of the effective depth vs the live blind (18.0BB).
    """
    # v8.12.8 QA-GPT P0.1: when a subsequent action IS the all-in call,
    # its amount is the exact contested figure — the stack-based cap below
    # uses the responder's stack at hand start and misses chips already
    # committed (66662469: turn jam 92.7 was called all-in for 62.6, but
    # hero's 114BB starting stack never triggered the cap).
    for _b in remaining_actions:
        if (_b.get('action') == 'calls'
                and (_b.get('all_in') or _b.get('is_all_in'))):
            _amt_b = _b.get('amount_bb', 0) or 0
            if 0 < _amt_b < nominal_amt:
                return _amt_b, True
            break
    _live_behind = []
    for _b in remaining_actions:
        if _b.get('action', '') == 'folds':
            continue
        _live_behind.append(_b.get('stack_bb', 0) or 0)
    if _live_behind:
        _cap = max(_live_behind)
        if _cap > 0 and _cap < nominal_amt:
            return min(nominal_amt, _cap), True
    # Fold-through Hero jam: no live opponent remains in remaining_actions, so
    # fall back to Hero's decision-effective depth (the live blind it was up
    # against) rather than reporting the uncapped nominal stack.
    if hero_eff_cap and 0 < hero_eff_cap < nominal_amt:
        return hero_eff_cap, True
    return nominal_amt, False

def _key_decision_action_class(key_dec):
    """Map a `key_decision` string to the Hero action class it names.

    `key_decision` always leads with Hero's verb — "Iso-raising...",
    "Turn jam...", "River call-all-in...", "Fold to the BB jam...". We take
    the action keyword that appears EARLIEST in the text, so villain context
    later in the sentence ("...vs BB check-raise jam") never overrides it.
    Returns one of 'fold'/'check'/'call'/'bet'/'raise', or None.
    """
    if not key_dec:
        return None
    import re as _re
    t = key_dec.lower()
    best_cls, best_pos = None, 10 ** 9
    for cls, pat in _KD_CLASS_PATTERNS.items():
        m = _re.search(pat, t)
        if m and m.start() < best_pos:
            best_pos, best_cls = m.start(), cls
    return best_cls


def _pick_key_action_idx(verbs, key_dec):
    """Choose which Hero action (0-based index within the street) the single-
    narrative analyst note binds to.

    B145 (v7.70, Ron 2026-05-23): the old rule bound the note to the LAST
    Hero action on the key street (B95). When that last action is a correct
    fold/check — e.g. an iso-raise that punts, then a correct fold to the
    re-jam — the (N) pill landed on the FOLD, flagging the wrong decision.
    Fix: bind to the action the analyst's `key_decision` names. Fallbacks
    keep the result safe when `key_decision` is absent or unmatched:
      1. action class named first in key_decision
      2. last committing action (not fold/check)
      3. last action overall (covers a fold that IS the only/keyed action)
    """
    n = len(verbs)
    if n == 0:
        return None
    cls = _key_decision_action_class(key_dec)
    if cls:
        want = _KD_CLASS_VERB.get(cls)
        matching = [i for i, v in enumerate(verbs) if v == want]
        if matching:
            return matching[-1]
    committing = [i for i, v in enumerate(verbs)
                  if v not in ('folds', 'checks')]
    if committing:
        return committing[-1]
    return n - 1


def _argument_is_structured(argument):
    """True when the analyst wrote the argument in the Output-Formatting
    structure (Analyst_Writing_Checklist §8): it leads with '**TL;DR:**'.

    Guard (B-HG1): note entries are occasionally non-string (e.g. an int
    note-number leaks into the notes list); coerce defensively so detection
    never raises.

    Upstream root cause: _split_argument_into_notes (sections_xiv.py) returns
    {int: str} but callers sometimes unpack keys into the notes list instead
    of values, producing int entries. The renderer guard is the fix-of-record
    because the upstream dict-key format is load-bearing for note numbering.
    Schema note (B-HG2): gem_report_lint should eventually validate that
    every note entry in the appendix card data is a string, catching this
    class of type-leak at build time.
    """
    if not isinstance(argument, str):
        return False
    return bool(argument and argument.lstrip().startswith('**TL;DR:**'))


def _parse_structured_argument(text):
    """Parse a structured analyst argument into renderable blocks.

    Returns a list of (kind, payload):
      ('tldr', str)            — the TL;DR line(s)
      ('section', str)         — a '### ' sub-header
      ('bullets', [str, ...])  — a run of '* '/'- ' bullets
      ('para', str)            — any other non-empty line
    A regex auto-structurer cannot produce this — the decomposition is an
    authoring task — so the analyst writes it and this just splits it back
    out for faithful rendering (B146, v7.71).
    """
    blocks = []
    buf = []

    def _flush():
        if buf:
            blocks.append(('bullets', buf[:]))
            buf.clear()

    for raw in (text or '').strip().split('\n'):
        ln = raw.strip()
        if not ln or ln == '---':
            _flush()
            continue
        if ln.startswith('**TL;DR:**'):
            _flush()
            blocks.append(('tldr', ln[len('**TL;DR:**'):].strip()))
        elif ln.startswith('### '):
            _flush()
            blocks.append(('section', ln[4:].strip()))
        elif ln.startswith('* ') or ln.startswith('- '):
            buf.append(ln[2:].strip())
        else:
            _flush()
            blocks.append(('para', ln))
    _flush()
    return blocks


def _note_inline(text):
    """Inline rendering for a structured-note fragment: raw card tokens →
    colored suit pills, then full inline markdown via _md_inline (bold,
    links, escaping, span-preservation).

    B147 (v7.71, Ron 2026-05-23): this was named `_md_inline` — which
    SHADOWED the module's real inline-markdown renderer (defined earlier),
    so every `*italic*` / `[link](#anchor)` in the whole report stopped
    rendering and leaked as raw text. Renamed; card tokens are pilled first
    so _md_inline's B79 stash preserves the resulting spans.
    """
    return _md_inline(_cards_text_to_pills(_humanize_verdicts(text or '')))


def _emit_structured_note(doc, note, note_num, is_bound, analyst_verdict=''):
    """Render a structured analyst argument into the yellow notes block:
    TL;DR row (carries the numbered pill), uppercase section sub-headers,
    and <ul> bullet runs — instead of one prose blob.

    v8.13.1 P1: if the FINAL analyst verdict is a confirmed mistake/punt but the
    TL;DR still asserts a 'standard / inside push range' read (stale auto copy),
    the contradiction is reframed in-line — a Mistake verdict must never render
    a 'standard' TL;DR."""
    pill_done = False
    for kind, payload in _parse_structured_argument(note):
        pill = ''
        if not pill_done and is_bound and kind in ('tldr', 'section', 'para'):
            pill = f"<span class='note-num'>{note_num}</span> "
            pill_done = True
        if kind == 'tldr':
            _tldr_txt = payload
            if tldr_contradicts_verdict(_tldr_txt, analyst_verdict):
                _tldr_txt = (_tldr_txt + '  *(auto pre-review framing — superseded '
                             'by the analyst verdict below: graded a mistake, not '
                             'standard).*')
            doc.w(f"<p class='note-tldr'>{pill}<strong>TL;DR:</strong> "
                  f"{_note_inline(_tldr_txt)}</p>")
        elif kind == 'section':
            doc.w(f"<p class='note-section'>{pill}{_note_inline(payload)}</p>")
        elif kind == 'bullets':
            # Emit the whole <ul> on ONE line: the HTML renderer passes a
            # line through raw when it starts with '<ul', but would wrap a
            # bare '<li>' line in <p>. One line keeps it valid markup.
            items = ''.join(f"<li>{_note_inline(b)}</li>" for b in payload)
            doc.w(f"<ul class='note-bullets'>{items}</ul>")
        else:  # para
            doc.w(f"<p class='note-cont'>{pill}{_note_inline(payload)}</p>")


def _split_argument_into_notes(argument, key_dec, one_two, matchup, spot,
                                hero_actions_by_street, analyst_street=None,
                                hero_action_verbs_by_street=None):
    """Break analyst commentary into numbered notes aligned to hero actions.

    Returns: (notes, action_to_note_num, action_to_tone) where:
      - notes: list of strings (the note texts in order)
      - action_to_note_num: dict mapping (street, action_index) → note_num
      - action_to_tone: dict mapping (street, action_index) → 'positive' | 'critical' | None
        when tone is 'positive' the renderer uses a 👎 red marker
        (per Ron's spec: "good move + here's why" gets thumbs-down red),
        when 'critical' (default) uses the numbered (N) pill,
        when None and the action has no note: 👍 thumbs-up.

    B57 (v7.55, Ron 2026-05-18): tone heuristic — note is 'positive' when it
    contains explicit confirming phrases like "good call", "well played",
    "100% GTO call", "correct fold", "standard", "mandatory", "GTO-standard",
    "defensible", "+EV exploit", "correctly", "should", etc. AND has no
    contrary negative phrases (punt, mistake, leak, overplay, error, bad).

    B108 (v7.59, Ron 2026-05-19): when the analyst sets cmt['street'] explicitly
    (e.g. "preflop" for a hand where preflop is the leak but Hero made postflop
    actions), pass that in as analyst_street to OVERRIDE the heuristic that
    picks "last hero non-fold action street". Without this, A3s-flat-vs-squeeze
    type punts had the (1) marker land on the (correct) river fold instead of
    the (actual leak) preflop call.
    """
    import re as _re
    notes = []
    action_to_note_num = {}
    action_to_tone = {}
    single_narrative_note_num = None  # B142 (v7.69): set if B83 override fires

    # B146 (v7.71, Ron 2026-05-23): structured-argument fast path. When the
    # analyst writes the argument in the Output-Formatting structure (leads
    # with "**TL;DR:**", then ### sections + bullets per Analyst_Writing_
    # Checklist §8) it is ONE coherent block. Do NOT sentence-split / street-
    # bucket it — that flattens the bullet/header line structure into a blob.
    # Emit it as a single raw note bound to the key-decision action; the
    # notes renderer detects the **TL;DR:** prefix and renders it faithfully.
    # key_decision/one_two_back/matchup are NOT appended — the structured
    # argument is self-contained (those fields still feed III.4/bust-audit).
    if _argument_is_structured(argument):
        key_street = None
        if analyst_street and hero_actions_by_street.get(analyst_street):
            key_street = analyst_street
        else:
            for _st in ('river', 'turn', 'flop', 'preflop'):
                if hero_actions_by_street.get(_st):
                    key_street = _st
                    break
        note_txt = argument.strip()
        if key_street:
            _verbs = (hero_action_verbs_by_street or {}).get(key_street, [])
            _acts = hero_actions_by_street.get(key_street, [])
            _tidx = _pick_key_action_idx(_verbs, key_dec)
            _target = (_acts[_tidx] if (_tidx is not None and _acts)
                       else (_acts[-1] if _acts else 0))
            return ([note_txt], {(key_street, _target): 1},
                    {(key_street, _target): 'critical'}, 1)
        return [note_txt], {}, {}, 1

    # B57: Tone detector — applies per-note text
    _positive_kw = _re.compile(
        r'\b('
        r'good\s+(call|fold|bet|raise|move|play|spot)|'
        r'well\s+played|correctly|correct\s+fold|correct\s+call|'
        r'100%\s+gto\s+call|gto-?standard|gto\s+standard|'
        r'standard\s+(play|line|stack-off|call|fold|3-?bet|raise)|'
        r'mandatory|forced\s+by|pot-?committed|defensible|'
        r'\+ev\s+exploit|capped-range\s+exploit|justified|'
        r'in[- ]range|range[- ]ok|firmly\s+in.*range|'
        r'textbook|clean\s+(stack-off|call|fold)|cooler|variance'
        r')\b', _re.IGNORECASE)
    _negative_kw = _re.compile(
        r'\b('
        r'punt|leak|mistake|error|overplay|spew|bad\s+(call|fold|bet|move)|'
        r'should\s+(fold|have folded|have called|have raised|have jammed)|'
        r'too\s+(loose|tight|aggressive)|misread|'
        r'better\s+line|sub-?optimal|-ev\b'
        r')\b', _re.IGNORECASE)

    def _classify_tone(text):
        if _negative_kw.search(text):
            return 'critical'
        if _positive_kw.search(text):
            return 'positive'
        return 'critical'  # default — neutral analyst commentary is informative, not confirming

    # B87 (v7.58, Ron 2026-05-18): the `spot` field is meta-info (tournament
    # name, hand summary, level) ALREADY shown in the appendix heading + meta
    # line above the grid. Including it in note text duplicated tournament
    # info inside (1) and made the analyst-comment unread-friendly. Drop it.
    # Sentence-split the full argument prose
    full_text_parts = []
    if argument: full_text_parts.append(argument)
    if key_dec: full_text_parts.append(key_dec)
    if one_two: full_text_parts.append(one_two)
    full_text = ' '.join(full_text_parts).strip()
    if not full_text and not matchup:
        return [], {}, {}, None

    sentences = _re.split(r'(?<=[.!?])\s+(?=[A-Z(*\[])', full_text)
    sentences = [s.strip() for s in sentences if s.strip()]

    # Bucket sentences by which street they reference
    street_kw = {
        'preflop': r'\b(pre-?\s*flop|preflop|pf\b|pre\s+|3-?bet\s+pre|squeeze\s+pre|jam.*pre|stack-off\s+pre|cold-?call)',
        'flop':    r'\b(flop\b|c-?bet\s+flop|cbet\s+flop|check.*flop|raise.*flop|overbet\s+flop|jam\s+flop|x/?r\s+flop|XR\s+flop|check-?raise\s+flop)',
        'turn':    r'\bturn\b',
        'river':   r'\briver\b',
    }
    by_street = {'preflop': [], 'flop': [], 'turn': [], 'river': []}
    general = []
    for sn in sentences:
        sn_low = sn.lower()
        matched = None
        # Prefer earliest street mention in sentence
        first_pos = 999
        for street, kw in street_kw.items():
            m = _re.search(kw, sn_low)
            if m and m.start() < first_pos:
                first_pos = m.start()
                matched = street
        if matched:
            by_street[matched].append(sn)
        else:
            general.append(sn)

    # B83 (v7.57) + retune (v7.58, Ron 2026-05-18): single-narrative
    # override. The original criterion required ≥2 streets in by_street
    # to fire, but most analyst arguments produce ONE street keyword hit
    # ("Flop 7s2s6c rainbow.") and everything else falls into `general`.
    # That left the (1) marker attached to a useless board-recap sentence.
    # New rule: fire whenever argument is meaningful narrative (≥250 chars
    # AND general has 3+ sentences). Dumps everything to key-decision
    # street, attached to the LAST hero action there (B95).
    streets_with_content = [s for s in by_street if by_street[s]]
    is_long_narrative = (
        argument
        and len(argument) > 250
        and (len(streets_with_content) >= 2 or len(general) >= 3)
    )
    if is_long_narrative:
        # B108 (v7.59, Ron 2026-05-19): respect explicit analyst-set street
        # before falling back to last-hero-non-fold heuristic.
        key_street = None
        if analyst_street and hero_actions_by_street.get(analyst_street):
            key_street = analyst_street
        else:
            for street in ('river', 'turn', 'flop', 'preflop'):
                if hero_actions_by_street.get(street):
                    key_street = street
                    break
        if key_street:
            all_sentences = sentences
            by_street = {'preflop': [], 'flop': [], 'turn': [], 'river': []}
            by_street[key_street] = all_sentences
            general = []

    # Build notes per street and attach to hero action on that street.
    # B95 (v7.58, Ron 2026-05-18): when B83 single-narrative override is in
    # effect, attach the narrative to the LAST hero action on the key street
    # (the actual decision driver — e.g., for a flop jam that punted, attach
    # to the JAM action, not the bet that preceded it). When NOT in override
    # (multiple-streets case), the per-street loop still attaches to the
    # first hero action on each street as before.
    # B142/B143 (v7.69, Ron 2026-05-22): under the single-narrative override
    # the whole argument is one note bound to ONE action on the key street.
    # single_narrative_note_num (set below) flags that the override fired so
    # the renderer can leave non-key-street hero actions UNMARKED — not a
    # bare 👍 (false clear) and not a (N) pill (false flag, Ron 5/22).
    for street in ('preflop', 'flop', 'turn', 'river'):
        stmts = by_street[street]
        if not stmts: continue
        note_text = ' '.join(stmts)
        hero_acts = hero_actions_by_street.get(street, [])
        if hero_acts:
            note_num = len(notes) + 1
            # Single-narrative override → key decision. B145 (v7.70): pick the
            # action the analyst's key_decision names (was: last hero action,
            # which mis-bound the (N) pill to a correct fold after a punting
            # raise). Non-override path keeps first-hero-action attachment.
            if is_long_narrative:
                _verbs = (hero_action_verbs_by_street or {}).get(street, [])
                _tidx = _pick_key_action_idx(_verbs, key_dec)
                target_action = (hero_acts[_tidx] if _tidx is not None
                                 else hero_acts[-1])
            else:
                target_action = hero_acts[0]
            key = (street, target_action)
            action_to_note_num[key] = note_num
            action_to_tone[key] = _classify_tone(note_text)
            notes.append(note_text)
            if is_long_narrative:
                single_narrative_note_num = note_num

    # General/context notes: attach to LAST hero action
    if general:
        # B108 (v7.59, Ron 2026-05-19): if analyst set street, prefer it for
        # general-bucket attachment too — keeps narrative + math together.
        last_street_acts = None
        last_street = None
        if analyst_street and hero_actions_by_street.get(analyst_street):
            last_street_acts = hero_actions_by_street[analyst_street]
            last_street = analyst_street
        else:
            for street in ('river', 'turn', 'flop', 'preflop'):
                ha = hero_actions_by_street.get(street, [])
                if ha:
                    last_street_acts = ha
                    last_street = street
                    break
        if last_street_acts is not None:
            note_text = ' '.join(general)
            existing_key = (last_street, last_street_acts[-1])
            if existing_key in action_to_note_num:
                idx = action_to_note_num[existing_key] - 1
                notes[idx] = notes[idx] + ' ' + note_text
                # Re-classify combined note
                action_to_tone[existing_key] = _classify_tone(notes[idx])
            else:
                note_num = len(notes) + 1
                action_to_note_num[existing_key] = note_num
                action_to_tone[existing_key] = _classify_tone(note_text)
                notes.append(note_text)
        else:
            notes.append(' '.join(general))

    # Matchup math always goes as the final "Math:" note (no inline marker)
    if matchup:
        notes.append('**Math:** ' + matchup.strip())

    return notes, action_to_note_num, action_to_tone, single_narrative_note_num


# ── v8.13.1 P1: verdict-contradiction reconciliation ──────────────────────
# A final analyst verdict must never coexist with a contradictory auto
# push/range widget (2026-06-13: KJo UTG+1 rendered "TL;DR standard / inside
# push range" AND "❌ Wrong push" on the same hand). These pure helpers decide
# how the auto check is presented given the analyst's final verdict.
_ANALYST_CLEARED_PREFIXES = ('III.0', 'III.3', 'III.4', 'III.5', 'I.7')
_ANALYST_MISTAKE_PREFIXES = ('III.1', 'III.2')


def reconcile_push_widget(in_range, analyst_verdict):
    """Decide how to present the auto push/range check given the FINAL analyst
    verdict. Returns (mode, note):
      'pre_review' — no analyst verdict yet; the auto check is a heuristic, not
                     a final verdict, so it is labelled 'auto pre-review'.
      'overridden' — analyst cleared/justified a hand the auto check flagged out
                     of range; show the override, not a bare 'Wrong push'.
      'agree'      — analyst and auto check agree (cleared+in, or a mistake).
    """
    av = (analyst_verdict or '').strip()
    if not av:
        return ('pre_review', 'auto pre-review')
    if av.startswith(_ANALYST_CLEARED_PREFIXES):
        return ('overridden', 'analyst cleared') if not in_range else ('agree', '')
    if av.startswith(_ANALYST_MISTAKE_PREFIXES):
        return ('agree', '')
    return ('pre_review', 'auto pre-review')


def tldr_contradicts_verdict(argument, analyst_verdict):
    """True iff a TL;DR asserts a 'standard / inside push range / justified'
    read while the FINAL analyst verdict is a confirmed mistake/punt — the
    contradiction that must be suppressed."""
    if not (analyst_verdict or '').strip().startswith(_ANALYST_MISTAKE_PREFIXES):
        return False
    low = (argument or '').lower()
    return ('inside the push range' in low or 'inside push range' in low
            or 'standard, result is variance' in low or 'standard push' in low
            or ' justified' in low)


def _render_hand_grid_table(doc, h, app_details, board, notes, action_to_note_num,
                              pot_by_street, used_streets, rd=None,
                              action_to_tone=None, single_narrative_note_num=None,
                              villain_badges=None):
    """Render the visual hand-grid table. used_streets = ordered list of streets
    that actually had cards/actions.

    B52-B56 (v7.55, Ron 2026-05-18):
    - Cards rendered as colored suit pills (♠/♥/♦/♣ with bg)
    - Bet/raise sizes show pot % in brackets: "Bet 8.0BB (50%)"
    - Hero actions WITHOUT a note get a 🟡 thumbs-up emoji inline
    - Result row at bottom of grid: total Hero BB won/lost + SD villain hand
    """
    all_actions = app_details.get('actions') or {}

    # ── REV11 E1: canonical action-semantic per Hero ledger action ──
    # The action grid renders Hero rows from the SAME classifier as the reviewed-decision
    # capsule (gem_decision_snapshot), so a first-in SB complete reads "Complete 0.5BB" (NOT
    # "Call 0.5BB / need 18%"), an underblind shove reads "All-in … short of the BB", and a
    # re-jam never reads "Call". Keyed by (street, Hero-occurrence-on-street).
    _canon_by_street_occ = {}
    try:
        from gem_decision_snapshot import (reviewed_action_display as _ds_rad,
                                           build_decision_snapshot as _ds_bds,
                                           build_action_sizing_contract as _ds_asc)
        _led_cg = h.get('action_ledger') or []
        _hero_cg = h.get('hero', 'Hero')
        _occ_cg = {}
        for _li, _la in enumerate(_led_cg):
            if _la.get('player') == _hero_cg and _la.get('action') != 'posts':
                _st = _la.get('street', 'preflop')
                _o = _occ_cg.get(_st, 0)
                _occ_cg[_st] = _o + 1
                try:
                    _snap_cg = _ds_bds(h, _li)
                    _disp_cg = _ds_rad(h, _li, _snap_cg)
                    # REV14 B/C/D3: the grid consumes the SAME canonical ActionSizingContract +
                    # DecisionPriceContract the reviewed capsule uses — so a Hero call shows the
                    # canonical callable price + required equity (NOT a raw amount_bb / running-pot
                    # recompute), and an all-in's "adds/all-in to" uses the live (ante-excluded) sizes.
                    _sc_cg = _ds_asc(h, _li)
                    _canon_by_street_occ[(_st, _o)] = {
                        'display_text': _disp_cg.get('display_text'),
                        'display_verb': _disp_cg.get('display_verb'),
                        'hero_action_kind': _snap_cg.get('hero_action_kind'),
                        'actual_node_type': _snap_cg.get('actual_node_type'),
                        'price_applicable': bool(_snap_cg.get('price_applicable')),
                        'facing': _snap_cg.get('decision_facing_state'),
                        # REV14: live (ante-excluded) sizing + the canonical price/equity.
                        'amount_added_bb': _sc_cg.get('amount_added_bb'),
                        'total_to_bb': _sc_cg.get('live_betting_total_to_bb'),
                        'continue_component_bb': _sc_cg.get('continue_component_bb'),
                        'callable_amount_bb': _snap_cg.get('callable_amount_bb'),
                        'required_equity_pct': _snap_cg.get('required_equity_pct'),
                        'became_all_in': bool(_snap_cg.get('became_all_in_on_this_action')),
                    }
                except Exception:
                    pass
    except Exception:
        pass

    # REV16 §6/§8.5: the ONE full-history per-action canonical replay, read by EVERY action row
    # (Hero AND villain) for its displayed physical size + live level — never raw added_bb. A row
    # whose ledger index cannot be resolved counts as a raw-sizing fallback (gated to 0 on real data).
    _grid_fallback = [0]

    def _canon_replay(_lidx):
        if _lidx is None:
            return None
        try:
            from gem_decision_snapshot import canonical_action_replay as _car
            return _car(h, _lidx)
        except Exception:
            return None

    def _jam_headline(_phys, _lvl):
        """REV16 §8.5: the ONE all-in headline for EVERY player — the chips committed this action
        (`adds`) and the live level reached (`all-in to`), both canonical. A first-in jam (no prior
        live chips this street) collapses to a single 'all-in {level}'."""
        if _lvl is not None and abs(_lvl - _phys) > 0.05:
            return f'⚡ JAM adds {_phys:.1f}BB, all-in to {_lvl:.1f}BB'
        return f'⚡ JAM all-in {_phys:.1f}BB'

    # ── Seat-stack fallback lookup (v8.4.2) ──
    _seat_stacks = {}
    for _pos, _stk_val in (h.get('seat_stacks_bb_all', {}) or {}).items():
        if isinstance(_stk_val, (int, float)) and _stk_val > 0:
            _seat_stacks[_pos] = _stk_val

    def _grid_stack(action_entry):
        """Return starting stack for a grid action, with seat_stacks fallback."""
        stk = action_entry.get('stack_bb', 0) or 0
        if stk <= 0:
            stk = _seat_stacks.get(action_entry.get('position', ''), 0)
        return stk

    # ── Villain identity for action grid (v8.4.2 / v8.7.0) ──
    _vi = h.get('villain_identity', {}) or {}
    _pv_name = (h.get('primary_villain', {}) or {}).get('name', '')
    _villain_badges = h.get('villain_badges', []) or []
    _vi_alias = (_vi.get('alias', '') or '').strip()
    _vi_vk = (_vi.get('villain_key', '') or h.get('primary_villain_key', '') or '')

    def _ps(pos, stk, player_name=''):
        """Format 'POS(NNnBB)' with optional villain-mini tag for primary villain."""
        _v_tag = ''
        if player_name and _pv_name and player_name == _pv_name and _vi_alias:
            _safe_alias = _html_mod.escape(_vi_alias)
            _safe_vk = _html_mod.escape(_vi_vk, quote=True)
            _onclick = ''
            # v8.12.2 Phase-C: click handled by the delegated listener on
            # .villain-mini[data-vk] — no per-span onclick attr (~65KB).
            _vk_attr = f' data-vk="{_safe_vk}"' if _vi_vk else ''
            _v_tag = (f'<span class="villain-mini"{_vk_attr}>'
                      f'{_safe_alias}</span> ')
        return f'{pos} {_v_tag}({stk:.0f}BB)' if stk > 0 else f'{pos} {_v_tag}'.strip()

    def _street_cards_html(street):
        if street == 'preflop': return ''
        cards = _street_cards(board, street)
        if not cards: return ''
        # Sort flop cards descending (Ac5s4s not 5s4sAc); keep turn/river at end
        if len(cards) >= 3:
            cards = _sort_cards_desc(cards[:3]) + cards[3:]
        # New card on turn/river highlighted with yellow border treatment
        # (the card pill itself already has color; we draw attention with a small ring)
        if street == 'turn' and len(cards) >= 4:
            base = ' '.join(_card_html(c) for c in cards[:3])
            new = f'<span class="pb-ring">{_card_html(cards[3])}</span>'
            return base + ' ' + new
        elif street == 'river' and len(cards) >= 5:
            base = ' '.join(_card_html(c) for c in cards[:4])
            new = f'<span class="pb-ring">{_card_html(cards[4])}</span>'
            return base + ' ' + new
        else:
            return ' '.join(_card_html(c) for c in cards)

    # ── Draw profiles for header (BUG-3 wiring) ──
    hero_cards_raw = h.get('cards') or []
    _draw_profiles = {}
    if len(hero_cards_raw) == 2 and board and len(board) >= 3:
        try:
            from gem_made_hands import draw_profile as _dp_fn
            for _dp_st, _dp_n in [('flop', 3), ('turn', 4), ('river', 5)]:
                if len(board) >= _dp_n:
                    _draw_profiles[_dp_st] = _dp_fn(hero_cards_raw, board[:_dp_n])
        except Exception:
            pass

    # Header row
    headers = []
    for street in used_streets:
        label = street.upper() if street != 'preflop' else 'PRE-FLOP'
        pot_bb = pot_by_street.get(street, 0)
        pot_str = f"{pot_bb:.1f} BB pot" if pot_bb > 0 else ""
        cards_html = _street_cards_html(street)
        cell_html = f"{label}"
        # IP/OOP badge on postflop streets
        if street != 'preflop' and h.get('hero_ip') is not None:
            _ip_lbl = 'IP' if h['hero_ip'] else 'OOP'
            _ip_clr = '#22c55e' if h['hero_ip'] else '#f59e0b'
            # R2: hottest inline style in the report (~816x) -> class
            _ip_cls = 'pb-ip-y' if h['hero_ip'] else 'pb-ip-n'
            cell_html += f" <span class='pb-ip {_ip_cls}'>{_ip_lbl}</span>"
        if cards_html:
            cell_html += f"<br><span class='cards'>{cards_html}</span>"
        if pot_str:
            cell_html += f"<span class='pot'>{pot_str}</span>"
        # Board texture label on flop header. v8.17.1 P0B: a stringified
        # None/null/undefined must NEVER render as a visible texture label — the
        # truthy string "None" was leaking into ~231 continued-street headers.
        _bt_raw = h.get('board_texture')
        if (street == 'flop' and _bt_raw
                and str(_bt_raw).strip().lower() not in ('none', 'null', 'undefined')):
            _bt = _html_mod.escape(
                str(_bt_raw).replace('_', ' ')
                .replace('ahigh', 'A-high').replace('khigh', 'K-high')
                .title())
            cell_html += f"<br><span class='board-tex pb-lbl'>{_bt}</span>"
        # Draw profile summary on each postflop street
        _dp = _draw_profiles.get(street)
        if _dp and _dp.get('summary'):
            _dp_text = _html_mod.escape(_dp['summary'])
            cell_html += f"<br><span class='draw-profile pb-mut-i'>{_dp_text}</span>"
        headers.append(cell_html)

    # Helpers for B53 — compute pot % at the moment of the action
    def _pot_pct_for_bet(street, amount_bb, pot_before_bb):
        """Compute bet/raise sizing as % of pot (or xPF for preflop raises).

        Preflop raises: report as Nx (multiple of BB). Postflop bets:
        report as % of pot. Raises postflop: report as % of pot also,
        though it's the amount-to-call ratio that matters for context.
        """
        if street == 'preflop':
            # preflop bets are usually in BB multiples of the previous bet
            # report as plain BB count (e.g. "2.2x"). For 3-bet+ chains we'd
            # need a chain-aware computation; for now keep it informational.
            return None  # skip preflop pot %
        if pot_before_bb and pot_before_bb > 0 and amount_bb > 0:
            pct = amount_bb / pot_before_bb * 100
            # v8.12.8 (QA G): stash every rendered sizing so the analyst
            # pct-claim lint (W-PCT) validates against the SAME numbers the
            # reader sees — never a re-derived figure that can drift.
            try:
                h.setdefault('_grid_bet_pcts', {}).setdefault(
                    street, []).append(int(round(pct)))
            except Exception:
                pass
            return f"{pct:.0f}%"
        return None

    # Build column cells
    col_cells = []
    # v8.9.7 B140: precompute Hero's last raw action index per street so a
    # (street, -1) sentinel villain-badge can be pinned to Hero's decision action.
    _hero_last_idx_by_street = {}
    for _st in used_streets:
        _acts = all_actions.get(_st) or []
        for _ai, _a in enumerate(_acts):
            if _a.get('is_hero'):
                _hero_last_idx_by_street[_st] = _ai
    _street_sentinel_placed = {}
    # v8.17.1 P3b: each VILLAIN's last non-fold action index per (street, POS) so
    # a villain-side evid sentinel can pin to THAT villain's last action row by
    # position (the atom's ledger action_index drifts from grid per-street index).
    _villain_last_idx_by_street_pos = {}
    for _st in used_streets:
        for _ai, _a in enumerate(all_actions.get(_st) or []):
            if _a.get('is_hero') or _a.get('action') in ('posts', 'folds', 'fold'):
                continue
            _vp = (_a.get('position') or '').upper()
            if _vp:
                _villain_last_idx_by_street_pos[(_st, _vp)] = _ai
    _villain_sentinel_placed = {}

    # B143: precompute trigger markers for fold-type mistakes.
    # When Hero folds with a critical note, mark the last aggressive villain
    # action as the trigger so it gets a red ! pill.
    _trigger_markers = {}
    for _ts in used_streets:
        _tacts = all_actions.get(_ts) or []
        _hero_idx = 0
        _last_aggro_raw = None
        for _ti, _ta in enumerate(_tacts):
            if _ta.get('action') == 'posts':
                continue
            if _ta.get('is_hero'):
                _tkey = (_ts, _hero_idx)
                _has_note = _tkey in action_to_note_num
                _is_positive = (action_to_tone or {}).get(_tkey) == 'positive'
                # v8.12.0b (Ron review): the red ! trigger marks the villain
                # action that PROVOKED any flagged hero decision — folds AND
                # too-loose calls/raises (was folds-only since B143). Hero's
                # own action keeps the yellow (N) pill (Q2).
                if (_has_note and not _is_positive
                        and _ta.get('action') in ('folds', 'calls', 'raises',
                                                  'bets')
                        and _last_aggro_raw is not None):
                    # v8.12.3 (Ron QA): carry the villain action description
                    # so the ! tooltip says WHAT to notice, not just a number.
                    _tv = _tacts[_last_aggro_raw]
                    _tv_desc = (f"{_tv.get('position', '?')} "
                                f"{_tv.get('action', '')} "
                                f"{(_tv.get('amount_bb') or 0):.1f}BB")
                    _trigger_markers[(_ts, _last_aggro_raw)] = (
                        action_to_note_num[_tkey], _tv_desc)
                _hero_idx += 1
            else:
                if _ta.get('action') in ('bets', 'raises', 'calls'):
                    _last_aggro_raw = _ti

    # Q4: pre-compute whether push/call-jam verdict will show ❌ so we can
    # suppress the conflicting 👍 ann-bare on the same action.
    _has_negative_pf_verdict = False
    try:
        from gem_ranges import normalize_hand_class as _nrm_q4, load_ranges as _lr_q4
        _q4_jammed = False
        if h.get('pf_allin') and h.get('first_in'):
            for _q4a in (h.get('action_ledger') or []):
                if (_q4a.get('player') == h.get('hero')
                        and _q4a.get('street') == 'preflop'
                        and _q4a.get('action') in ('raises', 'bets')
                        and _q4a.get('is_all_in')):
                    _q4_jammed = True
                    break
        _q4_stk = h.get('eff_stack_bb_at_decision') or h.get('stack_bb', 99)
        if _q4_jammed and _q4_stk <= 15:
            _q4c = h.get('cards', [])
            if len(_q4c) >= 2:
                _q4_hc = _nrm_q4(_q4c)
                # v8.14.1 P0-6: depth-appropriate chart via the shared selector
                # (not hardcoded PUSH_10BB) so this negative-verdict flag agrees
                # with the grid widget + range-evidence block.
                from gem_ranges import select_open_jam_chart as _sojc_q4
                _q4k, _q4t, _q4cov = _sojc_q4(h.get('position', '?'), _q4_stk, _lr_q4())
                _q4r = (_lr_q4()).get(_q4k or '', {})
                if _q4r and _q4_hc not in _q4r:
                    _has_negative_pf_verdict = True
        if not _has_negative_pf_verdict and h.get('pf_allin') and not _q4_jammed and _q4_stk <= 30:
            _q4c = h.get('cards', [])
            _q4j = h.get('jammer_position', '')
            if len(_q4c) >= 2 and _q4j:
                _q4_hc = _nrm_q4(_q4c)
                _q4d = ('12BB' if _q4_stk <= 14 else '15BB' if _q4_stk <= 17
                        else '20BB' if _q4_stk <= 25 else '30BB')
                _q4r = (_lr_q4()).get(f'CALLJAM_{_q4d}_vs{_q4j}', {})
                if _q4r and _q4_hc and _q4_hc not in _q4r:
                    _has_negative_pf_verdict = True
    except Exception:
        pass

    for street in used_streets:
        actions = all_actions.get(street) or []
        if not actions:
            col_cells.append('<em style="color:#aaa">—</em>')
            continue
        # Track running pot WITHIN the street so each bet/raise sees the pot
        # at the moment of action. Initialize from pre-street pot.
        running_pot = pot_by_street.get(street, 0) or 0
        # v8.8.6: track current bet level + raise count for display labels.
        # Preflop BB = 1.0 in BB-normalized data; postflop starts at 0.
        _current_bet = 1.0 if street == 'preflop' else 0.0
        _raise_count = 0  # 1=open, 2=3-bet, 3=4-bet, etc.
        # v8.12.8 QA-GPT P0.1: per-player street commitment — a raise's
        # ledger amount is the INCREMENT over the current bet, so the pot
        # must be charged the raiser's full catch-up delta (new total minus
        # what they already had in). Blind posts seed it (their chips are
        # in pot_by_street already).
        _street_commit = {}
        _gp_ante = (h.get('ante') or 0) / (h.get('bb_blind') or 1)
        for _pa in actions:
            if _pa.get('action') == 'posts':
                _pa_amt = _pa.get('amount_bb', 0) or 0
                if _gp_ante and abs(_pa_amt - _gp_ante) < 1e-6:
                    continue
                _pn = _pa.get('name', _pa.get('player', '?'))
                _street_commit[_pn] = _street_commit.get(_pn, 0) + _pa_amt
        lines = []
        i = 0
        hero_action_idx_on_street = 0
        while i < len(actions):
            # v8.8.7: skip mandatory blind/ante posts — everyone pays them,
            # they're already in the pot initialization, and they just make
            # the preflop column needlessly long.
            if actions[i].get('action') == 'posts':
                i += 1
                continue
            # Compact consecutive non-hero folds into a single line
            if actions[i].get('action') == 'folds' and not actions[i].get('is_hero'):
                j = i
                fold_positions = []
                while (j < len(actions)
                       and actions[j].get('action') == 'folds'
                       and not actions[j].get('is_hero')):
                    fold_positions.append(actions[j].get('position', '?'))
                    j += 1
                if len(fold_positions) >= 2:
                    lines.append(f'<span class="grid-action act-fold">{", ".join(fold_positions)} fold</span>')
                    i = j
                    continue
            a = actions[i]
            p = a.get('position', '?')
            _pname = a.get('player', a.get('name', ''))
            stk = _grid_stack(a)
            act = a.get('action', '')
            allin = a.get('all_in', False)
            is_h = a.get('is_hero', False)
            # REV16 §6/§8.5: source EVERY displayed size from the one full-history canonical replay —
            # `amt` is the physical chips the player adds; `_raise_to` is the live level reached. The
            # raw ledger amount_bb is NOT used for any displayed sizing (the parser folds the ante into
            # it). On real data the replay always resolves; a miss falls back to raw and is counted.
            _vr = _canon_replay(a.get('ledger_index'))
            _raw_amt = a.get('amount_bb', 0) or 0
            if _vr is not None:
                amt = _vr['physical_amount_added_bb']
                _vr_level_after = _vr['live_commitment_after_bb']
            else:
                if act in ('calls', 'bets', 'raises'):
                    _grid_fallback[0] += 1
                amt = _raw_amt
                _vr_level_after = None

            pot_pct_html = ''
            if act == 'folds':
                cls = 'act-fold'; text = f'{_ps(p, stk, _pname)} Fold'
            elif act == 'checks':
                cls = 'act-check'; text = f'{_ps(p, stk, _pname)} Check'
            elif act == 'calls':
                cls = 'act-call'
                # REV11 E1/B2/C2: a Hero 'calls' that is canonically NOT an ordinary priced call
                # (a first-in complete/limp, an underblind short all-in, or a covering re-jam)
                # renders the canonical verb and shows NO pot-odds (there is no voluntary wager to
                # price). Only a genuine call FACING a wager keeps "Call X / need Y%".
                _cg = _canon_by_street_occ.get((street, hero_action_idx_on_street)) if is_h else None
                _cg_kind = (_cg or {}).get('hero_action_kind')
                _cg_priced = bool((_cg or {}).get('price_applicable'))
                # REV14 D3: a Hero priced call shows the CANONICAL callable price (the live amount
                # Hero can actually commit), never the raw ledger amount_bb (ante-contaminated). The
                # grid and the reviewed capsule therefore show the SAME call price (83616904: 1.0 vs
                # 0.88 was the ante; 83914496: 14.7 not 14.85).
                _call_amt = amt
                if is_h and _cg is not None and _cg.get('callable_amount_bb') is not None and _cg_priced:
                    _call_amt = _cg['callable_amount_bb']
                text = f'{_ps(p, stk, _pname)} Call {_call_amt:.1f}BB'
                if _cg and _cg_kind == 'short_all_in':
                    cls = 'act-allin'
                    text = f'{_ps(p, stk, _pname)} ⚡ All-in {amt:.2f}BB (short of BB, first-in)'
                elif _cg and (_cg or {}).get('facing') == 'first_in':
                    _cverb = 'Complete' if p == 'SB' else 'Limp'
                    text = f'{_ps(p, stk, _pname)} {_cverb} {_call_amt:.1f}BB first-in'
                # REV14 D3/E1: required equity comes from the CANONICAL contestable-pot contract (the
                # same value the reviewed capsule shows), NOT a raw amt/(running_pot+amt) recompute
                # over the full pot — which over-counts the uncallable overjam / side-pot chips Hero
                # cannot win (83915165: grid 56% vs capsule 37.5%). Only a genuine priced Hero call.
                if is_h and _cg is not None and _cg_priced and _cg.get('required_equity_pct') is not None:
                    _req_eq = _cg['required_equity_pct']
                    text += (f' <span class="pot-pct" title="Call {_call_amt:.1f}BB — canonical '
                             f'required equity vs the contestable pot Hero can win">'
                             f'need {_req_eq:.0f}%</span>')
                elif is_h and _cg is None and running_pot > 0 and amt > 0:
                    # degenerate fallback (no canonical contract): the descriptive raw pot-odds.
                    _req_eq = amt / (running_pot + amt) * 100
                    text += (f' <span class="pot-pct" title="Call {amt:.1f}BB into '
                             f'{running_pot:.1f}BB pot">need {_req_eq:.0f}%</span>')
                running_pot += amt
                _cl_name = a.get('name', a.get('player', '?'))
                _street_commit[_cl_name] = _street_commit.get(_cl_name, 0) + amt
            elif act == 'bets':
                if allin:
                    cls = 'act-allin'
                    # REV16 §8.5: the effective (matched) size is the canonical physical minus the
                    # canonical uncalled return — no raw look-ahead arithmetic.
                    _uret = (_vr['uncalled_return_bb'] if _vr else 0.0)
                    _eff_amt = round(amt - _uret, 2)
                    _was_capped = _uret > 0.05
                    _lvl = _vr_level_after if _vr_level_after is not None else amt
                    pp = _pot_pct_for_bet(street, _eff_amt, running_pot)
                    pp_html = f'<span class="pot-pct">({pp})</span>' if pp else ''
                    _jam = _jam_headline(amt, _lvl)
                    if _was_capped:
                        text = (f'{_ps(p, stk, _pname)} {_jam} '
                                f'<span class="pot-pct">(eff {_eff_amt:.1f}BB'
                                f'{", " + pp if pp else ""})</span>')
                    else:
                        text = f'{_ps(p, stk, _pname)} {_jam}{pp_html}'
                else:
                    cls = 'act-bet'
                    pp = _pot_pct_for_bet(street, amt, running_pot)
                    pp_html = f'<span class="pot-pct">({pp})</span>' if pp else ''
                    text = f'{_ps(p, stk, _pname)} Bet {amt:.1f}BB{pp_html}'
                _current_bet = amt
                # v8.12.8 QA3 (66796475): a capped all-in's uncalled slice
                # is RETURNED — counting the full jam inflated the pot and
                # deflated the caller's "need %" (39% shown, 43.3% true).
                _bt_add = (_eff_amt if (allin and _was_capped) else amt)
                running_pot += _bt_add
                _bt_name = a.get('name', a.get('player', '?'))
                _street_commit[_bt_name] = (_street_commit.get(_bt_name, 0)
                                            + _bt_add)
            elif act == 'raises':
                _raise_count += 1
                # REV16 §8.3/§8.5: the raise-TO level comes from the canonical replay (the live level
                # the action reaches), not raw current_bet + increment.
                _raise_to = _vr_level_after if _vr_level_after is not None else (_current_bet + amt)
                if allin:
                    cls = 'act-allin'
                    _uret = (_vr['uncalled_return_bb'] if _vr else 0.0)
                    _eff_amt = round(amt - _uret, 2)
                    _was_capped = _uret > 0.05
                    pp = _pot_pct_for_bet(street, _eff_amt, running_pot)
                    pp_html = f'<span class="pot-pct">({pp})</span>' if pp else ''
                    _jam = _jam_headline(amt, _raise_to)
                    if _was_capped:
                        text = (f'{_ps(p, stk, _pname)} {_jam} '
                                f'<span class="pot-pct">(eff {_eff_amt:.1f}BB'
                                f'{", " + pp if pp else ""})</span>')
                    else:
                        text = f'{_ps(p, stk, _pname)} {_jam}{pp_html}'
                else:
                    cls = 'act-raise'
                    if street == 'preflop':
                        if _raise_count == 1:
                            _rlbl = 'Open to'
                        elif _raise_count == 2:
                            _rlbl = '3-bet to'
                        elif _raise_count == 3:
                            _rlbl = '4-bet to'
                        elif _raise_count == 4:
                            _rlbl = '5-bet to'
                        else:
                            _rlbl = 'Raise to'
                    else:
                        _rlbl = 'Raise to'
                    pp = _pot_pct_for_bet(street, _raise_to, running_pot)
                    pp_html = f'<span class="pot-pct">({pp})</span>' if pp else ''
                    text = f'{_ps(p, stk, _pname)} {_rlbl} {_raise_to:.1f}BB{pp_html}'
                _current_bet = _raise_to
                # v8.12.8 QA-GPT P0.1: charge the raiser their full
                # catch-up delta (to-total minus prior street commitment),
                # capped at the effective amount for under-called jams.
                _rp_name = a.get('name', a.get('player', '?'))
                _rp_delta = max(0, _raise_to
                                - _street_commit.get(_rp_name, 0))
                if allin and _was_capped:
                    _rp_delta = min(_rp_delta, _eff_amt)
                running_pot += _rp_delta
                _street_commit[_rp_name] = _raise_to
            else:
                cls = ''; text = f'{_ps(p, stk, _pname)} {act} {amt:.1f}BB'

            # REV16 §8.5: Hero AND villain all-in rows now share the ONE canonical _jam_headline
            # (REV13's Hero-only ActionSizingContract override is subsumed — `amt` is the canonical
            # physical and `_raise_to`/`_lvl` the canonical level, so every player's "adds X / all-in
            # to Y" is sourced from the same full-history replay).

            # Hero annotation
            # B54/B57 (v7.55):
            # - No analyst note attached → 👍 (yellow thumbs-up): standard play, fine
            # - Critical/instructive note → (N) numbered pill: needs reading
            # - Positive/confirming note → 👎 red thumbs-down: "good move + here's why"
            # B66 (v7.56, Ron 2026-05-18): emojis bumped via ann-emoji class
            ann_html = ''
            # REV13 C1: a forced underblind short all-in (Hero all-in below the big blind, first-in)
            # is NOT a strategic choice — it gets NO 👍/mistake marker. A green thumbs-up is a
            # strategic grade, and the contract says this node is UNGRADED (84078253). The neutral
            # explanation ("All-in XBB short of BB, first-in") lives in the action text itself.
            _ann_cg = _canon_by_street_occ.get((street, hero_action_idx_on_street)) if is_h else None
            _is_short_allin_ann = bool(_ann_cg and _ann_cg.get('hero_action_kind') == 'short_all_in')
            if is_h and not _is_short_allin_ann:
                note_key = (street, hero_action_idx_on_street)
                note_num = action_to_note_num.get(note_key)
                tone = (action_to_tone or {}).get(note_key)
                if note_num is not None:
                    if tone == 'positive':
                        # v8.12.8 QA3 (65398323): the marker said 👎 with a
                        # "Good move" tooltip since v7.55 — a defensible
                        # fold carried a red thumbs-DOWN. Thumbs up, green.
                        ann_html = (f'<span class="ann ann-positive ann-emoji" '
                                    f'title="Good move — see note ({note_num})">'
                                    f'👍<sup>{note_num}</sup></span>')
                    elif tone == 'critical':
                        # Q2 (v8.11.0d): hero mistakes use yellow (N) pill,
                        # red ! is reserved for villain trigger markers (B143).
                        ann_html = (f'<span class="ann" '
                                    f'title="Key mistake — see note ({note_num})">'
                                    f'({note_num})</span>')
                    else:
                        ann_html = f'<span class="ann">({note_num})</span>'
                else:
                    # No analyst note bound to this action.
                    # B142/B143 (v7.69): under the single-narrative override
                    # the one note is bound to the key decision.
                    # B147 (v7.71, Ron 2026-05-23): every OTHER hero action
                    # in a single-narrative hand gets 👍. The analyst reviewed
                    # the whole hand and pinned ONE key decision (the (N)
                    # pill); by that framing every other action — the setup
                    # raise, the c-bet, the cleanup fold — is fine. Ron wants
                    # the 👍 there, not a blank. Supersedes B143 (blank on
                    # chip-committing actions) and B145 (👍 on fold/check
                    # only): a 👍 on a non-key action is not a false clear,
                    # it is the analyst's holistic verdict on the hand.
                    # Q4: suppress 👍 when a push/call-jam verdict will
                    # show ❌ on this same hand — avoids contradictory signals.
                    _q4_suppress = (_has_negative_pf_verdict
                                    and street == 'preflop'
                                    and allin
                                    and act in ('raises', 'bets', 'calls'))
                    if single_narrative_note_num is not None and not _q4_suppress:
                        # v8.12.2 Phase-C: title via .pb-tt2 class (filled by
                        # JS at load) — this string repeated ~150x per report.
                        ann_html = '<span class="ann-bare pb-tt2">👍</span>'
                    # B109 (v7.59): bare 👍 — for hands with NO single-
                    # narrative blob — renders as inline emoji, no pill.
                    elif act not in ('folds', 'checks') and not _q4_suppress:
                        # ~440x per report -> .pb-tt1
                        ann_html = '<span class="ann-bare pb-tt1">👍</span>'
            # REV13 C1: the per-street Hero occurrence index advances for EVERY Hero action
            # (including the marker-suppressed short all-in) so subsequent rows stay aligned.
            if is_h:
                hero_action_idx_on_street += 1

            # v8.8.6 VH Phase 4: inline villain badges at (street, action_index)
            vb_html = ''
            if villain_badges:
                _vb_key = (street, i)
                _vb_list = list(villain_badges.get(_vb_key, []))
                # v8.9.7 B140: a (street, -1) sentinel means "no explicit action
                # index — attach to Hero's decision action on this street".
                if is_h:
                    _sentinel = villain_badges.get((street, -1), [])
                    if _sentinel and not _street_sentinel_placed.get(street):
                        if i == _hero_last_idx_by_street.get(street, i):
                            _vb_list = _vb_list + list(_sentinel)
                            _street_sentinel_placed[street] = True
                else:
                    # v8.17.1 P3b: villain-side sentinel — pin a (street, -1)
                    # note/pivot/evid atom to THIS villain's last action row, gated
                    # on the atom's villain_position == this row's position (never
                    # 'last villain action'; the position gate keeps it on the
                    # correct seat). Sentinel-anchored badges bypass the expect
                    # filter — position + last-action IS the deliberate anchor.
                    _vpos_row = (p or '').upper()
                    if (_vpos_row
                            and i == _villain_last_idx_by_street_pos.get((street, _vpos_row))
                            and not _villain_sentinel_placed.get((street, _vpos_row))):
                        for _vs in villain_badges.get((street, -1), []):
                            if (_vs.get('type') in ('note', 'pivot', 'evid')
                                    and (_vs.get('villain_position') or '') == _vpos_row):
                                _vb_list = _vb_list + [dict(_vs, _sentinel_anchored=True)]
                                _villain_sentinel_placed[(street, _vpos_row)] = True
                for _vb in _vb_list:
                    _vbt = _vb.get('type', 'note')
                    # v8.12.8 (QA F): badge-row ownership — villain evidence
                    # (note/pivot/evid) belongs on VILLAIN action rows;
                    # exploit verdicts (miss/good) on Hero's decision row. A
                    # mis-indexed atom is suppressed instead of mis-placed
                    # (the v8.8.9 BUG-4 failure mode).
                    if is_h and _vbt in ('note', 'pivot', 'evid'):
                        continue
                    if (not is_h) and _vbt in ('miss', 'good'):
                        continue
                    # v8.12.8 QA2: atom indexes are ledger-space, grid rows
                    # are street-space — require the row's action kind to
                    # match the badge's declared kind, else suppress.
                    _vb_exp = _vb.get('expect')
                    if _vb_exp and not _vb.get('_sentinel_anchored') and act not in _vb_exp:
                        continue
                    _vb_cls = 'vb-' + _vbt
                    _vb_lbl = _vb.get('label', '')
                    _vb_tip = _vb.get('tip', '')
                    _vb_tip_attr = f' title="{_vb_tip}"' if _vb_tip else ''
                    vb_html += (f'<span class="villain-badge {_vb_cls}"'
                                f'{_vb_tip_attr}>{_vb_lbl}</span>')

            # B143: trigger marker on the villain action that provoked the
            # flagged Hero decision. v8.12.8 (QA F): glyph ↪ + amber — the
            # red ! is reserved for villain EVIDENCE; a trigger is routing
            # ("this action caused the reviewed decision"), not a tell.
            trigger_html = ''
            if not is_h and _trigger_markers:
                _tm = _trigger_markers.get((street, i))
                if _tm is not None:
                    _tm_note, _tm_desc = _tm
                    trigger_html = (f'<span class="ann ann-trigger" '
                                    f'title="Trigger: {_tm_desc} provoked '
                                    f'the flagged decision — note '
                                    f'({_tm_note}) reviews '
                                    f'Hero&#39;s response">'
                                    f'↪<sup>{_tm_note}</sup></span>')

            hero_cls = ' is-hero' if is_h else ''
            lines.append(f'<span class="grid-action {cls}{hero_cls}">{text}{ann_html}{trigger_html}{vb_html}</span>')
            i += 1

        col_cells.append(''.join(lines))

    # B55 (v7.55): Result footer row — show Hero net + SD villain hand
    net_bb = h.get('net_bb') or 0
    net_sign = '+' if net_bb > 0 else ''
    net_cls = 'net-pos' if net_bb > 0 else ('net-neg' if net_bb < 0 else '')
    # BUG-A fix: h['won'] can be string 'chop' (truthy) — check chop before truthiness
    won_val = h.get('won', False)
    went_sd = h.get('went_to_sd', False)
    _is_chop = bool(h.get('is_chop')) or (isinstance(won_val, str) and won_val.lower() in ('chop', 'split', 'tie'))
    if _is_chop:
        result_label = 'CHOP'
    elif won_val:
        result_label = 'WON'
    elif net_bb < 0 or went_sd:
        result_label = 'LOST'
    else:
        result_label = 'TIED'

    # SD villain hand(s) from appendix details
    # B70/B72/B73 (v7.56, Ron 2026-05-18):
    #  - Sort hole cards by rank DESC (Ah 3h not 3h Ah)
    #  - Add made-hand description ("with two pair, Aces and Threes")
    #  - Highlight villain cards that pair to the board with a small dot
    sd_villain_html = ''
    sd_dict = (app_details.get('showdown') or {})
    if went_sd and sd_dict:
        board_cards = h.get('board') or []
        board_ranks_used = {c[0].upper() for c in board_cards if c and len(c) >= 2}
        villains = []
        for pos, info in sd_dict.items():
            if info.get('is_hero'):
                continue
            cards = _sort_cards_desc(info.get('cards') or [])
            if cards:
                # Mark hole cards that "connect" to the board (rank pairs)
                # with a subtle indicator so reader sees what villain hit.
                pills = []
                for c in cards:
                    if len(c) >= 2 and c[0].upper() in board_ranks_used:
                        pills.append(_card_html(c) +
                                     "<span class='board-match' title='Pairs board'>•</span>")
                    else:
                        pills.append(_card_html(c))
                cards_pills = ' '.join(pills)
                # Made-hand description
                made = _describe_made_hand(cards, board_cards)
                made_html = f" <span class='made-hand'>({made})</span>" if made else ''
                villains.append(f"{pos}: <span class='villain-card'>{cards_pills}</span>{made_html}")
        if villains:
            sd_villain_html = (f"<div class='sd-block'>Showdown vs " +
                                ' · '.join(villains) + "</div>")

    # V25.3 item 14: hero hand strength in result cell (guardrail 7)
    _hero_made_html = ''
    if went_sd and sd_dict:
        for _sd_pos, _sd_info in sd_dict.items():
            if _sd_info.get('is_hero'):
                _hero_cards = _sort_cards_desc(_sd_info.get('cards') or [])
                if _hero_cards and board_cards:
                    _hero_made = _describe_made_hand(_hero_cards, board_cards)
                    if _hero_made:
                        _hero_made_html = f" <span class='made-hand'>(Hero: {_hero_made})</span>"
                break

    _net_fmt = f"{net_sign}{net_bb:.1f} BB"
    _net_span = f"<span class='{net_cls}'>{_net_fmt}</span>" if net_cls else _net_fmt
    result_text = f"Hero result: {_net_span} · {result_label}{_hero_made_html}"

    # ── Result cell enrichments (pre-initialize all fragments) ──
    _eai_html = ''
    _arch_html = ''
    _icm_html = ''
    _push_html = ''
    _push_verdict_attr = ''
    _calljam_html = ''

    # EAI equity on all-in hands
    _eai_eq = (app_details or {}).get('eai_hero_equity')
    _eai_st = (app_details or {}).get('eai_street', '')
    if _eai_eq is not None:
        try:
            _eq_pct = _eai_eq * 100.0 if _eai_eq <= 1.5 else _eai_eq
            _is_fav = (app_details or {}).get('eai_is_favorite', False)
            _suckout = (app_details or {}).get('eai_suckout', '')
            _eq_cls = 'net-pos' if _is_fav else 'net-neg'
            _fav_label = 'favorite' if _is_fav else 'underdog'
            _so_label = ''
            if _suckout == 'hero_sucked_out':
                _so_label = ' · \U0001f922 got lucky'
            elif _suckout == 'hero_got_sucked_out':
                _so_label = ' · \U0001f976 got unlucky'
            # BUG-B fix: annotate chop so "77% favorite" reads in context
            if _is_chop:
                _so_label += ' · ½ runout chopped'
            _n_allin = (app_details or {}).get('eai_n_allin', 2)
            _eai_html = (f" · <span class='{_eq_cls}' title='Equity at all-in "
                         f"({_html_mod.escape(_eai_st)})' data-n-allin='{_n_allin}'>"
                         f"All-in equity: {_eq_pct:.0f}% ({_fav_label}){_so_label}"
                         f"</span>")
        except Exception:
            pass

    # Villain archetype + exploit note
    # NOTE: archetype lives on the hand dict h (set by gem_opponent_profiler),
    # NOT on app_details (appendix_hand_details) which only has seat/action/EAI data.
    _varch = _html_mod.escape(h.get('villain_archetype_label', '') or '')
    _vexploit = _html_mod.escape(h.get('villain_exploit_note', '') or '')
    if _varch:
        # Q6: link villain archetype to evidence modal when villain key exists
        _varch_link = _varch
        if _vi_vk:
            _vk_js_q6 = _json_mod.dumps(_vi_vk)
            _varch_link = (f"<a href='#' onclick=\"openVillainEvidence({_vk_js_q6});"
                           f"return false\" style='color:inherit;text-decoration:"
                           f"underline dotted;cursor:pointer;'>{_varch}</a>")
        _arch_html = (f"<div class='villain-arch' style='font-size:0.85em;"
                      f"color:var(--muted,#64748b);margin-top:3px;'>"
                      f"Villain: {_varch_link}")
        if _vexploit:
            _arch_html += f" — <em>{_vexploit}</em>"
        _arch_html += "</div>"

    # ICM context flag
    _icm = h.get('icm_context', {}) or {}
    if isinstance(_icm, dict) and _icm.get('icm_flag'):
        _icm_flag = _html_mod.escape(str(_icm['icm_flag']))
        _icm_html = (f"<div style='font-size:0.8em;color:#f59e0b;margin-top:2px;'>"
                     f"⚠️ {_icm_flag}</div>")

    # Push-range verdict for <=15BB open-shoves
    try:
        from gem_ranges import normalize_hand_class as _nrm_hc, load_ranges as _lr_push, range_boundary as _rb_push
        # v8.14.1 (GPT rev): gate the open-shove footer on the CANONICAL preflop
        # role (the same classifier the Range-evidence block uses), not a bare
        # first_in flag. A 3-bet/4-bet/re-jam/over-jam (73559949) marked first_in
        # must NOT render a "Correct/Wrong push" open-shove footer or a
        # data-push-verdict — the grid footer must agree with the evidence block.
        from gem_report_draft._helpers import _hand_preflop_range_role as _role_hg
        _hero_role_hg = _role_hg(h)
        _hero_jammed_pf = (_hero_role_hg == 'open_shove')
        # REV12 C1: a forced first-in UNDERBLIND short all-in (<1BB) is NOT a strategic open-shove —
        # never render a "Wrong/Correct push" verdict or an 8BB-proxy push chart for it (84078253).
        _is_short_allin_pv = False
        for _ce in _canon_by_street_occ.values():
            if _ce.get('actual_node_type') == 'first_in_short_all_in' or _ce.get('hero_action_kind') == 'short_all_in':
                _is_short_allin_pv = True
                break
        if (_hero_jammed_pf and not _is_short_allin_pv
                and (h.get('eff_stack_bb_at_decision') or h.get('stack_bb', 99)) <= 15):
            _ppos = h.get('position', '?')
            _pcards = h.get('cards', [])
            if len(_pcards) >= 2:
                _phc = _nrm_hc(_pcards)
                _pranges = _lr_push()
                _eff_now = (h.get('eff_stack_bb_at_decision')
                            or h.get('stack_bb') or 0)
                # v8.14.1 P0-2b/P0-6: pick the depth-appropriate chart via the
                # SHARED selector (the same one the TL;DR + the range-evidence
                # block use) so the grid widget can never cite a different chart
                # for the same jam (the 73400934 PUSH_10BB-vs-JAM_15BB split).
                from gem_ranges import select_open_jam_chart as _sojc_hg
                _pk, _ptgt_hg, _pcov_hg = _sojc_hg(_ppos, _eff_now, _pranges)
                _prange = _pranges.get(_pk or '', {})
                if _prange:
                    _in = _phc in _prange
                    _in_label = 'in' if _in else 'outside'
                    _in_color = '#22c55e' if _in else '#ef4444'
                    _boundary = _rb_push(', '.join(_prange.keys()))
                    _range_note = f' (boundary: {_boundary})' if _boundary else ''
                    # Disclose proxy/closest — never present an aliased/adjacent
                    # chart as an exact this-position-this-depth verdict.
                    if _pcov_hg == 'exact':
                        _near_line = (f"Chart: {_cdl_hg(_pk)} "
                                      f"(effective {_eff_now:.1f}BB).")
                    elif _pcov_hg == 'proxy':
                        _near_line = (f"Closest available: {_cdl_hg(_pk)} — position "
                                      f"proxy; no exact {_ppos} chart at "
                                      f"{_eff_now:.0f}BB.")
                    else:
                        _near_line = (f"Closest available: {_cdl_hg(_pk)} — nearest "
                                      f"depth; no exact chart at {_eff_now:.1f}BB.")
                    # v8.13.1 P1: reconcile against the FINAL analyst verdict so
                    # the auto widget never contradicts it.
                    # v8.17.1 P5(1): the "analyst cleared it" override consumes the
                    # ONE canonical verdict (active-queue or analyst decision) so the
                    # push footer can never disagree with the topbar / pill / markers.
                    _av_pv = ''
                    if rd:
                        _cvm_pv = rd.get('canonical_verdicts') or {}
                        _cv_pv = (_cvm_pv.get(h.get('id'))
                                  or _cvm_pv.get(str(h.get('id', ''))[-8:]))
                        if _cv_pv is not None:
                            if _cv_pv.get('source') in ('active_queue',
                                                        'analyst_reviewed'):
                                _av_pv = _cv_pv.get('verdict', '') or ''
                        else:
                            _cmt_pv = (rd.get('analyst_commentary') or {}).get(h.get('id')) or {}
                            if isinstance(_cmt_pv, dict):
                                _av_pv = _cmt_pv.get('verdict', '') or ''
                    _mode_pv, _note_pv = reconcile_push_widget(_in, _av_pv)
                    if _mode_pv == 'overridden':
                        _in_color = '#6b7280'
                        _verdict_push = (f'↩︎ Auto check flagged {_phc} {_in_label} '
                                         f'the {_cdl_hg(_pk)} range, but the analyst '
                                         f'cleared it ({_av_pv}).')
                    else:
                        _in_icon = '✅ Correct push' if _in else '❌ Wrong push'
                        _verdict_push = (f'{_in_icon} — {_phc} is {_in_label} the '
                                         f'{_cdl_hg(_pk)} range{_range_note}')
                        if _mode_pv == 'pre_review':
                            _verdict_push += ' · auto pre-review'
                    _push_html = (f"<div class='push-verdict' style='font-size:0.85em;"
                                 f"color:{_in_color};font-weight:700;"
                                 f"margin-top:2px;'>{_verdict_push}"
                                 f"<span style='display:block;font-weight:400;"
                                 f"color:#6b7280;font-size:0.92em'>{_near_line}</span></div>")
                    _safe_verdict = _html_mod.escape(_verdict_push, quote=True)
                    _push_verdict_attr = f" data-push-verdict='{_safe_verdict}'"

        # Call-jam verdict: Hero CALLED an all-in. v8.14.1 (GPT rev): gate on the
        # canonical role (== 'call_jam') so a re-jam/over-jam never falls into the
        # call-jam footer, and pick the NEAREST depth tier (not a ceil cutoff) so
        # this footer agrees with the Range-evidence block.
        if (_hero_role_hg == 'call_jam'
                and (h.get('eff_stack_bb_at_decision') or h.get('stack_bb', 99)) <= 30):
            _cj_pos = h.get('position', '?')
            _cj_cards = h.get('cards', [])
            _cj_jammer = h.get('jammer_position', '?')
            if len(_cj_cards) >= 2 and _cj_jammer:
                _cj_hc = _nrm_hc(_cj_cards)
                _cj_stack = h.get('eff_stack_bb_at_decision') or h.get('stack_bb') or 15
                _cj_depth = str(min([12, 15, 20, 30],
                                    key=lambda t: abs(t - (_cj_stack or 0)))) + 'BB'
                _cj_key = f'CALLJAM_{_cj_depth}_vs{_cj_jammer}'
                _cj_ranges = _lr_push()
                _cj_range = _cj_ranges.get(_cj_key, {})
                if _cj_range and _cj_hc:
                    _cj_in = _cj_hc in _cj_range
                    _cj_color = '#22c55e' if _cj_in else '#f59e0b'
                    _cj_label = 'in' if _cj_in else 'outside'
                    # v8.14.1 rev-3 (Blocker 3): CALLJAM_*BB is the NEAREST chart,
                    # not necessarily this hand's depth — state the actual effective
                    # stack so a 12BB-chart check on a ~6BB jam never reads as a
                    # definitive "Loose call" that contradicts the concrete pot-odds
                    # verdict (the 👍 on the action). Mirror the push-widget
                    # treatment: reconcile against the FINAL analyst verdict and
                    # label a not-yet-reviewed auto check as a pre-review heuristic.
                    _cj_near = (f"Nearest chart: {_cdl_hg(_cj_key)}; actual effective "
                                f"stack: {_cj_stack:.1f}BB.")
                    # v8.17.1 P5(1): same canonical override source as the push footer.
                    _av_cj = ''
                    if rd:
                        _cvm_cj = rd.get('canonical_verdicts') or {}
                        _cv_cj = (_cvm_cj.get(h.get('id'))
                                  or _cvm_cj.get(str(h.get('id', ''))[-8:]))
                        if _cv_cj is not None:
                            if _cv_cj.get('source') in ('active_queue',
                                                        'analyst_reviewed'):
                                _av_cj = _cv_cj.get('verdict', '') or ''
                        else:
                            _cmt_cj = (rd.get('analyst_commentary') or {}).get(h.get('id')) or {}
                            if isinstance(_cmt_cj, dict):
                                _av_cj = _cmt_cj.get('verdict', '') or ''
                    _cj_mode, _ = reconcile_push_widget(_cj_in, _av_cj)
                    if _cj_mode == 'overridden':
                        _cj_color = '#6b7280'
                        _cj_verdict = (f'↩︎ Auto check flagged {_cj_hc} {_cj_label} the '
                                       f'{_cdl_hg(_cj_key)} range, but the analyst '
                                       f'cleared it ({_av_cj}).')
                    else:
                        _cj_icon = '✅ Correct call' if _cj_in else '❌ Loose call'
                        _cj_verdict = (f'{_cj_icon} — {_cj_hc} is {_cj_label} the '
                                       f'{_cdl_hg(_cj_key)} range')
                        if _cj_mode == 'pre_review':
                            _cj_verdict += ' · auto pre-review'
                    _calljam_html = (f"<div style='font-size:0.85em;color:{_cj_color};"
                                    f"font-weight:700;margin-top:2px;'>{_cj_verdict}"
                                    f"<span style='display:block;font-weight:400;"
                                    f"color:#6b7280;font-size:0.92em'>{_cj_near}</span></div>")
    except Exception:
        pass  # gem_ranges import failure — skip verdicts silently

    result_cell = f"{result_text}{_eai_html}{sd_villain_html}{_arch_html}{_icm_html}{_push_html}{_calljam_html}"
    # Use colspan equal to number of street columns
    n_cols = len(used_streets)

    # Emit table
    # v8.17.1 P5(1): the action-row grid carries the SAME canonical verdict the
    # topbar / push & call-jam footer / capsule / queue read (zero drift).
    _canon_attr = ''
    try:
        _cvm_g = (rd or {}).get('canonical_verdicts') or {}
        _cv_g = (_cvm_g.get(h.get('id'))
                 or _cvm_g.get(str(h.get('id', ''))[-8:]) or {})
        _cvv_g = _cv_g.get('verdict', '') or ''
        if _cvv_g:
            _canon_attr = (" data-canonical-verdict='"
                           + _html_mod.escape(_cvv_g, quote=True) + "'")
    except Exception:
        _canon_attr = ''
    doc.w(f"<table class='hand-grid'{_push_verdict_attr}{_canon_attr}>")
    doc.w("<thead><tr>")
    for h_html in headers:
        doc.w(f"<th>{h_html}</th>")
    doc.w("</tr></thead>")
    doc.w("<tbody><tr>")
    for cell in col_cells:
        doc.w(f"<td class='street-actions'>{cell}</td>")
    doc.w("</tr></tbody>")
    doc.w(f"<tfoot><tr><td class='result' colspan='{n_cols}'>{result_cell}</td></tr></tfoot>")
    doc.w("</table>")
    doc.w("")

    # B68 (v7.56, Ron 2026-05-18): structured analyst notes.
    # Break each note into sub-rows tagged with emoji markers:
    #   🧠 strategic frame / texture / hand quality
    #   🗒️ Ron's own note (quoted via "Ron's note:" or "Ron's quote:")
    #   🧮 pot odds / math / EV / equity
    #   🎯 villain range construction
    #   📋 action recap (only if adds beyond grid)
    # Renderer emits each sub-row as its own <p> so they're visually separated
    # instead of one big blob.
    def _structure_note(note_text):
        """Return list of (emoji, text) tuples for sub-rows."""
        import re as _re2
        out = []
        # Detect "**Math:**" block (already a Math: prefix from matchup field)
        if note_text.startswith('**Math:**'):
            return [('🧮', note_text.replace('**Math:**', '').strip())]

        # Detect Ron's quoted notes — patterns like:
        #   Ron's note: '...'
        #   Ron's quote: "..."
        # B85 (v7.57, Ron 2026-05-18): match balanced quote pairs so inner
        # apostrophes in "didn't" don't break the capture. Try matching
        # ' ... ' (single quotes around a phrase ending at colon-or-period)
        # or " ... " (double quotes). Greedy to phrase-end punctuation.
        ron_match = (
            _re2.search(r"Ron's\s+(?:note|quote)\s*:\s*'([^']*(?:'[a-z]+[^']*)*)'(?=[.\s])",
                        note_text, _re2.IGNORECASE)
            or _re2.search(r'Ron\'s\s+(?:note|quote)\s*:\s*"([^"]+)"',
                           note_text, _re2.IGNORECASE)
        )
        ron_quote = None
        if ron_match:
            ron_quote = ron_match.group(1).strip()
            # Remove the matched portion from main text
            note_text = note_text[:ron_match.start()] + note_text[ron_match.end():]
            note_text = _re2.sub(r'\s{2,}', ' ', note_text).strip()

        # Sentence-split the main text and classify each
        sentences = _re2.split(r'(?<=[.!?])\s+(?=[A-Z(*\[])', note_text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        # Math markers — phrases with %, BB equity, fold equity, EV calc, pot odds
        math_re = _re2.compile(
            r'(equity|EV\s+(at|of|=)|fold equity|pot odds|×\s*\d|\d+%|'
            r'-\d+\s*BB\s*vs|wins?\s*\d+%|loses?\s*\d+%)',
            _re2.IGNORECASE)
        # Range construction markers
        range_re = _re2.compile(
            r'(range\s+(includes|is|weighted|construction)|'
            r'sets\s*\(|combos?\s+of|villain.s\s+range|XR\s+range|'
            r'jam\s+range|3-?bet\s+range|flat\s+range|stack-?off\s+range)',
            _re2.IGNORECASE)
        # Pure action recap markers — if a sentence is just describing what
        # happened on a street, it's redundant with the grid
        action_recap_re = _re2.compile(
            r'^(BB|UTG|UTG\+1|MP|HJ|CO|BTN|SB|Hero)\s+'
            r'(checks?|calls?|bets?|raises?|folds?|jams?|3-?bets?|donks?)\.?\s*$',
            _re2.IGNORECASE)
        # B94 (v7.58, Ron 2026-05-18): also drop pure board-recap sentences
        # like "Flop 7♠ 2♠ 6♣ rainbow." — grid header already shows the board.
        # Match: street name + 3-5 card refs (rank+suit or rank+symbol) +
        # optional texture word (rainbow/monotone/two-tone/connector/paired/etc).
        board_recap_re = _re2.compile(
            r'^(?:Flop|Turn|River)\s+'
            r'(?:[2-9TJQKA][shdc♠♥♦♣]\s*){3,5}'
            r'(?:rainbow|monotone|two-?tone|connector|paired|dry|wet|coord|disc)?\.?\s*$',
            _re2.IGNORECASE)

        # Bucket sentences
        math_bucket = []
        range_bucket = []
        frame_bucket = []  # default — strategic framing
        for sn in sentences:
            if action_recap_re.match(sn):
                # B68: drop pure action restatements — grid shows them
                continue
            if board_recap_re.match(sn):
                # B94: drop pure board-recap sentences — grid header shows them
                continue
            # B88 (v7.58, Ron 2026-05-18): comprehensive chip-amount cleanup.
            # The report works in BB throughout — chip amounts in analyst
            # prose are jarring and force the reader to convert. Patterns:
            #   (2,795 into 2,895)       — parenthetical asides
            #   (1,200) / (~9K)          — bare bet-amount parentheticals
            #   "to 10,350" / "to 1,200" — inline raise-to/bet-to amounts
            #   "snap-calls with 77 (set)" — preserve, those are hand combos
            # Strip: parenthetical chip asides + inline chip "to NNNN"
            #         + standalone trailing chip mentions
            # Keep: BB references (181BB), percentages (22%), hand combos (77, 87s)
            sn = _re2.sub(r'\(\s*~?\$?[\d,]+K?\s+(?:into|of|chips|to)\s+~?\$?[\d,]+K?\s*\)', '', sn)
            sn = _re2.sub(r'\(\s*~?\$?[\d,]{4,}K?\s*\)', '', sn)
            # Inline "to 10,350" / "to 1,200" → drop the amount.
            # Match: word "to" + optional ~/$ + digits-with-comma(s) + optional K,
            # NOT followed by 'BB' (which would be a BB amount we want to keep).
            sn = _re2.sub(r'\s+to\s+~?\$?[\d]{1,3}(?:,[\d]{3})+K?\b(?!\s*BB)',
                          '', sn)
            # Standalone "X = -100 BB" math expression: we want to preserve
            # the BB result. Don't touch.
            # Trailing chip-amount mentions: " 1,200" at end of clause
            sn = _re2.sub(r',?\s+~?\$?[\d]{1,3}(?:,[\d]{3})+K?(?=\s*[.,;!?]|\s*$)(?!\s*BB)',
                          '', sn)
            # B107 (Ron 2026-05-19): catch ALL remaining inline chip refs.
            # Pattern: comma-thousands number (1,071 / 12,984 / 6,006) appearing
            # ANYWHERE in a sentence, not just trailing or in "to N" context.
            # Common shapes from analyst prose:
            #   "Hero's call adds 1,071 to the pot"
            #   "6,006 to call into 4,400 + 6,006 = needs 36.6%"
            #   "BTN bets 3,398 (~90% pot)"
            # Strip the number + optional trailing chip-context word, preserve
            # surrounding prose. NOT followed by 'BB' / '%' (preserve those).
            sn = _re2.sub(
                r'\b~?\$?\d{1,3}(?:,\d{3})+K?\b(?!\s*(?:BB|%|/100|bb|outs?|combos?|combo|hands?|cards?))',
                '<chips>', sn)
            # Clean up artifacts from chip-strip: "<chips> to <chips> = needs"
            # → "to needs"; "adds <chips> to the pot" → "adds to the pot"
            sn = _re2.sub(r'<chips>\s*(?:to call into|to call|into|to)\s*<chips>\s*=\s*', '', sn)
            sn = _re2.sub(r'<chips>\s*\+\s*<chips>\s*=\s*', '', sn)
            sn = _re2.sub(r'\s*<chips>\s*', ' ', sn)
            sn = _re2.sub(r'\s+to\s+the\s+pot\b', ' to the pot', sn)
            # Final cleanup of dangling math tokens left by chip-strip
            sn = _re2.sub(r'\s*=\s*needs\s*', ' needs ', sn)
            sn = _re2.sub(r'\s{2,}', ' ', sn).strip()
            # If sentence becomes too thin after stripping ("BB check-raises ."),
            # drop entirely — the grid shows the action.
            if not sn or sn == '.' or len(sn) < 12:
                continue
            if math_re.search(sn):
                math_bucket.append(sn)
            elif range_re.search(sn):
                range_bucket.append(sn)
            else:
                frame_bucket.append(sn)

        # Emit in order: frame first, then range, then math, then Ron's quote
        if frame_bucket:
            out.append(('🧠', ' '.join(frame_bucket)))
        if range_bucket:
            out.append(('🎯', ' '.join(range_bucket)))
        if math_bucket:
            out.append(('🧮', ' '.join(math_bucket)))
        if ron_quote:
            out.append(('🗒️', f'<em>Ron\'s note:</em> "{ron_quote}"'))

        if not out:
            # Fallback: emit the original text as a single frame row
            out.append(('🧠', note_text.strip()))
        return out

    # Numbered notes block — B96 (v7.58, Ron 2026-05-18): organize BY STREET.
    # Each street that had hero action gets a header (PRE-FLOP / FLOP / TURN
    # / RIVER). Under each header, notes appear in the same (N) numbering
    # used by the action grid markers. Streets with no critical notes show
    # "no comment". Trailing unbound notes (matchup math) appear under the
    # LAST street that has hero action.
    if notes:
        # Compute hero_actions_by_street here (not passed in as parameter)
        hero_actions_by_street_local = _hero_actions_by_street_from_app(app_details)
        bound_note_nums = set(action_to_note_num.values())
        notenum_to_action = {}
        for (st, act_idx), nnum in action_to_note_num.items():
            notenum_to_action[nnum] = (st, act_idx)

        # Group bound notes by street
        notes_by_street = {'preflop': [], 'flop': [], 'turn': [], 'river': []}
        unbound_notes = []
        for i, note in enumerate(notes, 1):
            if i in bound_note_nums:
                st, _ = notenum_to_action[i]
                notes_by_street[st].append((i, note))
            else:
                unbound_notes.append((i, note))

        # Identify which street is the "last" with action
        last_street_with_action = None
        for street in ('river', 'turn', 'flop', 'preflop'):
            if hero_actions_by_street_local.get(street):
                last_street_with_action = street
                break

        doc.w("<div class='analyst-notes'>")
        # v8.13.1 P1: final analyst verdict for TL;DR-vs-verdict reconciliation
        _hand_av = ''
        if rd:
            _cmt_av = (rd.get('analyst_commentary') or {}).get(h.get('id')) or {}
            if isinstance(_cmt_av, dict):
                _hand_av = _cmt_av.get('verdict', '') or ''
        street_labels = {'preflop': 'PRE-FLOP', 'flop': 'FLOP',
                         'turn': 'TURN', 'river': 'RIVER'}
        for street in ('preflop', 'flop', 'turn', 'river'):
            ha = hero_actions_by_street_local.get(street, [])
            if not ha:
                continue
            label = street_labels[street]
            street_notes = notes_by_street[street]
            if street == last_street_with_action and unbound_notes:
                street_notes = street_notes + unbound_notes
            if not street_notes:
                continue
            doc.w(f"<p class='note-street'><strong>{label}</strong></p>")
            for note_num, note in street_notes:
                # Defensive coercion: a non-string note (e.g. a stray int
                # note-number) must not reach the string-based detectors below.
                if not isinstance(note, str):
                    note = '' if note is None else str(note)
                is_bound = note_num in bound_note_nums
                # B146 (v7.71): a structured argument renders as TL;DR +
                # section sub-headers + bullets, bypassing the prose-mangler.
                if _argument_is_structured(note):
                    _emit_structured_note(doc, note, note_num, is_bound,
                                          analyst_verdict=_hand_av)
                    continue
                sub_rows = _structure_note(note)
                for j, (emoji, text) in enumerate(sub_rows):
                    # v8.12.8 QA: prose notes are emitted as raw HTML <p>
                    # lines, so analyst markdown (**bold**) stayed literal
                    # on screen — the structured-note path already runs
                    # _note_inline; do the same here.
                    text_with_pills = _note_inline(text)
                    if j == 0 and is_bound:
                        doc.w(f"<p><span class='note-num'>{note_num}</span> "
                              f"<span class='note-tag'>{emoji}</span> {text_with_pills}</p>")
                    else:
                        doc.w(f"<p class='note-cont'>"
                              f"<span class='note-tag'>{emoji}</span> {text_with_pills}</p>")
        doc.w("</div>")
        doc.w("")


def _hero_actions_by_street_from_app(app_details):
    """Returns {street: [action_idx, ...]} for hero's actions on each street
    (using action ordinal within the hero-only sequence of that street).
    The action_idx is the 0-based index of the action among hero's actions
    on that street."""
    out = {'preflop': [], 'flop': [], 'turn': [], 'river': []}
    all_actions = app_details.get('actions') or {}
    for street in out:
        idx = 0
        for a in all_actions.get(street, []) or []:
            # v8.8.7: skip mandatory blind/ante posts (consistent with grid render)
            if a.get('action') == 'posts':
                continue
            if a.get('is_hero'):
                out[street].append(idx)
                idx += 1
    return out


def _hero_action_verbs_by_street_from_app(app_details):
    """Returns {street: [verb, ...]} — the raw action verb for each hero
    action on each street, index-parallel to _hero_actions_by_street_from_app.
    Used by _pick_key_action_idx to bind the single-narrative note to the
    action the analyst's key_decision names (B145, v7.70)."""
    out = {'preflop': [], 'flop': [], 'turn': [], 'river': []}
    all_actions = app_details.get('actions') or {}
    for street in out:
        for a in all_actions.get(street, []) or []:
            # v8.8.7: skip mandatory blind/ante posts (consistent with grid render)
            if a.get('action') == 'posts':
                continue
            if a.get('is_hero'):
                out[street].append((a.get('action') or '').lower())
    return out


# ============================================================
# MAIN ENTRY POINTS
# ============================================================

