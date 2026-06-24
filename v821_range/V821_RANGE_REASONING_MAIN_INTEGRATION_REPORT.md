# V821_RANGE_REASONING_MAIN_INTEGRATION_REPORT

Integration of the v8.21 Range Reasoning foundation (descriptive Runout Transition) into `main`.

## Git identity

| Item | Commit |
|---|---|
| Feature tip (certified, retained) | `330ff778703fb2dbea45248fd06daba9476fb165` |
| `main` before merge | `93637eb3285bcc9fa4aa1e86aab8a2b4e6788912` |
| Merge commit (`--no-ff`, no squash; parents `93637eb` + `330ff77`) | `d3aa50786d7a6ef9e1df06d730c60fe972c7b571` |
| Final pushed `main` | the documentation-reconciliation commit on top of the merge (this commit); recorded in the run output and verifiable via `git -C <main worktree> rev-parse HEAD` |
| `v8.20.0` (unchanged) | `d72ed955a868457f84ea917924aa55db17efecad` |
| Safety ref (retained) | `v8.21-range-reasoning-base` = `93637eb` |
| Release tag | none created |

## Product capability integrated

On eligible turn/river decisions, Pokerbot explains what the new card objectively changed, what remains true,
and what the player should reassess, directly inside the existing hand-detail report. Deterministic and
result-independent; ≤ 1 transition note per turn/river street; live in the existing note surface; no analyst-LLM
workload; 0 analyst-packet decisions; no opponent-range/equity/EV/fold-equity computation; no
continue/resize/pivot/abandon recommendation; strategic action remains *Insufficient evidence*; unresolved /
all-in render nothing.

## Deferred strategic scope

The strategic recommendation layer is **blocked** by the missing canonical **opponent-range / fold-equity
owner** (debt **D1**) and is not started. This is the single dependency that would unblock continue/resize/
slow/pivot/abandon; until then the descriptive layer ships and the strategic line stays *Insufficient evidence*.

## Pre- and post-merge gate results

Raw logs: `v821_range/merge_logs/`.

| Gate | Pre-merge (feature `330ff77`) | Post-merge (`main` `d3aa5078`) |
|---|---|---|
| `test_runout_transition.py` | 78/78 | 78/78 |
| `test_runout_wiring.py` | 34/34 | 34/34 |
| `_test_scratch.py` | 2024/2024 | 2024/2024 |
| `verify_release.py --project-dir <worktree>` | [PASS] 69/69 | [PASS] 69/69 |
| import smoke | OK | OK |
| seven-fixture Results | PASS | PASS |
| full report smoke (Runout notes render) | (proven on this code) | **V9: 104 hands with a note, 0 dup, 0 invalid wording** |
| analyst packet | 0 transition decisions; schema unchanged | required=34 optional=8, zero_calc=True, 0 transition decisions |

Post-merge `main` contains the exact approved descriptive capability; existing commentary, Tournament Results,
and navigation remain intact; no duplicate transition notes; no range/equity/EV computation.

## Remote / worktree confirmation

- `main` pushed to `origin`; `local main == origin/main` (see run output).
- Feature branch `feature/v8.21-range-reasoning-foundation` remains available at `330ff77`.
- `v8.20.0` unchanged; safety ref `v8.21-range-reasoning-base` intact; no v8.21 release tag.
- Worktrees clean (the feature worktree's `v821_range/merge_logs` scratch was moved aside before the merge).

## Next workstream

`main` is ready for the next workstream. The natural next step is commissioning the canonical opponent-range /
fold-equity owner (debt **D1**) to unblock the strategic layer — coordinated with the Sizing & Lines reference
bands (debt **D3**) under one owner decision. No new Range Reasoning feature work is pending in this branch.
