# CLAUDE CHAT — QUICK SETUP PROMPT (paste this first)

You are running the GEM Pokerbot runtime. The project was just refreshed to the **operational build
`GEM-main-ee5c105`** (source commit `ee5c105c6684633be03860fbae286ef33f88586e`, branch `main`). This is a
runtime refresh, **not** a formal release — there is no v8.21 tag.

Do exactly this, in order, before anything else:

1. Extract the runtime and work only from the extracted tree:
   ```
   python /mnt/project/gem_src_bundle.py /home/claude/gem
   cd /home/claude/gem
   ```
   Expect: `GEM bundle GEM-main-ee5c105: extracted 167 files`.

2. Copy the flat project CSVs (including `gem_pipeline_learnings.csv`) and install the equity engine:
   ```
   cp /mnt/project/gem_pipeline_learnings.csv . 2>/dev/null || true
   cp /mnt/project/session_*.csv . 2>/dev/null || true
   pip install --quiet phevaluator 2>/dev/null || pip install --quiet phevaluator --break-system-packages || true
   ```

3. Verify and confirm identity (must all pass):
   ```
   python -c "import gem_report_draft, gem_analyzer, gem_runout_transition; print('imports OK')"
   python verify_release.py --project-dir .
   python _test_scratch.py
   python test_runout_transition.py
   python test_runout_wiring.py
   python -c "import sys; sys.path.insert(0,'/mnt/project'); import gem_src_bundle as b; print(b.SOURCE_BRANCH, b.SOURCE_COMMIT)"
   ```
   Expected:
   - `verify_release`: **[PASS] All 69/69 files match, 664/664 canaries pass, 12/12 anti-canaries pass**
   - `_test_scratch.py`: **2024 passed, 0 failed**
   - `test_runout_transition.py`: **78 passed, 0 failed**
   - `test_runout_wiring.py`: **34 passed, 0 failed**
   - identity prints `main ee5c105c6684633be03860fbae286ef33f88586e`

   On ANY failure, STOP and tell Ron — do not improvise.

4. Read the flat prose references directly from `/mnt/project/` (Quick Reference, Analyst Writing Checklist,
   reference docs, Changelog). They are not extracted into the tree.

What's new in this build: the **descriptive Runout Transition** feature. On eligible turn/river decisions the
hand-detail report adds **one** note saying what the new card objectively changed, what remains true, and what
to reassess. It is deterministic and result-independent, renders in both AUTO_ONLY and analyst-integrated
reports, adds **no** analyst-packet decisions and **no** analyst-LLM work, and the strategic action stays
*Insufficient evidence* (no opponent-range / equity / EV calculation). Unresolved / all-in nodes render nothing.

When setup passes, reply "Runtime ready (GEM-main-ee5c105)" and wait for the session prompt.
