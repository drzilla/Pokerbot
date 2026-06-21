# Claude Chat Project — Runtime Replacement Instructions (v8.18.0)

Replace the GEM runtime inside your Claude Chat project with the **lean v8.18.0
runtime**. This is a packaging change only — your session data is retained.

**Order matters — do NOT remove the session files first.** Upload the new
runtime, confirm STEP0 rebuilds, then delete the two superseded files. The
session CSVs are RETAINED throughout.

---

## DELETE from current Claude Chat project
*(only after the new runtime is uploaded and STEP0 verified — see below)*

| File | Why |
|------|-----|
| `gem_src_bundle.py` | Superseded by `gem_lean_runtime.py` (lean, ~30% smaller). |
| `GEM_Changelog.txt` | Full historical changelog; replaced by `GEM_Release_Notes_v8.18.0.txt`. |

> Do **not** delete any `session_*.csv`. Do **not** delete the parser config /
> reference / STEP0 files.

## UPLOAD to Claude Chat project

| File | Notes |
|------|-------|
| `gem_lean_runtime.py` | The v8.18.0 lean report-generation runtime (self-extracting; 82 files; 1.69 MB). |
| `GEM_Release_Notes_v8.18.0.txt` | Current-state release notes (replaces the changelog). |

## RETAIN (leave in the project, unchanged)

| File | Why |
|------|-----|
| `GEM_Parser_Config.txt` | Parser configuration the runtime reads. |
| `GEM_Parser_Reference.txt` | Parser reference. |
| `SESSION_START_STEP0_package_rebuild.txt` | Startup / STEP0 instructions. |
| `session_financials.csv` | Your session financial data. |
| `session_financials_per_tournament.csv` | Per-tournament financial data. |
| `session_history_merged_*_recalibrated.csv` | Recalibrated session history. |

## OPTIONAL / do not upload unless needed
*(reference prose — upload on demand only; omitting them keeps capacity lower)*

`Analyst_Writing_Checklist.md`, `GEM_GTO_Wizard_Guide.txt`,
`GEM_Quick_Reference.txt`, `GTOW_Chrome_Extension_Extraction_Guide.txt`,
`GTO_Texture_Archetypes.txt`, `Live_Poker_Population_Reference.txt`,
`Live_Session_Guide.md`, `MDA_v7_5_Reference.txt`, `Mental_Game_Reference.txt`

---

## STEP 0 after replacement (rebuild the runtime, once per session)

```
python /mnt/project/gem_lean_runtime.py /home/claude/gem
cd /home/claude/gem
cp /mnt/project/session_*.csv .
pip install phevaluator
python -c "import gem_report_draft, gem_analyzer; print('runtime OK')"
```

---

## Projected Claude Chat project capacity

Capacity limit (calibrated from the observed **current = 97%**): **3,449,130 bytes**.

| Scenario | Contents | Total bytes | Projected capacity |
|----------|----------|-------------|--------------------|
| **Before (current)** | full bundle + flat prose + session CSVs | 3,345,656 | **97.0%** |
| **Required upload** | lean runtime + permanent prose (config/ref/STEP0/notes) + session CSVs | **2,305,067** | **66.8%** |
| **Conservative** | required + all optional reference prose | **2,487,368** | **72.1%** |

- Lean runtime `gem_lean_runtime.py`: **1,689,911 bytes** (largest single item).
- Retained session CSVs: **592,971 bytes**.
- Permanent prose (config + reference + STEP0 + release notes): **22,185 bytes**.
- Optional reference prose (if all kept): **182,301 bytes**.

**Result: the proposed package fits safely within the project limit** — 66.8%
required, 72.1% even if every optional reference is kept (both well under 100%).
This frees ~30 points of capacity versus the current 97%.
