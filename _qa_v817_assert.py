"""v8.17 synthetic acceptance — machine assertions + readable scenario matrix.
Renders via the REAL renderer (_qa_v817_synthetic.render), decodes lazyHands, and
asserts every required v8.17 scenario fired live. Exit 0 = all pass."""
import sys
from _qa_decode_lazy import decode_lazy_hands
import _qa_v817_synthetic as gen

PASS = FAIL = 0
ROWS = []


def ck(scenario, cond, detail=''):
    global PASS, FAIL
    ok = bool(cond)
    PASS, FAIL = PASS + ok, FAIL + (0 if ok else 1)
    ROWS.append((('PASS' if ok else 'FAIL'), scenario))
    if not ok:
        print('  FAIL %s -- %s' % (scenario, detail))


def main():
    html = gen.render()
    cards = decode_lazy_hands(html)

    def c(hid):
        return cards.get(hid[-8:], '')

    # 1 bounded queue + 2 aggregated 38-leak + internal-health excluded
    ck('1 bounded review queue rendered', 'data-topn' in html and 'rq-row' in html)
    ck('2 aggregated 38-example leak (one row, ×38)', '(×38)' in html
       and html.count('Missed BTN steal — extended range (×38)') == 1)
    ck('3 internal detector-health (auto_clear +7.5BB) not a visible mistake row',
       'TM9700050' not in html.split('review-queue')[-1][:3000] if 'review-queue' in html else True)
    # 4 exact-action mistake + 5 analyst override + 6/7 root/downstream/consequence
    ck('4 exact-action Mistake (analyst III.2) renders', bool(c('TM9700051')))
    ck('5 analyst-mistake open-shove decision label', 'Open-shove' in c('TM9700051'))
    c52 = c('TM9700052')
    ck('6/7 root->downstream->consequence attribution chain separated',
       'Attribution:' in c52 and 'root mistake' in c52
       and 'compounds the earlier error' in c52 and 'result' in c52)
    # 9 no postflop Range Lens after preflop all-in (unprovable decision-kind label)
    ck('9 preflop all-in unprovable -> exact-node-unavailable',
       'exact node type unavailable' in c('TM9700053'))
    # 10-12 decision kinds
    c60 = c('TM9700060')
    ck('10 call-vs-jam PKO Good + how-changes + threshold delta',
       'PKO Good' in c60 and 'How the bounty changes it:' in c60 and 'bounty-adjusted' in c60)
    ck('11 open-shove PKO', 'Open-shove' in c('TM9700061'))
    ck('12 rejam PKO', 'Re-jam' in c('TM9700062'))
    # 13 non-collectible (covered) + 14-17 provenance states
    c63 = c('TM9700063')
    ck('13 non-collectible (Hero covered) -> not collectible, no incentive',
       ('not collectible' in c63) and ('does not' in c63))
    ck('14 exact exported $ provenance', '(exact)' in c('TM9700064'))
    ck('15 estimated-current (effective-stack) provenance', 'effective-stack' in c('TM9700065'))
    ck('16 static event-start (flat) provenance', 'flat event estimate' in c('TM9700066'))
    ck('17 unavailable bounty provenance', 'Bounty value unavailable' in c('TM9700067'))
    # 18 three-way + 22 mixed cover (multiway suppression)
    c68 = c('TM9700068')
    ck('18 three-way all-in: HU required-equity suppressed + N-way label + FIELD note',
       'Multiway all-in (3-way)' in c68 and 'compare your equity to the FIELD' in c68
       and 'Required equity:' not in c68)
    ck('22 mixed-cover multiway directional (not a fixed price cut)',
       'directionally' in c('TM9700069') or 'uncertain' in c('TM9700069'))
    # 23/24 action-changing vs non-action-changing
    ck('23 action-changing PKO names the threshold shift', '−4.0pp' in c60 or '4.0pp' in c60)
    ck('24 non-action-changing PKO -> small-shift wording',
       'small shift' in c('TM9700070') or 'directionally' in c('TM9700070'))
    # 29/30 debate preserved WITHOUT forced grading (renders Justified, never Mistake).
    # (Verbatim long-analyst-narrative preservation is validated on the REAL
    # ANALYST_COMPLETE artifact in Slice 6B — the synthetic hand_strength field maps
    # to the verdict context, not a free narrative paragraph.)
    c80 = c('TM9700080')
    ck('29/30 debate hand preserved (Justified verdict, not forced to a Mistake)',
       bool(c80) and 'Justified' in c80 and 'Key mistake' not in c80,
       'verdict=%s' % ('Justified' if 'Justified' in c80 else '?'))
    # visible §9 capsules: factual / coaching / no_clear_lesson all render with badges
    def capof(hid):
        b = c(hid)
        import re as _r
        m = _r.search(r'pb-capsule[^>]*>(.*?)</div>', b, _r.S)
        return _r.sub(r'<[^>]+>', ' ', m.group(0)) if m else ''
    ck('A-capsule coaching register renders (mistake hand -> 🧭 Coach + Decision/Verdict)',
       'pb-cap-coaching' in c('TM9700051') and '🧭' in capof('TM9700051')
       and 'Coach' in capof('TM9700051'))
    ck('A-capsule factual register renders (standard PKO Good -> 🧭 Read + Math anchor)',
       'pb-cap-factual' in c('TM9700060') and 'Read' in capof('TM9700060')
       and 'need 31%' in capof('TM9700060'))
    ck('A-capsule no_clear_lesson renders (unprovable -> 🧭 Unclear, no scored verdict)',
       'pb-cap-no_clear_lesson' in c('TM9700053') and 'Unclear' in capof('TM9700053'))
    # 31 capsule layer / content lints clean on this synthetic report
    import re as _re
    bodies = {}
    for k, v in cards.items():
        bodies[id(v)] = v
    from gem_commentary_capsule import scan_visible_text_lints as _svtl
    _txt = _re.sub(r'<[^>]+>', ' ', '\n'.join(bodies.values()))
    _lz = _svtl(_txt)
    ck('31 capsule content lints clean (L2/L3/L6 = 0 on visible text)',
       _lz['l2'] == 0 and _lz['l3'] == 0 and _lz['l6'] == 0,
       'l2=%d l3=%d l6=%d' % (_lz['l2'], _lz['l3'], _lz['l6']))

    print('\n=== v8.17 synthetic scenario matrix ===')
    for st, name in ROWS:
        print('  [%s] %s' % (st, name))
    print('\nv8.17 synthetic acceptance: %d passed, %d failed' % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
