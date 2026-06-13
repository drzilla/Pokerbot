Phase 4 Plan — Patched
======================
Corrections applied after codebase verification (Step 1).


Corrected counts (vs original plan)
------------------------------------

| Claim in original plan | Actual (verified by grep) | Delta |
|------------------------|---------------------------|-------|
| "260+ sec- references across 7 files" | 234 across 10 files | -26 refs, +3 files |
| "7 _record_citation_explicit() calls" | 6 call sites (+ 1 definition in _state.py) | -1 (was miscounting the definition) |
| "32 _xref() calls" | 35 call sites across 5 emitter files (+ 1 definition in _helpers.py, + 1 comment in _html.py) | +3 |
| "15 _back_to_kpis() calls" | 10 call sites, all in sections_iv_xii.py (+ 1 definition in _helpers.py) | -5 |
| "82 doc.section/subsection calls" | 82 across 5 files (verified) | 0 — correct |

Detailed sec- reference breakdown (234 total):
  sections_iv_xii.py   61
  sections_financial.py 43
  tldr.py               35
  sections_xiii.py      34
  sections_mistakes.py  33
  sections_xiv.py       12
  _helpers.py            7
  _html.py               6
  _state.py              2
  draft.py               1

6 explicit-citation call sites:
  1. sections_mistakes.py:812   — sec-iii-2, 'III.2 Strategic Leak example'
  2. sections_mistakes.py:1403  — sec-iii-8, "III.9 Pokerbot's Picks"
  3. sections_mistakes.py:1440  — sec-iii-8, "III.8 Pokerbot's Picks (Candidates)"
  4. tldr.py:675                — sec-top-leaks (UNCHANGED — preamble anchor)
  5. sections_iv_xii.py:1611   — sec-viii-7-avoidable, 'VIII.7 Avoidable CRs (L1)'
  6. sections_iv_xii.py:2167   — sec-iv-6, "IV.6 Solver Confirmation Pass"


Correction: _compute_iii_state() not needed
--------------------------------------------
iii_state_audit.md proves that ZERO shared state crosses subsection boundaries
in _emit_section_iii.  Each subsection recomputes all data from (s, rd, hands).
The header block (lines 188-232) feeds only the section header and E2 summary.

Impact on commit plan:
  - Commit 2a ("extract _compute_iii_state as no-op refactor") is ELIMINATED.
  - Commit 2 becomes: split _emit_section_iii into 4 sub-emitters, each taking
    (doc, s, rd, hands).  No shared-state helper needed.
  - Similarly for Section II: _emit_mental_game is already separate; II.4 Bluff
    Profile reads s['bluff_profile'] independently.  Commit 3 splits
    _emit_section_ii at line 1558 — no shared-state helper needed either.


Markdown-compat decision: <<ANCHOR_COMPAT:X>> in render_md()
-------------------------------------------------------------
HTML: <<ANCHOR_COMPAT:X>> renders as:
  <span id="X" class="anchor-compat"></span>
  (zero-height invisible element — old URL #X scrolls correctly)

Markdown: <<ANCHOR_COMPAT:X>> renders as nothing (stripped).
  Rationale: Markdown output has no browser navigation; anchors in MD are
  consumed by markdown-to-HTML converters (GitHub, etc.) which only parse
  heading-level ids.  Emitting invisible spans would pollute the MD with raw
  HTML that some renderers choke on.  Old anchors in MD mode are simply gone —
  the canonical new anchor in the heading is all that's needed.

Implementation: In _html.py render_html(), the ANCHOR_COMPAT sentinel is
processed in the line loop alongside ANCHOR.  In render_md(), it is consumed
and discarded (empty string).


L3 golden-fragment re-baseline (commit 5)
------------------------------------------
Commit 5 (the reorder commit) changes anchor strings in rendered output.
test_blocks.py L3 golden-fragment tests compare rendered output against
stored fragments — anchor strings are part of those fragments.

After commit 5:
  1. Run test_blocks.py — L3 tests will FAIL (expected).
  2. Regenerate golden fragments with the new anchor strings.
  3. Re-run test_blocks.py — L3 tests pass.
  4. Include the regenerated golden fragments in commit 5.

This mirrors Phase 2's approach: intentional output change with explicit
re-baseline, not silent drift.


Updated commit sequence
-----------------------
Commit 1: _anchor_map.py (skeletal) + compat redirect layer in Doc +
          _xref() Arabic-label derivation + _back_to_kpis() future anchor.
          Behavior-neutral.  All 8 suites green.

Commit 2: Split _emit_section_iii into 4 sub-emitters.  Still called from
          the SAME position in section_emitters list (III slot).  All 8
          suites green + content-parity.  (No 2a/2b split needed — no
          shared state to extract first.)

Commit 3: Split _emit_section_ii into 2 sub-emitters.  Still called from
          the SAME position in section_emitters list (II slot).  All 8
          suites green + content-parity.  (No shared state.)

Commit 4: Rename anchors inside all sub-emitters to Arabic (sec-1, sec-2-1,
          etc.).  Compat redirects emit old anchors.  Update
          test_citation_timing and test_citation_explicit_timing for new
          anchors.  All 8 suites green + content-parity.

Commit 5: Reorder section_emitters list to Coach-first 18-segment order.
          Re-baseline L3 golden fragments.  Update citation-timing tests
          for new emission order.  All 8 suites green + content-parity.

Commits 6-11: Per-file cross-reference cleanup (one file per commit).
          6: tldr.py
          7: sections_financial.py
          8: sections_mistakes.py
          9: sections_iv_xii.py
          10: sections_xiii.py
          11: sections_xiv.py (emoji patterns + backlink anchor patterns)


Segment labels: S not section-sign
-----------------------------------
All heading labels use "S" prefix: S1, S1.1, S3.2, etc.
Anchors use sec-{n}-{sub}: sec-1, sec-1-1, sec-3-2.
_xref() auto-label produces "S8.3" from "sec-8-3" (not "section-sign 8.3").
Rationale: section-sign conflicts with handoff's "section-sign 3 grammar references" in
code comments and TABLE_GRAMMAR docstrings.
