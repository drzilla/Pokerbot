"""Stage-F self-check (rev 4): prove each FROZEN gate catches its seed (R1, R1B-R1S, R2, R3, R4,
R4B-R4J) for the stated reason, passes correct controls, and that the universal mutation-audit probes
(missing / empty / extra / duplicate / malformed / wrong-type / non-finite / wrong-identity /
right-value-wrong-identity / right-value-hidden / omitted-expectation / canonical-omitted /
observed-omitted / synthetic-evidence) are all caught. Runs NO production code."""
import io, json, math, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import row_bound_renderer_parity_gate as rb
import zero_fallback_gate as zf
import ownership_contract_gate as oc
import dead_blind_attribution_gate as db


def _denan(o):
    if isinstance(o, str):
        return float('nan') if o == '__nan__' else o
    if isinstance(o, list):
        return [_denan(x) for x in o]
    if isinstance(o, dict):
        return {k: _denan(v) for k, v in o.items()}
    return o


def _seed(n):
    return _denan(json.load(io.open(os.path.join(HERE, n), encoding='utf-8')))


def _keys(seed):
    return [(h, i) for h, i in seed['expected_sized_action_keys']]


results = []
def rec(name, ok, detail=''):
    results.append(ok)
    print(('  OK  ' if ok else '  XX  ') + name + ('' if ok else '  <- ' + str(detail)[:240]))


def _field(records, f):
    return any(f in (r.get('mismatch_fields') or []) for r in records)


def _why(records, *ws):
    return any(r.get('why') in ws for r in records)


def _rb_fails(name, seedfile, check_records):
    s = _seed(seedfile)
    rendered = s['rendered_html'] if not s.get('rendered_is_synthetic_list') else [{'ledger_index': 20}]
    r = rb.run(rendered, s['canonical_records'], _keys(s) if 'expected_sized_action_keys' in s else None)
    rec(name, r['violations'] >= 1 and check_records(r['records']), r['records'])
    return r


# ── row-bound seeds ──
_rb_fails('R1 cross-row collision fails the wrong Hero row (20)', 'seed_cross_row_collision.json',
          lambda recs: any(x.get('ledger_index') == 20 for x in recs) and not any(x.get('ledger_index') == 21 for x in recs))
_rb_fails('R1B omitted canonical action', 'seed_omitted_canonical_action.json', lambda recs: _why(recs, 'expected_action_not_rendered'))
_rb_fails('R1C wrong identity', 'seed_wrong_player_action_identity.json', lambda recs: _field(recs, 'player_id_ne_canonical') or _field(recs, 'action_kind_ne_canonical'))
_rb_fails('R1D missing attrs', 'seed_missing_required_attributes.json', lambda recs: _field(recs, 'missing_attr:data-live-total-bb'))
_rb_fails('R1E raise shows physical', 'seed_raise_displays_physical.json', lambda recs: _field(recs, 'primary_sizing_display_ne_action_required_field:live_total_bb'))
_rb_fails('R1F sparse canonical', 'seed_sparse_canonical_record.json', lambda recs: _why(recs, 'invalid_canonical_truth_record'))
r = _rb_fails('R1G composite identity flags only hand B', 'seed_shared_ledger_index_two_hands.json',
              lambda recs: any(x.get('hand_id') == 'TM6000000BBB' for x in recs) and not any(x.get('hand_id') == 'TM6000000AAA' for x in recs))
_rb_fails('R1H visible amount omitted', 'seed_visible_amount_omitted.json', lambda recs: _field(recs, 'primary_sizing_display_absent'))
_rb_fails('R1I missing explicit ledger_index', 'seed_canonical_missing_ledger_index.json', lambda recs: _why(recs, 'invalid_canonical_truth_record'))
_rb_fails('R1J fractional ledger_index', 'seed_canonical_fractional_ledger_index.json', lambda recs: _why(recs, 'invalid_canonical_truth_record'))
_rb_fails('R1K empty hand/player id', 'seed_canonical_empty_identity.json', lambda recs: _why(recs, 'invalid_canonical_truth_record'))
_rb_fails('R1L NaN canonical sizing', 'seed_canonical_nonfinite_numeric.json', lambda recs: _why(recs, 'invalid_canonical_truth_record'))
_rb_fails('R1M source-expected omitted from canonical', 'seed_source_expected_canonical_omitted.json', lambda recs: _why(recs, 'source_expected_action_missing_from_canonical'))
_rb_fails('R1N empty canonical+rendered with nonempty source', 'seed_all_empty_with_nonempty_source.json', lambda recs: _why(recs, 'source_expected_action_missing_from_canonical', 'expected_action_not_rendered'))
_rb_fails('R1O wrong visible + hidden correct', 'seed_visible_wrong_plus_hidden_correct.json', lambda recs: _field(recs, 'primary_sizing_display_ne_action_required_field:physical_bb'))
_rb_fails('R1P correct only in tooltip child', 'seed_correct_only_in_tooltip.json', lambda recs: _field(recs, 'primary_sizing_display_absent'))
_rb_fails('R1Q duplicate primary display', 'seed_duplicate_primary_display.json', lambda recs: _field(recs, 'duplicate_primary_sizing_display'))
_rb_fails('R1R multiple amounts wrong primary', 'seed_multiple_amounts_wrong_primary.json', lambda recs: _field(recs, 'primary_sizing_display_ne_action_required_field:physical_bb'))
_rb_fails('R1S synthetic rendered list rejected', 'seed_synthetic_rendered_list.json', lambda recs: _why(recs, 'synthetic_rendered_evidence_rejected'))

# row-bound CONTROL: a fully-correct render passes
GC = [{'hand_id': 'H', 'ledger_index': 20, 'player_id': 'Hero', 'action_kind': 'jam', 'sizing_source': 'canonical_replay', 'physical_bb': 18.1, 'live_total_bb': 18.1, 'uncalled_return_bb': 0.0}]
GH = '<div class="hand-body"><span class="grid-action act-jam" data-hand-id="H" data-ledger-index="20" data-player-id="Hero" data-action-kind="jam" data-sizing-source="canonical_replay" data-physical-bb="18.1" data-live-total-bb="18.1" data-uncalled-return-bb="0.0">Hero <span data-sizing-role="primary">18.1BB</span></span></div>'
rg = rb.run(GH, GC, [('H', 20)])
rec('row-bound CONTROL: a correct render PASSES (0 violations, rows_checked==1)', rg['violations'] == 0 and rg['rows_checked'] == 1, rg)
rec('row-bound CONTROL: integer-BB primary ("18BB" for 18.0) PASSES',
    rb.run(GH.replace('18.1', '18.0').replace('18.0BB', '18BB'), [dict(GC[0], physical_bb=18.0, live_total_bb=18.0)], [('H', 20)])['violations'] == 0)

# ── R2 zero-fallback ──
s = _seed('seed_equal_value_fallback.json')
rf = zf.run(s['rendered_html'], s['canonical_records'], _keys(s), s.get('fallback_log'))
rec('R2 zero-fallback FAILS the equal-value raw fallback', rf['violations'] >= 1 and rf['rows_not_sourced_canonical'] >= 1, rf)
rec('R2 control: canonical-sourced + empty log PASSES', zf.run(s['rendered_html'].replace('raw_fallback', 'canonical_replay'), s['canonical_records'], _keys(s), [])['violations'] == 0)

# ── R3 ownership ──
s = _seed('seed_missing_ownership.json')
rec('R3 ownership FAILS missing', oc.run(os.path.join(HERE, '__nope__.json'))['status'] == 'missing')
def _tmp(o):
    fd, p = tempfile.mkstemp(suffix='.json'); os.close(fd); io.open(p, 'w', encoding='utf-8').write(o if isinstance(o, str) else json.dumps(o)); return p
ps = [_tmp(s['also_failing_paths'][k]) for k in ('unreadable_inline', 'two_owners_inline', 'remaining_producer_inline')]
rec('R3 ownership FAILS unreadable / owner!=1 / remaining-producer', oc.run(ps[0])['status'] == 'unreadable' and oc.run(ps[1])['ok'] is False and oc.run(ps[2])['ok'] is False)
for p in ps:
    os.remove(p)
rec('R3 control: frozen ownership artifact PASSES', oc.run(os.path.join(HERE, 'production_calculation_ownership.json'))['ok'] is True)

# ── dead-blind seeds ──
def _db_fails(name, seedfile, check):
    s = _seed(seedfile)
    g = db.run(s['replay_records'], s['expected_dead_blind_keys'])
    rec(name, g['violations'] >= 1 and check(g), g)
_db_fails('R4 dead-blind live', 'seed_dead_blind_live.json', lambda g: _field(g['records'], 'live_commitment_changed'))
_db_fails('R4B dead-blind ignored', 'seed_dead_blind_ignored.json', lambda g: _field(g['records'], 'stack_not_reduced_by_physical_post') or _field(g['records'], 'contribution_not_conserved'))
_db_fails('R4C attribution fields omitted', 'seed_dead_blind_fields_omitted.json', lambda g: any(f.startswith('missing_field:') for r0 in g['records'] for f in (r0.get('mismatch_fields') or [])))
_db_fails('R4D expected action removed (coverage)', 'seed_dead_blind_removed.json', lambda g: _why(g['records'], 'expected_dead_blind_identity_missing_from_replay'))
_db_fails('R4E live decrease', 'seed_dead_blind_live_decrease.json', lambda g: _field(g['records'], 'live_commitment_changed'))
_db_fails('R4F expected identity set omitted', 'seed_dead_blind_expected_omitted.json', lambda g: _why(g['records'], 'expected_dead_blind_identity_set_omitted'))
_db_fails('R4G non-finite numeric', 'seed_dead_blind_nonfinite.json', lambda g: _field(g['records'], 'not_finite:physical_bb'))
_db_fails('R4H wrong identity same count', 'seed_dead_blind_wrong_identity.json', lambda g: _why(g['records'], 'expected_dead_blind_identity_missing_from_replay', 'replay_dead_blind_identity_not_expected'))
_db_fails('R4I non-integer idx', 'seed_dead_blind_bad_idx.json', lambda g: _field(g['records'], 'idx_not_exact_int'))
_db_fails('R4J post_type=dead_blind wrong action', 'seed_dead_blind_wrong_action.json', lambda g: _field(g['records'], 'dead_blind_wrong_or_missing_action:raises'))
# dead-blind CONTROL: a correct attributable dead blind with a matching identity set passes
rec('dead-blind CONTROL: a correct dead_blind (identity match) PASSES',
    db.run([{'idx': 1, 'player': 'Hero', 'action': 'posts', 'post_type': 'dead_blind', 'semantic_status': 'explicit_unknown', 'physical_bb': 0.5, 'stack_before_bb': 30.0, 'stack_after_bb': 29.5, 'total_contribution_before_bb': 1.0, 'total_contribution_after_bb': 1.5, 'live_commitment_before_bb': 0.0, 'live_commitment_after_bb': 0.0}], [1])['violations'] == 0)
rec('dead-blind CONTROL: an empty replay with a PROVEN-empty expected set PASSES', db.run([], [])['violations'] == 0)

# ── universal mutation-audit probes ──
rec('MUT omitted expectation (row-bound expected=None) FAILS', rb.run(GH, GC, None)['violations'] >= 1)
rec('MUT canonical population omitted (canonical=[], expected nonempty) FAILS', rb.run(GH, [], [('H', 20)])['violations'] >= 1)
rec('MUT observed population omitted (rendered empty, expected nonempty) FAILS', rb.run('<div></div>', GC, [('H', 20)])['violations'] >= 1)
rec('MUT synthetic evidence (rendered list) FAILS', rb.run([{'x': 1}], GC, [('H', 20)])['violations'] >= 1)
rec('MUT both-empty (canonical=[], expected=[], rendered=empty) is consistent -> 0', rb.run('<div></div>', [], [])['violations'] == 0)
rec('MUT zero-fallback omitted expectation FAILS', zf.run(GH, GC, None, [])['violations'] >= 1)
rec('MUT dead-blind omitted expectation FAILS', db.run([], None)['violations'] >= 1)

p = sum(1 for x in results if x)
print('\nSTAGE-F SELF-CHECK (rev 4): %d/%d assertions pass' % (p, len(results)))
sys.exit(0 if p == len(results) else 1)
