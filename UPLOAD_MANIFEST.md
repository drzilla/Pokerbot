# UPLOAD MANIFEST — GEM Claude Chat Quick Update (`GEM-main-ee5c105`)

Operational Chat runtime refresh from merged `main`. **Not a release** — no tag was created.

- Source commit: `ee5c105c6684633be03860fbae286ef33f88586e` (branch `main`)
- Runout Transition merge in history: `d3aa50786d7a6ef9e1df06d730c60fe972c7b571`
- Feature source commit in history: `330ff778703fb2dbea45248fd06daba9476fb165`
- Bundle: `gem_src_bundle.py` — BUILD_LABEL `GEM-main-ee5c105`, 167 files, zip sha256[:16] `530405cd798f2b12`

## Files in this package (upload all to the Claude Chat project)

| # | File | Role | Action in Chat |
|---|---|---|---|
| 1 | `gem_src_bundle.py` | self-extracting runtime (the entire source tree) | **REPLACE** the existing bundle |
| 2 | `SESSION_START_STEP0_package_rebuild.txt` | session STEP-0 setup (extract + verify + run) | **REPLACE** the existing copy (updated for this build) |
| 3 | `gem_pipeline_learnings.csv` | flat pipeline-learnings data the resolvers glob | upload/ensure present (replace if Chat's copy is older) |
| 4 | `CLAUDE_CHAT_QUICK_SETUP_PROMPT.md` | paste-first setup prompt | upload (new) |
| 5 | `CLAUDE_CHAT_TODAY_SESSION_PROMPT.md` | run-today session prompt | upload (new) |
| 6 | `UPLOAD_MANIFEST.md` | this manifest | upload (new) |
| 7 | `SHA256SUMS.txt` | SHA-256 of files 1–6 | upload (integrity sidecar) |

## NOT included (and why)

Unchanged flat references stay as the Chat project's existing copies — re-confirmed unchanged from `main`
before the merge (`93637eb`) to `ee5c105`: `GEM_Quick_Reference.txt`, `GEM_Changelog.txt`,
`Analyst_Writing_Checklist.md`, and the other reference docs. Do **not** re-upload them.

Also deliberately excluded: generated reports, analyst packets / analyst outputs, session caches, hand
histories, screenshots, pilot corpora, feature-development evidence, obsolete per-hand JSON.

## After uploading

In a new session, paste `CLAUDE_CHAT_QUICK_SETUP_PROMPT.md`. Setup must report: `verify_release` **[PASS]
69/69**, `_test_scratch.py` **2024/2024**, `test_runout_transition.py` **78/78**, `test_runout_wiring.py`
**34/34**, and identity `main ee5c105c6684633be03860fbae286ef33f88586e`. Then paste
`CLAUDE_CHAT_TODAY_SESSION_PROMPT.md` and attach today's session. Exact hashes: see `SHA256SUMS.txt`.
