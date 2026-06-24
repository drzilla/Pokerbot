# V03_RAMP_UP_BASELINE

Bet-Sizing / Line-Pattern pilot — Pokerbot v8.21. Established 2026-06-23.

## Development baseline

| Item | Value |
|---|---|
| Worktree | `C:\Users\ron\OneDrive\Desktop\Pokerbot_v821_sizing_line` (local, off the OneDrive-synced project root) |
| Branch | `feature/v8.21-sizing-line-pilot` |
| Starting HEAD | `f11a9caea6652132aacf92bad77ab0458b82d41d` (clean working tree at start) |
| `git describe` | `v8.19.0-29-gf11a9ca` |
| Accepted RC build identity | `GEM-v8.20.0-rc-f11a9caea665` |
| RC runtime ZIP SHA-256 | `591f611cbd65b4c055982e6f8088b7547af348ce623cc170577567ff4f6ec0e2` |
| Release tag status | **v8.20.0 final tag NOT present** — branched from the accepted RC commit `f11a9caea665`; promotion/tagging is **pending** (recorded, not performed here). |
| Source of charter/refs | `POKERBOT_V03_RAMP_UP_AND_EXECUTE_PACK.zip` (extracted once to `_v03_pack/`). The two charter docs (`V820_RELEASE_BASELINE_LOCKED.md`, `BET_SIZING_LINE_PATTERN_PRODUCT_CHARTER.md`) live in the pack, not the repo. |

Required source files present: `gem_analyzer.py` (621 KB), `gem_analyst_packet.py` (38 KB), `gem_sizing_detector.py` (6.2 KB). The long `feature/v8.20-wave1a1-trust-efficiency` branch was **not** continued from.

## Test / verifier baseline (pre-change, clean tree)

The repo has **no pytest/master runner**; each `test_*.py` is a standalone PASS/FAIL program (the "1999/1999" figure is a manually-tracked aggregate). Data-independent suites on the clean tree:

| Suite | Result |
|---|---|
| `test_metrics.py` | 533 passed, 0 failed |
| `test_textures.py` | 135 passed, 0 failed |
| `test_lint.py` | 48 passed, 0 failed |
| `test_gtow.py` | 58 tests, OK |
| `test_detectors.py` | **88 passed, 5 failed (PRE-EXISTING on the clean baseline)** |
| `verify_release.py` | `69/69 files OK, 664/664 canaries, 12/12 anti-canaries` (PASS) |

The 5 `test_detectors` failures (e.g. `TM91000012` re-jam CVJ control) are pre-existing on `f11a9caea665` and are **unrelated** to this pilot; they are fixture/data-dependent. The pilot must not increase that count (it does not — see the package report).

## Key data-availability finding (premise correction)

The V03 charter names the **844-hand June-16 benchmark** as the measurement corpus. During ramp-up I confirmed the **raw `GG20260616-*.txt` hand histories are absent from disk** (cleaned from the temp input dir); only processed/rendered June-16 artifacts survive, and the rendered report embeds hands lazily (no recoverable action ledgers). A full analyzer pass on June-16 is therefore **not reproducible locally**, and the user instruction *"do not search other folders"* rules out substituting an unrelated session from Downloads.

Consequence (decided, not deferred): the **detector is still fully implementable from canonical inputs** (no product rejection), and is implemented + tested + integrated this session. The **measurement** runs on the only in-worktree real-structure corpus — `test_hands.txt` + `test_hands_detectors.txt` (58 hands) — which is sufficient to prove the pipeline, severity classification, fail-closed behaviour, packet integration, and no-calc contract, but is **not** a production population for a per-100-hands rate. The exact missing dependency and the one-command path to a production measurement are recorded in `DEFERRED_FINDINGS.md`.

## Canonical capabilities reconstructed for this epic

- **Decision snapshot owner** — `gem_decision_snapshot.build_decision_snapshot(hand, action_index)` + `build_action_sizing_contract(...)`: street-exact board, pot/contestable-pot, hero stack-before, canonical effective decision depth, active players, price status, required equity, SPR, `amount_added_bb`, `live_betting_total_to_bb`, `raise_increment_bb`, `became_all_in`. Fail-closed when `no_hero_decision` or any core operand is `None`.
- **Atomic analyst record** — `gem_analyst_packet.atomic_snapshot(...)` consumes those two owners only; no parallel calc; truncates the action line at Hero's action; no result/showdown/net leakage.
- **Sizing price/contract** — chosen flop c-bet % of pot is carried canonically on `hand['hero_bets']` (`[street, sizing_pct, label, IP/OOP]`), the same field `gem_textures.aggregate_compliance` consumes.
- **Board texture / archetype / GTO band** — `gem_textures.classify_archetype` (16 archetypes, all `confidence: complete`), `get_gto_target(archetype, side, depth)` → `sizings_pct` band, `sizing_within_target(actual, targets, ±10pp)`. Source: `gto_texture_archetypes.json` (Dave coaching sessions 2026-05-04…05-13).
- **Discovery / packet pipeline** — `gem_discovery_context.run_value(hands, prior)` emits rule/chart-backed per-hand candidates → `gem_analyst_packet.build_packet` seals required/optional + keyed `EVIDENCE` + `validate_analyst_output` (one-pass, no-calc, fail-closed).
- **MDA / live-population / GTO-texture evidence** — `MDA_v7_5_Reference.txt`, `Live_Poker_Population_Reference.txt`, `GTO_Texture_Archetypes.txt` (evidence tiers 3–4 in the charter hierarchy; the pilot uses tier-1 chart evidence only).
- **Existing sizing detector** — `gem_sizing_detector.build_sizing_leak_signals` (AGGREGATE leak over `stats['texture_gto_findings']`, not per-hand). The pilot is its **per-decision complement**, reusing the same canonical primitives (see the capability matrix).

**Verdict — ramp-up baseline reliable: PASS** (with the documented June-16 raw-input gap).
