# DEFERRED_FINDINGS

Logged and left untouched per the scope lock. None blocks the pilot.

## D1 — 844-hand June-16 benchmark raw inputs are absent (data dependency, not a code defect)

- **What:** the `GG20260616-*.txt` raw hand histories (16 files, 844 hands / 12 tournaments) are not on
  disk; only processed/rendered June-16 artifacts survive, and the rendered report embeds hands lazily (no
  recoverable action ledgers). The analyzer's full pass + canonical input-hash binding require the raw files.
- **Effect:** the headline product-value rate (confirmed mistakes / 100 hands on the benchmark) could not be
  measured this session; the pilot was measured on the in-worktree fixture corpus instead.
- **Exact missing dependency:** the 16 raw `GG20260616-*.txt` inputs (hashes are listed in
  `Pokerbot_Knockman_20260616-17_AUTO_ONLY_V8_input_manifest.json`). Re-export from GG / restore from backup.
- **One-command production measurement once restored:**
  `PYTHONUTF8=1 python _v03_pilot_run.py <RESTORED_SESSION_DIR>` → regenerates every `v03_pilot/*.json` for
  the real population. (The harness already accepts a session directory and uses the canonical
  `gem_parser.parse_session`.)

## D2 — Second/third chart-backed sizing family blocked by chart coverage

- **What:** the only sizing chart in the runtime is **flop c-bet** (`gto_texture_archetypes.json`, sides
  `ip_cbet`/`oop_cbet`). There is no turn/river sizing band.
- **Effect:** charter families "missed/undersized **river** value" (sizing sub-case) and "turn barrel sizing"
  cannot be made chart-backed without inventing a reference (forbidden). Deferred until turn/river sizing
  charts exist (cf. the parked HF/SBD chart extraction work).

## D3 — All-in c-bet framing

- A gross over-size that is also all-in (`TM91000015`) is both a sizing error and a stack-off. The size
  finding is valid; a future enhancement could tag `became_all_in` candidates so the report frames them as
  over-commitment rather than pure sizing. Non-blocking.

## D4 — Pot-type scoping of the archetype band

- The archetype band is calibrated for single-raised-pot range c-bets; 3BP/4BP c-bets may legitimately
  differ. `hand['pot_type']` is available. A future refinement could scope the family to SRP or add 3BP
  bands. Non-blocking (current corpus had no 3BP false positive).

## D5 — Tiny-pot percentage sensitivity

- A small absolute bet into a small flop pot can inflate the % reading. The decision-time `pot_before_bb`
  is in every record for analyst sanity-checking; a `min_pot_before_bb` floor is a candidate guard if
  scaling shows noise. Non-blocking.

## Pre-existing items observed but NOT touched (out of scope)

- `test_detectors.py` carries **5 pre-existing failures** on the clean `f11a9caea665` baseline (e.g.
  `TM91000012` re-jam CVJ positive control). Fixture/data-dependent; unrelated to this pilot; left as-is.
- `verify_release.py` `VERSION` string is `v8.19.0` while the RC build identity is `v8.20.0-rc`; cosmetic,
  left as-is.
- Numerous version-specific `test_v8xx_*` / parity suites depend on a rendered report / live session and
  cannot reach green without session data; left as-is.
