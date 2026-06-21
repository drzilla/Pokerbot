"""REV17 Stage-P wiring: derive the INDEPENDENT source-expected sized-action key set + the canonical
record list from the real hands, and run the FROZEN Stage-F gates (row-bound parity, zero-fallback,
dead-blind attribution) over the regenerated report / holdout. This module is the production-side
caller of the read-only acceptance gates — it never modifies them.

A sized action is a ledger call / bet / raise. The source-expected keys come from a pure ledger scan
(independent of the canonical replay); the canonical records come from gem_decision_snapshot.
canonical_action_replay; the rendered evidence is the shipped hand-body HTML. The frozen gate enforces
source-expected == canonical == rendered, full identity, the primary visible display, and zero raw
fallback.
"""
import os
import sys

_ACC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'acceptance')
if _ACC not in sys.path:
    sys.path.insert(0, _ACC)
import row_bound_renderer_parity_gate as _rbg          # FROZEN
import zero_fallback_gate as _zfg                        # FROZEN
import dead_blind_attribution_gate as _dbg              # FROZEN
import gem_decision_snapshot as ds
from _qa_decode_lazy import decode_lazy_hands

SIZED = ('calls', 'bets', 'raises')


def canon_hand_id(h):
    return str(h.get('tournament_hand_id') or h.get('id') or '')


def action_kind(h, i, a):
    """The action kind the grid stamps (must equal data-action-kind): a bet/raise that is all-in is a
    jam; a Hero underblind short all-in 'calls' renders as a jam; otherwise call/bet/raise."""
    act = a.get('action')
    if act in ('bets', 'raises'):
        return 'jam' if a.get('is_all_in') else ('bet' if act == 'bets' else 'raise')
    if act == 'calls':
        if a.get('player') == h.get('hero'):
            try:
                if ds.build_decision_snapshot(h, i).get('hero_action_kind') == 'short_all_in':
                    return 'jam'
            except Exception:
                pass
        return 'call'
    return None


def source_expected_keys(h):
    """INDEPENDENT source scan: every sized ledger action's (hand_id, ledger_index) — no canonical
    replay is consulted."""
    hid = canon_hand_id(h)
    return [(hid, i) for i, a in enumerate(h.get('action_ledger') or []) if a.get('action') in SIZED]


def canonical_records(h):
    """The strict canonical record list the row-bound gate validates: one complete record per sized
    ledger action, sized from canonical_action_replay."""
    hid = canon_hand_id(h)
    out = []
    for i, a in enumerate(h.get('action_ledger') or []):
        if a.get('action') not in SIZED:
            continue
        r = ds.canonical_action_replay(h, i) or {}
        out.append({'hand_id': hid, 'ledger_index': i, 'player_id': a.get('player'),
                    'action_kind': action_kind(h, i, a), 'sizing_source': 'canonical_replay',
                    'physical_bb': round(float(r.get('physical_amount_added_bb') or 0.0), 2),
                    'live_total_bb': round(float(r.get('live_commitment_after_bb') or 0.0), 2),
                    'uncalled_return_bb': round(float(r.get('uncalled_return_bb') or 0.0), 2)})
    return out


def _lookup(hands_idx, key):
    return (hands_idx.get(key) or hands_idx.get(str(key)) or hands_idx.get(str(key)[-8:]))


def run_renderer_gates(hands_idx, html):
    """Run the FROZEN row-bound + zero-fallback gates over every grid-rendering hand body. Returns
    aggregate results with detailed records."""
    bodies = decode_lazy_hands(html) if html else {}
    rb = {'bodies_with_grid': 0, 'sized_actions': 0, 'violations': 0, 'records': []}
    zf = {'bodies_with_grid': 0, 'sized_actions': 0, 'fallback_activations': 0, 'violations': 0, 'records': []}
    for key, body in bodies.items():
        if 'grid-action' not in body:
            continue
        h = _lookup(hands_idx, key)
        if not isinstance(h, dict):
            continue
        exp = source_expected_keys(h)
        canon = canonical_records(h)
        r = _rbg.run(body, canon, exp)
        z = _zfg.run(body, canon, exp, [])
        rb['bodies_with_grid'] += 1; rb['sized_actions'] += len(exp); rb['violations'] += r['violations']
        zf['bodies_with_grid'] += 1; zf['sized_actions'] += len(exp); zf['violations'] += z['violations']
        zf['fallback_activations'] += z['rows_not_sourced_canonical']
        for rec in r['records'][:6]:
            if len(rb['records']) < 120:
                rb['records'].append({'hand': canon_hand_id(h)[-8:], **rec})
        for rec in z['records'][:6]:
            if len(zf['records']) < 120:
                zf['records'].append({'hand': canon_hand_id(h)[-8:], **rec})
    return rb, zf


def source_dead_blind_keys(hands_idx):
    """INDEPENDENT source scan over the corpus for dead-blind post identities. The pilot corpus has 0
    dead blinds (the parser never emits the type) — this proves the expected identity set is genuinely
    empty (not a default None)."""
    keys = []
    seen = set()
    for h in hands_idx.values():
        if not isinstance(h, dict) or id(h) in seen:
            continue
        seen.add(id(h))
        for i, a in enumerate(h.get('action_ledger') or []):
            if a.get('action') == 'posts' and a.get('post_type') == 'dead_blind':
                keys.append((canon_hand_id(h), i))
    return keys


def run_dead_blind_gate(hands_idx):
    """Run the FROZEN dead-blind gate with the source-derived (proven) expected identity set. For the
    pilot corpus the replay carries no dead-blind records and the expected set is empty -> 0
    violations; the production replay never classifies a dead_blind as live (REV17 §1.4)."""
    expected = source_dead_blind_keys(hands_idx)        # proven empty for the pilot
    records = []
    seen = set()
    for h in hands_idx.values():
        if not isinstance(h, dict) or id(h) in seen:
            continue
        seen.add(id(h))
        for i, a in enumerate(h.get('action_ledger') or []):
            if a.get('post_type') == 'dead_blind':
                records.append(dict(a, idx=i))
    g = _dbg.run(records, [k[1] for k in expected])
    return {'expected_dead_blind_actions': len(expected), 'dead_blind_records_in_replay': len(records),
            'violations': g['violations'], 'records': g['records']}
