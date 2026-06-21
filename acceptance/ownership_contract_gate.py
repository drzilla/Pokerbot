"""FROZEN Stage-F gate (REV17 §3.3) — MANDATORY tracked ownership contract.

The REV16 permanent test accepted `_real_status in ('ok', 'unreadable')`, so a missing real artifact
passed (the contract was not a required tracked source artifact). This gate makes the artifact
mandatory at a frozen, tracked, shipped, release-verified location:

    acceptance/production_calculation_ownership.json

Required behaviour (no tolerance for absence):
    missing               -> FAIL
    unreadable            -> FAIL
    required fact absent  -> FAIL
    owner count != 1      -> FAIL   (stack_before, all_in_state each EXACTLY one active owner)
    remaining active producer != []  -> FAIL

REV17 must add this path to the clean source bundle and to verify_release so the clean-room run
fails if it is missing.
"""
import io
import json
import os

FROZEN_PATH = 'acceptance/production_calculation_ownership.json'
REQUIRED_FACTS = ('physical_amount_added', 'live_commitment', 'total_contribution', 'stack_before',
                  'stack_after', 'uncalled_return', 'all_in_state', 'forced_post_type',
                  'callable_amount')
SINGLE_OWNER_FACTS = ('stack_before', 'all_in_state')


def run(path):
    """Returns {'status', 'ok'(bool), 'detail'}. status 'ok' only if every requirement holds."""
    if not path or not os.path.exists(path):
        return {'status': 'missing', 'ok': False, 'detail': 'ownership artifact absent at ' + str(path)}
    try:
        d = json.load(io.open(path, encoding='utf-8'))
    except Exception as e:
        return {'status': 'unreadable', 'ok': False, 'detail': 'json error: ' + str(e)[:80]}
    acc = d.get('acceptance')
    if not isinstance(acc, dict):
        return {'status': 'field_absent:acceptance', 'ok': False, 'detail': 'missing acceptance block'}
    if acc.get('stack_before_active_production_owners') != 1:
        return {'status': 'owner_count_ne_one:stack_before', 'ok': False, 'detail': str(acc.get('stack_before_active_production_owners'))}
    if acc.get('all_in_state_active_production_owners') != 1:
        return {'status': 'owner_count_ne_one:all_in_state', 'ok': False, 'detail': str(acc.get('all_in_state_active_production_owners'))}
    for f in REQUIRED_FACTS:
        rec = d.get(f)
        if not isinstance(rec, dict):
            return {'status': 'field_absent:' + f, 'ok': False, 'detail': 'missing fact record'}
        if 'remaining_active_producers' not in rec:
            return {'status': 'field_absent:' + f + '.remaining_active_producers', 'ok': False, 'detail': ''}
        if rec['remaining_active_producers']:
            return {'status': 'remaining_active_producer:' + f, 'ok': False,
                    'detail': str(rec['remaining_active_producers'])}
        if not rec.get('canonical_owner'):
            return {'status': 'field_absent:' + f + '.canonical_owner', 'ok': False, 'detail': ''}
    return {'status': 'ok', 'ok': True, 'detail': 'all owners single, 0 remaining producers'}
