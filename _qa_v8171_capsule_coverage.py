"""v8.17.1 P1 — capsule-coverage RENDER PROOF (rendered-output evidence, not unit-only).

Renders synthetic hands through the REAL gem_report_draft.render_html (lazy on)
and decodes PB_PAYLOADS["lazyHands"], then machine-asserts that the §9 register
DECISION capsule now appears on scored/evidenced hands that carry NO pot-odds
object — the v8.17.1 de-gate — while a genuinely bare non-decision hand renders
NO fabricated capsule. Synthetic ids only (90000001+); no real-id logic.

Run:  python _qa_v8171_capsule_coverage.py   (exit 0 = de-gate proven)
"""
import os
import sys

os.environ['GEM_LAZY_HANDS'] = '1'   # force lazy so all hand bodies decode uniformly

import _qa_v817_synthetic as SYN
from gem_report_draft import render_html
from _qa_decode_lazy import decode_lazy_hands


def run():
    stats, rd, hands = SYN.build()
    base_po_hands = set(rd['pot_odds_by_hand'].keys())

    # NEW hands with NO pot-odds object (the exact de-gate scenario):
    #  - an open-shove all-in (gradable decision label, no _po)  -> MUST get a capsule
    #  - a folded, no-evidence, non-decision hand (no _po)        -> MUST NOT get one
    h_shove = SYN._hand('90000001', ['As', 'Ks'], pf_allin=True, first_in=True,
                        pf_action='raise', position='CO', stack_bb=14.0, net_bb=14.0)
    h_bare = SYN._hand('90000002', ['7c', '2d'], pf_action='fold', position='UTG',
                       stack_bb=40.0, net_bb=-1.0)
    for h in (h_shove, h_bare):
        hands.append(h)
        rd['appendix_hand_ids_all'].append(h['id'])
        rd['appendix_hand_details'][h['id']] = {}
    assert '90000001' not in rd['pot_odds_by_hand']
    assert '90000002' not in rd['pot_odds_by_hand']
    stats['volume']['hands'] = len(hands)

    html = render_html(stats, rd, hands, sections=['XIV'])
    bodies = decode_lazy_hands(html) or {}

    def body(hid):
        return bodies.get(hid) or bodies.get(hid[-8:]) or ''

    # capsules on non-pot-odds hands across the WHOLE decoded corpus (systemic):
    non_po_capsule_hands = sum(
        1 for hid, b in bodies.items()
        if 'pb-capsule' in b and hid not in base_po_hands and hid[-8:] not in base_po_hands)

    PASS, FAIL = [], []

    def chk(name, cond):
        (PASS if cond else FAIL).append(name)
        print(('  [PASS] ' if cond else '  [FAIL] ') + name)

    chk('T-P1COV-1: all-in hand with NO pot-odds object renders a pb-capsule (de-gate works)',
        'pb-capsule' in body('90000001'))
    chk('T-P1COV-2: bare folded no-evidence hand renders NO fabricated capsule (no overclaim)',
        'pb-capsule' not in body('90000002'))
    chk('T-P1COV-3: capsules render on hands WITHOUT a pot-odds object (systemic, not _po-gated)',
        non_po_capsule_hands >= 1)

    print('\n  decoded hand bodies: %d | non-pot-odds hands with a capsule: %d'
          % (len(bodies), non_po_capsule_hands))
    fail = len(FAIL)
    print('v8.17.1 P1 capsule-coverage proof: %d passed, %d failed' % (len(PASS), fail))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(run())
