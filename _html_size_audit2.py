import re, io, sys, json, collections, zlib, base64
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
p = r"C:\Users\ron\Downloads\Pokerbot_Knockman_20260609-10_V3 (2).html"
html = open(p, encoding='utf-8', errors='replace').read()

def extract_blob(name):
    m = re.search(re.escape(name) + r'\s*=\s*', html)
    if not m:
        return None
    start = m.end()
    BS = chr(92)
    depth, i, instr, esc = 0, start, None, False
    while i < len(html):
        c = html[i]
        if instr:
            if esc:
                esc = False
            elif c == BS:
                esc = True
            elif c == instr:
                instr = None
        else:
            if c in '"\x27':
                instr = c
            elif c in '[{':
                depth += 1
            elif c in ']}':
                depth -= 1
                if depth == 0:
                    i += 1
                    break
        i += 1
    return html[start:i]

hoc = extract_blob('window.handOpponentContexts')
print(f"handOpponentContexts raw: {len(hoc):,} chars")
try:
    obj = json.loads(hoc)
    print(f"  type={type(obj).__name__}, n_keys={len(obj)}")
    if isinstance(obj, dict):
        k0 = list(obj.keys())[0]
        v0 = obj[k0]
        s0 = json.dumps(v0)
        print(f"  first key={k0}, value size={len(s0):,}")
        print(f"  sample: {s0[:600]}")
        # redundancy: serialize each value, count duplicate sub-objects (atoms)
        all_atoms = []
        def walk(o):
            if isinstance(o, dict):
                if 'dimension' in o or 'read' in o or 'label' in o:
                    all_atoms.append(json.dumps(o, sort_keys=True))
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(obj)
        c = collections.Counter(all_atoms)
        dup_bytes = sum((n-1)*len(s) for s, n in c.items() if n > 1)
        print(f"  atom-like objects: total={len(all_atoms):,}, unique={len(c):,}, duplicate bytes={dup_bytes:,}")
        comp = zlib.compress(hoc.encode('utf-8'), 9)
        print(f"  deflate(9): {len(comp):,} bytes; base64: {len(base64.b64encode(comp)):,}")
except Exception as e:
    print(f"  parse failed: {e}")

vi = extract_blob('window.villainIntel')
if vi:
    comp = zlib.compress(vi.encode('utf-8'), 9)
    print(f"villainIntel raw {len(vi):,}; deflate+b64: {len(base64.b64encode(comp)):,}")

arts = re.findall(r'<article class=["\x27]hand-detail-card[\s\S]*?</article>', html)
allh = ''.join(arts)
comp = zlib.compress(allh.encode('utf-8'), 9)
print(f"all hand cards: raw {len(allh):,}; deflate+b64: {len(base64.b64encode(comp)):,} ({len(base64.b64encode(comp))/len(allh)*100:.0f}%)")

# what's inside a card: tag frequency in cards
tags = collections.Counter(re.findall(r'<(\w+)', allh))
print("top tags in cards:", tags.most_common(10))
spans = re.findall(r'<span class="grid-action[^"]*"', allh)
print(f"grid-action spans: {len(spans):,}")

# how much of the card bytes are villain-evidence / facing strips / notes
for cls in ['analyst-notes', 'facing-strip', 'hand-grid', 'mh-verdict', 'coaching-card', 'note-street']:
    b = sum(len(m.group(0)) for m in re.finditer(r'<div class=[\x27"]' + cls + r'[\s\S]*?</div>', allh))
    print(f"  ~{cls}: {b/1024:.0f} KB (rough)")

# whole-file deflate baseline
wcomp = zlib.compress(html.encode('utf-8'), 9)
print(f"WHOLE FILE deflate(9): {len(wcomp):,} ({len(wcomp)/len(html.encode('utf-8'))*100:.0f}%)")
