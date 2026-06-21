"""gem_final_status.py -- the ONE canonical Final Decision Status owner (Wave 1A, v8.18.0).

Every surface that shows a hand's SYSTEM status (hand-detail top bar / article, the lazy body,
the reviewed-hand list, the review queue, the hand-list popup, the summary, a commentary heading)
reads the SAME typed value produced here. No renderer re-derives the status. Analyst/user REVIEW
state (Agree / Debate / Report bug / Drill / Rulebook / user feedback) is a SEPARATE concept and
never redefines the system status -- it is carried by its own review controls, not here.

Status -- exactly one per hand, in PRECEDENCE order (highest wins for a multi-decision hand):

    MISTAKE      -- a genuine graded action error
    CONDITIONAL  -- a read-dependent / borderline / mixed graded decision (no confirmed error)
    CLEARED      -- at least one graded-correct decision; no error and nothing conditional
    UNGRADED     -- no gradeable Hero decision (a walk / a forced sub-blind all-in / result-only)

Secondary reasons are SEPARATE and never masquerade as status (zero or more):

    SUCKOUT  FLIP  COOLER  JUSTIFIED  READ_DEPENDENT

Derivation consumes the EXISTING canonical decision evidence -- never the result alone:
  * gem_review_trust.resolve_canonical_verdict  -> the single-source verdict + a mistake/cleared/
    neutral marker (already priced/priority-resolved: active-queue > analyst > usable-auto > outcome
    > neutral), surfaced per hand as rd['canonical_verdicts'][id] by _helpers.build_canonical_verdicts;
  * gem_decision_snapshot.decision_grade_eligibility -> the UNGRADED contract (a walk or a forced
    first-in sub-blind all-in has no push/fold/call choice to grade).

This module is pure/​deterministic and typed for a future web frontend (to_dict / from_dict round-trip).
"""
import html as _html
from enum import Enum
from dataclasses import dataclass


class FinalDecisionStatus(Enum):
    MISTAKE = 'MISTAKE'
    CONDITIONAL = 'CONDITIONAL'
    CLEARED = 'CLEARED'
    UNASSESSED = 'UNASSESSED'
    UNGRADED = 'UNGRADED'


class SecondaryReason(Enum):
    SUCKOUT = 'SUCKOUT'
    FLIP = 'FLIP'
    COOLER = 'COOLER'
    JUSTIFIED = 'JUSTIFIED'
    READ_DEPENDENT = 'READ_DEPENDENT'


# precedence -- higher wins when a hand carries multiple graded decisions.
# (v8.18.0 W1-A correction §1.1: UNASSESSED sits BELOW CLEARED -- "nothing confirmed wrong" is NOT
# "explicitly judged correct" -- and ABOVE UNGRADED -- a gradeable-but-unjudged hand is not a non-hand.)
_PRECEDENCE = {
    FinalDecisionStatus.MISTAKE: 4,
    FinalDecisionStatus.CONDITIONAL: 3,
    FinalDecisionStatus.CLEARED: 2,
    FinalDecisionStatus.UNASSESSED: 1,
    FinalDecisionStatus.UNGRADED: 0,
}

# concise, consistent product display labels.
_STATUS_LABEL = {
    FinalDecisionStatus.MISTAKE: 'Mistake',
    FinalDecisionStatus.CONDITIONAL: 'Conditional',
    FinalDecisionStatus.CLEARED: 'Cleared',
    FinalDecisionStatus.UNASSESSED: 'Not reviewed',
    FinalDecisionStatus.UNGRADED: 'No decision',
}
# CSS modifier suffix (used in the .fs-* class + as the contradiction-gate key).
_STATUS_CSS = {
    FinalDecisionStatus.MISTAKE: 'mistake',
    FinalDecisionStatus.CONDITIONAL: 'conditional',
    FinalDecisionStatus.CLEARED: 'cleared',
    FinalDecisionStatus.UNASSESSED: 'unassessed',
    FinalDecisionStatus.UNGRADED: 'ungraded',
}
_SECONDARY_LABEL = {
    SecondaryReason.SUCKOUT: 'Suckout',
    SecondaryReason.FLIP: 'Flip',
    SecondaryReason.COOLER: 'Cooler',
    SecondaryReason.JUSTIFIED: 'Justified',
    SecondaryReason.READ_DEPENDENT: 'Read-dependent',
}


@dataclass(frozen=True)
class FinalStatus:
    """One hand's canonical final status + its separate secondary reasons. Immutable / typed."""
    status: FinalDecisionStatus
    secondary_reasons: tuple = ()    # tuple[SecondaryReason]
    rationale: str = ''

    def label(self):
        return _STATUS_LABEL[self.status]

    def css(self):
        return _STATUS_CSS[self.status]

    def secondary_labels(self):
        return [_SECONDARY_LABEL[r] for r in self.secondary_reasons]

    def to_dict(self):
        """Typed serialization shared by the static shell AND the lazy payload (one value, no drift)."""
        return {
            'status': self.status.value,
            'label': self.label(),
            'css': self.css(),
            'secondary': [r.value for r in self.secondary_reasons],
            'secondary_labels': self.secondary_labels(),
            'rationale': self.rationale,
        }

    @staticmethod
    def from_dict(d):
        if not d:
            return None
        return FinalStatus(
            FinalDecisionStatus(d.get('status', 'UNGRADED')),
            tuple(SecondaryReason(x) for x in (d.get('secondary') or [])),
            d.get('rationale', '') or '')


# --------------------------------------------------------------------------- #
# derivation                                                                   #
# --------------------------------------------------------------------------- #

def _norm(s):
    return (s or '').strip().lower()


# The canonical verdict taxonomy is carried in TWO interchangeable forms -- coded ('III.2 Mistake')
# and humanized ('Mistake') -- and the coded form does NOT match the bare-word MISTAKE_VERDICTS set,
# so the cv marker alone is unreliable for coded verdicts. The status owner therefore classifies from
# the verdict string itself (codes authoritative), matching the _SHORT_VERDICT taxonomy every pill uses:
#   III.1 Punt / III.2 Mistake .......... a graded action error      -> MISTAKE
#   III.4 Read-dependent / III.8/III.9 Pick  borderline / read-only  -> CONDITIONAL
#   I.7 Cooler / III.0 Standard / III.3 Cleared / III.5 Justified ... -> CLEARED
_MISTAKE_CODES = ('iii.1', 'iii.2')
_CONDITIONAL_CODES = ('iii.4', 'iii.8', 'iii.9')
_CLEARED_CODES = ('i.7', 'iii.0', 'iii.3', 'iii.5')
_CONDITIONAL_WORDS = ('read-dependent', 'read dependent', 'read-dep', 'debate', 'pick', 'unclear')
_CLEARED_WORDS = ('cooler', 'justified', 'cleared', 'standard', 'correct')


def _classify_verdict(verdict_norm):
    """Map a normalized verdict string (coded 'iii.2 mistake' OR humanized 'mistake') to a status,
    or None when it carries no graded signal. Codes take priority (the authoritative taxonomy)."""
    v = verdict_norm
    if not v:
        return None
    if v.startswith(_MISTAKE_CODES):
        return FinalDecisionStatus.MISTAKE
    if v.startswith(_CONDITIONAL_CODES):
        return FinalDecisionStatus.CONDITIONAL
    if v.startswith(_CLEARED_CODES):
        return FinalDecisionStatus.CLEARED
    if 'mistake' in v or 'punt' in v:
        return FinalDecisionStatus.MISTAKE
    if any(w in v for w in _CONDITIONAL_WORDS):
        return FinalDecisionStatus.CONDITIONAL
    if any(w in v for w in _CLEARED_WORDS):
        return FinalDecisionStatus.CLEARED
    return None


def status_from_canonical_verdict(cv):
    """Map ONE canonical-verdict dict (resolve_canonical_verdict + auto_downgraded flags) to a GRADED
    FinalDecisionStatus. The caller guarantees the decision is GRADABLE.

      * a Punt/Mistake verdict (coded III.1/III.2 or worded), or marker 'mistake' ... MISTAKE
      * an explicit read-dependent / pick / debate verdict, OR a downgraded suspected
        auto-mistake (auto_downgraded) .............................................. CONDITIONAL
      * an EXPLICIT positive adjudication -- cleared / justified / standard / correct, or a
        cooler/flip/suckout WITH a correct-action verdict (I.7/III.0/III.3/III.5) .... CLEARED
      * gradeable but NO positive or negative adjudication (a neutral 'Review', neutral
        queue inclusion, or simply not individually reviewed) ....................... UNASSESSED

    v8.18.0 W1-A correction §1.1: "nothing confirmed wrong" is NOT "explicitly judged correct" -- an
    unjudged gradeable hand is UNASSESSED ("Not reviewed"), never CLEARED. Never returns UNGRADED
    (decided upstream by gradeability). Never returns MISTAKE without an actual Punt/Mistake signal."""
    cv = cv or {}
    marker = _norm(cv.get('marker'))
    by_verdict = _classify_verdict(_norm(cv.get('verdict')))
    if by_verdict is FinalDecisionStatus.MISTAKE or marker == 'mistake':
        return FinalDecisionStatus.MISTAKE
    if by_verdict is FinalDecisionStatus.CONDITIONAL or cv.get('auto_downgraded'):
        return FinalDecisionStatus.CONDITIONAL
    if by_verdict is FinalDecisionStatus.CLEARED:
        return FinalDecisionStatus.CLEARED
    # gradeable, but the canonical verdict carries no positive or negative adjudication
    return FinalDecisionStatus.UNASSESSED


def secondary_reasons(h, cv, app_details=None):
    """Independent secondary reasons -- descriptive context that NEVER changes the status.
    cooler / justified / read-dependent come from the verdict; suckout / flip from the all-in
    equity + result classification already carried on the hand (the EAI fields). Deduped, ordered."""
    cv = cv or {}
    h = h or {}
    ad = app_details or {}
    verdict = _norm(cv.get('verdict'))
    so = (ad.get('eai_suckout') or h.get('eai_suckout') or '')
    out = []
    if verdict.startswith('i.7') or 'cooler' in verdict or so == 'hero_got_sucked_out':
        out.append(SecondaryReason.COOLER)
    if verdict.startswith('iii.5') or 'justified' in verdict:
        out.append(SecondaryReason.JUSTIFIED)
    if (verdict.startswith(('iii.4', 'iii.8', 'iii.9'))
            or 'read-dependent' in verdict or 'read dependent' in verdict or 'read-dep' in verdict):
        out.append(SecondaryReason.READ_DEPENDENT)
    if so == 'hero_sucked_out':
        out.append(SecondaryReason.SUCKOUT)
    if not out and h.get('pf_allin'):
        eq = ad.get('eai_hero_equity')
        if eq is None:
            eq = h.get('eai_hero_equity')
        if eq is not None:
            eqp = eq * 100 if eq <= 1.5 else eq
            if 40 <= eqp <= 60:
                out.append(SecondaryReason.FLIP)
    seen, uniq = set(), []
    for r in out:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return tuple(uniq)


def hand_gradeability(h):
    """'GRADABLE' or 'UNGRADED' via the canonical decision-snapshot taxonomy
    (gem_decision_snapshot.decision_grade_eligibility). A walk (Hero takes no voluntary action) and a
    forced first-in sub-blind short all-in have no push/fold/call choice, so they are UNGRADED.
    Defensive: if the snapshot cannot be built, treat the hand as UNGRADED rather than inventing a
    grade (a result-only hand must never be strategically graded)."""
    try:
        from gem_decision_snapshot import build_decision_snapshot, decision_grade_eligibility
        snap = build_decision_snapshot(h) or {}
        return decision_grade_eligibility(
            snap.get('actual_node_type'), bool(snap.get('no_hero_decision')))
    except Exception:
        return 'UNGRADED'


_GRADED_RATIONALE = {
    FinalDecisionStatus.MISTAKE: 'Graded action error (canonical decision verdict).',
    FinalDecisionStatus.CONDITIONAL: 'Read-dependent / borderline graded decision -- correct only under a read.',
    FinalDecisionStatus.CLEARED: "Graded decision was explicitly adjudicated correct / standard; the result does not change the grade.",
    FinalDecisionStatus.UNASSESSED: 'A gradeable Hero decision with no positive or negative adjudication -- not individually reviewed.',
}


def derive_final_status(h, cv, app_details=None, gradeability=None):
    """THE entry point. Return the one canonical FinalStatus for a hand.

    * UNGRADED when the reviewed Hero decision is not gradeable (a walk / a forced sub-blind all-in /
      a result-only hand) -- decided from decision evidence, NEVER from the result.
    * otherwise the graded status from the canonical verdict, with separate secondary reasons.

    Review state (analyst Agree/Debate, user feedback) is NOT consulted -- it cannot redefine the
    system status."""
    grade = gradeability or hand_gradeability(h)
    if grade == 'UNGRADED':
        return FinalStatus(
            FinalDecisionStatus.UNGRADED, (),
            'No gradeable Hero decision (a walk, a forced sub-blind all-in, or a result-only hand).')
    status = status_from_canonical_verdict(cv)
    return FinalStatus(status, secondary_reasons(h, cv, app_details), _GRADED_RATIONALE[status])


def combine_statuses(statuses):
    """Fold a hand's several graded-decision statuses into ONE via the frozen precedence
    MISTAKE > CONDITIONAL > CLEARED > UNASSESSED > UNGRADED. Secondary reasons never override the
    precedence. Accepts FinalStatus, FinalDecisionStatus, or status-string items."""
    best = FinalDecisionStatus.UNGRADED
    for s in statuses or ():
        if isinstance(s, FinalStatus):
            s = s.status
        elif isinstance(s, str):
            s = FinalDecisionStatus(s)
        if _PRECEDENCE[s] > _PRECEDENCE[best]:
            best = s
    return best


# --------------------------------------------------------------------------- #
# rendering -- the ONE place canonical-status HTML is produced                 #
# --------------------------------------------------------------------------- #

def status_payload(fs):
    """Normalize a FinalStatus | dict | None to the serialized dict (UNGRADED default)."""
    if isinstance(fs, FinalStatus):
        return fs.to_dict()
    if isinstance(fs, dict) and fs.get('status'):
        return fs
    return FinalStatus(FinalDecisionStatus.UNGRADED, (),
                       'No gradeable Hero decision.').to_dict()


def final_status_pill_html(fs, include_reason=True, extra_class=''):
    """Emit the canonical status pill -- the SINGLE HTML producer for the system status, so no
    surface hand-writes a status string. `fs` may be a FinalStatus or its serialized dict.
    Distinct from .verdict-pill (verdict nuance) and .status-pill (the review-queue review state)."""
    d = status_payload(fs)
    status = d.get('status') or 'UNGRADED'
    label = d.get('label') or 'No decision'
    css = d.get('css') or 'ungraded'
    cls = 'final-status-pill fs-' + css + ((' ' + extra_class) if extra_class else '')
    sec = d.get('secondary') or []
    sec_attr = (" data-final-status-secondary='" + ','.join(sec) + "'") if sec else ''
    reason = ''
    if include_reason and d.get('secondary_labels'):
        reason = ("<span class='final-status-reason'>"
                  + ' &middot; '.join(_html.escape(x) for x in d['secondary_labels'])
                  + '</span>')
    # No per-pill title tooltip: the labels (Mistake/Cleared/Conditional/No decision) + colours are
    # self-explanatory, and a ~50-char tooltip on 800+ lazy-payload hands inflates the HTML through
    # base64. The full rationale stays in the typed dict (to_dict) for a future web frontend / legend.
    return (f"<span class='{cls}' data-final-status='{status}'{sec_attr}"
            f">{_html.escape(label)}</span>{reason}")


def status_data_attr(fs):
    """The bare data-final-status='X' attribute fragment for stamping onto a container element."""
    return f"data-final-status='{status_payload(fs).get('status') or 'UNGRADED'}'"


def verdict_pill_redundant(fs, verdict_pill_html):
    """True when a standalone verdict-nuance pill would merely REPEAT the canonical status pill -- its
    label equals the status label OR a secondary-reason label the status pill already shows. Lets a
    caller drop the duplicate (no doubled 'Mistake Mistake' / 'Cleared Justified Justified') while
    keeping genuinely-additive nuance (Punt / Correct / Standard / Pick). Pure."""
    if not verdict_pill_html:
        return False
    import re as _re
    m = _re.search(r"data-verdict='([^']*)'", verdict_pill_html)
    if not m:
        return False
    lbl = m.group(1).strip().lower()
    d = status_payload(fs)
    shown = {(d.get('label') or '').strip().lower()}
    shown |= {x.strip().lower() for x in (d.get('secondary_labels') or [])}
    if lbl in ('read-dep', 'read-dependent') and 'read-dependent' in shown:
        return True
    return lbl in shown
