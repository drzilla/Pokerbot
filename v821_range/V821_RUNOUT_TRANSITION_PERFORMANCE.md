# V821_RUNOUT_TRANSITION_PERFORMANCE

Before/after measurement on a real session (`_session_20260527`, 1,220 hands, lazy hands ON = production
default). BEFORE = the no-wiring HEAD of `_hand_grid.py` + `sections_xiv.py`; AFTER = the same with the
Runout Transition wiring.

| Metric | BEFORE | AFTER | Δ |
|---|---|---|---|
| Report HTML size (primary) | 3,850 KB | 3,858 KB | **+8 KB (+0.2%)** |
| Report generation runtime | full pipeline (parse+analyze+render); render 13.7 s | comparable | render-time addition **≈ 0.09 s** (below run-to-run noise) |
| Added render work (the wiring) | — | `transitions_for_hand(h)` per appendix hand | **0.089 s over 1,220 hands (0.073 ms/hand), 177 records** |
| Analyst packet — events / input manifest | 12 events | 12 events | **identical** (byte-for-byte same manifest) |
| Analyst decisions added | — | — | **0** |
| Analyst schema change | — | — | **none** |
| LLM involvement in the transition | — | — | **none** (fully programmatic) |
| Renderer-created strategic calculation | — | — | **none** (the note only formats canonical facts) |

## How measured

- **Size / runtime:** generated the report with the wiring reverted to HEAD (`Pokerbot_..._V5`, 3,850 KB) and
  with the wiring (`Pokerbot_..._V2`, 3,858 KB), both lazy-on. The +8 KB is the 109 transition notes inside the
  `deflate-raw+base64` `PB_PAYLOADS.lazyHands` payload (≈44 KB uncompressed, ≈0.4% of the payload).
- **Added render cost:** timed `transitions_for_hand` over all 1,220 hands → 0.089 s; the appendix calls it at
  most once per rendered hand, so the live cost is ≤ that. Deterministic, single pass, no I/O.
- **Packet:** the input manifests of the BEFORE and AFTER runs are identical (same 12 events); `gem_analyst_
  packet.py` contains **0** references to `gem_runout_transition` — the wiring lives entirely in the render
  path, so the packet (and its required/optional analyst queues) is unchanged.

## Acceptance

- Zero added analyst decisions ✓
- No analyst schema change ✓
- No LLM involvement in generating the transition ✓
- Bounded deterministic runtime (+~0.09 s render) and report-size (+0.2%) increase ✓
- No renderer-created strategic calculations ✓
