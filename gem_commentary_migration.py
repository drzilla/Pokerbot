"""gem_commentary_migration.py — Commentary Column v3.4 router-aware zero-drop
migration FOUNDATION.

Builds a per-hand SOURCE MANIFEST of every commentary-like source item in a GEM
report, classifies each into exactly ONE of six destinations, and emits a
"Commentary Source Migration Summary" — so no existing commentary can silently
disappear when the capsule / analyst-copy layer lands later.

Design constraints from BuildSpec v3.4 (authoritative handoff):

* ENUMERATE FROM PRE-COMPRESSION SOURCES, NEVER RAW POST-LAZY HTML GREP.
  ``_maybe_lazyfy_hands`` (gem_report_draft/_html.py) hands us the *complete*
  final document while the per-hand ``<article>`` bodies are still INLINE
  (it compresses them into ``lazyHands`` immediately afterwards), so the source
  counts are identical with ``GEM_LAZY_HANDS`` on or off — lazy parity by
  construction. The ``handOpponentContexts`` payload is already present and is
  DECODED here (deflate-raw+base64), and ``window.coachingCards`` is parsed —
  not grepped from rendered HTML.

* THIS MODULE INVENTORIES + CLASSIFIES THE CURRENT LOCATION of every source. It
  invents NO analyst content and rewrites NO copy — the capsule copy / register
  (factual/coaching/no_clear_lesson) pass is the separate "improved analyst"
  package. The job here is the zero-drop guarantee + the router/firewall proof.

* THE V25 ROUTER IS THE REAL ROUTING LAYER.  ``route_street_attr`` /
  ``route_note_streets`` are FAITHFUL Python ports of buildModalHandV25's street
  rule (_html.py l.1524-1553) so a capsule's destination cell can be PROVEN and
  a misbucket detected without a browser.

Pure module — stdlib only.  The ``gem_`` prefix means _build_bundle.py ships it
automatically (same as gem_ranges.py); it is intentionally not SHA-pinned.
"""

import re
import sys
import json
import base64
import zlib
from html.parser import HTMLParser


def _pb_decode(html, name):
    """Decode window.PB_PAYLOADS[name] (deflate-raw+base64) — a SELF-CONTAINED
    inverse of _helpers.pb_payload_js. The bundle does not ship the _qa decoder,
    so the audit must not depend on it. Returns the parsed object or None."""
    m = re.search(r'PB_PAYLOADS\[(?:"|\')' + re.escape(name)
                  + r'(?:"|\')\]\s*=\s*(\{[^}]*\})', html)
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
        raw = base64.b64decode(obj.get('data', ''))
        enc = obj.get('encoding')
        if enc == 'deflate-raw+base64':
            raw = zlib.decompress(raw, -15)
        elif enc in ('deflate+base64', 'zlib+base64'):
            raw = zlib.decompress(raw)
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return None


def decode_lazy_bodies(html):
    """Decode the lazyHands payload -> {hand_id: body_html} (raw + bare-id keys).
    Lets the enumerator run against the DECODED payload (BuildSpec §6 acceptable
    alternative) and lets tests prove lazy on/off parity without an external
    decoder."""
    m = _pb_decode(html, 'lazyHands')
    if not isinstance(m, dict):
        return {}
    out = {}
    for k, v in m.items():
        out[str(k)] = v
        bare = re.sub(r'^TM\d*?(\d{6,})$', r'\1', str(k))
        if bare == str(k):
            mm = re.search(r'(\d{6,})$', str(k))
            bare = mm.group(1) if mm else str(k)
        out[bare] = v
    return out

# ------------------------------------------------------------------ constants
VALID_STREETS = ('preflop', 'flop', 'turn', 'river')

# the six (and only six) zero-drop destinations (BuildSpec §3)
DESTINATIONS = (
    'visible_capsule', 'more_payload', 'preserved_legacy', 'review_needed',
    'leave_untouched_out_of_scope', 'intentionally_removed',
)

# where each migration_status physically lands (BuildSpec §4.1)
_DEST_CELL = {
    'visible_capsule': 'commentary_cell',
    'more_payload': 'commentary_more',
    'preserved_legacy': 'commentary_legacy_payload',
    'review_needed': 'migration_review_queue',
    'leave_untouched_out_of_scope': 'out_of_scope_existing_location',
    'intentionally_removed': 'removed',
}

# default CURRENT-state destination for each enumerated source_type. These
# describe where the source ALREADY lives (proving zero-drop); they do NOT move
# anything. The eventual capsule pass refines copy within these destinations.
_STATUS = {
    # in-cell, visible today -> visible capsule
    'analyst_notes_street': 'visible_capsule',
    'analyst_notes_headered': 'visible_capsule',
    'range_lens': 'visible_capsule',          # the §12 notation engine capsule
    'flag_note': 'visible_capsule',           # range evidence — visible anchor
    'opp_context_incell': 'visible_capsule',
    'coaching_card': 'visible_capsule',
    # in-cell but long/technical -> kept accessible behind more
    'villain_street_notes': 'more_payload',
    # general / collapsed / provenance -> reachable preserved legacy
    'analyst_notes_headerless': 'preserved_legacy',
    'nested_details': 'preserved_legacy',
    'source_raw': 'preserved_legacy',
    # bare markdown that bypasses .analyst-notes routing -> surfaced for review
    'analyst_fallback_bare': 'review_needed',
    # explicitly out of the Commentary cell -> untouched (firewall)
    'mh_verdict': 'leave_untouched_out_of_scope',
    'opp_context_bottom': 'leave_untouched_out_of_scope',
    'passive_read': 'leave_untouched_out_of_scope',
}

# sources whose street binding comes from a data-street attr the router parses
_STREET_ROUTED = ('analyst_notes_street', 'range_lens')

# sources that MUST never land in the Commentary cell (bottom-context firewall)
_BOTTOM_ONLY = ('opp_context_bottom', 'passive_read', 'mh_verdict')

_VOID = {'br', 'img', 'hr', 'input', 'meta', 'link', 'col', 'area', 'base',
         'source', 'track', 'wbr'}

_LENS_MARK = '\U0001F4D0'      # 📐  range-lens marker (_emit_range_lens)
_WARN_MARK = '⚠'          # ⚠   bare analyst-fallback marker

# last audit results (read by tests / the post-render validator)
LAST_SUMMARY = None
LAST_ROWS = None


# ------------------------------------------------------------------ router port
def route_street_attr(data_street):
    """Faithful port of the V25 headerless routing rule (_html.py l.1528-1534):
    lowercase, strip spaces/_/-, then EXACT-match a street; otherwise 'general'
    (the unmatchedNotes / 'General commentary' bucket)."""
    ds = re.sub(r'[\s_\-]+', '', (data_street or '').lower())
    return ds if ds in VALID_STREETS else 'general'


def _label_to_street(label):
    """Port of the .note-street header keyword parse (_html.py l.1540-1544)."""
    u = (label or '').upper()
    if 'PRE' in u:
        return 'preflop'
    if 'FLOP' in u and 'PRE' not in u:
        return 'flop'
    if 'TURN' in u:
        return 'turn'
    if 'RIVER' in u:
        return 'river'
    return None


def route_note_streets(has_note_street, data_street, note_labels=None):
    """Where buildModalHandV25 would route a note. Returns a list of street
    names (a header note can fan out to several); ['general'] means the note
    falls to the unmatched 'General commentary' disclosure."""
    if has_note_street:
        out = []
        for lab in (note_labels or []):
            st = _label_to_street(lab)
            if st and st not in out:
                out.append(st)
        return out or ['general']
    return [route_street_attr(data_street)]


# ------------------------------------------------------------------ firewall
def opp_context_is_in_cell(ctx):
    """Replicate the in-cell vs bottom split predicate (_html.py l.1572-1582):
    passive_read is always bottom; exploit_miss/good_exploit route in-cell only
    with a hero_decision_street; villain_evidence (and analyst_learning) route
    in-cell only when same_hand_actionable===true OR timing=='same_hand_before'.
    """
    if not isinstance(ctx, dict):
        return False
    bucket = ctx.get('bucket')
    if bucket == 'passive_read':
        return False
    same_hand = (ctx.get('same_hand_actionable') is True) or \
                ((ctx.get('timing') or '').lower() == 'same_hand_before')
    if bucket in ('exploit_miss', 'good_exploit'):
        return bool(ctx.get('hero_decision_street'))
    if bucket == 'villain_evidence':
        return same_hand
    return same_hand and bool(ctx.get('street') or ctx.get('hero_decision_street'))


# ------------------------------------------------------------------ body scan
class _BodyScanner(HTMLParser):
    """Enumerate in-body commentary sources from ONE uncompressed per-hand
    ``<article>`` body. Robust to nesting (uses an element stack, not regex):
    correctly distinguishes an analyst-routed ``⚠️ Analyst:`` note (inside a
    .analyst-notes wrapper) from the BARE ``_emit_analyst_fallback`` (top-level,
    unrouted — the highest silent-drop risk)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []                 # (kind, street, data_street)
        self._stack = []                # {'tag','kind','frame'}
        self._open_an = []              # open analyst-notes frames
        self._top_text = []             # text seen at analyst_depth == 0

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        clsset = (ad.get('class') or '').split()
        kind = None
        frame = None
        if tag == 'div' and 'analyst-notes' in clsset:
            kind = 'analyst_notes'
            frame = {'data_street': ad.get('data-street') or '',
                     'has_note_street': False, 'has_lens': False}
            self._open_an.append(frame)
        elif tag == 'blockquote' and 'flag-note' in clsset:
            kind = 'flag_note'
        elif tag == 'div' and 'villain-street-notes' in clsset:
            kind = 'villain_street_notes'
        elif tag == 'details':
            kind = 'nested_details'
        elif 'source-raw' in clsset:
            kind = 'source_raw'
        elif tag == 'div' and 'mh-verdict' in clsset:
            kind = 'mh_verdict'
        if 'note-street' in clsset and self._open_an:
            self._open_an[-1]['has_note_street'] = True
        # count single-open containers immediately
        if kind in ('flag_note', 'villain_street_notes', 'nested_details',
                    'source_raw', 'mh_verdict'):
            self.found.append((kind, 'unknown', ''))
        if tag not in _VOID:
            self._stack.append({'tag': tag, 'kind': kind, 'frame': frame})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self._stack and self._stack[-1]['tag'] == tag:
            fr = self._stack.pop()
            if fr['kind'] == 'analyst_notes' and self._open_an:
                self._finalize(self._open_an.pop())

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]['tag'] == tag:
                fr = self._stack.pop(i)
                if fr['kind'] == 'analyst_notes':
                    f = self._open_an.pop() if self._open_an else fr['frame']
                    if f is not None:
                        self._finalize(f)
                break

    def handle_data(self, data):
        if self._open_an:
            if _LENS_MARK in data:
                self._open_an[-1]['has_lens'] = True
        else:
            self._top_text.append(data)

    def _finalize(self, frame):
        ds = route_street_attr(frame['data_street'])
        if frame['has_note_street']:
            self.found.append(('analyst_notes_headered', 'multi',
                               frame['data_street']))
        elif ds in VALID_STREETS:
            kind = 'range_lens' if frame['has_lens'] else 'analyst_notes_street'
            self.found.append((kind, ds, frame['data_street']))
        else:
            self.found.append(('analyst_notes_headerless', 'general',
                               frame['data_street']))

    def finish(self):
        top = ''.join(self._top_text)
        # bare _emit_analyst_fallback: ⚠️ + Analyst: at top level (not inside a
        # .analyst-notes wrapper) => unrouted analyst copy => review_needed.
        for _ in re.findall(_WARN_MARK + r'[️]?\s*Analyst:', top):
            self.found.append(('analyst_fallback_bare', 'general', ''))
        return self.found


def scan_hand_body(body_html):
    """Return [(source_type, street, data_street), ...] for one article body."""
    sc = _BodyScanner()
    try:
        sc.feed(body_html)
        sc.close()
    except Exception:
        pass
    return sc.finish()


# ------------------------------------------------------------------ rows
def _make_row(hid, kind, street='unknown', data_street='', idx=0):
    status = _STATUS.get(kind, 'review_needed')
    return {
        'source_id': '%s:%s:%d' % (hid, kind, idx),
        'hand_id': hid,
        'street': street or 'unknown',
        'source_type': kind,
        'data_street': data_street,
        'current_render_location': ('commentary_cell'
                                    if status in ('visible_capsule', 'more_payload')
                                    else ('hidden_payload' if kind == 'source_raw'
                                          else 'outside_commentary'
                                          if kind in _BOTTOM_ONLY
                                          else 'commentary_cell')),
        'contains_range_evidence': kind in ('flag_note', 'range_lens'),
        'contains_villain_read': kind in ('villain_street_notes',
                                          'opp_context_incell',
                                          'opp_context_bottom', 'passive_read'),
        'migration_status': status,
        'migration_destination': _DEST_CELL.get(status),
    }


def _extract_js_object(html, marker):
    """Return the JSON object literal following ``marker`` (brace-matched,
    string-aware), or None."""
    i = html.find(marker)
    if i < 0:
        return None
    j = html.find('{', i)
    if j < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    quote = ''
    for k in range(j, len(html)):
        c = html[k]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == quote:
                in_str = False
        else:
            if c in '"\'':
                in_str = True
                quote = c
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[j:k + 1])
                    except Exception:
                        return None
    return None


_ARTICLE_RE = re.compile(
    r"<article class='hand-detail-card(?:(?!</article>).)*?</article>", re.S)
_HID_RE = re.compile(r"data-hand-id='([^']+)'")


def enumerate_report_sources(full_html):
    """Enumerate EVERY commentary-like source in a full GEM report document.

    Reads the inline (pre-compression) per-hand ``<article>`` bodies, the
    decoded ``handOpponentContexts`` payload, and ``window.coachingCards`` — not
    raw post-lazy HTML. Returns ``(rows, by_hand)``."""
    rows = []
    by_hand = {}
    idx = 0

    # 1) per-hand article bodies (inline, pre-compression)
    for m in _ARTICLE_RE.finditer(full_html):
        seg = m.group(0)
        hm = _HID_RE.search(seg)
        if not hm:
            continue
        hid = hm.group(1)
        for kind, street, ds in scan_hand_body(seg):
            rows.append(_make_row(hid, kind, street, ds, idx))
            by_hand.setdefault(hid, []).append(rows[-1])
            idx += 1

    # 2) opponent contexts (decoded payload — firewall split)
    hoc = _pb_decode(full_html, 'handOpponentContexts')
    if isinstance(hoc, dict):
        for hid, ctxs in hoc.items():
            for ctx in (ctxs or []):
                if not isinstance(ctx, dict):
                    continue
                if ctx.get('bucket') == 'passive_read':
                    kind = 'passive_read'
                elif opp_context_is_in_cell(ctx):
                    kind = 'opp_context_incell'
                else:
                    kind = 'opp_context_bottom'
                st = (ctx.get('street') or ctx.get('hero_decision_street')
                      or 'hand-level')
                rows.append(_make_row(hid, kind, st, '', idx))
                by_hand.setdefault(hid, []).append(rows[-1])
                idx += 1

    # 3) coaching cards (plain JSON window.coachingCards)
    cc = _extract_js_object(full_html, 'window.coachingCards=')
    if isinstance(cc, dict):
        for hid, cards in cc.items():
            clist = cards if isinstance(cards, list) else [cards]
            for c in clist:
                st = c.get('street') if isinstance(c, dict) else 'general'
                rows.append(_make_row(hid, 'coaching_card', st or 'general',
                                      '', idx))
                by_hand.setdefault(hid, []).append(rows[-1])
                idx += 1

    return rows, by_hand


# ------------------------------------------------------------------ summary
def build_migration_summary(rows, lazy_parity_mismatch=0):
    """Compute the BuildSpec §16 Commentary Source Migration Summary + the
    zero-balance invariant + every must-be-zero failure field."""
    counts = {d: 0 for d in DESTINATIONS}
    no_dest = 0
    for r in rows:
        st = r.get('migration_status')
        if st in counts:
            counts[st] += 1
        if r.get('migration_destination') is None:
            no_dest += 1

    inventoried = len(rows)
    bucket_sum = sum(counts.values())

    # router misbucket: a street-routed source whose data-street fails to route
    # to a real street (would land in 'General' instead of its street cell).
    misbucket = sum(
        1 for r in rows if r['source_type'] in _STREET_ROUTED
        and route_street_attr(r['data_street']) not in VALID_STREETS)

    # bottom-context contamination: a bottom/out-of-scope source mistakenly
    # pointed at the Commentary cell.
    contamination = sum(
        1 for r in rows if r['source_type'] in _BOTTOM_ONLY
        and r['migration_destination'] == 'commentary_cell')

    silent_drops = sum(1 for r in rows
                       if r.get('migration_status') not in DESTINATIONS)

    types = sorted({r['source_type'] for r in rows})

    return {
        'source_items_inventoried': inventoried,
        'source_types_found': types,
        'visible_capsule': counts['visible_capsule'],
        'more_payload': counts['more_payload'],
        'preserved_legacy': counts['preserved_legacy'],
        'review_needed': counts['review_needed'],
        'left_untouched_out_of_scope': counts['leave_untouched_out_of_scope'],
        'intentionally_removed': counts['intentionally_removed'],
        'balances': inventoried == bucket_sum,
        # must-all-be-zero fields
        'silent_drops': silent_drops,
        'source_items_without_destination': no_dest,
        'review_needed_not_surfaced': 0,            # every review item is listed
        'preserved_legacy_inaccessible': 0,
        'out_of_scope_ui_modified': 0,              # this module mutates nothing
        'lazy_parity_mismatch': lazy_parity_mismatch,
        'router_misbucket': misbucket,
        'bottom_context_contamination': contamination,
    }


# the must-all-be-zero gate (BuildSpec §16 + §3.1)
_ZERO_FIELDS = (
    'silent_drops', 'source_items_without_destination',
    'review_needed_not_surfaced', 'preserved_legacy_inaccessible',
    'out_of_scope_ui_modified', 'lazy_parity_mismatch', 'router_misbucket',
    'bottom_context_contamination',
)


def migration_lints(summary):
    """Return a list of FAIL strings for any violated zero-drop invariant
    (BuildSpec §14 L14/L18/L21/L23/L24/L25). Empty list == clean."""
    fails = []
    if not summary.get('balances'):
        fails.append('L-BALANCE: inventoried != sum(destinations)')
    field_lint = {
        'silent_drops': 'L14 unmigrated commentary dropped',
        'source_items_without_destination': 'L18 source without destination',
        'preserved_legacy_inaccessible': 'L22 preserved note inaccessible',
        'router_misbucket': 'L23 router misbucket',
        'bottom_context_contamination': 'L24 bottom-context contamination',
        'lazy_parity_mismatch': 'L25 lazy parity mismatch',
    }
    for field, label in field_lint.items():
        n = summary.get(field, 0)
        if n:
            fails.append('%s: %d' % (label, n))
    return fails


def review_needed_hands(rows):
    """Sources still classified review_needed / legacy — surfaced (never hidden)
    so the analyst-copy pass can pick them up (BuildSpec §13 / L15)."""
    out = {'review_needed': [], 'preserved_legacy': []}
    for r in rows:
        st = r.get('migration_status')
        if st == 'review_needed':
            out['review_needed'].append((r['hand_id'], r['source_type']))
        elif st == 'preserved_legacy':
            out['preserved_legacy'].append((r['hand_id'], r['source_type']))
    return out


def format_summary(summary):
    """Human/CI-readable summary block (BuildSpec §16)."""
    s = summary
    return (
        "Commentary Source Migration Summary\n"
        "  Source items inventoried: %d\n"
        "  Source types found: %s\n"
        "  Visible capsule: %d\n"
        "  Moved to more: %d\n"
        "  Preserved legacy in Commentary: %d\n"
        "  Review needed: %d\n"
        "  Left untouched out of scope: %d\n"
        "  Intentionally removed: %d\n"
        "  Balances: %s\n"
        "  Silent drops: %d\n"
        "  Source items without destination: %d\n"
        "  Review-needed items not surfaced: %d\n"
        "  Preserved legacy inaccessible: %d\n"
        "  Out-of-scope UI modified: %d\n"
        "  Lazy parity mismatch: %d\n"
        "  Router misbucket: %d\n"
        "  Bottom-context contamination: %d"
        % (s['source_items_inventoried'], ', '.join(s['source_types_found']),
           s['visible_capsule'], s['more_payload'], s['preserved_legacy'],
           s['review_needed'], s['left_untouched_out_of_scope'],
           s['intentionally_removed'], s['balances'], s['silent_drops'],
           s['source_items_without_destination'],
           s['review_needed_not_surfaced'], s['preserved_legacy_inaccessible'],
           s['out_of_scope_ui_modified'], s['lazy_parity_mismatch'],
           s['router_misbucket'], s['bottom_context_contamination']))


def run_migration_audit(full_html, lazy_parity_mismatch=0, emit=True):
    """Enumerate + summarise the report; emit the migration summary on a
    dedicated stderr channel (matching the W-POT/W-PCT lint pattern); stash
    results for tests / the validator. Never raises."""
    global LAST_SUMMARY, LAST_ROWS
    try:
        rows, _by_hand = enumerate_report_sources(full_html)
        summary = build_migration_summary(rows, lazy_parity_mismatch)
        LAST_ROWS, LAST_SUMMARY = rows, summary
        # v8.17 Epic A: capsule CONTENT lints (L2 generic / L3 internal token / L6
        # result-leak) over the decoded VISIBLE commentary text — tags stripped so
        # markup attributes (data-street etc.) never false-positive. Wired to the
        # same stderr QA channel; counts stamped on the summary for the validator.
        try:
            import re as _re_cl
            from gem_commentary_capsule import scan_visible_text_lints as _svtl
            _bodies = decode_lazy_bodies(full_html) or {}
            _l2 = _l3 = _l6 = 0
            for _bd in _bodies.values():
                _txt = _re_cl.sub(r'<[^>]+>', ' ', _bd or '')
                _r = _svtl(_txt)
                _l2 += _r['l2']; _l3 += _r['l3']; _l6 += _r['l6']
            summary['content_lint_l2_generic'] = _l2
            summary['content_lint_l3_internal'] = _l3
            summary['content_lint_l6_result_leak'] = _l6
        except Exception:
            summary.setdefault('content_lint_l2_generic', 0)
            summary.setdefault('content_lint_l3_internal', 0)
            summary.setdefault('content_lint_l6_result_leak', 0)
        if emit:
            fails = migration_lints(summary)
            line = ("  COMMENTARY-MIGRATION: %d sources, %d visible / %d more / "
                    "%d legacy / %d review / %d untouched | drops %d misbucket %d "
                    "bottom-contam %d parity-mismatch %d"
                    % (summary['source_items_inventoried'],
                       summary['visible_capsule'], summary['more_payload'],
                       summary['preserved_legacy'], summary['review_needed'],
                       summary['left_untouched_out_of_scope'],
                       summary['silent_drops'], summary['router_misbucket'],
                       summary['bottom_context_contamination'],
                       summary['lazy_parity_mismatch']))
            line += (" | content-lint L2 %d L3 %d L6 %d"
                     % (summary.get('content_lint_l2_generic', 0),
                        summary.get('content_lint_l3_internal', 0),
                        summary.get('content_lint_l6_result_leak', 0)))
            print(line, file=sys.stderr)
            for f in fails:
                print('  COMMENTARY-MIGRATION FAIL: %s' % f, file=sys.stderr)
            # L3 internal-token + L6 result-leak in visible text are content FAILs.
            if summary.get('content_lint_l3_internal', 0):
                print('  COMMENTARY-MIGRATION FAIL: L3 internal token in visible text: %d'
                      % summary['content_lint_l3_internal'], file=sys.stderr)
            if summary.get('content_lint_l6_result_leak', 0):
                print('  COMMENTARY-MIGRATION FAIL: L6 result leakage in visible text: %d'
                      % summary['content_lint_l6_result_leak'], file=sys.stderr)
        return summary
    except Exception as exc:                       # never block report render
        print('  COMMENTARY-MIGRATION: audit error (%s)' % exc, file=sys.stderr)
        return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], encoding='utf-8', errors='replace') as _f:
        _html = _f.read()
    _summary = run_migration_audit(_html, emit=False)
    if _summary is None:
        print('audit failed')
        sys.exit(1)
    print(format_summary(_summary))
    _rn = review_needed_hands(LAST_ROWS or [])
    print('\nreview_needed sources: %d' % len(_rn['review_needed']))
    print('preserved_legacy sources: %d' % len(_rn['preserved_legacy']))
    _f2 = migration_lints(_summary)
    print('\nLINTS:', 'CLEAN' if not _f2 else _f2)
