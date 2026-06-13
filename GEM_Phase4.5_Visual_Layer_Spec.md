# GEM Phase 4.5 — Visual Layer Implementation Spec (for Claude Code)

**For:** Ron (Knockman) · **Author:** Claude (Chat) · **Renderer baseline:** v7.99.30
**Status:** Spec complete. Implementation = Claude Code, plan-first.

This is the contract for porting the redesign's *presentation* into the GEM generator. It
merges two redesign branches (v29 modal/look + v27 hand-detail cleanup) and adds per-hand
GTOW URLs built from the generator's real data.

---

## 0. THE GOVERNING RULE — content integrity

The redesign HTML files (v25/v26/v27/v29) were **LLM-generated from GEM reports.** They are
the **presentation spec, NOT the content spec.** The generator owns every value, verdict,
stat, and hand. NEVER copy a value, number, or verdict out of a redesign file into the
report. Reproduce the *look*; the generator renders its own *content*.

**Proof this matters (verified):** v29 has `<th>CI 90%</th>` as a visible column (10+
instances) and ZERO `ci-tip` tooltips. The LLM **reverted** the CI-as-tooltip work that the
metric_status migration (v7.99.30) had already done. Porting v29 naively would re-introduce
CI columns Ron deliberately removed.

**Hard guardrails:**
1. **CI stays a `ci-tip` tooltip on the value cell, NEVER a column.** The generator's current
   `metric_status` grammar (`Metric · Status · Value/Rate ⓘ · Target · Delta · Sample · Notes`)
   is correct. Do not touch metric-table structure. Lint rule E2 ("CI as visible column")
   must continue to pass — if the port reintroduces a CI column, E2 fires; that's a blocker.
2. **Generator owns all hand/stat content.** v29/v27 supply CSS, HTML structure, and JS only.

---

## 1. SCOPE

**This phase:** hand-detail component (v27) + two-popup model (v29, bug-fixed) + per-hand
GTOW URLs (v26 placement + GTOW PDF guide) + universal-pill guarantee + contrast/readability
fixes.

**Deferred to a follow-up phase:** sticky topbar, left nav with active-section tracking,
mobile card-tables. (Independent chrome; touches the page shell, not hand components.)

---

## 2. THE INTERACTION MODEL (the heart of the phase)

Two **distinct** popup types. They never merge. A hand-detail view ALWAYS shows exactly one
hand.

### 2.1 Single-hand popup (hand pill → one hand)
- Trigger: any `a.hand-ref[data-hand-id]` pill anywhere in the report.
- Behavior: clones **exactly one** `hand-detail-card` (the appendix card for that ID) into
  the modal body. Modal title = "Hand review" (the card owns the hand ID; no duplicate).
- **CRITICAL — the v29 bug to fix:** v29's `buildModalHand` calls `handSiblingNodes(target)`,
  which walks `nextElementSibling` collecting nodes until it *guesses* a boundary
  (next hand heading / H2 / HR, guard=80). When appendix hands aren't separated by exactly
  those markers, it **over-collects and pulls the NEXT hand's content into the modal** —
  this is the "more than one hand in a popup" bug Ron flagged.
- **The fix:** do NOT walk siblings. Because v27 wraps each hand in a self-contained
  `article.hand-detail-card`, the modal clones that ONE article by id/selector. One card =
  one hand, structurally. `handSiblingNodes` is deleted entirely.

### 2.2 Relevant-hands list popup (section → list of references)
- Trigger: a per-section "relevant hands" control.
- Data source: the **citation registry** — the hands cited from that section
  (`_get_citations_for` in reverse: hands-per-section). NOT a curated set. The generator
  injects this list per section.
- Behavior: renders a clickable **list of hand references** (ID + cards + brief context) —
  NOT rendered hand details. (v29's `updateContextHands` approximates this by scraping
  `a.hand-ref[data-hand-id]` from the section DOM; the generator should instead emit the
  registry-derived list directly so it's authoritative, not DOM-scraped.)
- Drill: clicking a list entry opens the single-hand popup (2.1) for that hand.

### 2.3 Invariants
- A hand-detail view contains exactly ONE hand. Always.
- The list popup contains references only, never rendered hand details.
- The two popup types never merge.
- localStorage (review notes) degrades gracefully: modal works if storage is blocked; notes
  just don't persist. Single-file portability preserved (everything inline).

---

## 3. UNIVERSAL-PILL GUARANTEE (hard build gate)

**Every `a.hand-ref[data-hand-id]` pill in the entire report MUST open its hand.** No dead
pills, no exceptions. Historically inconsistent; now enforced.

Two enforcement mechanisms:
1. **Build gate:** if any pill references a hand ID with no corresponding appendix
   `hand-detail-card`, the build FAILS (BLOCKER). The citation registry already tracks every
   cited hand (the `appendix_hand_ids_all` deep-harvest, B188) — make it a gate, not a hope.
2. **New lint rule (BLOCKER tier):** "every `data-hand-id` pill has a corresponding appendix
   card; zero orphan pills." Add to `gem_report_lint.py`.

---

## 4. THE HAND-DETAIL-CARD COMPONENT (from v27)

Each appendix hand is emitted as a self-contained card. v27 mapping doc spec:
- Wrap in `article.hand-detail-card` (max-width ~1040px, scannable).
- Hero cards appear ONCE in the hero-hand strip above the action grid — NOT in the title.
- Title carries the hand ID + net result pill only.
- Metadata rebuilt as compact chips (`.hand-meta-chips`): tournament · date · format ·
  level · pot type · effective stack · SPR.
- Remove the duplicate standalone result line (result stays in title net pill + grid footer).
- Stack/coverage table collapsed into a "Stack context" disclosure (renamed from "Hand {id}"
  to avoid duplicate IDs).
- Deduplicate hand-review row summaries (remove repeated board-card arrays).

### 4.1 v27 CSS (extracted — port into the `_html_wrap` shell)
```css
.hand-detail-card{max-width:1040px;margin:18px auto 22px;background:#fff;
  border:1px solid var(--line,#dbe3ef);border-radius:16px;padding:18px;
  box-shadow:0 10px 28px rgba(15,23,42,.05);}
.hand-detail-card + hr{display:none;}
.hand-detail-card .hero-hand{margin:14px 0 8px;padding:10px 12px;border-radius:12px;
  background:#eef4ff;border:1px solid #dbeafe;font-size:16px;}
.hand-detail-card .table-stacks{margin:6px 0 10px;color:#64748b;font-size:12px;}
.hand-detail-card .hand-grid{margin-top:8px;}
.hand-meta-chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 12px;}
/* chip styling, gtow-row, gtow-btn — see v27 file for full set */
```

### 4.2 Generator port target
The `appendix_hand` block / `_hand_grid.py` currently emits the hand detail. It must now emit
the `article.hand-detail-card` structure above. The card is the unit the modal clones.

---

## 5. MODAL SCAFFOLD + CORRECTED JS (from v29)

### 5.1 Modal HTML scaffold (port into the page shell, once)
```html
<div aria-hidden="true" class="modal" id="hand-modal">
  <div class="modal-backdrop"></div>
  <div aria-modal="true" class="modal-panel" role="dialog">
    <div class="modal-head">
      <h3 id="hand-modal-title">Hand review</h3>
      <button id="hand-modal-close" type="button">Close</button>
    </div>
    <div class="modal-body" id="hand-modal-body"></div>
    <div class="modal-review">
      <select id="modal-review-status">
        <option value="">— verdict —</option>
        <option>Agree</option><option>Debate</option><option>Report bug</option>
      </select>
      <textarea id="modal-review-notes" placeholder="Hand review notes — auto-saved while typing"></textarea>
      <div class="save-state" id="modal-save-state">Auto-saved</div>
    </div>
  </div>
</div>
```

### 5.2 JS — port these, with the boundary fix
- `openHand(hid)` — port as-is EXCEPT `buildModalHand` must clone the single
  `hand-detail-card` by id, not call `handSiblingNodes`.
- `closeHand()` — port as-is (backdrop click, Escape, close button).
- `saveModalReview()` — port; wrap localStorage in try/catch for graceful degradation.
- `buildModalHand(hid)` — REWRITE: `const card = document.querySelector('.hand-detail-card[data-hand-id="'+hid+'"]') || document.getElementById('sec-app-hand-'+hid); return card.cloneNode(true);` — ONE card, no sibling walk.
- `handSiblingNodes` — **DELETE.** This is the bug.
- List popup — emit the registry-derived per-section list server-side (generator), render on
  trigger; drilling calls `openHand(hid)`.

---

## 6. GTOW PER-HAND URLs (v26 placement + GTOW PDF guide)

v26 added the button + placement but it opens the GENERIC `app.gtowizard.com/solutions` page
— no per-hand URL ("Exact hand-encoded GTOW URLs are not yet generated. The renderer is
prepared for a future `data-gtow-url` value"). The generator must now POPULATE `data-gtow-url`.

### 6.1 Button placement (from v26)
Per hand-detail-card, after the heading: `.hand-actions > .gtow-row > a.gtow-btn` with
`data-hand-id`, `target="_blank"`, `rel="noopener noreferrer"`, label "Open in GTOW".

### 6.2 URL construction — per the GTOW PDF guide (conservative)
New module `gem_gtow.py`. Implement the guide's linkability classifier + builder:
- **HU postflop** → active button, high confidence. Completed preflop line + board + prior
  postflop actions, target node BEFORE Hero's decision.
- **Multiway postflop** → DISABLED button + tooltip "GTOW unavailable: multiway postflop."
- **Preflop-only** → active only if known-valid sizing path; else label
  "approximate / may fail."
- **Custom solve** → only if `custree_id`/`cussol_id` exist (cannot be derived).
- Encoding: all-in as `R{amount}` (not a special token); board cards do NOT count toward
  `history_spot`; `history_spot` = total action-token count; stacks hyphen-separated,
  `depth` = stacks[0] for now.
- **Labels:** "GTOW sim" / "Open comparable GTOW spot" — NEVER "open exact hand."
- **Manifest first:** produce a CSV/JSON manifest (one row per link: hand_id, street,
  link_status, gametype, depth, stacks, preflop_actions, board, flop/turn/river_actions,
  history_spot, url, notes). Sample-test 10 URLs (HU flop/turn/river, preflop-only, multiway,
  PKO) before patching the full report. Patch only reliable statuses.

### 6.3 Schema hook (from v26 doc)
Each hand gets a `gtow` object: `{status: ready|partial|unavailable, url, spot_summary,
missing_fields}`. The button reads `data-gtow-url` from this.

---

## 7. CONTRAST / READABILITY FIXES
Fix the documented contrast bugs (e.g. highlight/total rows with low-contrast text — the
yellow-bg/white-font issue). These are quick CSS fixes; bundle them since this is a visual
pass. Lint B3 (contrast) is currently a Phase-3b stub — implementing these is a chance to
activate it.

---

## 8. FILE-CHANGE MAP
- `gem_report_draft/_html.py` — modal scaffold + CSS (hand-detail-card, chips, modal,
  ci-tip already present), corrected modal JS, list-popup render, contrast fixes.
- `gem_report_draft/_hand_grid.py` — emit `article.hand-detail-card` structure; chips;
  hero-strip dedup; Stack-context disclosure; `data-hand-id` on the card; GTOW button row.
- `gem_report_draft/_blocks.py` / `appendix_hand` — card wrapper structure.
- `gem_report_draft/_state.py` / citation registry — expose per-section hands-list for the
  list popup (reverse of `_get_citations_for`).
- NEW `gem_gtow.py` — linkability classifier + URL builder + manifest.
- `gem_report_lint.py` — new BLOCKER rule (universal-pill / orphan-pill check); activate B3.
- NEW `test_gtow.py`, additions to `test_lint.py` (orphan-pill rule) and
  `test_content_parity.py` (every pill resolves to a card; CI never a column).

## 9. NON-NEGOTIABLES
Single-file portable HTML (everything inline, no external deps; localStorage optional/
graceful). Generator owns all content (§0). CI stays a tooltip (§0). Every pill opens its
hand (§3). One hand per detail view (§2.3). Preserve analytical depth + poker semantics.
All 9 suites stay green. Don't touch parser/analyzer/analytics logic.

## 10. SUGGESTED COMMIT SEQUENCE (Claude Code plans, we review)
1. Hand-detail-card component (v27) — generator emits the card; appendix renders it; suites green.
2. Modal scaffold + corrected JS (one-card clone, no sibling-walk) — single-hand popup works.
3. List popup from citation registry — drill-to-single-hand works.
4. Universal-pill build gate + orphan-pill lint rule — prove zero dead pills.
5. GTOW: `gem_gtow.py` + classifier + manifest (sample-test before full patch) + button wiring.
6. Contrast fixes + activate B3 lint.
Each commit: 9 suites + content-parity green; one-hand invariant held; CI-tooltip preserved.
