import re, io, sys, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
p = r"C:\Users\ron\Downloads\Pokerbot_Knockman_20260609-10_V3 (2).html"
html = open(p, encoding='utf-8', errors='replace').read()
total = len(html.encode('utf-8'))
print(f"TOTAL: {total:,} bytes ({total/1e6:.2f} MB)")

def tot(pattern, flags=0):
    return sum(len(m.group(0).encode('utf-8')) for m in re.finditer(pattern, html, flags))

style_b = tot(r'<style[\s\S]*?</style>')
script_b = tot(r'<script[\s\S]*?</script>')
print(f"<style> blocks: {style_b:,} ({style_b/total*100:.1f}%)")
print(f"<script> blocks: {script_b:,} ({script_b/total*100:.1f}%)")

arts = re.findall(r'<article class=["\x27]hand-detail-card[\s\S]*?</article>', html)
art_b = sum(len(a.encode('utf-8')) for a in arts)
print(f"hand-detail-card articles: n={len(arts)}, {art_b:,} bytes ({art_b/total*100:.1f}%)")
if arts:
    sizes = sorted(len(a.encode('utf-8')) for a in arts)
    print(f"  per-card: min={sizes[0]:,} med={sizes[len(sizes)//2]:,} max={sizes[-1]:,} avg={art_b//len(arts):,}")

inline_styles = re.findall(r'style=[\x27"][^\x27"]*[\x27"]', html)
is_b = sum(len(s.encode('utf-8')) for s in inline_styles)
print(f"inline style= attrs: n={len(inline_styles):,}, {is_b:,} bytes ({is_b/total*100:.1f}%)")
for s, c in collections.Counter(inline_styles).most_common(8):
    print(f"   {c:>6}x ({c*len(s.encode('utf-8'))//1024:>4} KB) {s[:90]}")

titles = re.findall(r'title=[\x27"][^\x27"]*[\x27"]', html)
ti_b = sum(len(s.encode('utf-8')) for s in titles)
print(f"title= attrs: n={len(titles):,}, {ti_b:,} bytes ({ti_b/total*100:.1f}%)")
for s, c in collections.Counter(titles).most_common(5):
    print(f"   {c:>6}x {s[:80]}")

onclicks = re.findall(r'onclick="[^"]*"', html)
oc_b = sum(len(s.encode('utf-8')) for s in onclicks)
print(f"onclick attrs: n={len(onclicks):,}, {oc_b:,} bytes ({oc_b/total*100:.1f}%)")

datas = re.findall(r'data-[a-z-]+=[\x27"][^\x27"]*[\x27"]', html)
da_b = sum(len(s.encode('utf-8')) for s in datas)
print(f"data-* attrs: n={len(datas):,}, {da_b:,} bytes ({da_b/total*100:.1f}%)")
dk = collections.Counter(re.match(r'data-[a-z-]+', d).group(0) for d in datas)
dsz = collections.defaultdict(int)
for d in datas:
    dsz[re.match(r'data-[a-z-]+', d).group(0)] += len(d.encode('utf-8'))
for k, b in sorted(dsz.items(), key=lambda x: -x[1])[:8]:
    print(f"   {k}: {dk[k]:,}x, {b/1024:.0f} KB")

ws = sum(len(m.group(0)) for m in re.finditer(r'\n[ \t]+', html))
print(f"leading indentation: {ws:,} bytes ({ws/total*100:.1f}%)")

BS = chr(92)
for m in re.finditer(r'(window\.[A-Za-z_$][\w$]*|var [A-Za-z_$][\w$]*|const [A-Za-z_$][\w$]*)\s*=\s*', html):
    start = m.end()
    ch = html[start:start+1]
    if ch in '[{':
        depth, i, instr, esc = 0, start, None, False
        while i < len(html) and i < start + 4_000_000:
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
                        break
            i += 1
        size = i - start
        if size > 30_000:
            print(f"JS blob {m.group(1)}: {size:,} bytes ({size/total*100:.1f}%)")

# section-level split by <section id=
secs = [(m.start(), m.group(1)) for m in re.finditer(r'<section[^>]*id="(sec-[^"]+)"', html)]
secs.append((len(html), 'END'))
print("--- top-level section sizes ---")
sizes = []
for i in range(len(secs)-1):
    sizes.append((secs[i+1][0]-secs[i][0], secs[i][1]))
for b, name in sorted(sizes, reverse=True)[:14]:
    print(f"   {name}: {b/1024:.0f} KB ({b/total*100:.1f}%)")
