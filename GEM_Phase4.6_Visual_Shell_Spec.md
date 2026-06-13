# GEM Phase 4.6 — Visual Shell (the "skin") Implementation Spec

**For:** Ron (Knockman) · **Author:** Claude (Chat) · **Baseline:** v7.99.32 (Phase 4.5 complete)
**Why this exists:** Phase 4.5 delivered the *interactions* (hand popups, drill-down, GTOW hooks)
but deliberately deferred the *visual shell*. The report functions like the redesign but still
wears the old plain stylesheet. This phase ports v29's LOOK into the generator.

**Verified gap (v29 vs current v7.99.32 output):**
| Feature | v29 | current |
|---|---|---|
| `:root` design tokens (CSS variables) | 24 | 0 |
| stat strip | 7 | 0 |
| left nav rail | 1 | 0 |
| grid layout | 5 | 0 |
| sticky topbar | 4 | 1 |
| mobile media queries | 7 | 1 |
| total CSS | ~37K (3 blocks) | ~20K (1 block) |

The generator has essentially none of the visual-shell layer. It's all in `_html_wrap()`'s
page shell — CSS + a small amount of nav HTML/JS. **No analytics, no hand logic, no content.**

---

## 0. GOVERNING RULES (carried from Phase 4.5)
1. **Generator owns all content.** v29 is the PRESENTATION spec only. Never copy a value.
2. **CI stays a `ci-tip` tooltip, never a column.** Don't touch metric-table structure. E2 stays green.
3. **Single-file portable.** All CSS inline in `<style>`, all JS inline in `<script>`. No external deps.
4. **Don't regress Phase 4.5.** The hand popups, pills, `hand-detail-card`, universal-pill gate,
   GTOW flag must all still work. The shell wraps them; it doesn't replace them.
5. All 9 suites + content-parity stay green. Don't touch parser/analyzer/analytics.

---

## 1. SCOPE — four pieces, all CSS/shell
A. **Design-token system** (`:root` CSS variables) — the foundation everything references.
B. **Sticky topbar** — brand lockup + stat strip (clickable KPI cards).
C. **Left nav rail** — section list with active-section tracking on scroll.
D. **Mobile-friendly tables + responsive layout** — grid collapses, tables become readable on phone.
Plus: apply the v29 token-based styling to existing tables/cards (the "skin").

---

## 2. DESIGN TOKENS (port verbatim into `_html_wrap()` `<style>`)
```css
:root{
  --bg:#f6f7fb; --paper:#fff; --ink:#111827; --muted:#667085; --line:#d7dce8;
  --brand:#172554; --brand2:#1d4ed8; --soft:#eef2ff;
  --good:#166534; --bad:#991b1b; --warn:#92400e; --warnbg:#fff7cc;
  --okbg:#ecfdf3; --badbg:#fef2f2; --shadow:0 10px 30px rgba(15,23,42,.08);
}
```
Then migrate existing hardcoded colors in the current stylesheet to reference these tokens
(so the whole report shares one palette). This is the "overall skin" — body bg, paper bg,
text colors, table borders, verdict colors all flow from tokens.

---

## 3. LAYOUT GRID + SIDEBAR (port)
```css
.layout{display:grid;grid-template-columns:260px minmax(0,1fr);gap:18px;
  max-width:1500px;margin:0 auto;padding:18px}
.sidebar{position:sticky;top:150px;height:calc(100vh - 170px);overflow:auto;align-self:start}
```
The page body becomes: `<div class="layout"><aside class="sidebar">…nav…</aside><main class="content">…report…</main></div>`.
The existing report body content goes inside `<main class="content">`; the nav rail is the `<aside>`.

---

## 4. STICKY TOPBAR + STAT STRIP
### HTML (emit at top of body, before `.layout`)
```html
<header class="topbar">
  <div class="top-title"><div class="brand-lockup">
    <div class="pb-logo" aria-hidden="true">PB</div>
    <div class="brand-copy"><h1>{player}, {date}</h1><p>Poker coaching report with GTO analysis</p></div>
  </div></div>
  <div class="stat-strip">
    <a class="stat-card" href="#sec-18"><span>Hands</span><b>{n_hands}</b></a>
    <a class="stat-card" href="#sec-1-1"><span>Tourneys</span><b>{n_tourneys}</b></a>
    <a class="stat-card stat-pos|stat-neg" href="#sec-1"><span>Net</span><b class="value-pos|value-neg">{net}</b></a>
    <a class="stat-card" href="#sec-1"><span>ROI</span><b>{roi}</b></a>
    <a class="stat-card" href="#sec-6"><span>BB/100</span><b>{bb100}</b></a>
    <!-- etc — the key KPIs, each linking to its section -->
  </div>
</header>
```
The stat-strip values come from the GENERATOR's computed financials/KPIs (rd), NOT from v29.
Each card links (`href="#sec-N"`) to the relevant Coach-first section anchor.

### CSS (port)
```css
.topbar{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.96);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--line);
  box-shadow:0 2px 14px rgba(15,23,42,.05);}
.stat-strip{display:flex;gap:8px;overflow-x:auto;padding:0 22px 10px}
.stat-card{min-width:92px;background:#f8fafc;border:1px solid var(--line);
  border-radius:12px;padding:8px 10px;text-decoration:none;color:var(--ink);display:block}
.stat-card:hover{background:var(--soft);border-color:#93c5fd}
.stat-card span{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.stat-card b{display:block;font-size:15px;white-space:nowrap}
.stat-card b.value-pos{color:#15803d} .stat-card b.value-neg{color:#b91c1c}
.stat-card.stat-pos{border-color:#bbf7d0;background:#effdf4}
.stat-card.stat-neg{border-color:#fecaca;background:#fff1f2}
```

---

## 5. LEFT NAV RAIL + ACTIVE-SECTION TRACKING
### HTML (emit in `<aside class="sidebar">`)
One `.nav-row` per Coach-first segment (S1–S18), generated from the same section list
`draft.py` already iterates (`section_emitters`). Each links to the section anchor:
```html
<aside class="sidebar" aria-label="Report navigation">
  <a class="nav-row" href="#sec-1"><b>1 · Reality Check</b><small>variance vs skill</small></a>
  <a class="nav-row" href="#sec-2"><b>2 · Strategic Evaluation</b><small>error taxonomy</small></a>
  ... (one per segment) ...
</aside>
```
### CSS (port)
```css
.nav-row{display:block;text-decoration:none;border-radius:10px;padding:8px 9px;color:#1f2937}
.nav-row b{display:block;font-size:13px}
.nav-row small{display:block;color:var(--muted);font-size:11px}
.nav-row.active,.nav-row:hover{background:#eef2ff;color:#1e3a8a}
```
### Active-tracking JS (inline `<script>`)
IntersectionObserver watches each section heading; the nav-row for the section currently in
view gets `.active`. Port v29's approach (or a clean equivalent):
```javascript
const navObserver = new IntersectionObserver((entries)=>{
  entries.forEach(e=>{ if(e.isIntersecting){
    document.querySelectorAll('.nav-row.active').forEach(n=>n.classList.remove('active'));
    const id=e.target.id; const row=document.querySelector('.nav-row[href="#'+id+'"]');
    if(row)row.classList.add('active');
  }});
},{rootMargin:'-20% 0px -70% 0px'});
document.querySelectorAll('h2[id^="sec-"]').forEach(h=>navObserver.observe(h));
```
Degrades gracefully — if JS off, nav rows are still working anchor links.

---

## 6. MOBILE / RESPONSIVE (port the @media rules)
```css
@media(max-width:980px){
  .layout{display:block;padding:10px}
  .sidebar{position:static;height:auto}
  .stat-strip{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));padding:0 12px 8px}
  .nav-panel{display:flex;overflow:auto;gap:4px;padding:8px}  /* nav becomes horizontal scroll */
}
```
**Mobile tables (the "no horizontal scroll" ask):** wide tables (metric tables, financial
tables) need a mobile card-mode. v29 uses `data-label` attributes on `<td>` (already present
on some tables — grep showed `data-label="CI 90%"`). The pattern: on narrow screens, each row
becomes a stacked card with the column header shown via `td::before{content:attr(data-label)}`.
Confirm which tables already emit `data-label`; for those that don't, add it in the table
emitter. This is the one piece that may touch table emission (to add `data-label`), so scope
it carefully and keep it behind the responsive media query (desktop unaffected).

---

## 7. FILE-CHANGE MAP
- `gem_report_draft/_html.py` — the bulk: `:root` tokens, layout grid, topbar+stat-strip CSS,
  sidebar/nav CSS, mobile @media, nav-tracking JS, and wrapping body content in
  `.layout > .sidebar + .content`. Emit the topbar (with generator KPIs) and nav rail.
- `gem_report_draft/draft.py` — supply the topbar KPI values + the nav section list (it already
  knows the section order from `section_emitters`); pass to the shell.
- Table emitters (`_blocks.py` / `_hand_grid.py` / sections) — ONLY if adding `data-label` for
  mobile card-tables; keep desktop rendering byte-identical.
- `gem_report_lint.py` — B3 contrast already active; verify token-based colors still pass.
- Tests — add a content-parity test: the shell wraps but does not alter section content
  (same blocks, same values, just inside `.content`); topbar/nav are additive.

---

## 8. RISKS
- **Regressing Phase 4.5:** the popups/pills must still work inside `.content`. Test: enriched
  fixture still produces working pills + cards after the shell wraps them.
- **Content-parity:** wrapping body in `.layout/.content` changes structure but not content.
  The parity test must confirm same blocks/values; update it to look inside `.content`.
- **Mobile table `data-label`:** the only change that touches table emission. Desktop output
  must stay identical; the card-mode is media-query-gated. Verify `test_report_draft` and
  golden fragments still pass (or rebaseline if the `data-label` attr changes rendered HTML).
- **Single-file portability:** `backdrop-filter` and IntersectionObserver are well-supported
  but verify graceful fallback (no blur / no active-tracking still leaves a usable report).

---

## 9. SUGGESTED COMMIT SEQUENCE (Claude Code plans, we review)
1. Design tokens + migrate existing colors to tokens (the skin) — visual only, all green.
2. Layout grid: wrap body in `.layout > .sidebar + .content`. Content-parity test updated.
3. Sticky topbar + stat strip (generator KPIs, section links).
4. Left nav rail + active-section IntersectionObserver tracking.
5. Mobile responsive + table card-mode (`data-label`), media-query-gated.
Each commit: 9 suites + content-parity green; Phase 4.5 popups/pills still work; CI tooltip intact.

---

## 10. ACCEPTANCE
Open the generated report in a browser: sticky topbar with clickable KPI cards; left nav that
highlights the current section as you scroll; tables readable on phone width (no horizontal
scroll); the whole thing visually matches v29's look; AND every Phase 4.5 interaction (click
pill → one hand popup, relevant-hands drill) still works. That's the redesign Ron has been
waiting for, fully realized.
