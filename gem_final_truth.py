"""gem_final_truth.py -- the ONE canonical final-truth owner (v8.20 Wave 1A.2A).

ONE FinalTruthRecord per reviewed hand. Every coaching surface (KPI/stat cards, TL;DR/Summary,
Top Hands, Confirmed Mistakes, punt tables, Issue Explorer / Large-Loss labels, strategic-leak
tables, blindspot tables, Pokerbot Picks, action items, review queue, hand-detail verdict pill,
appendix hand cards -- HTML and Markdown) consumes the populations/records emitted here. No surface
re-derives a final coaching population. Raw detector nominations survive ONLY in the per-record
`nominations` provenance for QA/debug -- never as a final coaching population after an override.

Builds ON the existing canonical owners (does not compete with them):
  * gem_review_trust.resolve_canonical_verdict -- precedence (active-queue > analyst > auto > outcome);
  * gem_final_status -- the 5-state SYSTEM status (MISTAKE / CONDITIONAL / CLEARED / UNASSESSED /
    UNGRADED) + secondary reasons + the single status pill.

Why a finer class than FinalDecisionStatus: the status owner groups III.1 *punt* and III.2 *mistake*
both as MISTAKE (correct for the pill colour). The COUNTING surfaces need them DISTINCT and MUTUALLY
EXCLUSIVE, because the headline error math is `confirmed mistakes + punts = errors`. This owner assigns
exactly ONE FinalClass per hand (the analyst verdict overrides the raw nomination), so the populations
are disjoint by construction and the count math can never double-count a hand (the v8.20 W1A.1 BUG-2
class of defect becomes structurally impossible).

Pure / deterministic / typed (to_dict round-trips for a future web frontend).
"""
import html as _html
from enum import Enum
from dataclasses import dataclass, field


class FinalClass(Enum):
    """The ONE final poker classification per hand (mutually exclusive)."""
    CONFIRMED_MISTAKE = 'CONFIRMED_MISTAKE'   # III.2, or a detector CLEAR survivor the analyst did not clear
    PUNT = 'PUNT'                             # III.1, or an auto-detected punt the analyst did not override
    COOLER = 'COOLER'                         # I.7
    JUSTIFIED = 'JUSTIFIED'                   # III.5
    READ_DEPENDENT = 'READ_DEPENDENT'         # III.4 (and III.8/III.9 read-only picks)
    STANDARD = 'STANDARD'                     # III.0 / III.3 -- graded correct / standard line
    WELL_PLAYED = 'WELL_PLAYED'               # explicit positive / Pokerbot-Pick-eligible
    INSUFFICIENT = 'INSUFFICIENT'             # insufficient evidence to grade
    UNASSESSED = 'UNASSESSED'                 # a gradeable Hero decision, not individually reviewed
    UNGRADED = 'UNGRADED'                     # no gradeable Hero decision (walk / forced sub-blind / result-only)


# stable, USER-FACING labels -- never expose internal Roman taxonomy codes (V820-QA-034).
_CLASS_LABEL = {
    FinalClass.CONFIRMED_MISTAKE: 'Confirmed mistake',
    FinalClass.PUNT: 'Punt',
    FinalClass.COOLER: 'Cooler',
    FinalClass.JUSTIFIED: 'Justified',
    FinalClass.READ_DEPENDENT: 'Read-dependent',
    FinalClass.STANDARD: 'Standard / correct',
    FinalClass.WELL_PLAYED: 'Well played',
    FinalClass.INSUFFICIENT: 'Insufficient evidence',
    FinalClass.UNASSESSED: 'Not reviewed',
    FinalClass.UNGRADED: 'No decision',
}

# the two ERROR populations -- the only classes whose count feeds "confirmed + punts = errors".
_ERROR_CLASSES = (FinalClass.CONFIRMED_MISTAKE, FinalClass.PUNT)
# positive classes eligible (with the gate below) to be shown as a Pokerbot Pick.
_PICK_ELIGIBLE_CLASSES = (FinalClass.WELL_PLAYED, FinalClass.STANDARD)
# classes that may never simultaneously be a confirmed Pick.
_PICK_FORBIDDEN_CLASSES = (FinalClass.CONFIRMED_MISTAKE, FinalClass.PUNT,
                           FinalClass.INSUFFICIENT, FinalClass.READ_DEPENDENT)


def _norm(s):
    return (s or '').strip().lower()


def class_from_verdict(verdict):
    """Map ONE verdict string (coded 'III.2 Mistake' OR humanized 'Cooler') to a FinalClass, or None
    when it carries no class signal. Codes are authoritative (the canonical taxonomy). This is the
    SINGLE place a verdict string becomes a poker class -- per-hand surfaces call it instead of
    re-implementing III.* prefix matching."""
    v = _norm(verdict)
    if not v:
        return None
    if v.startswith('iii.2'):
        return FinalClass.CONFIRMED_MISTAKE
    if v.startswith('iii.1'):
        return FinalClass.PUNT
    if v.startswith('i.7') or 'cooler' in v:
        return FinalClass.COOLER
    if v.startswith('iii.5') or 'justified' in v:
        return FinalClass.JUSTIFIED
    if v.startswith('iii.4') or 'read-dependent' in v or 'read dependent' in v or 'read-dep' in v:
        return FinalClass.READ_DEPENDENT
    if v.startswith(('iii.8', 'iii.9')) or 'well played' in v or 'well-played' in v or 'pick' in v:
        return FinalClass.WELL_PLAYED
    if v.startswith(('iii.0', 'iii.3')) or 'standard' in v or 'correct' in v or 'cleared' in v:
        return FinalClass.STANDARD
    if 'insufficient' in v or 'unclear' in v:
        return FinalClass.INSUFFICIENT
    if 'mistake' in v:
        return FinalClass.CONFIRMED_MISTAKE
    if 'punt' in v:
        return FinalClass.PUNT
    return None


@dataclass(frozen=True)
class FinalTruthRecord:
    """One hand's canonical final truth. Immutable / typed. Inclusion flags are DERIVED from
    `final_class` (+ the Pick gate) -- never set independently -- so they cannot contradict the class."""
    hand_id: str
    final_class: FinalClass
    decision_id: str = ''            # '' => unresolved decision node (Phase B owns the snapshot)
    workflow_state: str = 'AUTO_ONLY'   # CLEARED / REVIEWED / PENDING_USER / OPTIONAL / AUTO_ONLY (NOT a poker class)
    severity: str = ''
    confidence_state: str = ''       # INSUFFICIENT / TRACKING / PROVISIONAL / ACTIONABLE (Phase D owner)
    source: str = 'auto'             # analyst / auto / detector / outcome
    override: bool = False           # analyst verdict replaced the raw nomination
    nominations: tuple = ()          # original detector/auto nominations (QA/debug provenance ONLY)
    verdict: str = ''                # the raw canonical verdict string (debug; codes allowed here)
    label: str = ''                  # stable user-facing label (no Roman codes)
    terminal_reason: str = ''

    # ---- inclusion flags (derived; one class -> at most one error population) ----
    @property
    def is_confirmed_mistake(self):
        return self.final_class is FinalClass.CONFIRMED_MISTAKE

    @property
    def is_punt(self):
        return self.final_class is FinalClass.PUNT

    @property
    def is_cooler(self):
        return self.final_class is FinalClass.COOLER

    @property
    def is_justified(self):
        return self.final_class is FinalClass.JUSTIFIED

    @property
    def is_read_dependent(self):
        return self.final_class is FinalClass.READ_DEPENDENT

    @property
    def is_insufficient(self):
        return self.final_class is FinalClass.INSUFFICIENT

    @property
    def is_error(self):
        return self.final_class in _ERROR_CLASSES

    def to_dict(self):
        return {
            'hand_id': self.hand_id,
            'final_class': self.final_class.value,
            'label': self.label or _CLASS_LABEL[self.final_class],
            'decision_id': self.decision_id,
            'workflow_state': self.workflow_state,
            'severity': self.severity,
            'confidence_state': self.confidence_state,
            'source': self.source,
            'override': self.override,
            'nominations': list(self.nominations),
            'verdict': self.verdict,
            'terminal_reason': self.terminal_reason,
            'flags': {
                'confirmed_mistake': self.is_confirmed_mistake,
                'punt': self.is_punt,
                'cooler': self.is_cooler,
                'justified': self.is_justified,
                'read_dependent': self.is_read_dependent,
                'insufficient': self.is_insufficient,
                'error': self.is_error,
            },
        }


def pick_eligible(record):
    """A hand may be shown as a confirmed Pokerbot Pick ONLY when its final class is positive
    (well-played / standard) -- never when it is a mistake, punt, insufficient or read-dependent.
    A conditional/insufficient hand is a candidate/learning example, not a confirmed Pick (V820-QA-005)."""
    if record is None:
        return False
    return record.final_class in _PICK_ELIGIBLE_CLASSES


# --------------------------------------------------------------------------- #
# the build -- ONE pass that assigns exactly one class per hand                #
# --------------------------------------------------------------------------- #

def _detector_clear_survivors(raw_mistakes, needs_keys, auto_keys):
    """Detector mistake ids at CLEAR confidence that are not in the needs-review / auto-corrected
    buckets. Mirrors the long-standing survivor rule in _refresh_discipline_tier -- the ONE place it
    now lives."""
    out = set()
    for m in raw_mistakes or []:
        key = (m.get('id'), m.get('type'))
        if key in needs_keys or key in auto_keys:
            continue
        if (m.get('confidence', '') or '').upper() == 'CLEAR':
            out.add(m.get('id'))
    return out


def build_final_truth(rd, stats, hands, *, analyst_commentary=None):
    """Build the canonical final-truth record set for the session. Returns a dict:

        {
          'records':        {hand_id: record.to_dict()},
          'populations':    {class_value: [hand_id, ...]},   # disjoint, sorted
          'counts':         {class_value: int},
          'reconciliation': {contradictions, orphans, duplicates, by_class, error_total, ...},
        }

    `analyst_commentary` overrides rd['analyst_commentary'] -- the prepare-time discipline builder runs
    BEFORE the analyst file is bound to rd and must pass its file-loaded commentary in explicitly.
    Pure on its inputs; also stamps rd['final_truth'] for surfaces to read."""
    ac = analyst_commentary if analyst_commentary is not None else (rd.get('analyst_commentary') or {})
    raw_mistakes = stats.get('mistakes', []) or []
    raw_punts = (stats.get('punts', {}) or {}).get('hands', []) or []
    rev = rd.get('reviewed_mistakes', {}) or {}
    needs_keys = {(m.get('id'), m.get('type')) for m in (rev.get('needs_review') or [])}
    auto_keys = {(m.get('id'), m.get('type')) for m in (rev.get('auto_corrected') or [])}

    auto_punt_ids = {p.get('id') for p in raw_punts}
    detector_mistake_ids = {m.get('id') for m in raw_mistakes}
    clear_survivor_ids = _detector_clear_survivors(raw_mistakes, needs_keys, auto_keys)

    # the universe of hands that carry ANY final signal.
    universe = set()
    universe |= {hid for hid in ac.keys() if not str(hid).startswith('__')}
    universe |= auto_punt_ids
    universe |= detector_mistake_ids
    universe.discard(None)

    records = {}
    for hid in sorted(universe, key=lambda x: str(x)):
        cmt = ac.get(hid)
        cmt = cmt if isinstance(cmt, dict) else None
        verdict = (cmt.get('verdict', '') or '') if cmt else ''
        analyst_class = class_from_verdict(verdict)

        noms = []
        if hid in detector_mistake_ids:
            noms.append('detector_mistake')
        if hid in auto_punt_ids:
            noms.append('auto_punt')

        if analyst_class is not None:
            # ANALYST OVERRIDE FINALITY: the analyst verdict fully replaces the raw nomination.
            final_class = analyst_class
            source = 'analyst'
            override = bool(noms)   # overrode a raw nomination iff there was one
        elif hid in clear_survivor_ids:
            # a detector CLEAR-confidence mistake the analyst did not clear/reclassify.
            final_class = FinalClass.CONFIRMED_MISTAKE
            source = 'detector'
            override = False
        elif hid in auto_punt_ids:
            final_class = FinalClass.PUNT
            source = 'auto'
            override = False
        elif cmt is not None:
            # reviewed but no class signal in the verdict -> not an error.
            final_class = FinalClass.UNASSESSED
            source = 'analyst'
            override = False
        else:
            # a detector mistake at non-CLEAR confidence, unreviewed -> not yet a confirmed error.
            final_class = FinalClass.UNASSESSED
            source = 'detector'
            override = False

        terminal = '' if final_class not in (FinalClass.UNASSESSED, FinalClass.UNGRADED) \
            else 'no individual review' if final_class is FinalClass.UNASSESSED else 'no gradeable decision'

        records[hid] = FinalTruthRecord(
            hand_id=str(hid),
            final_class=final_class,
            workflow_state='REVIEWED' if cmt is not None else 'AUTO_ONLY',
            source=source,
            override=override,
            nominations=tuple(noms),
            verdict=verdict,
            label=_CLASS_LABEL[final_class],
            terminal_reason=terminal,
        )

    # populations -- disjoint by construction (one class per hand).
    populations = {c.value: [] for c in FinalClass}
    for hid, rec in records.items():
        populations[rec.final_class.value].append(hid)
    for k in populations:
        populations[k] = sorted(populations[k], key=lambda x: str(x))

    counts = {k: len(v) for k, v in populations.items()}
    error_total = counts[FinalClass.CONFIRMED_MISTAKE.value] + counts[FinalClass.PUNT.value]
    # detector-only CLEAR survivors that stayed confirmed mistakes -- the discipline-ladder rate input
    # (NOT the canonical confirmed count, which also includes analyst-confirmed III.2). Single-sourced.
    detector_clear_survivors = sum(1 for r in records.values()
                                   if r.is_confirmed_mistake and r.source == 'detector')

    # reconciliation: with one class per hand, contradictions/orphans/duplicates are 0 by design;
    # we verify it rather than assume it (a regression in the build would surface here, not in a report).
    contradictions = 0
    for hid, rec in records.items():
        flags = [rec.is_confirmed_mistake, rec.is_punt, rec.is_cooler,
                 rec.is_justified, rec.is_read_dependent, rec.is_insufficient]
        if sum(1 for f in flags if f) > 1:
            contradictions += 1
    orphans = sum(1 for r in records.values()
                  if r.final_class is FinalClass.UNASSESSED and not r.nominations and r.source == 'detector')
    # duplicate final owners: a hand id present in more than one population.
    seen, dupes = set(), 0
    for k, ids in populations.items():
        for hid in ids:
            if hid in seen:
                dupes += 1
            seen.add(hid)

    out = {
        'records': {hid: rec.to_dict() for hid, rec in records.items()},
        'populations': populations,
        'counts': counts,
        'reconciliation': {
            'contradictions': contradictions,
            'orphans': orphans,
            'duplicates': dupes,
            'error_total': error_total,
            'detector_clear_survivors': detector_clear_survivors,
            'confirmed_mistakes': counts[FinalClass.CONFIRMED_MISTAKE.value],
            'punts': counts[FinalClass.PUNT.value],
            'coolers': counts[FinalClass.COOLER.value],
            'reviewed_hands': sum(1 for r in records.values() if r.workflow_state == 'REVIEWED'),
            'by_class': {k: counts[k] for k in counts if counts[k]},
        },
    }
    rd['final_truth'] = out
    return out


# --------------------------------------------------------------------------- #
# thin accessors -- surfaces call these (transitional aliases delegate here)   #
# --------------------------------------------------------------------------- #

def populations(rd):
    ft = rd.get('final_truth')
    return (ft or {}).get('populations', {})


def population_ids(rd, final_class):
    """Sorted hand-ids for ONE FinalClass from the canonical owner (empty if not built)."""
    c = final_class.value if isinstance(final_class, FinalClass) else str(final_class)
    return list(populations(rd).get(c, []))


def count(rd, final_class):
    c = final_class.value if isinstance(final_class, FinalClass) else str(final_class)
    return (rd.get('final_truth') or {}).get('counts', {}).get(c, 0)


def confirmed_mistakes_count(rd):
    return count(rd, FinalClass.CONFIRMED_MISTAKE)


def punts_count(rd):
    return count(rd, FinalClass.PUNT)


def record_for(rd, hand_id):
    return (rd.get('final_truth') or {}).get('records', {}).get(hand_id)


def escape_attr(value):
    """Correct HTML escaping for a dynamic data-attribute payload -- apostrophe, quote, ampersand and
    angle brackets (V820-QA-030). Use for every data-* attribute built from session data."""
    return _html.escape('' if value is None else str(value), quote=True).replace("'", '&#x27;')


# --------------------------------------------------------------------------- #
# rendered-surface reconciliation -- surfaces register the IDs they ACTUALLY   #
# emit, so the artifact compares emitted IDs to the canonical populations.     #
# --------------------------------------------------------------------------- #

def register_rendered(rd, surface, hand_ids, final_class=None):
    """A coaching surface calls this with the hand-ids it ACTUALLY renders (a row table, a pill list,
    a Pick grid). The reconciliation then compares emitted IDs to the owner's canonical population for
    that class -- catching a row that the count owner excluded but a surface still drew, or vice-versa.
    Idempotent per (surface): the last registration for a surface wins (renderers may re-emit)."""
    store = rd.setdefault('_rendered_truth', {})
    fc = final_class.value if isinstance(final_class, FinalClass) else final_class
    store[surface] = {'ids': [str(h) for h in hand_ids if h is not None], 'final_class': fc}
    return store[surface]


def reconcile_rendered(rd):
    """Compare every registered surface's emitted IDs to the owner's canonical population for its class.
    Returns per-surface {rendered, expected, missing, extra, duplicates, final_class} plus a roll-up.
    A surface with no declared final_class is reported (rendered/duplicates) but not diffed against a
    population (e.g. a mixed table)."""
    pops = populations(rd)
    rendered = rd.get('_rendered_truth', {}) or {}
    surfaces = {}
    total_missing = total_extra = total_dupes = 0
    for name, rec in rendered.items():
        ids = rec.get('ids', [])
        fc = rec.get('final_class')
        dupes = sorted({x for x in ids if ids.count(x) > 1})
        total_dupes += len(dupes)
        entry = {'rendered_count': len(ids), 'duplicates': dupes, 'final_class': fc}
        if fc and fc in pops:
            expected = set(pops.get(fc, []))
            got = set(ids)
            missing = sorted(expected - got)
            extra = sorted(got - expected)
            total_missing += len(missing)
            total_extra += len(extra)
            entry.update({'expected_count': len(expected), 'missing': missing, 'extra': extra})
        surfaces[name] = entry
    return {
        'surfaces': surfaces,
        'total_missing': total_missing,
        'total_extra': total_extra,
        'total_duplicates': total_dupes,
        'rendered_reconciles': bool(total_missing == 0 and total_extra == 0 and total_dupes == 0),
    }
