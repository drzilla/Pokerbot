# GEM P1 — `gem_report_draft.py` Package Split — Execution Spec

**For:** a Claude Code session executing P1.
**Drafted:** 2026-05-23, from a live audit of `gem_report_draft.py` (9,797 lines —
note: grew past the handoff plan's 9,729).
**Status of prior phases:** P2 done (changelog extracted). P3 settled. P4 done
(zero dead modules). This spec supersedes the handoff plan's P1 section where they
differ — three corrections are flagged inline as ⚠.

---

## ⚠ Three corrections to the handoff plan

1. **Package name must be `gem_report_draft/`, NOT `gem_report/`.**
   The plan's hard constraint is "public API import lines frozen — `gem_analyzer`'s
   import line never changes." That line is `from gem_report_draft import
   generate_report_draft, render_html, render_md`. To keep it byte-identical, the
   package directory must be named `gem_report_draft/` (a directory replacing the
   `.py` file of the same stem). The plan's `# gem_report/__init__.py` snippet
   contradicts its own frozen-import constraint. Use `gem_report_draft/`.

2. **A `_state.py` module is required — it is not in the plan.** See the Shared
   State Hazard section below. This is the one genuinely non-mechanical part.

3. **Section XIV needs its own module.** The plan lists `sections_xiii.py` for the
   appendix but omits Section XIV (`_emit_section_xiv_appendix` + 8 helpers,
   ~790 lines, L8987–9778). Added as `sections_xiv.py`.

Also note: `VERSION = "v7.64"` constant (L193) is **stale** — changelog is at v7.76.
Not a P1 concern (doesn't affect behavior), but fix it when P1 bumps the version.

---

## The Shared State Hazard (READ BEFORE SPLITTING)

`gem_report_draft.py` has **exactly four** rebindable module-level globals
(confirmed exhaustively — the `global` keyword appears only at L381/396/405/420/442):

| Global | Type | Rebound at | Mutated-in-place at | Read at |
|---|---|---|---|---|
| `_CITATIONS` | dict | L421 (`_reset_citations`) | L412, L445, **L7415** | L428, L430 |
| `_CURRENT_SECTION_ANCHOR` | str/None | L397, L422 | — | L406, L409, L413 |
| `_CURRENT_SECTION_LABEL` | str/None | L398, L423 | — | L413 |
| `_APPENDIX_HAND_IDS` | set | L382 | — | L364 |

**Why this breaks a naive split:** these globals are written by some functions and
read by others that will land in *different* modules. `Doc.subsection()/section()`
(→ `_html.py`) call `_set_current_section`. `_emit_section_vii` (→ `sections_iv_xii.py`)
mutates `_CITATIONS` directly at L7415. `_hand_ref` (→ `_helpers.py`) reads
`_APPENDIX_HAND_IDS`. If each module gets its own copy via `from X import _CITATIONS`,
a rebinding (`_CITATIONS = {}` in `_reset_citations`) leaves every other module
pointing at the **stale** object. Citation tracking and appendix backlinks then
silently break — exactly the failure the byte-diff gate exists to catch, but it is
cheaper to design it out.

**Prescribed fix — `_state.py`:**

- `_state.py` holds all four globals **and** their six accessor functions:
  `_set_appendix_hand_ids`, `_set_current_section`, `_record_citation`,
  `_reset_citations`, `_get_citations_for`, `_record_citation_explicit`.
- Every other module imports the **module object**, never the names:
  `from gem_report_draft import _state` (or `import gem_report_draft._state as _state`).
- All **writes** go through the accessor functions.
- All **reads of the rebindable scalars** use attribute access on the module —
  `_state._CURRENT_SECTION_ANCHOR`, `_state._APPENDIX_HAND_IDS` — which always sees
  the current binding. NEVER `from _state import _CURRENT_SECTION_ANCHOR`.
- The direct mutation at **L7415** inside `_emit_section_vii` must be rewritten to
  call `_state._record_citation_explicit(...)` (or `_state._CITATIONS.setdefault`).
  This is the one line of real logic change in the whole split; everything else is
  a move. Verify it against the byte-diff.

Constants (`_RANK_ORD`, `_OUTCOME_LABELS`, `_SUIT_HTML`, `_RANK_VALUES`,
`_SUIT_VALUES`, `_KD_CLASS_VERB`, `_KD_CLASS_PATTERNS`, `_CI_Z_DEFAULT`,
`_MIN_N_FOR_SIGNAL`, `VERSION`) are never rebound after definition — safe to
`from X import` or co-locate with their primary consumer.

---

## Target package layout — `gem_report_draft/`

12 files. Each row is a contiguous line range in the current file (defs are
sequential by line number, so the split is a set of clean cuts).

| New file | Source lines | Contents |
|---|---|---|
| `__init__.py` | (new) | Re-exports (see list below). Package marker. |
| `_state.py` | L376–446 + globals | 4 globals + 6 accessors. ~80 lines. **NEW.** |
| `_helpers.py` | L44–760 (minus the 6 accessors → `_state`) | `_wilson_ci`, `_clr_naive`, `_clr`, `_clr_min`, `_pctc`, `_stat_signal`, `_verdict_ci`, `_verdict_pct`, `_compact_range`, `_emit_correct_ranges`, `_outcome_label`, `_run_emoji`, `_hand_ref`, `_compute_pot_by_street`, `_render_action_lines`, `_street_cards`, `_break_at_sentences`, `_href`, `_hand_ref_short`, `_xref`, `_stat_row`, `_stat_row_pct`, `_aim_lookup_from_watchlist`, `_back_to_kpis` + consts `_RANK_ORD`, `_OUTCOME_LABELS`, `_CI_Z_DEFAULT`, `_MIN_N_FOR_SIGNAL`. `_hand_ref` reads `_state._APPENDIX_HAND_IDS`. |
| `_html.py` | L761–1599 | `class Doc`, `_html_escape`, `_md_to_html`, `_is_table_sep`, `_md_inline`, `_html_wrap`, `_card_html`, `_cards_html`, `_sort_cards_desc`, `_describe_made_hand`, `_cards_str_to_pills`, `_cards_text_to_pills` + consts `_SUIT_HTML`, `_RANK_VALUES`, `_SUIT_VALUES`. `Doc.subsection/section` call `_state._set_current_section`. |
| `_hand_grid.py` | L1600–2457 | `_key_decision_action_class`, `_pick_key_action_idx`, `_argument_is_structured`, `_parse_structured_argument`, `_note_inline`, `_emit_structured_note`, `_split_argument_into_notes`, `_render_hand_grid_table`, `_hero_actions_by_street_from_app`, `_hero_action_verbs_by_street_from_app` + consts `_KD_CLASS_VERB`, `_KD_CLASS_PATTERNS`. |
| `tldr.py` | L2625–3843 | `_emit_tldr` (L2625–3762, **1,138 lines**), `_emit_leak_watchlist`, `_emit_legend`. See ⚠ deferral note below. |
| `sections_financial.py` | L3844–5038 | `_emit_daily_summary_table`, `_emit_skill_index_movement`, `_emit_section_i`, `_emit_section_ii`. |
| `sections_mistakes.py` | L5039–6105 | `_emit_mental_game`, `_emit_section_iii`. |
| `sections_iv_xii.py` | L6106–8180 | `_emit_section_iv` … `_emit_section_xii`, `_emit_csv_group`, `_emit_csv_remaining`. `_emit_section_vii` has the L7415 `_CITATIONS` write — route through `_state`. |
| `sections_xiii.py` | L8181–8986 | `_emit_section_xiii`. |
| `sections_xiv.py` | L8987–9778 | `_eai_one_liner`, `_per_tourney_one_liner`, `_short_tournament`, `_bust_verdict`, `_generate_cheat_sheet`, `_street_from_text`, `_xivb_flag_note`, `_compute_per_tourney_pnl`, `_emit_section_xiv_appendix`. **NEW module (plan omitted XIV).** |
| `draft.py` | L2458–2624 + L9779–end | `render_html`, `render_md`, `_build`, `_compute_table_size_breakdown`, `_emit_header`, `generate_report_draft`. Top-level orchestration. |

Module-level `import gem_made_hands as mh` / `import gem_coaching as _coach` (L195–197):
re-declare in whichever modules actually use `mh` / `_coach` (grep to confirm before
deleting from any file).

### ⚠ `_emit_tldr` sub-split — defer to P1b

The plan wants the 1,138-line `_emit_tldr` "broken into sub-emitters." That is
refactoring *inside a function* — genuine logic restructuring, not a move, and the
highest-risk change in the whole effort. **Do not combine it with the file split.**
P1 = move `_emit_tldr` verbatim into `tldr.py`. The byte-diff gate then proves the
split alone changed nothing. Breaking `_emit_tldr` into sub-emitters is **P1b**, a
separate session with its own byte-diff gate, so if the diff goes non-empty you know
which change caused it.

---

## `__init__.py` re-export list

`gem_analyzer.py:58` imports the 3 public names. The test suites *also* import
internals directly — to keep them green with **zero test edits**, `__init__.py` must
re-export everything the tests reach. Confirmed importers:

- `gem_analyzer.py` → `generate_report_draft`, `render_html`, `render_md`
- `test_csv_row_complete.py` → `generate_report_draft`
- `test_metrics.py` → `_wilson_ci`, `_clr`, `_clr_min`, `_stat_signal`
- `test_report_draft.py` (via `grd.<name>`) → `_compute_pot_by_street`,
  `_reset_citations`, `_set_current_section`, `_record_citation`,
  `_get_citations_for`, `_hand_ref`, `_argument_is_structured`,
  `_cards_str_to_pills`, `_key_decision_action_class`,
  `_parse_structured_argument`, `_pick_key_action_idx`

```python
# gem_report_draft/__init__.py
from .draft   import generate_report_draft, render_html, render_md
from .helpers_compat import (          # see note — actual module is _helpers
    _wilson_ci, _clr, _clr_min, _stat_signal, _hand_ref,
    _compute_pot_by_street, _cards_str_to_pills,
)
from ._state  import (
    _reset_citations, _set_current_section, _record_citation, _get_citations_for,
)
from ._hand_grid import (
    _argument_is_structured, _key_decision_action_class,
    _parse_structured_argument, _pick_key_action_idx,
)
```
(Adjust the `from ._helpers import` line — the placeholder `helpers_compat` above is
just to flag that these come from `_helpers.py`.)

### ⚠ `test_report_draft.py` loads by file path

`test_report_draft.py` uses `importlib.util` (L25/L41) to load the module — likely by
**file path** to `gem_report_draft.py`. When the file becomes a package directory,
that path load breaks. Point it at `gem_report_draft/__init__.py`, or switch to a
plain `import gem_report_draft as grd`. This is a **test-infrastructure** change
(import mechanism), not a behavior change — permitted, but call it out in the commit.
Inspect L25–48 of `test_report_draft.py` first and adjust minimally.

---

## Execution procedure (gated)

Run in Claude Code, in a working copy — never against `/mnt/project/` directly.

1. **Baseline.** Copy project files to the working dir. Run all five suites as
   scripts (`python3 test_*.py`). Confirm green beyond the one known false-failure
   `test_b144_tldr_no_hand_in_both_top_hands_and_top_leaks` (fails only because no
   prior report file exists in a fresh dir — it is not a regression). Record actual
   pass counts: parser ALL, detectors 85/85, solver 49/49, metrics 530/530,
   report_draft 33+1-known-fail.
2. **Freeze the baseline.** `cp gem_report_draft.py gem_report_draft_ORIG.py`. This
   copy is the diff harness's "before" and the rollback anchor. Do not edit it.
3. **Build `_state.py` first.** Move the 4 globals + 6 accessors. Rewrite the L7415
   `_emit_section_vii` direct mutation to go through `_state`.
4. **Build the package** file by file per the table. `gem_report_draft/` directory;
   delete the old `gem_report_draft.py` only after the package is in place. Each
   module: imports at top, then constants, then defs. Cross-module refs become
   `from gem_report_draft import _helpers` etc. Reads of rebindable state →
   `_state.<global>` attribute access.
5. **Write `__init__.py`** with the re-export list above.
6. **Adjust `test_report_draft.py`** import mechanism if it loads by file path.
7. **GATE 1 — tests.** Run all five suites. Every suite exit 0 except the one known
   false-failure. Any *other* failure → fix in the working copy; project is still on
   `_ORIG`, untouched.
8. **GATE 2 — byte-identical output.** Run `p1_diff_harness.py` (separate file). It
   imports `gem_report_draft_ORIG` (old) and `gem_report_draft` (new package),
   renders HTML + MD from the same fixture session, and diffs. **Empty diff = proven
   zero behavior change.** Non-empty diff = the split broke something; fix before
   proceeding. This gate is stronger than the tests.
9. **Only after both gates pass:** stage the package to `/mnt/user-data/outputs/`,
   keep `gem_report_draft_ORIG.py` available, run one real session end-to-end on the
   new package. When that confirms, the old file can be retired — last step, only
   destructive step.
10. Bump `VERSION` in `draft.py`, bump the Quick Ref version header, write the P1
    changelog entry into `GEM_Changelog.txt`. Fold in the P4 `gem_skill_review`
    standalone-tool note (provided separately).

## Hard constraints (from the handoff plan — unchanged)

- All five suites exit 0 before and after (excluding the one known false-failure).
- Rendered HTML + MD **byte-identical** to `_ORIG` on a fixture session.
- Public API import lines frozen — hence `gem_report_draft/` not `gem_report/`.
- Zero behavior change. P1 is a move; the only logic edit is the L7415 re-route, and
  the byte-diff must absorb it cleanly.
- Complete replacement files. Deliver only what changed.
- No new import cycles. Dependency direction: `_state` ← `_helpers` ← `_html` ←
  `_hand_grid` ← `tldr`/`sections_*` ← `draft`. Keep it acyclic.

## Verification checklist

- [ ] All five suites exit 0 (excluding `test_b144...`)
- [ ] `p1_diff_harness.py` reports empty HTML diff and empty MD diff
- [ ] `from gem_report_draft import generate_report_draft, render_html, render_md`
      works unchanged (the `gem_analyzer` line)
- [ ] No import cycle (`python3 -c "import gem_report_draft"` clean)
- [ ] `gem_report_draft_ORIG.py` retained until a real session confirms the package
- [ ] `VERSION` bumped, Quick Ref version bumped, `GEM_Changelog.txt` entry written
