"""gem_stage_meter -- a tiny, importable per-process counter that records which HEAVY pipeline stages
actually ran. The canonical `--quick` cache-only render must perform NONE of these; this meter lets the
quick path PROVE (and fail closed on) zero forbidden work instead of merely asserting it structurally.

Each full-pipeline stage entry calls tick(<stage>). `--quick` exits before any of them run, so a clean
quick render leaves every forbidden counter at 0. The telemetry is written next to the analyst packet.
"""

_COUNTS = {}

# the stages a cache-only quick render must never perform (owner Gate 2.2). 'analyze' subsumes evaluator
# calls + the analyst review pass; 'reference' is external chart/range loading.
FORBIDDEN_IN_QUICK = ('parse', 'reference', 'analyze', 'detector', 'worklist', 'packet')


def tick(stage):
    """Record that a heavy stage ran (called once at each full-pipeline stage entry)."""
    _COUNTS[stage] = _COUNTS.get(stage, 0) + 1


def snapshot():
    return dict(_COUNTS)


def reset():
    _COUNTS.clear()


def forbidden_quick_counts():
    return {s: _COUNTS.get(s, 0) for s in FORBIDDEN_IN_QUICK}


def quick_is_clean():
    """True iff no forbidden stage ran -- the invariant a cache-only quick render must satisfy."""
    return all(v == 0 for v in forbidden_quick_counts().values())
