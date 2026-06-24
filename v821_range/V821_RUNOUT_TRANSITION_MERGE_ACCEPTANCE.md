# V821_RUNOUT_TRANSITION_MERGE_ACCEPTANCE

The descriptive Runout Transition capability is integrated into `main` via an auditable non-fast-forward merge.

## Identity

| Item | Value |
|---|---|
| Feature branch | `feature/v8.21-range-reasoning-foundation` |
| Feature tip (certified) | `330ff778703fb2dbea45248fd06daba9476fb165` |
| `main` before merge | `93637eb3285bcc9fa4aa1e86aab8a2b4e6788912` |
| Merge commit (`--no-ff`, no squash) | `d3aa50786d7a6ef9e1df06d730c60fe972c7b571` (parents `93637eb` + `330ff77`) |
| `v8.20.0` (unchanged) | `d72ed955a868457f84ea917924aa55db17efecad` |
| Safety ref (retained) | `v8.21-range-reasoning-base` = `93637eb` |
| Release tag created | **none** |

## Capability merged

On eligible turn/river decisions the report explains what the new card objectively changed, what remains true,
and what to reassess — inside the existing hand-detail note surface. Accepted boundaries, all honoured:
deterministic / result-independent · **≤ 1 transition note per turn/river street** · live in the existing
report-note system · **no analyst-LLM workload** · **0 analyst-packet decisions** · no opponent-range / equity /
EV / fold-equity computation · no continue/resize/pivot/abandon recommendation (strategic action stays
**Insufficient evidence**, debt **D1**) · unresolved/all-in render nothing.

## Pre-merge gates (feature `330ff77`)

`test_runout_transition.py` **78/78** · `test_runout_wiring.py` **34/34** · `_test_scratch.py` **2024/2024** ·
`verify_release.py --project-dir <feature worktree>` **[PASS] 69/69** (664/664 canaries, 12/12 anti-canaries) ·
import smoke OK · seven-fixture Results **PASS** · **0** invalid flop/turn `plays the board` wording in the
corpus · **0** Runout Transition decisions in the analyst packet · analyst schema unchanged · no equity/EV path.

## Post-merge gates (`main`, merge `d3aa5078`)

`test_runout_transition.py` **78/78** · `test_runout_wiring.py` **34/34** · `_test_scratch.py` **2024/2024** ·
`verify_release.py --project-dir <main worktree>` **[PASS] 69/69** · import smoke OK · seven-fixture **PASS** ·
**one full report smoke from `main`** (`AUTO_ONLY` V9, packet runtime `GEM-v8.20.0-d3aa50786d7a`): **104 hands**
carry a transition note, **0** within-hand duplicate notes, **0** invalid board-play phrases; existing
commentary, Results and navigation intact; analyst packet `required=34 optional=8`, `zero_calc=True`, **0**
transition decisions.

## Deferred scope (unchanged)

The strategic recommendation layer (continue/resize/slow/pivot/abandon) remains **blocked** by the missing
canonical **opponent-range / fold-equity owner** (debt **D1**); it renders *Insufficient evidence*. No
opponent-range or fold-equity work was started; Sizing & Lines untouched; no release built; Claude Chat not
updated; no v8.21 release tag.

## Remote / worktree confirmation

See `V821_RANGE_REASONING_MAIN_INTEGRATION_REPORT.md` for the pushed `main` SHA, `local == origin/main`, the
retained feature branch at `330ff77`, and clean-worktree confirmation.
