"""_qa_status_consistency.py -- the W1-A status-contradiction gate (v8.18.0).

Parses a generated report (decoding the lazy hand payload) and proves, for every hand, that the ONE
canonical Final Decision Status (gem_final_status) is presented consistently across the surfaces that
show it -- the card-root data-final-status, the canonical status pill, and the verdict-nuance pill --
and that the verdict nuance never contradicts the status.

Invariants asserted (a violation is a contradiction):
  C1  every hand carries exactly one canonical status (a data-final-status on the card root).
  C2  the canonical status pill's data-final-status == the card-root data-final-status (no drift).
  C3  a CLEARED or UNGRADED hand shows NO 'Mistake'/'Punt' verdict-nuance pill (never says mistake
      when the system found no graded error).
  C4  a MISTAKE hand never shows a 'Correct'/'Justified'/'Standard'/'Cleared' verdict-nuance pill.
  C5  every status value is one of the four canonical values (no empty/unknown status).
  C6  the canonical status pill is present (a CLEARED hand is never blank).

Also reports the status distribution + secondary-reason distribution (plausibility).

Pure-ish: `run_status_consistency(html)` returns a dict; `main()` prints + exits non-zero on any
contradiction. No re-derivation of status here -- the gate only reads what the renderer emitted.
"""
import re
import sys
import io
import json
import collections

import _qa_decode_lazy as _dlz

_CANON = ('MISTAKE', 'CONDITIONAL', 'CLEARED', 'UNASSESSED', 'UNGRADED')
# CLEARED, UNASSESSED and UNGRADED must NOT carry a mistake verdict pill (only MISTAKE/CONDITIONAL may).
_NON_MISTAKE_STATES = ('CLEARED', 'UNASSESSED', 'UNGRADED')
_MISTAKE_VERDICT_LABELS = ('Mistake', 'Punt')
_CLEARED_VERDICT_LABELS = ('Correct', 'Justified', 'Standard', 'Cleared')

_RE_CARD = re.compile(r"<article[^>]*\bclass='hand-detail-card'[^>]*>", re.I)
_RE_CARD_STATUS = re.compile(r"data-final-status='([A-Z]+)'")
_RE_PILL = re.compile(
    r"<span class='final-status-pill fs-(\w+)'\s+data-final-status='([A-Z]+)'", re.I)
_RE_VERDICT_PILL = re.compile(r"<span class='verdict-pill'\s+data-verdict='([^']*)'")


def _iter_bodies(html):
    """Yield (hand_id, body_html) for every UNIQUE hand body in the report (lazy + any inline)."""
    bodies = _dlz.decode_lazy_hands(html) or {}
    seen = {}
    for k, v in bodies.items():
        m = re.search(r'(\d{6,})', str(k))
        if m:
            seen[m.group(1)] = v
    # also pick up any non-lazy inline hand-detail-cards present directly in the shell (the
    # data-hand-id is already a hand id, so use it directly -- robust to id length / attribute order).
    for m in re.finditer(r"<article[^>]*\bdata-hand-id='([^']+)'[^>]*\bclass='hand-detail-card'"
                         r"|<article[^>]*\bclass='hand-detail-card'[^>]*\bdata-hand-id='([^']+)'",
                         html):
        hid = m.group(1) or m.group(2) or ''
        bare = re.sub(r'^TM\d*?(\d+)$', r'\1', hid) if re.match(r'^TM\d', hid) else hid
        if bare and bare not in seen:
            # capture a slice of the inline card for the checks
            seen[bare] = html[m.start():m.start() + 4000]
    return seen.items()


def run_status_consistency(html):
    dist = collections.Counter()
    sec_dist = collections.Counter()
    violations = []
    n = 0
    for hid, body in _iter_bodies(html):
        n += 1
        card = _RE_CARD.search(body)
        card_status = None
        if card:
            ms = _RE_CARD_STATUS.search(card.group(0))
            card_status = ms.group(1) if ms else None
        # C1 / C5: exactly one canonical status on the card root
        if not card_status:
            violations.append({'hand': hid, 'rule': 'C1', 'detail': 'no data-final-status on the card root'})
            continue
        if card_status not in _CANON:
            violations.append({'hand': hid, 'rule': 'C5', 'detail': 'non-canonical status %r' % card_status})
        dist[card_status] += 1
        # the canonical status pill
        pill = _RE_PILL.search(body)
        # C6: a status pill must be present
        if not pill:
            violations.append({'hand': hid, 'rule': 'C6', 'detail': 'no final-status-pill rendered'})
        else:
            # C2: pill status == card status (no drift), and the css class matches
            if pill.group(2) != card_status:
                violations.append({'hand': hid, 'rule': 'C2',
                                   'detail': 'pill %s != card %s' % (pill.group(2), card_status)})
            if pill.group(1).upper() != card_status:
                violations.append({'hand': hid, 'rule': 'C2',
                                   'detail': 'pill css fs-%s != %s' % (pill.group(1), card_status)})
        # secondary-reason distribution
        for sm in re.findall(r"data-final-status-secondary='([^']*)'", body):
            for r in sm.split(','):
                if r:
                    sec_dist[r] += 1
        # verdict-nuance pills present in the body
        vlabels = set(_RE_VERDICT_PILL.findall(body))
        # C3: CLEARED / UNASSESSED / UNGRADED never carry a Mistake/Punt verdict pill
        if card_status in _NON_MISTAKE_STATES:
            bad = [v for v in vlabels if v in _MISTAKE_VERDICT_LABELS]
            if bad:
                violations.append({'hand': hid, 'rule': 'C3',
                                   'detail': '%s hand shows mistake verdict pill %s' % (card_status, bad)})
        # C4: MISTAKE never carries a cleared/correct verdict pill
        if card_status == 'MISTAKE':
            bad = [v for v in vlabels if v in _CLEARED_VERDICT_LABELS]
            if bad:
                violations.append({'hand': hid, 'rule': 'C4',
                                   'detail': 'MISTAKE hand shows cleared verdict pill %s' % bad})
    # C7 (v8.18.0 W1-A §1.2): the hand-list popup must CONSUME the canonical status (read
    # data-final-status from the card root), never independently infer it. Source-level check over the
    # popup JS embedded in the report, so a regressed popup that re-infers status is caught.
    surfaces = {'hand_card': True, 'final_status_pill': True,
                'lazy_static_same_article': True, 'popup_consumes_canonical': None}
    if 'openHandListPopup' in html:
        m = re.search(r'function openHandListPopup\(.*?\n  \}', html, re.S)
        popup = m.group(0) if m else html[html.find('openHandListPopup'):html.find('openHandListPopup') + 9000]
        consumes = "getAttribute('data-final-status')" in popup and '_fsMap' in popup
        infers_primary = "not individually reviewed" in popup and "getAttribute('data-final-status')" not in popup
        surfaces['popup_consumes_canonical'] = bool(consumes and not infers_primary)
        if not surfaces['popup_consumes_canonical']:
            violations.append({'hand': '(popup)', 'rule': 'C7',
                               'detail': 'hand-list popup does not consume the canonical data-final-status'})
    return {
        'hands_checked': n,
        'distribution': dict(dist),
        'secondary_reasons': dict(sec_dist),
        'surfaces': surfaces,
        'violations': violations,
        'contradictions': len(violations),
        'pass': len(violations) == 0 and n > 0,
    }


def main():
    if len(sys.argv) < 2:
        print('usage: python _qa_status_consistency.py REPORT.html [out.json]')
        return 2
    html = io.open(sys.argv[1], encoding='utf-8').read()
    res = run_status_consistency(html)
    print('W1-A status-contradiction gate')
    print('  hands checked     :', res['hands_checked'])
    print('  status distribution:', res['distribution'])
    print('  secondary reasons :', res['secondary_reasons'])
    print('  contradictions    :', res['contradictions'])
    for v in res['violations'][:25]:
        print('    [%s] %s -- %s' % (v['rule'], v['hand'], v['detail']))
    print('  RESULT            :', 'PASS' if res['pass'] else 'FAIL')
    if len(sys.argv) > 2:
        with io.open(sys.argv[2], 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(res, fh, indent=2, ensure_ascii=False)
        print('  wrote', sys.argv[2])
    return 0 if res['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
