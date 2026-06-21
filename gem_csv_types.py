#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""COR-001 (v8.18.1): ONE typed load/model boundary for the session-history / financial CSVs.

The session CSVs (session_history_*.csv, session_financials.csv, session_financials_per_tournament.csv)
are read with csv.DictReader, which yields every value as a STRING. Renderers then format those values
numerically -- e.g. ``'%+.1f' % row['BB_per_100']`` crashes on a string, and ``float(row['Net_USD'])``
crashes on a comma-formatted "1,234.50" or an empty "". Production failed before HTML generation for
exactly this reason and needed a local coercion workaround.

This module coerces the numeric columns ONCE, at the load boundary, so renderers receive typed numbers
(float/int) or None -- no per-site casts, no comma/format crashes. Text columns (names, formats) stay
text. Empty/missing -> None unless the column's domain explicitly defaults to zero.
"""
import csv as _csv
import io as _io


def coerce_numeric(value):
    """Normalize one CSV cell to a typed number or None.

        "49.5"      -> 49.5
        "1,234.50"  -> 1234.5
        "$25"       -> 25
        "-100.0"    -> -100.0
        "0.2529"    -> 0.2529
        "49"        -> 49        (int when the source carried no decimal point)
        ""          -> None
        None        -> None
        "missing"/"N/A"/"abc" -> None   (non-numeric text)
    """
    if value is None:
        return None
    s = str(value).strip()
    if s == '':
        return None
    body = s.replace(',', '').replace('$', '').replace('−', '-')
    if body.endswith('%'):
        body = body[:-1].strip()
    try:
        f = float(body)
    except (ValueError, TypeError):
        return None
    # keep an integer typed as int when the source had no fractional part
    if f.is_integer() and '.' not in body and 'e' not in body.lower():
        return int(f)
    return f


def _is_numeric_column(values):
    """A column is numeric when every NON-EMPTY value parses as a number (so 'Top_Leak' text columns,
    tournament names, formats stay text even if some cells look numeric-ish)."""
    nonempty = [v for v in values if v not in (None, '')]
    return bool(nonempty) and all(coerce_numeric(v) is not None for v in nonempty)


def coerce_csv_rows(rows, zero_default=frozenset(), numeric_fields=None):
    """Return (typed_rows, numeric_fields). Auto-detects numeric columns (or uses the supplied set) and
    coerces them; text columns are left untouched. Empty/non-numeric -> None unless the column is in
    ``zero_default`` (-> 0.0)."""
    rows = list(rows)
    if not rows:
        return rows, set()
    fields = list(rows[0].keys())
    if numeric_fields is None:
        numeric_fields = {f for f in fields if _is_numeric_column([r.get(f) for r in rows])}
    else:
        numeric_fields = set(numeric_fields)
    out = []
    for r in rows:
        nr = dict(r)
        for f in numeric_fields:
            if f not in nr:
                continue
            c = coerce_numeric(nr.get(f))
            nr[f] = c if c is not None else (0.0 if f in zero_default else None)
        out.append(nr)
    return out, numeric_fields


def read_typed_csv(path, zero_default=frozenset(), numeric_fields=None):
    """Open a CSV and return typed rows (the canonical replacement for ``list(csv.DictReader(open(path)))``
    at the session-CSV load boundary)."""
    with _io.open(path, encoding='utf-8', errors='replace') as f:
        rows, _ = coerce_csv_rows(_csv.DictReader(f), zero_default=zero_default,
                                  numeric_fields=numeric_fields)
    return rows
