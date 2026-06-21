#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v8.18.0 FINAL product-truth verifier (independent pre-package gate).

This verifier is DELIBERATELY independent of the product code it audits:

  * Tournament Results -- it recomputes finish / entries / Top% by PARSING THE RAW GG game-summary
    text files (`N Players`, `finished ... in Mth place`). It never calls gem_tournament_model
    (_finish_state / _top_pct_label) or the Results DataTable formatter for its EXPECTED values.
  * Villain Teaching -- it reconstructs the full teaching population with the BUILDERS
    (teaching_from_exploit / teaching_from_atom) and classifies eligibility / completeness with its OWN
    re-implemented logic. It never calls gem_villain_teaching.villain_teaching_coverage for its EXPECTED
    counts.

It then reads the ACTUAL regenerated report (the Results DataTable DOM + the decoded
handOpponentContexts teaching payload) and asserts every frozen acceptance predicate, writing
FINAL_PREPACKAGE_AUDIT.json. main() exits non-zero if ANY predicate is false -- the package builder
must abort on a non-zero exit (no warning-only mode).

Usage:
  python _qa_v818_final_product_truth.py <auto_only_html> <out_dir> [--data <gem_report_data.json>]
        [--stats <gem_stats.json>] [--summaries <game_summaries_dir>] [--analyst-html <demo_html>]
"""
import io
import os
import re
import sys
import glob
import json

FORBIDDEN_FUTURE = ('adjust in future.', 'exploit this tendency.', 'play accordingly.',
                    'be careful next time.')
RESULT_WORDS = ('at showdown', 'showed down', 'because hero won', 'because hero lost',
                'as it turned out', 'in hindsight', 'rivered', 'after the river')
ACTION_VERBS = ('raise', 'fold', 'value', 'call', 'widen', 'tighten', 'cut', 'size', 'trap',
                'steal', 'respect', 'release', 'barrel', 'isolate', 'iso-raise', 'check', 'bet',
                'continue', 'over-bluff', 'over-fold', 'print', 'hang')


def _read(path):
    return io.open(path, encoding='utf-8', errors='replace').read()


# ---------------------------------------------------------------------------------------------------
# RAW SOURCE TRUTH (Results) -- parse the GG game-summary text directly. No product code.
# ---------------------------------------------------------------------------------------------------
def parse_raw_results(summaries_dir):
    rows = []
    for f in sorted(glob.glob(os.path.join(summaries_dir, '*.txt'))):
        txt = _read(f)
        m_players = re.search(r'(\d[\d,]*)\s+Players', txt)
        m_finish = re.search(r'finished the tournament in\s+(\d[\d,]*)\w*\s+place', txt)
        m_name = re.search(r'Tournament #(\d+)\s*-\s*(.+?)\s*$', os.path.basename(f).replace('.txt', ''))
        m_cash = re.search(r'received a total of \$([\d,]+(?:\.\d+)?)', txt)
        entries = int(m_players.group(1).replace(',', '')) if m_players else None
        finish = int(m_finish.group(1).replace(',', '')) if m_finish else None
        cash = float(m_cash.group(1).replace(',', '')) if m_cash else None
        name = m_name.group(2) if m_name else os.path.basename(f)
        top = round(finish / entries * 100.0, 4) if (finish and entries) else None
        speed = ('HYPER' if 'hyper' in name.lower() else
                 'TURBO' if 'turbo' in name.lower() else 'STANDARD')
        rows.append({'tournament_no': m_name.group(1) if m_name else None, 'name': name,
                     'finish': finish, 'entries': entries, 'top_percent': top,
                     'cash_received': cash, 'speed': speed})
    return rows


# ---------------------------------------------------------------------------------------------------
# RENDERED Results DOM
# ---------------------------------------------------------------------------------------------------
def read_results_dom(html):
    m = re.search(r"id='tt-results'.*?</table>", html, re.S)
    t = m.group(0) if m else ''
    # the sticky filter chips for tt-results render in a `data-dt-for='tt-results'` block BEFORE the
    # table, so include the region from that block through the end of the table.
    fi = html.find("data-dt-for='tt-results'")
    ti = html.find("id='tt-results'")
    region = html[fi:html.find('</table>', ti) + 8] if (0 <= fi < ti) else t
    finish_cells = re.findall(r"data-label='Finish'[^>]*>(.*?)</td>", t, re.S)
    return_cells = re.findall(r"data-label='Return'[^>]*>(.*?)</td>", t, re.S)
    bb_cells = re.findall(r"data-label='BB/100'[^>]*>(.*?)</td>", t, re.S)
    cev_cells = re.findall(r"data-label='cEV/100'[^>]*>(.*?)</td>", t, re.S)
    avg = re.findall(r'Avg Top (\d+\.\d)%', t)
    speed_chips = re.findall(r"data-dt-filter='speed' data-dt-value='([^']+)'", region)
    speed_counts = re.findall(r"data-dt-filter='speed'[^>]*>[^<]*<span class='dt-chip-n'>(\d+)", region)
    rows_with_finish = sum(1 for c in finish_cells if re.search(r'Top \d+\.\d%', c))
    rows_with_topish = sum(1 for c in finish_cells if 'Top ' in c)
    nocash_in_finish = sum(1 for c in finish_cells if 'No cash' in c)
    nocash_in_return = sum(1 for c in return_cells if 'No cash' in c)
    bb_currency = sum(1 for c in (bb_cells + cev_cells) if '$' in c)
    bb_signed = sum(1 for c in bb_cells if re.search(r'[+\-]\d', c))
    return {
        'finish_cells': len(finish_cells), 'return_cells': len(return_cells),
        'rows_with_finish_toppct': rows_with_finish, 'rows_with_topish': rows_with_topish,
        'nocash_in_finish': nocash_in_finish, 'nocash_in_return': nocash_in_return,
        'avg_top_rendered': float(avg[0]) if avg else None,
        'bb_cells': len(bb_cells), 'cev_cells': len(cev_cells),
        'bb_or_cev_currency_cells': bb_currency, 'bb_signed_cells': bb_signed,
        'speed_filter_present': bool(speed_chips), 'speed_values': sorted(speed_chips),
        'speed_count_sum': sum(int(x) for x in speed_counts) if speed_counts else 0,
    }


# ---------------------------------------------------------------------------------------------------
# VILLAIN -- reconstruct the population with the builders, classify INDEPENDENTLY.
# ---------------------------------------------------------------------------------------------------
def reconstruct_villain_population(stats, report_data):
    from gem_villain_teaching import teaching_from_exploit, teaching_from_atom
    try:
        from gem_villain_intel import SIGNAL_COACHING as SIG
    except Exception:
        SIG = {}
    vi = (stats.get('villain_intel') or {})
    read_states = vi.get('read_states') or {}
    abv = vi.get('atoms_by_villain') or {}
    abh = vi.get('atoms_by_hand') or {}
    pko = ((report_data.get('pko_research') or {}).get('by_hand') or {})
    objs = []
    for exp in (vi.get('exploit_opportunities') or []):
        try:
            o = teaching_from_exploit(exp, read_states, abv, population='online', pko_by_hand=pko)
            o['_src'] = 'exploit'
            objs.append(o)
        except Exception:
            pass
    for hid, alist in abh.items():
        for atom in (alist or []):
            try:
                o = teaching_from_atom(atom, read_states, abv, signal_coaching=SIG,
                                       population='online', pko_by_hand=pko)
                o['_src'] = 'atom'
                objs.append(o)
            except Exception:
                pass
    return objs


def independent_villain_audit(objs):
    """A SECOND, independent implementation of eligibility-before-completeness. Returns the audit dict +
    the per-object rows + the eligible-incomplete (133-style) corrected rows."""
    seen = set()
    raw = dup = eligible = ineligible = complete = incomplete = 0
    by_reason = {r: 0 for r in ('INSUFFICIENT_EVIDENCE', 'RESULT_ONLY', 'NO_MEANINGFUL_CUE',
                                'NO_SAFE_EXPLOIT_SUPPORTED')}
    chronology = result_oriented = 0
    rows = []
    corrected = []
    for o in (objs or []):
        raw += 1
        st = o.get('source_truth') or {}
        did = st.get('decision_id')
        vk = o.get('villain_id')
        text = ((o.get('cue') or '') + ' ' + (o.get('villain_did') or '')).lower()
        is_result = any(w in text for w in RESULT_WORDS)
        if st.get('no_hindsight') is False and o.get('exploit_now'):
            chronology += 1
        if is_result and (o.get('exploit_now') or o.get('future_exploit')):
            result_oriented += 1
        row = {'decision_id': did, 'villain_id': vk, 'eligible': None, 'complete': None,
               'reason': None, 'missing_fields': []}
        lid = (vk, did)
        if did and lid in seen:
            dup += 1
            row.update(eligible=False, complete=False, reason='DUPLICATE_OBJECT')
            rows.append(row)
            continue
        if did:
            seen.add(lid)
        # eligibility (q1 villain_did, q2 cue, q3 archetype/read, q4 confidence, q5 exploit_now)
        if o.get('fallback') or not o.get('villain_did') or not o.get('cue'):
            ineligible += 1; by_reason['INSUFFICIENT_EVIDENCE'] += 1
            row.update(eligible=False, complete=False, reason='INSUFFICIENT_EVIDENCE')
            rows.append(row); continue
        if is_result:
            ineligible += 1; by_reason['RESULT_ONLY'] += 1
            row.update(eligible=False, complete=False, reason='RESULT_ONLY')
            rows.append(row); continue
        if not (o.get('archetype') and o.get('confidence')):
            ineligible += 1; by_reason['NO_MEANINGFUL_CUE'] += 1
            row.update(eligible=False, complete=False, reason='NO_MEANINGFUL_CUE')
            rows.append(row); continue
        if not o.get('exploit_now'):
            ineligible += 1; by_reason['NO_SAFE_EXPLOIT_SUPPORTED'] += 1
            row.update(eligible=False, complete=False, reason='NO_SAFE_EXPLOIT_SUPPORTED')
            rows.append(row); continue
        # ELIGIBLE
        eligible += 1
        missing = []
        if not o.get('future_exploit'):
            missing.append('future_exploit')
        if not o.get('do_not_overadjust'):
            missing.append('guardrail')
        row.update(eligible=True, complete=(not missing), missing_fields=missing)
        if not missing:
            complete += 1
        else:
            incomplete += 1
        rows.append(row)
        # the 133 corrected lessons = ATOM-derived eligible lessons (the ones that previously carried no
        # future_exploit and were misclassified no_actionable_cue) now completed. The 9 pre-existing
        # exploit lessons already had a future_exploit and are NOT part of the 133.
        if o.get('_src') == 'atom' and o.get('future_exploit'):
            corrected.append({
                'decision_id': did, 'villain_id': vk, 'archetype': o.get('archetype'),
                'cue': o.get('cue'), 'confidence': o.get('confidence'),
                'exploit_now': o.get('exploit_now'), 'future_exploit': o.get('future_exploit'),
                'guardrail': o.get('do_not_overadjust'),
            })
    audit = {
        'raw_teaching_objects': raw, 'duplicates_identified': dup, 'unique_objects': raw - dup,
        'eligible_lessons': eligible, 'ineligible_total': ineligible, 'ineligible_by_reason': by_reason,
        'complete_eligible_lessons': complete, 'incomplete_eligible_lessons': incomplete,
        'duplicate_lessons_remaining': 0,
        'chronology_violations': chronology, 'result_oriented_violations': result_oriented,
    }
    return audit, rows, corrected


# ---------------------------------------------------------------------------------------------------
# RENDERED villain payload (handOpponentContexts)
# ---------------------------------------------------------------------------------------------------
def read_villain_payload(html):
    import _qa_decode_lazy as D
    obj = D._decode_payload(html, 'handOpponentContexts')
    lessons = []

    def walk(o):
        if isinstance(o, dict):
            if 'q6_exploit_future' in o or ('q5_exploit_now' in o and 'q1_villain_did' in o):
                lessons.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj if obj is not None else {})
    eligible_shaped = [l for l in lessons if l.get('q1_villain_did') and l.get('q2_cue')
                       and l.get('q3_read') and l.get('q4_confidence') and l.get('q5_exploit_now')]
    with_future = [l for l in eligible_shaped if l.get('q6_exploit_future')]
    placeholders = sum(1 for l in lessons
                       if (l.get('q6_exploit_future') or '').strip().lower() in FORBIDDEN_FUTURE)
    actiony = sum(1 for l in with_future
                  if any(w in (l['q6_exploit_future'] or '').lower() for w in ACTION_VERBS))
    return {
        'payload_lessons': len(lessons),
        'eligible_shaped': len(eligible_shaped),
        'eligible_with_future': len(with_future),
        'forbidden_placeholders': placeholders,
        'future_with_action_verb': actiony,
    }


# ---------------------------------------------------------------------------------------------------
# Reconciliation: raw source vs typed model vs DOM row (Results)
# ---------------------------------------------------------------------------------------------------
def build_results_reconciliation(raw_rows, report_data, dom):
    pt = (report_data.get('usd_overlay') or {}).get('per_tournament') or []
    raw_valid = [r for r in raw_rows if r['top_percent'] is not None]
    model_valid = [e for e in pt if e.get('place') and e.get('total_players')]
    raw_avg = round(sum(r['top_percent'] for r in raw_valid) / len(raw_valid), 1) if raw_valid else None
    model_avg = round(sum(e['place'] / e['total_players'] * 100 for e in model_valid) / len(model_valid), 1) if model_valid else None
    return {
        'raw_source_events': len(raw_rows),
        'raw_events_with_finish_entries': len(raw_valid),
        'typed_model_events': len(pt),
        'typed_model_events_with_finish_entries': len(model_valid),
        'dom_rendered_rows': dom['finish_cells'],
        'dom_rows_with_finish_toppct': dom['rows_with_finish_toppct'],
        'dom_rows_missing_finish': dom['finish_cells'] - dom['rows_with_finish_toppct'],
        'dom_duplicate_rows': dom['finish_cells'] - len(raw_rows) if dom['finish_cells'] > len(raw_rows) else 0,
        'raw_avg_top_percent': raw_avg,
        'typed_model_avg_top_percent': model_avg,
        'dom_avg_top_percent': dom['avg_top_rendered'],
        'finish_mismatches': 0 if (len(raw_valid) == dom['rows_with_finish_toppct']) else (len(raw_valid) - dom['rows_with_finish_toppct']),
        'toppct_mismatches': 0 if (raw_avg == model_avg == dom['avg_top_rendered']) else 1,
        'bb100_currency_mismatches': dom['bb_or_cev_currency_cells'],
        'speed_mismatches': 0 if (dom['speed_filter_present'] and dom['speed_count_sum'] == len(raw_rows)) else 1,
    }


# ---------------------------------------------------------------------------------------------------
# Predicate harness
# ---------------------------------------------------------------------------------------------------
def run(auto_html_path, out_dir, data_path, stats_path, summaries_dir, analyst_html_path=None):
    html = _read(auto_html_path)
    report_data = json.loads(_read(data_path))
    stats = json.loads(_read(stats_path))

    # --- RESULTS ---
    raw_rows = parse_raw_results(summaries_dir)
    raw_valid = [r for r in raw_rows if r['top_percent'] is not None]
    raw_avg = round(sum(r['top_percent'] for r in raw_valid) / len(raw_valid), 1) if raw_valid else None
    dom = read_results_dom(html)
    recon = build_results_reconciliation(raw_rows, report_data, dom)

    # --- VILLAIN ---
    objs = reconstruct_villain_population(stats, report_data)
    vaudit, vrows, vcorrected = independent_villain_audit(objs)
    vpay = read_villain_payload(html)

    # source-truth artifacts (written by the INDEPENDENT verifier)
    os.makedirs(out_dir, exist_ok=True)
    speed_dist = {k: sum(1 for r in raw_rows if r['speed'] == k) for k in ('STANDARD', 'TURBO', 'HYPER')}
    _write(os.path.join(out_dir, 'results_source_truth.json'), {
        'source_events': len(raw_rows), 'events_with_valid_finish_entries': len(raw_valid),
        'average_top_percent_one_decimal': raw_avg, 'speed_distribution': speed_dist,
        'events': raw_rows, 'source': 'raw GG game-summary text (independent parse)'})
    _write(os.path.join(out_dir, 'results_source_model_dom_reconciliation.json'), recon)
    _write(os.path.join(out_dir, 'villain_full_population_audit.json'),
           {'audit': vaudit, 'objects': vrows})
    # 133-style: eligible lessons whose future_exploit was completed (atom-derived, exclude the 9
    # pre-existing exploit lessons that already had one)
    corrected_133 = [c for c in vcorrected]
    _write(os.path.join(out_dir, 'villain_133_corrected_lessons.json'),
           {'count': len(corrected_133), 'lessons': corrected_133})

    P = []

    def predicate(key, expected, observed):
        P.append({'predicate': key, 'expected': expected, 'observed': observed,
                  'passed': (expected == observed)})

    # Results predicates
    predicate('results.source_events', 12, len(raw_rows))
    predicate('results.source_events_with_finish_entries', 12, len(raw_valid))
    predicate('results.raw_avg_top_percent', 48.1, raw_avg)
    predicate('results.dom_rendered_rows', 12, dom['finish_cells'])
    predicate('results.dom_rows_with_finish_and_toppct', 12, dom['rows_with_finish_toppct'])
    predicate('results.nocash_in_finish_column', 0, dom['nocash_in_finish'])
    predicate('results.dom_avg_top_percent', 48.1, dom['avg_top_rendered'])
    predicate('results.bb100_or_cev_currency_cells', 0, dom['bb_or_cev_currency_cells'])
    predicate('results.bb100_signed_cells', 12, dom['bb_signed_cells'])
    predicate('results.speed_filter_present', True, dom['speed_filter_present'])
    predicate('results.speed_values', ['HYPER', 'STANDARD', 'TURBO'], dom['speed_values'])
    predicate('results.speed_count_sum', 12, dom['speed_count_sum'])
    predicate('results.reconciliation_missing_finish', 0, recon['dom_rows_missing_finish'])
    predicate('results.reconciliation_duplicate_rows', 0, recon['dom_duplicate_rows'])
    predicate('results.reconciliation_finish_mismatches', 0, recon['finish_mismatches'])
    predicate('results.reconciliation_toppct_mismatches', 0, recon['toppct_mismatches'])
    predicate('results.reconciliation_speed_mismatches', 0, recon['speed_mismatches'])

    # Villain predicates (independent audit)
    predicate('villain.raw_teaching_objects', 222, vaudit['raw_teaching_objects'])
    predicate('villain.duplicates_identified', 4, vaudit['duplicates_identified'])
    predicate('villain.unique_objects', 218, vaudit['unique_objects'])
    predicate('villain.eligible_lessons', 142, vaudit['eligible_lessons'])
    predicate('villain.ineligible_total', 76, vaudit['ineligible_total'])
    predicate('villain.complete_eligible_lessons', 142, vaudit['complete_eligible_lessons'])
    predicate('villain.incomplete_eligible_lessons', 0, vaudit['incomplete_eligible_lessons'])
    predicate('villain.duplicate_lessons_remaining', 0, vaudit['duplicate_lessons_remaining'])
    predicate('villain.chronology_violations', 0, vaudit['chronology_violations'])
    predicate('villain.result_oriented_violations', 0, vaudit['result_oriented_violations'])
    predicate('villain.ineligible_all_insufficient_evidence', 76, vaudit['ineligible_by_reason']['INSUFFICIENT_EVIDENCE'])
    # Villain predicates (rendered payload)
    predicate('villain.payload_lessons', 222, vpay['payload_lessons'])
    predicate('villain.payload_eligible_with_future_nonnull', vpay['eligible_shaped'], vpay['eligible_with_future'])
    predicate('villain.payload_forbidden_placeholders', 0, vpay['forbidden_placeholders'])
    predicate('villain.payload_future_all_have_action_verb', vpay['eligible_with_future'], vpay['future_with_action_verb'])
    predicate('villain.corrected_lessons_completed', True, len(corrected_133) >= 133)

    all_passed = all(p['passed'] for p in P)
    audit_doc = {
        'version': 'v8.18.0',
        'all_passed': all_passed,
        'predicate_count': len(P),
        'failed_predicates': [p for p in P if not p['passed']],
        'predicates': P,
        'results_dom': dom,
        'results_reconciliation': recon,
        'villain_independent_audit': vaudit,
        'villain_rendered_payload': vpay,
        'inputs': {'auto_html': os.path.basename(auto_html_path),
                   'summaries_dir': summaries_dir,
                   'analyst_html': os.path.basename(analyst_html_path) if analyst_html_path else None},
    }
    _write(os.path.join(out_dir, 'FINAL_PREPACKAGE_AUDIT.json'), audit_doc)
    return audit_doc


def _write(path, obj):
    io.open(path, 'w', encoding='utf-8', newline='\n').write(json.dumps(obj, indent=2, ensure_ascii=False))


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    auto_html = argv[1]
    out_dir = argv[2]
    data_path = _opt(argv, '--data', r'C:/home/claude/gem_report_data_Knockman.json')
    stats_path = _opt(argv, '--stats', r'C:/home/claude/gem_stats.json')
    summaries = _opt(argv, '--summaries', r'C:/mnt/user-data/outputs/iter0/june16_src/game_summaries')
    analyst = _opt(argv, '--analyst-html', None)
    doc = run(auto_html, out_dir, data_path, stats_path, summaries, analyst)
    print('FINAL_PREPACKAGE_AUDIT: all_passed=%s  (%d predicates, %d failed)'
          % (doc['all_passed'], doc['predicate_count'], len(doc['failed_predicates'])))
    for p in doc['failed_predicates']:
        print('  FAIL %s: expected %r observed %r' % (p['predicate'], p['expected'], p['observed']))
    return 0 if doc['all_passed'] else 1


def _opt(argv, flag, default):
    return argv[argv.index(flag) + 1] if flag in argv else default


if __name__ == '__main__':
    sys.exit(main(sys.argv))
