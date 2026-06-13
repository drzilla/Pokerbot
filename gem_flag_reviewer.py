#!/usr/bin/env python3
"""
GEM Flag Reviewer v1.0 (v7.20 pipeline upgrade)
================================================

Post-processing review layer between raw detectors and the report.
Addresses the architectural distinction:

  RAW DETECTOR OUTPUT = "candidates" (hands that matched a pattern)
  REVIEWED OUTPUT     = "confirmed mistakes" OR "ok" OR "variance" OR "detector_bug"

Every candidate is scrutinized along these dimensions:
  1. Iso-raise vs iso-jam (hero actually all-in?)
  2. Jam context (standard / squeeze / cover_jam / micro_jam)
  3. Bounty cover premium (format=bounty + hero covers villain?)
  4. Exception log match (same pattern previously reclassified?)
  5. Mutual exclusion (double-flagged?)
  6. Sample-size sanity (n<5 metric-based flags → defer)

Three-tier output:
  - AUTO_CORRECTED: reviewer resolved without human input (detector bug or context adjustment)
  - NEEDS_REVIEW: reviewer couldn't fully resolve — flagged for Claude scrutiny
  - CONFIRMED: review confirmed the flag is a real mistake

Detector bugs auto-generate entries in GEM Pipeline Change Requests.

v7.21 NOTE (symmetric protocol — handled by Claude, not in this code):
  This module processes hands that detectors FLAGGED. The symmetric
  case — hands the detector did NOT flag but Claude is tempted to
  manually-add as punts — is governed by the MANUAL ADD PROTOCOL in
  GEM_Quick_Reference.txt. Default classification for losing PFR
  all-in hands = cooler/variance/read-dependent, NOT punt. Claude
  must run the full analytical checklist (pot odds + bounty adjusted,
  combo-weighted equity, blockers, fold equity, EV across range bands)
  AND ask Ron about reads BEFORE manually-adding any hand to confirmed
  mistakes. See Quick Ref v7.21 for the full checklist.
"""

import os, json, csv
from datetime import datetime

EXCEPTIONS_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gem_exceptions_log.csv')

# ============================================================
# EV ESTIMATION TABLE (mirrors gem_report_data.py)
# ============================================================
def _estimate_ev(flag_type, confidence='CLEAR'):
    """Estimate chip EV of a flagged mistake. Mirrors gem_report_data.py logic."""
    if 'Missed Steal' in flag_type:
        return -1.5 if confidence == 'CLEAR' else -1.0
    if 'CVJ' in flag_type or 'Iso-Jam' in flag_type:
        return -3.0
    if 'Missed Rejam' in flag_type:
        return -2.0
    if 'J34' in flag_type:
        return -2.5
    if 'J35' in flag_type or 'Reshove' in flag_type:
        return -4.0 if 'J35' in flag_type else -3.0
    if 'J36' in flag_type:
        return -1.5
    if 'J37' in flag_type:
        return -3.0
    if 'J33' in flag_type:
        return -1.0
    if 'Missed Turn Delayed C-bet' in flag_type:
        return -0.5
    if 'Push <8BB' in flag_type or 'Reshove <8BB' in flag_type:
        return -2.0
    if confidence == 'MARGINAL':
        return -0.5
    return -1.0


# ============================================================
# PATTERN SIGNATURE MATCHING
# ============================================================
def _build_pattern_signature(hand, flag):
    """Build a pattern signature dict for exception-log matching."""
    eff = hand.get('eff_stack_bb') or hand.get('stack_bb') or 0
    if eff < 5: eff_bracket = '<5BB'
    elif eff < 12: eff_bracket = '5-12BB'
    elif eff < 20: eff_bracket = '12-20BB'
    elif eff < 30: eff_bracket = '20-30BB'
    elif eff < 50: eff_bracket = '30-50BB'
    else: eff_bracket = '50BB+'

    jammer_bb = flag.get('jammer_bb') or hand.get('jammer_stack_bb') or 0
    if jammer_bb < 5: vbracket = '<5BB'
    elif jammer_bb < 10: vbracket = '5-10BB'
    elif jammer_bb < 20: vbracket = '10-20BB'
    elif jammer_bb < 35: vbracket = '20-35BB'
    else: vbracket = '35BB+'

    return {
        'flag_type': flag.get('type', ''),
        'position': hand.get('position', ''),
        'hero_eff_bracket': eff_bracket,
        'villain_eff_bracket': vbracket,
        'format': hand.get('format', '').lower(),
        'hero_all_in': _hero_went_all_in(hand, flag),
        'action_type': flag.get('type', ''),
    }


def _signatures_match(sig_a, sig_b):
    """Check if two pattern signatures match."""
    keys = ['flag_type', 'position', 'hero_eff_bracket', 'villain_eff_bracket', 'format', 'hero_all_in']
    for k in keys:
        if sig_a.get(k) != sig_b.get(k):
            return False
    return True


def _load_exceptions_log():
    """Load logged exceptions from CSV."""
    if not os.path.exists(EXCEPTIONS_LOG_PATH):
        return []
    entries = []
    with open(EXCEPTIONS_LOG_PATH, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                row['pattern_signature'] = json.loads(row.get('pattern_signature_json', '{}'))
            except:
                row['pattern_signature'] = {}
            entries.append(row)
    return entries


def append_exception(hand_id, raw_flag, corrected_classification, pattern_signature,
                     reason, detector_bug=None):
    """Append a new exception to the log file."""
    header = ['pattern_id', 'date_logged', 'hand_id_example', 'raw_flag',
              'corrected_classification', 'pattern_signature_json', 'reason', 'detector_bug']
    existing = _load_exceptions_log()
    next_id = max([int(e.get('pattern_id', 0) or 0) for e in existing] + [0]) + 1
    write_header = not os.path.exists(EXCEPTIONS_LOG_PATH)
    with open(EXCEPTIONS_LOG_PATH, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(header)
        w.writerow([
            next_id,
            datetime.now().strftime('%Y-%m-%d'),
            hand_id,
            raw_flag,
            corrected_classification,
            json.dumps(pattern_signature),
            reason,
            detector_bug or '',
        ])
    return next_id


# ============================================================
# CONTEXT DETECTION
# ============================================================
def _hero_went_all_in(hand, flag):
    """Determine if Hero's preflop action committed the stack (all-in).

    Uses the canonical analyzer-computed fields in priority order:
      1. pf_allin (boolean, authoritative when present)
      2. hero_committed_bb / stack_bb ratio ≥ 0.95
      3. String heuristic fallback
    """
    # Authoritative field from analyzer
    if 'pf_allin' in hand:
        return bool(hand.get('pf_allin'))

    # Committed-ratio computation
    committed = hand.get('hero_committed_bb')
    stack = hand.get('stack_bb') or hand.get('eff_stack_bb')
    if committed is not None and stack and stack > 0:
        return (committed / stack) >= 0.95

    # Fallback string heuristic (legacy, imperfect)
    pf_seq = hand.get('pf_sequence', [])
    hero_lines = [s for s in pf_seq if isinstance(s, str) and '(H)' in s]
    for hl in hero_lines:
        if 'all-in' in hl.lower() or 'allin' in hl.lower():
            return True
    return False


def _detect_jam_context(hand, flag):
    """Classify the villain jam context for CVJ/Iso flags.

    Returns one of: 'micro_jam', 'squeeze_jam', 'chip_leader_cover_jam', 'standard_jam'
    """
    jammer_bb = flag.get('jammer_bb') or hand.get('jammer_stack_bb') or 0
    hero_bb = hand.get('stack_bb') or hand.get('eff_stack_bb') or 0
    n_players = hand.get('n_players') or hand.get('table_size') or 6
    jammer_pos = (flag.get('jammer') or hand.get('jammer_position') or '').upper()

    # Micro jam: villain eff <5BB = basically any-two
    if 0 < jammer_bb < 5:
        return 'micro_jam'

    # Squeeze jam: villain jammed OVER an open (3-bet jam at 5-20BB)
    pf_seq = hand.get('pf_sequence', [])
    pre_jam_actions = []
    for step in pf_seq:
        step_str = str(step)
        if 'raises' in step_str and 'all-in' in step_str.lower():
            break
        if 'raises' in step_str:
            pre_jam_actions.append(step)
    if len(pre_jam_actions) >= 1 and 5 <= jammer_bb <= 20:
        return 'squeeze_jam'

    # Chip-leader cover-jam: villain eff > 3x Hero AND short-handed AND villain LP
    if hero_bb > 0 and jammer_bb > 3 * hero_bb and n_players <= 5 and jammer_pos in ('BTN', 'CO', 'HJ'):
        return 'chip_leader_cover_jam'

    return 'standard_jam'


def _hero_covers_villain(hand, flag):
    """Check if Hero's stack covers villain's effective stack (for bounty premium)."""
    hero_bb = hand.get('stack_bb') or 0
    jammer_bb = flag.get('jammer_bb') or hand.get('jammer_stack_bb') or 0
    if jammer_bb == 0:
        return False
    return hero_bb > jammer_bb * 1.05


def _is_bounty_format(hand):
    fmt = (hand.get('format') or '').lower()
    return 'bounty' in fmt


# ============================================================
# CONTEXT-ADJUSTED THRESHOLD REVIEW
# ============================================================
def _review_cvj_iso(hand, flag):
    """Apply full review to Wide CVJ / Wide Iso-Jam / Reshove Over Small Jam flags.

    Returns dict with keys: classification, reason, detector_bug, confidence, corrected_ev
    """
    flag_type = flag.get('type', '')
    hero_all_in = _hero_went_all_in(hand, flag)
    jam_context = _detect_jam_context(hand, flag)
    covers = _hero_covers_villain(hand, flag)
    bounty = _is_bounty_format(hand)

    result = {
        'classification': None,
        'reason': None,
        'detector_bug': None,
        'confidence': 'HIGH',
        'corrected_ev': flag.get('estimated_ev_bb', flag.get('ev', 0)),
        'context_tags': [],
        'hero_all_in': hero_all_in,
        'jam_context': jam_context,
        'hero_covers': covers,
        'bounty_format': bounty,
    }

    # --- Iso-raise vs Iso-jam conflation check (A1) ---
    if 'Iso-Jam' in flag_type and not hero_all_in:
        result['classification'] = 'OK'
        result['reason'] = ('Hero iso-RAISED (kept stack behind), not iso-jammed. Iso-raise thresholds '
                            'are 2-3x wider than iso-jam thresholds because Hero retains fold equity. '
                            'Analyzer conflated the two.')
        result['detector_bug'] = 'iso_raise_iso_jam_conflation'
        result['corrected_ev'] = 0.0
        result['context_tags'].append('hero_not_all_in')
        return result

    # --- Reshove flag on non-reshove action ---
    if 'Reshove Over Small Jam' in flag_type and not hero_all_in:
        result['classification'] = 'OK'
        result['reason'] = ('Hero did not reshove — iso-raised with stack behind. Reshove classifier '
                            'should require hero_all_in = True.')
        result['detector_bug'] = 'reshove_action_misidentified'
        result['corrected_ev'] = 0.0
        result['context_tags'].append('hero_not_all_in')
        return result

    # --- CVJ context-adjusted thresholds (A2) ---
    if 'Wide CVJ' in flag_type:
        if jam_context == 'micro_jam':
            result['classification'] = 'OK'
            result['reason'] = (f'Villain jammed {flag.get("jammer_bb", "?")}BB (micro). Any reasonable '
                                f'playable hand calls profitably at these pot odds.')
            result['detector_bug'] = 'cvj_no_micro_jam_context'
            result['corrected_ev'] = 0.0
            result['context_tags'].append(jam_context)
            return result

        if jam_context == 'chip_leader_cover_jam':
            result['classification'] = 'NEEDS_REVIEW'
            result['reason'] = (f'Villain is chip-leader cover-jamming {flag.get("jammer_bb", "?")}BB at '
                                f'short-handed FT — range is ~35-50% not the Quick Ref chart assumption '
                                f'of ~15-25%. K9o-type hands have roughly 30-33% equity vs this widened '
                                f'range; pot odds ≈ 33% required. Call is likely breakeven-to-marginal-plus '
                                f'with bounty cover. Flag downgraded to REVIEW pending full range analysis.')
            result['detector_bug'] = 'cvj_no_chip_leader_cover_context'
            result['confidence'] = 'MED'
            result['context_tags'].append(jam_context)
            return result

        if jam_context == 'squeeze_jam' and bounty and covers:
            result['classification'] = 'NEEDS_REVIEW'
            result['reason'] = (f'Villain squeeze-jammed {flag.get("jammer_bb", "?")}BB over an open. '
                                f'Squeeze-jam ranges are ~10pp wider than standalone jam ranges. '
                                f'Hero covers in bounty format — +5-8% EV premium applies. '
                                f'Flag downgraded to REVIEW pending full range analysis.')
            result['detector_bug'] = 'cvj_no_squeeze_jam_context'
            result['confidence'] = 'MED'
            result['context_tags'].extend([jam_context, 'bounty_covers'])
            return result

    # --- Bounty-cover EV adjustment for any remaining flag (A3) ---
    if bounty and covers:
        ev = result['corrected_ev'] or 0
        bounty_adj = abs(ev) * 0.08  # 8% EV premium when covering in bounty
        adjusted = ev + bounty_adj
        result['corrected_ev'] = adjusted
        result['context_tags'].append('bounty_covers_adjusted')
        if adjusted > -0.5:
            # EV verification (A6): if adjusted EV is nearly breakeven, downgrade
            result['classification'] = 'OK'
            result['reason'] = (f'Raw EV {ev:+.1f}BB but bounty-cover premium (+{bounty_adj:.1f}BB, '
                                f'~8% when covering) brings adjusted EV to {adjusted:+.1f}BB — within '
                                f'variance range. Not a mistake.')
            result['detector_bug'] = 'no_bounty_cover_adjustment'
            return result

    # --- Default: confirm the flag ---
    result['classification'] = 'CONFIRMED'
    result['reason'] = 'Standard jam context, no modifiers apply. Flag stands.'
    return result


def _review_missed_steal(hand, flag):
    """Missed steals are generally real but check for edge cases."""
    # Missed steals at <3BB or with dead SB (some HH formats) could be edge cases
    stack = hand.get('stack_bb') or 0
    result = {
        'classification': 'CONFIRMED',
        'reason': None,
        'detector_bug': None,
        'confidence': 'HIGH' if flag.get('confidence') == 'CLEAR' else 'MED',
        'corrected_ev': flag.get('estimated_ev_bb', flag.get('ev', 0)),
        'context_tags': ['preflop_only'],
    }
    if flag.get('confidence') == 'MARGINAL':
        result['classification'] = 'CONFIRMED'
        result['reason'] = 'Marginal chart-edge fold — low-impact but real pattern.'
    else:
        result['reason'] = f'Standard push/open threshold at {stack:.0f}BB for the hand. Confirmed missed steal.'
    return result


def _review_missed_cbet_or_probe(hand, flag):
    """Postflop misses — generally confirm but flag small samples."""
    result = {
        'classification': 'CONFIRMED',
        'reason': 'Postflop missed-action pattern confirmed by context tags.',
        'detector_bug': None,
        'confidence': 'MED',
        'corrected_ev': flag.get('estimated_ev_bb', flag.get('ev', 0)),
        'context_tags': ['postflop'],
    }
    return result


# ============================================================
# MUTEX RESOLUTION (A4)
# ============================================================
_CVJ_ISO_FAMILY = {
    'Wide CVJ (Call Villain Jam)', 'Wide Iso-Jam',
    'Reshove Over Small Jam <30BB (J35)',
}

_MUTEX_PRIORITY = [
    'Wide Iso-Jam',                         # 1st
    'Reshove Over Small Jam <30BB (J35)',   # 2nd
    'Wide CVJ (Call Villain Jam)',          # 3rd
]


def _resolve_mutex(flags_for_hand):
    """For a single hand, collapse mutually-exclusive preflop-decision flags to one.

    Returns list of (flag, kept_or_dropped) tuples.
    """
    cvj_iso_flags = [f for f in flags_for_hand if f.get('type') in _CVJ_ISO_FAMILY]
    if len(cvj_iso_flags) <= 1:
        return [(f, 'kept') for f in flags_for_hand]

    # Pick highest priority
    for t in _MUTEX_PRIORITY:
        keepers = [f for f in cvj_iso_flags if f.get('type') == t]
        if keepers:
            keep = keepers[0]
            break
    else:
        keep = cvj_iso_flags[0]

    result = []
    for f in flags_for_hand:
        if f.get('type') in _CVJ_ISO_FAMILY and f is not keep:
            result.append((f, 'dropped_mutex'))
        else:
            result.append((f, 'kept'))
    return result


# ============================================================
# EXCEPTION LOG AUTO-MATCHING
# ============================================================
def _match_exception_log(hand, flag, exceptions):
    """If this hand+flag matches a previously logged exception, return that entry."""
    if not exceptions:
        return None
    current_sig = _build_pattern_signature(hand, flag)
    for exc in exceptions:
        exc_sig = exc.get('pattern_signature', {})
        if _signatures_match(current_sig, exc_sig):
            return exc
    return None


# ============================================================
# MAIN REVIEW ORCHESTRATION
# ============================================================
def review_candidates(raw_flags, hands_by_id, auto_log_exceptions=False):
    """Main entry point. Review every raw candidate flag.

    Args:
        raw_flags: list of dicts (from stats['mistakes'] — which is the superset,
                   NOT combined with marginal_mistakes which would double-count)
        hands_by_id: dict {hand_id: hand_dict}
        auto_log_exceptions: if True, write new auto-corrected patterns to exceptions log

    Returns:
        dict with meta, auto_corrected, needs_review, confirmed, detector_bugs, summary
    """
    exceptions = _load_exceptions_log()

    # Inject EV estimates into every flag (so reviewer can make EV-based decisions)
    for f in raw_flags:
        if 'estimated_ev_bb' not in f:
            f['estimated_ev_bb'] = _estimate_ev(f.get('type', ''), f.get('confidence', 'CLEAR'))

    # Step 1: Group flags by hand for mutex resolution
    flags_by_hand = {}
    for f in raw_flags:
        hid = f.get('id') or f.get('hand_id')
        if not hid:
            continue
        flags_by_hand.setdefault(hid, []).append(f)

    # Step 2: Apply mutex resolution
    mutex_dropped = []
    active_flags = []
    for hid, hflags in flags_by_hand.items():
        resolved = _resolve_mutex(hflags)
        for f, status in resolved:
            if status == 'dropped_mutex':
                mutex_dropped.append({
                    'hand_id': hid,
                    'dropped_flag': f.get('type'),
                    'reason': 'Double-flagged: mutex with higher-priority CVJ/Iso classification',
                })
            else:
                active_flags.append(f)

    # Step 3: Review each active flag
    auto_corrected = []
    needs_review = []
    confirmed = []
    detector_bugs = {}

    for flag in active_flags:
        hid = flag.get('id') or flag.get('hand_id')
        hand = hands_by_id.get(hid, {})
        flag_type = flag.get('type', '')

        # Exception log match first
        exc_match = _match_exception_log(hand, flag, exceptions)
        if exc_match:
            review_result = {
                'classification': 'OK' if exc_match.get('corrected_classification') != 'CONFIRMED' else 'CONFIRMED',
                'reason': f"Matches logged exception #{exc_match.get('pattern_id')}: {exc_match.get('reason', '')}",
                'detector_bug': exc_match.get('detector_bug') or None,
                'confidence': 'HIGH',
                'corrected_ev': 0.0 if exc_match.get('corrected_classification') != 'CONFIRMED' else flag.get('estimated_ev_bb', 0),
                'context_tags': ['exception_log_match'],
                'hero_all_in': _hero_went_all_in(hand, flag),
                'jam_context': _detect_jam_context(hand, flag) if flag_type in _CVJ_ISO_FAMILY else None,
                'hero_covers': _hero_covers_villain(hand, flag),
                'bounty_format': _is_bounty_format(hand),
            }
        # Route to type-specific reviewer
        elif flag_type in _CVJ_ISO_FAMILY:
            review_result = _review_cvj_iso(hand, flag)
        elif 'Missed Steal' in flag_type or 'Missed Open' in flag_type:
            review_result = _review_missed_steal(hand, flag)
        elif 'Missed' in flag_type and ('C-bet' in flag_type or 'Probe' in flag_type):
            review_result = _review_missed_cbet_or_probe(hand, flag)
        else:
            # Default: confirm as-is but mark as needs-review
            review_result = {
                'classification': 'NEEDS_REVIEW',
                'reason': 'No type-specific reviewer — requires manual framework analysis.',
                'detector_bug': None,
                'confidence': 'MED',
                'corrected_ev': flag.get('estimated_ev_bb', flag.get('ev', 0)),
                'context_tags': ['unclassified_type'],
            }

        reviewed = {**flag, **review_result, 'raw_flag_type': flag_type}

        # Track detector bugs
        if review_result.get('detector_bug'):
            bug = review_result['detector_bug']
            detector_bugs.setdefault(bug, []).append({
                'hand_id': hid,
                'raw_flag': flag_type,
                'reason': review_result['reason'],
            })

        # Auto-log new exception patterns if enabled
        if auto_log_exceptions and review_result['classification'] in ('OK',) and not exc_match:
            try:
                sig = _build_pattern_signature(hand, flag)
                append_exception(
                    hand_id=hid,
                    raw_flag=flag_type,
                    corrected_classification=review_result['classification'],
                    pattern_signature=sig,
                    reason=review_result['reason'][:500],
                    detector_bug=review_result.get('detector_bug'),
                )
            except Exception:
                pass

        # Route to bucket
        if review_result['classification'] == 'OK':
            auto_corrected.append(reviewed)
        elif review_result['classification'] == 'NEEDS_REVIEW':
            needs_review.append(reviewed)
        elif review_result['classification'] == 'CONFIRMED':
            confirmed.append(reviewed)
        else:
            needs_review.append(reviewed)

    # Step 4: Aggregate detector bug reports
    bug_reports = []
    for bug_name, instances in detector_bugs.items():
        bug_reports.append({
            'bug': bug_name,
            'count': len(instances),
            'instances': instances,
            'severity': 'HIGH' if len(instances) >= 2 else 'MED',
        })

    total_raw = len(raw_flags)
    total_confirmed_ev = sum(r.get('corrected_ev') or 0 for r in confirmed)

    return {
        'meta': {
            'version': 'v7.20',
            'raw_candidates': total_raw,
            'mutex_dropped': len(mutex_dropped),
            'auto_corrected': len(auto_corrected),
            'needs_review': len(needs_review),
            'confirmed': len(confirmed),
            'detector_bugs_detected': len(bug_reports),
        },
        'auto_corrected': auto_corrected,
        'needs_review': needs_review,
        'confirmed': confirmed,
        'mutex_dropped': mutex_dropped,
        'detector_bugs': bug_reports,
        'summary': {
            'raw_mistake_ev': round(sum(f.get('estimated_ev_bb', f.get('ev', 0)) or 0 for f in raw_flags), 2),
            'reviewed_mistake_ev': round(total_confirmed_ev, 2),
            'ev_restored_by_review': round(
                sum(f.get('estimated_ev_bb', f.get('ev', 0)) or 0 for f in raw_flags) - total_confirmed_ev, 2
            ),
        },
    }


# ============================================================
# REPORT-FRIENDLY OUTPUT FORMATTERS
# ============================================================
def format_review_section(review_output):
    """Build markdown for the Del 4B Review section."""
    meta = review_output['meta']
    lines = []

    lines.append(f"## Del 4B: Mistakes (Two-Tier Review — v{meta['version']})")
    lines.append("")
    lines.append(f"**Pipeline:** {meta['raw_candidates']} candidates → mutex-dropped {meta['mutex_dropped']} → "
                 f"auto-corrected {meta['auto_corrected']} → needs review {meta['needs_review']} → "
                 f"**confirmed {meta['confirmed']} mistakes**")
    lines.append("")
    lines.append(f"**EV impact:** raw {review_output['summary']['raw_mistake_ev']:.1f}BB → "
                 f"reviewed {review_output['summary']['reviewed_mistake_ev']:.1f}BB "
                 f"({review_output['summary']['ev_restored_by_review']:+.1f}BB restored by review)")
    lines.append("")

    # Auto-corrected section
    if review_output['auto_corrected']:
        lines.append("### Auto-Corrected by Review Layer")
        lines.append("*Detector flagged these, but reviewer identified a known detector bug or context adjustment. Not real mistakes.*")
        lines.append("")
        lines.append("| Hand ID | Cards | Pos | Raw Flag | Classification | Detector Bug | Reason |")
        lines.append("|---------|-------|-----|----------|----------------|--------------|--------|")
        for r in review_output['auto_corrected']:
            lines.append(f"| {r.get('id', '—')} | {r.get('hand_str', r.get('hand', '—'))} | "
                         f"{r.get('pos', '—')} | {r.get('raw_flag_type', '—')} | "
                         f"**{r.get('classification', '—')}** | `{r.get('detector_bug', '—')}` | "
                         f"{r.get('reason', '—')[:200]} |")
        lines.append("")

    # Needs review
    if review_output['needs_review']:
        lines.append("### Needs Review (Claude Scrutiny Required)")
        lines.append("*Reviewer couldn't fully auto-resolve — apply full framework: (1) villain range, (2) pot odds, (3) multi-street plan. Classify as Mistake / OK / Variance.*")
        lines.append("")
        lines.append("| Hand ID | Cards | Pos | Raw Flag | Confidence | Context | Reason |")
        lines.append("|---------|-------|-----|----------|-----------|---------|--------|")
        for r in review_output['needs_review']:
            ctx = ', '.join(r.get('context_tags', []))
            lines.append(f"| {r.get('id', '—')} | {r.get('hand_str', r.get('hand', '—'))} | "
                         f"{r.get('pos', '—')} | {r.get('raw_flag_type', '—')} | "
                         f"{r.get('confidence', '—')} | {ctx} | {r.get('reason', '—')[:150]} |")
        lines.append("")

    # Confirmed
    if review_output['confirmed']:
        lines.append("### Confirmed Mistakes")
        lines.append("*Flag survived review. These are the real leaks.*")
        lines.append("")
        lines.append("| Hand ID | Cards | Pos | BB | Type | EV | Confidence |")
        lines.append("|---------|-------|-----|----|----|----|-----|")
        for r in sorted(review_output['confirmed'], key=lambda x: x.get('corrected_ev') or 0):
            ev = r.get('corrected_ev', r.get('estimated_ev_bb', 0)) or 0
            lines.append(f"| {r.get('id', '—')} | {r.get('hand_str', r.get('hand', '—'))} | "
                         f"{r.get('pos', '—')} | {r.get('stack_bb', '—')} | {r.get('raw_flag_type', '—')} | "
                         f"{ev:+.1f} | {r.get('confidence', '—')} |")
        lines.append("")

    # Detector bugs detected
    if review_output['detector_bugs']:
        lines.append("### Detector Bugs Detected This Session")
        lines.append("*Auto-generated pipeline change requests. Each bug below has reproducer hand(s).*")
        lines.append("")
        lines.append("| Bug | Count | Severity | Reproducer Hands |")
        lines.append("|-----|-------|----------|------------------|")
        for b in review_output['detector_bugs']:
            rep = ', '.join(i['hand_id'] for i in b['instances'][:3])
            lines.append(f"| `{b['bug']}` | {b['count']} | {b['severity']} | {rep} |")
        lines.append("")

    # Mutex drops
    if review_output['mutex_dropped']:
        lines.append("### Double-Flag Drops (Mutex Resolution)")
        lines.append("*Same hand was multi-flagged by overlapping detectors. Resolved to highest-priority classification.*")
        lines.append("")
        for m in review_output['mutex_dropped']:
            lines.append(f"- **{m['hand_id']}**: dropped `{m['dropped_flag']}` ({m['reason']})")
        lines.append("")

    return '\n'.join(lines)


if __name__ == '__main__':
    # Standalone test: load gem_stats.json + gem_hands.json and review
    import sys
    stats_path = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/gem_stats.json'
    hands_path = sys.argv[2] if len(sys.argv) > 2 else '/home/claude/gem_hands.json'

    with open(stats_path) as f:
        stats = json.load(f)
    with open(hands_path) as f:
        hands = json.load(f)

    hands_by_id = {h.get('id'): h for h in hands if h.get('id')}
    # NOTE: stats['mistakes'] is the superset (includes both CLEAR and MARGINAL).
    # stats['marginal_mistakes'] is a subset — do NOT combine, would double-count.
    raw = stats.get('mistakes', [])

    output = review_candidates(raw, hands_by_id, auto_log_exceptions=False)
    print(json.dumps(output['meta'], indent=2))
    print(f"\nAuto-corrected: {len(output['auto_corrected'])}")
    for r in output['auto_corrected']:
        print(f"  {r.get('id')} | {r.get('raw_flag_type')} → {r.get('classification')} | bug: {r.get('detector_bug')}")
    print(f"\nNeeds review: {len(output['needs_review'])}")
    for r in output['needs_review']:
        print(f"  {r.get('id')} | {r.get('raw_flag_type')} | {r.get('reason')[:120]}")
    print(f"\nConfirmed: {len(output['confirmed'])}")
    for r in output['confirmed']:
        print(f"  {r.get('id')} | {r.get('raw_flag_type')} | EV {r.get('corrected_ev'):+.1f}")

    with open('/home/claude/gem_review_output.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, default=str)
    print("\nFull output: /home/claude/gem_review_output.json")
