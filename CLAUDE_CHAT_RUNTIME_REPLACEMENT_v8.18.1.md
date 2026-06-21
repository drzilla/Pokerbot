# Claude Chat Project — Runtime Replacement Instructions (v8.18.1)

A bug-fix hotfix on v8.18.0 (Villain Teaching future-exploit quality). Packaging
only — your session data is retained.

**Order matters — do NOT remove the session files first.** Upload the new
runtime, confirm STEP0 rebuilds, then delete the two superseded files.

---

## DELETE from current Claude Chat project
*(only after the new runtime is uploaded and STEP0 verified)*

| File | Why |
|------|-----|
| `gem_lean_runtime.py` (the v8.18.0 copy) | Replaced by the v8.18.1 lean runtime below. |
| `GEM_Release_Notes_v8.18.0.txt` | Replaced by `GEM_Release_Notes_v8.18.1.txt`. |

> Do **not** delete any `session_*.csv`. The v8.18.1 lean runtime self-extracts
> to **93 files** and still bundles all runtime data lookups — no separate data
> files to upload.

## UPLOAD to Claude Chat project

| File | Notes |
|------|-------|
| `gem_lean_runtime.py` | The v8.18.1 lean runtime (self-extracting; 93 files; 1.81 MB). |
| `GEM_Release_Notes_v8.18.1.txt` | Current-state release notes. |

## RETAIN (leave in the project, unchanged)
- `session_financials.csv`, `session_financials_per_tournament.csv`,
  `session_history_merged_*_recalibrated.csv` (your data; the runtime reads them
  for cross-session financial/variance context)
- `SESSION_START_STEP0_package_rebuild.txt` (bootstrap)

## OPTIONAL / do not upload unless needed
Reference prose only (the engine never reads it): `GEM_Parser_Config.txt`,
`GEM_Parser_Reference.txt`, `GEM_Quick_Reference.txt`, and the GTO / mental-game
guides. Omitting them keeps capacity lower.

---

## STEP 0 after replacement

```
python /mnt/project/gem_lean_runtime.py /home/claude/gem
cd /home/claude/gem
cp /mnt/project/session_*.csv .
pip install phevaluator
python -c "import gem_report_draft, gem_analyzer; print('runtime OK')"
```

---

## Projected Claude Chat project capacity

Capacity limit (calibrated from the observed v8.18.0 baseline): **3,449,130 bytes**.

| Scenario | Total bytes | Projected capacity |
|----------|-------------|--------------------|
| Required upload (lean runtime + bootstrap + session CSVs) | **2,424,879** | **70.3%** |
| Conservative (also keep all optional reference prose) | **2,607,180** | **75.6%** |

- Lean runtime `gem_lean_runtime.py`: **1,810,416 bytes** (includes the bundled
  data lookups; largest single item).
- Retained session CSVs: **592,971 bytes**.

**The package fits safely within the project limit** (70.3% required, 75.6% even
with every optional reference kept). Essentially unchanged from v8.18.0; the
hotfix added ~7 KB of villain-teaching logic.
