"""gem_report_draft/_datatable.py -- the bounded shared DataTable foundation (Wave-2, v8.18.0).

ONE typed table engine that Tournament Results consumes (replacing the ad-hoc _ttSort / per-surface
sort+filter+aggregate logic). It owns: typed column definitions, the display formatter, the sort
accessor (signed-numeric aware, stable null handling), filters, totals/aggregates, the sticky header
+ sticky filter controls, responsive behaviour, accessible labels, and canonical link/hand cells.

Python builds the typed schema + the table HTML; the shared `initDataTable(tableId)` JS (in _html.py)
reads the schema off the <thead> data-* attributes and drives click-to-sort (with aria-sort),
filter-chip state, and totals recomputation over the visible rows. No second table engine.

A Column is declarative:
    Column(key, label, kind, sortable, filterable, align, aggregate, null_label)
    kind  : text | num | money | pct | signed | finish | hand | link   (drives format + sort + align)
A Cell is {value (the sort key, None -> sorts last), display (HTML), cls}. build_cell() makes typed
cells; hand_cell() routes a hand through the canonical PokerHandDisplay owner.
"""
import html as _html
from dataclasses import dataclass

_NUM_KINDS = ('num', 'money', 'pct', 'signed')


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = 'text'          # text | num | money | pct | signed | finish | hand | link
    sortable: bool = True
    filterable: bool = False
    align: str = ''             # '', 'right', 'center'  ('' -> derived from kind)
    aggregate: str = ''         # '', 'sum', 'avg', 'wavg'
    null_label: str = '—'  # em dash
    weight_key: str = ''        # for aggregate='wavg': the key of the weight column

    def sort_kind(self):
        if self.kind in _NUM_KINDS:
            return 'num'
        if self.kind == 'finish':
            return 'finish'
        return 'text'

    def cell_align(self):
        return self.align or ('right' if self.kind in _NUM_KINDS else 'left')


def fmt_money(v, *, signed=False):
    if v is None:
        return None
    v = float(v)
    s = '${:,.2f}'.format(abs(v))
    if signed:
        return ('+' if v > 0 else ('-' if v < 0 else '')) + s
    return ('-' + s) if v < 0 else s


def fmt_pct(v, *, signed=False, decimals=1):
    if v is None:
        return None
    v = float(v)
    body = ('%.*f%%' % (decimals, abs(v)))
    if signed:
        return ('+' if v > 0 else ('-' if v < 0 else '')) + body
    return ('-' + body) if v < 0 else body


def build_cell(col, value, *, display=None, cls=''):
    """Make a typed Cell. `value` is the canonical sort key (None sorts LAST). `display` overrides the
    auto-format. Signed kinds carry a +/- and a sign class; -100% ROI is muted (kept, de-emphasised)."""
    sortv = value
    if display is None:
        if value is None:
            display = col.null_label
        elif col.kind == 'money':
            display = fmt_money(value, signed=False)
        elif col.kind == 'signed':
            display = fmt_money(value, signed=True)
        elif col.kind == 'pct':
            display = fmt_pct(value, signed=False)
        else:
            display = _html.escape(str(value))
    extra = cls
    if col.kind in ('signed',) and isinstance(value, (int, float)):
        extra += (' dt-pos' if value > 0 else (' dt-neg' if value < 0 else ''))
    # mute a total-bust -100% while RETAINING the value (Tournament Results ROI contract)
    if col.kind == 'pct' and isinstance(value, (int, float)) and abs(value + 100.0) < 0.5:
        extra += ' dt-muted'
    return {'value': sortv, 'display': display, 'cls': extra.strip()}


def hand_cell(col, hand_id, cards, *, size='standard'):
    """Canonical exit-hand / table hand cell: the PokerHandDisplay component + a standard hand link,
    with the hand id kept SEPARATE from the card display."""
    from gem_report_draft._cards import render_poker_hand, HandDisplaySize
    hid = str(hand_id or '')[-8:]
    if not hid:
        return {'value': None, 'display': col.null_label, 'cls': ''}
    sz = HandDisplaySize(size) if isinstance(size, str) else size
    phd = render_poker_hand(cards, size=sz, sort_desc=True) if cards else ''
    link = ("<a href='#' class='hand-ref xref' data-hid='%s' aria-label='Open hand %s'>%s</a>"
            % (_html.escape(hid), _html.escape(hid), _html.escape(hid)))
    disp = ("<span class='dt-hand'>%s%s</span>" % (phd + ' ' if phd else '', link))
    return {'value': hid, 'display': disp, 'cls': ''}


def _agg(col, rows):
    """Compute a column's aggregate over rows (each row is {key: cell}). Returns a display string."""
    vals = [(r.get(col.key) or {}).get('value') for r in rows]
    nums = [float(v) for v in vals if isinstance(v, (int, float))]
    if not nums or not col.aggregate:
        return ''
    if col.aggregate == 'sum':
        v = sum(nums)
    elif col.aggregate == 'avg':
        v = sum(nums) / len(nums)
    elif col.aggregate == 'wavg':
        ws = [(r.get(col.weight_key) or {}).get('value') for r in rows]
        pairs = [(float(x), float(w)) for x, w in zip(vals, ws)
                 if isinstance(x, (int, float)) and isinstance(w, (int, float))]
        tw = sum(w for _, w in pairs)
        v = (sum(x * w for x, w in pairs) / tw) if tw else (sum(nums) / len(nums))
    else:
        return ''
    if col.kind == 'money':
        return fmt_money(v)
    if col.kind == 'signed':
        return fmt_money(v, signed=True)
    if col.kind == 'pct':
        return fmt_pct(v)
    return ('%.1f' % v)


def render_datatable(columns, rows, *, table_id, totals=True, totals_label='Total',
                     totals_override=None, filters=None, mobile_min_width=920, classes='tt-finance'):
    """Render the typed table. `rows` is a list of {col.key: Cell}. `filters` is an optional list of
    {key, label, options:[{value,label,count}]} -> sticky compact filter chips. Emits the schema on the
    <thead> so initDataTable(tableId) drives sort/filter/totals."""
    cols = list(columns)
    th = []
    for i, c in enumerate(cols):
        # data-dt-kind is the COLUMN kind (drives both the numeric/text sort AND the totals format).
        attrs = ("data-dt-col='%s' data-dt-kind='%s' data-dt-sortable='%d' data-dt-agg='%s' class='dt-%s'"
                 % (_html.escape(c.key), _html.escape(c.kind), 1 if c.sortable else 0,
                    _html.escape(c.aggregate or ''), c.cell_align()))
        aria = " aria-sort='none'" if c.sortable else ''
        th.append('<th %s%s>%s</th>' % (attrs, aria, _html.escape(c.label)))
    body = []
    for r in rows:
        tds = []
        for c in cols:
            cell = r.get(c.key) or {'value': None, 'display': c.null_label, 'cls': ''}
            sv = cell.get('value')
            sv_attr = '' if sv is None else (" data-sort-value='%s'" % _html.escape(str(sv)))
            tds.append("<td data-label='%s'%s class='dt-%s %s'>%s</td>"
                       % (_html.escape(c.label), sv_attr, c.cell_align(),
                          _html.escape(cell.get('cls', '')), cell.get('display', '')))
        frow = ''
        if filters:
            fattrs = ' '.join("data-filter-%s='%s'" % (_html.escape(f['key']),
                              _html.escape(str((r.get('_filters') or {}).get(f['key'], ''))))
                              for f in filters)
            frow = ' ' + fattrs
        body.append('<tr%s>%s</tr>' % (frow, ''.join(tds)))
    foot = ''
    if totals:
        tds = []
        ov = totals_override or {}
        for i, c in enumerate(cols):
            if i == 0:
                tds.append("<td class='dt-totals-label'>%s</td>" % _html.escape(totals_label))
            elif c.key in ov:
                # a caller-supplied totals cell (e.g. average Top%); not JS-recomputed on filter.
                tds.append("<td class='dt-%s'>%s</td>" % (c.cell_align(), ov[c.key]))
            else:
                tds.append("<td class='dt-%s' data-dt-total='%s'>%s</td>"
                           % (c.cell_align(), _html.escape(c.key), _agg(c, rows)))
        foot = "<tfoot><tr class='dt-totals'>%s</tr></tfoot>" % ''.join(tds)
    fhtml = ''
    if filters:
        chips = []
        for f in filters:
            opts = ''.join(
                "<button type='button' class='dt-chip' data-dt-filter='%s' data-dt-value='%s'>"
                "%s%s</button>" % (_html.escape(f['key']), _html.escape(str(o['value'])),
                                   _html.escape(o['label']),
                                   (" <span class='dt-chip-n'>%d</span>" % o['count']) if o.get('count') is not None else '')
                for o in f.get('options', []))
            chips.append("<span class='dt-filter-group' role='group' aria-label='%s'>"
                         "<span class='dt-filter-label'>%s</span>%s</span>"
                         % (_html.escape(f['label']), _html.escape(f['label']), opts))
        fhtml = ("<div class='dt-filters' data-dt-for='%s' role='toolbar' aria-label='Table filters'>%s</div>"
                 % (_html.escape(table_id), ''.join(chips)))
    # No inline <script> (markdown would strip it); the caller wires initDataTable via the JS bootstrap.
    return (
        "%s<div class='table-shell dt-shell' data-mobile-mode='scroll' style='--mobile-table-min-width:%dpx'>"
        "<div class='table-scroll'><table class='data-table dt %s' id='%s' data-datatable='1'>"
        "<thead><tr>%s</tr></thead><tbody>%s</tbody>%s</table></div></div>"
        % (fhtml, mobile_min_width, _html.escape(classes), _html.escape(table_id),
           ''.join(th), ''.join(body), foot))
