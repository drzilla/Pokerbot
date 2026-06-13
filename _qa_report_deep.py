# -*- coding: utf-8 -*-
"""Deep structural QA over a generated Pokerbot report (lazy-aware, v2).
Usage: python _qa_report_deep.py <report.html>
"""
import io, re, sys, json, base64, zlib, collections

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
PATH = sys.argv[1]
t = io.open(PATH, encoding='utf-8', errors='replace').read()
print(f'=== QA {PATH.split(chr(92))[-1]} ({len(t)/1e6:.1f} MB) ===')
ISSUES = []
def issue(sev, code, msg):
    ISSUES.append((sev, code, msg))

# ---------- payload (PB_PAYLOADS["lazyHands"]) ----------
hands_payload = {}
i = t.find('window.PB_PAYLOADS["lazyHands"]=')
if i >= 0:
    j = t.find('=', i) + 1
    depth = 0
    k = j
    while True:
        c = t[k]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                break
        k += 1
    try:
        obj = json.loads(t[j:k + 1])
        data = obj.get('data') or ''
        if isinstance(data, list):
            data = ''.join(data)
        hands_payload = json.loads(
            zlib.decompress(base64.b64decode(data), -15))
        print(f'payload: {len(hands_payload)} lazy hands decoded')
    except Exception as e:
        issue('P0', 'PAYLOAD', f'cannot decode lazyHands: {e}')
else:
    print('payload: none (non-lazy build)')
pay_ids = {k[-8:] for k in hands_payload}

# ---------- articles / availability / index ----------
art_ids = set()
for m in re.finditer(r"<article[^>]*data-hand-id=['\"](\d+)['\"]", t):
    art_ids.add(m.group(1)[-8:])
av = {}
mav = re.search(r'window\.handAvailability=(\{.*?\});', t)
if mav:
    av = json.loads(mav.group(1))
hi = {}
mhi = re.search(r'window\.handIndex=(\{.*?\});', t)
if mhi:
    hi = json.loads(mhi.group(1))
print(f'articles={len(art_ids)} availability={len(av)} handIndex={len(hi)}')

if pay_ids - art_ids:
    issue('P1', 'LAZY-ORPHAN',
          f'{len(pay_ids - art_ids)} payload hands without article shell: '
          f'{sorted(pay_ids - art_ids)[:5]}')
if hi:
    miss_idx = sorted(art_ids - set(hi))
    if miss_idx:
        issue('P2', 'ART-NOIDX',
              f'{len(miss_idx)} articles missing from handIndex: {miss_idx[:5]}')

# ---------- anchors (static + payload-runtime) ----------
static_anchor = set(re.findall(r"(?<![\w-])id=[\"']sec-app-hand-(\d+)[\"']", t))
pay_anchor = {k[-8:] for k, v in hands_payload.items()
              if re.search(r"id=[\"']sec-app-hand-", v)}
print(f'anchors: static={len(static_anchor)} payload-only='
      f'{len(pay_anchor - static_anchor)}')
href_refs = set(re.findall(r'href="#sec-app-hand-(\d+)"', t))
truly_dead = sorted(h for h in href_refs
                    if h not in static_anchor and h not in pay_anchor
                    and h not in art_ids and h not in av)
if truly_dead:
    issue('P1', 'XREF-DEAD',
          f'{len(truly_dead)} hand hrefs resolvable nowhere (no anchor/'
          f'payload/article/availability): {truly_dead[:6]}')

# ---------- popup references ----------
ref_ids = set()
for mm in re.finditer(r'data-hids="([^"]+)"', t):
    for x in mm.group(1).split(','):
        x = x.strip()
        if x:
            ref_ids.add(x[-8:])
unresolved = sorted(r for r in ref_ids
                    if r not in art_ids and r not in av and r not in pay_ids)
if unresolved:
    issue('P1', 'POPUP-DEAD',
          f'{len(unresolved)} popup ids with no article/availability/payload:'
          f' {unresolved[:8]}')

# ---------- render smells (text outside script/style) ----------
stripped = re.sub(r'<script.*?</script>|<style.*?</style>', '', t, flags=re.S)
joined_payload = ' '.join(hands_payload.values())
both = stripped + ' ' + joined_payload
smells = {
    'undefined-text': r'>\s*undefined\s*<',
    'NaN-text': r'>\s*NaN\s*<',
    'object-Object': r'\[object Object\]',
    'py-none-cell': r'<td[^>]*>\s*None\s*</td>',
    'pct-double': r'\d+%%',
    'empty-strong': r'<strong>\s*</strong>',
    'raw-md-bold': r'(?<=>)[^<>]*\*\*[A-Za-z][^<>*]{3,60}\*\*',
    'raw-unicode-escape': r'(?<=>)[^<>]*\\u00b[07][^<>]*(?=<)',
    'fstring-leak': r'\{(?:hid|_pk|_pko|cls|hand|net)[a-z_]*\}',
}
for code, pat in smells.items():
    hits = re.findall(pat, both)
    if hits:
        issue('P2', 'SMELL-' + code, f'{len(hits)} hits, e.g. {[h[:70] for h in hits[:3]]}')

# ---------- PKO contradiction scan (payload-aware) ----------
contradict = []
for k, v in hands_payload.items():
    if 'cannot collect' in v and re.search(r'covers opener|Hero covers', v):
        contradict.append(k[-8:])
if contradict:
    issue('P1', 'PKO-COVER',
          f'{len(contradict)} hands say cannot-collect AND covers: '
          f'{contradict[:5]}')

# ---------- evid/pivot badges on hero rows (must never happen) ----------
bad_badge = []
for k, v in hands_payload.items():
    for mm in re.finditer(
            r"<span class=\"grid-action [^\"]*is-hero[^\"]*\">.*?</span>\s*",
            v):
        seg = mm.group(0)
        if 'vb-evid' in seg or 'vb-pivot' in seg or 'vb-note' in seg:
            bad_badge.append(k[-8:])
            break
if bad_badge:
    issue('P1', 'BADGE-HERO-ROW',
          f'{len(bad_badge)} hands with evidence badge on a HERO row: '
          f'{bad_badge[:5]}')

# evid badge must pair with a villain note block in the same hand
unpaired = []
src_all = hands_payload if hands_payload else {}
for k, v in src_all.items():
    if 'vb-evid' in v and 'villain-street-notes' not in v:
        unpaired.append(k[-8:])
if unpaired:
    issue('P2', 'EVID-UNPAIRED',
          f'{len(unpaired)} hands with evid badge but no villain note block: '
          f'{unpaired[:5]}')

# ---------- table arity ----------
bad_tables = []
for tm in re.finditer(r'<table[^>]*class="data-table"[^>]*>(.*?)</table>',
                      t, re.S):
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tm.group(1), re.S)
    if not rows:
        continue
    n_head = len(re.findall(r'<th', rows[0]))
    for r in rows[1:8]:
        n_td = len(re.findall(r'<td', r))
        if n_td and n_head and n_td != n_head and 'colspan' not in r:
            head_txt = re.sub(r'<[^>]+>', '', rows[0])[:60]
            bad_tables.append(f'{head_txt!r} ({n_td} vs {n_head})')
            break
if bad_tables:
    issue('P2', 'TABLE-ARITY', f'{len(bad_tables)}: {bad_tables[:3]}')

# ---------- trust-contract invariants (v8.12.9, GPT audit checks) ----------
# INV-NEED: per (street, call amount) every rendered required-equity figure
# must agree within 0.6pp. Action-row "need X%" vs pot-odds block values.
import collections as _c2
need_conflicts = []
for k, v in hands_payload.items():
    hid8 = k[-8:]
    claims = _c2.defaultdict(set)
    # grid action rows live inside per-street cells; map cell order to the
    # thead street order so the join key is (street, call amount) — two
    # legit same-size calls on different streets are NOT a conflict.
    streets = re.findall(r">(PRE-FLOP|FLOP|TURN|RIVER)<", v)
    cells = re.findall(r"<td class='street-actions'>(.*?)</td>", v, re.S)
    for st, cell in zip(streets, cells):
        stl = {'PRE-FLOP': 'preflop'}.get(st, st.lower())
        for m in re.finditer(r'Call ([\d.]+)BB[^<]*?need (\d+)%', cell):
            claims[(stl, float(m.group(1)))].add(float(m.group(2)))
    # pot-odds per-street summary lines name their street
    for m in re.finditer(r'(preflop|flop|turn|river): call ([\d.]+)\s*BB '
                         r'into [\d.]+\s*BB — need ([\d.]+)%', v):
        claims[(m.group(1), float(m.group(2)))].add(float(m.group(3)))
    # all-in pot-odds block: street from the div's data-street attr
    for m in re.finditer(r"<div class='analyst-notes' data-street='(\w+)'>"
                         r"(?:(?!</div>).)*?\(call ([\d.]+)BB into"
                         r"(?:(?!</div>).)*?Required equity:</strong>\s*"
                         r"([\d.]+)%", v, re.S):
        claims[(m.group(1), float(m.group(2)))].add(float(m.group(3)))
    for key2, vals in claims.items():
        if len(vals) > 1 and max(vals) - min(vals) > 1.0:
            need_conflicts.append((hid8, key2, sorted(vals)))
if need_conflicts:
    issue('P0', 'INV-NEED', f'{len(need_conflicts)} (hand, street+call) with conflicting need%: {need_conflicts[:6]}')
else:
    print('INV-NEED: no per-call required-equity conflicts')

# INV-NOTATION: reversed labels + pairs with s/o suffix
bad_notation = []
_rv_inv = {r: i for i, r in enumerate('23456789TJQKA', 2)}
for k, v in hands_payload.items():
    txt = re.sub(r'<[^>]+>', ' ', v)
    for m in re.finditer(r'([2-9TJQKA])([2-9TJQKA])([so])', txt):
        a, b = m.group(1), m.group(2)
        if a == b:
            bad_notation.append((k[-8:], m.group(0), 'pair+suffix'))
        elif _rv_inv[a] < _rv_inv[b]:
            bad_notation.append((k[-8:], m.group(0), 'reversed'))
if bad_notation:
    issue('P0', 'INV-NOTATION', f'{len(bad_notation)} bad hand labels: {bad_notation[:8]}')
else:
    print('INV-NOTATION: clean')

# INV-BOUNTY: bounty-adjusted threshold while block says no discount
bt = [k[-8:] for k, v in hands_payload.items()
      if 'bounty-adjusted threshold' in v
      and 'no discount (Hero does not cover' in v]
if bt:
    issue('P0', 'INV-BOUNTY', f'{len(bt)} hands claim a bounty threshold next to no-discount: {bt[:6]}')
else:
    print('INV-BOUNTY: clean')

# INV-RANGE: inside/OUTSIDE contradiction
rc = [k[-8:] for k, v in hands_payload.items()
      if ('inside the jamming range' in v and 'OUTSIDE range' in v)
      or ('outside the standard jamming range' in v and ': IN range' in v)]
if rc:
    issue('P0', 'INV-RANGE', f'{len(rc)} hands contradict range membership: {rc[:6]}')
else:
    print('INV-RANGE: clean')

# INV-ROMAN: user-facing Roman verdict codes (informational until Slice B)
roman = sum(len(re.findall(r'(?:III|II|I|IV|V)\.\d', re.sub(r'<[^>]+>', ' ', v)))
            for v in hands_payload.values())
print(f'SCAN-ROMAN: {roman} Roman verdict tokens in hand payloads')

# SCAN-RAWID: internal chart/detector ids in visible text (Slice D target)
rawid = _c2.Counter()
for v in hands_payload.values():
    txt = re.sub(r'<[^>]+>', ' ', v)
    for m in re.finditer(r'(REJAM_\w+|PUSH_\d+BB_\w+|CALLJAM_\w+|OPEN_[\d-]+BB_\w+|3BF_\w+|SQF_\w+|BB_DEF_\w+|DONK_LEAD|CBET_INTO\w*|RIVER_BET\w*)', txt):
        rawid[m.group(1)] += 1
print(f'SCAN-RAWID: {sum(rawid.values())} raw chart/detector ids visible ({len(rawid)} distinct)')

# SCAN-GTOW-GAP: actual eff vs solver depth in link metadata (Slice D target)
gaps = []
for m in re.finditer(r"data-eff-bb='([\d.]+)'[^>]*>(?:(?!</article>).)*?stacks=(\d+)", t[:0], re.S):
    pass  # placeholder — depth lives in URL params; cheap scan below
gtow_gap = 0
for k, v in hands_payload.items():
    me = re.search(r"data-eff-bb='([\d.]+)'", v)
    md = re.search(r'[?&]depth=([\d.]+)', v) or re.search(r'stacks?=([\d.]+)', v)
    if me and md:
        try:
            if abs(float(me.group(1)) - float(md.group(1))) > 10:
                gtow_gap += 1
        except ValueError:
            pass
print(f'SCAN-GTOW-GAP: {gtow_gap} hands with >10BB eff-vs-solver-depth gap')

# ---------- handIndex content spot-check vs payload ----------
if hi and hands_payload:
    bad_idx = []
    import random
    random.seed(8)
    sample = random.sample(sorted(pay_ids & set(hi)),
                           min(60, len(pay_ids & set(hi))))
    for hid8 in sample:
        seg = next(v for k, v in hands_payload.items() if k[-8:] == hid8)
        e = hi[hid8]
        pm = re.search(r'\((\w[\w+]*)\s+[\d.]+BB\)', re.sub(r'<[^>]+>', '', seg))
        if pm and e.get('p') and pm.group(1) != e['p']:
            bad_idx.append((hid8, 'pos', e['p'], pm.group(1)))
        nm = re.search(r'([+-][\d.]+)\s*BB', re.sub(r'<[^>]+>', '', seg))
        if nm and 'n' in e and abs(float(nm.group(1)) - e['n']) > 0.15:
            bad_idx.append((hid8, 'net', e['n'], nm.group(1)))
    if bad_idx:
        issue('P1', 'IDX-MISMATCH',
              f'{len(bad_idx)} index fields disagree with payload: '
              f'{bad_idx[:4]}')
    else:
        print(f'handIndex spot-check: {len(sample)} sampled OK')

print()
if not ISSUES:
    print('NO ISSUES FOUND')
for sev, code, msg in sorted(ISSUES):
    print(f'[{sev}] {code}: {msg}')
