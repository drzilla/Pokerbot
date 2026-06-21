"""FROZEN Stage-F gate (REV17 §3.4; F4 + G3 + H3) — dead_blind attribution, identity-coverage-based,
finite, non-filtering.

Recon (Stage F): the parser NEVER emits post_type `dead_blind` / `straddle`; the June-16 pilot corpus
has 0 occurrences. Production + the oracle classify `dead_blind` as a LIVE post (the B4 error).

Hardened contract (UNSUPPORTED but ATTRIBUTABLE):
  * MANDATORY IDENTITY COVERAGE. `expected_dead_blind_keys` (the stable idx identities the SOURCE
    action inventory says are dead blinds, derived independently of the replay output) is MANDATORY —
    None / omitted FAILS, even when the valid expected set is empty. The replay's dead-blind idx set
    must EQUAL the expected set (identity, not just count — a substituted record fails).
  * SCAN, DO NOT FILTER. Any record declaring post_type == "dead_blind" is checked; a record with the
    dead-blind post_type but a wrong/missing `action` FAILS as malformed (it is not filtered away).
  * COMPLETE + FINITE + EXACT IDENTITY. Each dead-blind record must carry idx (exact int, unique),
    post_type, semantic_status (in the valid set), physical_bb, stack_before_bb, stack_after_bb,
    total_contribution_before_bb, total_contribution_after_bb, live_commitment_before_bb,
    live_commitment_after_bb — all present and FINITE numbers.
  * ARITHMETIC (absolute equality) — stack_after == stack_before - physical; contribution_after ==
    contribution_before + physical; live_after == live_before (EQUALITY: a decrease fails too);
    physical > 0.

Because the pilot corpus has zero dead blinds, Stage P must ship the independent source-scan evidence
that the expected key set is genuinely empty; a default None or unproved empty list is insufficient.
"""
import math

EPS = 0.02
DEAD_POST_TYPES = ('dead_blind',)
VALID_STATUS = ('explicit_unknown', 'dead', 'unsupported')
REQUIRED_FIELDS = ('idx', 'post_type', 'semantic_status', 'physical_bb', 'stack_before_bb',
                   'stack_after_bb', 'total_contribution_before_bb', 'total_contribution_after_bb',
                   'live_commitment_before_bb', 'live_commitment_after_bb')
_NUMERIC = ('physical_bb', 'stack_before_bb', 'stack_after_bb', 'total_contribution_before_bb',
            'total_contribution_after_bb', 'live_commitment_before_bb', 'live_commitment_after_bb')


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _exact_idx(x):
    return isinstance(x, int) and not isinstance(x, bool)


def run(replay_records, expected_dead_blind_keys):
    out = {'expected_keys': None, 'found_keys': 0, 'violations': 0, 'records': []}

    def viol(rec):
        out['violations'] += 1
        if len(out['records']) < 200:
            out['records'].append(rec)

    if expected_dead_blind_keys is None:
        viol({'why': 'expected_dead_blind_identity_set_omitted'}); return out
    try:
        exp = set(expected_dead_blind_keys)
    except Exception:
        viol({'why': 'expected_dead_blind_identity_set_malformed'}); return out
    out['expected_keys'] = len(exp)

    # SCAN every record declaring the dead-blind post_type (do not filter on action)
    found = [r for r in (replay_records or []) if r.get('post_type') in DEAD_POST_TYPES]
    out['found_keys'] = len(found)
    seen_idx = set()
    found_idx = set()
    for r in found:
        fields = []
        idx = r.get('idx')
        if not _exact_idx(idx):
            fields.append('idx_not_exact_int')
        else:
            if idx in seen_idx:
                fields.append('duplicate_idx_identity')
            seen_idx.add(idx)
            found_idx.add(idx)
        if r.get('action') != 'posts':
            fields.append('dead_blind_wrong_or_missing_action:' + str(r.get('action')))
        for f in REQUIRED_FIELDS:
            if r.get(f) is None:
                fields.append('missing_field:' + f)
        for f in _NUMERIC:
            v = r.get(f)
            if v is not None and not _finite(v):
                fields.append('not_finite:' + f)
        status = r.get('semantic_status')
        if status is not None and status not in VALID_STATUS:
            fields.append('semantic_status_misclassified:' + str(status))
        phys, sb, sa = r.get('physical_bb'), r.get('stack_before_bb'), r.get('stack_after_bb')
        cb, ca = r.get('total_contribution_before_bb'), r.get('total_contribution_after_bb')
        lb, la = r.get('live_commitment_before_bb'), r.get('live_commitment_after_bb')
        if _finite(phys) and phys <= EPS:
            fields.append('physical_post_not_attributable')
        if all(_finite(x) for x in (phys, sb, sa)) and abs(sa - (sb - phys)) > EPS:
            fields.append('stack_not_reduced_by_physical_post')
        if all(_finite(x) for x in (phys, cb, ca)) and abs(ca - (cb + phys)) > EPS:
            fields.append('contribution_not_conserved')
        if all(_finite(x) for x in (lb, la)) and abs(la - lb) > EPS:
            fields.append('live_commitment_changed')
        if fields:
            viol({'idx': idx, 'semantic_status': status, 'mismatch_fields': fields})
    # IDENTITY coverage: the replay dead-blind idx set must equal the source-expected identity set
    for k in sorted(exp - found_idx, key=lambda x: str(x)):
        viol({'why': 'expected_dead_blind_identity_missing_from_replay', 'idx': k})
    for k in sorted(found_idx - exp, key=lambda x: str(x)):
        viol({'why': 'replay_dead_blind_identity_not_expected', 'idx': k})
    return out
