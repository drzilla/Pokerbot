"""GEM v8.20 Wave 1A — the ONE canonical material-loss review population.

Today the material-loss population is computed in three independent passes (build_loss_screens id-lists,
the candidate loss-screen ctx records, and the completeness critical/significant sets re-derived from
candidate buckets). They agree only because they all read the same h['net_bb'] and the same bucket
constants. This module is the single owner of the per-hand MATERIAL-LOSS RECORD that every consumer
(biggest-loss screen, postflop-loss screen, analyst worklist, finality/completeness, report summary,
hand-detail drilldown) reads — so a materially important loss can never silently disappear.

It is keyed on the canonical screen-id owner (gem_coverage_builder.build_loss_screens), which stays the
single producer of the screened id-set (and the ANA-001 fail-loud schema). This module does NOT
re-derive the screen; it enriches it into records and proves no material id is dropped.

Pure + testable: no rendering, no file IO. Every materially important loss ends in EXACTLY ONE visible
state (the eight CLASSIFICATIONS below) — never silently absent.
"""

# ── materiality (single source) ──────────────────────────────────────────────
# The postflop materiality threshold lives in gem_coverage_builder.POSTFLOP_LOSS_SCREEN_BB (-15.0); the
# biggest-loss screen has no magnitude floor (any per-tournament net loss qualifies). This module reads
# the SCREENED population, so it inherits that one definition rather than inventing a second threshold.
SMALL_TOURNAMENT_MIN_HANDS = 10   # stack_trajectories gate (gem_analyzer): <this contributes no
#                                   biggest_loss_id; surfaced as an explicit coverage flag, never silent.

# ── the eight terminal classifications (product contract) ────────────────────
CONFIRMED_MISTAKE = 'confirmed_mistake'
PUNT = 'punt'
JUSTIFIED = 'justified'              # correctly played / justified / cleared
READ_DEPENDENT = 'read_dependent'
COOLER = 'cooler'
VARIANCE = 'variance'
INSUFFICIENT = 'insufficient'
UNGRADED = 'ungraded'               # explicitly ungraded and awaiting analyst
CLASSIFICATIONS = (CONFIRMED_MISTAKE, PUNT, JUSTIFIED, READ_DEPENDENT, COOLER,
                   VARIANCE, INSUFFICIENT, UNGRADED)

# detector buckets a material hand may ALSO be nominated by (for nominating_detector_families)
_DETECTOR_BUCKETS = ('mistakes', 'punts', 'coolers', 'bust_audit', 'iii4_screening',
                     'read_dependent_screening', 'bestplay_screening', 'big_river_calldowns',
                     'sizing_leaks')


def classify_verdict(verdict):
    """Map an analyst verdict string (e.g. 'III.2 Mistake', 'III.5 Justified', 'I.7 Cooler',
    'variance', 'insufficient evidence') to ONE of the eight terminal classifications. An empty/None
    verdict is UNGRADED (explicitly awaiting analyst) — never silently dropped."""
    v = (verdict or '').strip().lower()
    if not v:
        return UNGRADED
    # explicit non-coded states first
    if 'variance' in v:
        return VARIANCE
    if 'insufficient' in v or 'no_clear_lesson' in v or 'no clear lesson' in v:
        return INSUFFICIENT
    if 'cooler' in v or v.startswith('i.7'):
        return COOLER
    if 'read-dependent' in v or 'read dependent' in v or v.startswith('iii.4') \
            or v.startswith('iii.8') or v.startswith('iii.9'):
        return READ_DEPENDENT
    if v.startswith('iii.1') or 'punt' in v:
        return PUNT
    if v.startswith('iii.2') or ('mistake' in v and 'no ' not in v):
        return CONFIRMED_MISTAKE
    # III.0 / III.3 cleared / III.5 justified / best-play / correct
    if v.startswith('iii.0') or v.startswith('iii.3') or v.startswith('iii.5') \
            or 'justified' in v or 'cleared' in v or 'correct' in v or 'best play' in v:
        return JUSTIFIED
    # a verdict we cannot map is treated as graded-but-unclear (INSUFFICIENT), never UNGRADED-silent
    return INSUFFICIENT


def build_material_loss_population(loss_screens, hands, *, candidates=None,
                                   analyst_commentary=None, blindspot_ids=None,
                                   stack_trajectories=None, variance_ids=None):
    """The ONE canonical owner. Returns {hid: record} for every materially important loss.

    loss_screens     : output of gem_coverage_builder.build_loss_screens (the screen-id owner).
    hands            : the session hands (for net_bb / street / pf_allin).
    candidates       : the analyst-candidate buckets (for nominating_detector_families).
    analyst_commentary: {hid: {verdict, street, ...}} (for analyst_status + final_classification).
    blindspot_ids    : ids in the blindspot sample (for blindspot_only).
    Each record retains: id, net_bb (magnitude), entry_reason, screen_reason, reached_flop, pf_allin,
    street, nominating_detector_families, blindspot_only, analyst_status, final_classification.
    """
    hands_by_id = {h.get('id'): h for h in (hands or []) if h.get('id')}
    _ac = analyst_commentary or {}
    _bs = set(blindspot_ids or [])
    _var = set(variance_ids or [])
    # which detector buckets each hand appears in (other than the loss screens themselves)
    fam_by_id = {}
    for bk in _DETECTOR_BUCKETS:
        for c in ((candidates or {}).get(bk, []) or []):
            cid = c.get('id') if isinstance(c, dict) else c
            if cid:
                fam_by_id.setdefault(cid, set()).add(bk)

    def _street_of(h):
        ks = h.get('key_decision_street') or h.get('key_street')
        if ks:
            return str(ks)
        b = h.get('board') or []
        n = len(b) if isinstance(b, (list, tuple)) else len(str(b).replace(' ', '')) // 2
        return 'river' if n >= 5 else 'turn' if n == 4 else 'flop' if n >= 3 else 'preflop'

    pop = {}
    for entry_reason, screen_text in (('biggest_loss', 'Per-tournament biggest loss; must clear or classify.'),
                                      ('postflop_loss', None)):
        bucket = 'biggest_loss_screen' if entry_reason == 'biggest_loss' else 'postflop_loss_screen'
        for hid in (loss_screens or {}).get(bucket, []) or []:
            if hid in pop:                       # a hand is screened into at most one bucket
                continue
            h = hands_by_id.get(hid, {}) or {}
            net = h.get('net_bb')
            sr = screen_text or ('Postflop loss %.0fBB; must clear or classify.' % (net or 0))
            verdict = (_ac.get(hid) or {}).get('verdict') if isinstance(_ac.get(hid), dict) else _ac.get(hid)
            reviewed = hid in _ac and not str(hid).startswith('__')
            # the ANALYST verdict is authoritative when present; the variance_outcomes heuristic only
            # pre-labels hands the analyst has not graded (so an explicit III.5 is never overridden).
            cls = (classify_verdict(verdict) if reviewed
                   else VARIANCE if hid in _var else UNGRADED)
            fams = sorted(fam_by_id.get(hid, set()))
            pop[hid] = {
                'id': hid,
                'net_bb': net,
                'entry_reason': entry_reason,
                'screen_reason': sr,
                'reached_flop': _reached_flop(h),
                'pf_allin': bool(h.get('pf_allin')),
                'street': _street_of(h),
                'nominating_detector_families': fams,
                'blindspot_only': (hid in _bs) and not fams,
                'analyst_status': 'reviewed' if reviewed else 'unreviewed',
                'final_classification': cls,
            }
    return pop


def _reached_flop(h):
    b = h.get('board') or []
    n = len(b) if isinstance(b, (list, tuple)) else len(str(b).replace(' ', '')) // 2
    return n >= 3 or bool(h.get('went_to_sd'))


def reenrich_material_loss(population, analyst_commentary=None, variance_ids=None):
    """Update analyst_status + final_classification IN PLACE from the live analyst_commentary (the
    population id-set never changes — only its review state does). Called at render time + on --quick,
    after the analyst file is loaded, so the same canonical owner reflects analyst verdicts. Returns
    the population."""
    _ac = analyst_commentary or {}
    _var = set(variance_ids or [])
    for hid, r in (population or {}).items():
        reviewed = hid in _ac and not str(hid).startswith('__')
        verdict = (_ac.get(hid) or {}).get('verdict') if isinstance(_ac.get(hid), dict) else _ac.get(hid)
        r['analyst_status'] = 'reviewed' if reviewed else 'unreviewed'
        r['final_classification'] = (classify_verdict(verdict) if reviewed
                                     else VARIANCE if hid in _var else UNGRADED)
    return population


def material_loss_summary(population):
    """Counts for the visible completeness surface. Every record is in exactly one classification, so
    the per-classification counts always sum to total (proven by T-W1A-ML tests)."""
    pop = population or {}
    by_cls = {c: 0 for c in CLASSIFICATIONS}
    by_cls_ids = {c: [] for c in CLASSIFICATIONS}
    reviewed = 0
    blindspot_only = []
    magnitude = 0.0
    for hid, r in pop.items():
        cls = r.get('final_classification', UNGRADED)
        by_cls[cls] += 1
        by_cls_ids[cls].append(hid)
        if r.get('analyst_status') == 'reviewed':
            reviewed += 1
        if r.get('blindspot_only'):
            blindspot_only.append(hid)
        try:
            magnitude += float(r.get('net_bb') or 0)
        except (TypeError, ValueError):
            pass
    total = len(pop)
    confirmed = by_cls[CONFIRMED_MISTAKE] + by_cls[PUNT]
    variance_coolers = by_cls[VARIANCE] + by_cls[COOLER]
    cleared = by_cls[JUSTIFIED] + by_cls[READ_DEPENDENT]
    return {
        'total': total,
        'reviewed': reviewed,
        'ungraded': by_cls[UNGRADED],
        'confirmed_mistakes_punts': confirmed,
        'variance_coolers': variance_coolers,
        'cleared': cleared,
        'insufficient': by_cls[INSUFFICIENT],
        'blindspot_only_discovered': len(blindspot_only),
        'blindspot_only_ids': sorted(blindspot_only),
        'magnitude_bb': round(magnitude, 1),
        'by_classification': by_cls,
        'by_classification_ids': {c: sorted(v) for c, v in by_cls_ids.items()},
        'all_ids': sorted(pop.keys()),
    }


def assert_no_silent_drop(population, surfaced_ids):
    """Fail-loud guarantee (the product contract): every material-loss hand must reach a visible,
    classified surface. `surfaced_ids` is the set of ids that actually appear on the rendered
    material-loss surface (each classified or explicitly UNGRADED). Raises if any material hand is
    silently absent — i.e. dropped by deduplication, auto-clear, analyst omission, an alternate report
    path, or a non-matching detector family. Returns the population id-set on success."""
    pop_ids = set(population or {})
    missing = sorted(pop_ids - set(surfaced_ids or ()))
    if missing:
        raise ValueError(
            'MAT-001: %d material-loss hand(s) silently disappeared from the visible surface: %s '
            '(every material loss must end in one of %s)' % (len(missing), missing[:8], CLASSIFICATIONS))
    return pop_ids
