# V821_SIZING_LINES_CONFLICT_RESOLUTION

v8.20.0 is **authoritative** wherever the parked work conflicts. Each conflict resolved explicitly with the
reason the chosen side wins.

## The only true conflict candidate: `gem_analyzer.py`

It is the only file changed by **both** the release (`f11a9caea665..main`) and the parked branch
(`f11a9caea665..78780bb`).

**Resolution: clean 3-way auto-merge, 0 conflict markers.** The two change-sets are in disjoint regions:

- **v8.20 owns** the `if __name__ == '__main__':` block (~L9005–L11067): malformed-JSON `--quick` guards,
  one-pass analyst consumption (`analyst_commentary_from_output`), ungraded/`unresolved`-debt split, and the
  full `build_identity` in the run manifest. → **v8.20 wins this region** because it is the released analyst /
  coverage / packaging authority.
- **Parked owns** the GTO texture block (`_gto_sizing_pct`, ~L2622–L2631): the safety gate
  `if not _sizedet.cbet_chart_applies(h): return None` + `import gem_sizing_detector as _sizedet`. v8.20 left
  this block byte-identical to the merge-base, so the parked hunk applies without contest. → **parked wins this
  region** because v8.20 never touched it and the gate is the sole new v8.21 deliverable.

**Post-merge verification (empirical):**
```
gem_analyzer.py:2622  import gem_sizing_detector as _sizedet
gem_analyzer.py:2623  def _gto_sizing_pct(h):
gem_analyzer.py:2629      if not _sizedet.cbet_chart_applies(h):  return None
grep -c analyst_commentary_from_output|_ungraded|build_identity  → 13  (v8.20 __main__ changes intact)
```
Both change-sets coexist; the file compiles; the gate's call target `cbet_chart_applies` resolves at
`gem_sizing_detector.py:137`.

## Per-file merge outcome (full)

| File | Winner | Reason / verified risk |
|---|---|---|
| `gem_analyzer.py` | **both (disjoint auto-merge)** | v8.20 `__main__` + parked GTO-block gate; both present; compiles; chain intact. |
| `gem_sizing_detector.py` | **parked** | Not in the release diff — v8.20 made zero edits. `cbet_chart_applies` + `_flop_cbet_is_all_in` + `build_sizing_leak_signals` carry verbatim. |
| `gem_discovery_context.py` | **v8.20** | Parked reverted byte-identical to `f11a9ca`; v8.20 changed it (3-population routing context). v8.20's version taken; no parked sizing artifact remains; no candidate flows into the packet. |
| `gem_analyst_packet.py` | **v8.20** | Parked byte-identical to `f11a9ca`; v8.20 substantially changed it (`unresolved` population, `ONEPASS_TO_REPORT_VERDICT`, `analyst_commentary_from_output`, de-hardcoded reconciliation). v8.20 authoritative; the aggregate sizing path emits 0 packet candidates so no new schema obligation. |
| `gem_report_draft/draft.py` | **v8.20** | Parked made no draft.py edit. v8.20 added `<<ANCHOR:sec-SL>>` (L716) — **`sec-SL` fix**. `_emit_sizing_lines` still renders the gated "## Sizing & Line Patterns" from `rd['sizing_leak_signals']`. |
| `gem_coverage_builder.py` | **either (unchanged both sides)** | Sizing wiring at L2205-2206 intact; not in either diff. |
| all other 17 release files | **v8.20** | Parked didn't touch them (lean runtime, build identity, report_data, sections, tldr, verify_release, QA harnesses). v8.20 authoritative. |

## End-to-end production chain (verified intact post-merge)

```
gem_parser hero_bets → gem_analyzer._gto_sizing_pct [GATED by cbet_chart_applies]
  → gem_textures.aggregate_compliance → gem_sizing_detector.build_sizing_leak_signals
  → gem_coverage_builder:2205 report_data['sizing_leak_signals']
  → gem_report_draft._emit_sizing_lines  "## Sizing & Line Patterns"  (anchored <<ANCHOR:sec-SL>>)
```

## Stale assumptions the parked work made (v8.20 changed → status)

| # | Parked assumption | v8.20 reality | Action |
|---|---|---|---|
| 1 | `## Sizing & Line Patterns` heading had no anchor | v8.20 emits `<<ANCHOR:sec-SL>>` above it (`draft.py:716`) | None — parked made no draft edit; the test asserts the heading *string* (unchanged). Future SSL re-emits must keep the anchor first. |
| 2 | Packet is 2-population (`required`/`optional`) | v8.20 adds `unresolved`; a no-node candidate routes to debt | Moot — per-hand family removed; aggregate flows 0 candidates. Constraint logged for any per-hand revival. |
| 3 | `artifact_cache_identity` includes `final_truth` | v8.20 excludes it (`--quick` idempotency) | None for the gate; logged for future packet-feeding sizing code. |
| 4 | `build_coverage_reconciliation` keyed on `kqs_*` / fixture `TM6084610450` | v8.20 de-hardcoded → `rule_backed_sb_flat_demoted` | None — no surviving test asserts old keys. |
| 5 | Completeness signatures (`canonical_required_review_ids`, `compute_report_completeness`) | gained `hands_by_id` + `ungraded`/`ungraded_debt` | None for the gate; logged for future sizing code reading completeness. |
| 6 | One-pass analyst not live on `--quick` | v8.20 integrates validated verdicts on `--quick` | Moot — aggregate leak is a `requires_analyst_review` note, not a keyed verdict. Constraint for per-hand revival. |
| 7 | phevaluator "may be absent / degrade loud" | v8.20 vendors it → exact NLH equity guaranteed (Omaha `.dat` excluded) | None — gate uses decision-time inputs only, no equity branch. |
| 8 | `AGGREGATE_CLOSEOUT_PACKAGE.md` "+235L footprint" | true net is **+41L** (`gem_analyzer +8` / `gem_sizing_detector +33`) | **ADAPT_TO_V820** — reconcile the doc banner. |

No stale assumption forced a code change to the surviving gate; all are either moot (per-hand family removed)
or logged constraints for any future sizing work.
