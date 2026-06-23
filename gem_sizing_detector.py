"""GEM v8.20 Wave 1A — bet-sizing detector v1 (bounded, production-connected).

This WRAPS the existing production flop-c-bet sizing engine (gem_textures.aggregate_compliance, run
every session into stats['texture_gto_findings']) — it does NOT re-implement sizing math or invent a
generic standard. The reference is the curated gto_texture_archetypes.json sizings_pct band per
archetype × side × depth (sourced from real coaching sessions), so a finding never reduces to a vague
"differs from standard".

Family: flop_cbet_sizing. It emits an AGGREGATE LEAK signal (a repeated sizing pattern), NOT a per-hand
mistake verdict — a single off-size c-bet is never auto-graded as an error. Contributing hands are
listed as evidence; the analyst decides whether any individual hand was actually a mistake.

A signal fires ONLY for a high-confidence bucket:
  - sample_size_label == 'sufficient' (>= 8 c-bet opportunities), AND
  - sizing_judged_n >= MIN_JUDGED (enough sized c-bets to trust the rate), AND
  - sizing_compliance_pct < COMPLIANCE_FLOOR  (the off-reference rate is high).
Thin / small-sample / compliant buckets are excluded (and counted, never silently dropped).
"""

import gem_textures

MIN_JUDGED = 3
COMPLIANCE_FLOOR = 60.0

# ── v8.21 chart-applicability gate for the ONE canonical aggregate sizing path ────────────────
# Deep validation (3,609 real hands) found 0 confirmed per-hand sizing mistakes, so there is NO per-hand
# sizing detector. The only sizing surface is the AGGREGATE build_sizing_leak_signals above, fed by
# gem_analyzer's GTO block via gem_textures.aggregate_compliance and rendered as "Sizing & Line Patterns".
# `cbet_chart_applies` (below) is the safety gate that production path uses so the sizing-leak judgment
# counts only HEADS-UP, SINGLE-RAISED-POT, non-all-in c-bets (where the chart actually holds).


def _arch_human(arch):
    return str(arch or '').replace('_', ' ')


def _depth_repr(depth_band):
    """A representative effective stack (the band low bound) for the reference lookup."""
    try:
        return max(int(str(depth_band).split('-')[0].replace('BB', '')), 1)
    except (ValueError, AttributeError):
        return 40


def _pattern_label(arch, side):
    """Human-readable pattern name (never an internal detector code)."""
    return 'Flop c-bets off-size on %s boards (%s)' % (_arch_human(arch), (side or '').upper())


def build_sizing_leak_signals(texture_gto_findings, *, min_judged=MIN_JUDGED,
                              compliance_floor=COMPLIANCE_FLOOR):
    """Return {'signals': [...], 'excluded_counts': {...}}. Each signal exposes detector family, the
    specific trigger, the evidence used, confidence, signal_type (aggregate_leak), the contributing
    hands, the exclusions considered, and the human what/why/adjustment for the report surface."""
    signals = []
    excluded = {'thin_sample': 0, 'small_sample': 0, 'compliant': 0, 'no_target': 0}
    for arch in sorted((texture_gto_findings or {}).keys()):
        sides = texture_gto_findings.get(arch) or {}
        for side in sorted(sides.keys()):
            d = sides.get(side)
            if not isinstance(d, dict):
                continue
            ssl = d.get('sample_size_label')
            comp = d.get('sizing_compliance_pct')
            judged = d.get('sizing_judged_n') or 0
            if comp is None:
                excluded['no_target'] += 1
                continue
            if ssl == 'small':
                excluded['small_sample'] += 1
                continue
            if ssl == 'thin' or judged < min_judged:
                excluded['thin_sample'] += 1
                continue
            if comp >= compliance_floor:
                excluded['compliant'] += 1
                continue
            # ── qualifying high-confidence aggregate sizing leak ──────────────
            sized = d.get('sizing_hands') or []
            off_ids, actual = [], []
            for h in sized:
                if isinstance(h, dict) and h.get('within') is False and h.get('id'):
                    off_ids.append(h['id'])
                    if h.get('sizing_pct') is not None:
                        actual.append(round(float(h['sizing_pct'])))
            depth = _depth_repr(sized[0].get('depth_band') if sized else None)
            tgt = gem_textures.get_gto_target(arch, side, depth) or {}
            ref = list(tgt.get('sizings_pct') or [])
            ref_str = ('/'.join('%d%%' % r for r in ref) if ref else 'reference')
            act_str = ', '.join('%d%%' % a for a in sorted(set(actual))[:6]) or '?'
            signals.append({
                'family': 'flop_cbet_sizing',
                'signal_type': 'aggregate_leak',                  # repeated leak, NOT a per-hand verdict
                'archetype': arch,
                'side': side,
                'pattern_label': _pattern_label(arch, side),
                'trigger': ('flop c-bet sizing off-reference on %d of %d sized c-bets '
                            '(%.0f%% within ±10pp of %s) on %s boards %s'
                            % (len(set(off_ids)), judged, comp, ref_str, _arch_human(arch), side.upper())),
                'evidence': {
                    'actual_sizings_pct': sorted(set(actual)),
                    'reference_sizings_pct': ref,
                    'tolerance_pp': 10,
                    'sizing_compliance_pct': comp,
                    'judged_c_bets': judged,
                    'sample_size_label': ssl,
                    'depth_band': (sized[0].get('depth_band') if sized else None),
                },
                'confidence': 'high',
                'contributing_hands': sorted(set(off_ids)),
                'exclusions_considered': 'thin / small-sample / compliant buckets excluded; structural '
                                         'eligibility owned by is_legal_cbet_opportunity',
                'requires_analyst_review': ('aggregate sizing pattern — analyst confirms whether any '
                                            'contributing hand was an individual mistake; the signal does '
                                            'not grade hands'),
                # human-readable surface copy (no internal codes)
                'what_happened': 'Hero c-bet %s on %s boards %s; the reference band is %s.'
                                 % (act_str, _arch_human(arch), side.upper(), ref_str),
                'why_it_matters': 'A repeated off-reference flop c-bet size leaks value or protection '
                                  'across this whole board class, not just one hand.',
                'adjustment': 'On %s boards %s, size flop c-bets toward %s.'
                              % (_arch_human(arch), side.upper(), ref_str),
            })
    return {'signals': signals, 'excluded_counts': excluded}


def _flop_cbet_is_all_in(hand):
    """True iff Hero's flop c-bet action is all-in. An all-in c-bet is a commitment / stack-off
    decision, not a free sizing choice, so it is out of scope for a c-bet SIZING comparison."""
    for a in (hand.get('action_ledger') or []):
        if (isinstance(a, dict) and a.get('street') == 'flop' and a.get('player') == 'Hero'
                and (a.get('action') in ('bets', 'raises'))):
            return bool(a.get('is_all_in'))
    return False


def cbet_chart_applies(hand):
    """True iff the gto_texture_archetypes sizing band applies to this flop c-bet: HEADS-UP,
    SINGLE-RAISED-POT, non-all-in. The bands are calibrated for HU SRP range c-bets, so a 3-bet/4-bet pot,
    a multiway flop, or an all-in c-bet must NOT be sizing-judged. gem_analyzer's GTO block uses this gate
    to skip those from the sizing dimension while leaving the c-bet FREQUENCY denominator untouched, so the
    one canonical aggregate path (aggregate_compliance -> build_sizing_leak_signals) only ever measures
    sizing where the chart holds. Canonical decision-time inputs only; no results/showdown/range/equity."""
    if (hand.get('pot_type') or '') != 'SRP':
        return False
    if hand.get('multiway_flop') or (hand.get('players_at_flop') or 2) > 2:
        return False
    if _flop_cbet_is_all_in(hand):
        return False
    return True
