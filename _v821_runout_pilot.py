"""v8.21 Runout Transition -- real-session pilot + MEASURED trust audit.

Runs the PRODUCT PATH (transitions_for_hand) over the approved real corpus and MEASURES (does not assume)
result-field leakage, later-card leakage, unsupported range/strategic wording, duplicate records per street,
accidentally-rendered unresolved records, shared-board false-improvement claims, and static-texture
duplication. Canonical owners only. Writes RUNOUT_PILOT_METRICS.json + RUNOUT_PILOT_SAMPLES.json.
"""
import json
import os
import re
import time
from collections import Counter

import gem_parser
import gem_runout_transition as RT

SESSIONS = [
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_live_test', 'live_test_2026-06-04'),
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\hh_today', 'hh_today_2026-06-09'),
    (r'C:\Users\ron\OneDrive\Desktop\GEM 20260527\_session_20260527', 'session_2026-05-27'),
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v821_range')
os.makedirs(OUT, exist_ok=True)

_RESULT_WORDS = re.compile(r'\b(won|collected|showdown|mucks?|wins?|net|profit|loss|busto|knocked out|bounty won)\b', re.I)
_RANGE_WORDS = re.compile(r'\b(range|equity|combos?|fold equity|nut advantage|polari[sz]ed|capped|%\s*to\s*continue|ev\b)\b', re.I)
_STRATEGY_WORDS = re.compile(r'\b(you should|correct play|best line|i recommend|gto says|must (?:bet|call|raise|fold|check)|always (?:bet|fold|call))\b', re.I)
_CHANGE_VERB = re.compile(r'\b(changed|now|paired|completed|arrived|became|is now|did not|four-to|more connected|blank)\b', re.I)


def main():
    hands = []
    for path, name in SESSIONS:
        if os.path.isdir(path):
            hh, *_ = gem_parser.parse_session(path)
            for h in hh:
                h['_session'] = name
            hands += hh

    t0 = time.perf_counter()
    unique_hands = len(hands)
    eligible_nodes = resolved = unresolved = rendered = 0
    unresolved_reasons = Counter()
    tag_dist = Counter()
    contrib_dist = Counter()           # hole-card contribution after the card
    category_change_dist = Counter()
    bytes_total = 0

    audit = Counter()                  # measured trust violations (target: all 0)
    per_street_dupes = 0

    samples = {k: [] for k in ('shared_board_change', 'hero_private_improvement', 'flush_threat',
                               'board_paired', 'blank', 'draw_missed', 'multiway', 'threebet', 'unresolved')}

    for h in hands:
        full_board = [c for c in (h.get('board') or [])]
        recs = RT.transitions_for_hand(h)            # PRODUCT PATH: one record per street
        by_street = Counter(r.get('street') for r in recs)
        per_street_dupes += sum(1 for s, n in by_street.items() if n and n > 1)

        for rec in recs:
            eligible_nodes += 1
            blob = json.dumps(rec, default=str)
            bytes_total += len(blob)
            note = RT.transition_note_text(rec)

            if rec.get('unresolved'):
                unresolved += 1
                unresolved_reasons[rec.get('unresolved_reason')] += 1
                if note != '':
                    audit['rendered_unresolved'] += 1          # unresolved must render to nothing
                if len(samples['unresolved']) < 4:
                    samples['unresolved'].append({'hand': h.get('id'), 'street': rec.get('street'),
                                                  'reason': rec.get('unresolved_reason')})
                continue

            resolved += 1
            if note:
                rendered += 1
            # the FACTUAL claims (changed/remained); the fixed strategic caveat is allowed to name the missing
            # "opponent-range owner", so range/strategy/banned scans target the claims, not the caveat.
            fact_text = ' '.join([c['fact'] for c in rec['changed']] + [r['fact'] for r in rec['remained']])

            # ---- MEASURED trust audit ----
            if _RESULT_WORDS.search(blob):
                audit['result_word_leak'] += 1
            if _RANGE_WORDS.search(fact_text):
                audit['unsupported_range_term'] += 1
            if _STRATEGY_WORDS.search(fact_text):
                audit['unsupported_strategic_directive'] += 1
            if re.search(r'\b(showdown value|improved|improve|weakened|counterfeit)\b', fact_text, re.I):
                audit['banned_strength_word'] += 1
            # later-card leakage: no card dealt AFTER this decision street may appear as a whole token
            # (token-bounded so a card like 'Th' does not false-match inside a word such as "The").
            dec_n = len(rec['resulting_board'])
            for later in full_board[dec_n:]:
                if later and re.search(r'(?<![A-Za-z0-9])' + re.escape(later) + r'(?![A-Za-z0-9])', blob):
                    audit['later_card_leak'] += 1
                    break
            # shared-board false improvement: if Hero's hole cards do NOT contribute, no fact may claim they make/improve a hand
            if rec['hero_hole_cards_contribute_after'] is False:
                if any(re.search(r'your hole cards now make|your hole cards still make', c['fact'], re.I) for c in rec['changed']):
                    audit['shared_board_false_improvement'] += 1
            # static-texture duplication: every 'changed' fact must describe a CHANGE, not a bare static label
            for c in rec['changed']:
                if not _CHANGE_VERB.search(c['fact']):
                    audit['static_texture_duplication'] += 1
                    break

            # ---- distributions ----
            for tg in rec['transition_tags']:
                tag_dist[tg] += 1
            contrib_dist['contributes' if rec['hero_hole_cards_contribute_after'] else 'board_or_shared'] += 1
            category_change_dist['changed' if rec['category_changed'] else 'unchanged'] += 1

            one = {'hand': h.get('id'), 'session': h.get('_session'), 'street': rec['street'],
                   'card': rec['new_card'], 'board': '-'.join(rec['resulting_board']),
                   'cat': '%s->%s' % (rec['best_five_category_before'], rec['best_five_category_after']),
                   'contributes': rec['hero_hole_cards_contribute_after'], 'tags': rec['transition_tags'],
                   'changed': [c['fact'] for c in rec['changed']], 'reassess': rec['reassess']}
            if rec['category_changed'] and rec['hero_hole_cards_contribute_after'] is False and len(samples['shared_board_change']) < 5:
                samples['shared_board_change'].append(one)
            if rec['category_changed'] and rec['hero_hole_cards_contribute_after'] and len(samples['hero_private_improvement']) < 5:
                samples['hero_private_improvement'].append(one)
            if 'flush_card' in rec['transition_tags'] and len(samples['flush_threat']) < 4:
                samples['flush_threat'].append(one)
            if 'board_paired' in rec['transition_tags'] and len(samples['board_paired']) < 4:
                samples['board_paired'].append(one)
            if 'blank' in rec['transition_tags'] and len(samples['blank']) < 4:
                samples['blank'].append(one)
            if rec['real_draw_missed'] and len(samples['draw_missed']) < 4:
                samples['draw_missed'].append(one)
            if rec['multiway'] and len(samples['multiway']) < 4:
                samples['multiway'].append(one)
            if rec['pot_type'] in ('3bet', '3-bet', 'threebet') and len(samples['threebet']) < 4:
                samples['threebet'].append(one)
    dt = time.perf_counter() - t0

    metrics = {
        'corpus': [n for _, n in SESSIONS], 'unique_hands': unique_hands,
        'eligible_street_transitions': eligible_nodes,
        'resolved_complete_evidence': resolved,
        'unresolved_suppressed': unresolved,
        'unresolved_reasons': dict(unresolved_reasons),
        'rendered_blocks': rendered,
        'resolved_rate': round(resolved / eligible_nodes, 3) if eligible_nodes else 0.0,
        'hero_hole_card_contribution': dict(contrib_dist),
        'category_change': dict(category_change_dist),
        'transition_tag_distribution': dict(tag_dist.most_common()),
        'MEASURED_trust_audit': {
            'result_field_leakage': audit['result_word_leak'],
            'later_card_leakage': audit['later_card_leak'],
            'unsupported_range_terms': audit['unsupported_range_term'],
            'unsupported_strategic_directives': audit['unsupported_strategic_directive'],
            'banned_strength_words(improved/weakened/counterfeit/showdown-value)': audit['banned_strength_word'],
            'shared_board_false_improvement': audit['shared_board_false_improvement'],
            'static_texture_duplication': audit['static_texture_duplication'],
            'duplicate_records_per_street': per_street_dupes,
            'accidentally_rendered_unresolved': audit['rendered_unresolved'],
        },
        'rule_backed_strategic_coaching': 0,
        'analyst_workload_added': 0,
        'avg_record_bytes': (bytes_total // max(eligible_nodes, 1)),
        'runtime_seconds': round(dt, 3),
    }
    audit_clean = all(v == 0 for v in metrics['MEASURED_trust_audit'].values())
    metrics['MEASURED_trust_audit_all_zero'] = audit_clean

    json.dump(metrics, open(os.path.join(OUT, 'RUNOUT_PILOT_METRICS.json'), 'w', encoding='utf-8'), indent=2)
    json.dump(samples, open(os.path.join(OUT, 'RUNOUT_PILOT_SAMPLES.json'), 'w', encoding='utf-8'), indent=2, default=str)

    print('unique hands:', unique_hands, '| eligible street transitions:', eligible_nodes)
    print('resolved:', resolved, '(%.0f%%)' % (100 * metrics['resolved_rate']), '| unresolved:', unresolved, dict(unresolved_reasons))
    print('rendered blocks:', rendered, '| rule-backed strategic coaching: 0 (strategic blocked)')
    print('hole-card contribution:', dict(contrib_dist), '| category change:', dict(category_change_dist))
    print('top tags:', tag_dist.most_common(8))
    print('MEASURED trust audit (target all 0):')
    for k, v in metrics['MEASURED_trust_audit'].items():
        print('   %-55s %d' % (k, v))
    print('AUDIT ALL ZERO:', audit_clean)
    print('avg record bytes:', metrics['avg_record_bytes'], '| runtime %.3fs for %d transitions' % (dt, eligible_nodes))
    print('--- sample shared-board change (no false improvement) ---')
    for s in samples['shared_board_change'][:3]:
        print('  ', s['hand'], s['board'], s['cat'], 'contributes=', s['contributes'], '::', s['changed'])
    print('--- sample Hero private improvement ---')
    for s in samples['hero_private_improvement'][:3]:
        print('  ', s['hand'], s['board'], s['cat'], '::', s['changed'])


if __name__ == '__main__':
    main()
