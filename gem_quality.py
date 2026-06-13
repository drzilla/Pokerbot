"""
GEM Pipeline Quality Layer — v7.30

Three components addressing the failure patterns from the 2026-05-05 QA:

1. PRE-FLIGHT VALIDATION — runs before any leak narrative is generated.
   Sanity-checks foundational inputs (range file, parser sizing,
   aggregation cells, EAI buckets). Failed checks downgrade affected
   sections to ❌ unreliable rather than producing fake findings.

2. PLAUSIBILITY GATE — runs at the moment a finding is promoted to a
   leak. Asks "does this make sense?" before raising the alarm. Catches
   denominator-thin findings, magnitude outliers, and "would a coach
   call this actionable" failures.

3. LEARNING LOG — runs at end of every analyzer pass. Captures what
   was unexpected, what failed pre-flight, what got plausibility-gated,
   and what new misclassifications surfaced. Appends to
   gem_pipeline_learnings.csv so each session educates the next.

These exist because v1/v2/v3 of last session's report all built leak
narratives on unverified upstream layers. The structural fix isn't
"try harder to verify" — it's runtime gates that make unverified
findings explicit.
"""

import os
import csv
from datetime import datetime


# =====================================================================
# PRE-FLIGHT VALIDATION
# =====================================================================

# Anchor hands that MUST be in standard MTT opening ranges. If any
# absent, the range file is treated as corrupted and all range-comparator
# findings (Missed Open, Wide Open, Missed Defend, Missed Rejam,
# Missed BB Defend) are downgraded to ❌ unreliable.
ANCHOR_HANDS = {
    'OPEN_100BB_UTG':  ['AA', 'KK', 'QQ', 'AKs', 'AQs', 'AJs', 'ATs'],
    'OPEN_100BB_MP':   ['AA', 'KK', 'QQ', 'AKs', 'AQs', '88', 'KQs'],
    'OPEN_100BB_HJ':   ['AA', 'KK', 'AKs', 'AQs', 'AJs', 'ATs', '88'],
    'OPEN_100BB_CO':   ['AA', 'AKs', 'AQs', 'AJs', 'ATs', '88', 'KQs', '76s'],
    'OPEN_100BB_BTN':  ['AA', 'AKs', 'AQs', 'AJs', 'ATs', '76s', '65s', 'KQs', '55', '44'],
    # Selected REJAM ranges — anchor only on universal-include hands
    # (AQs in BB rejam vs BTN is borderline across strategies; not universal).
    'REJAM_BBvsBTN':   ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'TT', '99'],
    'REJAM_HJvsMP':    ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'TT'],
}


def preflight_check_ranges(ranges):
    """Verify range file contains standard anchor hands.

    Returns dict: {chart_name: {'ok': bool, 'missing': [hands]}}
    plus a top-level 'ranges_reliable' bool summarizing.
    """
    results = {}
    any_failed = False
    for chart_name, expected in ANCHOR_HANDS.items():
        chart = ranges.get(chart_name, set())
        if not chart:
            results[chart_name] = {'ok': False, 'missing': expected,
                                   'reason': 'chart not loaded'}
            any_failed = True
            continue
        missing = [h for h in expected if h not in chart]
        results[chart_name] = {'ok': len(missing) == 0, 'missing': missing}
        if missing:
            any_failed = True
    results['ranges_reliable'] = not any_failed
    return results


def preflight_check_parser_sizing(hands):
    """Spot-check that parser produces non-zero antes when antes are present.

    Verifies the v7.30 P0-1 ante regex fix is still working by checking
    that antes are NOT all-zero across the session.

    The original bug produced ante=0 for 100% of hands. Threshold here is
    intentionally low (5%) to avoid false positives in mixed test sets
    (early-level fixtures legitimately have no antes). A real regression
    of the regex bug shows as 0% — anything ≥5% means parsing works.

    Returns: {'ok': bool, 'pct_with_ante': float, 'note': str}
    """
    if not hands:
        return {'ok': True, 'pct_with_ante': 0, 'note': 'no hands to check'}
    with_ante = sum(1 for h in hands if h.get('ante', 0) > 0)
    pct = 100 * with_ante / len(hands)
    # The ante regex bug produced ante=0 for 100% of hands. Threshold is set
    # at 5% — generous enough to allow mixed test fixtures without false positives,
    # tight enough to catch a real regression (which shows as 0%).
    ok = pct >= 5
    return {
        'ok': ok,
        'pct_with_ante': round(pct, 1),
        'note': ('ante regex fix verified' if ok
                 else f'⚠️ only {pct:.0f}% of hands have ante — regex may have regressed (P0-1)')
    }


def preflight_check_aggregation_no_pf_allin(stats, hands):
    """Verify aggregation_tables denominators don't include PF all-ins.

    Spot-checks PFR_Flop_OOP made_hand: its 'total' should NOT exceed
    the count of (PFR + saw flop + OOP + NOT pf_allin) hands.
    """
    ag = stats.get('aggression_tables', {})
    pfr_flop_oop = ag.get('PFR_Flop_OOP', {}).get('made_hand', {})
    reported_total = pfr_flop_oop.get('total', 0)

    real_count = sum(1 for h in hands
                     if h.get('pfr')
                     and len(h.get('board', [])) >= 3
                     and not h.get('hero_ip')  # OOP
                     and not h.get('pf_allin'))
    # 'made_hand' is a subset of "saw flop" so reported should be <= real_count
    # but they're filtered differently (made-hand check etc). Approximate sanity:
    # reported_total should not be wildly larger than real_count.
    ok = reported_total <= real_count + 2  # allow small slack
    return {
        'ok': ok,
        'reported_total': reported_total,
        'max_expected': real_count,
        'note': ('aggregation tables exclude PF all-ins ✓' if ok
                 else f'⚠️ reported {reported_total} > expected ≤{real_count}, '
                      f'PF all-in filter may have regressed')
    }


def preflight_check_eai_buckets(stats):
    """Spot-check EAI bucket logic — verify chops are partial wins.

    If any 'won' value in a bucket exceeds the count of binary True wins,
    chop-handling is working.
    """
    eai = stats.get('eai', {})
    pf = eai.get('preflop', {})
    # Easiest sanity: total wins (sum of fractional wins) should be <= count
    total_count = pf.get('count', 0)
    total_wins = (pf.get('ahead', {}).get('won', 0)
                  + pf.get('flip', {}).get('won', 0)
                  + pf.get('behind', {}).get('won', 0))
    ok = total_wins <= total_count
    return {
        'ok': ok,
        'total_count': total_count,
        'total_wins': total_wins,
        'note': ('EAI bucket counts coherent ✓' if ok
                 else f'⚠️ total_wins {total_wins} > total_count {total_count}')
    }


def preflight_check_hand_metadata(hands):
    """v7.30: every hand row in the report MUST have tournament name + date.
    Without these, the reader can't find the hand to review it. Ron's
    explicit requirement — 'Unknown' tournament breaks the workflow.

    Returns: {'ok': bool, 'missing_tournament_pct': float, 'missing_date_pct': float, 'note': str}
    """
    if not hands:
        return {'ok': True, 'missing_tournament_pct': 0, 'missing_date_pct': 0, 'note': 'no hands'}
    n = len(hands)
    missing_tournament = sum(1 for h in hands
                             if not h.get('tournament') or h.get('tournament') == 'Unknown')
    missing_date = sum(1 for h in hands if not h.get('date'))
    pct_t = round(100 * missing_tournament / n, 1)
    pct_d = round(100 * missing_date / n, 1)
    ok = missing_tournament == 0 and missing_date == 0
    if ok:
        note = 'all hands have tournament + date ✓'
    else:
        bits = []
        if missing_tournament:
            bits.append(f"{missing_tournament}/{n} ({pct_t}%) missing/Unknown tournament")
        if missing_date:
            bits.append(f"{missing_date}/{n} ({pct_d}%) missing date")
        note = f"⚠️ hand metadata gaps: {'; '.join(bits)} — clinical/GTO tables will be unfindable"
    return {
        'ok': ok,
        'missing_tournament_pct': pct_t,
        'missing_date_pct': pct_d,
        'missing_tournament_count': missing_tournament,
        'missing_date_count': missing_date,
        'note': note,
    }


# v7.32 (C8): per-detector required-charts registry. If a detector's required
# chart family has zero matching entries in the loaded ranges/targets, emit a
# warning so the detector doesn't silently report 0 deviations and look fine.
# Each value is a tuple (chart_prefix_patterns) — preflight checks at least
# one chart with the prefix exists in the loaded artifacts.
DETECTOR_REQUIRED_CHARTS = {
    'check_open_deviations':       ('OPEN_100BB_', 'OPEN_20-40BB_', 'PUSH_10BB_'),
    'check_rejam_deviations':      ('REJAM_',),
    'check_defend_3bet_deviations': ('CALLRJ_', 'FLAT3B_'),
    'check_bb_defend_deviations':  ('BB_DEF_',),
    # v7.32 new — these consume *_TARGET_* bands, not range charts.
    'check_turn_cbet_by_position':     ('TURN_CBET_TARGET_',),
    'check_river_cbet_by_position':    ('RIVER_CBET_TARGET_',),
    'check_fold_to_cbet_by_position':  ('F2CB_TARGET_',),
    'check_squeeze_by_position':       ('SQUEEZE_TARGET_',),
    'check_rfi_by_position':           ('RFI_TARGET_',),
}


def preflight_check_detector_charts(ranges, targets=None):
    """v7.32 (C8): For each detector, verify at least one chart with its
    required prefix is loaded. Disables silent-zero failures like the v7.30
    pattern (56 missing CALLRJ_*/FLAT3B_* charts → Missed-Defend silently
    reported 0 deviations and looked clean).

    Returns: {detector_name: {'ok': bool, 'missing_prefixes': [...],
                              'matched_count': int}, ..., 'all_ok': bool}
    """
    targets = targets or {}
    chart_names = set(ranges.keys()) | set(targets.keys())
    results = {}
    any_failed = False
    for detector, prefixes in DETECTOR_REQUIRED_CHARTS.items():
        missing = []
        matched = 0
        for prefix in prefixes:
            n = sum(1 for name in chart_names if name.startswith(prefix))
            if n == 0:
                missing.append(prefix)
            else:
                matched += n
        ok = (len(missing) == 0)
        if not ok:
            any_failed = True
        results[detector] = {
            'ok': ok,
            'missing_prefixes': missing,
            'matched_count': matched,
        }
    results['all_ok'] = not any_failed
    return results


def preflight_check_buyin_bounds(stats):
    """v7.32 (C9): warn if any parsed buy-in > $5,000. Catches the v7.31
    buy-in-parser bug pattern (filename format change → date misread as
    buy-in, $20.26M reported). The actual fix is in gem_report_data.py;
    this is a tripwire for future regressions.

    Returns: {'ok': bool, 'max_buyin': float, 'count_over_5k': int,
              'note': str}
    """
    buyins = []
    for src in ('volume', 'core'):
        sd = stats.get(src) or {}
        for k, v in sd.items():
            if 'buyin' in k.lower() and isinstance(v, (int, float)):
                buyins.append(float(v))
    # Also look at avg_buyin / total_buyin top-level
    for k in ('avg_buyin', 'total_buyin', 'max_buyin'):
        v = stats.get(k)
        if isinstance(v, (int, float)):
            buyins.append(float(v))
    if not buyins:
        return {'ok': True, 'max_buyin': 0, 'count_over_5k': 0,
                'note': 'No buy-in data found in stats.'}
    max_bi = max(buyins)
    over_5k = sum(1 for b in buyins if b > 5000)
    ok = max_bi <= 5000
    note = ('All buy-ins under $5K threshold.' if ok
            else f'⚠️ Buy-in over $5K detected (max=${max_bi:,.0f}). '
                 f'Likely a parser bug — date or GTD field misread as buy-in. '
                 f'Verify gem_report_data.py _parse_buyins regex.')
    return {'ok': ok, 'max_buyin': max_bi, 'count_over_5k': over_5k, 'note': note}


def preflight_check_all_zeros_sections(stats, hands):
    """Detect report sections where the headline metric is 0 but the underlying
    raw data is non-zero — almost always a renderer/analyzer wiring break.

    Returns {'ok': bool, 'sections_flagged': [{'section', 'metric', 'reported',
    'raw_n', 'note'}]}.

    This is the auto-zero investigator (Ron's request 2026-05-09): when a
    section renders all zeros, the pipeline should self-flag rather than
    silently confuse the reader.
    """
    flagged = []
    core = stats.get('core', {}) or {}

    # ---- Section VI: 3BP/4BP cbet ----
    # If core says cbet_3bp_pct=0 (or None) but raw hands count says
    # cbet_3bp_opps > 0, there's a wiring break. Same for 4BP.
    cbet_3bp_opps_raw = sum(1 for h in hands
                             if h.get('pfr')
                             and h.get('pot_type') == '3BP'
                             and len(h.get('board') or []) >= 3)
    cbet_3bp_n_raw = sum(1 for h in hands if h.get('cbet_flop_3bp'))
    cbet_3bp_opps_core = core.get('cbet_3bp_opps')
    if cbet_3bp_opps_raw > 0 and (cbet_3bp_opps_core in (None, 0)):
        flagged.append({
            'section': 'VI Post-Flop 3BP & 4BP',
            'metric': 'cbet_3bp_opps',
            'reported': cbet_3bp_opps_core,
            'raw_n': cbet_3bp_opps_raw,
            'note': (f'Raw hand scan finds {cbet_3bp_opps_raw} 3BP cbet opps '
                     f'and {cbet_3bp_n_raw} cbets, but core stat is '
                     f'{cbet_3bp_opps_core}. Analyzer not writing core fields.'),
        })

    cbet_4bp_opps_raw = sum(1 for h in hands
                             if h.get('pfr')
                             and h.get('pot_type') == '4BP'
                             and len(h.get('board') or []) >= 3)
    cbet_4bp_n_raw = sum(1 for h in hands if h.get('cbet_flop_4bp'))
    cbet_4bp_opps_core = core.get('cbet_4bp_opps')
    if cbet_4bp_opps_raw > 0 and (cbet_4bp_opps_core in (None, 0)):
        flagged.append({
            'section': 'VI Post-Flop 3BP & 4BP',
            'metric': 'cbet_4bp_opps',
            'reported': cbet_4bp_opps_core,
            'raw_n': cbet_4bp_opps_raw,
            'note': (f'Raw hand scan finds {cbet_4bp_opps_raw} 4BP cbet opps; '
                     f'core stat is {cbet_4bp_opps_core}.'),
        })

    # ---- Generic "all zero counter" detector: if every numeric value in a
    # known headline group is 0 AND total hands > 0, that's suspicious. ----
    # Check progress tracker — trend rows present but every numeric col is 0.
    # (Renderer-side investigation; report_data carries trend_data but is
    # outside this preflight scope. Skipped here, handled at render time.)

    return {
        'ok': len(flagged) == 0,
        'sections_flagged': flagged,
    }


def run_preflight(stats, hands, ranges, targets=None):
    """Run all pre-flight checks and return a structured report.

    Returns: {
      'ranges': preflight_check_ranges(...),
      'parser_sizing': preflight_check_parser_sizing(...),
      'aggregation': preflight_check_aggregation_no_pf_allin(...),
      'eai': preflight_check_eai_buckets(...),
      'hand_metadata': preflight_check_hand_metadata(...),
      'all_ok': bool,
      'unreliable_sections': [str]   # which report sections to mark ❌
    }
    """
    report = {
        'ranges': preflight_check_ranges(ranges),
        'parser_sizing': preflight_check_parser_sizing(hands),
        'aggregation': preflight_check_aggregation_no_pf_allin(stats, hands),
        'eai': preflight_check_eai_buckets(stats),
        'hand_metadata': preflight_check_hand_metadata(hands),
        # v7.32 additions
        'detector_charts': preflight_check_detector_charts(ranges, targets),
        'buyin_bounds': preflight_check_buyin_bounds(stats),
        # v7.42 — Ron's request 2026-05-09: auto-investigate all-zero sections
        # where raw data isn't actually zero (i.e., core/renderer wiring break).
        'all_zeros_sections': preflight_check_all_zeros_sections(stats, hands),
    }
    unreliable = []
    if not report['ranges'].get('ranges_reliable'):
        unreliable.extend([
            'preflop_deviations (Missed Open / Wide Open / Missed Defend / '
            'Missed Rejam / Missed BB Defend)'
        ])
    if not report['parser_sizing']['ok']:
        unreliable.append('all postflop bet-sizing percentages')
    if not report['aggregation']['ok']:
        unreliable.append('aggression_tables')
    if not report['eai']['ok']:
        unreliable.append('eai_summary')
    if not report['hand_metadata']['ok']:
        unreliable.append('clinical/GTO hand-reference tables (missing tournament or date)')
    # v7.32 (C8): detectors with missing chart families are unreliable.
    if not report['detector_charts'].get('all_ok'):
        bad = [det for det, d in report['detector_charts'].items()
               if isinstance(d, dict) and not d.get('ok')]
        if bad:
            unreliable.append(f'detector outputs (missing charts): {", ".join(bad)}')
    # v7.32 (C9): buy-in over $5K is a hard warning, not a section disable.
    if not report['buyin_bounds']['ok']:
        unreliable.append('volume/buyin stats')
    # v7.42: all-zero section investigator — flag when render shows zeros but
    # raw data isn't zero (analyzer/renderer wiring break).
    azs = report.get('all_zeros_sections', {})
    if not azs.get('ok', True):
        for entry in azs.get('sections_flagged', []):
            unreliable.append(
                f"all-zeros wiring break in {entry['section']} "
                f"({entry['metric']}: reported={entry['reported']} "
                f"vs raw n={entry['raw_n']})"
            )
    report['all_ok'] = len(unreliable) == 0
    report['unreliable_sections'] = unreliable
    return report


# =====================================================================
# PLAUSIBILITY GATE
# =====================================================================

def plausibility_gate(finding, hands=None):
    """Gate a finding before promoting to a leak. Returns dict with:

      passes:    bool — finding is plausible enough to surface
      confidence: '✅ verified' | '🟡 detector-only' | '⚪ small sample' | '❌ unreliable'
      reasons:   [str] — explanations for confidence/passes

    A 'finding' dict should carry:
      - 'denominator': N spots considered (for sample-size check)
      - 'numerator':   how many fired (e.g. how many "missed" or "wide")
      - 'magnitude':   |actual - target| or similar effect size
      - 'rule_code':   J-rule or detector name
      - 'verified':    bool — set True after recomputing from raw hands
      - 'requires_context': bool — True when interpretation depends on
                                   bounty/ICM/villain-pool data the
                                   detector doesn't see

    Plausibility checks:
      - denominator < 5: ⚪ small sample
      - magnitude < 0.5x or 5pp threshold: ⚪ noise floor (Ron-calibrated)
      - finding flagged as "100% bet" or "0% bet": cross-check denominator
        for sanity (filtering already happened upstream but double-check)
      - requires_context: ⚪ unverified
      - explicitly verified=True: ✅
      - else: 🟡 detector-only
    """
    reasons = []
    confidence = '🟡 detector-only'  # default
    passes = True

    n = finding.get('denominator')
    k = finding.get('numerator')
    mag = finding.get('magnitude')

    # Sample-size check
    if n is not None and n < 5:
        confidence = '⚪ small sample'
        reasons.append(f'denominator n={n} < 5 — too thin to act on')

    # Noise floor — Ron-calibrated 0.2 BB EV / 5pp metric
    if mag is not None and abs(mag) < 0.05:  # 5pp for percentage metrics
        confidence = '⚪ small sample'
        reasons.append(f'magnitude |{mag:.3f}| below noise floor (0.05)')

    # 0% / 100% extreme — denominator check needed
    if k is not None and n is not None and n > 0:
        rate = k / n
        if (rate == 0 or rate == 1) and n < 10:
            reasons.append(f'extreme rate ({rate:.0%}) with thin denominator (n={n}) — '
                           f'check if denominator includes ineligible spots')

    # Context-dependent
    if finding.get('requires_context'):
        confidence = '⚪ small sample'  # treat as unverified
        reasons.append('interpretation requires bounty/ICM/villain-pool context')

    # Verified
    if finding.get('verified'):
        confidence = '✅ verified'
        reasons.append('recomputed from raw hands')

    # Explicit unreliable mark from upstream
    if finding.get('unreliable'):
        confidence = '❌ unreliable'
        passes = False
        reasons.append('marked unreliable by upstream check (pre-flight failed)')

    return {
        'passes': passes,
        'confidence': confidence,
        'reasons': reasons,
    }


# =====================================================================
# LEARNING LOG
# =====================================================================

LEARNING_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)) or '.', 'gem_pipeline_learnings.csv')


def append_learning(date, category, observation, suggested_action='', context=''):
    """Append a row to the pipeline learning log.

    Categories:
      preflight_fail     — a pre-flight check failed (e.g. range corruption)
      misclassification  — a detector misclassified a hand (added to exceptions log)
      thin_denominator   — a finding's denominator was <5
      noise_floor        — a finding's magnitude was below noise floor
      detector_prereq    — a detector lacked a prerequisite gate
      contradiction      — analyzer output contradicted itself

    Dedups: same (date, category, observation) row never appended twice.
    Multiple analyzer runs in one day → still only one entry per unique
    learning. Cleared the next day if the issue persists.
    """
    new_file = not os.path.exists(LEARNING_LOG_PATH)

    # Dedup check: read existing rows, skip if (date, category, observation) already there
    if not new_file:
        try:
            with open(LEARNING_LOG_PATH, 'r', newline='') as f:
                existing = csv.DictReader(f)
                for row in existing:
                    if (row.get('date') == date
                            and row.get('category') == category
                            and row.get('observation') == observation):
                        return  # already logged
        except Exception:
            pass  # if read fails, fall through to append

    with open(LEARNING_LOG_PATH, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(['date', 'category', 'observation', 'suggested_action', 'context'])
        w.writerow([date, category, observation, suggested_action, context])


def end_of_run_learning(preflight_report, gated_findings, stats):
    """Capture what was unexpected during this analyzer run.

    Returns a list of learning entries (also appended to CSV) so the
    report can surface a "what was learned this run" section.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    learnings = []

    # Pre-flight failures
    for sect, status in preflight_report.items():
        if isinstance(status, dict) and status.get('ok') is False:
            # v8.12.4 (QA item 22): "preflight_fail: all_zeros_sections" with
            # no note told the reader nothing. Name WHICH sections were
            # all-zero and the reported-vs-raw numbers.
            _note = status.get('note', '')
            if not _note and status.get('sections_flagged'):
                _note = '; '.join(
                    f"{e.get('section','?')} ({e.get('metric','?')}: "
                    f"reported={e.get('reported')} vs raw n={e.get('raw_n')})"
                    for e in status['sections_flagged'][:4])
            obs = f"Pre-flight check failed: {sect} — {_note}"
            action = f"Investigate {sect} before next run"
            learnings.append({'category': 'preflight_fail', 'observation': obs,
                              'suggested_action': action})
        elif isinstance(status, dict) and 'ranges_reliable' in status:
            if not status['ranges_reliable']:
                missing_charts = [k for k, v in status.items()
                                  if isinstance(v, dict) and v.get('missing')]
                obs = f"Range file missing anchor hands in: {', '.join(missing_charts[:5])}"
                action = "Regenerate Poker_Ranges_Text.txt from clean source"
                learnings.append({'category': 'preflight_fail', 'observation': obs,
                                  'suggested_action': action})

    # Thin denominator findings
    thin = [f for f in (gated_findings or []) if '⚪ small sample' in f.get('confidence', '')]
    if thin:
        obs = f"{len(thin)} findings had thin denominators (n<5) and were downgraded"
        action = "Either accumulate more sessions before acting, or accept ⚪ confidence"
        learnings.append({'category': 'thin_denominator', 'observation': obs,
                          'suggested_action': action})

    # Misclassifications surfaced from gem_exceptions_log.csv compared to last run
    # (placeholder — full diff requires reading prior log; future enhancement)

    # Append all to CSV
    for L in learnings:
        append_learning(today, L['category'], L['observation'],
                        L.get('suggested_action', ''))

    return learnings


# =====================================================================
# v7.30 STANDALONE CSV ROW WRITER
# =====================================================================
# Writes the session_history + run_log rows as separate CSV files
# (filename includes date so it's self-identifying for "click add to project").
# Called by the report pipeline after stats are generated.

def write_standalone_csv_rows(rd, output_dir):
    """Write session_history_row + run_log_row to standalone CSV files.

    Args:
      rd: report_data dict (must contain 'session_history_row' + 'run_log_row')
      output_dir: where to write the CSVs

    Returns: dict {'session_history_path': str, 'run_log_path': str}
    Filenames carry the batch date so Ron can drop them into project knowledge
    without colliding with prior sessions' files.
    """
    import csv as _csv
    from gem_report_data import SESSION_HISTORY_COLUMNS, RUN_LOG_COLUMNS

    os.makedirs(output_dir, exist_ok=True)
    sh_row = rd.get('session_history_row') or {}
    rl_row = rd.get('run_log_row') or {}

    batch_id = sh_row.get('Batch_ID', 'unknown_batch')

    sh_path = os.path.join(output_dir, f'session_history_row_{batch_id}.csv')
    rl_path = os.path.join(output_dir, f'gem_run_log_row_{batch_id}.csv')

    with open(sh_path, 'w', newline='', encoding='utf-8') as f:
        w = _csv.DictWriter(f, fieldnames=SESSION_HISTORY_COLUMNS)
        w.writeheader()
        w.writerow({k: sh_row.get(k, '') for k in SESSION_HISTORY_COLUMNS})

    with open(rl_path, 'w', newline='', encoding='utf-8') as f:
        w = _csv.DictWriter(f, fieldnames=RUN_LOG_COLUMNS)
        w.writeheader()
        w.writerow({k: rl_row.get(k, '') for k in RUN_LOG_COLUMNS})

    return {'session_history_path': sh_path, 'run_log_path': rl_path}


# ============================================================
# v7.36 — PIPELINE-STAGE SCHEMA VALIDATION
# ============================================================
# Catches doc-vs-code drift between analyzer output and renderer
# expectations (Bug #3 class). Runs lightweight structural checks
# on the data dicts that flow between stages, raising clear errors
# when a section's data shape doesn't match what the renderer reads.
#
# Not a full JSON Schema validator — that's gem_schema.json + the
# external validate_schema.py for stricter contracts. This is the
# inline "smoke test" that runs every session as a guardrail.

def validate_pipeline_outputs(stats, report_data, strict=False):
    """Validate stats + report_data shape for known renderer expectations.

    Returns (ok: bool, issues: list[str]). When strict=True, raises
    ValueError on the first issue. Default soft mode logs issues for the
    end-of-run learning report so they surface but don't block rendering.
    """
    issues = []

    # ---- gem_stats.json structural expectations ----
    # _hands_by_id is added by the renderer itself, not stats — don't expect it here.
    required_top = ['volume', 'core', 'csv_row', 'mistakes', 'preflop_deviations',
                    'coolers', 'cbet', 'eai', 'card_quality']
    for k in required_top:
        if k not in stats:
            issues.append(f"stats[{k!r}] missing — renderer reads this in multiple sections")

    vol = stats.get('volume', {})
    for k in ['hands', 'tournaments', 'date', 'date_range']:
        if k not in vol:
            issues.append(f"stats['volume'][{k!r}] missing — renderer header + filename rely on this")

    csv = stats.get('csv_row', {})
    if csv and 'Batch_ID' not in csv:
        issues.append("stats['csv_row']['Batch_ID'] missing — run_log row needs this")

    # ---- gem_report_data.json shape expectations ----
    if not report_data:
        issues.append("report_data is empty/None — renderer would emit blank sections")
        return (len(issues) == 0, issues)

    # Bug #3 root cause: leak_persistence shape
    lp = report_data.get('leak_persistence')
    if lp is not None:
        if not isinstance(lp, dict):
            issues.append("report_data['leak_persistence'] should be dict, not "
                          f"{type(lp).__name__}")
        else:
            # IX renderer reads summary + tracker
            if 'summary' not in lp:
                issues.append("leak_persistence['summary'] missing — IX header counts 0/0/0")
            elif not isinstance(lp['summary'], dict):
                issues.append("leak_persistence['summary'] should be dict with new/recurring/resolved")
            if 'tracker' not in lp:
                issues.append("leak_persistence['tracker'] missing — IX table empty")
            elif not isinstance(lp['tracker'], list):
                issues.append("leak_persistence['tracker'] should be list of dicts")
            # III.2 reader uses current_leaks
            if 'current_leaks' not in lp:
                issues.append("leak_persistence['current_leaks'] missing — III.2 table empty")

    # Hero classification + skill band shape
    for k, label in [('hero_classification', 'Hero structure verdict'),
                      ('skill_band', 'Skill band')]:
        v = report_data.get(k)
        if v is not None and not isinstance(v, dict):
            issues.append(f"report_data['{k}'] should be dict ({label})")

    # Analyst commentary shape (v7.36): hand_id → dict
    ac = report_data.get('analyst_commentary')
    if ac is not None:
        if not isinstance(ac, dict):
            issues.append("report_data['analyst_commentary'] should be dict[hand_id, entry]")
        else:
            for hid, entry in ac.items():
                if not isinstance(entry, dict):
                    issues.append(f"analyst_commentary[{hid!r}] should be dict, not "
                                  f"{type(entry).__name__}")
                    break  # one example is enough

    if strict and issues:
        raise ValueError(f"Pipeline schema validation failed ({len(issues)} issue(s)):\n  - "
                         + "\n  - ".join(issues))
    return (len(issues) == 0, issues)
