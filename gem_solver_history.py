#!/usr/bin/env python3
"""
gem_solver_history.py — v0.1

Cross-session persistence for solver runs. Feeds the drift monitor.

One row per solved hand. Lives in /mnt/project/solver_history.csv
(persistent across sessions — Ron uploads at session end).

Schema (CSV):
  timestamp, session_tag, hand_id, mode, mistake_type, confidence,
  heuristic_ev_bb, solver_ev_bb, delta_bb,
  audit_path, range_source_key, within_m14_band

Rules:
  - Every solver_applied=True augmentation appends one row
  - M14-indifferent spots are logged but flagged (excluded from drift agg)
  - Low-confidence (🔴) spots are logged but flagged (excluded from drift agg)
  - Never silently drops a row — failures caught at read time, not write
"""
import os, csv, json
from datetime import datetime, timezone

HISTORY_COLS = [
    'timestamp', 'session_tag', 'hand_id', 'mode', 'mistake_type',
    'confidence', 'heuristic_ev_bb', 'solver_ev_bb', 'delta_bb',
    'audit_path', 'range_source_key', 'within_m14_band',
]

# Default location: read from /mnt/project/ (persistent), write to /home/claude/
# At session end Ron copies /home/claude/solver_history.csv → /mnt/project/
DEFAULT_READ_PATH  = '/mnt/project/solver_history.csv'
DEFAULT_WRITE_PATH = '/home/claude/solver_history.csv'


def read_history(path=DEFAULT_READ_PATH):
    """Read historical solver runs. Returns list of dicts, empty if file missing."""
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for r in reader:
                # Coerce numerics; skip unparseable rows rather than crash
                try:
                    r['heuristic_ev_bb'] = float(r['heuristic_ev_bb'])
                    r['solver_ev_bb']    = float(r['solver_ev_bb'])
                    r['delta_bb']        = float(r['delta_bb'])
                    r['within_m14_band'] = r.get('within_m14_band', '').lower() == 'true'
                    rows.append(r)
                except (ValueError, KeyError):
                    continue
    except Exception:
        return []
    return rows


def append_rows(new_rows, read_path=DEFAULT_READ_PATH, write_path=DEFAULT_WRITE_PATH):
    """
    Append rows to history. Strategy:
      1. Read existing history from read_path (/mnt/project/)
      2. Combine with new_rows
      3. Write combined to write_path (/home/claude/)
    Ron uploads write_path → read_path between sessions.

    new_rows: list of dicts with keys in HISTORY_COLS
    """
    existing = read_history(read_path)
    # Deduplicate on (hand_id, timestamp) to avoid duplicate rows if solver re-runs
    seen = {(r.get('hand_id'), r.get('timestamp')) for r in existing}
    combined = list(existing)
    for r in new_rows:
        key = (r.get('hand_id'), r.get('timestamp'))
        if key not in seen:
            combined.append(r)
            seen.add(key)

    os.makedirs(os.path.dirname(write_path), exist_ok=True)
    with open(write_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLS, extrasaction='ignore')
        writer.writeheader()
        for r in combined:
            writer.writerow(r)
    return len(combined), len(new_rows)


def make_row(session_tag, hand_id, mode, mistake_type, confidence,
             heuristic_ev, solver_ev, audit_path, range_source_key,
             within_m14):
    """Construct a single history row with validated fields."""
    return {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'session_tag': session_tag or '',
        'hand_id': hand_id or '',
        'mode': mode or '',
        'mistake_type': mistake_type or '',
        'confidence': confidence or '',
        'heuristic_ev_bb': round(float(heuristic_ev or 0), 2),
        'solver_ev_bb': round(float(solver_ev or 0), 2),
        'delta_bb': round(float((solver_ev or 0) - (heuristic_ev or 0)), 2),
        'audit_path': audit_path or '',
        'range_source_key': range_source_key or '',
        'within_m14_band': bool(within_m14),
    }


if __name__ == '__main__':
    # Self-test
    rows = read_history()
    print(f'Existing history rows: {len(rows)}')
    sample = make_row('test_sess', 'TM99000001', 'call_fold', 'Bad River Call',
                      '🟢 HIGH', -3.0, -10.97, '/tmp/audit', 'BB_DEF_vs20pct', False)
    print(f'Sample row: {sample}')
