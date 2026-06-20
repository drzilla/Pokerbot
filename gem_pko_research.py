"""
gem_pko_research.py — v8.12.0 PKO research bucket layer
=========================================================
Maps BB-defense decisions in bounty formats onto measured GTOWizard
ICMPKO-vs-Classic aggregate deltas and classifies them conservatively.

Verdict-integrity rule (release contract):
  Classic / exact chart evidence can create mistakes.
  PKO aggregate research can create Review.
  Aggregate-only items NEVER enter Top Punts, BB/100 loss estimates,
  confirmed-mistake counts, or copy-notes mistake export.

Schema notes (v2, external review):
  - `is_opportunity` / `hero_continued` / `hero_action` are COUNT DIMENSIONS.
  - `classification` ∈ {Good, Too wide, Missed, Review, Baseline, Out of scope}
    and never contains Opp/Actual.
  - `can_collect_bounty` (Hero can eliminate Villain on the winning branch;
    equal stacks collectible) is SEPARATE from the research `coverage_bucket`
    (heuristic 1.10x / 0.90x stack-ratio buckets — display + mapping only).
  - action_mix "n/r" buckets classify Classic-OK continues as Baseline
    (guardrails Option A): we can say Classic-good, not PKO-good.
  - Classic evidence source priority: exact chart membership (the BB_DEF_*
    deviations ARE chart membership) over detector heuristics. The PKO layer
    never resolves Classic-source disagreement.

Deltas: measured buckets carry the PKO3 v3 panel-validated extraction
(2026-06-12, CSS-panel hybrid, every block revisit-verified at 0.0pp
drift). One preset per spot so delta_range_pp is [point, point] until the
P2 multi-stack-set sweep widens it; delta_bucket grades on the range
FLOOR. Rows the v3 panel could not reach (no preset) keep their v1-era
figures DEMOTED to directional confidence with action_mix withdrawn --
they classify conservatively (Baseline/Review) until measured.
HEADLINE v3 FINDING: the added PKO defend region is FLAT-CALL dominated
in every measured multiway/wide-opener spot; the v1 'squeeze-jam' story
was an artifact-era read and is retired.
"""

_CONF_FULL = 'aggregate_gtow_supported'
_CONF_DIR = 'directional_aggregate'

# Delta-bucket grading from the RANGE FLOOR (validation-run rule)
def _grade(floor_pp):
    if floor_pp >= 25: return 'Very high'
    if floor_pp >= 10: return 'High'
    if floor_pp >= 7:  return 'Medium'
    return 'Low'


PKO_RESEARCH_BUCKETS = {
    'bb_vs_btn_hu_short_covered': {
        'classic_defend_pct': 68.2,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs BTN open',
        'depth_bucket': '<=20bb', 'players': 'HU', 'coverage': 'Hero covered',
        'pko_delta_pp': 2.0, 'delta_range_pp': [2.0, 2.0],
        'action_mix': ('near-Classic: added region +2.0pp tilts to small '
                       'raise/jam (calls -1.4 / raise +1.8 / allin +1.6pp)'),
        'jam_heavy': False, 'confidence': _CONF_FULL,
        'teaching_note': ('Covered HU short BB defense: the bounty effect '
                          'nearly vanishes when Hero cannot collect '
                          '(PKO 70.2% vs Classic 68.2% defend).'),
        'source': 'PKO3 v3 panel-validated 2026-06-12 (revisit 0.0pp) - MTTGeneral_ICMPKO8m1000PTBUBBLE152PT '
                  'F-F-F-F-F-R2-F @ BB18.1 vs BTN26.1 (eff ~17bb)',
        'gtow_link_type': 'exact'},
    'bb_vs_btn_hu_short_covering': {
        'classic_defend_pct': None,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs BTN open',
        'depth_bucket': '<=20bb', 'players': 'HU', 'coverage': 'Hero covers',
        'pko_delta_pp': 14.6, 'delta_range_pp': [2.8, 14.6],
        'action_mix': 'n/r', 'jam_heavy': None, 'confidence': _CONF_DIR,
        'teaching_note': ('Covering HU short: v1-era figure NOT re-validated '
                          'in PKO3 (no short-covering preset in the v3 '
                          'panel). The measured mid-depth covering row came '
                          'in at -1.0pp, so treat the +14.6 headline as '
                          'directional only.'),
        'source': 'MTTGeneral_ICMPKO8m1000PTBUBBLE152PT F-F-F-F-F-R2-F',
        'gtow_link_type': 'exact'},
    'bb_vs_btn_hu_30bb_equal': {
        'classic_defend_pct': 86.9,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs BTN open',
        'depth_bucket': '~30bb', 'players': 'HU', 'coverage': 'Equal',
        'pko_delta_pp': -1.0, 'delta_range_pp': [-1.0, -1.0],
        'action_mix': ('PKO slightly tighter overall (-1.0pp); composition '
                       'shifts ~4-5pp of flats into small raises'),
        'jam_heavy': False, 'confidence': _CONF_FULL,
        'teaching_note': ('Near-equal ~30bb HU: PKO effect is noise-level '
                          '(85.9% vs 86.9% defend); structure trades a few '
                          'pp of calls for raises.'),
        'source': 'PKO3 v3 panel-validated 2026-06-12 (revisit 0.0pp) - MTTGeneral_ICMPKO8m1000PTBUBBLE152PT '
                  'F-F-F-F-F-R2-F @ BB34.1 vs BTN32.1 (eff ~30bb)',
        'gtow_link_type': 'exact'},
    'bb_vs_btn_hu_50bb_covering': {
        'classic_defend_pct': 86.1,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs BTN open',
        'depth_bucket': '~50bb', 'players': 'HU', 'coverage': 'Hero covers',
        'pko_delta_pp': 2.5, 'delta_range_pp': [2.4, 2.5],
        'action_mix': 'n/r', 'jam_heavy': None, 'confidence': _CONF_DIR,
        'teaching_note': ('Deep covering HU: small positive PKO widening '
                          '(v1-era -- not re-validated in PKO3; no 50bb '
                          'preset in the v3 panel).'),
        'source': 'MTTGeneral_ICMPKO8m1000PTBUBBLE152PT F-F-F-F-F-R2-F',
        'gtow_link_type': 'exact'},
    'bb_vs_btn_hu_50bb_covered': {
        'classic_defend_pct': 66.4,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs BTN open',
        'depth_bucket': '~50bb', 'players': 'HU', 'coverage': 'Hero covered',
        'pko_delta_pp': -3.1, 'delta_range_pp': [-3.1, -0.9],
        'action_mix': 'n/r', 'jam_heavy': None, 'confidence': _CONF_DIR,
        'teaching_note': ('Deep covered HU: slightly TIGHTER than Classic '
                          '(v1-era -- not re-validated in PKO3; no 50bb '
                          'preset in the v3 panel).'),
        'source': 'MTTGeneral_ICMPKO8m1000PTBUBBLE152PT F-F-F-F-F-R2-F',
        'gtow_link_type': 'exact'},
    'bb_vs_btn_3way_short': {
        'classic_defend_pct': 38.6,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs BTN + caller',
        'depth_bucket': '<=20bb', 'players': '3-way', 'coverage': 'Mixed',
        'pko_delta_pp': 29.5, 'delta_range_pp': [29.5, 29.5],
        'action_mix': ('added region ~96% flat calls (calls +28.3 / raise '
                       '+0.5 / allin +0.7pp)'),
        'jam_heavy': False, 'confidence': _CONF_FULL,
        'teaching_note': ('Short 3-way is the largest measured PKO effect: '
                          'defend expands +29.5pp (68.1% vs 38.6%) and the '
                          'added region is overwhelmingly FLAT CALLS -- the '
                          'v1 squeeze-jam story is retired. Single preset; '
                          'P2 stack-set sweep pending.'),
        'source': 'PKO3 v3 panel-validated 2026-06-12 (revisit 0.0pp) - MTTGeneral_ICMPKO8m1000PTBUBBLE152PT '
                  'F-F-F-F-F-R2-C @ BB18.1, BTN26.1 opens, SB13.1 calls',
        'gtow_link_type': 'exact'},
    'bb_vs_btn_4way_short': {
        'classic_defend_pct': 18.3,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs open + 2 callers',
        'depth_bucket': '<=20bb', 'players': '4-way', 'coverage': 'Mixed',
        'pko_delta_pp': 10.0, 'delta_range_pp': [10.0, 10.0],
        'action_mix': ('added region call-dominated (calls +8.5 / allin '
                       '+1.8 / raise -0.3pp)'),
        'jam_heavy': False, 'confidence': _CONF_FULL,
        'teaching_note': ('Short 4-way: defend widens +10.0pp (28.3% vs '
                          '18.3%); the added region is call-dominated with '
                          'a small jam slice -- NOT jam-dominant (v1 claim '
                          'retired).'),
        'source': 'PKO3 v3 panel-validated 2026-06-12 (revisit 0.0pp) - MTTGeneral_ICMPKO8m1000PTBUBBLE152PT '
                  'F-F-F-F-R2-C-C @ BB18.1, two callers behind the open',
        'gtow_link_type': 'exact'},
    'bb_multiway_short_covered': {
        'classic_defend_pct': 52.8,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs open + caller',
        'depth_bucket': '<=20bb', 'players': '3-way', 'coverage': 'Hero covered',
        'pko_delta_pp': 11.5, 'delta_range_pp': [11.5, 11.5],
        'action_mix': ('added region ~92% flat calls (calls +10.6 / raise '
                       '+0.5 / allin +0.4pp)'),
        'jam_heavy': False, 'confidence': _CONF_FULL,
        'teaching_note': ('Short multiway covered: strongly positive '
                          '(+11.5pp, 64.3% vs 52.8%) -- multiway inverts '
                          'the HU covered pattern; added region is '
                          'flat-call dominated.'),
        'source': 'PKO3 v3 panel-validated 2026-06-12 (revisit 0.0pp) - MTTGeneral_ICMPKO8m1000PTBUBBLE152PT '
                  'F-F-F-F-R2-C-F @ BB18.1 covered by the field',
        'gtow_link_type': 'exact'},
    'bb_multiway_short_covering': {
        'classic_defend_pct': 11.8,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs open + caller',
        'depth_bucket': '<=20bb', 'players': '3-way', 'coverage': 'Hero covers',
        'pko_delta_pp': 7.6, 'delta_range_pp': [7.6, 7.6],
        'action_mix': ('added region call-dominated (calls +6.1 / allin '
                       '+0.9 / raise +0.6pp)'),
        'jam_heavy': False, 'confidence': _CONF_FULL,
        'teaching_note': ('Short multiway covering: positive widening '
                          '(+7.6pp, 19.4% vs 11.8% -- tight base: LJ open '
                          '+ HJ call); added region mostly flat calls.'),
        'source': 'PKO3 v3 panel-validated 2026-06-12 (revisit 0.0pp) - MTTGeneral_ICMPKO8m1000PTBUBBLE152PT '
                  'F-F-R2-C-F-F-F @ BB17eff covering LJ16/HJ14',
        'gtow_link_type': 'exact'},
    'bb_multiway_50bb': {
        'classic_defend_pct': None,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs open + caller',
        'depth_bucket': '~50bb', 'players': '3-way', 'coverage': 'Mixed',
        'pko_delta_pp': 2.8, 'delta_range_pp': [2.8, 2.8],
        'action_mix': 'n/r', 'jam_heavy': None, 'confidence': _CONF_DIR,
        'teaching_note': ('Deep multiway: PKO effect decays to small '
                          '(v1-era -- not re-validated in PKO3; no deep '
                          'multiway preset in the v3 panel).'),
        'source': 'MTTGeneral_ICMPKO8m1000PTBUBBLE152PT R2.1-C',
        'gtow_link_type': 'exact'},
    'bb_vs_co_hu_short': {
        'classic_defend_pct': 42.9,
        'family': 'BB_DEFEND_VS_OPEN', 'spot': 'BB vs CO open',
        'depth_bucket': '<=20bb', 'players': 'HU', 'coverage': 'Any',
        'pko_delta_pp': 11.1, 'delta_range_pp': [11.1, 11.1],
        'action_mix': ('added region pure flat calls (calls +12.1 / raise '
                       '+0.9 / allin -1.9pp -- jam share DROPS)'),
        'jam_heavy': False, 'confidence': _CONF_FULL,
        'teaching_note': ('BB vs CO open short: +11.1pp (54.0% vs 42.9%), '
                          'LARGER than vs BTN -- wider-opener PKO pressure '
                          'confirmed; v3 independently reproduced the v1 '
                          'surprise. All-in share actually falls.'),
        'source': 'PKO3 v3 panel-validated 2026-06-12 (revisit 0.0pp) - MTTGeneral_ICMPKO8m1000PTBUBBLE152PT '
                  'F-F-F-F-R2-F-F @ BB18.1 vs CO22.1',
        'gtow_link_type': 'exact'},
}

# Annotate derived grade once at import
for _bk, _bv in PKO_RESEARCH_BUCKETS.items():
    _bv['delta_bucket'] = _grade(_bv['delta_range_pp'][0])

_OOS_NEXT_ACTION = {
    'out_of_scope_mystery':   'Review manually (bounty value/stage unknown)',
    'out_of_scope_pushfold':  'FT push/fold PKO charts extracted — ingest v8.12.1+',
    'out_of_scope_deep':      'No research bucket >60bb',
    'out_of_scope_5way':      'No research bucket for 5+ way',
    'out_of_scope_sb':        'Await corrected SBD2 ingest (v8.13.x)',
    'out_of_scope_sb_opener': ('SB-open defense is a different tree — no '
                               'aggregate measured; never borrows BTN data'),
    'out_of_scope_position':  'Hero not BB — future extraction',
    'out_of_scope_no_open':   'Not a single-open defense tree',
    'review_band_edge':       'Depth between measured buckets — drill nearest',
    'allin_family':           'Evaluated in the All-In / Bounty Capture audit',
}


def can_collect_bounty(hero_stack, villain_stack):
    """Hero can eliminate Villain on the winning branch. Equal stacks are
    collectible (Villain busts when Hero wins outright). Split-pot branches
    are not captures — callers must not apply discounts off split equity."""
    try:
        return float(hero_stack or 0) >= float(villain_stack or 0) > 0
    except Exception:
        return False


def coverage_bucket(hero_stack, opener_stack):
    """Research-bucketing heuristic (1.10x / 0.90x). Display wording only —
    never gates live bounty math (that is can_collect_bounty's job)."""
    try:
        h, o = float(hero_stack or 0), float(opener_stack or 0)
        if h <= 0 or o <= 0:
            return 'Unknown'
        if h > o * 1.10: return 'Hero covers'
        if h < o * 0.90: return 'Hero covered'
        return 'Equal'
    except Exception:
        return 'Unknown'


def depth_band(eff_bb):
    """Hard band-edge routing (no snapping): returns (bucket|None, band_edge,
    oos_reason|None)."""
    try:
        e = float(eff_bb or 0)
    except Exception:
        return None, False, 'out_of_scope_deep'
    if e < 12.0:  return None, False, 'out_of_scope_pushfold'
    if e <= 22.0: return '<=20bb', False, None
    if e < 25.0:  return '<=20bb', True, None       # band edge -> Review cap
    if e <= 38.0: return '~30bb', False, None
    if e < 40.0:  return '~30bb', True, None        # band edge -> Review cap
    if e <= 60.0: return '~50bb', False, None
    return None, False, 'out_of_scope_deep'


def _pko_sentence(s):
    """Normalize a fragment into one concrete sentence (capital + period)."""
    s = (s or '').strip()
    if not s:
        return ''
    if s[-1] not in '.!?':
        s += '.'
    return s[0].upper() + s[1:]


def reconcile_pko_trust(*, coverage_bucket=None, can_collect_bounty=None,
                        players=2, coverage_label='', bounty_value_bb=None,
                        bounty_usd=None, discount_pp=0.0,
                        chip_threshold_pct=None, pko_threshold_pct=None,
                        overjam_bb=None, caveat=''):
    """Slice E — single PKO trust reconciliation. PURE.

    Collapses the already-stamped cover / collectibility / bounty facts into ONE
    compact, concrete "trust line", and flags any internal contradiction so the
    report never shows a bounty conclusion that fights its own math. Invents no
    stacks or dollar values — it only re-states and cross-checks inputs.

    Returns a dict: trust_line, cover_state, collectible, multiway,
    discount_applies, contradiction(+reason), suppress_overclaim,
    bounty_display, threshold_line.
    """
    cb = (coverage_bucket or '').strip()
    cl = (coverage_label or '')
    cll = cl.lower()
    multiway = int(players or 2) > 2
    collectible = can_collect_bounty  # may be True / False / None
    try:
        discount_pp = float(discount_pp or 0)
    except Exception:
        discount_pp = 0.0
    discount_applies = discount_pp > 0

    if cb == 'Hero covers':
        cover_state = 'hero_covers'
    elif cb == 'Hero covered':
        cover_state = 'hero_covered'
    elif cb in ('Equal', 'Near-equal', 'near-equal'):
        cover_state = 'equal'
    elif cb == 'Mixed':
        cover_state = 'mixed'
    else:
        cover_state = 'unknown'

    # ---- contradiction guard (the trust gate) ----
    contradiction, reason = False, ''
    if cover_state == 'hero_covers' and collectible is False:
        contradiction = True
        reason = 'Hero covers the villain but the bounty is marked not collectible.'
    elif discount_applies and collectible is False:
        contradiction = True
        reason = 'A bounty discount is applied although the bounty is not collectible.'
    elif cover_state == 'hero_covered' and discount_applies:
        contradiction = True
        reason = 'Villain covers Hero, so a bounty discount should not apply to Hero.'
    elif (discount_applies and chip_threshold_pct is not None
          and pko_threshold_pct is not None
          and pko_threshold_pct > chip_threshold_pct + 0.05):
        contradiction = True
        reason = ('PKO-adjusted threshold is higher than the chip-only threshold '
                  'despite a positive bounty discount.')

    # ---- over-claim suppression (multiway / ambiguous side-pot) ----
    multiway_full_cover = 'all bounties collectible' in cll
    suppress = bool(caveat) or cover_state in ('mixed', 'unknown')
    if multiway and not multiway_full_cover:
        suppress = True

    # ---- bounty display (never fabricates a $ figure) ----
    if bounty_value_bb and float(bounty_value_bb) > 0:
        if bounty_usd:
            bounty_display = '$%0.2f ≈ %.1fBB' % (float(bounty_usd),
                                                       float(bounty_value_bb))
        else:
            bounty_display = ('≈ %.1fBB (estimated bounty model)'
                              % float(bounty_value_bb))
    else:
        bounty_display = 'bounty value unavailable'

    # ---- threshold reconciliation line (only when a discount is in play) ----
    if (chip_threshold_pct is not None and pko_threshold_pct is not None
            and discount_applies):
        threshold_line = ('Chip-only call needs %.0f%%; PKO-adjusted needs ~%.0f%% '
                          '(−%.1fpp)' % (float(chip_threshold_pct),
                                              float(pko_threshold_pct), discount_pp))
    else:
        threshold_line = ''

    # ---- primary concrete sentence ----
    if contradiction:
        primary = 'PKO trust check failed — ' + reason
    elif cover_state == 'hero_covers':
        primary = cl or 'Hero covers the villain; bounty collectible'
    elif cover_state == 'hero_covered':
        primary = 'Villain covers Hero; bounty discount does not help Hero'
    elif cover_state == 'equal':
        primary = ('Near-equal stacks; bounty collectible only if Hero wins outright'
                   if collectible is not False else
                   'Near-equal stacks; opener has Hero just covered (bounty not collectible)')
    elif cover_state == 'mixed':
        primary = cl or ('Multiway: bounty impact uncertain because side-pot/cover '
                         'is ambiguous')
    else:
        primary = 'Cover/collectibility unresolved; treat the bounty effect as uncertain'

    extra = []
    if not contradiction:
        if (multiway and suppress and cover_state != 'hero_covered'
                and 'uncertain' not in primary.lower()):
            extra.append('multiway: bounty impact uncertain (side-pot/cover ambiguous)')
        if overjam_bb and float(overjam_bb) > 0:
            extra.append('side-pot ~%.1fBB Hero cannot win' % float(overjam_bb))
        if bounty_value_bb and float(bounty_value_bb) > 0:
            extra.append(bounty_display)
        elif caveat:
            extra.append('exact bounty unavailable — using estimate')
        if threshold_line:
            extra.append(threshold_line)
        elif (bounty_value_bb and float(bounty_value_bb) > 0 and not suppress
              and cover_state in ('hero_covers', 'equal')):
            # v8.14.1 hotfix (#2): a PKO context is present but no chip-vs-PKO
            # threshold was modelled (no discount at this depth) -> say so
            # explicitly; never imply a silent confident PKO adjustment.
            extra.append('chip-vs-PKO threshold not modelled at this depth')
        else:
            # v8.14.1 rev-4 (Blocker B): EVERY Bounty-trust strip must state its
            # threshold status. When no chip-vs-PKO threshold was modelled because
            # cover/collectibility is unresolved, multiway, or the villain covers
            # Hero, say so explicitly rather than leave the threshold silent.
            extra.append('chip-vs-PKO threshold unavailable — review manually')

    trust_line = ' '.join(_pko_sentence(p) for p in ([primary] + extra) if p)

    return {
        'trust_line': trust_line,
        'cover_state': cover_state,
        'collectible': collectible,
        'multiway': multiway,
        'discount_applies': discount_applies,
        'contradiction': contradiction,
        'contradiction_reason': reason,
        'suppress_overclaim': bool(suppress),
        'bounty_display': bounty_display,
        'threshold_line': threshold_line,
    }


def how_pko_changes_decision(*, cover_state, discount_applies, contradiction,
                             suppress_overclaim, multiway, classification,
                             chip_threshold_pct=None, pko_threshold_pct=None,
                             discount_pp=0.0, bounty_available=False):
    """v8.17 Epic B (B7) — the explicit "how the bounty changes the decision"
    coaching sentence. PURE; composes the SAME reconciled facts reconcile_pko_trust
    already produced (no recompute, invents no value). Returns '' when there is no
    honest claim to make (contradiction, no bounty, or villain covers Hero).

    Answers, in one sentence: does the bounty lower Hero's required equity, by how
    much, against whom, does it materially change the action, and is the incentive
    positive / negative / mixed (with multiway uncertainty stated honestly)."""
    if contradiction or not bounty_available:
        return ''
    try:
        chip = float(chip_threshold_pct) if chip_threshold_pct is not None else None
        pko = float(pko_threshold_pct) if pko_threshold_pct is not None else None
        dpp = float(discount_pp or 0)
    except Exception:
        chip, pko, dpp = None, None, 0.0
    # villain covers Hero: the bounty cannot be collected here -> not an incentive.
    if cover_state == 'hero_covered':
        return ('How the bounty changes it: it does not — the villain covers Hero, '
                'so Hero collects no bounty here. Price this as a chip decision.')
    # multiway / ambiguous side-pot: positive but not precisely priceable.
    if multiway or suppress_overclaim or cover_state in ('mixed', 'unknown'):
        return ('How the bounty changes it: it is a positive incentive to continue, '
                'but multiway/side-pot uncertainty means the exact discount is not '
                'reliable — treat it directionally, not as a fixed price cut.')
    # Hero covers / near-equal: a real, collectible bounty.
    _act = {'Good': 'and continuing is correct here',
            'Missed': 'and Hero passed up a continue the bounty made profitable',
            'Too wide': 'but the spot is still too wide to continue even with the bounty',
            }.get(classification, 'so weigh continuing')
    if discount_applies and chip is not None and pko is not None and dpp > 0:
        delta = max(0.0, chip - pko)
        mat = ('a meaningful shift' if delta >= 2.0
               else 'a small shift that rarely flips a borderline spot')
        return ('How the bounty changes it: chip-only need %.0f%% → '
                'bounty-adjusted ~%.0f%% (−%.1fpp). Hero covers the all-in '
                'caller, so the bounty lowers the call requirement by %.1fpp — '
                '%s, %s.' % (chip, pko, dpp, delta, mat, _act))
    # collectible but no discount modelled at this depth -> directional only.
    return ('How the bounty changes it: Hero covers the all-in caller, so the bounty '
            'is a positive incentive to continue, but no chip-vs-PKO discount was '
            'modelled at this depth — treat it directionally.')


# Confident PKO classifications that must NOT survive a trust contradiction.
_PKO_CONFIDENT_CLS = ('Good', 'Missed', 'Too wide')


def pko_trust_render(pko_ctx, *, bounty_usd=None, discount_pp=0.0,
                     chip_threshold_pct=None, pko_threshold_pct=None,
                     overjam_bb=None):
    """Render-path PKO trust (Slice E rev-2). PURE + fixture-testable.

    Re-reconciles the stamped pko_context COVER facts WITH the per-hand pot-odds
    facts (chip-only vs PKO-adjusted threshold, discount, overjam) so the on-page
    "Bounty trust:" strip proves the FULL reconciliation — not just cover/bounty.
    On a trust contradiction it DOWNGRADES a confident PKO classification to
    'Review' so the report never shows a confident PKO verdict that fights its
    own math. Returns the render payload incl. the exact markdown strip.
    """
    ctx = pko_ctx or {}
    tr = reconcile_pko_trust(
        coverage_bucket=ctx.get('coverage_bucket'),
        can_collect_bounty=ctx.get('can_collect_bounty'),
        players=ctx.get('players_if_hero_continues', 2),
        coverage_label=ctx.get('coverage_label', ''),
        bounty_value_bb=ctx.get('bounty_value_bb_est'),
        bounty_usd=bounty_usd, discount_pp=discount_pp,
        chip_threshold_pct=chip_threshold_pct, pko_threshold_pct=pko_threshold_pct,
        overjam_bb=overjam_bb)
    cls = ctx.get('classification', 'Review')
    # v8.14.1 hotfix (#3): a confident PKO classification must not survive EITHER
    # a trust contradiction OR a multiway/ambiguous over-claim suppression. When
    # the strip says "bounty impact uncertain", the pill cannot say "PKO Good" /
    # "PKO Too wide" — downgrade to Review.
    if cls in _PKO_CONFIDENT_CLS and (tr['contradiction'] or tr['suppress_overclaim']):
        cls_display, downgraded = 'Review', True
    else:
        cls_display, downgraded = cls, False
    prefix = '⚠️ ' if tr['contradiction'] else '\U0001F3AF '
    strip_md = (prefix + '**Bounty trust:** ' + tr['trust_line']) if tr['trust_line'] else ''
    # v8.17 Epic B (B7): the explicit "how the bounty changes the decision" coaching
    # sentence, built from the SAME reconciled facts (no recompute). Uses the
    # POST-downgrade display class so the coaching can never out-claim the verdict.
    _bounty_available = bool(ctx.get('bounty_value_bb_est')) or bounty_usd is not None
    how_changes_md = how_pko_changes_decision(
        cover_state=tr['cover_state'], discount_applies=tr['discount_applies'],
        contradiction=tr['contradiction'], suppress_overclaim=tr['suppress_overclaim'],
        multiway=tr['multiway'], classification=cls_display,
        chip_threshold_pct=chip_threshold_pct, pko_threshold_pct=pko_threshold_pct,
        discount_pp=discount_pp, bounty_available=_bounty_available)
    return {
        'trust_line': tr['trust_line'],
        'strip_md': strip_md,
        'prefix': prefix,
        'contradiction': tr['contradiction'],
        'contradiction_reason': tr['contradiction_reason'],
        'suppress_overclaim': tr['suppress_overclaim'],
        'classification_display': cls_display,
        'downgraded': downgraded,
        'cover_state': tr['cover_state'],
        'discount_applies': tr['discount_applies'],
        'multiway': tr['multiway'],
        'how_changes_md': how_changes_md,
    }


def _phase_full_conf(phase):
    return (phase or '') in ('bubble_zone', 'post_bubble')


def _preflop_facing(h):
    """Extract the BB-defense decision shape from the preflop ledger.
    Returns None when the hand is not Hero-BB-facing-one-open(+callers)."""
    if (h.get('position') or '') != 'BB':
        return None
    hero = h.get('hero', '')
    opener_pos, opener_stack, opener_allin = None, 0, False
    callers = []
    hero_act = None
    hero_stack = 0
    n_raises = 0
    for a in (h.get('action_ledger') or []):
        if a.get('street') != 'preflop':
            continue
        act = a.get('action', '')
        if act == 'posts':
            continue
        is_hero = (a.get('player') == hero)
        if is_hero:
            if act == 'folds':
                hero_act = 'fold'
            elif act == 'calls':
                hero_act = 'call'
            elif act in ('raises', 'bets'):
                hero_act = 'jam' if a.get('is_all_in') else 'raise'
            else:
                continue
            # Hero's OWN stack — coverage must never use the effective
            # stack (min with the opener), which collapses every
            # hero-covers spot into "Equal" (QA 2026-06-12: 69bb vs 18bb
            # rendered as "cannot collect").
            hero_stack = a.get('stack_bb', 0) or 0
            break  # first hero decision is the one we classify
        if act in ('raises', 'bets'):
            n_raises += 1
            if n_raises > 1:
                return None  # 3-bet pots are out of research scope
            opener_pos = a.get('position', '')
            opener_stack = a.get('stack_bb', 0) or 0
            opener_allin = bool(a.get('is_all_in'))
        elif act == 'calls' and n_raises == 1:
            callers.append({'pos': a.get('position', ''),
                            'stack': a.get('stack_bb', 0) or 0,
                            'allin': bool(a.get('is_all_in'))})
    if hero_act is None or n_raises != 1 or not opener_pos:
        return None
    return {'opener_pos': opener_pos, 'opener_stack': opener_stack,
            'opener_allin': opener_allin, 'callers': callers,
            'hero_act': hero_act, 'hero_stack': hero_stack,
            'players_if_continue': 2 + len(callers)}


def _map_bucket(depth, players, cov, opener_pos):
    """Bucket key + confidence downgrade reasons for the measured matrix."""
    reasons = []
    if players == 2:
        if depth == '<=20bb':
            if opener_pos == 'CO':
                return 'bb_vs_co_hu_short', reasons
            if opener_pos != 'BTN':
                reasons.append('opener_not_measured(%s)' % opener_pos)
            if cov == 'Hero covers':
                return 'bb_vs_btn_hu_short_covering', reasons
            if cov == 'Hero covered':
                return 'bb_vs_btn_hu_short_covered', reasons
            reasons.append('coverage_equal_mapped_to_covered')
            return 'bb_vs_btn_hu_short_covered', reasons
        if depth == '~30bb':
            if opener_pos not in ('BTN',):
                reasons.append('opener_not_measured(%s)' % opener_pos)
            return 'bb_vs_btn_hu_30bb_equal', reasons
        if depth == '~50bb':
            if opener_pos not in ('BTN',):
                reasons.append('opener_not_measured(%s)' % opener_pos)
            if cov == 'Hero covers':
                return 'bb_vs_btn_hu_50bb_covering', reasons
            return 'bb_vs_btn_hu_50bb_covered', reasons
    elif players == 3:
        if depth == '<=20bb':
            if cov == 'Hero covers':
                return 'bb_multiway_short_covering', reasons
            if cov == 'Hero covered':
                return 'bb_multiway_short_covered', reasons
            return 'bb_vs_btn_3way_short', reasons
        reasons.append('multiway_depth_mapped_to_50bb_row')
        return 'bb_multiway_50bb', reasons
    elif players == 4:
        if depth == '<=20bb':
            return 'bb_vs_btn_4way_short', reasons
        reasons.append('multiway_depth_mapped_to_50bb_row')
        return 'bb_multiway_50bb', reasons
    return None, reasons


def _classify(hero_continued, hero_act, classic_says_defend, classic_too_loose,
              bucket, band_edge, full_phase):
    """v2 classification table + guardrails. Returns (classification, fit)."""
    grade = bucket['delta_bucket'] if bucket else 'Low'
    jam_heavy = bucket.get('jam_heavy') if bucket else None
    mix_known = bool(bucket) and bucket.get('action_mix', 'n/r') != 'n/r'
    if hero_continued:
        if classic_too_loose:
            # Too wide requires the Classic detector; medium+ delta -> Review
            if grade in ('Medium', 'High', 'Very high'):
                return 'Review', 'unknown'
            return 'Too wide', 'unknown'
        # Classic OK (detector silent = OK in current system semantics)
        if not mix_known:
            return 'Baseline', 'unknown'   # guardrail: Classic-good, not PKO-good
        if jam_heavy and hero_act == 'call':
            if grade in ('High', 'Very high'):
                return 'Review', 'misaligned'
            return 'Baseline', 'misaligned'
        return 'Good', 'aligned'
    # Hero folded
    if classic_says_defend:
        return 'Missed', 'unknown'         # chart-backed; PKO upgrades priority
    if band_edge or not full_phase:
        # band edges / unresearched phases cap at Review regardless of grade
        if grade in ('High', 'Very high'):
            return 'Review', 'unknown'
        return 'Baseline', 'unknown'
    if grade in ('High', 'Very high'):
        return 'Review', 'unknown'
    return 'Baseline', 'unknown'


def _drill_cue(bucket, classification, seen):
    if not bucket:
        return ''
    rng = bucket['delta_range_pp']
    rng_txt = ('%+.1f to %+.1fpp' % (rng[0], rng[1])
               if rng[0] != rng[1] else '%+.1fpp' % rng[0])
    cue = 'Aggregate Δ %s' % rng_txt
    if bucket['confidence'] == _CONF_DIR:
        cue += ' (directional)'
    if classification in ('Review', 'Missed'):
        cue = 'Study focus — ' + cue
    if seen and seen <= 5:
        cue += ' · drill cue only, not a stable frequency read'
    return cue


def build_pko_context(h, classic_ids=None):
    """Build the pko_context fact for one hand. Pure function of hand fields
    + the Classic-evidence id sets. Never raises (caller wraps anyway)."""
    fmt = (h.get('format') or '').upper()
    ctx = {'enabled': False, 'is_bounty_format': fmt in
           ('BOUNTY', 'PKO', 'MYSTERY_BOUNTY')}
    if not ctx['is_bounty_format']:
        ctx['oos_reason'] = 'not_bounty_format'
        return ctx
    ctx['bounty_type'] = 'MYSTERY' if fmt == 'MYSTERY_BOUNTY' else 'PKO'
    if fmt == 'MYSTERY_BOUNTY':
        ctx['oos_reason'] = 'out_of_scope_mystery'
        return ctx

    hid = h.get('id', '')
    facing = _preflop_facing(h)
    if facing is None:
        pos = h.get('position') or ''
        ctx['oos_reason'] = ('out_of_scope_sb' if pos == 'SB'
                             else 'out_of_scope_position' if pos != 'BB'
                             else 'out_of_scope_no_open')
        return ctx

    # All-in family routing: opener (or any caller) all-in, or pot-committing
    # raise — the defense buckets never evaluate those.
    eff = h.get('eff_stack_bb_at_decision') or h.get('eff_stack_bb') or \
        h.get('stack_bb') or 0
    opener_stack = facing['opener_stack'] or eff
    if (facing['opener_allin'] or any(c['allin'] for c in facing['callers'])):
        ctx['oos_reason'] = 'allin_family'
        return ctx

    # v8.12.8: an SB open is a different defense tree entirely (no research
    # bucket measures it) — never borrow the BTN aggregate for it.
    if facing['opener_pos'] == 'SB':
        ctx['oos_reason'] = 'out_of_scope_sb_opener'
        return ctx

    # v8.12.8: coverage compares Hero's OWN stack to the opponents' stacks.
    # eff is min(hero, opener) — using it here collapsed every hero-covers
    # spot to "Equal" and routed it to the covered bucket ("cannot collect"
    # rendered on a 69bb-vs-18bb hand).
    hero_stack = (facing.get('hero_stack') or h.get('stack_bb') or eff or 0)

    eff_vs_opener = min(float(eff or 0), float(opener_stack or 0)) or eff
    depth, band_edge, oos = depth_band(eff_vs_opener)
    if oos:
        ctx['oos_reason'] = oos
        return ctx
    players = facing['players_if_continue']
    if players > 4:
        ctx['oos_reason'] = 'out_of_scope_5way'
        return ctx

    others = [opener_stack] + [c['stack'] for c in facing['callers']]
    if players == 2:
        cov = coverage_bucket(hero_stack, opener_stack)
    else:
        if all(float(hero_stack or 0) > float(o or 0) * 1.10 for o in others):
            cov = 'Hero covers'
        elif all(float(hero_stack or 0) < float(o or 0) * 0.90 for o in others):
            cov = 'Hero covered'
        else:
            cov = 'Mixed'

    bkey, downgrade_reasons = _map_bucket(depth, players, cov,
                                          facing['opener_pos'])
    if not bkey:
        ctx['oos_reason'] = 'out_of_scope_no_open'
        return ctx
    bucket = PKO_RESEARCH_BUCKETS[bkey]

    phase = h.get('tournament_phase', '') or ''
    full_phase = _phase_full_conf(phase)
    confidence = bucket['confidence']
    conf_reasons = list(downgrade_reasons)
    if not full_phase:
        confidence = _CONF_DIR
        conf_reasons.append('phase_outside_near_bubble(%s)' % (phase or '?'))
    if band_edge:
        confidence = _CONF_DIR
        conf_reasons.append('depth_band_edge')
    if downgrade_reasons:
        confidence = _CONF_DIR

    classic_ids = classic_ids or {}
    classic_says_defend = hid in classic_ids.get('missed_defend', set())
    classic_too_loose = hid in classic_ids.get('wide_defend', set())

    hero_act = facing['hero_act']
    hero_continued = hero_act in ('call', 'raise', 'jam')
    classification, fit = _classify(
        hero_continued, hero_act, classic_says_defend, classic_too_loose,
        bucket, band_edge, full_phase)

    # v8.12.8: spot label tells the truth about the ACTUAL opener; the
    # bucket's own spot becomes aggregate_spot. A borrowed (nearest) bucket
    # may never produce a PKO-good claim, and its teaching note is replaced
    # by an explicit nearest-aggregate note (QA: 8 hands labeled "BB vs BTN
    # open" with CO/HJ/MP/SB openers).
    _opener = facing['opener_pos']
    spot_lbl = ('BB vs %s open' % _opener if players == 2 else
                'BB vs %s open + caller' % _opener if players == 3 else
                'BB vs %s open + 2 callers' % _opener)
    fit_exact = not any(r.startswith(('opener_not_measured',
                                      'coverage_equal_mapped',
                                      'multiway_depth_mapped'))
                        for r in downgrade_reasons)
    if fit_exact:
        teach = bucket['teaching_note']
    else:
        _why = []
        for r in downgrade_reasons:
            if r.startswith('opener_not_measured'):
                _why.append('no measured aggregate for %s opens' % _opener)
            elif r == 'coverage_equal_mapped_to_covered':
                _why.append('near-equal stacks fall between the '
                            'covering/covered rows')
            elif r == 'multiway_depth_mapped_to_50bb_row':
                _why.append('multiway at this depth maps to the deep row')
        teach = ('No exact aggregate for this spot (%s). Nearest measured: '
                 '%s %s (%s) — directional Review cue only.'
                 % ('; '.join(_why), bucket['spot'], bucket['depth_bucket'],
                    bucket['coverage']))
        if classification == 'Good':
            classification, fit = 'Baseline', 'unknown'

    # Coverage/collectibility from exact stacks (display + teaching).
    can_collect = can_collect_bounty(hero_stack, opener_stack)
    if players == 2:
        if cov == 'Hero covers':
            coverage_label = 'covers opener — bounty collectible'
        elif cov == 'Hero covered':
            coverage_label = 'covered by opener — opener bounty not collectible'
        else:
            coverage_label = ('near-equal stacks — bounty collectible if '
                              'Hero wins outright' if can_collect else
                              'near-equal stacks — opener has Hero just covered')
    else:
        # v8.12.9 (GPT QA: "covers 1/2 — those bounties collectible" is
        # imprecise): name exactly whose bounty is collectible.
        _opp_pairs = ([(facing['opener_pos'], opener_stack)]
                      + [(c['pos'], c['stack']) for c in facing['callers']])
        _coll_pos = [p for p, o in _opp_pairs
                     if can_collect_bounty(hero_stack, o)]
        _uncoll_pos = [p for p, o in _opp_pairs if p not in _coll_pos]
        if len(_coll_pos) == len(_opp_pairs):
            coverage_label = 'covers the field — all bounties collectible'
        elif _coll_pos:
            coverage_label = ('covers %s only — that bounty collectible; '
                              '%s cover%s Hero'
                              % ('/'.join(_coll_pos), '/'.join(_uncoll_pos),
                                 '' if len(_uncoll_pos) > 1 else 's'))
        else:
            coverage_label = 'covered by the field — no bounty collectible'

    # v8.12.8: estimated-bounty fallback — GG never exports the exact
    # bounty, but the gem_bounty model estimates it per tournament/phase.
    _bvbb = h.get('bounty_value_bb') or 0
    _blbl = h.get('bounty_label') or ''
    if _bvbb > 0:
        _bounty_txt = ('Bounty ≈ %.1fBB (%s — phase-weighted estimate; '
                       'exact GG bounty not exported).' % (_bvbb, _blbl))
        _bounty_reason = 'bounty_estimated_from_model'
    else:
        _bounty_txt = 'Exact bounty size unavailable in GG export.'
        _bounty_reason = 'bounty_size_unknown_in_gg_export'

    # Slice E: single reconciled PKO trust line (cover / collectibility /
    # multiway / bounty), with the contradiction guard. Threshold/discount and
    # overjam live in the pot-odds layer; the strip here states the cover facts.
    _pko_trust = reconcile_pko_trust(
        coverage_bucket=cov, can_collect_bounty=can_collect, players=players,
        coverage_label=coverage_label, bounty_value_bb=(_bvbb or None))

    ctx.update({
        'enabled': True,
        'decision_family': 'BB_DEFEND_VS_OPEN',
        'spot': spot_lbl,
        'aggregate_spot': bucket['spot'],
        'aggregate_fit': 'exact' if fit_exact else 'nearest',
        'hero_position': 'BB',
        'opener_position_effective': facing['opener_pos'],
        'players_if_hero_continues': players,
        'depth_bucket': depth,
        'effective_stack_bb': round(float(eff_vs_opener or 0), 1),
        'hero_stack_bb': round(float(hero_stack or 0), 1),
        'band_edge': band_edge,
        'coverage_bucket': cov,
        'coverage_label': coverage_label,
        'coverage_model': 'heuristic_stack_ratio',
        'can_collect_bounty': can_collect,
        'coverage_ratio': (round(float(hero_stack) / float(opener_stack), 2)
                           if opener_stack else None),
        'research_bucket': bkey,
        'pko_delta_pp': bucket['pko_delta_pp'],
        'delta_range_pp': list(bucket['delta_range_pp']),
        'pko_delta_bucket': bucket['delta_bucket'],
        'action_mix': bucket['action_mix'],
        'confidence': confidence,
        'confidence_reasons': conf_reasons + [_bounty_reason],
        'phase': phase,
        'is_opportunity': True,
        'hero_action': hero_act,
        'hero_continued': hero_continued,
        'classification': classification,
        'pko_action_fit': fit,
        'classic_support_source': ('chart' if (classic_says_defend or
                                               classic_too_loose) else 'none'),
        'bounty_value_bb_est': (_bvbb or None),
        'teaching_note': teach,
        'caveat': ('Aggregate GTOW research — Review cue, not a confirmed '
                   'mistake. ' + _bounty_txt),
        'pko_trust': _pko_trust,
    })
    return ctx


# ---------------------------------------------------------------------------
# Session-level enrichment + aggregation (single counting source for S4)
# ---------------------------------------------------------------------------

def _classic_id_sets(stats):
    """Pull Classic chart-membership evidence from existing analyzer outputs.
    The BB_DEF deviations / gated lists ARE chart membership (built upstream
    from BB_DEF_vs*pct charts), so source='chart'."""
    missed, wide = set(), set()
    try:
        # v8.12.0b FIX: the analyzer stores these under 'preflop_deviations'
        # (s['preflop_deviations'], analyzer ~4759) — the old 'deviations'
        # key never existed, so Missed/Too wide were silently never assigned
        # (caught via the Chat report: a Confirmed Wide BB Defend pill read
        # 'PKO Baseline').
        for d in (stats or {}).get('preflop_deviations', []) or []:
            t = d.get('type', '')
            hid = d.get('id') or d.get('hand_id') or ''
            if not hid:
                continue
            if t == 'Missed BB Defend':
                missed.add(hid)
            elif t == 'Wide BB Defend':
                wide.add(hid)
    except Exception:
        pass
    try:
        gated = ((stats or {}).get('facing_action', {})
                 .get('bb_defense_vs_steal', {})
                 .get('missed_defend_gated', [])) or []
        for g in gated:
            if g.get('id'):
                missed.add(g['id'])
    except Exception:
        pass
    return {'missed_defend': missed, 'wide_defend': wide}


def _allin_audit_rows(hands, pot_odds_by_hand):
    """S4.4 spot families + migration audit (math vs verdict impact)."""
    fams = {k: [] for k in ('hu_calls', 'hu_jams', 'multiway', 'no_bounty')}
    migration = []
    for h in hands:
        fmt = (h.get('format') or '').upper()
        if fmt not in ('BOUNTY', 'PKO', 'MYSTERY_BOUNTY'):
            continue
        if not h.get('pf_allin'):
            continue
        hid = h.get('id', '')
        n_allin = (h.get('eai_n_allin') or 2)
        eff = h.get('eff_stack_bb_at_decision') or h.get('stack_bb') or 0
        jammer_bb = h.get('jammer_stack_bb') or 0
        hero_jammed = bool(h.get('first_in')) and any(
            a.get('player') == h.get('hero') and a.get('street') == 'preflop'
            and a.get('action') in ('raises', 'bets') and a.get('is_all_in')
            for a in (h.get('action_ledger') or []))
        # REV4 B2: this PKO all-in audit consumes the canonical DECISION-TIME bounty
        # context (never the legacy realized scalar h['bounty_collectible']). For a
        # COMMITTED confrontation (Hero calls a jam) eligibility owns `collect`; for an
        # open jam (no committed opponent at the decision) the decision-time stack-cover
        # relationship vs the relevant villain owns it (would Hero collect if called).
        # Fall back to the legacy heuristic only when the context is absent/unresolved.
        _dbc_pko = h.get('decision_bounty_context')
        if _dbc_pko is None:
            try:
                from gem_decision_snapshot import build_decision_bounty_context as _ds_dbc_pko
                _dbc_pko = _ds_dbc_pko(h)
            except Exception:
                _dbc_pko = {}
        _dbc_pko = _dbc_pko or {}
        if _dbc_pko.get('bounty_eligibility_known'):
            collect = bool(_dbc_pko.get('hero_covers_relevant_villain'))
        elif _dbc_pko.get('cover_relationship_known'):
            collect = bool(_dbc_pko.get('hero_covers_relevant_villain_by_cover'))
        else:
            collect = can_collect_bounty(eff, jammer_bb) if jammer_bb else \
                bool(h.get('hero_covers_all', h.get('covers', False)))
        if n_allin > 2:
            fams['multiway'].append(hid)
        elif hero_jammed:
            fams['hu_jams'].append(hid)
        else:
            fams['hu_calls'].append(hid)
        if not collect:
            fams['no_bounty'].append(hid)

        # Migration audit: old flat model vs v8.12.0 gated vs v8.12.1 shadow
        if hero_jammed or fmt == 'MYSTERY_BOUNTY' or not jammer_bb:
            mystery = fmt == 'MYSTERY_BOUNTY'
            if not mystery and not hero_jammed:
                continue
        call = min(jammer_bb or 0, eff or 0)
        if call <= 0:
            continue
        base_req = call / (2 * call + 2.3) * 100
        old_req = max(0.0, base_req - 8.0)
        gated_disc = 0.0
        reason = []
        if fmt == 'MYSTERY_BOUNTY':
            reason.append('mystery_no_discount')
        elif n_allin > 2:
            reason.append('multiway_no_numeric_discount')
        elif not collect:
            reason.append('no_cover_no_discount')
        else:
            gated_disc = 8.0
        new_req = max(0.0, base_req - gated_disc)
        depth_scale = 1.0 if (eff or 0) <= 20 else (
            0.5 if (eff or 0) <= 35 else 0.25)
        shadow_req = max(0.0, base_req - gated_disc * depth_scale)
        if abs(new_req - old_req) < 0.05 and abs(shadow_req - old_req) < 0.05:
            continue
        eq = None
        po = (pot_odds_by_hand or {}).get(hid) or {}
        if po.get('hero_equity_pct') is not None:
            eq = float(po['hero_equity_pct'])
        impact = 'math_changed_only'
        old_v = new_v = ''
        if eq is not None:
            old_v = 'call OK' if eq >= old_req else 'call -EV'
            new_v = 'call OK' if eq >= new_req else 'call -EV'
            if old_v != new_v:
                impact = 'verdict_changed'
        migration.append({
            'id': hid, 'spot': ('multiway all-in' if n_allin > 2 else
                                'HU bounty call'),
            'old_req': round(old_req, 1), 'new_req': round(new_req, 1),
            'shadow_req': round(shadow_req, 1),
            'old_verdict': old_v, 'new_verdict': new_v,
            'impact_type': impact,
            'reason': '+'.join(reason) or 'depth_scale_shadow',
        })
    return fams, migration


def enrich_pko_contexts(hands, stats=None, pot_odds_by_hand=None):
    """Build h['pko_context'] for every hand + the single aggregate structure
    consumed by S4 and the hand-detail pill. Fail-soft: a per-hand failure
    yields enabled=False for that hand; a total failure returns
    {'enabled': False} and the renderer omits the S4 research tables
    (never restoring old discounts)."""
    try:
        classic_ids = _classic_id_sets(stats)
        by_hand = {}
        teaching = {}
        oos_counts = {}
        for h in hands or []:
            try:
                ctx = build_pko_context(h, classic_ids)
            except Exception:
                ctx = {'enabled': False, 'oos_reason': 'unknown'}
            h['pko_context'] = ctx
            hid = h.get('id', '')
            if not hid:
                continue
            by_hand[hid] = ctx
            if ctx.get('enabled'):
                # v8.12.0b: one row per RESEARCH BUCKET (dims from the bucket
                # definition) — per-hand dim variants produced near-duplicate
                # rows and an over-wide table (Ron 2026-06-11 review).
                key = ctx['research_bucket']
                _bdef = PKO_RESEARCH_BUCKETS[key]
                row = teaching.setdefault(key, {
                    'spot': _bdef['spot'], 'depth': _bdef['depth_bucket'],
                    'players': _bdef['players'],
                    'coverage': _bdef['coverage'],
                    'bucket': key,
                    'delta_range_pp': _bdef['delta_range_pp'],
                    'delta_bucket': _bdef['delta_bucket'],
                    'classic_defend_pct': _bdef.get('classic_defend_pct'),
                    'action_mix': _bdef['action_mix'],
                    'confidence': ctx['confidence'],
                    'cells': {c: [] for c in
                              ('Seen', 'Actual', 'Too wide', 'Missed',
                               'Good', 'Review', 'Baseline')},
                })
                row['cells']['Seen'].append(hid)
                if ctx['hero_continued']:
                    row['cells']['Actual'].append(hid)
                cls = ctx['classification']
                if cls in row['cells']:
                    row['cells'][cls].append(hid)
            else:
                r = ctx.get('oos_reason', 'unknown')
                if ctx.get('is_bounty_format') and r != 'not_bounty_format':
                    oos_counts.setdefault(r, []).append(hid)

        for row in teaching.values():
            bucket = PKO_RESEARCH_BUCKETS.get(row['bucket'], {})
            n = len(row['cells']['Seen'])
            has_flag = bool(row['cells']['Review'] or row['cells']['Missed'])
            row['drill_cue'] = _drill_cue(
                bucket, 'Review' if has_flag else 'Baseline', n)

        fams, migration = _allin_audit_rows(hands or [], pot_odds_by_hand)

        bounty_ids = [h.get('id') for h in hands or []
                      if (h.get('format') or '').upper() in
                      ('BOUNTY', 'PKO', 'MYSTERY_BOUNTY') and h.get('id')]
        enabled_ids = [hid for hid, c in by_hand.items() if c.get('enabled')]
        mw_ids = [hid for hid, c in by_hand.items() if c.get('enabled')
                  and c.get('players_if_hero_continues', 2) >= 3]
        snapshot = {
            'bounty_hands': bounty_ids,
            'pko_sensitive_opps': enabled_ids,
            'bb_defense_opps': enabled_ids,
            'multiway_opps': mw_ids,
            'allin_bounty_opps': sorted(set(fams['hu_calls'] + fams['hu_jams']
                                            + fams['multiway'])),
            'out_of_scope': sorted({x for v in oos_counts.values()
                                    for x in v}),
            'needs_exact_grid': enabled_ids,
        }
        return {
            'enabled': True,
            'by_hand': by_hand,
            'teaching_rows': sorted(teaching.values(),
                                    key=lambda r: -len(r['cells']['Seen'])),
            'oos': {r: ids for r, ids in sorted(oos_counts.items())},
            'oos_next_action': _OOS_NEXT_ACTION,
            'allin_families': fams,
            'migration_audit': migration,
            'snapshot': snapshot,
        }
    except Exception as e:
        import sys
        print(f"  WARN: PKO research aggregation failed ({e}) — "
              f"S4 research tables omitted; live-logic removals unaffected.",
              file=sys.stderr)
        return {'enabled': False, 'error': str(e)}


def refresh_migration_equity(report_data):
    """Called by gem_coverage_builder AFTER it sets pot_odds_by_hand (that
    stage runs after generate_report_data, so the initial migration audit
    rows were computed without equity → math_changed_only). Re-derives the
    verdict columns now that equity exists. Upstream analysis layer — the
    renderer never recomputes."""
    try:
        pr = (report_data or {}).get('pko_research') or {}
        po_map = (report_data or {}).get('pot_odds_by_hand') or {}
        if not pr.get('enabled') or not po_map:
            return 0
        n = 0
        for row in pr.get('migration_audit', []) or []:
            po = po_map.get(row.get('id')) or {}
            eq = po.get('hero_equity_pct')
            if eq is None:
                continue
            old_v = 'call OK' if eq >= row['old_req'] else 'call -EV'
            new_v = 'call OK' if eq >= row['new_req'] else 'call -EV'
            row['old_verdict'], row['new_verdict'] = old_v, new_v
            row['impact_type'] = ('verdict_changed' if old_v != new_v
                                  else 'math_changed_only')
            n += 1
        return n
    except Exception:
        return 0
