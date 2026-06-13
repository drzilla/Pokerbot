"""Analysis QA Gate — sanity checks after each pipeline stage.

Catches impossible data before it propagates to the report. Each check
returns a count of violations. Zero = clean. Non-zero = investigate.

Three gate levels:
  - run_parser_qa(hands)    — after Stage 1+2 (parse + DP extraction)
  - run_analyzer_qa(stats, hands) — after Stage 3-6 (detectors + equity)
  - run_render_qa(html)     — after Stage 15 (rendered HTML)

Failures are logged as warnings (non-blocking) unless severity='error'.
The pipeline continues but the report carries a QA badge.
"""

import re


def run_parser_qa(hands):
    """Post-parser sanity checks. Run after parse + DP extraction."""
    results = {
        'pot_mismatch_count': 0,
        'impossible_stack_count': 0,
        'missing_eff_stack_count': 0,
        'invalid_board_count': 0,
        'villain_cards_no_showdown': 0,
        'missing_action_ledger': 0,
        'non_nlh_detected': 0,
        'duplicate_ids': 0,
        'disconnected_count': 0,
        'warnings': [],
        'errors': [],
    }

    seen_ids = set()
    for h in hands:
        hid = h.get('id', '?')

        # Duplicate detection
        if hid in seen_ids:
            results['duplicate_ids'] += 1
            results['warnings'].append(f"Duplicate hand ID: {hid}")
        seen_ids.add(hid)

        # Action ledger exists
        ledger = h.get('action_ledger') or []
        if not ledger and h.get('vpip'):
            results['missing_action_ledger'] += 1
            results['warnings'].append(f"{hid}: VPIP hand with no action_ledger")

        # Pot balance: sum of action_ledger amounts should approximate net result
        # (rough check — side pots and uncalled bets make exact match impossible)
        if ledger:
            hero_name = h.get('hero', '')
            hero_in = sum(e.get('amount_bb', 0) for e in ledger
                          if e.get('player') == hero_name
                          and e.get('action') in ('calls', 'bets', 'raises', 'posts'))
            hero_won = h.get('net_bb', 0)
            # If Hero put in X and result is -(X+epsilon), the pot math is consistent
            # Flag only gross mismatches (Hero "lost" more than they could have put in)
            if hero_in > 0 and hero_won < -(hero_in * 1.5 + 5):
                results['pot_mismatch_count'] += 1
                results['warnings'].append(
                    f"{hid}: pot mismatch — Hero invested {hero_in:.1f}BB "
                    f"but net is {hero_won:.1f}BB")

        # Impossible stacks
        stack = h.get('stack_bb', 0)
        if stack < 0:
            results['impossible_stack_count'] += 1
            results['errors'].append(f"{hid}: negative stack {stack}BB")
        elif stack > 500 and (h.get('buyin') or 0) < 100:
            results['impossible_stack_count'] += 1
            results['warnings'].append(f"{hid}: stack {stack}BB at micro buyin")

        # Effective stack on all-in hands
        if h.get('pf_allin') or h.get('flop_allin'):
            if not h.get('eff_stack_bb_at_decision') and not h.get('eff_stack_bb'):
                results['missing_eff_stack_count'] += 1
                results['warnings'].append(f"{hid}: all-in without eff_stack")

        # Board card count validity
        board = h.get('board') or []
        if len(board) not in (0, 3, 4, 5):
            results['invalid_board_count'] += 1
            results['warnings'].append(
                f"{hid}: invalid board length {len(board)}")

        # Villain cards without showdown
        villains = h.get('villains') or {}
        for vname, vdata in villains.items():
            if isinstance(vdata, dict) and vdata.get('shown_cards'):
                if not h.get('went_to_sd'):
                    results['villain_cards_no_showdown'] += 1
                    results['warnings'].append(
                        f"{hid}: villain {vname} has shown_cards but no showdown")

        # Game type detection
        gt = h.get('game_type', 'NLH')
        if gt != 'NLH':
            results['non_nlh_detected'] += 1

        # Disconnection
        if h.get('disconnected'):
            results['disconnected_count'] += 1

    return results


def run_analyzer_qa(stats, hands):
    """Post-analyzer sanity checks. Run after detectors + equity."""
    results = {
        'cooler_and_punt_overlap': 0,
        'formula_mismatch_count': 0,
        'non_nlh_in_detectors': 0,
        'disconnected_in_metrics': 0,
        'warnings': [],
        'errors': [],
    }

    # No hand flagged as both cooler AND punt
    cooler_ids = set()
    for c in (stats.get('coolers', {}).get('hands', []) or []):
        cooler_ids.add(c.get('id', ''))
    punt_ids = set()
    for p in (stats.get('punts', {}).get('hands', []) or []):
        punt_ids.add(p.get('id', ''))
    overlap = cooler_ids & punt_ids
    results['cooler_and_punt_overlap'] = len(overlap)
    if overlap:
        results['warnings'].append(
            f"Cooler+punt overlap: {', '.join(list(overlap)[:5])}")

    # Non-NLH hands should not appear in mistake list
    non_nlh = {h.get('id') for h in hands if h.get('game_type', 'NLH') != 'NLH'}
    mistake_ids = {m.get('id') for m in (stats.get('mistakes') or [])}
    bad = non_nlh & mistake_ids
    results['non_nlh_in_detectors'] = len(bad)
    if bad:
        results['errors'].append(
            f"Non-NLH hands in NLH detectors: {', '.join(list(bad)[:5])}")

    # Disconnected hands should not be in VPIP/PFR metrics
    disconnected_ids = {h.get('id') for h in hands if h.get('disconnected')}
    vpip_ids = stats.get('_vpip_hand_ids', set())
    if isinstance(vpip_ids, (set, list)):
        dc_in_vpip = disconnected_ids & set(vpip_ids)
        results['disconnected_in_metrics'] = len(dc_in_vpip)
        if dc_in_vpip:
            results['errors'].append(
                f"Disconnected hands in VPIP: {', '.join(list(dc_in_vpip)[:3])}")

    # Decision point pot-odds formula check
    for h in hands:
        for dp in (h.get('decision_points') or []):
            if (dp.get('math_type') == 'facing_bet'
                    and dp.get('hero_call_amount_bb')
                    and dp.get('final_pot_if_call_bb')
                    and dp.get('required_equity') is not None):
                expected = dp['hero_call_amount_bb'] / dp['final_pot_if_call_bb']
                if abs(dp['required_equity'] - expected) > 0.005:
                    results['formula_mismatch_count'] += 1
                    results['warnings'].append(
                        f"{dp['id']}: req_eq {dp['required_equity']:.4f} "
                        f"!= {expected:.4f}")

    return results


def run_render_qa(html):
    """Post-render sanity checks. Run on the rendered HTML string."""
    results = {
        'orphan_popup_ids': 0,
        'zero_bb_stacks': 0,
        'count_mismatch': False,
        'extreme_percentages': 0,
        'broken_anchors': 0,
        'warnings': [],
    }

    # (0BB) in rendered output
    results['zero_bb_stacks'] = len(re.findall(r'\(0BB\)', html))

    # Orphan popup IDs (data-hids entries without matching appendix cards)
    popup_ids = set()
    for m in re.findall(r'data-hids="([^"]+)"', html):
        for hid in m.split(','):
            hid = hid.strip()
            if hid:
                popup_ids.add(hid[-8:])  # normalize to 8-digit
    appendix_ids = set()
    for m in re.findall(r"data-hand-id='(\d{8})'", html):
        appendix_ids.add(m)
    orphans = popup_ids - appendix_ids
    results['orphan_popup_ids'] = len(orphans)

    # Forbidden tokens — schema/operator strings that shouldn't reach the reader
    _forbidden = ['__synthesis__', '.leaks[', 'equity TBD', 'HERO_AGGRESSIVE',
                  'MISSED_AGGRESSION', 'TOO_AGGRESSIVE', 'CORRECTLY_PASSIVE',
                  'pending analyst', 'to resolve']
    _fcount = 0
    for _ft in _forbidden:
        _fc = html.count(_ft)
        if _fc:
            _fcount += _fc
            results['warnings'].append(f"Forbidden token '{_ft}': {_fc} occurrences")
    results['forbidden_tokens'] = _fcount

    # Extreme percentages in non-sizing columns (>1000%)
    # Sizing columns legitimately have large values (15x pot = 1500%)
    extreme = re.findall(r'>(\d{4,})\.?\d*%<', html)
    results['extreme_percentages'] = len(extreme)

    # Broken internal anchors
    anchors = set(re.findall(r'id="([^"]+)"', html))
    hrefs = set(re.findall(r'href="#([^"]+)"', html))
    # Filter out JS-generated patterns
    real_hrefs = {h for h in hrefs if not h.startswith("'+") and not h.startswith("${")
                  and not h.startswith("list-")}
    broken = real_hrefs - anchors
    results['broken_anchors'] = len(broken)
    if broken:
        results['warnings'].append(
            f"Broken anchors: {', '.join(list(broken)[:10])}")

    return results


def print_qa_summary(label, results):
    """Print a human-readable QA summary."""
    errors = results.get('errors', [])
    warnings = results.get('warnings', [])

    # Count non-zero numeric fields
    issues = sum(1 for k, v in results.items()
                 if isinstance(v, (int, float)) and v > 0
                 and k not in ('disconnected_count', 'non_nlh_detected'))

    if errors:
        print(f"  QA {label}: {len(errors)} ERROR(s), {len(warnings)} warning(s)")
        for e in errors[:5]:
            print(f"    ERROR: {e}")
    elif issues:
        print(f"  QA {label}: {issues} issue(s), {len(warnings)} warning(s)")
    else:
        print(f"  QA {label}: CLEAN")

    for w in warnings[:10]:
        print(f"    warn: {w}")
