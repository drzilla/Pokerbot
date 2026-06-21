"""FROZEN Stage-F gate (REV17 §3.1; F1/F2/F3 + G1/G2/G3 + H1/H2) — ROW-BOUND renderer parity.

Hardened so no malformed/synthetic input fails open:

  H1 STRICT, NON-COERCING CANONICAL. `canonical_records` is a LIST of complete records (a dict is
     rejected — no ledger_index inference from a key). Each record must EXPLICITLY carry hand_id
     (non-empty str), ledger_index (exact non-negative int — a float/str fails), player_id (non-empty
     str), action_kind (in the enum), sizing_source == "canonical_replay", physical_bb / live_total_bb
     / uncalled_return_bb (FINITE numbers). Duplicate composite identities fail.
  H1 INDEPENDENT TRIPLE COVERAGE. `expected_sized_action_keys` (the source-derived expected set of
     (hand_id, ledger_index), independent of the canonical replay under test) is MANDATORY — None /
     omitted FAILS. Required exact equality: source-expected == canonical == rendered. So an action
     the canonical replay omits (making both canonical + rendered disappear together) still fails.
  H2 PRIMARY VISIBLE DISPLAY. `rendered` must be the shipped HTML string (a pre-parsed list is
     rejected — synthetic evidence cannot stand in for the DOM). Each sized row must contain EXACTLY
     ONE non-hidden element marked data-sizing-role="primary" whose parsed amount equals the
     action-kind-required field (call/bet/jam -> physical_bb, raise -> live_total_bb). A hidden /
     aria-hidden / display:none / visibility:hidden primary, a duplicate primary, an unrelated/tooltip
     number, or a wrong primary all FAIL. (Stage P additionally runs a browser/DOM computed-visibility
     acceptance; this static gate freezes marker cardinality + text + static-hidden.)
"""
import math
import re

TOL = 0.06
ACTION_KINDS = ('call', 'bet', 'jam', 'raise')
DISPLAY_FIELD = {'call': 'physical_bb', 'bet': 'physical_bb', 'jam': 'physical_bb', 'raise': 'live_total_bb'}
REQUIRED_ATTRS = ('data-hand-id', 'data-ledger-index', 'data-player-id', 'data-action-kind',
                  'data-sizing-source', 'data-physical-bb', 'data-live-total-bb', 'data-uncalled-return-bb')
CANON_STR = ('hand_id', 'player_id')
CANON_NUM = ('physical_bb', 'live_total_bb', 'uncalled_return_bb')
_VIS_BB = re.compile(r'(\d+(?:\.\d+)?)\s*BB')
_HIDDEN = re.compile(r'\bhidden\b|aria-hidden="true"|display\s*:\s*none|visibility\s*:\s*hidden', re.I)


def _attr(tag, name):
    m = re.search(r'\b' + re.escape(name) + r'="([^"]*)"', tag)
    return m.group(1) if m else None


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _exact_int(x):
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def _f(x):
    try:
        v = float(x)
        return round(v, 2) if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def validate_canonical(canonical_records):
    """H1: strict, non-coercing. Returns (by_composite, errors). A non-empty errors list means the
    canonical truth set is malformed and the gate FAILS before any rendered comparison."""
    errors = []
    if not isinstance(canonical_records, list):
        return {}, [{'why': 'canonical_not_a_list'}]
    by_comp = {}
    for rec in canonical_records:
        if not isinstance(rec, dict):
            errors.append({'why': 'canonical_record_not_a_dict'}); continue
        bad = []
        for f in CANON_STR:
            v = rec.get(f)
            if not isinstance(v, str) or v == '':
                bad.append('missing_or_empty:' + f)
        li = rec.get('ledger_index')
        if not _exact_int(li):
            bad.append('ledger_index_not_exact_nonneg_int')
        ak = rec.get('action_kind')
        if ak not in ACTION_KINDS:
            bad.append('action_kind_not_in_enum:' + str(ak))
        if rec.get('sizing_source') != 'canonical_replay':
            bad.append('sizing_source_ne_canonical_replay')
        for f in CANON_NUM:
            if not _finite(rec.get(f)):
                bad.append('not_finite_number:' + f)
        if bad:
            errors.append({'hand_id': rec.get('hand_id'), 'ledger_index': li, 'invalid_fields': bad}); continue
        comp = (rec['hand_id'], li)
        if comp in by_comp:
            errors.append({'hand_id': rec['hand_id'], 'ledger_index': li, 'invalid_fields': ['duplicate_canonical_composite']}); continue
        by_comp[comp] = rec
    return by_comp, errors


def _extract_displays(inner):
    """Return the list of (role, amounts[], hidden) for every data-sizing-role element in a row."""
    out = []
    for m in re.finditer(r'<(?P<tag>[a-zA-Z][\w-]*)\b(?P<attrs>[^>]*\bdata-sizing-role="[^"]*"[^>]*)>(?P<body>.*?)</(?P=tag)>',
                         inner, re.DOTALL):
        attrs = m.group('attrs')
        role = _attr('<x ' + attrs + '>', 'data-sizing-role')
        hidden = bool(_HIDDEN.search(attrs))
        amounts = [round(float(x), 1) for x in _VIS_BB.findall(re.sub(r'<[^>]+>', ' ', m.group('body')))]
        out.append({'role': role, 'amounts': amounts, 'hidden': hidden})
    return out


def _iter_marked(html):
    """Yield (head_open_tag, inner_html) for every element carrying data-ledger-index, using BALANCED
    same-tag matching so a row's nested display <span>s are captured (a non-greedy regex stops at the
    first inner close and loses them)."""
    for m in re.finditer(r'<([a-zA-Z][\w-]*)\b[^>]*\bdata-ledger-index="[^"]*"[^>]*>', html):
        tag = m.group(1)
        head = m.group(0)
        start = m.end()
        depth = 1
        for t in re.finditer(r'<(/?)' + re.escape(tag) + r'\b[^>]*>', html[start:]):
            if t.group(1) == '/':
                depth -= 1
                if depth == 0:
                    yield head, html[start:start + t.start()]
                    break
            else:
                depth += 1


def parse_marked_rows(html):
    rows = []
    for head, inner in _iter_marked(html):
        present = {a: _attr(head, a) for a in REQUIRED_ATTRS}
        li_raw = present['data-ledger-index']
        rows.append({
            'attrs_present': {a: (present[a] is not None) for a in REQUIRED_ATTRS},
            'hand_id': present['data-hand-id'],
            'ledger_index': (int(li_raw) if (li_raw is not None and li_raw.isdigit()) else None),
            'player_id': present['data-player-id'],
            'action_kind': present['data-action-kind'],
            'sizing_source': present['data-sizing-source'],
            'physical_bb': _f(present['data-physical-bb']),
            'live_total_bb': _f(present['data-live-total-bb']),
            'uncalled_return_bb': _f(present['data-uncalled-return-bb']),
            'displays': _extract_displays(inner),
        })
    return rows


def run(rendered, canonical_records, expected_sized_action_keys):
    out = {'expected_source_keys': None, 'canonical_keys': 0, 'rendered_keys': 0, 'rows_checked': 0,
           'canonical_validation_errors': 0, 'violations': 0, 'records': []}

    def viol(rec):
        out['violations'] += 1
        if len(out['records']) < 200:
            out['records'].append(rec)

    # H1: the independent source-expected inventory is MANDATORY
    if expected_sized_action_keys is None:
        viol({'why': 'expected_source_inventory_omitted'})
        return out
    try:
        exp_src = set((str(h), int(i)) for (h, i) in expected_sized_action_keys)
    except Exception:
        viol({'why': 'expected_source_inventory_malformed'})
        return out
    out['expected_source_keys'] = len(exp_src)

    # H2: production acceptance runs against shipped HTML — a synthetic pre-parsed list is rejected
    if not isinstance(rendered, str):
        viol({'why': 'synthetic_rendered_evidence_rejected'})
        return out

    # H1: strict canonical validation before any comparison
    by_comp, errors = validate_canonical(canonical_records)
    out['canonical_keys'] = len(by_comp)
    out['canonical_validation_errors'] = len(errors)
    if errors:
        for e in errors:
            viol({'why': 'invalid_canonical_truth_record', **e})
        return out

    try:
        rows = parse_marked_rows(rendered)
    except Exception as e:
        viol({'why': 'dom_parse_failure', 'detail': str(e)[:80]})
        return out

    by_render = {}
    for r in rows:
        if r.get('ledger_index') is None or not isinstance(r.get('hand_id'), str) or r['hand_id'] == '':
            viol({'why': 'rendered_row_missing_or_unparseable_identity', 'attrs': r.get('attrs_present')})
            continue
        by_render.setdefault((r['hand_id'], r['ledger_index']), []).append(r)
    out['rendered_keys'] = len(by_render)

    canon_keys = set(by_comp.keys())
    render_keys = set(by_render.keys())
    # H1: triple equality source == canonical == rendered
    for comp in sorted(exp_src - canon_keys, key=lambda c: (c[0], c[1])):
        viol({'why': 'source_expected_action_missing_from_canonical', 'hand_id': comp[0], 'ledger_index': comp[1]})
    for comp in sorted(canon_keys - exp_src, key=lambda c: (c[0], c[1])):
        viol({'why': 'canonical_action_not_in_source_expected_set', 'hand_id': comp[0], 'ledger_index': comp[1]})
    for comp in sorted(exp_src - render_keys, key=lambda c: (c[0], c[1])):
        viol({'why': 'expected_action_not_rendered', 'hand_id': comp[0], 'ledger_index': comp[1]})
    for comp in sorted(render_keys - exp_src, key=lambda c: (c[0], c[1])):
        viol({'why': 'rendered_action_not_in_expected_set', 'hand_id': comp[0], 'ledger_index': comp[1]})
    for comp in sorted(render_keys, key=lambda c: (c[0], c[1])):
        if len(by_render[comp]) > 1:
            viol({'why': 'duplicate_rendered_element_for_composite', 'hand_id': comp[0], 'ledger_index': comp[1], 'count': len(by_render[comp])})

    # field + primary-visible-display equality for the matched 1:1 elements
    for comp in sorted(exp_src & canon_keys & render_keys, key=lambda c: (c[0], c[1])):
        if len(by_render[comp]) != 1:
            continue
        r = by_render[comp][0]
        canon = by_comp[comp]
        out['rows_checked'] += 1
        fields = []
        for a, present in r['attrs_present'].items():
            if not present:
                fields.append('missing_attr:' + a)
        for a, key in (('data-physical-bb', 'physical_bb'), ('data-live-total-bb', 'live_total_bb'),
                       ('data-uncalled-return-bb', 'uncalled_return_bb')):
            if r['attrs_present'].get(a) and r.get(key) is None:
                fields.append('unparseable_or_nonfinite_attr:' + a)
        if r.get('player_id') != canon['player_id']:
            fields.append('player_id_ne_canonical')
        if r.get('action_kind') != canon['action_kind']:
            fields.append('action_kind_ne_canonical')
        if r.get('sizing_source') != canon['sizing_source']:
            fields.append('sizing_source_ne_canonical')
        for key in CANON_NUM:
            rv = r.get(key)
            if rv is None or abs(rv - round(canon[key], 2)) > TOL:
                fields.append(key + '_ne_canonical')
        # H2: exactly one NON-HIDDEN primary display, its amount == the action-required field
        req_field = DISPLAY_FIELD[canon['action_kind']]
        req_amt = round(float(canon[req_field]), 1)
        primaries = [d for d in r['displays'] if d['role'] == 'primary']
        visible_primaries = [d for d in primaries if not d['hidden']]
        if len(primaries) == 0:
            fields.append('primary_sizing_display_absent')
        elif len([d for d in primaries]) > 1 and len(visible_primaries) != 1:
            fields.append('duplicate_primary_sizing_display')
        elif len(visible_primaries) != 1:
            fields.append('primary_sizing_display_hidden')
        else:
            amts = visible_primaries[0]['amounts']
            if not amts:
                fields.append('primary_sizing_display_no_parseable_amount')
            elif req_amt not in set(amts):
                fields.append('primary_sizing_display_ne_action_required_field:' + req_field)
        if fields:
            viol({'hand_id': r.get('hand_id'), 'ledger_index': comp[1], 'player_id': r.get('player_id'),
                  'action_kind': r.get('action_kind'), 'displays': r.get('displays'), 'canonical': canon,
                  'mismatch_fields': fields})
    return out
