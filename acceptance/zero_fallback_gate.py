"""FROZEN Stage-F gate (REV17 §3.2; F1 + G1 + H1/H2) — ZERO raw-sizing fallback, source-bound,
coverage-bound, over the STRICT canonical truth set and the independent source-expected key set.

  * `expected_sized_action_keys` (independent, source-derived) is MANDATORY — None FAILS.
  * `canonical_records` is validated strictly (row_bound_renderer_parity_gate.validate_canonical);
    a malformed/coerced canonical set FAILS.
  * `rendered` must be the shipped HTML string (a synthetic pre-parsed list is rejected).
  * every source-expected (hand_id, ledger_index) must have EXACTLY ONE rendered element whose
    data-sizing-source == "canonical_replay"; a missing / non-canonical-sourced element FAILS (a
    dropped or unmarked sized row does not escape).
  * any rendered marked element with data-sizing-source != "canonical_replay" FAILS (source-bound,
    never value-bound). The persisted fallback-activation log must be EMPTY.
"""
try:
    from . import row_bound_renderer_parity_gate as _rb
except Exception:
    import row_bound_renderer_parity_gate as _rb

REQUIRED_SOURCE = 'canonical_replay'


def run(rendered, canonical_records, expected_sized_action_keys, fallback_log=None):
    fallback_log = fallback_log or []
    out = {'expected_source_keys': None, 'marked_rows': 0, 'rows_not_sourced_canonical': 0,
           'expected_without_canonical_source': 0, 'canonical_validation_errors': 0,
           'fallback_log_activations': len(fallback_log), 'violations': 0, 'records': []}

    def viol(rec):
        out['violations'] += 1
        if len(out['records']) < 200:
            out['records'].append(rec)

    if expected_sized_action_keys is None:
        viol({'why': 'expected_source_inventory_omitted'}); return out
    try:
        exp_src = set((str(h), int(i)) for (h, i) in expected_sized_action_keys)
    except Exception:
        viol({'why': 'expected_source_inventory_malformed'}); return out
    out['expected_source_keys'] = len(exp_src)

    if not isinstance(rendered, str):
        viol({'why': 'synthetic_rendered_evidence_rejected'}); return out

    by_comp, errors = _rb.validate_canonical(canonical_records)
    out['canonical_validation_errors'] = len(errors)
    for e in errors:
        viol({'why': 'invalid_canonical_truth_record', **e})
    if errors:
        return out
    # the canonical set must equal the source-expected set (no silent omission)
    for comp in sorted(exp_src ^ set(by_comp.keys()), key=lambda c: (c[0], c[1])):
        viol({'why': 'source_expected_ne_canonical', 'hand_id': comp[0], 'ledger_index': comp[1]})

    try:
        rows = _rb.parse_marked_rows(rendered)
    except Exception as e:
        viol({'why': 'dom_parse_failure', 'detail': str(e)[:80]}); return out
    out['marked_rows'] = len(rows)
    by_render = {}
    for r in rows:
        if r.get('ledger_index') is not None and isinstance(r.get('hand_id'), str) and r['hand_id']:
            by_render.setdefault((r['hand_id'], r['ledger_index']), []).append(r)

    for comp in sorted(exp_src, key=lambda c: (c[0], c[1])):
        sourced = [e for e in by_render.get(comp, []) if e.get('sizing_source') == REQUIRED_SOURCE]
        if len(sourced) != 1:
            out['expected_without_canonical_source'] += 1
            viol({'why': 'expected_sized_action_without_a_single_canonical_sourced_element',
                  'hand_id': comp[0], 'ledger_index': comp[1], 'canonical_sourced_count': len(sourced),
                  'total_rendered': len(by_render.get(comp, []))})
    for r in rows:
        if r.get('sizing_source') != REQUIRED_SOURCE:
            out['rows_not_sourced_canonical'] += 1
            viol({'why': 'rendered_row_not_sourced_from_canonical_replay',
                  'hand_id': r.get('hand_id'), 'ledger_index': r.get('ledger_index'), 'sizing_source': r.get('sizing_source')})
    for a in fallback_log:
        viol({'why': 'raw_sizing_fallback_activated', 'activation': a})
    return out
