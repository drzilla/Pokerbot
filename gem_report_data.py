#!/usr/bin/env python3
"""
GEM Report Data Generator v7.12
================================
Pre-stages ALL data needed for report writing into gem_report_data.json.
Eliminates manual querying of gem_hands.json during report generation.

INTEGRATION: Add to gem_analyzer.py main block:
    from gem_report_data import generate_report_data
    report_data = generate_report_data(stats, hands, SESSION_DIR, session_history_path)
    with open('/home/claude/gem_report_data.json', 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, default=str)

Also auto-generates the GTO Wizard export file.
"""

import re, os, json
from collections import defaultdict
from gem_parser import normalize_hand, RANK_NUM

# ============================================================
# A3: Source-aware appendix collector
# ============================================================

class AppendixCollector:
    """Tracks which hand IDs should get appendix articles, with source attribution.
    Replaces 8 scattered appendix_hand_ids_all extension blocks."""

    def __init__(self):
        self._entries = {}       # hid → {source, reason, priority}
        self._full_ids = set()   # IDs that get rich (XIV.A) rendering

    def add(self, hand_id, source, reason='', priority=50):
        if not hand_id:
            return
        existing = self._entries.get(hand_id)
        if not existing or priority > existing['priority']:
            self._entries[hand_id] = {
                'source': source, 'reason': reason, 'priority': priority
            }

    def add_full(self, hand_id, source, reason=''):
        """Add with rich rendering (XIV.A)."""
        self.add(hand_id, source, reason, priority=90)
        if hand_id:
            self._full_ids.add(hand_id)

    def hand_ids(self):
        return sorted(self._entries.keys())

    def full_ids(self):
        return sorted(self._full_ids)

    def explain(self, hand_id):
        return self._entries.get(hand_id)

    def sources_summary(self):
        from collections import Counter
        return Counter(e['source'] for e in self._entries.values())

    def __len__(self):
        return len(self._entries)

    def __contains__(self, hand_id):
        return hand_id in self._entries


# ============================================================
# HELPER: Analyst file resolution (Fix B — v7.99.26)
# ============================================================

# Module-level cache: set by gem_analyzer.py after resolution so that
# internal _maybe_load_analyst_commentary calls (which run during
# generate_report_data, BEFORE analyst_commentary is set on rd) use
# the same resolved path. None = not yet resolved.
_ANALYST_FILE_OVERRIDE = None

def _resolve_analyst_file(date_range, explicit_path=None):
    """Locate session_analysis_<date_range>.json via a search order.

    Search order:
      1. explicit_path (--analyst-file CLI argument) — if given and exists
      2. Working directory (where gem_run.py was invoked from)
      3. /mnt/user-data/outputs/
      4. /home/claude/

    If multiple session_analysis_*.json files match in a directory, prefer
    exact date-range match and warn on ambiguity.

    Returns (resolved_path_or_None, search_log_list).
    search_log is a list of strings describing what was tried — always
    populated so callers can print diagnostics.
    """
    import glob as _glob_mod
    canonical_name = f'session_analysis_{date_range}.json'
    log = []

    # 1. Explicit path
    if explicit_path:
        if os.path.isfile(explicit_path):
            log.append(f"  ✓ --analyst-file: {explicit_path}")
            return explicit_path, log
        else:
            log.append(f"  ✗ --analyst-file: {explicit_path} (not found)")

    # 2-4. Search directories in order
    search_dirs = [
        ('working directory', os.getcwd()),
        ('/mnt/user-data/outputs', '/mnt/user-data/outputs'),
        ('/home/claude', '/home/claude'),
    ]
    for label, d in search_dirs:
        if not os.path.isdir(d):
            log.append(f"  — {label}: {d} (directory not found)")
            continue
        # v8.3.1: try exact date-only name first, then player-named variants
        exact = os.path.join(d, canonical_name)
        if os.path.isfile(exact):
            log.append(f"  ✓ {label}: {exact}")
            return exact, log
        # Try session_analysis_{player}_{date_range}.json (from --name flag)
        # v8.7.8 FIX: skip *_TEMPLATE* files — they're auto-generated pre-fills
        # that should never be auto-loaded as the real analyst pass.
        player_matches = [p for p in _glob_mod.glob(
            os.path.join(d, f'session_analysis_*_{date_range}.json'))
            if '_TEMPLATE' not in os.path.basename(p)]
        if player_matches:
            # Prefer the most recently modified if multiple players
            best = max(player_matches, key=os.path.getmtime)
            log.append(f"  ✓ {label}: {best} (player-named match)")
            return best, log
        # Check for any glob matches (date overlap / partial match)
        matches = [p for p in _glob_mod.glob(
            os.path.join(d, 'session_analysis_*.json'))
            if '_TEMPLATE' not in os.path.basename(p)]
        if matches:
            # Also try matching just the date portion inside filenames
            for m in sorted(matches, key=os.path.getmtime, reverse=True):
                _bn = os.path.basename(m)
                if date_range in _bn:
                    log.append(f"  ✓ {label}: {m} (date substring match)")
                    return m, log
            log.append(f"  — {label}: {canonical_name} not found, but "
                       f"{len(matches)} other session_analysis_*.json "
                       f"file(s) present: {', '.join(os.path.basename(m) for m in matches[:5])}"
                       f"{' …' if len(matches) > 5 else ''}")
        else:
            log.append(f"  — {label}: {d} (no session_analysis files)")

    return None, log


# ============================================================
# HELPER: Extract raw hand history from HH files
# ============================================================
def _maybe_load_analyst_commentary(stats):
    """Load analyst commentary JSON if it exists for this session date.

    Used by the candidate augmentation step (v7.43) — runs BEFORE the
    analyzer stitches commentary into report_data, so we read directly
    via the search-order resolution.

    Uses _ANALYST_FILE_OVERRIDE (set by gem_analyzer.py after resolution)
    so all internal calls use the same resolved path.
    """
    try:
        date_compact = stats.get('volume', {}).get('date_range', '')
        if not date_compact:
            return {}
        path, _log = _resolve_analyst_file(date_compact, _ANALYST_FILE_OVERRIDE)
        if not path:
            return {}
        import json as _json
        with open(path) as f:
            return _json.load(f)
    except Exception:
        return {}


def _extract_raw_hh(hand_ids, hh_dir):
    """Search raw HH files for specific hand IDs, return {id: raw_text}."""
    found = {}
    if not os.path.isdir(hh_dir):
        return found
    for fn in os.listdir(hh_dir):
        fp = os.path.join(hh_dir, fn)
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, encoding='utf-8', errors='replace') as f:
                content = f.read()
        except:
            continue
        for hid in hand_ids:
            if hid in content and hid not in found:
                pattern = rf'(Poker Hand #{re.escape(hid)}:.*?)(?=Poker Hand #|\Z)'
                m = re.search(pattern, content, re.DOTALL)
                if m:
                    found[hid] = m.group(1).strip()
    return found


# ============================================================
# v7.45 (Ron 2026-05-11): RICH SEAT/ACTION PARSING
# ============================================================
# Renderer needs stack depths, bet sizes, and bounty coverage in the
# appendix preflop action display. The structured hands.json `pf_sequence`
# only has "POSITION:action" without amounts or stacks. So we parse the
# raw HH text once per appendix hand and stash the result on rd.

_POS_BY_SIZE = {
    9: ['SB','BB','UTG','UTG+1','MP','HJ','CO','BTN'],
    8: ['SB','BB','UTG','UTG+1','MP','HJ','CO','BTN'],
    7: ['SB','BB','UTG','MP','HJ','CO','BTN'],
    6: ['SB','BB','UTG','MP','CO','BTN'],
    5: ['SB','BB','UTG','CO','BTN'],
    4: ['SB','BB','UTG','BTN'],
    3: ['SB','BB','BTN'],
    2: ['BTN/SB','BB'],
}


def _seats_to_positions(seat_lines, btn_seat, n_active):
    """seat_lines: list of (seat_num, name, stack_chips). Returns
    {seat_num: position_label} dict mapped by walking from BTN+1 (SB)."""
    seats_sorted = sorted(seat_lines, key=lambda x: x[0])
    seat_nums = [s[0] for s in seats_sorted]
    if btn_seat not in seat_nums:
        return {}
    btn_idx = seat_nums.index(btn_seat)
    n_seats = len(seat_nums)
    template = _POS_BY_SIZE.get(n_active, _POS_BY_SIZE[8])
    seat_to_pos = {}
    for i, pos in enumerate(template):
        seat = seat_nums[(btn_idx + 1 + i) % n_seats]
        seat_to_pos[seat] = pos
    if n_active >= 3:
        seat_to_pos[btn_seat] = 'BTN'
    return seat_to_pos


def _build_seat_info_from_hand(hand_dict):
    """A2b-4: Build seat info from the parsed hand dict (action_ledger path).
    Avoids re-reading raw HH files. Returns the same structure as
    _parse_hand_seat_info for backward compat."""
    if not hand_dict or not hand_dict.get('action_ledger'):
        return None  # fall back to raw_hh path
    bb = hand_dict.get('bb_blind', 1) or 1
    hero = hand_dict.get('hero', 'Hero')
    result = {
        'bb_size_chips': bb,
        'hero_stack_chips': (hand_dict.get('stack_bb', 0) or 0) * bb,
        'seats': [],
        'actions': {'preflop': [], 'flop': [], 'turn': [], 'river': []},
        'is_bounty': hand_dict.get('format', '') == 'BOUNTY',
        'level': hand_dict.get('level'),
        'showdown': {},
    }
    # Populate showdown reveals from raw_text if available
    _raw = hand_dict.get('raw_text', '')
    if _raw and hand_dict.get('went_to_sd'):
        _villains = hand_dict.get('villains', {}) or {}
        _pos_map = {hero: hand_dict.get('position', '?')}
        for _vname, _vinfo in _villains.items():
            _pos_map[_vname] = _vinfo.get('position', _vname)
        _stacks_behind = hand_dict.get('stacks_behind', {}) or {}
        for _sbp in _stacks_behind:
            _pos_map.setdefault(_sbp, _sbp)
        # v8.12.4 (QA item 9, TM6060369292): derive per-player outcome from
        # the SUMMARY block. Without it, downstream "winning villain" filters
        # (cooler table) matched nothing and fell back to joining EVERY shown
        # hand — including a folded player's voluntary one-card show.
        _outcome_by_name = {}
        for _om in re.finditer(
                r'^Seat \d+: (\S+).*?showed \[[^\]]+\] and (won|lost)',
                _raw, re.MULTILINE):
            _outcome_by_name[_om.group(1)] = _om.group(2)
        for _sm in re.finditer(r'(\S+):\s+show(?:s|ed)\s+\[([^\]]+)\]', _raw):
            _sname = _sm.group(1)
            _scards = _sm.group(2).split()
            # Find position for this player
            _spos = _pos_map.get(_sname, _sname)
            result['showdown'][_spos] = {
                'cards': _scards,
                'is_hero': _sname == hero,
                'outcome': _outcome_by_name.get(_sname, ''),
                # voluntary partial show (e.g. "shows [5s]") — not a
                # showdown matchup hand
                'partial': len(_scards) < 2,
            }
    # Build seats from stacks_behind + hero
    _hero_stack = hand_dict.get('stack_bb', 0) or 0
    result['seats'].append({
        'name': hero, 'position': hand_dict.get('position', '?'),
        'stack_chips': _hero_stack * bb, 'stack_bb': _hero_stack,
        'is_hero': True, 'covers_hero': False, 'hero_covers': False,
    })
    for _pos, _stk in (hand_dict.get('stacks_behind', {}) or {}).items():
        result['seats'].append({
            'name': _pos, 'position': _pos,
            'stack_chips': (_stk or 0) * bb, 'stack_bb': _stk or 0,
            'is_hero': False,
            'covers_hero': (_stk or 0) > _hero_stack,
            'hero_covers': _hero_stack > (_stk or 0),
        })
    # Build actions from action_ledger
    # CP22: use seat_stacks_bb_all (parser-provided full seat list) so
    # folders' stacks are available without re-parsing raw_text.
    _all_stacks = hand_dict.get('seat_stacks_bb_all', {}) or {}
    for _pos, _sbb in _all_stacks.items():
        if not any(s.get('position') == _pos or s.get('name') == _pos
                   for s in result['seats']):
            result['seats'].append({
                'name': _pos, 'position': _pos,
                'stack_chips': (_sbb or 0) * bb, 'stack_bb': _sbb or 0,
                'is_hero': False, 'covers_hero': False, 'hero_covers': False,
            })
    # Fallback: parse from raw_text if seat_stacks_bb_all is empty
    if not _all_stacks:
        _raw = hand_dict.get('raw_text', '')
        if _raw:
            import re as _re_seats
            for _sm in _re_seats.finditer(r'Seat \d+: (\S+) \(([\d,]+(?:\.\d+)?)\s+in chips\)', _raw):
                _sn = _sm.group(1)
                _sc = float(_sm.group(2).replace(',', ''))
                _sbb = round(_sc / bb, 1) if bb > 0 else 0
                if not any(s.get('name') == _sn for s in result['seats']):
                    result['seats'].append({
                        'name': _sn, 'position': '?',
                        'stack_chips': _sc, 'stack_bb': _sbb,
                        'is_hero': False, 'covers_hero': False, 'hero_covers': False,
                    })
    # Look up starting stacks by player name/position for the grid display
    _stack_by_player = {}
    _stack_by_pos = {}
    for _seat in result['seats']:
        _stack_by_player[_seat.get('name', '')] = _seat.get('stack_bb', 0)
        if _seat.get('position', '?') != '?':
            _stack_by_pos[_seat.get('position')] = _seat.get('stack_bb', 0)
    # Also use seat_stacks_bb_all (parser-provided, position-keyed, complete)
    for _pos_k, _stk_v in (hand_dict.get('seat_stacks_bb_all', {}) or {}).items():
        if _pos_k not in _stack_by_pos and _stk_v:
            _stack_by_pos[_pos_k] = _stk_v
    for _li, a in enumerate(hand_dict.get('action_ledger', [])):
        st = a.get('street', 'preflop')
        if st in result['actions']:
            _player = a.get('player', '')
            _pos = a.get('position', '')
            _stk = (_stack_by_player.get(_player)
                    or _stack_by_pos.get(_pos) or 0)
            result['actions'][st].append({
                'name': _player,
                'position': _pos,
                'action': a.get('action', ''),
                'amount_chips': (a.get('amount_bb', 0) or 0) * bb,
                'amount_bb': a.get('amount_bb', 0),
                'all_in': a.get('is_all_in', False),
                'is_hero': _player == hero,
                'stack_bb': round(_stk, 1),
                # REV16 §6: the ledger index lets the grid read the ONE full-history per-action
                # canonical replay (physical chips / live level) for EVERY player row, Hero + villain.
                'ledger_index': _li,
            })
    return result


def _parse_hand_seat_info(raw_hh, hero_name=None):
    """Parse a raw HH text. Returns dict with:
      bb_size_chips, hero_stack_chips, is_bounty, level,
      seats: [{seat, name, stack_chips, stack_bb, position, covers_hero, hero_covers}],
      actions: {street: [{name, position, stack_bb, action, amount_chips, amount_bb, all_in}]}.

    Used by appendix renderer to enrich preflop action display per Ron's
    2026-05-11 ask: include stacks + bet sizes + bounty-coverage hints.

    hero_name: if None, auto-derived from 'Dealt to <name> [' in the HH text.
    """
    # §4.1 self-healing: derive hero from HH if not explicitly provided
    if hero_name is None and raw_hh:
        _hm = re.search(r'Dealt to (\S+) \[', raw_hh)
        hero_name = _hm.group(1) if _hm else 'Hero'
    elif hero_name is None:
        hero_name = 'Hero'
    result = {
        'bb_size_chips': None, 'hero_stack_chips': None,
        'seats': [], 'actions': {'preflop':[],'flop':[],'turn':[],'river':[]},
        'is_bounty': False, 'level': None,
        # B54 (v7.47, Ron 2026-05-12): showdown reveals — {position: [cards]}
        # for any seat that showed at SD. Used by appendix to render villain
        # hole cards next to "Result: Lost SD" so the reader can sanity-check
        # the verdict against villain's actual hand.
        'showdown': {},
    }
    if not raw_hh:
        return result
    first_line = raw_hh.split('\n', 1)[0]
    if 'Bounty' in first_line or '[Bounty' in first_line:
        result['is_bounty'] = True
    m_lvl = re.search(r'Level(\d+)\(', raw_hh)
    if m_lvl:
        result['level'] = int(m_lvl.group(1))

    btn_match = re.search(r'Seat #(\d+) is the button', raw_hh)
    if not btn_match:
        return result
    btn_seat = int(btn_match.group(1))

    seat_re = re.compile(r'^Seat (\d+): (\S+) \(([\d,]+) in chips\)', re.MULTILINE)
    seats_raw = []
    for m in seat_re.finditer(raw_hh):
        seats_raw.append((int(m.group(1)), m.group(2), int(m.group(3).replace(',', ''))))

    n_active = len(seats_raw)
    seat_to_pos = _seats_to_positions(seats_raw, btn_seat, n_active)

    bb_match = re.search(r'\S+: posts big blind ([\d,]+)', raw_hh)
    if bb_match:
        result['bb_size_chips'] = int(bb_match.group(1).replace(',', ''))
    bb_size = result['bb_size_chips'] or 1

    name_to_pos = {}
    name_to_stack = {}
    hero_stack = 0
    for seat_num, name, stack in seats_raw:
        if name == hero_name:
            hero_stack = stack
    result['hero_stack_chips'] = hero_stack

    seats_out = []
    for seat_num, name, stack in seats_raw:
        pos = seat_to_pos.get(seat_num, '?')
        is_hero = (name == hero_name)
        # Bounty coverage: Hero covers villain if Hero's stack >= villain's stack
        covers_hero = (not is_hero) and (stack > hero_stack)
        hero_covers = (not is_hero) and (stack <= hero_stack)
        name_to_pos[name] = pos
        name_to_stack[name] = stack
        seats_out.append({
            'seat': seat_num, 'name': name,
            'stack_chips': stack, 'stack_bb': stack / bb_size if bb_size else 0,
            'position': pos, 'is_hero': is_hero,
            'covers_hero': covers_hero, 'hero_covers': hero_covers,
        })
    result['seats'] = seats_out

    sections = re.split(r'\*\*\* (HOLE CARDS|FLOP|TURN|RIVER|SUMMARY|SHOWDOWN) \*\*\*', raw_hh)
    cur_street = None
    for sec in sections:
        if sec == 'HOLE CARDS': cur_street = 'preflop'; continue
        if sec == 'FLOP': cur_street = 'flop'; continue
        if sec == 'TURN': cur_street = 'turn'; continue
        if sec == 'RIVER': cur_street = 'river'; continue
        if sec in ('SUMMARY','SHOWDOWN'): cur_street = None; continue
        if cur_street and sec:
            for line in sec.split('\n'):
                m = re.match(
                    r'^(\S+): (folds|checks|calls|bets|raises)'
                    r'( (\d[\d,]*)( to (\d[\d,]*))?( and is all-in)?)?',
                    line.strip())
                if not m: continue
                name = m.group(1)
                if name in ('Dealt', 'Uncalled'): continue
                action = m.group(2)
                amt_str = m.group(6) or m.group(4) or '0'
                amt = int(amt_str.replace(',', '')) if amt_str else 0
                all_in = bool(m.group(7))
                result['actions'][cur_street].append({
                    'name': name,
                    'position': name_to_pos.get(name, '?'),
                    'stack_chips': name_to_stack.get(name, 0),
                    'stack_bb': name_to_stack.get(name, 0) / bb_size if bb_size else 0,
                    'is_hero': (name == hero_name),
                    'action': action,
                    'amount_chips': amt,
                    'amount_bb': amt / bb_size if bb_size else 0,
                    'all_in': all_in,
                })

    # B54 (v7.47): parse showdown reveals from SUMMARY block.
    # Format: "Seat N: <name> (position) showed [Xx Yy] and (won|lost) ..."
    sd_re = re.compile(
        r'^Seat \d+: (\S+).*?showed \[([2-9TJQKA][cdhs] [2-9TJQKA][cdhs])\]'
        r' and (won|lost)',
        re.MULTILINE)
    for m in sd_re.finditer(raw_hh):
        name = m.group(1)
        cards = m.group(2).split()
        result['showdown'][name_to_pos.get(name, '?')] = {
            'cards': cards,
            'is_hero': (name == hero_name),
            'outcome': m.group(3),
        }
    return result


# ============================================================
# HELPER: Parse buy-ins from filenames
# ============================================================
def _parse_buyins(hh_dir, tournaments):
    """Extract buy-ins from filenames and compute averages.

    v7.43 fix: previous parser took the first 1-999 number in the cleaned
    filename, which is wrong for two filename patterns:
      - Network prefix "XX-Y NNN" e.g. "64-L 25 Saturday Secret KO":
        first number was 64 (the network ID), should be 25 (the actual buy-in).
      - GTD-only suffix "200K GTD" e.g. "Weekender Bounty Closer, 200K GTD":
        first number is 200 (guarantee), filename has no actual buy-in.
    """
    # Known tournaments with no buy-in token in filename — fall back to map.
    # Add entries here as they're discovered. Keys are substring matches on
    # the tournament name.
    KNOWN_BUYIN_OVERRIDES = {
        'Weekender Bounty Closer': 25,  # Stage 1H per Ron 2026-05-09
    }

    # Step 1: Parse buy-in from each filename
    # B-AVIEL BUG-1 (2026-06-01): match decimals (8.88, 10.80, 5.50) not just
    # integers.  Regex now grabs "N.NN" first, plain "N" second.
    fn_buyins = {}
    if os.path.isdir(hh_dir):
        for fn in os.listdir(hh_dir):
            # B-V10 (2026-06-01): only process .txt HH files — skip analyst
            # JSON, game summaries, ZIPs, and any other non-HH files that may
            # live in the input dir (an analyst .json was parsed as a $601
            # phantom tournament).
            if not fn.lower().endswith('.txt'):
                continue
            cleaned = re.sub(r'^GG\d{8}(-\d+)?\s*-\s*', '', fn)
            cleaned = re.sub(r'^Tournament\s*#\d+\s*-\s*', '', cleaned)
            # v7.43: strip leading network prefix "XX-Y" (e.g. 64-L, 67-H, 63-M)
            cleaned_for_parse = re.sub(r'^\d+-[A-Z]\s+', '', cleaned)
            # v7.43: strip K/M-suffixed numbers (GTD guarantees, not buy-ins)
            cleaned_for_parse = re.sub(r'\b\d+\.?\d*[KM]\b\s*(?:GTD)?', '', cleaned_for_parse)
            # v7.43: strip Stage/Day identifiers like "Stage 1H", "Day 2A",
            # "1L", "1H" — single-digit followed by single uppercase letter.
            # Avoid stripping legitimate buy-ins; "5K" is already handled above.
            cleaned_for_parse = re.sub(r'\b\d+[A-Z]\b', '', cleaned_for_parse)
            # First plausible buy-in: 1-999 range. Higher numbers are dates/GTD/etc.
            buyin_found = None
            for s_tok in re.findall(r'(\d+\.\d+|\d+)', cleaned_for_parse):
                n = round(float(s_tok), 2)
                if 1 <= n <= 999:
                    buyin_found = n
                    break
            # Known-tournament override fallback
            if buyin_found is None:
                for keyword, override_buyin in KNOWN_BUYIN_OVERRIDES.items():
                    if keyword in fn:
                        buyin_found = override_buyin
                        break
            if buyin_found is not None:
                fn_buyins[fn] = buyin_found

    # Step 2: Group files by tournament name
    # B-AVIEL BUG-2 (2026-06-01): the old tname[:20] prefix match collapsed
    # distinct "Bounty Hunters Sunday ..." tournaments into one bucket.
    # Pass 1 = exact full-name match (case-insensitive).
    # Pass 2 = full-containment fallback, guarded by min-length >= 20.
    tourney_bullets = defaultdict(lambda: {'buyin': 0, 'bullets': 0})
    for fn, bi in fn_buyins.items():
        name_part = re.sub(r'^GG\d+-\d+ - ', '', fn).replace('.txt', '').strip()
        matched = False
        # Pass 1: exact match (case-insensitive)
        for t in tournaments:
            tname = t.get('name', '')
            if tname.lower() == name_part.lower():
                tourney_bullets[tname]['buyin'] = bi
                tourney_bullets[tname]['bullets'] += 1
                matched = True
                break
        if not matched:
            # Pass 2: full-containment, guarded by min-length >= 20
            for t in tournaments:
                tname = t.get('name', '')
                if min(len(tname), len(name_part)) >= 20 and (
                        tname in name_part or name_part in tname):
                    tourney_bullets[tname]['buyin'] = bi
                    tourney_bullets[tname]['bullets'] += 1
                    matched = True
                    break
        if not matched:
            tourney_bullets[name_part]['buyin'] = bi
            tourney_bullets[name_part]['bullets'] += 1

    total = sum(d['buyin'] * d['bullets'] for d in tourney_bullets.values())
    n_bullets = sum(d['bullets'] for d in tourney_bullets.values())
    avg = round(total / n_bullets, 2) if n_bullets > 0 else 0

    breakdown = [{'tournament': t, 'buyin': d['buyin'], 'bullets': d['bullets'],
                  'cost': round(d['buyin'] * d['bullets'], 2)}
                 for t, d in sorted(tourney_bullets.items(), key=lambda x: -x[1]['buyin'])]

    return {'avg_buyin': avg, 'total_invested': total, 'n_bullets': n_bullets,
            'breakdown': breakdown}


# ============================================================
# B47 (v7.52, Ron 2026-05-18): USD overlay — parse GG game summaries
# ============================================================
def _parse_game_summaries_usd(hh_dir, hands):
    """Parse GG game-summary files to extract per-tournament USD net.

    Game summaries look like:
        Tournament #283301262, 135-H: $250 Saturday Speed Zone [Hyper 5-Max], Hold'em No Limit
        Buy-in: $230+$20
        473 Players
        Total Prize Pool: $108,790
        Tournament started 2026/05/17 04:30:00
        335th : Hero, $0
        You finished the tournament in 335th place.
        You made 2 re-entries and received a total of $0.

    Looks in hh_dir, hh_dir/../game_summaries, or hh_dir/game_summaries.

    Returns dict with:
      - per_tournament: list of {tid, name, buyin, bullets, cost, cash, net, ...}
      - totals: {n_tournaments, n_bullets, total_cost, total_cash, total_net,
                 roi_pct, biggest_loss_usd, biggest_win_usd}
      - hh_intersect_totals: subset of tournaments whose IDs match the HH session,
        with the same fields. Use this for HH-session-specific USD reporting.
      - status: 'parsed' (success), 'no_summaries_found', or 'parse_error'
    """
    # Find candidate dirs — preference order:
    #   1. hh_dir itself (most specific)
    #   2. hh_dir/game_summaries subdirectory (nested)
    #   3. sibling game_summaries (only as fallback when neither above has any)
    # This avoids cross-contaminating sessions when a parent dir holds summaries
    # for multiple sessions. Caller can co-locate summaries with HHs to get the
    # exact session match.
    candidates = []
    has_summaries_in_hh = False
    if hh_dir and os.path.isdir(hh_dir):
        # Check hh_dir itself first
        for fn in os.listdir(hh_dir):
            if fn.endswith('.txt'):
                fp = os.path.join(hh_dir, fn)
                try:
                    with open(fp, encoding='utf-8', errors='replace') as f:
                        head = f.read(500)
                    if 'Total Prize Pool' in head:
                        has_summaries_in_hh = True
                        break
                except Exception:
                    continue
        if has_summaries_in_hh:
            candidates.append(hh_dir)
        # Nested game_summaries subdir
        for sub in ('game_summaries', 'Game Summaries', 'summaries'):
            sub_path = os.path.join(hh_dir, sub)
            if os.path.isdir(sub_path):
                candidates.append(sub_path)
                has_summaries_in_hh = True
        # Sibling fallback ONLY if HH dir is empty of summaries
        if not has_summaries_in_hh:
            parent = os.path.dirname(os.path.abspath(hh_dir))
            for sib in ('game_summaries', 'Game Summaries', 'summaries'):
                sib_path = os.path.join(parent, sib)
                if os.path.isdir(sib_path):
                    candidates.append(sib_path)
                    has_summaries_in_hh = True
        # v8.12.5 (QA item 17): content-sniffed sibling fallback. Session
        # uploads arrive as two zips extracted to arbitrarily-named sibling
        # folders (e.g. hh_20260610/a + hh_20260610/merged) — the name-based
        # candidates above never matched, so cash/ROI silently rendered
        # blank. Sniff each sibling dir (one level, bounded) for files whose
        # head carries 'Total Prize Pool' and accept the dir on first hit.
        if not has_summaries_in_hh:
            parent = os.path.dirname(os.path.abspath(hh_dir))
            try:
                _sibs = sorted(
                    d for d in os.listdir(parent)
                    if os.path.isdir(os.path.join(parent, d))
                    and os.path.abspath(os.path.join(parent, d))
                        != os.path.abspath(hh_dir))
            except Exception:
                _sibs = []
            for _sib in _sibs:
                _sp = os.path.join(parent, _sib)
                try:
                    _txts = [f for f in os.listdir(_sp)
                             if f.endswith('.txt')][:40]
                except Exception:
                    continue
                for _fn in _txts:
                    try:
                        with open(os.path.join(_sp, _fn), encoding='utf-8',
                                  errors='replace') as _fh:
                            if 'Total Prize Pool' in _fh.read(500):
                                candidates.append(_sp)
                                break
                    except Exception:
                        continue

    summary_files = []
    seen_basenames = set()
    for cand in candidates:
        for fn in os.listdir(cand):
            if not fn.endswith('.txt'):
                continue
            if fn in seen_basenames:
                continue  # dedup across candidate dirs
            seen_basenames.add(fn)
            fp = os.path.join(cand, fn)
            # Lightweight check: game summaries have "Total Prize Pool" line
            try:
                with open(fp, encoding='utf-8', errors='replace') as f:
                    head = f.read(500)
                if 'Total Prize Pool' in head or 'Buy-in:' in head:
                    summary_files.append(fp)
            except Exception:
                continue

    if not summary_files:
        return {'status': 'no_summaries_found', 'per_tournament': [],
                'totals': None, 'hh_intersect_totals': None}

    tournaments_parsed = []
    for fp in summary_files:
        try:
            with open(fp, encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            continue

        tid_m = re.search(r'Tournament #(\d+)', content)
        if not tid_m:
            continue
        tid = tid_m.group(1)

        # Buy-in components — sum all $X.XX values in the Buy-in line
        bi_m = re.search(r'Buy-in:\s*([\d$.+,]+)', content)
        buyin = 0.0
        buyin_parts = []
        if bi_m:
            parts = re.findall(r'\$?([\d.,]+)', bi_m.group(1))
            buyin_parts = [p for p in parts if p]
            try:
                buyin = sum(float(p.replace(',', '')) for p in parts if p)
            except ValueError:
                pass
        # B144 (Ron 2026-05-23): a 3-component buy-in ($prize+$fee+$bounty)
        # marks a bounty (PKO) tournament. In a bounty event cash_received
        # includes KO money, so "cash >= buyin" wrongly tags a bounty BUST
        # (deep run, no placement payout, KO money only) as ITM. Bounty ITM
        # must be placement-based instead — see the itm calc below.
        is_bounty = len(buyin_parts) >= 3

        name_m = re.search(r'Tournament #\d+,\s*([^,]+),', content)
        tname = name_m.group(1).strip() if name_m else ''

        start_m = re.search(r'Tournament started\s+(\d{4}/\d{2}/\d{2})', content)
        start_date = start_m.group(1).replace('/', '-') if start_m else ''

        re_m = re.search(r'You made (\d+) re-entr', content)
        re_entries = int(re_m.group(1)) if re_m else 0
        bullets = 1 + re_entries

        # Cash received: explicit "You received a total of..." or fallback to
        # the "Nth : Hero, $X" line.
        # B132 (Ron 2026-05-20): match BOTH "You received a total of" and the
        # re-entry phrasing "...and received a total of"; the old (?:\.|$)
        # terminator truncated cents ("$542.59." -> "$542" -> $0.59 lost).
        # Anchor on an optional sentence-final period at end-of-line instead.
        cash_received = 0.0
        ticket_value = 0.0
        seats_won = 0
        advanced = False
        cm = re.search(r'received a total of\s+(.+?)\.?\s*$', content, re.M)
        cash_source_line = cm.group(1).strip() if cm else None
        if cash_source_line is None:
            hm = re.search(r'\d+\w*\s*:\s*Hero,\s*(.+?)(?:\n|$)', content)
            cash_source_line = hm.group(1).strip() if hm else ''
        if cash_source_line:
            if 'chips' in cash_source_line:
                cash_received = 0
                # v8.12.5 (QA item 8): a chips payout = flighted advancement
                # (Hero bagged a stack for a later Day/Stage). Neither a bust
                # nor a cash — label it instead of letting the tournament
                # read as an unexplained $0.
                advanced = True
            elif any(k in cash_source_line for k in ('Entry', 'Ticket', 'Seat')):
                tm = re.search(r'\$?([\d.,]+)\s*(?:Entry|Ticket|Seat)', cash_source_line)
                if tm:
                    try:
                        ticket_value = float(tm.group(1).replace(',', ''))
                        seats_won = 1
                    except ValueError:
                        pass
            else:
                cm2 = re.search(r'\$?([\d.,]+)', cash_source_line)
                if cm2:
                    try:
                        cash_received = float(cm2.group(1).replace(',', ''))
                    except ValueError:
                        pass

        pm = re.search(r'(\d+)\w*\s*:\s*Hero', content)
        place = int(pm.group(1)) if pm else 0
        tp_m = re.search(r'(\d+)\s+Players', content)
        total_players = int(tp_m.group(1)) if tp_m else 0

        is_sat = 'Satellite' in tname or 'MEGA' in tname
        cost = buyin * bullets
        cash_total = cash_received + ticket_value
        net = cash_total - cost
        # B144: ITM definition.
        #  - satellite: won a seat/ticket.
        #  - bounty tournament: reached a PAID PLACEMENT — cash alone is
        #    unreliable because it includes KO money. Paid field ~ top 15%
        #    (ITM_PAID_FRACTION); a bust outside that is not ITM however much
        #    bounty money was collected. Falls back to cash>=buyin if the
        #    placement / field size could not be parsed.
        #  - non-bounty: cash_total >= buyin (cash comes only from placement).
        ITM_PAID_FRACTION = 0.15
        if seats_won > 0:
            itm = True
        elif is_bounty and place > 0 and total_players > 0:
            import math as _math
            paid_places = _math.ceil(total_players * ITM_PAID_FRACTION)
            itm = (place <= paid_places) and (cash_total > 0)
        else:
            itm = (cash_total >= buyin) or (seats_won > 0)

        tournaments_parsed.append({
            'tid': tid, 'name': tname, 'start_date': start_date,
            'buyin': round(buyin, 2), 'bullets': bullets, 'cost': round(cost, 2),
            'cash_received': round(cash_received, 2),
            'ticket_value': round(ticket_value, 2),
            'cash_total': round(cash_total, 2), 'net': round(net, 2),
            'seats_won': seats_won, 'is_sat': is_sat, 'itm': itm,
            'place': place, 'total_players': total_players,
            'advanced': advanced,
        })

    # Totals across all parsed summaries
    n_t = len(tournaments_parsed)
    n_b = sum(t['bullets'] for t in tournaments_parsed)
    tot_cost = sum(t['cost'] for t in tournaments_parsed)
    tot_cash = sum(t['cash_total'] for t in tournaments_parsed)
    # v8.14.3 Issue 1: expose the ticket portion of total_cash so the report can
    # visibly label the cash basis as cash + satellite ticket value.
    tot_ticket = sum(t.get('ticket_value', 0) for t in tournaments_parsed)
    tot_net = tot_cash - tot_cost
    roi = (tot_net / tot_cost * 100) if tot_cost > 0 else 0
    big_loss = min((t['net'] for t in tournaments_parsed), default=0)
    big_win = max((t['net'] for t in tournaments_parsed), default=0)
    big_loss_t = next((t for t in tournaments_parsed if t['net'] == big_loss), None)
    big_win_t = next((t for t in tournaments_parsed if t['net'] == big_win), None)

    totals = {
        'n_tournaments': n_t, 'n_bullets': n_b,
        'total_cost': round(tot_cost, 2), 'total_cash': round(tot_cash, 2),
        'total_ticket_value': round(tot_ticket, 2),   # v8.14.3 Issue 1: ticket portion of cash
        'total_net': round(tot_net, 2), 'roi_pct': round(roi, 1),
        'biggest_loss_usd': big_loss, 'biggest_win_usd': big_win,
        'biggest_loss_tournament': (big_loss_t['name'] if big_loss_t else ''),
        'biggest_win_tournament': (big_win_t['name'] if big_win_t else ''),
    }

    # HH-session intersection: only tournaments whose NAME appears in the HH hands.
    # Hands carry the tournament name (e.g. '131-M 55 Bounty Hunters Daily Main')
    # while summaries carry slight format variation ('131-M: $55 Bounty Hunters...').
    # Normalize aggressively before comparing: lowercase, strip $/colons/brackets,
    # collapse whitespace, then check token-set overlap.
    hh_tournament_names = set()
    for h in hands or []:
        v = h.get('tournament') if isinstance(h, dict) else None
        if v:
            hh_tournament_names.add(v.strip())

    def _normalize_name(name):
        """Aggressive normalize for matching. Returns a set of significant tokens."""
        norm = name.lower()
        # Strip $, :, brackets, commas, slashes
        norm = re.sub(r'[\$:,/\[\]()]', ' ', norm)
        # Strip 'world' OCR artifact (summaries sometimes say 'orld')
        norm = re.sub(r'\borld\b', 'world', norm)
        # Collapse whitespace
        norm = re.sub(r'\s+', ' ', norm).strip()
        # Tokenize; drop generic words and short numerics
        STOPWORDS = {'the', 'a', 'an', 'to', 'of', 'for', 'and', 'or',
                     'holdem', "hold'em", 'no', 'limit', 'nl', 'gtd',
                     'tickets', 'ticket', 'seats', 'seat'}
        tokens = set()
        for t in norm.split():
            if t in STOPWORDS:
                continue
            # Drop pure-numeric "1m" "10k" style guarantees
            if re.fullmatch(r'\d+[km]?', t) and len(t) <= 3:
                continue
            tokens.add(t)
        return tokens

    def _name_match(summary_name, hh_names):
        """Match by significant-token overlap (>=3 shared tokens or 60%+ overlap)."""
        s_tok = _normalize_name(summary_name)
        if not s_tok:
            return False
        for hn in hh_names:
            h_tok = _normalize_name(hn)
            if not h_tok:
                continue
            shared = s_tok & h_tok
            min_size = min(len(s_tok), len(h_tok))
            if min_size == 0:
                continue
            if len(shared) >= 3 or len(shared) / min_size >= 0.6:
                return True
        return False

    hh_t = [t for t in tournaments_parsed if _name_match(t['name'], hh_tournament_names)]
    if hh_t:
        hh_cost = sum(t['cost'] for t in hh_t)
        hh_cash = sum(t['cash_total'] for t in hh_t)
        hh_net = hh_cash - hh_cost
        hh_roi = (hh_net / hh_cost * 100) if hh_cost > 0 else 0
        hh_bullets = sum(t['bullets'] for t in hh_t)
        hh_big_loss = min((t['net'] for t in hh_t), default=0)
        hh_big_loss_t = next((t for t in hh_t if t['net'] == hh_big_loss), None)
        hh_big_win = max((t['net'] for t in hh_t), default=0)
        hh_big_win_t = next((t for t in hh_t if t['net'] == hh_big_win), None)
        # Concentration: top-3 cost tournaments share of total cost
        sorted_by_cost = sorted(hh_t, key=lambda t: -t['cost'])
        top3_cost = sum(t['cost'] for t in sorted_by_cost[:3])
        top3_cost_share = (top3_cost / hh_cost) if hh_cost > 0 else 0
        # And top-3 losers share of negative result
        sorted_by_loss = sorted(hh_t, key=lambda t: t['net'])
        top3_loss = sum(t['net'] for t in sorted_by_loss[:3] if t['net'] < 0)
        hh_intersect = {
            'n_tournaments': len(hh_t), 'n_bullets': hh_bullets,
            'total_cost': round(hh_cost, 2), 'total_cash': round(hh_cash, 2),
            'total_net': round(hh_net, 2), 'roi_pct': round(hh_roi, 1),
            'biggest_loss_usd': hh_big_loss,
            'biggest_loss_tournament': (hh_big_loss_t['name'] if hh_big_loss_t else ''),
            'biggest_win_usd': hh_big_win,
            'biggest_win_tournament': (hh_big_win_t['name'] if hh_big_win_t else ''),
            'top3_cost_share': round(top3_cost_share, 2),
            'top3_negative_net': round(top3_loss, 2),
            'tournaments': hh_t,
        }
    else:
        hh_intersect = None

    # v8.12.5 (QA item 8): reverse match — HH tournaments with NO summary
    # entry are UNRESOLVED (missing summary file, or a flight whose summary
    # belongs to a later day). Name them so the per-tournament P&L can say
    # "K of N unresolved" instead of leaving the reader to count.
    _summary_names = [t['name'] for t in tournaments_parsed]
    unresolved_hh = sorted(
        hn for hn in hh_tournament_names
        if not any(_name_match(sn, {hn}) for sn in _summary_names))
    advanced_list = [t['name'] for t in tournaments_parsed if t.get('advanced')]

    return {'status': 'parsed', 'per_tournament': tournaments_parsed,
            'totals': totals, 'hh_intersect_totals': hh_intersect,
            'unresolved_hh_tournaments': unresolved_hh,
            'advanced_tournaments': advanced_list}


# ============================================================
# HELPER: Load trend data from session history
# ============================================================
def _load_trend_data(csv_path, n=5):
    """Load last n sessions from session_history CSV for trend tracking.
    COR-001: rows are TYPE-COERCED at this load boundary (numeric columns -> float/int/None), so trend
    renderers never numeric-format a raw csv string (the production crash)."""
    if not csv_path or not os.path.exists(csv_path):
        return []
    from gem_csv_types import read_typed_csv
    rows = read_typed_csv(csv_path)
    # Return last n rows (most recent sessions)
    return rows[-n:] if len(rows) >= n else rows


# ============================================================
# MAIN: Generate report data
# ============================================================
LEAK_ALIASES = {
    # Normalize leak names to canonical forms
    'sb steal': 'SB Steal',
    'sb pot-entry': 'SB Pot-Entry',
    'sb bvb': 'SB BvB',
    'btn open': 'BTN Open',
    'btn regression': 'BTN Open',
    'btn < co': 'BTN Open',
    'co open': 'CO Open',
    'hu cbet': 'HU C-Bet',
    'hu cbet ip': 'HU C-Bet',
    'hu c-bet': 'HU C-Bet',           # B30: normalize hyphenated form (was → 'Hu C-Bet' via .title() fallback)
    'hu c-bet ip': 'HU C-Bet',
    'flop probe': 'Flop Probe',
    'mw cbet': 'MW C-Bet',
    'board-type cbet': 'Board Texture C-Bet',
    'river c-bet': 'River C-Bet',
    'river surrender': 'River Surrender',
    'non-sd win': 'Non-SD Win',
    'sd aggressor': 'SD Aggressor',
    'sd aggr': 'SD Aggressor',
    'vpip-pfr gap': 'VPIP-PFR Gap',
    'caller ip agg': 'Caller IP Agg',
    'pure bluff rate': 'Pure Bluff Rate',
    'regression under pressure': 'Regression Under Pressure',
    'unnecessary jam': 'Unnecessary Jam',
    'wide opens': 'Wide Opens',
    'trips vs flush': 'Trips vs Flush',
    'open-jam sizing': 'Open-Jam Sizing',
    'nit button/co': 'BTN/CO Nit',
}


def _normalize_leak(raw):
    """Normalize a leak string to a canonical name."""
    if not raw: return None
    raw_lower = raw.strip().lower()
    # Remove percentage/number suffixes like "13.0%" or "7.0%"
    raw_clean = re.sub(r'\s*[\d.]+%?\s*$', '', raw_lower).strip()
    # Filter 'none' / empty
    if not raw_clean or raw_clean == 'none':
        return None
    # Direct match
    if raw_clean in LEAK_ALIASES:
        return LEAK_ALIASES[raw_clean]
    # Partial match
    for alias, canonical in LEAK_ALIASES.items():
        if alias in raw_clean:
            return canonical
    # Fallback: title-case the cleaned string
    return raw_clean.title() if raw_clean else None


def _parse_leak_string(leak_str):
    """Parse a Top_Leak string into a set of normalized leak names."""
    if not leak_str or not leak_str.strip() or leak_str.strip().lower() == 'none':
        return set()
    # Split on ' + ' delimiter
    parts = re.split(r'\s*\+\s*', leak_str.strip())
    leaks = set()
    for part in parts:
        normalized = _normalize_leak(part)
        if normalized:
            leaks.add(normalized)
    return leaks


_COMPLETENESS_NEED_BUCKETS = ('bust_audit', 'coolers', 'mistakes', 'punts',
                              'iii4_screening', 'read_dependent_screening')

# v8.13.1 P0 (analyst-coverage trust): ANALYST_COMPLETE must require that the
# hands that actually decide session results are reviewed — not just an empty
# candidate queue. On 2026-06-13 a report self-declared ANALYST_COMPLETE after
# reviewing 5 hands while every meaningful postflop loss (incl. the -40BB
# biggest loss) went unreviewed. These buckets are the loss / confirmed-error
# groups; ANY unreviewed (and not auto-resolved) member blocks COMPLETE.
_CRITICAL_NEED_BUCKETS = ('mistakes', 'punts', 'coolers', 'bust_audit',
                          'biggest_loss_screen', 'postflop_loss_screen')
# The loss subset surfaced in the visible coverage line
# ("N/M significant-loss hands reviewed").
_SIGNIFICANT_LOSS_BUCKETS = ('biggest_loss_screen', 'postflop_loss_screen',
                             'coolers', 'bust_audit')


def _is_non_nlh_candidate(_c):
    """A candidate is unsupported non-NLH when its game_type is not NLH, or it carries 4+ hole
    cards (Omaha/PLO). Used as a defensive per-candidate fallback when rd['_non_nlh_ids'] is absent."""
    if not isinstance(_c, dict):
        return False
    if (_c.get('game_type') or 'NLH') != 'NLH':
        return True
    _cards = _c.get('cards') or []
    return isinstance(_cards, (list, tuple)) and len(_cards) >= 4


def canonical_required_review_ids(candidates, auto_resolved_ids=None, non_nlh_ids=None):
    """v8.19.0 RC3 (P2-1): the ONE canonical required-review population, shared verbatim by the
    analyst COVERAGE GATE (gem_analyzer __main__) and the COMPLETENESS owner
    (compute_report_completeness). A hand requires analyst review iff it is a candidate in a
    _COMPLETENESS_NEED_BUCKETS bucket and is neither chart-match auto-resolved nor an unsupported
    non-NLH hand. Two deliberate identity rules so the gate's "Full coverage" message provably
    implies the completeness layer has NO unreviewed required hand:
      - SUPPRESS-noise candidates are KEPT (a suggested SUPPRESS is the auto-classifier's hint, not
        an analyst waiver; every flagged candidate is reviewable until the analyst rules on it).
      - The blindspot-audit sample is a SEPARATE coverage signal, never folded into this set.
    Returns {'need': set, 'need_bucket': {id: bucket}, 'non_nlh': set} (non_nlh includes the
    per-candidate game_type/4-card fallback so both callers exclude the same hands)."""
    _auto = set(auto_resolved_ids or [])
    _non_nlh = set(non_nlh_ids or [])
    for _bk in set(_COMPLETENESS_NEED_BUCKETS) | set(_CRITICAL_NEED_BUCKETS) | set(_SIGNIFICANT_LOSS_BUCKETS):
        for _c in (candidates.get(_bk, []) or []):
            _cid = _c.get('id') if isinstance(_c, dict) else None
            if _cid and _is_non_nlh_candidate(_c):
                _non_nlh.add(_cid)
    _need, _need_bucket = set(), {}
    for _bk in _COMPLETENESS_NEED_BUCKETS:
        for _c in (candidates.get(_bk, []) or []):
            _cid = _c.get('id') if isinstance(_c, dict) else None
            if _cid and _cid not in _auto and _cid not in _non_nlh:
                _need.add(_cid)
                _need_bucket.setdefault(_cid, _bk)
    return {'need': _need, 'need_bucket': _need_bucket, 'non_nlh': _non_nlh}


def compute_report_completeness(rd, candidates=None):
    """v8.12.10 (pipeline trust contract): classify the report as
    AUTO_ONLY / ANALYST_PARTIAL / ANALYST_COMPLETE and stamp the counts the
    TL;DR banner + CLI + manifest read. Single owner so all three render
    paths (full / resume / quick) agree.

    candidates: the analyst_candidates dict when available (full/resume).
    In --quick mode it is None; the need-set is read back from the cached
    rd['_candidate_need_ids'] stamped during the prior full/resume run.
    """
    _ac = rd.get('analyst_commentary') or {}
    reviewed_ids = {hid for hid in _ac.keys() if not str(hid).startswith('__')}

    # v8.20 W1A: re-enrich the ONE canonical material-loss population with the LIVE analyst verdicts so
    # the visible material-loss surface + summary reflect the same owner on full AND --quick renders
    # (the population id-set is fixed at build time; only its review state/classification changes here).
    _mpop_rd = rd.get('material_loss_population')
    if _mpop_rd:
        import gem_material_loss as _mloss_rc
        _vo = rd.get('variance_outcomes')
        _var_ids = set(_vo.keys()) if isinstance(_vo, dict) else set(rd.get('variance_ids') or [])
        _mloss_rc.reenrich_material_loss(_mpop_rd, analyst_commentary=_ac, variance_ids=_var_ids)
        rd['material_loss_summary'] = _mloss_rc.material_loss_summary(_mpop_rd)

    if candidates is not None:
        _auto = set(rd.get('auto_resolved_ids', []) or [])
        # RC3 P0-1 / P2-1: the completeness owner and the coverage gate share ONE canonical
        # required-review population (canonical_required_review_ids) so a "Full coverage" message
        # provably implies completeness has no unreviewed required hand. It excludes auto-resolved
        # and unsupported non-NLH hands (the latter via rd['_non_nlh_ids'] PLUS a per-candidate
        # game_type/4-card fallback), keeps SUPPRESS-noise candidates, and never folds in blindspot.
        _canon = canonical_required_review_ids(candidates, _auto, rd.get('_non_nlh_ids'))
        _non_nlh = _canon['non_nlh']
        rd['_non_nlh_ids'] = sorted(_non_nlh)   # persist the resolved set for --quick

        def _ids_for(_buckets):
            _s = set()
            for _bk in _buckets:
                for _c in candidates.get(_bk, []) or []:
                    _cid = _c.get('id') if isinstance(_c, dict) else None
                    if _cid and _cid not in _auto and _cid not in _non_nlh:
                        _s.add(_cid)
            return _s

        need = _canon['need']
        need_bucket = _canon['need_bucket']    # id -> bucket, persisted for --quick
        rd['_candidate_need_ids'] = sorted(need)  # persist for --quick
        rd['_candidate_need_bucket'] = need_bucket
        # v8.13.1 P0: critical-coverage + significant-loss sets (persist for --quick)
        critical_need = _ids_for(_CRITICAL_NEED_BUCKETS)
        significant_loss = _ids_for(_SIGNIFICANT_LOSS_BUCKETS)
        rd['_critical_need_ids'] = sorted(critical_need)
        rd['_significant_loss_ids'] = sorted(significant_loss)
    else:
        # RC3 P0-1: the --quick path subtracts the persisted non-NLH set too (idempotent if the
        # cached sets were already filtered, but guarantees consistency across full/--quick).
        _non_nlh = set(rd.get('_non_nlh_ids') or [])
        need = set(rd.get('_candidate_need_ids', []) or []) - _non_nlh
        need_bucket = rd.get('_candidate_need_bucket', {}) or {}
        critical_need = set(rd.get('_critical_need_ids', []) or []) - _non_nlh
        significant_loss = set(rd.get('_significant_loss_ids', []) or []) - _non_nlh

    awaiting = sorted(need - reviewed_ids)
    # v8.12.12 Obj-D: per-bucket breakdown of what is still awaiting review, so
    # the ANALYST_PARTIAL banner can name which buckets remain.
    awaiting_by_bucket = {}
    for _aid in awaiting:
        _bk = need_bucket.get(_aid)
        if _bk:
            awaiting_by_bucket[_bk] = awaiting_by_bucket.get(_bk, 0) + 1

    # v8.13.1 P0: critical-coverage gate. A report cannot be ANALYST_COMPLETE
    # while any critical-loss / confirmed-error hand is unreviewed (and not
    # auto-resolved). Auto-resolved hands are already excluded from the sets.
    critical_unreviewed = sorted(critical_need - reviewed_ids)
    sig_total = len(significant_loss)
    sig_reviewed = len(significant_loss & reviewed_ids)

    # v8.19.0 Chapter B (PHF-001): one canonical ReviewCoverageVM. The visible numerator in
    # "X reviewed of N candidates" MUST be the INTERSECTION (reviewed AND a worklist candidate),
    # NEVER all analyst entries — `reviewed_hands` (all) stays for the CLI / manifest / run
    # verdict count; the banner now reads `reviewed_in_candidates`. System-priority coverage
    # stays distinct from Ron's personal review marks (a JS-only concept, not derived here).
    reviewed_in_candidates = need & reviewed_ids
    reviewed_critical = critical_need & reviewed_ids
    if critical_unreviewed:
        coverage_state = 'PARTIAL'           # required critical coverage incomplete
    elif awaiting:
        coverage_state = 'BOUNDED_COMPLETE'  # all critical done; lower-priority candidates remain
    else:
        coverage_state = 'COMPLETE'
    review_coverage_vm = {
        'analyst_reviewed_all_ids': sorted(reviewed_ids),
        'worklist_candidate_ids': sorted(need),
        'critical_ids': sorted(critical_need),
        'reviewed_worklist_ids': sorted(reviewed_in_candidates),
        'unreviewed_worklist_ids': sorted(need - reviewed_ids),
        'reviewed_critical_ids': sorted(reviewed_critical),
        'unreviewed_critical_ids': critical_unreviewed,
        'bucket_ids': {bk: sorted(i for i in need if need_bucket.get(i) == bk)
                       for bk in sorted(set(need_bucket.values()))},
        'coverage_state': coverage_state,
    }

    if not reviewed_ids:
        state = 'AUTO_ONLY'
    elif awaiting or critical_unreviewed:
        state = 'ANALYST_PARTIAL'
    else:
        state = 'ANALYST_COMPLETE'

    # Visible, quantified coverage line (single source — MD + HTML agree). Numerators are the
    # INTERSECTION sets (PHF-001) so "of N" never uses the all-analyst count.
    if critical_unreviewed:
        coverage_line = (f'Analyst coverage PARTIAL: {len(critical_unreviewed)} of '
                         f'{len(critical_need)} critical hands unreviewed — not final · '
                         f'worklist {len(reviewed_in_candidates)} of {len(need)} reviewed '
                         f'({len(need - reviewed_ids)} remain).')
    else:
        coverage_line = (f'Analyst coverage {coverage_state}: reviewed {len(reviewed_ids)} '
                         f'hands overall · worklist {len(reviewed_in_candidates)} of '
                         f'{len(need)} reviewed · critical {len(reviewed_critical)} of '
                         f'{len(critical_need)} · {sig_reviewed}/{sig_total} significant-loss.')

    rc = {
        'state': state,
        'reviewed_hands': len(reviewed_ids),
        # v8.19.0 Chapter B (PHF-001): intersection numerators + canonical coverage VM.
        'reviewed_in_candidates': len(reviewed_in_candidates),
        'reviewed_critical': len(reviewed_critical),
        'critical_total': len(critical_need),
        'coverage_state': coverage_state,
        'review_coverage_vm': review_coverage_vm,
        'candidate_need': len(need),
        'awaiting_candidates': len(awaiting),
        'awaiting_markers': len(awaiting),
        'awaiting_ids': awaiting[:50],
        'awaiting_by_bucket': awaiting_by_bucket,
        # v8.13.1 P0 critical-coverage gate
        'critical_unreviewed': len(critical_unreviewed),
        'critical_unreviewed_ids': critical_unreviewed[:50],
        'significant_loss_total': sig_total,
        'significant_loss_reviewed': sig_reviewed,
        'critical_coverage_ok': not critical_unreviewed,
        'coverage_line': coverage_line,
    }
    rd['report_completeness'] = rc
    return rc


def _refresh_discipline_tier(rd, stats, hands):
    """B-AVIEL BUG-5: re-derive discipline_tier after analyst_commentary is
    definitively bound to rd.  This ensures the stat strip's punt and
    mistake counts match the body sections (both use the same analyst-
    cleared set)."""
    n_h = len(hands)
    raw_mistakes = stats.get('mistakes', []) or []
    rev_block = rd.get('reviewed_mistakes', {})
    needs_keys = {(m.get('id'), m.get('type')) for m in (rev_block.get('needs_review') or [])}
    auto_keys = {(m.get('id'), m.get('type')) for m in (rev_block.get('auto_corrected') or [])}
    _ac = rd.get('analyst_commentary') or {}
    # v8.12.4 (QA item 31): entry reconciliation — "verdicts written: 106"
    # vs 108 submitted means entries dropped SILENTLY. Surface any analyst
    # entry whose hand id does not exist in this session so the gap has
    # names, not just a count difference.
    if _ac and not rd.get('_analyst_recon_done'):
        rd['_analyst_recon_done'] = True
        _hand_ids_recon = {h.get('id') for h in (hands or [])}
        _ac_real = [hid for hid in _ac.keys() if not str(hid).startswith('__')]
        _unmatched_recon = sorted(h for h in _ac_real if h not in _hand_ids_recon)
        # v8.12.9 (pipeline-learnings Fix 4): "35 entries / 34 matched"
        # looked like a silent drop — __synthesis__/meta keys are not
        # hands. Count them separately so the numbers reconcile on sight.
        _ac_meta = len(_ac) - len(_ac_real)
        _meta_txt = (f" + {_ac_meta} synthesis/meta block"
                     f"{'s' if _ac_meta != 1 else ''}" if _ac_meta else '')
        if _unmatched_recon:
            print(f"  ⚠ Analyst file: {len(_ac_real)} hand entries{_meta_txt}. "
                  f"Reconciliation: {len(_ac_real) - len(_unmatched_recon)}"
                  f"/{len(_ac_real)} matched; UNMATCHED hand ids "
                  f"(not in this session): {_unmatched_recon[:6]}")
        else:
            print(f"  ✓ Analyst file: {len(_ac_real)} hand entries{_meta_txt}. "
                  f"Reconciliation: {len(_ac_real)}/{len(_ac_real)} hand "
                  f"entries matched session hands")
        # v8.12.4 (QA item 28): batch-stamp detector — many verdicts sharing
        # one identical argument text are rubber stamps, indistinguishable
        # from real reviews in the Cleared aggregate. Name the worst offender.
        from collections import Counter as _Ctr_recon
        _arg_counts = _Ctr_recon(
            str((_ac.get(h) or {}).get('argument', '')).strip()[:120]
            for h in _ac_real if (_ac.get(h) or {}).get('argument'))
        _stamp = [(t, n) for t, n in _arg_counts.most_common(3)
                  if n >= 10 and t]
        for _st_t, _st_n in _stamp:
            print(f"  ⚠ Analyst batch-stamp: {_st_n} verdicts share one "
                  f"argument text (\"{_st_t[:60]}…\") — these read as "
                  f"rubber stamps, not reviews.")
    # v8.20 W1A.2A: the canonical confirmed-mistake / punt populations are now owned by ONE place --
    # gem_final_truth.build_final_truth (one final class per hand; analyst override fully replaces the raw
    # nomination; PUNT and CONFIRMED_MISTAKE are disjoint by construction). The discipline tier DELEGATES
    # here instead of re-deriving the populations, so the "confirmed + punts = errors" math can never
    # double-count an overridden hand again (the v8.20 W1A.1 BUG-2 class of divergence is now impossible),
    # and every consumer of dt['canonical_*_count'] reads the SAME owner.
    import gem_final_truth as _ft
    _ft_out = _ft.build_final_truth(rd, stats, hands)
    canonical_mistakes_count = _ft_out['counts']['CONFIRMED_MISTAKE']
    punts_count = _ft_out['counts']['PUNT']
    clear_surv = _ft_out['reconciliation']['detector_clear_survivors']
    mist_per_100 = 100.0 * clear_surv / max(n_h, 1)
    punts_per_100 = float(punts_count) * 100.0 / max(n_h, 1)
    # Re-classify discipline tier
    if mist_per_100 < 0.5 and punts_per_100 < 0.1:
        dt_label, dt_emoji = 'Elite Discipline', '\U0001F396️'
    elif mist_per_100 < 1.0 and punts_per_100 < 0.2:
        dt_label, dt_emoji = 'Strong Discipline', '✅'
    elif mist_per_100 < 2.0 and punts_per_100 < 0.5:
        dt_label, dt_emoji = 'Solid Discipline', '✅'
    elif mist_per_100 < 4.0 and punts_per_100 < 1.0:
        dt_label, dt_emoji = 'Developing Discipline', '\U0001F7E1'
    else:
        dt_label, dt_emoji = 'Leak-Heavy', '\U0001F534'
    dt = rd.get('discipline_tier', {})
    dt.update({
        'label': dt_label, 'emoji': dt_emoji,
        'mistakes_per_100': round(mist_per_100, 2),
        'punts_per_100': round(punts_per_100, 2),
        'clear_mistakes_count': clear_surv,
        'canonical_mistakes_count': canonical_mistakes_count,
        'canonical_mistakes_per_100': round(100.0 * canonical_mistakes_count / max(n_h, 1), 2),
        'punts_count': punts_count,
        'canonical_punts_count': punts_count,
        'canonical_punts_per_100': round(punts_per_100, 2),
    })
    rd['discipline_tier'] = dt
    # v8.12.4 (QA items 5+6): the attribution ledger must agree with the
    # sections after analyst verdicts attach — same trigger point as the
    # discipline-tier refresh.
    try:
        _refresh_results_attribution(rd, stats, hands)
    except Exception:
        pass


def _refresh_results_attribution(rd, stats, hands):
    """v8.12.4 (QA items 5+6). Post-analyst-attach consistency refresh.

    (5) Cooler count: S1.7 applies analyst overrides (drop III.x, add I.7)
        plus equity reclassification (lost 40-60% -> flip, >60% -> suckout)
        — the attribution row was still reading the raw detector count, so
        the report said "7 negative coolers" in one place and "6 actual"
        in another. Classify ONCE here, store rd['cooler_ledger'], and
        update results_attribution's cooler fields from it. The renderer
        consumes the same ledger.
    (6) Mistake-EV: the attribution row counted analyst III.1/III.2
        verdicts but carried ZERO EV for them, so 2 confirmed mistakes
        worth ~92BB showed as "+0.00". Add their EV (hand net_bb — the
        same figure the S2.2 Confirmed Mistakes table shows) on the same
        spine conversions.
    """
    ra = rd.get('results_attribution') or {}
    if not ra:
        return
    # per-100 conversions MUST use the attribution population (ra['n_hands']),
    # the same denominator every other ledger row uses.
    n_h = ra.get('n_hands') or len(hands or []) or 1
    hands_by_id = {h.get('id', ''): h for h in (hands or [])}
    _ac = rd.get('analyst_commentary') or {}
    _ac = {hid: c for hid, c in _ac.items() if isinstance(c, dict)}

    # ---- (5) cooler ledger -------------------------------------------------
    coolers_block = stats.get('coolers', {}) or {}
    entries = []
    for c in (coolers_block.get('hands') or []):
        if isinstance(c, dict) and c.get('id'):
            entries.append({'id': c['id'], 'hero': c.get('hero', ''),
                            'villain': c.get('villain', ''),
                            'board': c.get('board', ''), 'src': 'detector'})
    _iiix = {hid for hid, c in _ac.items()
             if (c.get('verdict', '') or '').startswith(
                 ('III.0', 'III.1', 'III.2', 'III.4', 'III.5'))}
    entries = [e for e in entries if e['id'] not in _iiix]
    _have = {e['id'] for e in entries}
    _i7 = {hid for hid, c in _ac.items()
           if (c.get('verdict', '') or '').startswith('I.7')}
    for hid in sorted(_i7 - _have):
        h = hands_by_id.get(hid)
        if not h:
            continue
        # winning villain hand from appendix showdown (2-card, outcome-aware)
        _v = ''
        _sd = (((rd.get('appendix_hand_details') or {}).get(hid, {}) or {})
               .get('showdown', {}) or {})
        _won_v = [' '.join(i.get('cards') or []) for i in _sd.values()
                  if not i.get('is_hero') and len(i.get('cards') or []) == 2
                  and (i.get('outcome') or '').startswith('won')]
        _all_v = [' '.join(i.get('cards') or []) for i in _sd.values()
                  if not i.get('is_hero') and len(i.get('cards') or []) == 2]
        if _won_v:
            _v = _won_v[0]
        elif _all_v:
            _v = _all_v[0]
        entries.append({'id': hid, 'hero': ' '.join(h.get('cards') or []),
                        'villain': _v,
                        'board': ' '.join(h.get('board') or []),
                        'src': 'analyst'})
    # equity reclassification of LOST entries (mirror of S1.7 / BUG-5 logic,
    # including the direct-enumeration fallback so this ledger is strictly
    # authoritative for the renderer)
    try:
        from gem_pot_odds import enumerate_equity as _enum_eq
    except Exception:
        _enum_eq = None
    _eai_by_id = {e.get('id', ''): e
                  for e in (stats.get('eai', {}).get('hands', []) or [])}
    neg_ids, flip_ids, suck_ids = [], [], []
    for e in entries:
        hid = e['id']
        _full = hands_by_id.get(hid, {})
        _won = _full.get('won')
        _ee = _eai_by_id.get(hid)
        if _ee and _ee.get('won') is not None:
            _won = _ee['won']
        if _won is not False:
            neg_ids.append(hid)
            continue
        _eq = None
        if _ee:
            _eq = _ee.get('hero_equity') or _ee.get('equity_at_allin')
        if _eq is None and _enum_eq:
            _hc = (e.get('hero') or '').split()
            _vc = (e.get('villain') or '').split()
            _bd = [x for x in (e.get('board') or '').split() if len(x) == 2]
            if len(_hc) == 2 and len(_vc) == 2:
                try:
                    _raw_eq = _enum_eq(_hc, [_vc], _bd[:3] if _bd else [])
                    if _raw_eq is not None:
                        _eq = _raw_eq / 100.0
                except Exception:
                    pass
        if _eq is None:
            neg_ids.append(hid)
            continue
        if 0.40 <= _eq <= 0.60:
            flip_ids.append(hid)
        elif _eq > 0.60:
            suck_ids.append(hid)
        else:
            neg_ids.append(hid)
    pos_count = int(coolers_block.get('positive_count', 0) or 0)
    rd['cooler_ledger'] = {
        'negative_ids': neg_ids,
        'flip_reclassified_ids': flip_ids,
        'suckout_reclassified_ids': suck_ids,
        'analyst_added_ids': sorted(_i7 - _have),
        'analyst_dropped_ids': sorted(_iiix & {(c.get('id') or '') for c in
                                               (coolers_block.get('hands') or [])
                                               if isinstance(c, dict)}),
        'positive_count': pos_count,
        'negative_count': len(neg_ids),
        'net_count': len(neg_ids) - pos_count,
    }
    # re-derive the attribution cooler layer from the FINAL count
    exp_lo = coolers_block.get('expected_low', 0.15)
    exp_hi = coolers_block.get('expected_high', 0.30)
    expected_coolers = (exp_lo + exp_hi) / 2.0 * n_h / 100.0
    _old_var = ra.get('cooler_var_bb', 0) or 0
    new_var = -(len(neg_ids) - expected_coolers) * 35.0  # BB_PER_COOLER
    ra['cooler_count_actual'] = len(neg_ids)
    ra['cooler_count_expected'] = round(expected_coolers, 1)
    ra['cooler_var_bb'] = round(new_var, 1)
    ra['cooler_var_per_100'] = round(100.0 * new_var / n_h, 2)
    # keep the cEV layer proportional to the BB change (same hand mix)
    try:
        _vc = (rd.get('variance_cev') or {}).get('cooler') or {}
        if _vc.get('cev_per_100') is not None and _old_var:
            _vc['cev_per_100'] = round(
                _vc['cev_per_100'] * (new_var / _old_var), 2)
    except Exception:
        pass

    # ---- (6) mistake row: analyst III.1/III.2 EV ---------------------------
    _counted = set(ra.get('non_tail_mistake_ids') or [])
    extra_bb = 0.0
    extra_cev = 0.0
    extra_ids = []
    for hid, c in _ac.items():
        if not (c.get('verdict', '') or '').startswith(('III.1', 'III.2')):
            continue
        if hid in _counted:
            continue
        h = hands_by_id.get(hid)
        if not h:
            continue
        _ev = h.get('net_bb') or 0.0
        extra_bb += _ev
        # bounded fraction-of-starting-stack conversion (spine approximation:
        # net BB / hand-start stack in BB)
        _stk = h.get('stack_bb') or 0
        if _stk:
            extra_cev += max(-3.0, min(_ev / _stk, 3.0))
        extra_ids.append(hid)
    _canon = (rd.get('discipline_tier') or {}).get('canonical_mistakes_count')
    ra['analyst_mistake_extra_ids'] = sorted(extra_ids)
    ra['analyst_mistake_extra_bb'] = round(extra_bb, 1)
    ra['mistake_row_count'] = (_canon if _canon is not None
                               else ra.get('non_tail_mistake_count', 0) + len(extra_ids))
    ra['mistake_row_per_100'] = round(
        (ra.get('non_tail_mistake_per_100', 0) or 0)
        + 100.0 * extra_bb / n_h, 2)
    ra['mistake_row_cev_per_100'] = round(
        (ra.get('non_tail_mistake_cev_per_100', 0) or 0)
        + 100.0 * extra_cev / n_h, 4)
    rd['results_attribution'] = ra

    # ---- (11/12) analyst-confirmed mistakes always reach the GTOW
    # shortlist — the session's biggest confirmed mistake must not be
    # missing from the solver queue while smaller hands made it.
    try:
        _sl = rd.get('gto_shortlist')
        if isinstance(_sl, list):
            _sl_ids = {c.get('id') for c in _sl}
            for hid, c in _ac.items():
                if not (c.get('verdict', '') or '').startswith(('III.1', 'III.2')):
                    continue
                if hid in _sl_ids:
                    continue
                h = hands_by_id.get(hid)
                if not h:
                    continue
                try:
                    from gem_nicknames import combo_to_chart as _ctc
                    _cards_q = _ctc(h.get('cards', []))
                except Exception:
                    _cards_q = ''.join(h.get('cards', []) or [])
                _lbl = c.get('label') or 'confirmed mistake'
                _sl.append({
                    'id': hid,
                    'reason': 'Confirmed mistake (analyst)',
                    'cluster': 'Confirmed mistakes — solver review',
                    'date': h.get('date', ''),
                    'tournament': h.get('tournament', ''),
                    'cards': ' '.join(h.get('cards', []) or []),
                    'position': h.get('position', ''),
                    'stack_bb': round(h.get('stack_bb', 0) or 0),
                    'net_bb': round(h.get('net_bb', 0) or 0, 1),
                    'line': h.get('line', ''),
                    'board': ' '.join(h.get('board', []) or []),
                    'action_summary': h.get('action_summary', ''),
                    'question': (f"{h.get('pot_type', 'SRP')} "
                                 f"{h.get('position', '?')} "
                                 f"{round(h.get('stack_bb', 0) or 0)}BB, "
                                 f"{_cards_q} — confirmed mistake ({_lbl}). "
                                 f"Find the correct line street by street."),
                })
                _sl_ids.add(hid)
    except Exception:
        pass


def generate_report_data(stats, hands, hh_dir, session_history_path=None,
                         player_name=None, isolate=False):
    """
    Pre-stage all data needed for report writing.
    Returns a dict ready to dump as gem_report_data.json.

    player_name: display name for the report header / title. Defaults to
                 'Knockman' for backward compatibility but MUST be set when
                 running another player's data (Issue 2 / Issue 3 isolation).
    isolate:     when True, disables ALL /mnt/project/ baseline fallbacks
                 (trend CSV, skill context, drift monitor). Use for non-Ron
                 data to prevent cross-player contamination (Issue 3).
                 Auto-enabled when player_name is set to anything other than
                 'Knockman'.
    """
    rd = {}
    _pname = player_name or 'Knockman'
    rd['player_name'] = _pname
    # Auto-isolate when running another player's data
    _isolate = isolate or (_pname.lower() != 'knockman')

    # ----------------------------------------------------------
    # Bug B guard (Ron 2026-05-30): stale gem_hands.json detection.
    # If len(hands) diverges from stats['volume']['hands'] by > 10%,
    # the hands list was likely loaded from a stale file (e.g. a prior
    # session's gem_hands.json with 33 hands when stats covers 9,919).
    # This contaminates results_attribution, made-hands variance, and
    # cEV calculations. Hard-fail to prevent garbage metrics.
    # ----------------------------------------------------------
    _vol_hands = (stats.get('volume', {}) or {}).get('hands', 0) or 0
    _len_hands = len(hands) if hands else 0
    if _vol_hands and _len_hands:
        _drift = abs(_vol_hands - _len_hands) / max(_vol_hands, 1)
        if _drift > 0.10:
            raise ValueError(
                f"STALE DATA GUARD: stats reports {_vol_hands} hands but "
                f"hands list has {_len_hands} entries ({_drift:.0%} drift). "
                f"This usually means gem_hands.json is from a previous session. "
                f"Re-run the parser or pass the fresh hands list from parse_session().")

    # ----------------------------------------------------------
    # 1. BUY-IN DATA
    # ----------------------------------------------------------
    buyin_data = _parse_buyins(hh_dir, stats.get('tournament_list', []))
    # B-AVIEL BUG-3 (2026-06-01): bullets = distinct tournament entries, NOT
    # HH file count.  GGPoker splits a single entry across multiple files, so
    # file-count inflates bullets (and cost/ROI).  Recompute from distinct
    # tournament_id values per tournament name in the actual hands.
    _tid_by_tname = defaultdict(set)
    for _h in hands:
        _tn = _h.get('tournament', '')
        _tid = str(_h.get('tournament_id', '') or '')
        if _tn and _tid:
            _tid_by_tname[_tn].add(_tid)
    # v8.7.4 FIX (Bug 2): use file-based bullet count from tournament_list
    # which carries n_files per tournament (set by parser, re-entry aware)
    _tlist = stats.get('tournament_list', []) or []
    _files_by_tname = {t['name']: t.get('n_files', 1) for t in _tlist if t.get('name')}
    for _bd in buyin_data.get('breakdown', []):
        _bdn = _bd.get('tournament', '')
        _file_bullets = _files_by_tname.get(_bdn, 0)
        _tid_bullets = len(_tid_by_tname.get(_bdn, set()))
        _actual_bullets = _file_bullets or _tid_bullets or _bd.get('bullets', 1)
        _bd['bullets'] = _actual_bullets
        _bd['cost'] = round(_bd['buyin'] * _actual_bullets, 2)
    # B-V10 BUG-CP17-2 (2026-06-01): restrict totals to breakdown rows whose
    # tournament name actually appears in the hands.  Phantom rows from fuzzy
    # filename matches (non-HH files, summary files, duplicate name fragments)
    # inflate bullets and ABI.  Safety fallback: use all rows if filter empties.
    _real_tnames = set(_tid_by_tname.keys())
    _real_rows = [d for d in buyin_data.get('breakdown', [])
                  if d.get('tournament', '') in _real_tnames]
    if not _real_rows:
        _real_rows = buyin_data.get('breakdown', [])
    _total_inv = sum(d['cost'] for d in _real_rows)
    # v8.7.3 FIX (handover Bug 1+2): use authoritative file-based bullet count
    # from stats.volume.bullets, not the tid-collapsed per-row sum which undercounts
    # re-entries (same tournament_id reused for multiple bullets).
    _vol_bullets = (stats.get('volume') or {}).get('bullets')
    _total_bul = _vol_bullets or sum(d['bullets'] for d in _real_rows)
    buyin_data['total_invested'] = _total_inv
    buyin_data['n_bullets'] = _total_bul
    buyin_data['avg_buyin'] = round(_total_inv / _total_bul, 2) if _total_bul else 0
    rd['avg_buyin'] = buyin_data['avg_buyin']
    rd['total_invested'] = buyin_data['total_invested']
    rd['buyin_breakdown'] = buyin_data['breakdown']

    # B47 (v7.52, Ron 2026-05-18): USD overlay from game summaries.
    # If hh_dir (or a sibling 'game_summaries' folder) contains GG game-summary
    # files, parse them to get the actual USD net per tournament. This closes
    # the gap between BB/100 (decision-quality, hand-weighted) and USD (risk-
    # weighted, buyin-weighted) — same session can look near-neutral by BB/100
    # but be brutally negative by USD if high-buyin bustouts dominated cost.
    rd['usd_overlay'] = _parse_game_summaries_usd(hh_dir, hands)

    # v8.14.3 Issue 1 (Ron 2026-06-15): single financial source of truth. When a
    # USD overlay parsed successfully, its game-summary totals are CANONICAL — so
    # the top-level total_invested / avg_buyin must NOT keep contradicting them
    # (shipped: top-level 3930.97/59.56 vs overlay 3946.97/60.72). Re-point the
    # top-level fields to the overlay (cost, cost/bullets). The filename system
    # above stays the fallback and is left byte-identical when no overlay parses.
    _ov = rd.get('usd_overlay') or {}
    _ovt = _ov.get('totals') or {}
    if _ov.get('status') == 'parsed' and _ovt.get('total_cost') and _ovt.get('n_bullets'):
        rd['total_invested'] = _ovt['total_cost']
        rd['avg_buyin'] = round(_ovt['total_cost'] / _ovt['n_bullets'], 2)
        rd['_financial_source'] = 'usd_overlay'   # provenance for QA / lint
    else:
        rd['_financial_source'] = 'filename'

    # ----------------------------------------------------------
    # 2. DATES
    # ----------------------------------------------------------
    rd['dates'] = sorted(set(h.get('date', '') for h in hands if h.get('date')))

    # ----------------------------------------------------------
    # 3. SB BvB BY TABLE SIZE (ICM-adjusted)
    # ----------------------------------------------------------
    bvb_full = {'n': 0, 'limp': 0, 'raise': 0, 'fold': 0, 'hands': []}
    bvb_short = {'n': 0, 'limp': 0, 'raise': 0, 'fold': 0, 'hands': []}
    for h in hands:
        if h.get('position') != 'SB' or not h.get('first_in'):
            continue
        action = h.get('pf_action', '')
        bucket = bvb_full if h.get('n_players', 9) >= 6 else bvb_short
        bucket['n'] += 1
        if action == 'call':
            bucket['limp'] += 1
        elif action == 'raise':
            bucket['raise'] += 1
        elif action == 'fold':
            bucket['fold'] += 1
        bucket['hands'].append({
            'id': h['id'], 'cards': ' '.join(h.get('cards', [])),
            'stack_bb': round(h.get('stack_bb', 0)),
            'action': action, 'n_players': h.get('n_players', 0),
            'tournament': h.get('tournament', ''),
            'date': h.get('date', ''),
            'phase': h.get('tournament_phase', ''),
            'net_bb': round(h.get('net_bb', 0), 1)
        })
    for bucket in [bvb_full, bvb_short]:
        n = bucket['n']
        if n > 0:
            bucket['limp_pct'] = round(bucket['limp'] / n * 100, 1)
            bucket['raise_pct'] = round(bucket['raise'] / n * 100, 1)
            bucket['fold_pct'] = round(bucket['fold'] / n * 100, 1)
    rd['sb_bvb_by_table_size'] = {
        'full_ring': bvb_full,
        'short_handed': bvb_short
    }

    # ----------------------------------------------------------
    # 4. C-BET BY ALL TEXTURES (HU IP, all pot types)
    # ----------------------------------------------------------
    tex_data = defaultdict(lambda: {'opps': 0, 'bets': 0})
    for h in hands:
        if h.get('players_at_flop', 0) != 2:
            continue
        if not h.get('pfr'):
            continue
        if h.get('pf_allin') or (h.get('spr') is not None and h.get('spr', 99) <= 0):
            continue
        if len(h.get('board', [])) < 3:
            continue
        # Check if IP
        line = h.get('line', '')
        is_ip = '_IP_' in line or h.get('hero_ip', False)
        if not is_ip:
            continue
        tex = h.get('board_texture', 'other')
        flop_action = h.get('hero_street_actions', {}).get('flop', '')
        tex_data[tex]['opps'] += 1
        if flop_action in ('cbet', 'bet'):
            tex_data[tex]['bets'] += 1

    rd['cbet_all_textures_hu_ip'] = {
        tex: {
            'opps': d['opps'], 'bets': d['bets'],
            'pct': round(d['bets'] / d['opps'] * 100, 1) if d['opps'] > 0 else 0
        }
        for tex, d in sorted(tex_data.items())
    }
    rd['cbet_all_textures_hu_ip']['_total_opps'] = sum(d['opps'] for d in tex_data.values())
    rd['cbet_all_textures_hu_ip']['_total_bets'] = sum(d['bets'] for d in tex_data.values())

    # ----------------------------------------------------------
    # 5. CHECK-RAISE EVIDENCE HANDS
    # ----------------------------------------------------------
    cr_evidence = []
    for h in hands:
        # B164 (Ron 2026-05-24): a hand Hero folded preflop cannot contain a
        # Hero check-raise — but the parser can mis-attribute another
        # player's flop check-raise to Hero's `check_raises` list. Guard:
        # skip preflop folds outright (TM5990455478 / TM5991274599 were
        # surfacing here with line='fold_preflop').
        if h.get('line') == 'fold_preflop' or h.get('pf_action') == 'fold':
            continue
        crs = h.get('check_raises', [])
        if not crs:
            continue
        for cr_street in crs:
            st = cr_street if isinstance(cr_street, str) else cr_street.get('street', '')
            cr_evidence.append({
                'id': h['id'], 'date': h.get('date', ''),
                'tournament': h.get('tournament', ''),
                'cards': ' '.join(h.get('cards', [])),
                'position': h.get('position', ''),
                'street': st,
                'board': ' '.join(h.get('board', [])),
                'hand_strength': h.get('hand_strength', ''),
                'draw_type': h.get('draw_type', ''),
                'net_bb': round(h.get('net_bb', 0), 1),
                'line': h.get('line', '')
            })
    rd['cr_evidence_hands'] = cr_evidence

    # ----------------------------------------------------------
    # 6. DEVIATION EVIDENCE + BASE RATES
    # ----------------------------------------------------------
    devs = stats.get('preflop_deviations', [])
    dev_by_type = defaultdict(lambda: {'clear': [], 'marginal': []})
    for d in devs:
        sev = 'clear' if d.get('confidence') == 'CLEAR' else 'marginal'
        dev_by_type[d.get('type', 'unknown')][sev].append({
            'id': d.get('id', ''), 'date': d.get('date', hands[0].get('date', '') if hands else ''),
            'tournament': d.get('tournament', ''),
            'cards': d.get('cards', ''), 'pos': d.get('pos', ''),
            'bb': d.get('stack_bb', 0), 'severity': d.get('confidence', 'MARGINAL'),
            'detail': d.get('action_summary', '')
        })

    # Evidence: pick 2-3 per type (mix clear + marginal)
    dev_evidence = {}
    for dtype, sev_dict in dev_by_type.items():
        evidence = sev_dict['clear'][:3] + sev_dict['marginal'][:2]
        dev_evidence[dtype] = evidence[:5]
    rd['deviation_evidence'] = dev_evidence

    # Base rates
    fi_opps = sum(1 for h in hands if h.get('first_in'))
    total_opens = sum(1 for h in hands if h.get('first_in') and h.get('pf_action') == 'raise')
    faced_raise_non_bb = sum(1 for h in hands if h.get('hero_faced_raise') and h.get('position') != 'BB')
    villain_jams = sum(1 for h in hands if h.get('villain_jammed'))
    bb_faced = sum(1 for h in hands if h.get('position') == 'BB' and h.get('hero_faced_raise'))
    bb_defended = sum(1 for h in hands if h.get('position') == 'BB' and h.get('hero_faced_raise') and h.get('vpip'))

    base_map = {
        'Missed Open': (fi_opps, 'FI opportunities'),
        'Wide Open': (total_opens, 'total opens'),
        'Missed Defend/3-Bet': (faced_raise_non_bb, 'faced raise (non-BB)'),
        'Wide 3-Bet': (faced_raise_non_bb, 'faced raise (non-BB)'),
        'Missed Rejam': (faced_raise_non_bb, 'rejam opportunities'),
        'Wide CVJ (Call Villain Jam)': (villain_jams, 'villain jams'),
        'Wide CVJ — re-jam over jam (covers)': (villain_jams, 'villain jams'),  # B176
        'Missed BB Defend': (bb_faced, 'BB faced raise'),
        'Wide BB Defend': (bb_defended, 'BB defends'),
    }

    dev_base_rates = {}
    for dtype, sev_dict in dev_by_type.items():
        clear_n = len(sev_dict['clear'])
        marg_n = len(sev_dict['marginal'])
        total_n = clear_n + marg_n
        base, label = base_map.get(dtype, (0, 'unknown'))
        dev_base_rates[dtype] = {
            'total': total_n, 'clear': clear_n, 'marginal': marg_n,
            'base': base, 'base_label': label,
            'clear_pct': round(clear_n / base * 100, 1) if base > 0 else 0,
            'marginal_pct': round(marg_n / base * 100, 1) if base > 0 else 0,
        }
    rd['deviation_base_rates'] = dev_base_rates

    # ----------------------------------------------------------
    # 7. DEEP RUN TRAJECTORIES + KEY MOMENTS
    # ----------------------------------------------------------
    deep_runs_data = []
    for dr in stats.get('deep_runs', []):
        tname = dr.get('tournament', '')
        dr_hands = sorted(
            [h for h in hands if h.get('tournament', '') == tname],
            key=lambda h: (h.get('level', 0), h.get('id', ''))
        )
        # Stack trajectory: first hand at each level
        levels = {}
        for h in dr_hands:
            lvl = h.get('level', 0)
            if lvl not in levels:
                levels[lvl] = round(h.get('stack_bb', 0))
        trajectory = [{'level': lvl, 'stack_bb': bb} for lvl, bb in sorted(levels.items())]

        # Key moments: |net_bb| > 15
        key_moments = [{
            'id': h['id'], 'level': h.get('level', 0),
            'cards': ' '.join(h.get('cards', [])),
            'position': h.get('position', ''),
            'stack_bb': round(h.get('stack_bb', 0)),
            'net_bb': round(h.get('net_bb', 0), 1),
            'line': h.get('line', ''),
            'action_summary': h.get('action_summary', '')
        } for h in dr_hands if abs(h.get('net_bb', 0)) > 15]

        # Determine phase reached
        max_level = max((h.get('level', 0) for h in dr_hands), default=0)
        min_players = min((h.get('n_players', 9) for h in dr_hands), default=9)
        if min_players <= 2:
            phase_reached = 'Heads-Up'
        elif any(h.get('tournament_phase') == 'ft_zone' for h in dr_hands):
            phase_reached = 'FT Zone'
        elif any(h.get('tournament_phase') == 'post_bubble' for h in dr_hands):
            phase_reached = 'Post-Bubble'
        elif any(h.get('tournament_phase') == 'bubble_zone' for h in dr_hands):
            phase_reached = 'Bubble'
        else:
            phase_reached = 'Post-Reg'

        deep_runs_data.append({
            'tournament': tname,
            'hands': len(dr_hands),
            'start': dr.get('start', 0), 'peak': dr.get('peak', 0),
            'low': dr.get('low', 0), 'final': dr.get('final', 0),
            'phase_reached': phase_reached,
            'trajectory': trajectory,
            'key_moments': key_moments,
            'premiums_pct': dr.get('premiums_pct', 0),
            'prem_strong_pct': dr.get('prem_strong_pct', 0),
            'eai_total': dr.get('eai_total', 0),
            'eai_won': dr.get('eai_won', 0),
            'eai_expected': dr.get('eai_expected', 0),
        })
    rd['deep_run_trajectories'] = deep_runs_data

    # ----------------------------------------------------------
    # 8. CLINICAL CANDIDATES + GTO SHORTLIST
    # ----------------------------------------------------------
    candidates = []
    # Include: mistakes, coolers, big pots, missed value, missed probes
    seen_ids = set()

    # B173 (Ron 2026-05-24): a hand the analyst cleared (III.3/4/5) can still be
    # worth a solver look — III.6 is a review list, not a mistake list — but it
    # must NOT be labelled "Mistake:". Load the override set and relabel.
    _ac_clin = (rd.get('analyst_commentary')
                or _maybe_load_analyst_commentary(stats) or {})
    _override_clin = {hid for hid, cmt in _ac_clin.items()
                      if isinstance(cmt, dict)
                      and cmt.get('verdict', '').startswith(('III.3', 'III.4', 'III.5'))}

    # Mistakes
    for m in stats.get('mistakes', []) + stats.get('marginal_mistakes', []):
        if m['id'] not in seen_ids:
            if m['id'] in _override_clin:
                # analyst-cleared — keep for review but don't call it a mistake
                candidates.append({
                    'id': m['id'],
                    'reason': f"Analyst-cleared: {m.get('type', '')}",
                    'priority': 4
                })
            else:
                candidates.append({
                    'id': m['id'], 'reason': f"Mistake: {m.get('type', '')}",
                    'priority': 1 if m.get('confidence') == 'CLEAR' else 2
                })
            seen_ids.add(m['id'])

    # Missed river value
    for m in stats.get('missed_river_value', {}).get('hands', []):
        if m['id'] not in seen_ids:
            candidates.append({'id': m['id'], 'reason': 'Missed river value', 'priority': 2})
            seen_ids.add(m['id'])

    # Missed probes
    for m in stats.get('missed_probes', {}).get('hands', []):
        if m['id'] not in seen_ids:
            candidates.append({'id': m['id'], 'reason': 'Missed probe', 'priority': 3})
            seen_ids.add(m['id'])

    # Big pots (|net_bb| > 25, not coolers)
    cooler_ids = {c['id'] for c in stats.get('coolers', {}).get('hands', [])}
    for h in hands:
        if abs(h.get('net_bb', 0)) > 25 and h['id'] not in seen_ids and h['id'] not in cooler_ids:
            candidates.append({
                'id': h['id'], 'reason': f"Big pot: {h.get('net_bb', 0):+.1f}BB",
                'priority': 3
            })
            seen_ids.add(h['id'])

    # Coolers
    for c in stats.get('coolers', {}).get('hands', []):
        if c['id'] not in seen_ids:
            candidates.append({'id': c['id'], 'reason': 'Cooler', 'priority': 4})
            seen_ids.add(c['id'])

    # Sort by priority
    candidates.sort(key=lambda x: x['priority'])

    # Enrich with hand data
    hands_by_id = {h['id']: h for h in hands}
    for c in candidates:
        h = hands_by_id.get(c['id'], {})
        c['date'] = h.get('date', '')
        c['tournament'] = h.get('tournament', '')
        c['cards'] = ' '.join(h.get('cards', []))
        c['position'] = h.get('position', '')
        c['stack_bb'] = round(h.get('stack_bb', 0))
        c['net_bb'] = round(h.get('net_bb', 0), 1)
        c['line'] = h.get('line', '')
        c['board'] = ' '.join(h.get('board', []))
        c['action_summary'] = h.get('action_summary', '')

    # Extract raw HH for top candidates (GTO shortlist = top 9)
    # GTO shortlist prioritizes POSTFLOP decisions over routine preflop opens/folds
    def _gto_priority(c):
        """Lower = higher priority for GTO review."""
        reason = c.get('reason', '')
        h = hands_by_id.get(c['id'], {})
        has_board = len(h.get('board', [])) >= 3
        big = abs(h.get('net_bb', 0)) > 20
        # Routine preflop folds (missed steals, missed pushes) = low priority
        if 'Missed Steal' in reason or 'Missed Push' in reason:
            return 90
        # Postflop mistakes/big pots = highest priority
        if has_board and big:
            return 1
        if 'Missed river value' in reason:
            return 2
        if 'Missed probe' in reason:
            return 3
        if 'CVJ' in reason or 'Iso-Jam' in reason:
            return 4
        if 'Big pot' in reason:
            return 5
        if has_board:
            return 10
        return 50

    # Generate GTO review question per hand
    def _gto_question(c):
        reason = c.get('reason', '')
        h = hands_by_id.get(c['id'], {})
        pos = h.get('position', '?')
        bb = round(h.get('stack_bb', 0))
        pot = h.get('pot_type', 'SRP')
        line = h.get('line', '')
        # CP22-BUG-2: chart notation for cards, descriptive text for board
        # (was raw tokens like "Kc Qc" and "Ts 3c 2c 5c 7d")
        from gem_nicknames import combo_to_chart as _combo_to_chart
        cards = _combo_to_chart(h.get('cards', []))
        _bd = h.get('board') or []
        if isinstance(_bd, list) and _bd:
            _ranks = '-'.join(c[0] for c in _bd[:5])
            _suits = [c[1] if len(c) > 1 else '?' for c in _bd[:5]]
            from collections import Counter as _Ctr
            _sc = _Ctr(_suits).most_common(1)
            _flush_note = ''
            if _sc and _sc[0][1] >= 3:
                _sn = {'s': 'spades', 'h': 'hearts', 'd': 'diamonds', 'c': 'clubs'}.get(_sc[0][0], '')
                _flush_note = f' ({_sc[0][1]} {_sn})'
            board = f'{_ranks} board{_flush_note}'
        else:
            board = ''
        if 'Missed river value' in reason:
            return f'{pot} {pos} {bb}BB — should Hero bet river for value with {cards}?'
        if 'Missed probe' in reason:
            return f'{pot} {pos} {bb}BB — missed turn/river probe. Correct to bet?'
        if 'CVJ' in reason:
            return f'Call villain jam with {cards} at {bb}BB from {pos} — correct call threshold?'
        if 'Iso-Jam' in reason:
            return f'Iso-jam {cards} at {bb}BB from {pos} — threshold for jamming over limp/raise?'
        if 'Big pot' in reason:
            net = h.get('net_bb', 0)
            _on = f' on a {board}' if board else ''
            return (f'{pot} {pos} {bb}BB, {cards}{_on} — {net:+.0f}BB pot. '
                    f'Which street was the EV decision, and was the size right?')
        if 'Cooler' in reason:
            _on = f' on a {board}' if board else ''
            return (f'{pot} {pos} {bb}BB, {cards}{_on} — cooler. Was there a '
                    f'non-stack-off line, or is the loss purely structural?')
        if 'jam' in line:
            return f'{pot} {pos} {bb}BB — jam correct here?'
        if 'cbet' in line:
            return f'{pot} {pos} {bb}BB — c-bet line + sizing check'
        _on = f' on {board}' if board else ''
        return (f'{pot} {pos} {bb}BB, {cards}{_on} — review '
                f'{line or "the line"} street by street')

    # v8.12.4 (QA item 12): equal-priority candidates race in assembly order,
    # so the session's BIGGEST pot could lose its cluster slot to smaller
    # hands. Tie-break by |net_bb| descending, and GUARANTEE the two largest
    # losing pots + every detector CLEAR mistake a shortlist seat (they skip
    # the per-cluster and total caps).
    gto_sorted = sorted(
        candidates,
        key=lambda c: (_gto_priority(c),
                       -abs(hands_by_id.get(c['id'], {}).get('net_bb', 0) or 0)))
    _guaranteed_gto = set()
    _losers = sorted((h for h in hands if (h.get('net_bb') or 0) < -25),
                     key=lambda h: h.get('net_bb', 0))
    _guaranteed_gto.update(h['id'] for h in _losers[:2] if h.get('id'))
    _guaranteed_gto.update(
        m['id'] for m in stats.get('mistakes', [])
        if isinstance(m, dict) and m.get('id')
        and (m.get('confidence', '') or '').upper() == 'CLEAR')
    _cand_ids_gto = {c['id'] for c in candidates}
    for _gid in sorted(_guaranteed_gto - _cand_ids_gto):
        _gh = hands_by_id.get(_gid)
        if not _gh:
            continue
        _gc = {'id': _gid,
               'reason': f"Big pot: {_gh.get('net_bb', 0):+.1f}BB",
               'priority': 1,
               'date': _gh.get('date', ''), 'tournament': _gh.get('tournament', ''),
               'cards': ' '.join(_gh.get('cards', [])),
               'position': _gh.get('position', ''),
               'stack_bb': round(_gh.get('stack_bb', 0)),
               'net_bb': round(_gh.get('net_bb', 0), 1),
               'line': _gh.get('line', ''),
               'board': ' '.join(_gh.get('board', [])),
               'action_summary': _gh.get('action_summary', '')}
        gto_sorted.insert(0, _gc)
    # Diversity cap: max 3 per category to ensure variety
    # B185 (Ron review 2026-05-25): the category was computed for the cap but
    # never written onto the hand, so the IV.3 renderer (which groups by
    # `cluster`) dumped every hand into one "general" bucket. Write a readable
    # cluster label so the shortlist is genuinely clustered by leak pattern.
    _CLUSTER_LABEL = {
        'preflop_fold': 'Pre-flop folds — steal / push spots',
        'cvj':          'Call-villain-jam thresholds',
        'iso_jam':      'Iso-jam thresholds',
        'missed_value': 'Missed river value',
        'missed_probe': 'Missed turn / river probes',
        'big_pot':      'Big-pot lines',
        'cooler':       'Coolers — loss-minimisation review',
        'other':        'Other — line review',
    }
    # v8.12.4 (QA item 13): a "Cooler" candidate where Hero CALLED an all-in
    # as a heavy equity dog (<30% at the all-in) is a calling-discipline
    # question, not a loss-minimisation cooler — route it to the CVJ cluster.
    _eai_eq_gto = {e.get('id'): e.get('hero_equity')
                   for e in (stats.get('eai', {}).get('hands', []) or [])}
    gto_shortlist = []
    cat_counts = {}
    _seen_gto = set()
    for c in gto_sorted:
        if c['id'] in _seen_gto:
            continue
        _is_guaranteed = c['id'] in _guaranteed_gto
        if len(gto_shortlist) >= 9 and not _is_guaranteed:
            continue  # only guaranteed hands may exceed the 9-cap
        reason = c.get('reason', '')
        if 'Missed Steal' in reason or 'Missed Push' in reason:
            cat = 'preflop_fold'
        elif 'CVJ' in reason:
            cat = 'cvj'
        elif 'Iso-Jam' in reason:
            cat = 'iso_jam'
        elif 'Missed river' in reason:
            cat = 'missed_value'
        elif 'Missed probe' in reason:
            cat = 'missed_probe'
        elif 'Big pot' in reason:
            cat = 'big_pot'
        elif 'Cooler' in reason:
            cat = 'cooler'
            _eq_g = _eai_eq_gto.get(c['id'])
            if _eq_g is not None and _eq_g < 0.30:
                cat = 'cvj'
                c['reason'] = (reason + ' / CVJ — called as a '
                               f'{_eq_g*100:.0f}% dog')
        else:
            cat = 'other'
        if cat_counts.get(cat, 0) >= 3 and not _is_guaranteed:
            continue
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        c['cluster'] = _CLUSTER_LABEL.get(cat, cat)
        gto_shortlist.append(c)
        _seen_gto.add(c['id'])
        if len(gto_shortlist) >= 9 and not (_guaranteed_gto - _seen_gto):
            break
    for g in gto_shortlist:
        g['question'] = _gto_question(g)

    gto_ids = [c['id'] for c in gto_shortlist]
    raw_hh = _extract_raw_hh(gto_ids, hh_dir)
    for c in candidates:
        c['raw_hh'] = raw_hh.get(c['id'], '')

    # v7.43 (2026-05-09): augment candidates with analyst-classified hands
    # that the auto-detector missed (III.1 punts via postflop agency,
    # III.4 read-dep calls, I.7 coolers like flush-over-flush). Without
    # this, GTO export drops 50%+ of the analyst-deep-dived hands because
    # they don't trigger detector patterns.
    analyst_pre = (rd.get('analyst_commentary') or
                   _maybe_load_analyst_commentary(stats))
    if isinstance(analyst_pre, dict):
        for hid, cmt in analyst_pre.items():
            if not (isinstance(cmt, dict) and hid.startswith('TM')):
                continue
            if hid in seen_ids:
                continue
            verdict = cmt.get('verdict', '')
            if verdict.startswith('III.1'):
                reason_label = 'Punt (analyst)'
                priority = 1
            elif verdict.startswith('III.4'):
                reason_label = 'Read-dependent (analyst)'
                priority = 2
            elif verdict.startswith('III.5'):
                reason_label = 'Justified variance (analyst)'
                priority = 4
            elif verdict.startswith('I.7'):
                reason_label = 'Cooler (analyst)'
                priority = 4
            else:
                continue
            h = hands_by_id.get(hid, {})
            candidates.append({
                'id': hid, 'reason': reason_label, 'priority': priority,
                'date': h.get('date', ''), 'tournament': h.get('tournament', ''),
                'cards': ' '.join(h.get('cards', [])), 'position': h.get('position', ''),
                'stack_bb': round(h.get('stack_bb', 0)), 'net_bb': round(h.get('net_bb', 0), 1),
                'line': h.get('line', ''), 'board': ' '.join(h.get('board', [])),
                'action_summary': h.get('action_summary', ''),
                'raw_hh': '',  # filled below
            })
            seen_ids.add(hid)

    # v7.43: extract raw_hh for the full export-cap window, not just the
    # 9-hand shortlist. Previous behavior: GTO_EXPORT_CAP=30 but raw_hh
    # only attached to 9 → effective export cap = 9. Now: pre-rank
    # candidates by EV magnitude (proxy: |net_bb| for postflop, with a
    # priority bonus for CLEAR mistakes/punts) and attach raw_hh for the
    # top 30. NOTE: rank by EV magnitude FIRST, priority second — a 0.5BB
    # missed-steal is priority 1 but should not outrank a -45BB punt.
    GTO_EXPORT_CAP_INNER = 30  # mirror of GTO_EXPORT_CAP below
    def _prerank(c):
        # Tier 0: postflop big-impact (|net_bb| > 20 OR analyst-classified
        #         III.1/III.4/I.7) — these are the highest-leverage spots
        # Tier 1: confirmed mistakes with CLEAR confidence
        # Tier 2: missed value, missed probes
        # Tier 3: everything else
        reason = c.get('reason', '')
        net = abs(c.get('net_bb', 0))
        is_postflop_big = net > 20
        is_analyst = '(analyst)' in reason or 'Punt' in reason or 'Cooler' in reason
        if is_postflop_big or is_analyst:
            return (0, -net)  # rank within tier by EV magnitude
        if c.get('priority', 9) == 1:
            return (1, -net)
        if 'Missed river' in reason or 'Missed probe' in reason:
            return (2, -net)
        return (3, -net)
    candidates_for_export = sorted(candidates, key=_prerank)[:GTO_EXPORT_CAP_INNER]
    export_ids = [c['id'] for c in candidates_for_export if not c.get('raw_hh')]
    if export_ids:
        more_raw_hh = _extract_raw_hh(export_ids, hh_dir)
        for c in candidates:
            if not c.get('raw_hh'):
                c['raw_hh'] = more_raw_hh.get(c['id'], '')

    rd['clinical_candidates'] = candidates
    rd['gto_shortlist'] = gto_shortlist

    # ----------------------------------------------------------
    # 10. MISTAKE EV ESTIMATES  (moved before GTO export in v7.14
    #     so export can prioritize by EV-delta)
    # ----------------------------------------------------------
    ev_estimates = []
    ev_by_id = {}  # id → estimated_ev_bb (for GTO export sorting)
    for m in stats.get('mistakes', []):
        mtype = m.get('type', '')
        bb = m.get('stack_bb', 0)
        ev = 0
        reasoning = ''
        if 'Missed Steal' in mtype:
            ev = -1.5
            reasoning = 'Missed ~1.5BB steal equity (blinds + antes)'
        elif 'CVJ' in mtype or 'Iso-Jam' in mtype:
            ev = -3.0
            reasoning = 'Calling outside range costs ~3BB EV vs correct fold'
        elif 'Missed Rejam' in mtype:
            ev = -2.0
            reasoning = 'Flatting instead of rejam loses ~2BB fold equity'
        elif 'J34' in mtype:  # ICM MP Flat
            ev = -2.5
            reasoning = 'Flatting at ICM <=30BB surrenders fold equity vs a 3-bet (~2.5BB)'
        elif 'J35' in mtype:  # Reshove over small jam
            ev = -4.0
            reasoning = 'Reshove over small jam at <30BB commits chips w/o fold equity (~4BB)'
        elif 'J36' in mtype:  # ICM Jam 30-37BB
            ev = -1.5
            reasoning = 'ICM jam 30-37BB: 3-bet sizing likely captures same EV (~1.5BB marginal)'
        elif 'J37' in mtype:  # BvB BB shallow middling jam
            ev = -3.0
            reasoning = 'Middling broadway jam shallow: villain folds worse, calls better (~3BB)'
        elif 'J33' in mtype:  # Weak-blocker jam
            ev = -1.0
            reasoning = 'Weak-blocker jam: thinner than nut-blocker (~1BB marginal)'
        elif 'Weak Ax Flat' in mtype:  # N1 Amit weak-Ax flat vs 3bet/squeeze (v7.29)
            # Squeeze case slightly worse than 3bet (multiway risk amplifies)
            if 'Squeeze' in mtype:
                ev = -2.5
                reasoning = 'Weak Ax flat vs squeeze: multiway OOP postflop with hand that misses most flops (~2.5BB)'
            else:
                ev = -2.0
                reasoning = 'Weak Ax flat vs 3bet: surrenders fold equity, poor SPR realization (~2BB)'
        elif 'MP ATo Flat' in mtype:  # N9 Amit MP ATo flat vs PFR (v7.48)
            ev = -2.0
            reasoning = 'MP ATo flat vs UTG/UTG+1 PFR: dominated by AK/AQ/AJ, poor equity realization OOP (~2BB)'
        elif 'SB Pair 3-bet-fold' in mtype:  # N13 Amit (v7.48)
            ev = -4.0
            reasoning = 'SB pair 3-bet-fold vs LP <=30BB: J11 violation + missed shove FE + flip equity (~4BB)'
        ev_estimates.append({
            'id': m['id'], 'type': mtype, 'estimated_ev_bb': ev,
            'reasoning': reasoning
        })
        ev_by_id[m['id']] = ev
    # Add marginal mistakes
    for m in stats.get('marginal_mistakes', []):
        mtype = m.get('type', '')
        ev = -1.0 if 'Missed Steal' in mtype else -0.5
        ev_estimates.append({
            'id': m['id'], 'type': mtype, 'estimated_ev_bb': ev,
            'reasoning': f'Marginal {mtype}: ~{abs(ev):.1f}BB opportunity cost'
        })
        ev_by_id[m['id']] = ev
    rd['mistake_ev_estimates'] = ev_estimates
    rd['total_mistake_ev'] = round(sum(e['estimated_ev_bb'] for e in ev_estimates), 1)

    # ----------------------------------------------------------
    # 10a. FLAG REVIEWER (v7.20)
    #      Apply the two-tier review layer: raw detector output → review →
    #      {auto_corrected, needs_review, confirmed, detector_bugs}.
    # ----------------------------------------------------------
    try:
        from gem_flag_reviewer import review_candidates
        hands_by_id = {h.get('id'): h for h in hands if h.get('id')}
        # Inject EV estimates into the raw flags so reviewer has them
        ev_by_mid = {e['id']: e['estimated_ev_bb'] for e in ev_estimates}
        raw_mistakes = []
        for m in stats.get('mistakes', []):
            m_copy = dict(m)
            if 'estimated_ev_bb' not in m_copy:
                m_copy['estimated_ev_bb'] = ev_by_mid.get(m.get('id'), 0)
            raw_mistakes.append(m_copy)
        review_output = review_candidates(raw_mistakes, hands_by_id, auto_log_exceptions=False)
        rd['reviewed_mistakes'] = review_output
        rd['reviewed_mistakes_available'] = True
    except Exception as e:
        rd['reviewed_mistakes_available'] = False
        rd['reviewed_mistakes_error'] = str(e)

    # ----------------------------------------------------------
    # 10b. SOLVER AUGMENTATION (v7.15 — prototype, river HU only)
    #      AUGMENTS heuristic EV above; does NOT replace it.
    #      Non-blocking: failures leave breadcrumbs, never crash the report.
    # ----------------------------------------------------------
    rd['solver_augmentations'] = {}
    rd['solver_meta'] = {'available': False, 'reason': 'not_attempted'}
    try:
        from gem_solver_integration import run_on_mistakes, _SOLVER_AVAILABLE, _IMPORT_ERROR
        if not _SOLVER_AVAILABLE:
            rd['solver_meta'] = {'available': False, 'reason': _IMPORT_ERROR or 'unavailable'}
        else:
            solver_mistake_ids = [m['id'] for m in stats.get('mistakes', []) if m.get('id')]
            solver_raw_hh = _extract_raw_hh(solver_mistake_ids, hh_dir)
            session_tag = stats.get('volume', {}).get('date', 'unknown').replace('-', '')
            solver_out_base = '/home/claude/solver_runs'
            augs = run_on_mistakes(
                mistakes=stats.get('mistakes', []),
                hands=hands,
                raw_hh_map=solver_raw_hh,
                out_dir_base=solver_out_base,
                session_tag=session_tag,
                heuristic_ev_map=ev_by_id,
            )
            rd['solver_augmentations'] = augs
            applied = sum(1 for a in augs.values() if a.get('solver_applied'))
            rd['solver_meta'] = {
                'available': True,
                'mistakes_scanned': len(solver_mistake_ids),
                'river_eligible': len(augs),
                'solver_applied': applied,
                'audit_base': os.path.join(solver_out_base, session_tag),
                'session_tag': session_tag,
                'scope': 'river_HU_call_fold_value_bet_bluff_only',
                'caveat': 'chipEV only, no ICM, ranges heuristically constructed',
            }
    except Exception as e:
        rd['solver_meta'] = {'available': False, 'reason': f'exception: {type(e).__name__}: {e}'}

    # ----------------------------------------------------------
    # 10c. DRIFT MONITOR (v7.19 — reads solver_history.csv,
    #      emits heuristic_calibration.md)
    #      Non-blocking: if history absent or monitor fails,
    #      report still generates.
    # ----------------------------------------------------------
    rd['drift_monitor'] = {'available': False, 'reason': 'not_attempted'}
    try:
        from gem_drift_monitor import run as drift_run
        _drift_path = (None if _isolate
                       else '/mnt/project/solver_history.csv')
        if not _drift_path:
            raise FileNotFoundError('isolate mode — skip /mnt/project/')
        drift_out = drift_run(
            history_path=_drift_path,
            out_path='/home/claude/heuristic_calibration.md',
        )
        rd['drift_monitor'] = {'available': True, **drift_out}
    except Exception as e:
        rd['drift_monitor'] = {'available': False, 'reason': f'{type(e).__name__}: {e}'}

    # ----------------------------------------------------------
    # 9. AUTO-GENERATE GTO WIZARD EXPORT  (v7.14: cap at 30, sort by EV-delta)
    # ----------------------------------------------------------
    # Rank candidates by estimated EV impact (descending |ev|) so the
    # first 30 are the highest-leverage review spots. Candidates without
    # EV estimates (coolers, big pots, missed value) get a nominal rank
    # so they're still included but behind confirmed mistakes.
    def _ev_rank(c):
        cid = c.get('id', '')
        ev = ev_by_id.get(cid, 0)
        if ev != 0:
            return (0, -abs(ev))  # tier 0: has EV estimate, sort by |ev| desc
        reason = c.get('reason', '')
        # Tier 1: missed river value / missed probe / cooler — review-worthy but no hard EV
        if 'Missed river' in reason or 'Missed probe' in reason:
            return (1, -c.get('priority', 0))
        if 'Cooler' in reason or 'Big pot' in reason:
            return (2, -abs(c.get('net_bb', 0)))
        return (3, 0)

    candidates_by_ev = sorted(candidates, key=_ev_rank)
    # v7.43 (2026-05-09): guarantee analyst-classified hands always export.
    # Otherwise small-net cooler analysis (e.g., 12BB BTN TT-vs-KK at
    # net=-12BB) gets pushed below the 30-hand cap by big-pot variance
    # winners that don't need analyst review. Analyst hands first, then
    # fill remaining slots from EV-ranked list.
    analyst_hand_ids = set()
    if isinstance(analyst_pre, dict):
        analyst_hand_ids = {hid for hid, cmt in analyst_pre.items()
                            if isinstance(cmt, dict) and hid.startswith('TM')
                            and cmt.get('verdict', '').startswith(('I.7','III.1','III.4','III.5'))}
    _vol_date = (stats.get('volume', {}) or {}).get('date', '')
    _date_compact = _vol_date.replace('-', '') if _vol_date else 'unknown'
    gto_path = f"/home/claude/Claude_GEM_2_GTOWizard_{_date_compact}_V1.txt"
    GTO_EXPORT_CAP = 30  # v7.14: bumped from 9 to 30 per Ron's review preference
    exported = 0
    written_ids = set()
    with open(gto_path, 'w', encoding='utf-8') as f:
        # Pass 1: analyst-classified hands (guaranteed slot)
        for c in candidates_by_ev:
            if c['id'] not in analyst_hand_ids:
                continue
            if c.get('raw_hh') and c['id'] not in written_ids:
                f.write(c['raw_hh'])
                f.write('\n\n\n')
                exported += 1
                written_ids.add(c['id'])
        # Pass 2: fill remaining cap from EV-ranked list (skipping already-written)
        for c in candidates_by_ev:
            if exported >= GTO_EXPORT_CAP: break
            if c['id'] in written_ids: continue
            if c.get('raw_hh'):
                f.write(c['raw_hh'])
                f.write('\n\n\n')
                exported += 1
                written_ids.add(c['id'])
    rd['gto_export_path'] = gto_path
    rd['gto_export_count'] = exported
    rd['gto_export_cap'] = GTO_EXPORT_CAP
    rd['gto_export_analyst_count'] = len(analyst_hand_ids & written_ids)
    # v8.14.1 P0-1: persist the GTO-export id-set so a later --quick analyst
    # re-render can honestly recompute gto_export_analyst_count against the
    # newly-applied analyst commentary (the GTO export itself is not
    # regenerated in --quick). No facts are derived from this at render time.
    rd['_gto_written_ids'] = sorted(written_ids)



    # ----------------------------------------------------------
    # 11. TREND DATA (last 5 sessions)
    # ----------------------------------------------------------
    trend_keys = ['Date', 'Hands', 'BB_per_100', 'VPIP', 'PFR', 'BTN_Open', 'CO_Open',
                  'SB_Steal', 'Flop_CBet_HU', 'Punts_per_100', 'Mistakes_per_100',
                  'SD_Aggressor', 'Non_SD_Win', 'Caller_IP_Flop_Agg', 'VPIP_PFR_Gap',
                  'Top_Leak', 'Premiums_Pct', 'ThreeBet',
                  # v7.66 fix: K2/K3/K6 cumulative-map source columns. The
                  # XIII.5.0 renderer's cross-session estimate reads trend_data,
                  # not session_history directly, so these must be projected
                  # here or the K-rule Cumulative column always renders "—".
                  'Flop_CBet_HU_OOP', 'IP_Stab_Rate', 'Flop_Lead_Rate']
    # Try multiple possible paths
    csv_paths = [session_history_path]
    if not _isolate:
        csv_paths += [
            '/mnt/project/session_history_20260409.csv',
            '/mnt/project/session_history.csv',
        ]
    trend_rows = []
    for cp in csv_paths:
        if cp:
            trend_rows = _load_trend_data(cp, n=5)
            if trend_rows:
                break
    rd['trend_data'] = [{k: row.get(k, '') for k in trend_keys} for row in trend_rows]

    # Compute sparklines (last 5 values for key metrics)
    sparkline_metrics = ['BTN_Open', 'CO_Open', 'SB_Steal', 'Mistakes_per_100',
                         'SD_Aggressor', 'Non_SD_Win', 'VPIP_PFR_Gap',
                         # NEW (Ron 2026-05-16): skill_index family
                         'Skill_Index', 'FinScore_Pct']
    sparklines = {}
    for metric in sparkline_metrics:
        vals = []
        for row in trend_rows:
            v = row.get(metric, '')
            try:
                vals.append(float(v))
            except (ValueError, TypeError):
                pass
        if len(vals) >= 2:
            direction = '📈' if vals[-1] > vals[-2] else '📉' if vals[-1] < vals[-2] else '➡️'
            sparklines[metric] = {
                'values': vals,
                'current': vals[-1],
                'previous': vals[-2],
                'direction': direction,
                'trend_str': ' → '.join(f'{v:.1f}' for v in vals[-3:]) + f' {direction}'
            }
    rd['trend_sparklines'] = sparklines

    # ----------------------------------------------------------
    # 12. HERO CLASSIFICATION
    # ----------------------------------------------------------
    # Compute phase distribution from hands (stats may not have tournament_phases)
    phase_counts = defaultdict(int)
    for h in hands:
        p = h.get('tournament_phase', '')
        if p:
            phase_counts[p] += 1
    total_hands = stats['volume']['hands']

    ft_hands = phase_counts.get('ft_zone', 0)
    hu_hands = sum(1 for h in hands if h.get('n_players', 9) <= 2)
    ft_pct = round(ft_hands / total_hands * 100, 1) if total_hands > 0 else 0

    # v7.31 Patch 5: session-volume gate. The FT-zone% test is meaningful at
    # high session volume (every bullet that doesn't FT contributes 0%). At
    # low bullet count, FT-zone% is mechanically tiny even when play is solid
    # — a single deep run that doesn't quite FT pulls the metric below
    # benchmark. Need >= 20 bullets for the phase-distribution test to
    # discriminate "early bustout pattern" from "ran into variance in this batch".
    n_bullets = stats.get('volume', {}).get('bullets', 0)
    MIN_BULLETS_FOR_HERO_CLASSIFIER = 20
    # v7.33 Bug #3 fix: framing of low-bullet message. Old text said "insufficient
    # volume for classification" which conflicted with skill_band emitting a real
    # verdict at n_hands>=200. Now distinguish: at n_hands>=200 + n_bullets<20,
    # this is a "Variance Session — skill_band has a verdict, structure read does
    # not" rather than "insufficient volume." The skill_band downstream gives the
    # actual skill verdict; this label is purely about FT-zone structure.
    n_hands_total = sum(t.get('hands', 0) for t in stats.get('tournaments', {}).values()) \
                     if isinstance(stats.get('tournaments'), dict) else 0
    if not n_hands_total:
        n_hands_total = stats.get('volume',{}).get('hands', 0)
    if n_bullets < MIN_BULLETS_FOR_HERO_CLASSIFIER:
        if n_hands_total >= 200:
            # Skill_band has a verdict; this is just structure-read insufficient.
            label, emoji = 'Variance Session — skill_band ranks below; structure read needs more bullets', '⚪'
            reasoning = (f'Only {n_bullets} bullets so FT-zone% structure test '
                         f'can not discriminate, but {n_hands_total} hands is '
                         f'enough for the skill_band CI verdict. See skill_band.')
        else:
            label, emoji = 'Variance Session — insufficient volume for classification', '⚪'
            reasoning = (f'Only {n_bullets} bullets and {n_hands_total} hands; '
                         f'need ≥{MIN_BULLETS_FOR_HERO_CLASSIFIER} bullets for '
                         f'structure-read AND ≥200 hands for skill_band verdict.')
    elif ft_pct > 12:
        label, emoji = 'Deep Run Specialist', '🎖️'
        reasoning = f'{ft_pct}% of hands at FT zone (benchmark: 3-8% for solid reg)'
    elif ft_pct >= 5:
        label, emoji = 'Solid Reg', '✅'
        reasoning = f'{ft_pct}% of hands at FT zone (benchmark: 3-8% for solid reg)'
    elif ft_pct >= 3:
        label, emoji = 'Average', '⚪'
        reasoning = f'{ft_pct}% of hands at FT zone (benchmark: 3-8% for solid reg)'
    else:
        label, emoji = 'Early Bustout Pattern', '🔴'
        reasoning = f'{ft_pct}% of hands at FT zone (benchmark: 3-8% for solid reg)'

    rd['hero_classification'] = {
        'label': label, 'emoji': emoji, 'ft_pct': ft_pct,
        'hu_hands': hu_hands,
        'n_bullets': n_bullets,
        'reasoning': reasoning,
    }

    # v7.32 (C11): structure_profile is a clearer alias for hero_classification.
    # The old name was repeatedly misread as a SKILL judgment ("Average") when
    # it's actually a structure metric (FT-zone %). Keep hero_classification as
    # back-compat alias for one version. Also add skill_band — a CI-derived
    # skill judgment from EV-adjusted BB/100.
    rd['structure_profile'] = dict(rd['hero_classification'])  # alias

    # ---- skill_band: CI on EV-adjusted bb-per-hand ----
    # ev_bb_per_100 = mean BB per 100 hands (already in core). Derive a 95% CI
    # using bb-per-hand stdev from per-hand net_bb. For a sample mean, CI is
    # mean ± 1.96 * stdev / sqrt(n). We then scale to bb/100.
    import math as _math
    core = stats.get('core', {}) or {}
    ev_bb100 = core.get('ev_bb_per_100')
    if ev_bb100 is None:
        # fall back to actual bb/100
        ev_bb100 = (stats.get('positional_pnl', {}) or {}).get('OVERALL', {}).get('bb_per_100', 0)
    try:
        ev_bb100_f = float(ev_bb100)
    except (TypeError, ValueError):
        ev_bb100_f = 0.0

    # bb-per-hand stdev across all hands (not just EAI). Need hands list.
    bb_hands = [float(h.get('net_bb') or 0) for h in (hands or [])]
    n_h = len(bb_hands)
    if n_h >= 2:
        mu = sum(bb_hands) / n_h
        var = sum((x - mu) ** 2 for x in bb_hands) / (n_h - 1)
        sd = _math.sqrt(var)
        # SE on mean bb-per-hand
        se_per_hand = sd / _math.sqrt(n_h)
        # 95% CI on bb/100 = (mean ± 1.96*SE) * 100
        margin_bb100 = 1.96 * se_per_hand * 100
        lo = ev_bb100_f - margin_bb100
        hi = ev_bb100_f + margin_bb100
    else:
        lo, hi = ev_bb100_f, ev_bb100_f
        margin_bb100 = 0.0

    # F2 (Ron 2026-05-11): skill_band labels use one-tailed P(skill > 0) from
    # the same SE. The old "Marginal — 95% CI straddles 0" framing reads as a
    # performance verdict when it's really a sample-size verdict; replacing
    # with a confidence percentage like "86% confidence skill is positive"
    # gives Ron a directly actionable number.
    # P(skill > 0) ≈ Φ(ev_bb100 / SE_bb100). Approximate Φ via error function.
    se_bb100 = (margin_bb100 / 1.96) if margin_bb100 > 0 else 0.0001
    z_pos = ev_bb100_f / se_bb100
    # Normal CDF approximation
    p_skill_positive = 0.5 * (1 + _math.erf(z_pos / _math.sqrt(2)))
    conf_pct = int(round(100 * p_skill_positive))

    # Skill band thresholds per Implementation_Prompt_v7_32.md
    if n_h < 200:
        sb_label, sb_emoji = 'Insufficient Sample', '⚪'
        sb_note = f'Need ≥200 hands for skill_band CI to discriminate; got {n_h}.'
    elif lo > 10:
        sb_label, sb_emoji = 'Crusher', '🎖️'
        sb_note = f'95% CI lower bound {lo:.1f} > 10 BB/100'
    elif lo > 5:
        sb_label, sb_emoji = 'Strong Reg', '✅'
        sb_note = f'95% CI lower bound {lo:.1f} > 5 BB/100'
    elif lo > 0:
        sb_label, sb_emoji = 'Solid Reg', '✅'
        sb_note = f'95% CI lower bound {lo:.1f} > 0'
    elif hi < 0:
        sb_label, sb_emoji = 'Losing', '🔴'
        sb_note = f'95% CI upper bound {hi:.1f} < 0'
    else:
        # F2 (Ron 2026-05-11) / F6 (Ron 2026-05-13): one-tailed P(skill > 0).
        # Label clarified to make it explicit this is a SAMPLE-SIZE CI on
        # observed BB/100 — not a variance-adjusted skill point estimate.
        # The two metrics legitimately disagree: skill band CI is about
        # confidence-given-finite-sample, implied true EV is about
        # variance-stripping. Both are surfaced; reader should compare.
        if conf_pct >= 80:
            sb_label, sb_emoji = f'{conf_pct}% confidence BB/100 > 0 (sample-size CI)', '🟢'
        elif conf_pct >= 60:
            sb_label, sb_emoji = f'{conf_pct}% confidence BB/100 > 0 (sample-size CI)', '🟢'
        elif conf_pct >= 40:
            sb_label, sb_emoji = f'{conf_pct}% confidence BB/100 > 0 (sample-size CI)', '🟡'
        elif conf_pct >= 20:
            sb_label, sb_emoji = f'{conf_pct}% confidence BB/100 > 0 (sample-size CI; i.e. {100-conf_pct}% < 0)', '🟡'
        else:
            sb_label, sb_emoji = f'{conf_pct}% confidence BB/100 > 0 (sample-size CI; i.e. {100-conf_pct}% < 0)', '🔴'
        sb_note = (f'95% CI ({lo:.1f}, {hi:.1f}) straddles 0 — single-session sample '
                   f'too small for 95% verdict; one-tailed P(BB/100>0) = {conf_pct}%. '
                   f'Compare against True EV (var-adjusted) for the skill point estimate.')

    rd['skill_band'] = {
        'label': sb_label, 'emoji': sb_emoji,
        'ev_bb_per_100': round(ev_bb100_f, 2),
        'ci_low': round(lo, 2), 'ci_high': round(hi, 2),
        'ci_margin_pp': round(margin_bb100, 2),
        'n_hands': n_h,
        'note': sb_note,
        'p_skill_positive': round(p_skill_positive, 3),
        'confidence_pct': conf_pct,
    }

    # ---- discipline_tier: mistake-rate based classification (v7.43) ----
    # Independent of bb/100 (which has wide CI on single sessions). Based on
    # CLEAR-mistake rate + punt rate, which converge faster than bb/100.
    # Tier thresholds aligned with typical MTT-pro / strong-reg benchmarks.
    # v7.43+ Ron 2026-05-09: mistakes_per_100 must use SURVIVING CLEAR count
    # (mistakes minus needs_review minus auto_corrected minus tail folds), so
    # the tier classification matches the headline mistake count, not the raw
    # detector output. Tail folds are explicitly NOT mistakes (mixed-strategy
    # bottom-of-chart folds).
    raw_mistakes = stats.get('mistakes', []) or []
    rev_block = rd.get('reviewed_mistakes', {})
    needs_keys = {(m.get('id'), m.get('type')) for m in (rev_block.get('needs_review') or [])}
    auto_keys = {(m.get('id'), m.get('type')) for m in (rev_block.get('auto_corrected') or [])}
    # B42/B173: analyst-cleared III.3/4/5 hands must be netted out of BOTH the
    # punt count (B42) and the CLEAR-mistake count (B173) — load the override
    # set first so survivors_dt below can use it. prepare_report_data runs
    # BEFORE analyst_commentary is set on rd (gem_analyzer sets it only after
    # this returns), so load from the JSON file via _maybe_load_analyst_commentary.
    # v8.20 W1A.2A: delegate the canonical confirmed-mistake / punt populations to the ONE owner
    # (gem_final_truth) -- the same single source the post-analyst _refresh_discipline_tier uses, so the
    # prepare-time and refresh-time tiers can never diverge. This pass runs BEFORE analyst_commentary is
    # bound to rd, so the file-loaded commentary is passed explicitly. No independent count formula
    # remains here -- one owner, one definition of "confirmed mistake" and "punt" (disjoint).
    _analyst_pre_dt = (rd.get('analyst_commentary') or
                       _maybe_load_analyst_commentary(stats) or {})
    import gem_final_truth as _ft
    _ft_out_dt = _ft.build_final_truth(rd, stats, hands, analyst_commentary=_analyst_pre_dt)
    clear_surv = _ft_out_dt['reconciliation']['detector_clear_survivors']
    mist_per_100 = 100.0 * clear_surv / max(n_h, 1)
    punts_count_after_override = _ft_out_dt['counts']['PUNT']
    punts_per_100 = float(punts_count_after_override) * 100.0 / max(n_h, 1)
    canonical_mistakes_count = _ft_out_dt['counts']['CONFIRMED_MISTAKE']
    canonical_mistakes_per_100 = 100.0 * canonical_mistakes_count / max(n_h, 1)
    # B130 (Ron 2026-05-20): this is a DISCIPLINE ladder (mistake-rate +
    # punt-rate based) — not a stakes measure. The old top label
    # "Mid-Stakes Pro Tier" implied a stakes axis that doesn't exist here
    # (no Low/High-Stakes counterparts), and collided with the separate
    # buy-in-tier framework in gem_skill_review. Labels are now purely
    # discipline-level descriptors.
    if mist_per_100 < 0.5 and punts_per_100 < 0.1:
        dt_label, dt_emoji = 'Elite Discipline', '🎖️'
        dt_note = (f'CLEAR-mistakes {mist_per_100:.2f}/100 < 0.5 AND punts '
                   f'{punts_per_100:.2f}/100 < 0.1 — pro-tier discipline')
    elif mist_per_100 < 1.0 and punts_per_100 < 0.2:
        dt_label, dt_emoji = 'Strong Discipline', '✅'
        dt_note = (f'CLEAR-mistakes {mist_per_100:.2f}/100, punts {punts_per_100:.2f}/100 '
                   f'— strong-reg discipline')
    elif mist_per_100 < 2.0 and punts_per_100 < 0.5:
        dt_label, dt_emoji = 'Solid Discipline', '✅'
        dt_note = (f'CLEAR-mistakes {mist_per_100:.2f}/100, punts {punts_per_100:.2f}/100 '
                   f'— solid-reg discipline')
    elif mist_per_100 < 4.0 and punts_per_100 < 1.0:
        dt_label, dt_emoji = 'Developing Discipline', '🟡'
        dt_note = (f'CLEAR-mistakes {mist_per_100:.2f}/100, punts {punts_per_100:.2f}/100 '
                   f'— recreational-regular discipline')
    else:
        dt_label, dt_emoji = 'Leak-Heavy', '🔴'
        dt_note = (f'CLEAR-mistakes {mist_per_100:.2f}/100 OR punts {punts_per_100:.2f}/100 '
                   f'too high for stable winrate')
    # B-AVIEL BUG-5 (2026-06-01): canonical_punts_count mirrors canonical_
    # mistakes_count — both use the same analyst-override logic. When no
    # analyst file is present, both default to the raw detector count so
    # strip and body never diverge.
    canonical_punts_count = punts_count_after_override
    canonical_punts_per_100 = float(canonical_punts_count) * 100.0 / max(n_h, 1)
    rd['discipline_tier'] = {
        'label': dt_label, 'emoji': dt_emoji,
        'mistakes_per_100': round(mist_per_100, 2),
        'punts_per_100': round(punts_per_100, 2),
        'clear_mistakes_count': clear_surv,
        # B222: canonical confirmed-mistake count (detector CLEAR + analyst-
        # confirmed III.1/III.2) — matches III.2 Confirmed Mistakes / XIII.4.
        # Display sites must use these, not clear_mistakes_count.
        'canonical_mistakes_count': canonical_mistakes_count,
        'canonical_mistakes_per_100': round(canonical_mistakes_per_100, 2),
        'punts_count': punts_count_after_override,
        # B-AVIEL BUG-5: canonical punt count (analyst-aware).
        'canonical_punts_count': canonical_punts_count,
        'canonical_punts_per_100': round(canonical_punts_per_100, 2),
        'note': dt_note,
    }

    # ---- skill_band_cumulative: aggregate across session_history (v7.43) ----
    # Single-session bb/100 CI is too wide (±30 BB/100 typical) to discriminate
    # tier. Cumulative across recorded sessions tightens the CI substantially.
    # Read session_history if available; if not, leave cumulative empty.
    rd['skill_band_cumulative'] = {'available': False}
    if session_history_path and os.path.exists(session_history_path):
        try:
            import csv as _csv
            cum_hands = 0
            cum_bb_units = 0.0
            cum_mist_units = 0.0
            sessions_used = 0
            recent_hands = 0
            recent_bb_units = 0.0
            recent_mist_units = 0.0
            recent_sessions = []
            current_date_str = stats.get('volume', {}).get('date', '')
            with open(session_history_path) as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    try:
                        h = int(row.get('Hands', 0))
                        bb = float(row.get('BB_per_100', 0) or 0)
                        mt = float(row.get('Mistakes_per_100', 0) or 0)
                        cum_hands += h
                        cum_bb_units += h * bb / 100.0
                        cum_mist_units += h * mt / 100.0
                        sessions_used += 1
                        recent_sessions.append({'h': h, 'bb': bb, 'mt': mt})
                    except Exception:
                        continue
            if cum_hands > 0:
                cum_bb_per_100 = 100.0 * cum_bb_units / cum_hands
                cum_mist_per_100 = 100.0 * cum_mist_units / cum_hands
                # Last 5 sessions (recent trend)
                last5 = recent_sessions[-5:]
                last5_h = sum(s['h'] for s in last5)
                last5_bb = (100.0 * sum(s['h']*s['bb']/100.0 for s in last5) / last5_h
                            if last5_h else 0)
                last5_mt = (100.0 * sum(s['h']*s['mt']/100.0 for s in last5) / last5_h
                            if last5_h else 0)
                # Approx CI on cumulative bb/100 — use ~80 BB/hand stdev proxy
                se_bb_100 = 80.0 / _math.sqrt(cum_hands) * 100
                cum_lo = cum_bb_per_100 - 1.96 * se_bb_100
                cum_hi = cum_bb_per_100 + 1.96 * se_bb_100
                # Tier from cumulative CI lower bound
                if cum_lo > 10:
                    cum_label, cum_emoji = 'Crusher', '🎖️'
                elif cum_lo > 5:
                    cum_label, cum_emoji = 'Strong Reg', '✅'
                elif cum_lo > 0:
                    cum_label, cum_emoji = 'Solid Reg', '✅'
                elif cum_hi < 0:
                    cum_label, cum_emoji = 'Losing', '🔴'
                else:
                    cum_label, cum_emoji = 'Marginal', '🟡'
                rd['skill_band_cumulative'] = {
                    'available': True,
                    'label': cum_label, 'emoji': cum_emoji,
                    'cum_hands': cum_hands,
                    'cum_bb_per_100': round(cum_bb_per_100, 2),
                    'cum_mistakes_per_100': round(cum_mist_per_100, 2),
                    'ci_low': round(cum_lo, 2), 'ci_high': round(cum_hi, 2),
                    'sessions_used': sessions_used,
                    'last5_hands': last5_h,
                    'last5_bb_per_100': round(last5_bb, 2),
                    'last5_mistakes_per_100': round(last5_mt, 2),
                    'note': (f'Cumulative across {sessions_used} sessions / {cum_hands} hands. '
                             f'CI ({cum_lo:.1f}, {cum_hi:.1f}). Last 5 sessions '
                             f'({last5_h} hands): {last5_bb:+.2f} BB/100.'),
                }
        except Exception as e:
            rd['skill_band_cumulative'] = {'available': False, 'error': f'{type(e).__name__}: {e}'}

    # ----------------------------------------------------------
    # 13. TOURNAMENT PHASE DISTRIBUTION (with benchmarks)
    # ----------------------------------------------------------
    benchmarks = {
        'late_reg': (50, 65), 'post_reg': (15, 20), 'bubble_zone': (5, 10),
        'post_bubble': (3, 8), 'ft_zone': (3, 8), 'hu': (0, 2)
    }
    phase_dist = []
    for phase_name in ['late_reg', 'post_reg', 'bubble_zone', 'post_bubble', 'ft_zone']:
        count = phase_counts.get(phase_name, 0)
        phase_pct = round(count / total_hands * 100, 1) if total_hands > 0 else 0
        lo, hi = benchmarks.get(phase_name, (0, 100))
        if phase_pct > hi:
            indicator = '🟢🟢' if phase_name == 'ft_zone' else '🟡'
        elif phase_pct < lo:
            indicator = '🔴' if phase_name == 'ft_zone' else '⚪'
        else:
            indicator = '⚪'
        phase_dist.append({
            'phase': phase_name, 'hands': count, 'pct': phase_pct,
            'benchmark': f'{lo}-{hi}%', 'indicator': indicator
        })
    # Add HU
    phase_dist.append({
        'phase': 'hu', 'hands': hu_hands,
        'pct': round(hu_hands / total_hands * 100, 1) if total_hands > 0 else 0,
        'benchmark': '0-2%', 'indicator': '⚪'
    })
    rd['tournament_phase_dist'] = phase_dist
    # v8.12.4 (QA item 18, Quick Reference Del 6): hero phase-TYPE
    # classification. A late_reg share over 75% combined with an ft_zone
    # share under 3% is the Early Bustout Pattern — chips are committed in
    # the registration phase and rarely survive to where the money is.
    _lr_pct = next((p['pct'] for p in phase_dist if p['phase'] == 'late_reg'), 0)
    _ft_pct = next((p['pct'] for p in phase_dist if p['phase'] == 'ft_zone'), 0)
    if _lr_pct > 75 and _ft_pct < 3:
        rd['phase_pattern'] = {
            'label': 'Early Bustout Pattern',
            'emoji': '🔴',
            'detail': (f"{_lr_pct:.1f}% of hands in late_reg (>75%) with "
                       f"{_ft_pct:.1f}% in ft_zone (<3%) — volume is being "
                       f"committed early and rarely converts to late-phase "
                       f"play. Review early-phase stack preservation before "
                       f"drilling late-phase spots."),
            'caveat': ("Benchmark assumes a multi-session volume profile — "
                       "a single-day late-reg-heavy schedule can trigger "
                       "this pattern by design."),
        }
    else:
        rd['phase_pattern'] = None

    # ----------------------------------------------------------
    # 14. LEAK PERSISTENCE TRACKER (cross-session)
    # ----------------------------------------------------------
    # Parse Top_Leak from session history to track new/recurring/resolved
    # (LEAK_ALIASES, _normalize_leak, _parse_leak_string are now
    # module-level for testability — see top of file.)

    # Build leak history from all sessions
    current_date = stats.get('volume', {}).get('date', '')
    leak_history = []  # [{date, leaks: set()}]
    for row in trend_rows:
        date = row.get('Date', '')
        leak_str = row.get('Top_Leak', '')
        leaks = _parse_leak_string(leak_str)
        leak_history.append({'date': date, 'leaks': leaks})

    # Current session leaks (from the CSV row stats will generate)
    csv_row = stats.get('csv_row', {})
    current_leak_str = csv_row.get('Top_Leak', '')
    current_leaks = _parse_leak_string(current_leak_str)

    # v7.22: all leak detection guarded by min sample size to prevent
    # noise from driving persistence tracker false positives.
    # v8.12.5 (QA item 1 follow-up): the proportion-based rules below now use
    # Wilson 90% CI bounds instead of raw thresholds — the same rule the HU
    # C-Bet promotion has used since v7.43. A leak promotes only when the
    # data is STATISTICALLY past the target line (CI upper < floor for
    # below-floor leaks; CI lower > ceiling for above-ceiling leaks), so a
    # 0.5pp point-estimate miss on a modest sample no longer outranks a
    # well-sampled cluster.
    def _wilson_pl(pct, n, z=1.645):
        """(lo, hi) Wilson 90% CI in percent for a rate given as pct of n."""
        if not n or n <= 0:
            return (0.0, 100.0)
        p = max(0.0, min(1.0, (pct or 0) / 100.0))
        denom = 1 + z * z / n
        centre = p + z * z / (2 * n)
        margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
        return (max(0.0, (centre - margin) / denom) * 100.0,
                min(1.0, (centre + margin) / denom) * 100.0)

    def _ci_below(pct, n, floor):
        return _wilson_pl(pct, n)[1] < floor   # statistically UNDER target

    def _ci_above(pct, n, ceiling):
        return _wilson_pl(pct, n)[0] > ceiling  # statistically OVER target

    core = stats.get('core', {})
    N = stats.get('volume', {}).get('hands', 0) or 0
    if core.get('sd_total', 0) >= 10 and _ci_below(
            core.get('sd_aggressor_pct', 100), core.get('sd_total', 0), 40):
        current_leaks.add('SD Aggressor')
    if core.get('wwsf_total', 0) >= 20 and _ci_below(
            core.get('non_sd_win', 100), core.get('wwsf_total', 0), 25):
        current_leaks.add('Non-SD Win')
    # v7.22: VPIP-PFR Gap leak uses non-blind metric (raw inflated by BB
    # defense). Gap-in-pp is not a simple proportion — keep the threshold.
    if N >= 150 and core.get('vpip_pfr_gap_nonblind', 0) > 4:
        current_leaks.add('VPIP-PFR Gap')
    if core.get('caller_ip_flop_n', 0) >= 10 and _ci_below(
            core.get('caller_ip_flop_agg', 100),
            core.get('caller_ip_flop_n', 0), 30):
        current_leaks.add('Caller IP Agg')
    # Appendix K leak detection (v7.13)
    # K3: IP Stab Rate target 40-60%. Flag if statistically below 40 (n>=15).
    if core.get('ip_stab_n', 0) >= 15 and _ci_below(
            core.get('ip_stab_rate', 100), core.get('ip_stab_n', 0), 40):
        current_leaks.add('IP Stab Rate')
    # K3: Float→Turn Attack target >50%. Flag if statistically below 40 (n>=10).
    if core.get('float_turn_attack_n', 0) >= 10 and _ci_below(
            core.get('float_turn_attack_rate', 100),
            core.get('float_turn_attack_n', 0), 40):
        current_leaks.add('Float Turn Attack')
    # K1: IP Caller x/r MW should be 0-5%. Flag if statistically above 10 (n>=10).
    if core.get('ip_caller_xr_mw_n', 0) >= 10 and _ci_above(
            core.get('ip_caller_xr_mw_rate', 0),
            core.get('ip_caller_xr_mw_n', 0), 10):
        current_leaks.add('MW x/r Over-Aggression')
    # K6: Flop Lead Rate overall should be 2-8%. Flag if statistically above
    # 10 (n>=30, likely leading wrong boards).
    if core.get('flop_lead_n', 0) >= 30 and _ci_above(
            core.get('flop_lead_rate', 0), core.get('flop_lead_n', 0), 10):
        current_leaks.add('Flop Lead Rate')
    # v7.13 drill-derived leak detection
    # Aggressor vs Reactor delta — the single most important stat
    ar = stats.get('aggressor_vs_reactor', {})
    if ar and (ar.get('aggressor_n', 0) + ar.get('reactor_n', 0)) >= 30:
        agg_bbph = ar.get('aggressor_bb_per_hand', 0)
        react_bbph = ar.get('reactor_bb_per_hand', 0)
        # Flag if Aggressor BB/h is not >3x Reactor BB/h (threshold: delta < 2)
        if (agg_bbph - react_bbph) < 2:
            current_leaks.add('Aggressor vs Reactor Delta')
    # Draw Overbet Jams — any occurrence with >=3 hands
    if stats.get('draw_overbet_jams', {}).get('count', 0) >= 3:
        current_leaks.add('Draw Overbet Jams')
    # Passive-Passive-Jam — any occurrence with >=3 hands
    if stats.get('passive_passive_jam', {}).get('count', 0) >= 3:
        current_leaks.add('Passive-Passive-Jam')
    # Triple Barrel called-all-3 win rate <45% with n>=5
    tb = stats.get('triple_barrel_response', {})
    if tb.get('called', {}).get('flag_if_wr_below_45', False):
        current_leaks.add('Triple Barrel Over-Calling')
    # Small-small-JAM anti-pattern
    if stats.get('sizing_consistency', {}).get('small_small_jam_count', 0) >= 2:
        current_leaks.add('Small→Small→JAM')
    sbv = stats.get('sb_bvb_preflop', {})
    if sbv.get('total', 0) > 10 and _ci_below(
            sbv.get('limp_pct', 100), sbv.get('total', 0), 60):
        current_leaks.add('SB BvB')
    # v8.12.4 (QA item 1): the promotion gate had NO rule for the two
    # best-sampled defensive signals, so borderline stats (Non-SD Win at
    # 0.5pp under floor) could be promoted while a 200+-spot over-folding
    # cluster never was. v8.12.5: CI-gated like every other proportion rule.
    # (a) BB defense vs steal — same stat + target band S7.4 renders
    # (floor 55; promote only when statistically under it).
    _bbd_pl = (stats.get('facing_action', {}) or {}).get('bb_defense_vs_steal', {}) or {}
    if (_bbd_pl.get('opps', 0) >= 30
            and _ci_below(_bbd_pl.get('defend_pct', 100),
                          _bbd_pl.get('opps', 0), 55)):
        current_leaks.add('BB Over-Fold')
    # (b) Postflop over-folding vs bets — same buckets + targets S11.1
    # scores ("N of 9 buckets defend below target"). A bucket counts as
    # over-folding only when its call rate is STATISTICALLY below the
    # bucket floor (Wilson upper < floor), not on a point-estimate miss.
    _fb_pl = stats.get('facing_bets', {}) or {}
    _fb_targets_pl = {
        'flop_small': (70, 85), 'flop_medium': (55, 70), 'flop_large': (40, 55),
        'turn_small': (65, 80), 'turn_medium': (50, 65), 'turn_large': (35, 50),
        'river_small': (55, 75), 'river_medium': (45, 65), 'river_large': (30, 50),
    }
    _fb_scored = _fb_over = _fb_opps = 0
    for _fbk, (_fblo, _fbhi) in _fb_targets_pl.items():
        _fbd = _fb_pl.get(_fbk, {}) or {}
        _fbn = _fbd.get('call', 0) + _fbd.get('fold', 0)
        if _fbn < 8:
            continue
        _fb_scored += 1
        _fb_opps += _fbn
        if _ci_below(100.0 * _fbd.get('call', 0) / _fbn, _fbn, _fblo):
            _fb_over += 1
    if _fb_scored >= 5 and _fb_over >= 5 and _fb_opps >= 60:
        current_leaks.add('Postflop Over-Folding')
    cbet = stats.get('cbet', {})
    # v7.43 (Ron 2026-05-09): use Wilson CI lower-bound vs target ceiling
    # instead of raw % threshold. Previous logic `hu_ip_pct > 70` promoted
    # this leak any time raw rate exceeded 70%, even when the 90% CI overlapped
    # the target band (60-75%). Result: false-positive recurring leak even
    # though V.1 status correctly showed 🟢 in-target. Now: only promote if
    # CI lower bound > 75 (target ceiling), meaning we're statistically above
    # target. Same thresholding rule the V.1 status uses.
    hu_ip_opp = cbet.get('hu_ip_opp', 0)
    hu_ip_bet = cbet.get('hu_ip_bet', 0)
    if hu_ip_opp >= 10:
        # Wilson 90% CI lower bound (z=1.645) for hu_ip_bet/hu_ip_opp
        import math as _math
        z = 1.645
        p = hu_ip_bet / hu_ip_opp if hu_ip_opp else 0
        denom = 1 + z*z/hu_ip_opp
        center = (p + z*z/(2*hu_ip_opp)) / denom
        spread = z * _math.sqrt(p*(1-p)/hu_ip_opp + z*z/(4*hu_ip_opp*hu_ip_opp)) / denom
        ci_lower = max(0.0, (center - spread) * 100)
        # Promote only if CI lower bound clears target ceiling (75%).
        if ci_lower > 75:
            current_leaks.add('HU C-Bet')

    # v7.43 (Ron 2026-05-09): SB BvB and SB Pot-Entry dedup. Both metrics
    # measure SB defense quality from different angles — BvB-distribution drift
    # and overall SB pot-entry rate. They share root cause: under-defending SB.
    # If both fire, keep BvB (more actionable: explicit raise/limp/fold split
    # vs J29) and suppress Pot-Entry to a dependent finding so the leak count
    # isn't inflated by double-counting one underlying behavior.
    if 'SB BvB' in current_leaks and 'SB Pot-Entry' in current_leaks:
        current_leaks.discard('SB Pot-Entry')
        # Keep a tag in the synthesis-friendly note that Pot-Entry was
        # suppressed by BvB co-fire (renderer can surface this if needed).
        rd_meta_tags = stats.setdefault('_leak_dedup_notes', [])
        rd_meta_tags.append({
            'suppressed': 'SB Pot-Entry',
            'reason': 'co-fired with SB BvB (same root cause: under-defending SB)',
            'kept': 'SB BvB'
        })

    # Classify each current leak
    all_past_leaks = set()
    recent_leaks = set()  # last 3 sessions (excluding current)
    past_only = [lh for lh in leak_history if lh['date'] != current_date]
    for i, lh in enumerate(past_only):
        all_past_leaks.update(lh['leaks'])
        if i >= len(past_only) - 3:
            recent_leaks.update(lh['leaks'])

    leak_tracker = []
    for leak in sorted(current_leaks):
        if leak in recent_leaks:
            status = '🔴 Recurring'
            # Count consecutive sessions (from most recent backwards, excluding current)
            streak = 0
            for lh in reversed(past_only):
                if leak in lh['leaks']:
                    streak += 1
                else:
                    break
            note = f'Flagged {streak + 1} sessions in a row (incl current)' if streak > 0 else 'Appeared in recent sessions'
        elif leak in all_past_leaks:
            status = '🟡 Returned'
            note = 'Previously flagged, was absent, now back'
        else:
            status = '🆕 New'
            note = 'First time flagged'
        leak_tracker.append({
            'leak': leak, 'status': status, 'note': note
        })

    # Check for resolved leaks (were in previous session but not in current)
    # Skip the last row if it's the current session date (already in CSV)
    # B122 (Ron 2026-05-20): exclude dedup-suppressed leaks. A leak folded into
    # a co-firing leak (e.g. SB Pot-Entry suppressed by SB BvB, same root
    # cause) is NOT resolved — its underlying metric is still failing. Marking
    # it "✅ Resolved / now in range" while _leak_progress still reported it
    # "6.7pp below floor" was self-contradictory. The suppressed leak is
    # already represented by the leak that absorbed it.
    _suppressed_leaks = {d.get('suppressed')
                         for d in (stats.get('_leak_dedup_notes') or [])
                         if d.get('suppressed')}
    prev_session_leaks = set()
    for lh in reversed(leak_history):
        if lh['date'] != current_date and lh['leaks']:
            prev_session_leaks = lh['leaks']
            break
    for leak in sorted(prev_session_leaks - current_leaks - _suppressed_leaks):
        leak_tracker.append({
            'leak': leak, 'status': '✅ Resolved', 'note': 'Was flagged last session, now in range'
        })

    # Build full history timeline for report
    leak_timeline = []
    for lh in leak_history[-5:]:
        leak_timeline.append({
            'date': lh['date'],
            'leaks': sorted(lh['leaks'])
        })
    leak_timeline.append({
        'date': stats.get('volume', {}).get('date', 'current'),
        'leaks': sorted(current_leaks)
    })

    # v7.14: Progress-vs-target for each current leak.
    # Maps canonical leak name → (current_value, target_range_string, gap_formula).
    # Gap formula returns a human-readable "Xpp below floor" / "at target" string.
    def _leak_progress(leak_name):
        """Return {current, target, gap, direction} for a leak name."""
        core = stats.get('core', {})
        pos = stats.get('positions', {})
        cbet = stats.get('cbet', {})
        # Canonical mapping — current value, target range (lo, hi), higher_is_better
        # v7.22: use scoped metrics (matches CSV + stat_health logic)
        LEAK_TARGETS = {
            # name: (current_value, target_lo, target_hi, higher_better, n, anchor_section, ev_per100_estimate)
            # ev_per100_estimate: rough BB/100 cost when this leak is fully present
            # (gap-pp × scaling-factor). Used by renderer to surface the leak's $$$
            # weight per Ron's B18 request. Estimates are conservative.
            'Non-SD Win':     (core.get('non_sd_win', 0), 25, 35, True,
                              core.get('wwsf_total', 0), 'sec-iii-2', 0.4),
            'SD Aggressor':   (core.get('sd_aggressor_pct', 0), 40, 100, True,
                              core.get('sd_total', 0), 'sec-iii-2', 0.6),
            'VPIP-PFR Gap':   (core.get('vpip_pfr_gap_nonblind', 0), 0, 4, False,
                              N, 'sec-iv-1', 0.5),
            'Caller IP Agg':  (core.get('caller_ip_flop_agg', 0), 30, 40, True,
                              core.get('caller_ip_flop_n', 0), 'sec-v-3', 0.3),
            'HU C-Bet':       (cbet.get('hu_ip_pct', 0), 60, 65, True,
                              cbet.get('hu_ip_opp', 0), 'sec-v-1', 0.35),
            'MW C-Bet':       (cbet.get('mw_pct', 0), 30, 40, True,
                              cbet.get('mw_opp', 0), 'sec-v-1', 0.25),
            'BTN Open':       (pos.get('BTN', {}).get('open_pct', 0), 45, 65, True,
                              pos.get('BTN', {}).get('fi_opps', 0), 'sec-iv-1', 0.4),
            'CO Open':        (pos.get('CO', {}).get('open_pct', 0), 25, 40, True,
                              pos.get('CO', {}).get('fi_opps', 0), 'sec-iv-1', 0.3),
            'SB Pot-Entry':   (pos.get('SB', {}).get('open_pct', 0), 70, 95, True,
                              pos.get('SB', {}).get('fi_opps', 0), 'sec-iv-3', 0.5),
            'WWSF':           (core.get('wwsf', 0), 42, 48, True,
                              core.get('wwsf_total', 0), 'sec-vii', 0.4),
        }
        # v8.12.4 (QA item 21): leaks the promotion gate can flag but the
        # progress table had no metric spec for — they rendered as n=0 /
        # current "—" while the body section showed real samples.
        _sbv_lp = stats.get('sb_bvb_preflop', {}) or {}
        if _sbv_lp.get('total'):
            LEAK_TARGETS['SB BvB'] = (
                _sbv_lp.get('limp_pct', 0), 60, 90, True,
                _sbv_lp.get('total', 0), 'sec-7-4', 0.5)
        _bbd_lp = (stats.get('facing_action', {}) or {}).get('bb_defense_vs_steal', {}) or {}
        if _bbd_lp.get('opps'):
            LEAK_TARGETS['BB Over-Fold'] = (
                _bbd_lp.get('defend_pct', 0), 55, 65, True,
                _bbd_lp.get('opps', 0), 'sec-7-4', 0.5)
        _fb_lp = stats.get('facing_bets', {}) or {}
        if _fb_lp:
            _fb_t_lp = {
                'flop_small': (70, 85), 'flop_medium': (55, 70), 'flop_large': (40, 55),
                'turn_small': (65, 80), 'turn_medium': (50, 65), 'turn_large': (35, 50),
                'river_small': (55, 75), 'river_medium': (45, 65), 'river_large': (30, 50),
            }
            _c_lp = sum((d or {}).get('call', 0) for d in _fb_lp.values() if isinstance(d, dict))
            _n_lp = sum((d or {}).get('call', 0) + (d or {}).get('fold', 0)
                        for d in _fb_lp.values() if isinstance(d, dict))
            if _n_lp:
                _wlo_lp = sum(_fb_t_lp.get(k, (50, 70))[0]
                              * ((d or {}).get('call', 0) + (d or {}).get('fold', 0))
                              for k, d in _fb_lp.items() if isinstance(d, dict)) / _n_lp
                _whi_lp = sum(_fb_t_lp.get(k, (50, 70))[1]
                              * ((d or {}).get('call', 0) + (d or {}).get('fold', 0))
                              for k, d in _fb_lp.items() if isinstance(d, dict)) / _n_lp
                LEAK_TARGETS['Postflop Over-Folding'] = (
                    round(100.0 * _c_lp / _n_lp, 1), round(_wlo_lp), round(_whi_lp),
                    True, _n_lp, 'sec-11-1', 0.6)
        if core.get('ip_stab_n'):
            LEAK_TARGETS['IP Stab Rate'] = (
                core.get('ip_stab_rate', 0), 40, 60, True,
                core.get('ip_stab_n', 0), 'sec-10-1', 0.3)
        if core.get('float_turn_attack_n'):
            LEAK_TARGETS['Float Turn Attack'] = (
                core.get('float_turn_attack_rate', 0), 40, 100, True,
                core.get('float_turn_attack_n', 0), 'sec-10-1', 0.3)
        if core.get('flop_lead_n'):
            LEAK_TARGETS['Flop Lead Rate'] = (
                core.get('flop_lead_rate', 0), 2, 8, False,
                core.get('flop_lead_n', 0), 'sec-10-2', 0.25)
        if leak_name not in LEAK_TARGETS:
            return None
        spec = LEAK_TARGETS[leak_name]
        current, tgt_lo, tgt_hi, higher_better = spec[:4]
        n_obs = spec[4] if len(spec) > 4 else 0
        anchor = spec[5] if len(spec) > 5 else None
        ev_factor = spec[6] if len(spec) > 6 else 0.3
        target_str = f'{tgt_lo}-{tgt_hi}%'
        if higher_better:
            if current >= tgt_lo:
                gap_str, direction = f'at target ({current}%)', 'in_range'
                gap_pp = 0
            else:
                gap_pp = round(tgt_lo - current, 1)
                gap_str = f'{gap_pp}pp below floor'
                direction = 'below'
        else:
            if current <= tgt_hi:
                gap_str, direction = f'at target ({current}%)', 'in_range'
                gap_pp = 0
            else:
                gap_pp = round(current - tgt_hi, 1)
                gap_str = f'{gap_pp}pp above ceiling'
                direction = 'above'
        # B18: rough BB/100 cost estimate = gap_pp × ev_factor
        ev_cost_per100 = round(abs(gap_pp) * ev_factor, 2) if gap_pp else 0
        return {
            'current': current, 'target': target_str,
            'gap': gap_str, 'direction': direction,
            'n': n_obs, 'anchor': anchor,
            'ev_cost_per100_bb': ev_cost_per100,
            'gap_pp': gap_pp,
        }

    # Attach progress info to each tracker entry
    for lt in leak_tracker:
        prog = _leak_progress(lt['leak'])
        if prog:
            lt['current'] = prog['current']
            lt['target'] = prog['target']
            lt['gap'] = prog['gap']
            lt['direction'] = prog['direction']
            # B18 (v7.46): enriched fields
            lt['n'] = prog.get('n', 0)
            lt['anchor'] = prog.get('anchor')
            lt['ev_cost_per100_bb'] = prog.get('ev_cost_per100_bb', 0)
            lt['gap_pp'] = prog.get('gap_pp', 0)

    # B122 (Ron 2026-05-20): a leak is only genuinely "✅ Resolved" if its
    # underlying metric is back in range. A leak that merely dropped off the
    # Top_Leak shortlist (other leaks ranked higher this session) while its own
    # metric is still below floor was being mislabeled "Resolved / now in
    # range" while the attached progress simultaneously showed it "Xpp below
    # floor" — the contradiction Ron flagged on SB Pot-Entry. Drop those
    # false-resolved entries: they are neither a current top leak nor
    # genuinely fixed, so they do not belong in the tracker as resolved.
    leak_tracker = [lt for lt in leak_tracker
                    if not (lt['status'].startswith('✅')
                            and lt.get('direction') not in (None, 'in_range'))]

    rd['leak_persistence'] = {
        'current_leaks': sorted(current_leaks),
        'tracker': leak_tracker,
        'timeline': leak_timeline,
        'summary': {
            'new': sum(1 for lt in leak_tracker if '🆕' in lt['status']),
            'recurring': sum(1 for lt in leak_tracker if '🔴' in lt['status']),
            'returned': sum(1 for lt in leak_tracker if '🟡' in lt['status']),
            'resolved': sum(1 for lt in leak_tracker if '✅' in lt['status']),
        }
    }

    # v7.30: build session_history + run_log row dicts for standalone CSV export.
    # These were previously embedded in the MD report; Ron asked to surface them
    # as click-to-add-to-project files instead. Filenames carry the date range
    # so they're self-identifying.
    rd['session_history_row'] = _build_session_history_row(stats, hands)
    rd['run_log_row'] = _build_run_log_row(stats, hands, hh_dir)

    # v7.31: GTO texture archetype compliance findings (Dave taxonomy).
    # Pull directly from analyzer output. We also build a flattened
    # 'actionable_findings' list filtered to verdict='deviation' with
    # sufficient or thin samples, sorted by sample size and severity for
    # the report draft. Tagged [GTO ref] in the report — solver-derived,
    # not population/exploit.
    gto_findings = stats.get('texture_gto_findings', {})
    gto_meta = stats.get('texture_gto_meta', {})
    actionable = []
    for arch_id, sides in gto_findings.items():
        for side, b in sides.items():
            if b.get('verdict') != 'deviation':
                continue
            if b.get('sample_size_label') == 'small':
                # n<3: keep but mark; report draft will tag with ⚪
                pass
            actionable.append({
                'archetype': arch_id,
                'side': side.upper(),
                'n_opps': b.get('n_opps', 0),
                'cbet_pct': b.get('cbet_pct'),
                'target_freq_pct': b.get('target_freq_pct'),
                'freq_compliant': b.get('freq_compliant'),
                'sizing_compliance_pct': b.get('sizing_compliance_pct'),
                'sample_size_label': b.get('sample_size_label'),
                'depth_bands_seen': b.get('depth_bands_seen', []),
                # confidence label aligned with v7.30 quality gate vocabulary
                'quality_label': (
                    '⚪ small sample' if b.get('sample_size_label') == 'small'
                    else '🟡 detector-only' if b.get('sample_size_label') == 'thin'
                    else '✅ verified'
                ),
            })
    # Sort: sufficient samples first, then thin, then small, deviation magnitude
    # tiebreaker (worst freq miss first).
    sample_rank = {'sufficient': 0, 'thin': 1, 'small': 2}
    def _sort_key(f):
        return (
            sample_rank.get(f['sample_size_label'], 3),
            -(f.get('n_opps') or 0),
        )
    actionable.sort(key=_sort_key)
    rd['texture_gto'] = {
        'meta': gto_meta,
        'findings': gto_findings,
        'actionable_findings': actionable,
        'archetype_examples': {
            a['id']: a.get('example', '')
            for a in (
                __import__('gem_textures').all_archetypes()
                if gto_meta.get('source') else []
            )
        } if gto_meta.get('source') else {},
    }

    # ====================================================================
    # v7.45 (Ron 2026-05-11): APPENDIX HAND DETAILS — seat info for rich
    # preflop action display in XIV appendix (stacks + bet sizes + bounty
    # coverage hints).
    # ====================================================================
    analyst_pre_app = (rd.get('analyst_commentary') or
                       _maybe_load_analyst_commentary(stats) or {})
    rev_block = rd.get('reviewed_mistakes', {}) or {}
    # A3: Source-aware appendix collector replaces scattered appendix_ids sets
    _collector = AppendixCollector()
    appendix_ids = set()       # legacy alias for backward compat during transition
    appendix_ids_full = set()  # legacy alias
    for m in (rev_block.get('needs_review') or []):
        if m.get('id'):
            appendix_ids.add(m.get('id'))
            appendix_ids_full.add(m.get('id'))
    for hid, cmt in analyst_pre_app.items():
        if isinstance(cmt, dict) and hid.startswith('TM'):
            appendix_ids.add(hid)
            appendix_ids_full.add(hid)
    # Tier 2 (Ron 2026-05-11): broad collection — any hand_id referenced
    # in body sections gets a compact lookup stub so EVERY citation links.
    # Sources: bust hands, coolers, mistakes list, deviations, clinical
    # examples, missed check-raises.
    for h in (hands or []):
        # Bust hands (>25BB lost) — referenced from I.3
        if (h.get('net_bb') or 0) < -25:
            appendix_ids.add(h.get('id', ''))
    # coolers detail list (when present) — rd.get('cooler_details') is the
    # per-hand list; stats['coolers'] is just summary stats
    for c in (rd.get('cooler_details') or stats.get('cooler_details') or []):
        if isinstance(c, dict) and c.get('id'):
            appendix_ids.add(c.get('id'))
    for m in (stats.get('mistakes', []) or []):
        if isinstance(m, dict) and m.get('id'):
            appendix_ids.add(m.get('id'))
    for d in (stats.get('preflop_deviations', []) or []):
        if isinstance(d, dict) and d.get('id'):
            appendix_ids.add(d.get('id'))
    # cr_evidence_hands (VIII.4 missed check-raise candidates)
    for c in (rd.get('cr_evidence_hands') or []):
        if isinstance(c, dict) and c.get('id'):
            appendix_ids.add(c.get('id'))
    # MDA exploits — aligned + missed lists (XII MDA Overlay). B123 (Ron
    # 2026-05-20): the data key is 'missed', not 'opposed' — the old tuple
    # silently scanned nothing, so the 8 "MDA exploits missed" hands cited in
    # Top Leaks had no appendix entry and the links were dead.
    for kind in ('aligned', 'missed'):
        for ex in (stats.get('mda_exploits', {}) or {}).get(kind, []) or []:
            if isinstance(ex, dict) and ex.get('hand_id'):
                appendix_ids.add(ex.get('hand_id'))
    # B63 (v7.48, Ron 2026-05-12) — DEFERRED to post-aggression block below
    # (v7.50 B71 fix): the original placement here ran BEFORE
    # rd['aggression_analysis'] was populated (computed at end of function),
    # so _agg_buckets was always empty and no IDs got promoted. The actual
    # promotion now happens after the aggression detector runs, at the
    # bottom of this function.
    # Ron 2026-05-11 (A6): deep-scan rd + stats for any embedded hand_id-
    # shaped fields. Covers VII sizing-consistency tables, deep-run tables,
    # MDA-deviation example hands, big-win highlights, anything we missed.
    def _scan_for_hand_ids(obj, depth=0):
        if depth > 6: return  # bound recursion
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ('id', 'hand_id') and isinstance(v, str) and v.startswith('TM'):
                    appendix_ids.add(v)
                elif isinstance(v, str) and v.startswith('TM') and len(v) > 8:
                    # any TM-prefix string field (defensive — example_hands etc.)
                    appendix_ids.add(v)
                elif isinstance(v, (dict, list)):
                    _scan_for_hand_ids(v, depth + 1)
        elif isinstance(obj, list):
            for x in obj: _scan_for_hand_ids(x, depth + 1)
    _scan_for_hand_ids(rd)
    _scan_for_hand_ids(stats)
    # Clinical examples / check-raise missed live under rd
    for c in (rd.get('clinical_examples', []) or []):
        if isinstance(c, dict) and c.get('id'):
            appendix_ids.add(c.get('id'))
        elif isinstance(c, str) and c.startswith('TM'):
            appendix_ids.add(c)
    for c in (rd.get('check_raise_missed', []) or []):
        if isinstance(c, dict) and c.get('id'):
            appendix_ids.add(c.get('id'))
        elif isinstance(c, str) and c.startswith('TM'):
            appendix_ids.add(c)
    # B118 (Ron 2026-05-20): auto-detected punts (stats['punts']) are cited in
    # III.1 with a #sec-app-hand link — they MUST have an appendix entry or the
    # link is dead ("hand has no full detail in the examples"). A winning punt
    # (e.g. a re-jam that held) was being dropped by the 250-cap because it is
    # not net<-25 / mistake / cooler, so it never reached the priority list.
    # Add punts to appendix_ids_full → guaranteed survival + full-detail grid.
    # B123 (Ron 2026-05-20): same guarantee for MDA-exploit hands — they are
    # linked from the "Top Leaks → MDA exploits missed" row and were also
    # being dropped by the cap (not net<-25 / mistake / cooler). Any hand
    # cited in the Top-Leaks block must be reachable from the report.
    for _p in ((stats.get('punts') or {}).get('hands', []) or []):
        if isinstance(_p, dict) and _p.get('id'):
            appendix_ids.add(_p['id'])
            appendix_ids_full.add(_p['id'])
    for _kind in ('aligned', 'missed'):
        for _ex in (stats.get('mda_exploits', {}) or {}).get(_kind, []) or []:
            if isinstance(_ex, dict) and _ex.get('hand_id'):
                appendix_ids.add(_ex['hand_id'])
                appendix_ids_full.add(_ex['hand_id'])
    # Cap at 250 — beyond that the report bloats. Keep priority hands FIRST,
    # then fill remaining slots from the broader set (previous logic
    # replaced with a 37-id subset which dropped most referenced hands).
    # v8.12.4 (QA item 19): with lazy hand cards ON, a referenced hand costs
    # ~0.6KB compressed — the 250 cap was orphaning 350+ hands cited by
    # count-cell popups / villain evidence (one whole tournament's ids dead).
    # Lazy builds get a 1000 cap; classic builds keep 250. GEM_APPENDIX_CAP
    # overrides both.
    _lazy_on_cap = os.environ.get('GEM_LAZY_HANDS', '1') == '1'
    try:
        _app_cap = int(os.environ.get('GEM_APPENDIX_CAP', '0') or '0')
    except ValueError:
        _app_cap = 0
    if _app_cap <= 0:
        _app_cap = 1000 if _lazy_on_cap else 250
    appendix_ids.discard('')
    appendix_ids.discard(None)
    if len(appendix_ids) > _app_cap:
        priority = list(appendix_ids_full)
        priority += [h.get('id','') for h in (hands or []) if (h.get('net_bb') or 0) < -25]
        priority += [m.get('id','') for m in (stats.get('mistakes',[]) or []) if isinstance(m, dict)]
        priority += [c.get('id','') for c in (rd.get('cooler_details') or stats.get('cooler_details') or []) if isinstance(c, dict)]
        seen = set(); ordered = []
        for hid in priority:
            if hid and hid not in seen:
                seen.add(hid); ordered.append(hid)
        # Fill remaining slots from broader appendix_ids set
        for hid in sorted(appendix_ids):
            if hid not in seen and len(ordered) < _app_cap:
                seen.add(hid); ordered.append(hid)
        appendix_ids = set(ordered)
    # B53 fix (v7.47, Ron 2026-05-12): use the hh_dir parameter that's
    # already in scope. Previously hardcoded /home/claude/session_files →
    # /mnt/user-data/uploads, both of which miss the actual session dir on
    # most runs, leaving appendix_hand_details empty and the per-street
    # action lines blank. (Reproduces as empty FLOP/TURN/RIVER blocks under
    # every hand in XIV.A — Ron flagged 2026-05-12.)
    app_hh_dir = hh_dir if (hh_dir and os.path.isdir(hh_dir)) else '/home/claude/session_files'
    if not os.path.isdir(app_hh_dir):
        app_hh_dir = '/mnt/user-data/uploads'
    # A2b-4: try action ledger path first (no file re-read), fall back to raw
    _hands_by_id_app = {h.get('id'): h for h in (hands or [])}
    appendix_details = {}
    _ledger_hits = 0
    for hid in appendix_ids:
        _hdict = _hands_by_id_app.get(hid)
        if _hdict and _hdict.get('action_ledger'):
            _built = _build_seat_info_from_hand(_hdict)
            if _built:
                appendix_details[hid] = _built
                _ledger_hits += 1
                continue
    # Fall back to raw HH for any hands not covered by ledger
    _missing_raw = appendix_ids - set(appendix_details.keys())
    if _missing_raw:
        raw_hhs_app = _extract_raw_hh(_missing_raw, app_hh_dir)
        for hid, hh_text in raw_hhs_app.items():
            try:
                appendix_details[hid] = _parse_hand_seat_info(hh_text, hero_name=_pname)
            except Exception as e:
                appendix_details[hid] = {'error': str(e)}
    # B-V10 FEATURE (2026-06-01): attach EAI equity to appendix_hand_details
    # so the hand grid can show "Hero equity: X%" on all-in hands.
    _eai_hands = (stats.get('eai') or {}).get('hands') or []
    for _e in _eai_hands:
        _eid = _e.get('id')
        if _eid and _eid in appendix_details:
            _ad = appendix_details[_eid]
            if _e.get('hero_equity') is not None:
                _ad['eai_hero_equity'] = _e['hero_equity']
                _ad['eai_street'] = _e.get('street', '')
                _ad['eai_is_favorite'] = _e.get('is_favorite', False)
                _ad['eai_category'] = _e.get('category', '')
                _ad['eai_suckout'] = _e.get('suckout', '')
                _ad['eai_n_allin'] = _e.get('n_allin', 2)
    rd['appendix_hand_details'] = appendix_details
    rd['appendix_hand_ids_full'] = sorted(appendix_ids_full)
    rd['appendix_hand_ids_all'] = sorted(appendix_ids)

    # v8.12.0: PKO research layer — single counting source for the S4 tables,
    # snapshot, and the hand-detail PKO pill. Fail-soft per release guardrail:
    # an aggregation failure omits the S4 research tables (renderer checks
    # rd['pko_research']['enabled']) and never restores removed discounts.
    try:
        import gem_pko_research as _pko_mod
        rd['pko_research'] = _pko_mod.enrich_pko_contexts(
            hands, stats, rd.get('pot_odds_by_hand'))
    except Exception as _pko_e:
        import sys as _pko_sys
        print(f"  WARN: pko_research enrichment failed: {_pko_e}",
              file=_pko_sys.stderr)
        rd['pko_research'] = {'enabled': False, 'error': str(_pko_e)}

    # v8.12.1 P2: review-tier flags (G4/G6-lite/G12) — cautious-copy notes
    # only; never mistakes, never punts, never BB/100.
    try:
        import gem_review_flags as _rvf
        rd['review_flags'] = _rvf.build_review_flags(hands)
        # v8.12.2 P4: analyst worksheet only — never rendered.
        rd['p4_worksheet'] = _rvf.build_p4_worksheet(hands, stats)
        import sys as _p4s
        _p4w = rd['p4_worksheet']
        print(f"  P4 worksheet: "
              f"{len(_p4w['g11_overbluff_candidates'])} overbluff cand, "
              f"{len(_p4w['g14_post_loss_clusters'])} post-loss clusters, "
              f"G15 cover-hands={_p4w['g15_big_stack_bubble'].get('bubble_hands_as_cover', 0)}",
              file=_p4s.stderr)
    except Exception:
        rd['review_flags'] = {}

    # v8.12.0 P0: coverage audit — read-only measurement, runs ONLY when the
    # --coverage-audit flag set GEM_COVERAGE_AUDIT=1. JSON + stderr output;
    # zero report-data mutation.
    try:
        import os as _ca_os2
        if _ca_os2.environ.get('GEM_COVERAGE_AUDIT') == '1':
            import gem_coverage_audit as _ca_mod
            _ca_mod.run_coverage_audit(hands, stats, rd, hh_dir)
    except Exception as _ca_e:
        import sys as _ca_sys
        print(f"  WARN: coverage audit failed: {_ca_e}", file=_ca_sys.stderr)

    # ====================================================================
    # v7.45 (Ron 2026-05-11): RESULTS ATTRIBUTION — decompose surface BB/100
    # into skill / variance / mistakes / tail-folds. Replaces the simpler
    # luck-vs-skill bullet in TL;DR.
    # ====================================================================
    n_hands_attr = stats.get('volume', {}).get('hands', 0) or 0
    bb100_actual = stats.get('core', {}).get('bb_per_100', 0)
    surface_bb_total = bb100_actual * n_hands_attr / 100.0

    eai_block = stats.get('eai_ev_adjusted', {}) or {}
    var_pf = eai_block.get('approx_bb_variance_pf', 0) or 0
    var_post = eai_block.get('approx_bb_variance_post', 0) or 0
    eai_variance_bb = var_pf + var_post  # signed: negative = variance hurt
    # v8.12.8 (handover Issue 2): surface the equity-method stamp so the
    # renderer can mark True EV approximate when the engine was degraded.
    rd['eai_equity_method'] = eai_block.get('equity_method') or ''
    rd['eai_equity_degraded'] = bool(
        rd['eai_equity_method'] and rd['eai_equity_method'] != 'phevaluator')

    # Mistake EV split: CLEAR/MARGINAL non-tail vs tail folds (info-only)
    raw_mist_attr = stats.get('mistakes', []) or []
    mev_estimates = {m.get('id'): m for m in rd.get('mistake_ev_estimates', [])}
    needs_keys_attr = {(m.get('id'), m.get('type')) for m in (rev_block.get('needs_review') or [])}
    auto_keys_attr = {(m.get('id'), m.get('type')) for m in (rev_block.get('auto_corrected') or [])}
    # B173 (Ron 2026-05-24): exclude analyst-cleared III.3/4/5 hands from the
    # attribution mistake bucket — same netting XIII.4.1 / III header / the
    # discipline tier apply. Without this, an analyst-cleared CLEAR flag
    # (91328435) inflated the Mistake-EV count + cost above XIII.4's "6".
    _override_attr = {hid for hid, cmt in analyst_pre_app.items()
                      if isinstance(cmt, dict)
                      and cmt.get('verdict', '').startswith(('III.3', 'III.4', 'III.5'))}
    survivors_attr = [m for m in raw_mist_attr
                      if (m.get('id'), m.get('type')) not in needs_keys_attr
                      and (m.get('id'), m.get('type')) not in auto_keys_attr
                      and m.get('id') not in _override_attr]
    # v7.61: per-mistake cEV. v7.63 (Ron 2026-05-21): the cEV denominator is
    # the mistake's OWN tournament starting stack — NOT the session mean. A
    # late-game mistake's bb_blind is huge; dividing ev_bb*bb_blind by a small
    # session-mean stack inflated trivial folds to multiple starting stacks
    # (the half of B142 that was never fixed — it lived in the mistake path).
    _hands_by_id_attr = {h.get('id'): h for h in hands if h.get('id')}
    _tid_by_id_attr = {h.get('id'): (h.get('tournament_id') or h.get('tournament'))
                       for h in hands if h.get('id')}
    try:
        from gem_cev import compute_cev_per_stack as _ccps
        _ptc_attr = _ccps(hands)
        _cev_sess_attr = _ptc_attr.get('session', {}) or {}
        _mean_start_attr = _cev_sess_attr.get('mean_starting_stack') or 0
        _start_by_tid_attr = {tid: d['starting_chips']
                              for tid, d in _ptc_attr.get('per_tournament', {}).items()
                              if isinstance(d, dict) and d.get('starting_chips')}
    except Exception:
        _ptc_attr = {}; _cev_sess_attr = {}; _mean_start_attr = 0
        _start_by_tid_attr = {}

    def _mistake_cev(mid, ev_bb):
        """One mistake's EV cost as cEV/stack: ev chips / that tournament's
        starting stack. Per-tournament denominator (v7.63) — see note above.
        Clamped to [-3, +3] starting stacks per hand: at very high late-game
        blinds a sub-1-BB decision's chip figure can balloon to double-digit
        stacks; the clamp bounds that handful of extreme hands so one fold
        does not dominate the Mistake-EV / Tail-fold rows. Normal-blind
        hands (the overwhelming majority) are far inside the band."""
        h = _hands_by_id_attr.get(mid) or {}
        bb = h.get('bb_blind') or 0
        start_t = _start_by_tid_attr.get(_tid_by_id_attr.get(mid))
        if not start_t or not bb:
            return 0.0
        return max(-3.0, min((ev_bb * bb) / start_t, 3.0))

    tail_ev = 0.0; non_tail_ev = 0.0
    tail_n = 0; non_tail_n = 0
    tail_cev = 0.0; non_tail_cev = 0.0
    non_tail_mistake_ids = set()  # for MDA-missed dedup (avoid double-subtract)
    for m in survivors_attr:
        conf = (m.get('confidence', '') or '').upper()
        typ = (m.get('type', '') or '')
        # B173 (Ron 2026-05-24): tail-fold test MUST match the XIII.4 renderer's
        # _is_tail_fold_local exactly — include Missed Push, and read the
        # MARGINAL tier from the type string ("... (MARGINAL)") as well as the
        # confidence field. The old test ('Missed Steal' + conf=='MARGINAL')
        # leaked marginal Missed-Push folds into the non-tail mistake count.
        _is_steal_push = ('missed steal' in typ.lower()
                          or 'missed push' in typ.lower())
        _tier_marginal = ('(marginal)' in typ.lower()) or (conf == 'MARGINAL')
        is_tail = _is_steal_push and _tier_marginal
        # EV: prefer estimated_ev_bb from rd['mistake_ev_estimates'] when available;
        # else fall back to corrected_ev on the raw record (which can be 0/null).
        ev_est = mev_estimates.get(m.get('id'), {}).get('estimated_ev_bb')
        if ev_est is None:
            ev_est = m.get('corrected_ev') or 0
        _cev = _mistake_cev(m.get('id'), ev_est)
        if is_tail:
            tail_ev += ev_est; tail_n += 1; tail_cev += _cev
        elif conf == 'CLEAR':
            # B173: the mistake metric is CLEAR-confirmed only — consistent
            # with XIII.4.1 and discipline_tier.clear_mistakes_count. MARGINAL
            # non-tail flags are line-review candidates, not confirmed mistakes
            # (and not tail folds) — they fall through to neither bucket.
            non_tail_ev += ev_est; non_tail_n += 1; non_tail_cev += _cev
            non_tail_mistake_ids.add(m.get('id'))
        # else: MARGINAL non-tail — line-review candidate, not counted.

    # B173 (Ron 2026-05-24): the analyst-reviewed-flag loop was REMOVED here.
    # It added needs_review flags to the non-tail mistake count whenever the
    # analyst verdict wasn't 🟢/justified, which pushed the headline count
    # above XIII.4's "6 CLEAR confirmed" (analyst-reviewed flags live in their
    # own section XIII.4.5, not in the confirmed-mistake count). The mistake
    # count + EV now cover exactly the CLEAR detector-confirmed survivors.

    # Implied EVs
    # eai_variance_bb is signed (negative = HURT). Subtracting gives variance-adjusted.
    implied_true_ev_bb = surface_bb_total - eai_variance_bb
    implied_ceiling_bb = implied_true_ev_bb - non_tail_ev  # remove mistake cost

    def _to_per100(bb): return 100.0 * bb / max(n_hands_attr, 1)

    # ====================================================================
    # v7.46 (Ron 2026-05-11): EXTENDED VARIANCE LAYERS — card quality,
    # made hands vs expected, cooler frequency. Each captures a distinct
    # variance layer upstream of the others, so they nest cleanly:
    #   1. Dealt-cards quality (premium-hand frequency)
    #   2. Made-hands rate (given played, did board cooperate)
    #   3. Cooler frequency (given strong made hand, did villain make stronger)
    #   4. EAI variance (given chips in middle, did equity hold)
    # Per-delta BB conversions are conservative MTT-pool estimates. The
    # OVERFITTING GUARD at the bottom flags when corrections together
    # exceed 2x the surface result — that's the warning that the model
    # is explaining the session almost entirely by variance.
    # ====================================================================

    # Layer 1: Dealt-cards quality
    # Compare actual premium% (AA-QQ, AK) to expected ~5.9% baseline.
    # Convert delta to BB using ~5 BB/premium-hand-net (conservative; spreads
    # AA/KK/QQ/AK win expectancy across premium category — single-premium
    # hand averages ~+5-10 BB vs random, weighted toward AA being higher).
    cq = stats.get('card_quality', {}) or {}
    prem_strong_pct = cq.get('prem_strong_pct', 0) or 0
    expected_prem_pct = 5.9  # baseline AA-QQ-AK ~5.9% of hands
    prem_delta_pct = prem_strong_pct - expected_prem_pct
    # delta in COUNT of premium hands across session
    prem_delta_n = (prem_delta_pct / 100.0) * n_hands_attr
    # BB per premium-hand-net: ~5 BB (range AA ~+15 to JJ ~+3, average ~+5)
    BB_PER_PREMIUM_HAND = 5.0
    card_quality_var_bb = prem_delta_n * BB_PER_PREMIUM_HAND
    # Signed: positive = ran HOT on cards; negative = ran COLD

    # Layer 2: Made-hands vs expected
    # For each class (set, flush, straight, two_pair, full_house) compute
    # delta from expected rate × opportunities, then multiply by class EV.
    # _made_hands isn't computed in stats — it's built at render time from
    # gem_made_hands. Compute it here for the attribution math.
    try:
        import gem_made_hands as _mh_mod
        _made_hands_data = _mh_mod.compute(hands)
    except Exception:
        _made_hands_data = {}
    # Conservative BB-per-made-hand estimates (avg net BB when made vs
    # average pocket reaching same showdown):
    #  set     ~ +8 BB (sets cooler villains' top pair lines)
    #  flush   ~ +6 BB (often flush-over-flush risk but mostly value)
    #  straight ~ +5 BB (less disguised, smaller value extraction)
    #  two_pair ~ +4 BB (vulnerable to draws / overpairs)
    #  full_house ~ +15 BB (rare + stack-getter)
    BB_PER_MADE = {'set': 8.0, 'flush': 6.0, 'straight': 5.0,
                   'two_pair': 4.0, 'full_house': 15.0}
    made_hands_var_bb = 0.0
    for cls, bb_per in BB_PER_MADE.items():
        d = _made_hands_data.get(cls, {}) if isinstance(_made_hands_data, dict) else {}
        if not d: continue
        opp = d.get('opp', 0)
        if opp < 5: continue  # sample too small to attribute
        made = d.get('made', 0)
        expected_pct = d.get('expected', 0)
        expected_n = expected_pct * opp / 100.0
        delta_n = made - expected_n
        made_hands_var_bb += delta_n * bb_per
    # Positive: hit more than expected (HOT); negative: hit less (COLD)

    # Layer 3: Cooler frequency
    # actual coolers vs expected_low / expected_high midpoint
    # Coolers cost ~30-40 BB on average (typical preflop pair-over-pair gets
    # it in 100+ BB total pot, hero loses 30-40 BB net average).
    coolers_block = stats.get('coolers', {}) or {}
    cooler_rate_actual = coolers_block.get('rate', 0)  # per 100 hands
    cooler_count_actual = coolers_block.get('count', 0)
    exp_lo = coolers_block.get('expected_low', 0.15)
    exp_hi = coolers_block.get('expected_high', 0.30)
    exp_mid_rate = (exp_lo + exp_hi) / 2.0
    expected_coolers = exp_mid_rate * n_hands_attr / 100.0
    cooler_delta_n = cooler_count_actual - expected_coolers
    BB_PER_COOLER = 35.0  # average loss when on losing side of a cooler
    # Signed flip: MORE coolers than expected = MORE losses (hurt)
    cooler_var_bb = -cooler_delta_n * BB_PER_COOLER

    # Aggregate variance corrections
    # Total variance = EAI + card_quality + made_hands + coolers
    total_outcome_variance_bb = (eai_variance_bb + card_quality_var_bb
                                  + made_hands_var_bb + cooler_var_bb)
    # Variance-adjusted implied EV
    implied_true_ev_extended_bb = surface_bb_total - total_outcome_variance_bb
    implied_ceiling_extended_bb = implied_true_ev_extended_bb - non_tail_ev

    # ============================================================
    # B46 (v7.51, Ron 2026-05-18): DEEP-STACK VARIANCE IMPACT
    # ============================================================
    # Quantifies the "felt brutal" perception that variance hits harder at
    # deep stacks. The standard variance decomposition treats every BB equal,
    # but a -80 BB loss at 150BB-deep is psychologically and chip-EV-wise
    # very different from twenty -4BB losses at 20BB. The "deep loss
    # concentration" metric counts how much of the negative variance came
    # from hands where Hero had effective stack >= 50BB.
    #
    # Calc: for hands where net_bb < -25, sum the net_bb by stack tier
    # (deep >= 50BB, mid 20-50BB, short < 20BB). Then report:
    # - deep_loss_total_bb / total negative variance ratio
    # - max_single_deep_loss_bb (largest -BB hand at >= 50BB eff)
    # - n_deep_losses (hands where eff >= 50BB and net <= -25BB)
    # This surfaces the asymmetric impact of variance at peak stacks.
    hands_with_loss = hands or []
    deep_loss_bb = 0.0
    mid_loss_bb = 0.0
    short_loss_bb = 0.0
    deep_loss_hands = []   # (hid, eff_bb, net_bb) for the worst few
    mid_loss_hands = []    # B141 (Ron 2026-05-23): collect mid-tier hands too
    short_loss_hands = []  # B141: ...and short-tier — so every tier shows a worst single
    n_deep_losses = 0
    n_mid_losses = 0
    n_short_losses = 0
    for h in hands_with_loss:
        net = h.get('net_bb', 0) or 0
        if net >= -25:
            continue
        eff = (h.get('effective_stack_bb_at_decision')
               or h.get('eff_stack_bb_at_decision')
               or h.get('effective_stack_bb')
               or h.get('eff_stack_bb')
               or 0) or 0
        if eff >= 50:
            deep_loss_bb += net
            n_deep_losses += 1
            deep_loss_hands.append((h.get('id', ''), eff, net))
        elif eff >= 20:
            mid_loss_bb += net
            n_mid_losses += 1
            mid_loss_hands.append((h.get('id', ''), eff, net))
        else:
            short_loss_bb += net
            n_short_losses += 1
            short_loss_hands.append((h.get('id', ''), eff, net))
    deep_loss_hands.sort(key=lambda t: t[2])   # most negative first
    mid_loss_hands.sort(key=lambda t: t[2])
    short_loss_hands.sort(key=lambda t: t[2])
    total_neg_loss = deep_loss_bb + mid_loss_bb + short_loss_bb
    deep_loss_share = (deep_loss_bb / total_neg_loss) if total_neg_loss != 0 else 0
    max_single_deep_loss = (deep_loss_hands[0][2] if deep_loss_hands else 0)
    max_single_mid_loss = (mid_loss_hands[0][2] if mid_loss_hands else 0)
    max_single_short_loss = (short_loss_hands[0][2] if short_loss_hands else 0)
    # Verdict: deep concentration is "high" when >60% of large losses came
    # from >=50BB stacks. That's the "felt brutal" signature.
    deep_concentration = "high" if deep_loss_share > 0.6 and n_deep_losses >= 3 else (
        "moderate" if deep_loss_share > 0.4 else "low")

    # Overfitting guard: if total corrections magnitude > 2× |surface|,
    # the decomposition is explaining the session almost entirely by
    # variance — flag it so the reader treats the implied EV with skepticism.
    correction_magnitude = abs(total_outcome_variance_bb)
    surface_magnitude = max(abs(surface_bb_total), 1.0)
    overfit_ratio = correction_magnitude / surface_magnitude
    overfit_warning = overfit_ratio > 2.0

    rd['results_attribution'] = {
        'n_hands': n_hands_attr,
        'surface_bb_total': round(surface_bb_total, 1),
        'surface_bb_per_100': round(bb100_actual, 2),
        # EAI (existing)
        'eai_variance_bb': round(eai_variance_bb, 1),
        'eai_variance_per_100': round(_to_per100(eai_variance_bb), 2),
        # Card quality (new)
        'card_quality_var_bb': round(card_quality_var_bb, 1),
        'card_quality_var_per_100': round(_to_per100(card_quality_var_bb), 2),
        'card_quality_delta_pp': round(prem_delta_pct, 2),
        # Made hands (new)
        'made_hands_var_bb': round(made_hands_var_bb, 1),
        'made_hands_var_per_100': round(_to_per100(made_hands_var_bb), 2),
        # Coolers (new)
        'cooler_var_bb': round(cooler_var_bb, 1),
        'cooler_var_per_100': round(_to_per100(cooler_var_bb), 2),
        'cooler_count_actual': cooler_count_actual,
        'cooler_count_expected': round(expected_coolers, 1),
        # Mistakes (existing)
        'non_tail_mistake_ev_bb': round(non_tail_ev, 1),
        'non_tail_mistake_per_100': round(_to_per100(non_tail_ev), 2),
        'non_tail_mistake_count': non_tail_n,
        'non_tail_mistake_ids': sorted(non_tail_mistake_ids),
        'non_tail_mistake_cev': round(non_tail_cev, 3),
        'non_tail_mistake_cev_per_100': round(_to_per100(non_tail_cev), 4),
        'tail_fold_ev_bb': round(tail_ev, 1),
        'tail_fold_per_100': round(_to_per100(tail_ev), 2),
        'tail_fold_count': tail_n,
        'tail_fold_cev': round(tail_cev, 3),
        'tail_fold_cev_per_100': round(_to_per100(tail_cev), 4),
        # Old implied EVs (EAI-only) kept for back-compat / comparison
        'implied_true_ev_bb': round(implied_true_ev_bb, 1),
        'implied_true_ev_per_100': round(_to_per100(implied_true_ev_bb), 2),
        'implied_ceiling_bb': round(implied_ceiling_bb, 1),
        'implied_ceiling_per_100': round(_to_per100(implied_ceiling_bb), 2),
        # New implied EVs (all 4 variance layers)
        'total_outcome_variance_bb': round(total_outcome_variance_bb, 1),
        'total_outcome_variance_per_100': round(_to_per100(total_outcome_variance_bb), 2),
        'implied_true_ev_extended_bb': round(implied_true_ev_extended_bb, 1),
        'implied_true_ev_extended_per_100': round(_to_per100(implied_true_ev_extended_bb), 2),
        'implied_ceiling_extended_bb': round(implied_ceiling_extended_bb, 1),
        'implied_ceiling_extended_per_100': round(_to_per100(implied_ceiling_extended_bb), 2),
        # B46: Deep-stack loss concentration ("felt brutal" articulation)
        'deep_loss_bb': round(deep_loss_bb, 1),
        'mid_loss_bb': round(mid_loss_bb, 1),
        'short_loss_bb': round(short_loss_bb, 1),
        'n_deep_losses': n_deep_losses,
        'n_mid_losses': n_mid_losses,
        'n_short_losses': n_short_losses,
        'deep_loss_share': round(deep_loss_share, 2),
        'max_single_deep_loss_bb': round(max_single_deep_loss, 1),
        'deep_concentration': deep_concentration,
        'max_single_mid_loss_bb': round(max_single_mid_loss, 1),
        'max_single_short_loss_bb': round(max_single_short_loss, 1),
        'worst_deep_loss_hands': [{'id': hid, 'eff_bb': round(eff, 1),
                                   'net_bb': round(net, 1)}
                                  for hid, eff, net in deep_loss_hands[:5]],
        'worst_mid_loss_hands': [{'id': hid, 'eff_bb': round(eff, 1),
                                  'net_bb': round(net, 1)}
                                 for hid, eff, net in mid_loss_hands[:5]],
        'worst_short_loss_hands': [{'id': hid, 'eff_bb': round(eff, 1),
                                    'net_bb': round(net, 1)}
                                   for hid, eff, net in short_loss_hands[:5]],
        # Overfit guard
        'overfit_ratio': round(overfit_ratio, 2),
        'overfit_warning': overfit_warning,
    }

    # v7.61 (Ron 2026-05-21): per-layer variance cEV — real chip-derived
    # attribution (NOT a BB->cEV translation) for the Result Attribution
    # table's cEV column. EAI / cooler / made-hands get a chip-derived
    # cEV/stack figure; card quality has no realized-chip measure by design.
    rd['variance_cev'] = {}
    try:
        from gem_cev import compute_cev_per_stack, compute_variance_cev
        _ptc = compute_cev_per_stack(hands)
        rd['cev_session'] = _ptc.get('session', {})
        rd['variance_cev'] = compute_variance_cev(
            hands, stats, rd['results_attribution'], _ptc)
    except Exception as e:
        rd['variance_cev'] = {'available': False,
                              'reason': f'{type(e).__name__}: {e}'}

    # v7.63 (Ron 2026-05-21): cEV LEDGER SPINE. The BB ledger above does NOT
    # aggregate across tournaments — net_bb sums blind-weighted, so a stack
    # built at low blinds then busted at high blinds reads BB-positive on a
    # chip loss (70 of 185 tournaments did exactly that in the May run), and
    # the surface BB/100 went positive on a losing dataset. The cEV column —
    # chips / tournament starting stack — IS chip-conserving and reconciles
    # with financial direction, so it is the spine: implied true EV, ceiling
    # and (downstream) the residual decomposition are derived in cEV. The BB
    # figures are retained as a secondary, blind-weighted lens only.
    _vc = rd.get('variance_cev', {}) or {}
    _cs = rd.get('cev_session', {}) or {}
    _surface_cev = _cs.get('cev_per_stack_total')
    _surface_cev_p100 = _cs.get('cev_per_stack_per_100')
    _n_res = _cs.get('n_hands_resolved') or n_hands_attr or 1
    _layer_cev = {k: (_vc.get(k) or {}).get('cev_stacks')
                  for k in ('card_quality', 'made_hands', 'cooler', 'eai')}
    _all_layers = all(v is not None for v in _layer_cev.values())
    _total_var_cev = (round(sum(_layer_cev.values()), 4)
                      if _all_layers else None)
    # implied true EV = surface − Σ variance layers; ceiling = implied −
    # non-tail mistakes. non_tail_cev is already chip-derived per-tournament.
    _implied_cev = (round(_surface_cev - _total_var_cev, 4)
                    if _surface_cev is not None and _total_var_cev is not None
                    else None)
    _ceiling_cev = (round(_implied_cev - non_tail_cev, 4)
                    if _implied_cev is not None else None)

    def _cev100(v):
        return round(v / _n_res * 100, 4) if v is not None else None

    # B146 (Ron 2026-05-23): the overfit guard must fire on the SPINE
    # (% starting stack), not the BB lens. The BB-lens ratio set earlier
    # (overfit_ratio) is kept as a reference, but BB does not aggregate
    # across MTT blind levels, so a correction stack that is 3x the surface
    # on the spine can read 0.6x in BB and the warning never fires — exactly
    # the failure mode on the 260%-implied session. overfit_warning is now
    # driven by the spine ratio.
    _overfit_spine = (abs(_total_var_cev) / max(abs(_surface_cev), 1e-9)
                      if (_total_var_cev is not None
                          and _surface_cev not in (None, 0)) else None)

    rd['results_attribution'].update({
        'surface_cev': _surface_cev,
        'surface_cev_per_100': _surface_cev_p100,
        'total_variance_cev': _total_var_cev,
        'total_variance_cev_per_100': _cev100(_total_var_cev),
        'implied_true_ev_cev': _implied_cev,
        'implied_true_ev_cev_per_100': _cev100(_implied_cev),
        'implied_ceiling_cev': _ceiling_cev,
        'implied_ceiling_cev_per_100': _cev100(_ceiling_cev),
        'cev_ledger_balances': bool(_all_layers and _surface_cev is not None),
        'cev_n_hands_resolved': _n_res,
        'overfit_ratio_spine': (round(_overfit_spine, 2)
                                if _overfit_spine is not None else None),
        'overfit_ratio_bb': overfit_ratio,
        'overfit_warning': bool(_overfit_spine is not None
                                and _overfit_spine > 2.0),
    })
    # tid -> starting stack, for the residual-decomposition cEV (gem_analyzer).
    rd['cev_starts'] = _start_by_tid_attr

    # v7.62 residual decomposition is computed in gem_analyzer AFTER the
    # read-dependent quantification step (read_dependent_quant is not yet
    # on rd at this point in generate_report_data). See gem_analyzer.

    # B58 (v7.47, Ron 2026-05-12): Aggression detector — 5-gate analysis
    # replacing v7.46's "made_value_hand + called = missed_value" heuristic.
    # Adds board-texture, action-context, ER/ED axis, and vs-what-calls gates.
    # Catches false positives like dry-board IP set-vs-donk-lead (correctly
    # passive) and OOP combo-draw spots (correctly passive, ER axis).
    try:
        from gem_aggression_detector import analyze_session as _analyze_aggression
        rd['aggression_analysis'] = _analyze_aggression(hands)
    except Exception as e:
        rd['aggression_analysis'] = {'error': f'{type(e).__name__}: {e}',
                                      'missed_aggression': [], 'correctly_passive': [], 'ambiguous': []}

    # B59 (v7.47, Ron 2026-05-12): AF breakdown by street/position/role
    # Session-level AF is too aggregated to be actionable. Cross-slice
    # AF (e.g., river_ip_pfr) points at the specific decision class
    # driving the leak.
    try:
        from gem_af_breakdown import compute_af_breakdown as _compute_af
        rd['af_breakdown'] = _compute_af(hands)
    except Exception as e:
        rd['af_breakdown'] = {'error': f'{type(e).__name__}: {e}'}

    # B66 (v7.48, Ron 2026-05-12): Solver batch pass for river candidates.
    # Confirms heuristic missed-aggression verdicts against gem_solver
    # value_bet EV. Each candidate gets solver_verdict (CONFIRMED/DENIED/
    # NEUTRAL/SKIPPED) attached if its solver_status was IN_SCOPE.
    try:
        from gem_aggression_solver_pass import run_solver_pass, cluster_for_drills
        solver_out_dir = os.path.join('/home/claude', 'solver_runs_agg')
        rd['aggression_solver_pass'] = run_solver_pass(
            rd['aggression_analysis'], hands, hh_dir, solver_out_dir
        )
        # B67 (v7.48): drill clusters keyed by AF below-target slices.
        # Each cluster groups missed-aggression candidates that share the
        # same leak class and attaches a focused tactical drill question.
        rd['aggression_drill_clusters'] = cluster_for_drills(
            rd.get('aggression_analysis', {}),
            rd.get('af_breakdown', {})
        )
    except Exception as e:
        rd['aggression_solver_pass'] = {'error': f'{type(e).__name__}: {e}'}
        rd['aggression_drill_clusters'] = []

    # B226 (Ron review 2026-05-25): IV.7 Bounty/PKO flip analysis. Finds
    # all-in CALLS whose correct/incorrect verdict flips between the freezeout
    # and bounty regimes. v1 scope: heads-up preflop jam-calls in bounty
    # formats (see IV7_Bounty_PKO_Rebuild_Scope.md).
    try:
        from gem_pko import analyze_pko_flips
        _pko_ids = {h.get('id') for h in hands
                    if h.get('pf_allin')
                    and (h.get('format') or '') in ('BOUNTY', 'MYSTERY_BOUNTY')}
        _pko_raw = _extract_raw_hh(_pko_ids, hh_dir)
        rd['pko_flips'] = analyze_pko_flips(hands, _pko_raw)
    except Exception as e:
        rd['pko_flips'] = {'error': f'{type(e).__name__}: {e}'}

    # B71 (v7.50, Ron 2026-05-12): B63 promotion of aggression candidates to
    # appendix_ids_full was placed BEFORE aggression_analysis was computed,
    # so _agg_buckets was always empty. Re-do the promotion HERE, after the
    # aggression detector has run, mutating the already-emitted lists in rd.
    _agg_block = rd.get('aggression_analysis', {}) or {}
    if isinstance(_agg_block, dict) and 'error' not in _agg_block:
        _agg_buckets = {}
        def _ab(k): return _agg_buckets.setdefault(k, [])
        for _c in _agg_block.get('missed_aggression', []):
            _ab((_c.get('street_of_interest'), 'MISSED')).append(_c)
        for _c in _agg_block.get('ambiguous', []):
            _ab((_c.get('street_of_interest'), 'AMBIGUOUS')).append(_c)
        for _c in _agg_block.get('correctly_passive', []):
            _ab((_c.get('street_of_interest'), 'CORRECTLY_PASSIVE')).append(_c)
        # Read existing rd lists (already populated), augment, write back
        _all_set = set(rd.get('appendix_hand_ids_all', []) or [])
        _full_set = set(rd.get('appendix_hand_ids_full', []) or [])
        for _items in _agg_buckets.values():
            _items.sort(key=lambda c: -abs(c.get('net_bb', 0) or 0))
            for _c in _items[:5]:  # top 5 per cell
                _hid = _c.get('hand_id')
                if _hid:
                    _all_set.add(_hid)
                    _full_set.add(_hid)
        rd['appendix_hand_ids_all'] = sorted(_all_set)
        rd['appendix_hand_ids_full'] = sorted(_full_set)

    # B71 (v7.50): same fix for III.3 example hands — they're computed at
    # render-time in gem_report_draft, after appendix is frozen. Pre-compute
    # them here so they land in the appendix set.
    _pf_devs = stats.get('postflop_deviations_v732', []) or []
    if _pf_devs:
        _iii3_example_ids = set()
        for d in _pf_devs[:15]:
            rule = d.get('rule', ''); pos = d.get('pos', '')
            n_added = 0
            for h in hands:
                if h.get('position') != pos: continue
                match = False
                if rule == 'detector_fold_to_cbet_by_pos':
                    match = (h.get('faced_villain_cbet_flop')
                             and h.get('fold_to_villain_cbet_flop')
                             and not h.get('first_in'))
                elif rule == 'detector_call_cbet_by_pos':
                    match = (h.get('faced_villain_cbet_flop')
                             and h.get('called_villain_cbet_flop'))
                elif rule == 'detector_river_cbet_by_pos':
                    match = h.get('pfr') and h.get('cbet_river_then_sd')
                elif rule == 'detector_rfi_by_pos':
                    match = h.get('first_in') and h.get('pfr')
                if match:
                    hid = h.get('id')
                    if hid:
                        _iii3_example_ids.add(hid)
                        n_added += 1
                if n_added >= 3: break
        if _iii3_example_ids:
            _all_set = set(rd.get('appendix_hand_ids_all', []) or [])
            _full_set = set(rd.get('appendix_hand_ids_full', []) or [])
            _all_set |= _iii3_example_ids
            _full_set |= _iii3_example_ids
            rd['appendix_hand_ids_all'] = sorted(_all_set)
            rd['appendix_hand_ids_full'] = sorted(_full_set)

    # B73 (v7.50, Ron 2026-05-12): same for IV.3 Blind Combat example hands.
    # Pre-compute defense-type examples here (first-3 by iteration order)
    # so the renderer and the appendix promotion use the SAME list.
    _blind_examples_by_type = {
        'SB Defense vs LP (J29)': [],
        'BB Defense vs Steal': [],
        'BB Defense vs Non-Steal (EP/MP/HJ open)': [],
    }
    for h in hands:
        if h.get('hero') != 'Hero': continue
        pos = h.get('position')
        op = h.get('opener_position') or ''
        hid = h.get('id')
        if not hid: continue
        if (pos == 'SB' and h.get('faced_open_vs_open_pos') in ('CO', 'BTN')
                and h.get('vpip')
                and len(_blind_examples_by_type['SB Defense vs LP (J29)']) < 3):
            _blind_examples_by_type['SB Defense vs LP (J29)'].append(hid)
        elif (pos == 'BB' and op in ('CO', 'BTN', 'SB')
              and not h.get('walked')
              and len(_blind_examples_by_type['BB Defense vs Steal']) < 3):
            _blind_examples_by_type['BB Defense vs Steal'].append(hid)
        elif (pos == 'BB' and op in ('UTG', 'UTG+1', 'UTG+2', 'MP', 'HJ')
              and not h.get('walked')
              and len(_blind_examples_by_type['BB Defense vs Non-Steal (EP/MP/HJ open)']) < 3):
            _blind_examples_by_type['BB Defense vs Non-Steal (EP/MP/HJ open)'].append(hid)
    rd['blind_combat_example_hands'] = _blind_examples_by_type
    # Promote ALL these example hand IDs to appendix
    _all_blind = {hid for ids in _blind_examples_by_type.values() for hid in ids}
    if _all_blind:
        _all_set = set(rd.get('appendix_hand_ids_all', []) or [])
        _full_set = set(rd.get('appendix_hand_ids_full', []) or [])
        _all_set |= _all_blind
        _full_set |= _all_blind
        rd['appendix_hand_ids_all'] = sorted(_all_set)
        rd['appendix_hand_ids_full'] = sorted(_full_set)

    # FEAT-3/4 (v7.99): promote texture-deviation + CR per-hand IDs to the
    # appendix so clickable popup triggers have article data to display.
    # The generic _scan_for_hand_ids misses TM-prefix strings stored as
    # list elements (it only catches direct dict values), so explicit
    # promotion is required.
    _feat34_ids = set()
    # FEAT-3: texture deviation hand IDs (cbet_hand_ids, missed_hand_ids)
    _tex_findings = stats.get('texture_gto_findings', {}) or {}
    for _arch, _sides in _tex_findings.items():
        if not isinstance(_sides, dict):
            continue
        for _side, _bucket in _sides.items():
            if not isinstance(_bucket, dict):
                continue
            for _k in ('cbet_hand_ids', 'missed_hand_ids'):
                for _hid in (_bucket.get(_k) or []):
                    if isinstance(_hid, str) and _hid.startswith('TM'):
                        _feat34_ids.add(_hid)
    # FEAT-4: check-raise per-hand IDs (actual CRs and opportunities)
    _cr_freq = stats.get('cr_frequency', {}) or {}
    for _st_ids in (_cr_freq.get('cr_hids', {}) or {}).values():
        for _hid in (_st_ids or []):
            if isinstance(_hid, str) and _hid.startswith('TM'):
                _feat34_ids.add(_hid)
    # CR opportunity hands are numerous — only promote the CR hands (small
    # set, analytically interesting). Opportunity hands stay available for
    # count display but don't need appendix articles.
    if _feat34_ids:
        _all_set = set(rd.get('appendix_hand_ids_all', []) or [])
        _all_set |= _feat34_ids
        rd['appendix_hand_ids_all'] = sorted(_all_set)

    # POPUP-COVERAGE: ensure EVERY hand ID that will appear in a
    # hand-list-trigger popup has an appendix entry so clicking through
    # shows the actual hand detail, not a dead link.
    # Sources: defend folds, cold-calls, J44 deviations, villain examples.
    _popup_ids = set()
    # 1. Defend matrix fold IDs — hands Hero folded vs a steal/raise
    for h in (hands or []):
        if not isinstance(h, dict):
            continue
        # Missed defends: Hero in BB/SB, faced raise, didn't defend
        if (h.get('position') in ('BB', 'SB') and h.get('hero_faced_raise')
                and not h.get('cold_called') and not h.get('hero_3bet')
                and h.get('id')):
            _popup_ids.add(h['id'])
        # Wide defends: Hero defended and lost > 10BB
        if (h.get('position') in ('BB', 'SB') and h.get('hero_faced_raise')
                and (h.get('cold_called') or h.get('hero_3bet'))
                and (h.get('net_bb') or 0) < -10 and h.get('id')):
            _popup_ids.add(h['id'])
        # Cold-call hands
        if h.get('cold_called') and h.get('id'):
            _popup_ids.add(h['id'])
    # 2. J44 deviation hand IDs
    _j44 = stats.get('ip_3bet_sizing', {}) or {}
    for _bk in (_j44.get('buckets', {}) or {}).values():
        for _dev in (_bk.get('deviations', []) or []):
            if isinstance(_dev, dict) and _dev.get('id'):
                _popup_ids.add(_dev['id'])
    # 3. Villain archetype example hand IDs
    for _vp in (stats.get('opponent_profiles', {}) or {}).values():
        for _eid in (_vp.get('example_hand_ids', []) or []):
            if isinstance(_eid, str) and _eid.startswith('TM'):
                _popup_ids.add(_eid)
    # Every popup hand ID MUST be in the appendix — without it, clicking
    # through shows "no detail" placeholder. No cap: a broken popup is worse
    # than a slightly larger appendix.
    if _popup_ids:
        _all_set = set(rd.get('appendix_hand_ids_all', []) or [])
        _all_set |= _popup_ids
        rd['appendix_hand_ids_all'] = sorted(_all_set)

    # B197 (Ron review 2026-05-25): deep-harvest EVERY hand id referenced
    # anywhere in rd, BEFORE the B158 detail-backfill below. The B188 draft-
    # time deep-harvest added ids to the appendix set so _hand_ref LINKS them
    # — but it ran AFTER this function, so those hands had no entry in
    # appendix_hand_details and rendered as a bare header with no hand grid
    # ("Where's the hand?!" — 96340214 / 96569167 / 93012530 etc.). Harvesting
    # here means the backfill at line ~2871 parses seat/action detail for them
    # too, so every cited hand renders a full grid. _hands_by_id / the raw
    # hand list are skipped (lookup tables, not citation sources).
    def _b197_harvest(obj, out, _d=0):
        if _d > 12:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ('_hands_by_id', 'hands', 'all_hands'):
                    continue
                if k in ('id', 'hand_id') and isinstance(v, str) \
                        and v.startswith('TM'):
                    out.add(v)
                else:
                    _b197_harvest(v, out, _d + 1)
        elif isinstance(obj, (list, tuple)):
            for it in obj:
                # B-V10 STRUCTURAL (2026-06-01): catch bare TM-prefixed
                # strings in lists (e.g. cbet_hands: ['TM123', 'TM456']).
                # Without this, any list of hand ID strings is silently
                # skipped and those hands become orphaned links.
                if isinstance(it, str) and it.startswith('TM') and len(it) > 5:
                    out.add(it)
                else:
                    _b197_harvest(it, out, _d + 1)
    _all_set = set(rd.get('appendix_hand_ids_all', []) or [])
    _b197_harvest(rd, _all_set)
    # B-V10 STRUCTURAL: also scan stats — some hand ID lists (c-bet examples,
    # line analysis top hands, suckouts) live in stats, not rd.
    _b197_harvest(stats, _all_set)
    # B-V10 BUG (2026-06-01): c-bet example hands are plain string lists
    # inside facing_action_v728 — the recursive scanner only catches dicts
    # with 'id'/'hand_id' keys, so these were orphaned (clickable links
    # with no appendix card). Explicitly add them.
    _fav728 = stats.get('facing_action_v728') or {}
    for _pt in ((_fav728.get('cbet_by_pot_type') or {}).values()):
        for _kind in ('cbet_hands', 'nocbet_hands'):
            for _hid in (_pt.get(_kind) or []):
                if isinstance(_hid, str) and _hid.startswith('TM'):
                    _all_set.add(_hid)
    # B-V10 FEATURE: P&L Lines top-3 best/worst hands in appendix
    for _ll in (stats.get('top_losing_lines') or []) + (stats.get('top_winning_lines') or []):
        for _k in ('top3_best', 'top3_worst', 'example_ids'):
            for _hid in (_ll.get(_k) or []):
                if isinstance(_hid, str) and _hid.startswith('TM'):
                    _all_set.add(_hid)
    # Renderer link BUG-4: harvest suckout IDs from stats['suckouts'].
    # The suckout ledger (I.4) links to these via _hand_ref, so they must
    # be in the appendix set or XIV.B won't render their stub.
    _sk = (stats.get('suckouts') or {})
    for _bucket in ('against_hero', 'by_hero'):
        for _e in (_sk.get(_bucket) or []):
            _sid = _e.get('id') if isinstance(_e, dict) else None
            if isinstance(_sid, str) and _sid.startswith('TM'):
                _all_set.add(_sid)
    # B228 (Ron 2026-06-01): blind-spot audit hands must be in the appendix
    # so they get XIV.B review modals — same analyst workflow as punts/mistakes.
    _bsa = (stats.get('blindspot_audit') or {}).get('sampled') or []
    for _be in _bsa:
        _bid = _be.get('id') if isinstance(_be, dict) else None
        if isinstance(_bid, str) and _bid.startswith('TM'):
            _all_set.add(_bid)
    # B229 (Ron 2026-06-01): fold-to-steal + re-steal hands in appendix so the
    # S11.9 hand-list popup can open full hand details.
    for _h in hands:
        if (_h.get('fold_to_steal_bb') or _h.get('restole')) and _h.get('id'):
            _all_set.add(_h['id'])
    rd['appendix_hand_ids_all'] = sorted(_all_set)

    # B158 (v7.80, Ron 2026-05-23): backfill appendix_hand_details for any
    # hand ID added to appendix_hand_ids_all AFTER the initial seat-parse
    # earlier in this function. The B71 (III.3 examples / aggression) and
    # B73 (blind-combat) blocks above extend appendix_hand_ids_all but do
    # NOT re-parse seat/action detail — so those hands landed in XIV.B as
    # bare metadata stubs (no action grid) because appendix_hand_details
    # had no entry for them. Re-run the parse for every missing ID so every
    # XIV.B Quick-Lookup hand renders the full hand grid, same as XIV.A.
    # A2b-4: backfill using ledger first, raw HH fallback
    _ahd = rd.get('appendix_hand_details', {}) or {}
    _missing_app = [hid for hid in rd.get('appendix_hand_ids_all', [])
                    if hid and hid not in _ahd]
    if _missing_app:
        # Try ledger path first
        for _hid in list(_missing_app):
            _hdict = _hands_by_id_app.get(_hid)
            if _hdict and _hdict.get('action_ledger'):
                _built = _build_seat_info_from_hand(_hdict)
                if _built:
                    _ahd[_hid] = _built
                    _missing_app.remove(_hid)
        # Fall back to raw HH for remaining
        if _missing_app:
            _raw_bf = _extract_raw_hh(set(_missing_app), app_hh_dir)
            for _hid, _hh_text in _raw_bf.items():
                try:
                    _ahd[_hid] = _parse_hand_seat_info(_hh_text, hero_name=_pname)
                except Exception as _e:
                    _ahd[_hid] = {'error': str(_e)}
        rd['appendix_hand_details'] = _ahd

    # A3: Build source-aware collector from the final appendix set.
    # This provides explain() capability for debugging appendix diffs.
    # TODO(A3-full): replace the 8 extension blocks above with collector.add()
    # calls. For now, collector is built post-hoc from the final set.
    for _hid in rd.get('appendix_hand_ids_all', []):
        if _hid in (rd.get('appendix_hand_ids_full') or []):
            _collector.add_full(_hid, source='analyst_reviewed')
        else:
            _collector.add(_hid, source='body_citation')
    rd['_appendix_collector_summary'] = dict(_collector.sources_summary())

    # ----------------------------------------------------------
    # SKILL CONTEXT SIDEBAR (Ron 2026-05-14, build #2)
    # ----------------------------------------------------------
    # Pull backward-looking trailing-window logit/AvgF for the session's
    # primary BI tier, providing "where I stood entering today" context.
    # Source: session_financials_per_tournament.csv (must exist under
    # project root). Renderer-visible field is rd['skill_context'].
    try:
        from gem_summary_parser import (session_skill_context,
                                         session_movement_summary)
        import csv as _csv
        # Default path — matches existing pipeline convention.
        # CWD/local takes precedence over /mnt/project/ since the project
        # file is read-only and may lag a local working copy.
        per_tourn_paths = [
            'session_financials_per_tournament.csv',
            '/home/claude/session_financials_per_tournament.csv',
        ]
        if not _isolate:
            per_tourn_paths.append(
                '/mnt/project/session_financials_per_tournament.csv')
        per_tourn_rows = None
        for _p in per_tourn_paths:
            try:
                with open(_p) as _f:
                    per_tourn_rows = list(_csv.DictReader(_f))
                if per_tourn_rows:
                    break
            except FileNotFoundError:
                continue
        if per_tourn_rows and rd.get('dates'):
            # Session date = first session date (analyzer concatenates per-day)
            _session_date = rd['dates'][0]
            _avg_bi = rd.get('avg_buyin') or None
            _ctx = session_skill_context(
                per_tourn_rows, _session_date,
                session_avg_bi=_avg_bi,
                window_bullets=500,
            )
            if _ctx:
                rd['skill_context'] = _ctx

            # NEW: skill_movement (Ron 2026-05-16). Computes today vs.
            # trailing anchor (500b) and responsive (100t) windows.
            # B136 (Ron 2026-05-20): the "today" window must cover the WHOLE
            # uploaded session, not a single GG calendar date. HH files use
            # UTC timestamps, so a Bangkok-time session straddles two GG dates
            # (and PokerCraft rows can land on either) — filtering by
            # rd['dates'][0] alone dropped ~all of the session, leaving "Today"
            # at n=1/1. Build today_rows from every tournament_id in this
            # session's USD overlay; fall back to the date filter only if the
            # overlay is unavailable.
            _today_rows = None
            _today_tids = rd.get('today_tids')  # opt-in override
            if not _today_tids:
                _overlay = (rd.get('usd_overlay') or {}).get('per_tournament') or []
                _today_tids = [t.get('tid') for t in _overlay if t.get('tid')]
            if _today_tids:
                _today_rows = [r for r in per_tourn_rows
                               if r.get('tournament_id') in set(_today_tids)]
            _mv = session_movement_summary(
                per_tourn_rows, _session_date,
                anchor_window_bullets=500,
                responsive_window_tnys=100,
                today_rows=_today_rows,
            )
            if _mv:
                rd['skill_movement'] = _mv
    except Exception as _e:
        # Skill context is decorative — never block report generation
        rd['skill_context'] = None
        rd.setdefault('skill_movement', None)

    # ----------------------------------------------------------
    # ROI FORECAST SIDEBAR (Ron 2026-05-14, v7.49.10)
    # ----------------------------------------------------------
    # Predict forward 200-bullet ROI + logit from THIS session's metrics
    # using the triangulation-v2 regression model. Renders as a second
    # sidebar line under the date/hands header. Decorative — wide
    # prediction intervals reflect MTT variance.
    try:
        from gem_summary_parser import session_roi_forecast
        _csv_row = stats.get('csv_row', {})
        _session_date = rd['dates'][0] if rd.get('dates') else None
        _3bet = _csv_row.get('ThreeBet')
        _vpip = _csv_row.get('VPIP')
        _mistakes = _csv_row.get('Mistakes_per_100')
        # Coerce strings to floats if needed
        try: _3bet = float(_3bet) if _3bet not in (None, '') else None
        except (ValueError, TypeError): _3bet = None
        try: _vpip = float(_vpip) if _vpip not in (None, '') else None
        except (ValueError, TypeError): _vpip = None
        try: _mistakes = float(_mistakes) if _mistakes not in (None, '') else None
        except (ValueError, TypeError): _mistakes = None

        if _session_date and _3bet is not None and _vpip is not None and _mistakes is not None:
            _fc = session_roi_forecast(_session_date, _3bet, _vpip, _mistakes)
            if _fc:
                rd['roi_forecast'] = _fc
    except Exception as _e:
        rd['roi_forecast'] = None

    # ----------------------------------------------------------
    # LEAK WATCHLIST (Ron 2026-05-14, v7.49.11)
    # ----------------------------------------------------------
    # Compares 20 actionable session metrics against target ranges
    # derived from the May 2026 64-session cohort. Renders as a new
    # report section showing red/amber/green status per metric plus
    # prioritized actions. Targets refit via gem_meta_analysis.py.
    try:
        from gem_leak_watchlist import build_leak_watchlist
        _csv_row = stats.get('csv_row', {})
        if _csv_row:
            rd['leak_watchlist'] = build_leak_watchlist(_csv_row)
    except Exception as _e:
        rd['leak_watchlist'] = None

    return rd


# ============================================================
# v7.30 STANDALONE CSV ROW GENERATORS
# ============================================================
# These produce dict rows matching the existing
# session_history_*.csv and gem_run_log.csv schemas. The report
# pipeline writes them to separate files (date in filename)
# rather than embedding them in the MD output.

# Schema must match existing session_history_20260419.csv header exactly.
SESSION_HISTORY_COLUMNS = [
    'Date', 'Batch_ID', 'Hands', 'BB_per_100',
    'VPIP', 'PFR', 'ThreeBet', 'ATS',
    'BTN_Open', 'CO_Open', 'SB_Steal', 'AF',
    'WTSD_Vol', 'WSD_Vol',
    'Flop_CBet_HU', 'Flop_CBet_MW', 'Turn_CBet', 'River_CBet', 'Flop_Probe',
    'LT12BB_Errors', 'Punts_per_100', 'Mistakes_per_100', 'RedLine_BB100',
    'Pure_Bluff_Pct', 'Semi_Bluff_Pct', 'Value_Bet_Pct',
    'ThreeBet_vs_EP', 'ThreeBet_vs_LP', 'Premiums_Pct', 'Top_Leak',
    'VPIP_PFR_Gap', 'WWSF', 'Non_SD_Win', 'SD_Aggressor',
    'Caller_IP_Flop_Agg', 'IP_Stab_Rate', 'Flop_Lead_Rate', 'Float_Turn_Attack',
    'Agg_React_Delta', 'Draw_Overbet_Jams', 'Passive_Passive_Jam',
    'Triple_Barrel_Called_WR', 'Sizing_Geo_Pct', 'Small_Small_Jam_Ct',
    'CR_Flop_Pct', 'CR_Total_Pct', 'ThreeBet_BTN'
]

RUN_LOG_COLUMNS = [
    'Date', 'Session_ID', 'Hands', 'Tournaments',
    'Files', 'Tokens_Est', 'Parse_Errors',
    'Processing_Time_Approx', 'Notes'
]


def _build_session_history_row(stats, hands):
    """Build one session_history CSV row from stats. Returns dict matching
    SESSION_HISTORY_COLUMNS schema. Reads from the canonical stats['csv_row']
    that the analyzer already populates — avoids re-deriving and keeps schema
    drift contained to one place."""
    src = stats.get('csv_row', {}) or {}
    vol = stats.get('volume', {})
    # Map SESSION_HISTORY_COLUMNS → csv_row keys (handles minor naming gaps).
    KEY_MAP = {
        'Date': 'Date',
        'Batch_ID': 'Batch_ID',
        'Hands': 'Hands',
        'BB_per_100': 'BB_per_100',
        'VPIP': 'VPIP',
        'PFR': 'PFR',
        'ThreeBet': 'ThreeBet',
        'ATS': 'ATS',
        'BTN_Open': 'BTN_Open',
        'CO_Open': 'CO_Open',
        'SB_Steal': 'SB_Steal',
        'AF': 'AF',
        'WTSD_Vol': 'WTSD_Vol',
        'WSD_Vol': 'WSD_Vol',
        'Flop_CBet_HU': 'Flop_CBet_HU',
        'Flop_CBet_MW': 'Flop_CBet_MW',
        'Turn_CBet': 'Turn_CBet',
        'River_CBet': 'River_CBet',
        'Flop_Probe': 'Flop_Probe',
        'LT12BB_Errors': 'LT12BB_Errors',
        'Punts_per_100': 'Punts_per_100',
        'Mistakes_per_100': 'Mistakes_per_100',
        'RedLine_BB100': 'RedLine_BB100',
        'Pure_Bluff_Pct': 'Pure_Bluff_Pct',
        'Semi_Bluff_Pct': 'Semi_Bluff_Pct',
        'Value_Bet_Pct': 'Value_Bet_Pct',
        'ThreeBet_vs_EP': 'ThreeBet_vs_EP',
        'ThreeBet_vs_LP': 'ThreeBet_vs_LP',
        'Premiums_Pct': 'Premiums_Pct',
        'Top_Leak': 'Top_Leak',
        'VPIP_PFR_Gap': 'VPIP_PFR_Gap',
        'WWSF': 'WWSF',
        'Non_SD_Win': 'Non_SD_Win',
        'SD_Aggressor': 'SD_Aggressor',
        'Caller_IP_Flop_Agg': 'Caller_IP_Flop_Agg',
        'IP_Stab_Rate': 'IP_Stab_Rate',
        'Flop_Lead_Rate': 'Flop_Lead_Rate',
        'Float_Turn_Attack': 'Float_Turn_Attack',
        'Agg_React_Delta': 'Agg_React_Delta',
        'Draw_Overbet_Jams': 'Draw_Overbet_Jams',
        'Passive_Passive_Jam': 'Passive_Passive_Jam',
        'Triple_Barrel_Called_WR': 'Triple_Barrel_Called_WR',
        'Sizing_Geo_Pct': 'Sizing_Geo_Pct',
        'Small_Small_Jam_Ct': 'Small_Small_Jam_Ct',
        'CR_Flop_Pct': 'CR_Flop_Pct',
        'CR_Total_Pct': 'CR_Total_Pct',
        'ThreeBet_BTN': 'ThreeBet_BTN',
    }
    row = {col: src.get(KEY_MAP.get(col, col), '') for col in SESSION_HISTORY_COLUMNS}
    # Always use date_range for Batch_ID — single-day sessions get GG20260505,
    # multi-day get GG2026050405. csv_row's Batch_ID uses just one date which
    # would mismatch the run_log filename for multi-day sessions.
    row['Batch_ID'] = f"GG{vol.get('date_range','').replace('-','')}"
    if not row.get('Date'):
        row['Date'] = vol.get('date', '')
    if not row.get('Hands'):
        row['Hands'] = vol.get('hands', '')
    return row


def _build_run_log_row(stats, hands, hh_dir):
    """Build one gem_run_log CSV row. Token estimate is approximate
    (chars/4 across all HHs); processing_time stays empty (filled by
    pipeline runner if it tracks wall-clock time)."""
    import os as _os
    vol = stats.get('volume', {})
    n_files = vol.get('bullets', 0)
    parse_errors = vol.get('parse_errors', 0)
    # Token estimate: rough
    tokens_est = ''
    try:
        total_chars = 0
        if hh_dir and _os.path.isdir(hh_dir):
            for f in _os.listdir(hh_dir):
                if f.endswith('.txt'):
                    total_chars += _os.path.getsize(_os.path.join(hh_dir, f))
        if total_chars:
            tk = round(total_chars / 4 / 1000)
            tokens_est = f"~{tk}K"
    except Exception:
        pass

    notes = (f"v7.30 pipeline run. Quality: {stats.get('quality', {}).get('note','')}").replace(',', ';')

    return {
        'Date': vol.get('date', ''),
        'Session_ID': f"GG{vol.get('date_range','').replace('-','')}",
        'Hands': vol.get('hands', ''),
        'Tournaments': vol.get('tournaments', ''),
        'Files': n_files,
        'Tokens_Est': tokens_est,
        'Parse_Errors': parse_errors,
        'Processing_Time_Approx': '',
        'Notes': notes,
    }


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    print("gem_report_data.py is a module. Import generate_report_data() from gem_analyzer.py.")
    print("See docstring for integration instructions.")
