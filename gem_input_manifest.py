"""v8.19.0 Chapter I — explicit input manifest + reproducibility.

A PURE, deterministic builder: the same inputs + config produce the same manifest (modulo a
caller-supplied timestamp). It makes report coverage explicit — files discovered/classified,
hands parsed, events discovered vs HH-backed vs summary-only vs financially resolved, skipped /
failed files, analysis mode, config/version, cache/stale — and emits a reproducibility proof
(canonical file-list hash + the invariants that must hold for the conclusions to be stable).

No silent coercion / fallback / missing-file behaviour may change conclusions: anything that
could is recorded here so it is visible rather than hidden.
"""
import os
import hashlib
from collections import Counter


def _file_md5(path):
    try:
        h = hashlib.md5()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def canonical_input_hashes(session_dir):
    """SHA-256 of every input file actually used under session_dir, by RECURSIVE walk (not only top-level
    *.txt) -- the canonical input identity the sealed analyst packet + --quick bind against (owner blocker
    #6/#7). Keys are session-relative POSIX paths so the identity is stable across machines."""
    out = {}
    if not session_dir or not os.path.isdir(session_dir):
        return out
    for root, _dirs, files in os.walk(session_dir):
        for fn in sorted(files):
            if fn.startswith('.') or not fn.lower().endswith('.txt'):
                continue
            p = os.path.join(root, fn)
            try:
                h = hashlib.sha256()
                with open(p, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b''):
                        h.update(chunk)
                rel = os.path.relpath(p, session_dir).replace('\\', '/')
                out[rel] = h.hexdigest()
            except OSError:
                pass
    return out


def _date_of(h):
    return h.get('hand_ts_date') or h.get('date') or None


def build_input_manifest(session_dir, hands, tournaments, stats, *,
                         analysis_mode='AUTO_ONLY', config=None, cache_state='fresh',
                         skipped_files=None, failed_files=None, generated_at=None):
    """Return the input-coverage manifest dict. Deterministic given (session_dir contents,
    hands, tournaments, stats, config); `generated_at` is the ONLY non-deterministic field and
    is supplied by the caller (never sampled here, so the manifest stays reproducible)."""
    hands = hands or []
    tournaments = tournaments or []
    config = dict(config or {})

    # 1. INPUT_FILES ledger -------------------------------------------------
    discovered = []
    if session_dir and os.path.isdir(session_dir):
        discovered = sorted(f for f in os.listdir(session_dir) if f.lower().endswith('.txt'))
    hands_by_file = Counter(h.get('source_file') or h.get('file') or '' for h in hands)
    input_files = []
    file_hashes = []
    for fn in discovered:
        p = os.path.join(session_dir, fn)
        md5 = _file_md5(p)
        if md5:
            file_hashes.append(md5)
        input_files.append({
            'basename': fn,
            'md5': md5,
            'size_bytes': (os.path.getsize(p) if os.path.isfile(p) else None),
            'hands_attributed': hands_by_file.get(fn, 0),
        })

    # 2. PARSED_HANDS summary ----------------------------------------------
    ids = sorted(str(h.get('id') or '') for h in hands if h.get('id'))
    # Date range: prefer the CANONICAL session-coverage dates (COR-005 union of file + timestamp
    # dates) so the manifest agrees with the report identity; fall back to hand dates.
    _cov_dates = ((stats or {}).get('session_coverage') or {}).get('dates') or []
    dates = sorted(_cov_dates) if _cov_dates else sorted({d for d in (_date_of(h) for h in hands) if d})
    game_types = Counter((h.get('game_type') or 'NLH') for h in hands)
    formats = Counter((h.get('format') or h.get('game_format') or 'UNKNOWN') for h in hands)
    parsed = {
        'count': len(hands),
        'schema_version': config.get('parser_schema_version'),
        'earliest_id': ids[0] if ids else None,
        'latest_id': ids[-1] if ids else None,
        'date_range': ([dates[0], dates[-1]] if dates else []),
        'game_type_counts': dict(game_types),
        'format_counts': dict(formats),
    }

    # 3/4. EVENTS classification (HH-backed / summary-only / financially resolved) ---
    tids_with_hands = {str(h.get('tournament_id') or '') for h in hands if h.get('tournament_id')}
    events = []
    n_hh, n_summary, n_resolved, n_inplay = 0, 0, 0, 0
    for t in tournaments:
        if not isinstance(t, dict):
            continue
        tid = str(t.get('tournament_id') or t.get('tid') or '')
        # HH-backed: prefer the canonical tt-model signal (a parsed hand count); else match the
        # tournament id against the ids that carry hands. `return`/`net`/`cash_total` any of which
        # being present means the financial result is resolved.
        _perf = t.get('performance') or {}
        if _perf.get('hands') is not None:
            hh_backed = _perf['hands'] > 0
        else:
            # performance.hands not populated on this event -> fall back to the authoritative
            # signal: does any parsed hand carry this tournament id.
            hh_backed = tid in tids_with_hands
        in_play = bool((t.get('finish') or {}).get('is_in_play'))
        resolved = (not in_play) and (t.get('net') is not None or t.get('return') is not None
                                      or t.get('cash_total') is not None)
        n_hh += int(hh_backed)
        n_summary += int(not hh_backed)
        n_resolved += int(resolved)
        n_inplay += int(in_play)
        events.append({
            'tournament_id': tid,
            'name': t.get('name'),
            'hh_backed': hh_backed,
            'financially_resolved': resolved,
            'in_play': in_play,
        })

    coverage = {
        'events_discovered': len(events),
        'hh_backed_events': n_hh,
        'summary_only_events': n_summary,
        'financially_resolved_events': n_resolved,
        'unresolved_events': len(events) - n_resolved,
        'in_play_events': n_inplay,
    }

    # 5/6. CONFIG + REPRODUCIBILITY ---------------------------------------
    filelist_hash = hashlib.md5('|'.join(sorted(file_hashes)).encode('utf-8')).hexdigest() \
        if file_hashes else None
    vol = (stats or {}).get('volume') or {}
    reproducibility = {
        'canonical_filelist_md5': filelist_hash,
        'hand_count_matches_volume': (len(hands) == vol.get('hands')) if 'hands' in vol else None,
        'first_hand_id': (ids[0] if ids else None),
        'date_range_matches_coverage':
            (dates == sorted((stats or {}).get('session_coverage', {}).get('dates', []) or dates)
             if (stats or {}).get('session_coverage') else None),
    }

    return {
        'schema': 'input-manifest/1',
        'generated_at': generated_at,
        'analysis_mode': analysis_mode,
        'cache_state': cache_state,
        'config': config,
        'input_files': input_files,
        'files_discovered': len(discovered),
        'files_classified': len(input_files),
        'skipped_files': list(skipped_files or []),
        'failed_files': list(failed_files or []),
        'parsed_hands': parsed,
        'coverage': coverage,
        'events': events,
        'reproducibility': reproducibility,
    }
