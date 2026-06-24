"""Re-evaluate the manual-review ledger against the safety/wording rules AFTER the board-play wording fix.
Deterministic, mechanizable checks per item (the corrected shared-board cases are re-evaluated, not assumed).
Writes v821_range/MANUAL_REVIEW_VERDICTS.json and prints a per-item PASS/FAIL ledger."""
import json
import os
import re

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v821_range')
data = json.load(open(os.path.join(OUT, 'MANUAL_REVIEW_SAMPLE.json'), encoding='utf-8'))

BANNED_STRENGTH = re.compile(r'\b(improved|weakened|counterfeit|showdown value)\b', re.I)
BANNED_BOARDPLAY = ('plays the board', 'supplied by the board', 'complete best five', 'best five is supplied')
RANGE = re.compile(r'\b(range|equity|fold equity|\bev\b|combos?)\b', re.I)
DIRECTIVE = re.compile(r'\b(you should|must (?:bet|call|raise|fold|check)|i recommend|gto says)\b', re.I)
ENUM = re.compile(r'\b(high_card|two_pair|full_house|straight_flush)\b')


def review(item):
    cat = item.get('category')
    text = item.get('rendered') or ''
    low = text.lower()
    fails = []
    if cat == 'unresolved_suppressed':
        if text.strip():
            fails.append('unresolved must render an empty note')
        return ('PASS' if not fails else 'FAIL', fails)
    street = item.get('street')
    contributes = item.get('hole_cards_contribute_after')
    # rule 1: no relative-strength claim
    if BANNED_STRENGTH.search(text):
        fails.append('rule1: banned strength word')
    if 'strategic read: insufficient evidence' not in low:
        fails.append('rule1: missing compact insufficient-evidence line')
    # rule 2: hole-card credit only when contribution proven
    credits_hole = ('your hole cards now make' in low) or ('draw completed: your hole cards now make' in low)
    if credits_hole and contributes is False:
        fails.append('rule2: credits hole cards while contribute=False')
    # rule 3 + board-play: NEVER claim board-play on flop/turn; "complete best five" only on a river
    for ph in BANNED_BOARDPLAY:
        if ph in low and street != 'river':
            fails.append('rule3/boardplay: "%s" on a %s note' % (ph, street))
    if 'complete best five' in low and street != 'river':
        fails.append('boardplay: complete-best-five off the river')
    # a turn shared-category change must defer kickers to the hole cards
    if street == 'turn' and 'every remaining player' in low and 'hole cards' not in low:
        fails.append('boardplay: turn shared note omits the hole-card kicker caveat')
    # rule 6: no raw enum names
    if ENUM.search(text):
        fails.append('rule6: raw enum name')
    # rule 7: no literal markdown underscores wrapping a word
    if re.search(r'_[A-Za-z][^_]*_', text):
        fails.append('rule7: literal markdown underscores')
    # rule 8: no range/equity/EV term or strategic directive in the FACTS (strip the fixed strategic caveat)
    facts_only = re.sub(r'\*\*strategic read.*$', '', low)
    if RANGE.search(facts_only):
        fails.append('rule8: range/equity/EV term in facts')
    if DIRECTIVE.search(low):
        fails.append('rule8: strategic directive')
    return ('PASS' if not fails else 'FAIL', fails)


verdicts = []
for i, item in enumerate(data['ledger']):
    v, fails = review(item)
    verdicts.append({'idx': i, 'category': item.get('category'), 'hand': item.get('hand'),
                     'street': item.get('street'), 'verdict': v, 'fails': fails,
                     'rendered': item.get('rendered') or item.get('reason')})

npass = sum(1 for v in verdicts if v['verdict'] == 'PASS')
nfail = sum(1 for v in verdicts if v['verdict'] == 'FAIL')
out = {'total': len(verdicts), 'pass': npass, 'fail': nfail,
       'failures': [v for v in verdicts if v['verdict'] == 'FAIL'], 'verdicts': verdicts}
json.dump(out, open(os.path.join(OUT, 'MANUAL_REVIEW_VERDICTS.json'), 'w', encoding='utf-8'), indent=2)

print('RE-EVALUATED %d items: %d PASS, %d FAIL' % (len(verdicts), npass, nfail))
print('--- corrected shared-board-pair cases (re-evaluated) ---')
for v in verdicts:
    if v['category'] == 'shared_board_pair_change':
        print('  [%s] %s %s :: %s' % (v['verdict'], v['hand'], v['street'], v['rendered'][:120]))
if nfail:
    print('--- FAILURES ---')
    for v in out['failures']:
        print('  ', v['hand'], v['street'], v['fails'])
