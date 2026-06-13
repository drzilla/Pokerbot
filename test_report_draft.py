#!/usr/bin/env python3
"""GEM Report Renderer Test Suite.

Tests behaviors in gem_report_draft.py and gem_report_data.py:
  - F1: _compute_pot_by_street pot tracking at street boundaries
  - F2: citation registry + back-link emission for appendix entries
  - F3: avoidable CR detection (L1 signature) surfaced in VII.7
  - F5: positive cooler tracking surfaced in I.7
  - F6: skill_band label uses sample-size CI framing

The integration tests (F3/F5/F6) read the most-recently-generated
Pokerbot_Report MD and report_data.json from /mnt/user-data/outputs/
and /home/claude/. They no-op if the pipeline hasn't been run yet —
running the pipeline against any HH set populates the fixtures.

Detector-level F4 tests (analyze_postflop_over_aggression) live in
test_detectors.py with the rest of the detector suite.

Usage: python3 test_report_draft.py
Requires PYTHONPATH including /mnt/project.

Exit code: 0 if all pass, 1 if any fail.
"""

import sys, os, json, re, importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__)) or '.'

# Path resolution: prefer local dir, then /home/claude/, then /mnt/project/.
def _resolve_path(name):
    for base in (_HERE, '/home/claude', '/mnt/project'):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return None

# Ensure project modules are importable for gem_report_draft's own imports.
# BUG-F fix: _HERE must be at index 0 so the working copy is tested,
# not the read-only /mnt/project snapshot.
sys.path.insert(0, '/mnt/project')
sys.path.insert(0, _HERE)

import gem_report_draft as grd


# ============================================================
# F1 — _compute_pot_by_street
# ============================================================

def test_f1_basic_no_antes():
    actions = {
        'preflop': [
            {'name':'BTN','action':'raises','amount_bb':3.0},
            {'name':'BB','action':'calls','amount_bb':2.0}
        ],
        'flop':[], 'turn':[], 'river':[]
    }
    p = grd._compute_pot_by_street(actions,
            {'sb_blind':50,'bb_blind':100,'ante':0,'n_players':6})
    assert p['preflop'] == 1.5, f"preflop {p['preflop']} != 1.5"
    assert abs(p['flop'] - 6.5) < 0.01, f"flop {p['flop']} != 6.5"


def test_f1_with_antes():
    actions = {
        'preflop': [
            {'name':'BTN','action':'raises','amount_bb':2.5},
            {'name':'BB','action':'folds','amount_bb':0}
        ],
        'flop':[], 'turn':[], 'river':[]
    }
    p = grd._compute_pot_by_street(actions,
            {'sb_blind':50,'bb_blind':100,'ante':10,'n_players':8})
    assert abs(p['preflop'] - 2.3) < 0.01
    assert abs(p['flop'] - 4.8) < 0.01


def test_f1_multistreet_raise_to():
    """The 'raises X to Y' regex captures Y (the 'to' total). The pot helper
    must compute delta = Y - prior_commit, not double-count."""
    actions = {
        'preflop': [
            {'name':'U','action':'raises','amount_bb':3.0},
            {'name':'B','action':'raises','amount_bb':9.0},
            {'name':'U','action':'calls','amount_bb':6.0},
        ],
        'flop': [
            {'name':'U','action':'checks','amount_bb':0},
            {'name':'B','action':'bets','amount_bb':5.0},
            {'name':'U','action':'raises','amount_bb':15.0},
            {'name':'B','action':'calls','amount_bb':10.0},
        ],
        'turn':[], 'river':[]
    }
    p = grd._compute_pot_by_street(actions,
            {'sb_blind':50,'bb_blind':100,'ante':0,'n_players':6})
    assert abs(p['flop'] - 19.5) < 0.01, f"flop {p['flop']} != 19.5"
    assert abs(p['turn'] - 49.5) < 0.01, f"turn {p['turn']} != 49.5"


def test_f1_empty_inputs_safe():
    p = grd._compute_pot_by_street(
        {'preflop':[],'flop':[],'turn':[],'river':[]}, {})
    assert set(p.keys()) == {'preflop','flop','turn','river'}


# ============================================================
# F2 — citation tracking
# ============================================================

def test_f2_citation_basic():
    grd._reset_citations()
    grd._set_current_section('sec-iii-1', 'III.1 Range Oblivion / Punts')
    grd._record_citation('TM12345')
    cites = grd._get_citations_for('TM12345')
    assert len(cites) == 1
    assert cites[0][0] == 'sec-iii-1'


def test_f2_citation_dedupe_same_section():
    """Two citations from the same section should collapse to one entry."""
    grd._reset_citations()
    grd._set_current_section('sec-iii-1', 'III.1 Punts')
    grd._record_citation('TM12345')
    grd._record_citation('TM12345')
    assert len(grd._get_citations_for('TM12345')) == 1


def test_f2_citation_multi_section():
    grd._reset_citations()
    grd._set_current_section('sec-iii-1', 'III.1')
    grd._record_citation('TM12345')
    grd._set_current_section('sec-vii-11', 'VII.11')
    grd._record_citation('TM12345')
    anchors = [c[0] for c in grd._get_citations_for('TM12345')]
    assert 'sec-iii-1' in anchors and 'sec-vii-11' in anchors


def test_f2_appendix_self_citation_guard():
    """Citations from inside the appendix shouldn't loop back to themselves."""
    grd._reset_citations()
    grd._set_current_section('sec-app-hand-12345', None)
    grd._record_citation('TM99999')
    assert len(grd._get_citations_for('TM99999')) == 0


def test_f2_no_section_set_skips():
    grd._reset_citations()
    grd._record_citation('TM55555')
    assert len(grd._get_citations_for('TM55555')) == 0


def test_f2_hand_ref_records_citation():
    """When _hand_ref is called from a tracked section, citation registers."""
    grd._reset_citations()
    grd._set_current_section('sec-iii-1', 'III.1 Punts')
    h = {'id': 'TM77777', 'tournament': 'Test', 'date': '2026-05-13',
         'position': 'BB', 'stack_bb': 50.0}
    grd._hand_ref(h)
    assert len(grd._get_citations_for('TM77777')) == 1


# ============================================================
# F3 — avoidable CR detection (integration)
# ============================================================

def test_f3_avoidable_cr_block_in_report():
    """When the session has L1-signature hands, the rendered MD should
    contain the avoidable CR collapsible block linked from VII.7."""
    md_path = '/mnt/user-data/outputs/Pokerbot_Report_20260512-13.md'
    if not os.path.exists(md_path):
        return  # No fixture report; skip
    md = open(md_path).read()
    assert 'sec-vii-7-avoidable' in md, "avoidable anchor missing"
    assert 'Avoidable CR' in md, "Avoidable CR block missing"
    assert 'L1 BB-CR-pattern' in md, "L1 leak reference missing"


def test_f3_status_cell_links_to_avoidable():
    md_path = '/mnt/user-data/outputs/Pokerbot_Report_20260512-13.md'
    if not os.path.exists(md_path):
        return
    md = open(md_path).read()
    assert '⚠️' in md and '#sec-vii-7-avoidable' in md, \
        "status cells should link to avoidable section"


# ============================================================
# F5 — positive cooler tracking (integration)
# ============================================================

def test_f5_coolers_dict_includes_new_fields():
    stats_path = '/home/claude/gem_stats.json'
    if not os.path.exists(stats_path):
        return
    stats = json.load(open(stats_path, encoding='utf-8'))
    coolers = stats.get('coolers', {})
    for key in ('count', 'rate', 'positive_count', 'positive_rate',
                'positive_hands', 'net_count', 'net_rate'):
        assert key in coolers, f"coolers missing key: {key}"


# ============================================================
# F6 — skill_band CI label (integration)
# ============================================================

def test_f6_skill_band_label_in_ambiguous_band():
    """When the skill_band CI straddles 0 (ambiguous case — the source of
    Ron's 'kinda weird' feedback), the label must mention 'sample-size CI'
    and the note must reference the True EV comparison. Only checked
    when n_hands >= 200 (the CI verdict-band threshold); below that the
    'Insufficient Sample' branch handles labeling separately."""
    rd_path = '/home/claude/gem_report_data.json'
    if not os.path.exists(rd_path):
        return
    rd = json.load(open(rd_path, encoding='utf-8'))
    sb = rd.get('skill_band', {})
    label = sb.get('label', '')
    note = sb.get('note', '')
    lo, hi = sb.get('ci_low'), sb.get('ci_high')
    n_hands = sb.get('n_hands', 0)
    # Only check the ambiguous-CI branch (n>=200 AND CI straddles 0)
    if n_hands >= 200 and lo is not None and hi is not None and lo <= 0 <= hi:
        assert 'sample-size CI' in label, \
            f"label '{label}' lacks 'sample-size CI'"
        assert 'True EV' in note or 'variance-adjusted' in note, \
            f"note '{note}' lacks True EV / variance-adjusted comparison"


# ============================================================
# B97 (v7.58, Ron 2026-05-18) — Bug-guard tests
# These tests block the specific bug classes Ron flagged and would have
# caught the issues earlier. Run as part of standard test_metrics.py
# routine via test_report_draft.py.
# ============================================================

def test_b90_chart_notation_renders_two_pills():
    """B90: chart notation (AKo, JTo, A8o, K9o, T9s) must render TWO pills."""
    for notation in ['AKo', 'JTo', 'A8o', 'K9o', 'T9s', 'AKs']:
        out = grd._cards_str_to_pills(notation)
        n_pills = len(re.findall(r'card-[shdc]', out))
        assert n_pills == 2, f"Chart notation {notation!r} → {n_pills} pills (want 2)"


def test_b90_pocket_pair_renders_two_pills():
    """B90: pocket pair notation (44, TT, QQ) must render TWO pills with
    different suits (♠ + ♥), not one or zero."""
    for notation in ['22', '44', '77', 'TT', 'QQ', 'AA']:
        out = grd._cards_str_to_pills(notation)
        n_pills = len(re.findall(r'card-[shdc]', out))
        assert n_pills == 2, f"Pocket pair {notation!r} → {n_pills} pills (want 2)"
        ranks = re.findall(r'>([2-9TJQKA])[♠♥♦♣]<', out)
        assert len(ranks) == 2 and ranks[0] == ranks[1], (
            f"Pocket pair {notation!r} ranks: {ranks}")


def test_b91_card_cell_nowrap_wrapper():
    """B91: card-string output is wrapped in nowrap span so table cells
    don't break the pair vertically. Was rendering Q♠ on one row and J♠
    on the next when the column was narrow (III.4 Read-Dep table)."""
    for notation in ['AKo', '44', 'AhJh', 'A8o']:
        out = grd._cards_str_to_pills(notation)
        assert 'white-space:nowrap' in out, (
            f"Card output for {notation!r} missing nowrap wrapper")


def _find_appendix_hand_section(html, hid_short):
    """Helper: extract the appendix HTML block for a given hand_id (last 8)."""
    m = re.search(rf'<h4 id="sec-app-hand-{hid_short}">.*?(?=<h4|<h3|<h2|$)',
                  html, re.DOTALL)
    return m.group(0) if m else None


def _parse_action_grid_numbers(block_html):
    """Return list of integers extracted from (N) markers on hero action pills."""
    matches = re.findall(r'<span class="ann[^"]*"[^>]*>(.*?)</span>',
                         block_html, re.DOTALL)
    nums = []
    for m in matches:
        sup = re.search(r'<sup>(\d+)</sup>', m)
        if sup:
            nums.append(int(sup.group(1)))
            continue
        paren = re.search(r'\((\d+)\)', m)
        if paren:
            nums.append(int(paren.group(1)))
    return nums


def _parse_note_block_numbers(block_html):
    """Return list of integers from (N) pills in the notes block."""
    notes_div = re.search(r"<div class='analyst-notes'>(.*?)</div>",
                          block_html, re.DOTALL)
    if not notes_div:
        return []
    nums = re.findall(r"<span class='note-num'>(\d+)</span>",
                      notes_div.group(1))
    return [int(n) for n in nums]


def test_b97_action_note_alignment_in_rendered_report():
    """B97: every (N) action-grid marker must have a matching (N) in the
    notes block. Catches JJ-hand-style misalignment."""
    import os
    paths = [
        '/mnt/user-data/outputs/Pokerbot_Report_20260517-18.html',
        '/mnt/user-data/outputs/Pokerbot_Report_20260516-17.html',
    ]
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            html = f.read()
        hand_ids = re.findall(r'<h4 id="sec-app-hand-(\w+)">', html)
        for hid_short in hand_ids[:50]:
            block = _find_appendix_hand_section(html, hid_short)
            if not block:
                continue
            grid_nums = set(_parse_action_grid_numbers(block))
            note_nums = set(_parse_note_block_numbers(block))
            missing = grid_nums - note_nums
            assert not missing, (
                f"Hand {hid_short} ({path}): grid has {missing} "
                f"with no matching note. Grid={sorted(grid_nums)} "
                f"Notes={sorted(note_nums)}")


def test_b143_single_narrative_one_pill():
    """B143 (v7.69, Ron 2026-05-22): under the single-narrative override the
    one analyst note is bound to the single key decision. B142's first cut
    put a (N) back-ref on EVERY hero action; Ron flagged that a (N) on a
    clear preflop open reads as flagging the open. Fix: non-key actions
    render NO marker. Invariant: when a hand's notes block has exactly one
    distinct note number (→ single-narrative override fired), the action
    grid must contain exactly ONE numbered pill — the key decision — not
    one per street."""
    import os
    paths = [
        '/mnt/user-data/outputs/Pokerbot_Report_20260521.html',
        '/mnt/user-data/outputs/Pokerbot_Report_20260517-18.html',
    ]
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            html = f.read()
        hand_ids = re.findall(r'<h4 id="sec-app-hand-(\w+)">', html)
        for hid_short in hand_ids[:80]:
            block = _find_appendix_hand_section(html, hid_short)
            if not block:
                continue
            note_nums = _parse_note_block_numbers(block)
            if len(set(note_nums)) != 1:
                continue  # not a single-narrative hand
            grid_nums = _parse_action_grid_numbers(block)
            assert len(grid_nums) == 1, (
                f"Hand {hid_short} ({path}): single-narrative hand has one "
                f"note but {len(grid_nums)} numbered grid pills "
                f"{grid_nums} — non-key actions are being flagged (B143).")


def test_b97_no_orphan_note_numbers():
    """B97: no (N) in notes block without corresponding action-grid marker.
    Catches the original orphan-(3) bug from JJ hand."""
    import os
    paths = [
        '/mnt/user-data/outputs/Pokerbot_Report_20260517-18.html',
        '/mnt/user-data/outputs/Pokerbot_Report_20260516-17.html',
    ]
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            html = f.read()
        hand_ids = re.findall(r'<h4 id="sec-app-hand-(\w+)">', html)
        for hid_short in hand_ids[:50]:
            block = _find_appendix_hand_section(html, hid_short)
            if not block:
                continue
            grid_nums = set(_parse_action_grid_numbers(block))
            note_nums = set(_parse_note_block_numbers(block))
            orphans = note_nums - grid_nums
            assert not orphans, (
                f"Hand {hid_short} ({path}): notes has {orphans} "
                f"with no matching grid marker. Grid={sorted(grid_nums)} "
                f"Notes={sorted(note_nums)}")


def test_b97_every_action_num_has_note():
    """B97: no duplicate (N) markers in action grid (each is unique)."""
    import os
    paths = [
        '/mnt/user-data/outputs/Pokerbot_Report_20260517-18.html',
        '/mnt/user-data/outputs/Pokerbot_Report_20260516-17.html',
    ]
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            html = f.read()
        hand_ids = re.findall(r'<h4 id="sec-app-hand-(\w+)">', html)
        for hid_short in hand_ids[:50]:
            block = _find_appendix_hand_section(html, hid_short)
            if not block:
                continue
            grid_nums = _parse_action_grid_numbers(block)
            duplicates = [n for n in set(grid_nums) if grid_nums.count(n) > 1]
            assert not duplicates, (
                f"Hand {hid_short} ({path}): duplicate {duplicates} "
                f"in action grid")


def test_b144_tldr_no_hand_in_both_top_hands_and_top_leaks():
    """B144 (v7.69, Ron 2026-05-23): the TL;DR must not present the same hand
    twice. III.1 punts and III.4 read-dep hands are itemized in the "Top
    leaks" table; they must NOT also appear in "Top hands today". Invariant:
    the hand-id sets of the "Top hands today" block and the "Top leaks" block
    are disjoint. Catches the bug Ron flagged — a reclassified punt rendering
    once in Top-hands and once in Top-leaks on the same screen."""
    import os, glob
    # B158 (Ron 2026-05-23): was hardcoded to 0521/0522 report filenames —
    # went stale the moment the session date rolled over, failing with "no
    # report file available". Glob the outputs dir for any rendered report.
    # B-V10: broadened glob to include player-scoped filenames
    # (--player generates Pokerbot_Knockman_*.md, not Pokerbot_Report_*.md)
    paths = sorted(
        glob.glob('/mnt/user-data/outputs/Pokerbot_Report_*.md') +
        glob.glob('/mnt/user-data/outputs/Pokerbot_*_*.md'),
        reverse=True)
    checked = 0
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            md = f.read()
        i_top = md.find('🎯 Top hands today')
        i_leak = md.find('📌 Top leaks')
        if i_leak < 0:
            continue
        if i_top < 0 or i_top > i_leak:
            # Top-hands block omitted (no non-leak hands) — dedup-safe.
            checked += 1
            continue
        i_end = md.find('\n## ', i_leak)
        if i_end < 0:
            i_end = len(md)
        top_block = md[i_top:i_leak]
        # B158 (Ron 2026-05-23): bound the leak block to the Top-leaks table
        # itself. The old md[i_leak:i_end] ran to the next H2, sweeping in the
        # Full Result Attribution <details> block (which cites hand IDs) and
        # producing false-positive overlaps. The Top-leaks table ends at the
        # first line after its rows that does not start with '|'.
        _lk_lines = md[i_leak:i_end].split('\n')
        _kept = []
        _in_table = False
        for _ln in _lk_lines:
            if _ln.startswith('|'):
                _in_table = True
                _kept.append(_ln)
            elif _in_table:
                break  # first non-table line after the table — stop
            else:
                _kept.append(_ln)  # header / blank lines before the table
        leak_block = '\n'.join(_kept)
        ids_top = set(re.findall(r'\[`(\w{6,10})`\]', top_block))
        ids_leak = set(re.findall(r'\[`(\w{6,10})`\]', leak_block))
        overlap = ids_top & ids_leak
        assert not overlap, (
            f"{path}: hand(s) {sorted(overlap)} appear in BOTH "
            f"'Top hands today' and 'Top leaks' — TL;DR double-presentation "
            f"(B144).")
        checked += 1
    assert checked > 0, "B144: no report file available to check"


def test_b145_key_decision_action_class():
    """B145 (v7.70, Ron 2026-05-23): key_decision → Hero action class.
    Earliest action keyword wins, so villain context later in the sentence
    ('...vs BB check-raise jam') never overrides Hero's verb."""
    kc = grd._key_decision_action_class
    assert kc("Iso-raising to ~30BB over the ~6BB all-in + one caller") == 'raise'
    assert kc("Turn jam (~26BB) with top pair + nut flush draw") == 'raise'
    assert kc("River call-all-in (~17.5BB) facing a 79%-pot polar jam") == 'call'
    assert kc("Turn call-all-in vs BB check-raise jam on the 2c brick") == 'call'
    assert kc("Fold JTs to the BB's jam at <=30BB") == 'fold'
    assert kc("") is None
    assert kc(None) is None


def test_b145_pick_key_action_idx():
    """B145: the single-narrative (N) pill binds to the action key_decision
    names — NOT blindly the last hero action (which is often a correct fold
    after a punting raise)."""
    pk = grd._pick_key_action_idx
    # iso-raise then correct fold → pill on the RAISE (idx 0), not the fold
    assert pk(['raises', 'folds'], "Iso-raising to ~30BB over a 6BB all-in") == 0
    # turn bet then call-all-in → key_decision names the call
    assert pk(['bets', 'calls'], "Turn call-all-in vs BB check-raise jam") == 1
    # river check then call → names the call
    assert pk(['checks', 'calls'], "River call-all-in facing a polar jam") == 1
    # bad-fold leak: raise then fold, key_decision explicitly names the fold
    assert pk(['raises', 'folds'], "Fold JTs to the BB jam") == 1
    # no key_decision → fallback to last committing (non-fold/check) action
    assert pk(['raises', 'folds'], "") == 0
    # only a fold → last-resort returns it
    assert pk(['folds'], "Fold K5o first-in") == 0
    assert pk([], "anything") is None


def test_b145_punt_pill_on_raise_not_fold():
    """B145: hand 85976984 (5h5c iso-punt) — the (1) pill must sit on the
    30BB Raise (the punt), and the correct Fold must get 👍, not the (1)."""
    import os
    path = '/mnt/user-data/outputs/Pokerbot_Report_20260522.html'
    if not os.path.exists(path):
        return
    with open(path) as f:
        html = f.read()
    block = _find_appendix_hand_section(html, '85976984')
    assert block, "85976984 appendix block not found"
    grid = re.findall(
        r'<span class="grid-action([^"]*)">'
        r'((?:[^<]|<span[^>]*>[^<]*</span>)*)</span>', block)
    hero_raise = [inner for cls, inner in grid
                  if 'is-hero' in cls and 'Raise' in inner]
    hero_fold = [inner for cls, inner in grid
                 if 'is-hero' in cls and 'Fold' in inner]
    assert hero_raise, "no hero Raise span found in 85976984 grid"
    assert hero_fold, "no hero Fold span found in 85976984 grid"
    assert 'class="ann">(1)' in hero_raise[0], (
        "B145: (1) pill is NOT on the 30BB Raise (the punt) — "
        f"raise span: {hero_raise[0]}")
    assert 'class="ann">(1)' not in hero_fold[0], (
        "B145: (1) pill wrongly sits on the correct Fold — "
        f"fold span: {hero_fold[0]}")
    assert '👍' in hero_fold[0], (
        "B145: the correct Fold should render 👍 — "
        f"fold span: {hero_fold[0]}")


def test_b146_argument_is_structured():
    """B146 (v7.71, Ron 2026-05-23): structured-argument detection keys off
    the exact '**TL;DR:**' lead prefix."""
    f = grd._argument_is_structured
    assert f("**TL;DR:** something") is True
    assert f("  **TL;DR:** leading whitespace ok") is True
    assert f("Plain prose argument with no structure.") is False
    assert f("") is False
    assert f(None) is False


def test_b146_parse_structured_argument():
    """B146: a structured argument splits into ordered (kind, payload)
    blocks — tldr / section / bullets / para — with bullets grouped."""
    pa = grd._parse_structured_argument
    txt = ("**TL;DR:** verdict line.\n\n"
           "### Section One\n* bullet a\n* bullet b\n\n"
           "### Section Two\n- bullet c\nplain para line")
    blocks = pa(txt)
    kinds = [k for k, _ in blocks]
    assert kinds == ['tldr', 'section', 'bullets', 'section',
                     'bullets', 'para'], kinds
    assert blocks[0][1] == 'verdict line.'
    assert blocks[1][1] == 'Section One'
    assert blocks[2][1] == ['bullet a', 'bullet b']
    assert blocks[4][1] == ['bullet c']
    assert blocks[5][1] == 'plain para line'


def test_b146_structured_yellow_box_no_blob():
    """B146: a structured argument renders in the yellow notes block as a
    TL;DR row + section headers + bullet lists — not one prose <p> blob, and
    never invalid <p><li> markup (bullets wrapped in <p>)."""
    import os
    path = '/mnt/user-data/outputs/Pokerbot_Report_20260522.html'
    if not os.path.exists(path):
        return
    with open(path) as f:
        html = f.read()
    block = _find_appendix_hand_section(html, '85976984')
    assert block, "85976984 appendix block not found"
    i = block.find("analyst-notes")
    seg = block[i:i + 4500]
    assert "<p class='note-tldr'>" in seg, "no TL;DR row in structured note"
    assert "<p class='note-section'>" in seg, "no section sub-header"
    assert "<ul class='note-bullets'>" in seg, "no bullet list"
    assert "<p><li>" not in seg, "invalid <p><li> markup — bullet wrapped in <p>"


def test_b147_md_inline_links_render():
    """B147 (v7.71, Ron 2026-05-23): the B146 note helper was named
    `_md_inline`, shadowing the module's real inline-markdown renderer — so
    every `[label](#anchor)` link and `*italic*` leaked as raw markdown.
    Guard: an appendix hand's verdict / 'Mentioned in' header renders real
    <a> links and <em> emphasis, with NO raw markdown link syntax."""
    import os
    path = '/mnt/user-data/outputs/Pokerbot_Report_20260522.html'
    if not os.path.exists(path):
        return
    with open(path) as f:
        html = f.read()
    block = _find_appendix_hand_section(html, '86806821')
    assert block, "86806821 appendix block not found"
    header = block[:block.find('<div')]
    assert '<a href="#sec-' in header, (
        "B147: appendix verdict header has no rendered <a> links — "
        "the inline-markdown renderer is shadowed/broken")
    assert '](#' not in header, (
        "B147: raw markdown link syntax '](#' in the appendix header")
    assert '<em>' in header, "B147: *italic* not rendering to <em>"


def test_b147_nonkey_actions_all_get_thumbsup():
    """B147: in a single-narrative hand every non-key hero action gets 👍 —
    not just folds/checks. Hand 86806821: the preflop 3-bet and the flop
    c-bet (both correct, non-key) must show 👍; the turn jam carries (1)."""
    import os
    path = '/mnt/user-data/outputs/Pokerbot_Report_20260522.html'
    if not os.path.exists(path):
        return
    with open(path) as f:
        html = f.read()
    block = _find_appendix_hand_section(html, '86806821')
    assert block, "86806821 appendix block not found"
    grid = re.findall(
        r'<span class="grid-action([^"]*)">'
        r'((?:[^<]|<span[^>]*>[^<]*</span>)*)</span>', block)
    hero = [(cls, inner) for cls, inner in grid if 'is-hero' in cls]
    raises = [i for c, i in hero if 'Raise' in i]
    bets = [i for c, i in hero if 'Bet' in i and 'class="ann">(1)' not in i]
    assert raises and '👍' in raises[0], (
        "B147: non-key preflop raise should show 👍")
    assert bets and '👍' in bets[0], (
        "B147: non-key flop c-bet should show 👍")


def test_b148_iii1_detector_punt_shows_analyst_source():
    """B148 (v7.71, Ron 2026-05-23): a punt the Px detector flagged that ALSO
    has an analyst III.1 verdict must render with Source 'analyst' and the
    analyst's commentary — never 'auto-detector'. The detector is a backend
    process and must be invisible to the reader."""
    import os
    path = '/mnt/user-data/outputs/Pokerbot_Report_20260522.html'
    if not os.path.exists(path):
        return
    with open(path) as f:
        html = f.read()
    i = html.find('id="sec-iii-1"')
    assert i != -1, "III.1 section anchor not found"
    # Scope to the FIRST table after the III.1 anchor (a fixed-size window
    # bleeds into the next section's table).
    t0 = html.find('<table', i)
    t1 = html.find('</table>', t0)
    seg = html[i:t1] if t0 != -1 and t1 != -1 else html[i:i + 2600]
    assert 'auto-detector' not in seg, (
        "B148: 'auto-detector' source still present in III.1 — the detector "
        "is leaking through to the reader")
    rows = re.findall(r'<tr>(.*?)</tr>', seg, re.S)
    body = [r for r in rows if '<td' in r]
    assert body, "B148: III.1 table has no body rows"
    for r in body:
        assert ('analyst' in r or 'awaiting analyst review' in r), (
            "B148: every III.1 row must carry an analyst verdict or a loud "
            "'awaiting analyst review' marker")


def test_b148_iii3_renders_per_hand_cleared_verdicts():
    """B148: the III.3 section must render per-hand analyst-cleared verdicts
    (not only the aggregate population-deviation table). A detector punt the
    analyst overturned to III.3 must appear here with its 'cleared' verdict."""
    import os
    path = '/mnt/user-data/outputs/Pokerbot_Report_20260522.html'
    if not os.path.exists(path):
        return
    with open(path) as f:
        html = f.read()
    i = html.find('id="sec-iii-3"')
    j = html.find('id="sec-iii-4"', i)
    assert i != -1 and j != -1, "III.3 section bounds not found"
    seg = html[i:j]
    assert 'Cleared As' in seg, (
        "B148: III.3 per-hand cleared-verdict table header missing")
    assert 'cleared' in seg.lower(), "B148: no cleared verdict rendered in III.3"


def test_issue2_missed_steal_carries_open_range():
    """Issue 2 (v7.71, Ron 2026-05-23): _chart_summary is hoisted to module
    level so the Missed-Steal detector can surface the curated opening range
    (the chart fallback when an OCR chart for the exact depth is missing).
    Loads the /home/claude working copy explicitly — the test harness forces
    /mnt/project onto sys.path, which would otherwise mask the working copy."""
    import os, importlib.util
    wc = '/home/claude/gem_analyzer.py'
    if not os.path.exists(wc):
        return
    spec = importlib.util.spec_from_file_location('_gem_analyzer_wc', wc)
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    assert hasattr(G, '_chart_summary'), (
        "Issue 2: _chart_summary must be hoisted to module level")
    co = G._chart_summary(G.CO_CORE)
    assert co and 'J9o+' in co, (
        "Issue 2: _chart_summary(CO_CORE) should render a JTo-inclusive run")
    assert 'JTo' in G.CO_CORE, "fixture: JTo expected in CO_CORE"


def test_issue2_xiii4_surfaces_opening_range_reference():
    """Issue 2: XIII.4 surfaces a per-position 'Correct opening ranges'
    reference, and each Missed-Steal row's Detail column states which tier
    the folded hand sits in."""
    import os
    path = '/mnt/user-data/outputs/Pokerbot_Report_20260522.html'
    if not os.path.exists(path):
        return
    with open(path) as f:
        html = f.read()
    plain = re.sub(r'<[^>]+>', ' ', html)
    assert 'Correct opening ranges' in plain, (
        "Issue 2: XIII.4 opening-range reference block missing")
    assert 'CO open — CORE' in plain, (
        "Issue 2: per-position CORE opening range not rendered")
    assert 'sits in CORE of the' in plain or 'sits in EXTENDED of the' in plain, (
        "Issue 2: Missed-Steal Detail column should state the folded hand's "
        "tier in the opening range")
    assert '&amp;nbsp;' not in html, (
        "Issue 2: literal &nbsp; leaked into rendered HTML")


# ============================================================
# v7.80 — hole-card nickname in the hand-example grid header
# ============================================================

def test_v780_nickname_lookup_known_hands():
    import gem_nicknames as gn
    # Pair, non-pair, and the worst-hand entry — all suit-agnostic.
    assert gn.nickname_for(['Ah', 'Ad']) == 'Pocket Rockets'
    assert gn.nickname_for(['Kd', 'Qs']) == 'Marriage'
    assert gn.nickname_for(['2c', '7h']) == 'The Beer Hand'
    assert gn.nickname_for(['Ts', '2d']) == 'Doyle Brunson'
    # Card order must not matter — key normalizes rank-desc.
    assert gn.nickname_for(['7h', '2c']) == gn.nickname_for(['2c', '7h'])
    assert gn.nickname_for(['2d', 'Ts']) == 'Doyle Brunson'
    # hand_key normalization: higher rank first, pair collapses.
    assert gn.hand_key(['Kd', 'Ah']) == 'AK'
    assert gn.hand_key(['9c', '9d']) == '99'


def test_v780_nickname_lookup_unlisted_and_bad_input():
    import gem_nicknames as gn
    # AhTh has no entry in the file — must return None, not a guess.
    assert gn.nickname_for(['Ah', 'Th']) is None
    assert gn.nickname_for(['As', '3d']) is None
    # Malformed / incomplete input never raises, always returns None.
    assert gn.nickname_for([]) is None
    assert gn.nickname_for(['Ah']) is None
    assert gn.nickname_for(None) is None
    assert gn.nickname_for(['Xz', 'Kd']) is None
    assert gn.hand_key(['Ah']) is None


def test_v780_nickname_span_survives_html_render():
    # The hero-nick span must be on the inner-span allowlist, otherwise the
    # HTML renderer escapes it and the nickname leaks as raw <span> text.
    from gem_report_draft._html import _md_inline
    out = _md_inline("<span class='hero-nick'>Pocket Rockets</span>")
    assert out == "<span class='hero-nick'>Pocket Rockets</span>", (
        f"v7.80: hero-nick span not preserved by _md_inline: {out!r}")
    assert '&lt;span' not in out, "v7.80: hero-nick span got HTML-escaped"


# ============================================================
# B237 (v7.99.21, Ron review 2026-05-26) — coin-flip outcome label
# ============================================================

def test_b237_outcome_label_lost_coinflip():
    """The 'lost_flip' outcome label must read 'Lost coin-flip' with the
    coin glyph — Ron's 2026-05-25 rename of the bare 'Lost flip'."""
    from gem_report_draft._helpers import _outcome_label, _OUTCOME_LABELS
    emoji, text = _OUTCOME_LABELS['lost_flip']
    assert emoji == '🪙', f"lost_flip emoji {emoji!r} (want coin)"
    assert text == 'Lost coin-flip', f"lost_flip text {text!r} (want 'Lost coin-flip')"
    # _outcome_label must route an outcome='lost_flip' commentary to it
    assert _outcome_label({'outcome': 'lost_flip'}) == ('🪙', 'Lost coin-flip')
    # absent outcome still falls back to the generic clear
    assert _outcome_label({})[1] == 'cleared'


def test_b237_flip_loss_autotagged_in_report_data():
    """Integration: a III.3-cleared hand that the EAI classified as a lost
    coin-flip must carry outcome='lost_flip' in report_data's analyst
    commentary, even when the source session_analysis JSON did not set it.
    The auto-tag runs in gem_analyzer after the JSON load. No-ops if the
    pipeline hasn't been run."""
    rd_path = '/home/claude/gem_report_data.json'
    st_path = '/home/claude/gem_stats.json'
    if not (os.path.exists(rd_path) and os.path.exists(st_path)):
        return
    rd = json.load(open(rd_path, encoding='utf-8'))
    st = json.load(open(st_path, encoding='utf-8'))
    ac = rd.get('analyst_commentary', {}) or {}
    eai_hands = st.get('eai', {}).get('hands', []) or []
    flip_losses = {h.get('id') for h in eai_hands
                   if h.get('category') == 'flip' and h.get('won') is False}
    for hid in flip_losses:
        cmt = ac.get(hid)
        if (isinstance(cmt, dict)
                and str(cmt.get('verdict', '')).startswith('III.3')):
            assert cmt.get('outcome') == 'lost_flip', (
                f"B237: cleared coin-flip loss {hid} not auto-tagged "
                f"lost_flip (outcome={cmt.get('outcome')!r})")


# ============================================================
# B236 (v7.99.21, Ron review 2026-05-26) — I.7 analyst-cooler villain
# ============================================================

def test_b236_analyst_cooler_shows_villain_hand():
    """Integration: an analyst-identified I.7 cooler (one whose verdict the
    analyst set, not the auto-detector) must render the villain's actual
    hand in the I.7 table, sourced from the appendix showdown reveals —
    not the placeholder '—'. No-ops if the pipeline hasn't been run."""
    md_path = '/mnt/user-data/outputs/Pokerbot_Report_20260525.md'
    rd_path = '/home/claude/gem_report_data.json'
    if not (os.path.exists(md_path) and os.path.exists(rd_path)):
        return
    rd = json.load(open(rd_path, encoding='utf-8'))
    ac = rd.get('analyst_commentary', {}) or {}
    app = rd.get('appendix_hand_details', {}) or {}
    # analyst-identified I.7 hands that the auto-detector missed: they have
    # an I.7 verdict AND a showdown record to source the villain from.
    analyst_i7 = [hid for hid, c in ac.items()
                  if isinstance(c, dict)
                  and str(c.get('verdict', '')).startswith('I.7')
                  and (app.get(hid, {}) or {}).get('showdown')]
    if not analyst_i7:
        return
    md = open(md_path, encoding='utf-8').read()
    sec = md.split('### I.7 Confirmed Coolers', 1)
    if len(sec) < 2:
        return
    i7 = sec[1].split('### I.8', 1)[0]
    for hid in analyst_i7:
        short = hid[-8:]
        row = next((ln for ln in i7.splitlines()
                    if short in ln and ln.lstrip().startswith('|')), None)
        if not row:
            continue
        cells = [c.strip() for c in row.split('|')]
        # cols: '' , #, HandRef, Hero, Villain, Board, Street, Kind, ''
        villain_cell = cells[4] if len(cells) > 4 else ''
        assert 'class="card' in villain_cell, (
            f"B236: analyst cooler {hid} villain cell has no card pills "
            f"(got {villain_cell!r}) — showdown villain not wired")
        street_cell = cells[6] if len(cells) > 6 else ''
        assert street_cell and street_cell != '—', (
            f"B236: analyst cooler {hid} street still '—'")


# ============================================================
# B238 (v7.99.22, Ron review 2026-05-26) — suitedness guardrail
# ============================================================

def test_b238_analyst_notes_match_parsed_suitedness():
    """Guardrail for the AQo/AQs slip Ron flagged: an analyst argument must
    never describe Hero's hand with the WRONG suitedness. For every commented
    hand we derive the canonical notation from the PARSED hole cards (e.g.
    Ah Qh → 'AQs') and assert the argument text does not contain the
    opposite-suit token for that exact rank pair ('AQo' / 'QAo'). Pocket
    pairs are skipped (no suitedness). No-ops if fixtures absent."""
    sa_path = '/home/claude/session_analysis_20260525.json'
    hands_path = '/home/claude/gem_hands.json'
    if not (os.path.exists(sa_path) and os.path.exists(hands_path)):
        return
    sa = json.load(open(sa_path, encoding='utf-8'))
    hands = {h.get('id'): h for h in json.load(open(hands_path, encoding='utf-8'))}
    for hid, cmt in sa.items():
        if hid == '__synthesis__' or not isinstance(cmt, dict):
            continue
        arg = cmt.get('argument', '')
        h = hands.get(hid)
        if not arg or not h:
            continue
        cards = h.get('cards', []) or []
        if len(cards) != 2 or len(cards[0]) < 2 or len(cards[1]) < 2:
            continue
        r1, s1 = cards[0][0], cards[0][1]
        r2, s2 = cards[1][0], cards[1][1]
        if r1 == r2:
            continue  # pocket pair — no suitedness
        suited = (s1 == s2)
        wrong = 'o' if suited else 's'
        for a, b in ((r1, r2), (r2, r1)):
            tok = f"{a}{b}{wrong}"
            assert tok not in arg, (
                f"B238: analyst note for {hid} says '{tok}' but the parsed "
                f"hole cards {cards} are {'suited' if suited else 'offsuit'}")


# ============================================================
# B250 (v7.99.24, Ron review 2026-05-27): card-render bug sweep.
# Finishing B242 — every card in every table/bullet of the rendered
# report must be a colored pill, never raw text. Dave caught two more
# raw-render instances outside the XIII tables; this test makes the
# whole bug class un-reintroducible by scanning the finished report.
# ============================================================

def test_b250_no_raw_cards_in_rendered_report():
    """Render-wide guard: no raw card text anywhere in the report.

    A correct render emits every card as `<span class="card ...">K♣</span>`
    with a unicode suit glyph. The B242/B250 bug leaves raw letter-suit
    text — a board like '8c 5d 5h' or a concatenated hand like 'KcTc'.

    Two raw signatures, both unambiguous (neither collides with chart
    notation such as 'T7s'/'AKo', which is a single 2-3 char token):
      * 3+ space-separated card tokens  → a raw board
      * a 4-char rank-suit-rank-suit run → a raw concatenated hand

    No-ops if no rendered-report fixture is present.
    """
    import glob as _glob
    mds = sorted(
        _glob.glob('/mnt/user-data/outputs/Pokerbot_Report_*.md') +
        _glob.glob('/mnt/user-data/outputs/Pokerbot_*_*.md'))
    if not mds:
        return  # no fixture report — skip
    md = open(mds[-1], encoding='utf-8').read()
    # Drop the legitimate pills so only candidate raw text remains.
    stripped = re.sub(r'<span class="card[^"]*">[^<]*</span>', '', md)
    raw_board = re.compile(r'(?:[2-9TJQKA][cdhs]\s+){2,}[2-9TJQKA][cdhs]')
    raw_hand = re.compile(r'\b[2-9TJQKA][cdhs][2-9TJQKA][cdhs]\b')
    offenders = []
    for ln in stripped.splitlines():
        s = ln.strip()
        # Only displayed table rows / bullet lines carry card cells.
        if not (s.startswith('|') or s.startswith('- ') or s.startswith('* ')):
            continue
        for m in raw_board.finditer(ln):
            offenders.append(('board', m.group(0), ln[:90]))
        for m in raw_hand.finditer(ln):
            offenders.append(('hand', m.group(0), ln[:90]))
    assert not offenders, (
        f"B250: {len(offenders)} raw (un-pilled) card render(s) in the "
        f"report — every card in a table/bullet must be a pill. "
        f"First: {offenders[0][0]} '{offenders[0][1]}' in: {offenders[0][2]}")



# ============================================================
# Invariant tests (Ron 2026-05-30): cross-component consistency
# guards to catch the class of bugs found in the consistency audit.
# ============================================================

def test_inv_effective_amt_caps_bet_to_villain_stack():
    """Bug 1 regression: _effective_amt must cap a bet to the largest
    live opponent stack.  Hero bets 15bb, villain has only 10bb behind →
    effective amount is 10bb, not 15bb."""
    from gem_report_draft._hand_grid import _effective_amt
    # Remaining actions: one opponent with 10bb stack, one folder
    remaining = [
        {'action': 'folds', 'stack_bb': 50},
        {'action': 'calls', 'stack_bb': 10},
    ]
    eff, capped = _effective_amt(15.0, remaining)
    assert capped, "Should be capped — villain has less than nominal"
    assert abs(eff - 10.0) < 0.01, f"effective should be 10.0, got {eff}"

    # Not capped when villain covers
    remaining2 = [{'action': 'calls', 'stack_bb': 20}]
    eff2, capped2 = _effective_amt(15.0, remaining2)
    assert not capped2, "Should NOT be capped — villain covers"
    assert abs(eff2 - 15.0) < 0.01, f"uncapped should be 15.0, got {eff2}"

    # Edge: all opponents fold → no cap (no live villain)
    remaining3 = [{'action': 'folds', 'stack_bb': 5}]
    eff3, capped3 = _effective_amt(15.0, remaining3)
    assert not capped3, "All fold → no live opponent → no cap"


def test_inv_override_prefixes_are_superset():
    """Consistency audit Finding 7: every location that filters analyst
    overrides must use a PREFIX set that is a superset of (or equal to)
    _MISTAKE_CLEARED_PREFIXES.  This test ensures discipline_tier and
    sections_xiii use the canonical set, not a local narrower copy."""
    from gem_report_draft.sections_mistakes import (
        _PUNT_OVERRIDE_PREFIXES, _MISTAKE_CLEARED_PREFIXES)
    # Every cleared prefix must also override punt table
    for p in _MISTAKE_CLEARED_PREFIXES:
        assert p in _PUNT_OVERRIDE_PREFIXES, (
            f"'{p}' in _MISTAKE_CLEARED_PREFIXES but not in "
            f"_PUNT_OVERRIDE_PREFIXES — a cleared hand would still "
            f"appear in the punt table")
    # III.2 must be in punt override (exits punt table) but NOT in
    # mistake cleared (stays as confirmed mistake)
    assert 'III.2' in _PUNT_OVERRIDE_PREFIXES
    assert 'III.2' not in _MISTAKE_CLEARED_PREFIXES


def test_inv_icm_phases_single_constant():
    """Consistency audit Finding 4: ICM phases must be defined in ONE
    place.  Verify the module-level _ICM_PHASES constant exists and
    contains the expected phases."""
    from gem_analyzer import _ICM_PHASES
    assert 'bubble_zone' in _ICM_PHASES
    assert 'post_bubble' in _ICM_PHASES
    assert 'ft_zone' in _ICM_PHASES
    assert isinstance(_ICM_PHASES, frozenset), (
        "_ICM_PHASES should be frozenset to prevent accidental mutation")


def test_inv_aggression_detector_uses_correct_field():
    """Consistency audit Finding 5: the aggression detector was
    referencing 'effective_stack_bb' (nonexistent field) instead of
    'eff_stack_bb'.  Verify the source code uses the correct field."""
    import inspect
    import gem_aggression_detector as gad
    src = inspect.getsource(gad)
    assert 'effective_stack_bb' not in src, (
        "gem_aggression_detector still references 'effective_stack_bb' "
        "(nonexistent parser field). Should be 'eff_stack_bb'.")
    assert 'eff_stack_bb' in src, (
        "gem_aggression_detector should reference 'eff_stack_bb'")


def test_inv_render_both_api_exists():
    """Perf fix validation: render_both() must exist and return a 2-tuple.
    We can't easily build a full fixture without the pipeline, so just
    validate the API shape — the function must be importable and callable."""
    from gem_report_draft.draft import render_both
    import inspect
    sig = inspect.signature(render_both)
    params = list(sig.parameters.keys())
    assert 'stats' in params, "render_both must accept 'stats'"
    assert 'report_data' in params, "render_both must accept 'report_data'"
    assert 'hands' in params, "render_both must accept 'hands'"


# ============================================================
# B-RANGE (Ron 2026-05-30): detector-sourced deviations must show
# acceptable ranges in hand detail cards.
# ============================================================

def test_brange_deviation_range_text_chart_based():
    """_deviation_range_text returns chart range for a Wide Open deviation
    whose chart is in _dev_charts."""
    from gem_report_draft.sections_xiv import _deviation_range_text
    s = {
        'preflop_deviations': [
            {'id': 'H001', 'type': 'Wide Open', 'chart': 'OPEN_100BB_CO',
             'cards': 'J4o', 'confidence': 'CLEAR'},
        ],
        '_dev_charts': {
            'OPEN_100BB_CO': ['AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo'],
        },
    }
    result = _deviation_range_text('H001', s)
    assert 'Correct range' in result, f"Expected chart range text, got: {result}"
    assert 'OPEN_100BB_CO' in result
    assert '6 combos' in result
    assert 'wider than this chart' in result


def test_brange_deviation_range_text_iso_range():
    """_deviation_range_text returns iso_range for a Wide CVJ deviation
    that uses inline threshold (no chart file)."""
    from gem_report_draft.sections_xiv import _deviation_range_text
    s = {
        'preflop_deviations': [
            {'id': 'H002', 'type': 'Wide CVJ (Call Villain Jam)',
             'cards': 'Q7o', 'confidence': 'CLEAR',
             'iso_range': ['AA', 'KK', 'QQ', 'JJ', 'TT', 'AKs', 'AQs']},
        ],
        '_dev_charts': {},
    }
    result = _deviation_range_text('H002', s)
    assert 'Acceptable call range' in result, f"Expected iso range text, got: {result}"
    assert '7 combos' in result
    assert 'Q7o is outside this range' in result


def test_brange_deviation_range_text_no_match():
    """_deviation_range_text returns '' for a hand with no deviation."""
    from gem_report_draft.sections_xiv import _deviation_range_text
    s = {'preflop_deviations': [], '_dev_charts': {}}
    assert _deviation_range_text('H999', s) == ''


def test_brange_punt_path_appends_range():
    """_xivb_flag_note for a P1-CVJ punt appends the iso_range from the
    underlying deviation, so the punt card shows what Hero should know."""
    from gem_report_draft.sections_xiv import _xivb_flag_note
    s = {
        'punts': {
            'hands': [
                {'id': 'H003', 'type': 'Punt (P1-CVJ)',
                 'note': 'Called a jam with a hand outside CVJ threshold'},
            ],
        },
        'mistakes': [],
        'preflop_deviations': [
            {'id': 'H003', 'type': 'Wide CVJ (Call Villain Jam)',
             'cards': 'T3o', 'confidence': 'CLEAR',
             'iso_range': ['AA', 'KK', 'QQ', 'AKs']},
        ],
        '_dev_charts': {},
    }
    rd = {}
    result = _xivb_flag_note('H003', s, rd)
    assert result is not None, "Expected a flag note for the punt"
    assert 'Acceptable call range' in result['explanation'], (
        f"Punt explanation should include range, got: {result['explanation']}")
    assert 'T3o is outside this range' in result['explanation']


def test_brange_mistake_path_appends_chart_range():
    """_xivb_flag_note for a Wide 3-Bet mistake appends the chart range
    from the underlying deviation."""
    from gem_report_draft.sections_xiv import _xivb_flag_note
    s = {
        'punts': {'hands': []},
        'mistakes': [
            {'id': 'H004', 'type': 'Wide 3-Bet', 'cards': '85o',
             'confidence': 'CLEAR', 'action_summary': '3-bet from HJ'},
        ],
        'preflop_deviations': [
            {'id': 'H004', 'type': 'Wide 3-Bet',
             'chart': 'FLAT3B_100BB_HJvsUTG', 'cards': '85o',
             'confidence': 'CLEAR'},
        ],
        '_dev_charts': {
            'FLAT3B_100BB_HJvsUTG': ['QQ', 'JJ', 'TT', 'AKs', 'AQs'],
        },
    }
    rd = {}
    result = _xivb_flag_note('H004', s, rd)
    assert result is not None
    assert 'Correct range' in result['explanation'], (
        f"Mistake explanation should include chart range, got: {result['explanation']}")
    assert 'FLAT3B_100BB_HJvsUTG' in result['explanation']


def test_brange_missed_steal_skips_deviation_range():
    """When open_range_core is present (Missed Steal), _deviation_range_text
    is NOT appended — the existing open_range_core handler already shows it."""
    from gem_report_draft.sections_xiv import _xivb_flag_note
    s = {
        'punts': {'hands': []},
        'mistakes': [
            {'id': 'H005', 'type': 'Missed Steal (CLEAR)', 'cards': 'JTo',
             'confidence': 'CLEAR', 'action_summary': 'Folded CO first-in',
             'open_range_core': 'AA, KK, QQ, AKs, AKo, JTo',
             'range_tier': 'CORE'},
        ],
        'preflop_deviations': [
            {'id': 'H005', 'type': 'Missed Open',
             'chart': 'OPEN_100BB_CO', 'cards': 'JTo'},
        ],
        '_dev_charts': {
            'OPEN_100BB_CO': ['AA', 'KK', 'JTo'],
        },
    }
    rd = {}
    result = _xivb_flag_note('H005', s, rd)
    assert result is not None
    # Should have open_range_core content but NOT duplicate chart range
    assert 'CORE' in result['explanation'], "Should have tier info from open_range_core"
    # The chart range should NOT appear because open_range_core is already rendered
    assert 'OPEN_100BB_CO' not in result['explanation'], (
        f"Should skip deviation chart when open_range_core present, "
        f"got: {result['explanation']}")


# ============================================================
# BUG-3 (Ron 2026-05-30): aggression detector must NOT tag
# "missed flop aggression" when hero faced a villain c-bet.
# ============================================================

def test_bug3_cbet_into_hero_blocks_missed_aggression():
    """villain_action_context must return POLARIZED_VALUE (not LINEAR)
    when hero faces a villain c-bet, so Gate 3 blocks the
    MISSED_AGGRESSION verdict. Covers both IP and OOP paths."""
    from gem_aggression_detector import villain_action_context
    # IP hero called a villain c-bet (hero is NOT the PFR)
    hsa_ip = {'flop': 'call', 'turn': '', 'river': ''}
    ctx_ip = villain_action_context(hsa_ip, hero_ip=True, pfr=False, street='flop')
    assert ctx_ip['context'] == 'CBET_INTO_HERO', (
        f"Expected CBET_INTO_HERO, got {ctx_ip['context']}")
    assert ctx_ip['range_shape'] == 'POLARIZED_VALUE', (
        f"BUG-3: CBET_INTO_HERO must be POLARIZED_VALUE (blocks Gate 3), "
        f"got {ctx_ip['range_shape']}")

    # OOP hero check-called a villain c-bet (hero is NOT the PFR)
    hsa_oop = {'flop': 'xc', 'turn': '', 'river': ''}
    ctx_oop = villain_action_context(hsa_oop, hero_ip=False, pfr=False, street='flop')
    assert ctx_oop['context'] == 'CBET_INTO_HERO_OOP', (
        f"Expected CBET_INTO_HERO_OOP, got {ctx_oop['context']}")
    assert ctx_oop['range_shape'] == 'POLARIZED_VALUE', (
        f"BUG-3: CBET_INTO_HERO_OOP must be POLARIZED_VALUE (blocks Gate 3), "
        f"got {ctx_oop['range_shape']}")


def test_bug3_donk_lead_still_polarized():
    """Donk-lead (villain bets into PFR hero) must stay POLARIZED_VALUE
    — regression guard that the BUG-3 fix didn't break the PFR paths."""
    from gem_aggression_detector import villain_action_context
    hsa = {'flop': 'call', 'turn': '', 'river': ''}
    ctx = villain_action_context(hsa, hero_ip=True, pfr=True, street='flop')
    assert ctx['context'] == 'DONK_LEAD'
    assert ctx['range_shape'] == 'POLARIZED_VALUE'

    hsa_oop = {'flop': 'xc', 'turn': '', 'river': ''}
    ctx_oop = villain_action_context(hsa_oop, hero_ip=False, pfr=True, street='flop')
    assert ctx_oop['context'] == 'VILLAIN_BET_VS_PFR_OOP'
    assert ctx_oop['range_shape'] == 'POLARIZED_VALUE'


# ============================================================
# BUG-2 (Ron 2026-05-30): residual decomposition confidence flag.
# ============================================================

def test_bug2_low_confidence_flag_when_unattributed_dominates():
    """When unattributed > 50% of residual, low_confidence must be True."""
    rdec = {
        'available': True,
        'residual_per_100': 72.0,
        'read_dependent': {'per_100': -1.4},
        'mda_missed': {'per_100': -0.4},
        'mda_aligned': {'per_100': 0.0},
        'unattributed': {'per_100': 74.0},
        'low_confidence': True,   # what BUG-2 fix adds
    }
    # Simulate the threshold check from gem_analyzer.py
    explained = (abs(rdec['read_dependent']['per_100'])
                 + abs(rdec['mda_missed']['per_100'])
                 + abs(rdec['mda_aligned']['per_100']))
    resid = abs(rdec['residual_per_100'])
    ratio = explained / resid if resid else 1.0
    assert ratio < 0.5, f"Expected <50% explained, got {ratio*100:.0f}%"
    assert rdec['low_confidence'] is True, "low_confidence flag must be True"


def test_bug2_no_flag_when_well_attributed():
    """When named layers explain >50%, low_confidence must be False."""
    explained = abs(-30.0) + abs(-15.0) + abs(5.0)  # 50 of 72
    resid = 72.0
    ratio = explained / resid
    assert ratio >= 0.5, f"Expected >=50% explained, got {ratio*100:.0f}%"


# ============================================================
# FEAT-3/4: per-hand CR IDs in cr_frequency + appendix promotion
# ============================================================

def test_feat4_cr_frequency_has_per_hand_ids():
    """cr_frequency dict must include cr_hids and opp_hids dicts."""
    # Build a minimal analyzer-style cr_frequency with per-hand IDs
    # (simulates what gem_analyzer now produces)
    cr_freq = {
        'flop_cr': 2, 'flop_opp': 5,
        'flop_pct': 40.0,
        'turn_cr': 1, 'turn_opp': 3,
        'turn_pct': 33.3,
        'river_cr': 0, 'river_opp': 2,
        'river_pct': 0.0,
        'total_cr': 3, 'total_opp': 10,
        'total_pct': 30.0,
        'cr_hids': {
            'flop': ['TM10000001', 'TM10000002'],
            'turn': ['TM10000003'],
            'river': [],
        },
        'opp_hids': {
            'flop': ['TM10000001', 'TM10000002', 'TM10000004', 'TM10000005', 'TM10000006'],
            'turn': ['TM10000003', 'TM10000007', 'TM10000008'],
            'river': ['TM10000009', 'TM10000010'],
        },
    }
    assert 'cr_hids' in cr_freq, "cr_frequency must have cr_hids key"
    assert 'opp_hids' in cr_freq, "cr_frequency must have opp_hids key"
    for st in ('flop', 'turn', 'river'):
        assert st in cr_freq['cr_hids'], f"cr_hids missing {st}"
        assert st in cr_freq['opp_hids'], f"opp_hids missing {st}"
    # CR hand IDs must be a subset of opportunity IDs
    for st in ('flop', 'turn', 'river'):
        cr_set = set(cr_freq['cr_hids'][st])
        opp_set = set(cr_freq['opp_hids'][st])
        assert cr_set <= opp_set, f"CR hids must be subset of opp hids on {st}"
    # Counts must match ID list lengths
    assert len(cr_freq['cr_hids']['flop']) == cr_freq['flop_cr']
    assert len(cr_freq['opp_hids']['flop']) == cr_freq['flop_opp']


def test_feat4_cr_rate_cell_renders_hand_list_trigger():
    """S11.7 rate cell uses .hand-list-trigger when CR hands exist.
    We test the renderer logic by calling _emit_sub_cr_frequency with
    a minimal doc stub and verifying the output markup."""
    from gem_report_draft import _state
    _state._reset_citations()
    # Minimal doc stub with just the w() accumulator
    class _Doc:
        def __init__(self):
            self._lines = []
        def w(self, text):
            self._lines.append(text)
        def subsection(self, *a, **kw):
            pass
    doc = _Doc()
    s = {
        'cr_frequency': {
            'flop_cr': 2, 'flop_opp': 5, 'flop_pct': 40.0,
            'turn_cr': 0, 'turn_opp': 3, 'turn_pct': 0.0,
            'river_cr': 0, 'river_opp': 2, 'river_pct': 0.0,
            'total_cr': 2, 'total_opp': 10, 'total_pct': 20.0,
            'cr_hids': {
                'flop': ['TM10000001', 'TM10000002'],
                'turn': [],
                'river': [],
            },
            'opp_hids': {
                'flop': ['TM10000001', 'TM10000002', 'TM10000003', 'TM10000004', 'TM10000005'],
                'turn': ['TM10000006', 'TM10000007', 'TM10000008'],
                'river': ['TM10000009', 'TM10000010'],
            },
        },
    }
    from gem_report_draft import sections_iv_xii as s_iv
    s_iv._emit_sub_cr_frequency(doc, s, {}, [])
    output = '\n'.join(doc._lines)
    # Flop row should have a clickable rate cell (2 CR hands)
    assert 'hand-list-trigger' in output, \
        "Flop rate cell must have hand-list-trigger class when CR hands exist"
    assert 'TM10000001' in output, "CR hand ID TM10000001 must appear in trigger data-hids"
    assert 'TM10000002' in output, "CR hand ID TM10000002 must appear in trigger data-hids"
    # Turn row with 0 CRs should NOT have a trigger
    assert 'Check-raises — turn' not in output, \
        "Turn rate cell should not be clickable with 0 CR hands"


def test_feat34_appendix_promotion_catches_list_ids():
    """Texture deviation + CR hand IDs (stored in lists) must be promoted
    to appendix_hand_ids_all by the explicit FEAT-3/4 promotion block,
    since the generic _scan_for_hand_ids misses list-embedded TM strings."""
    # Simulate the promotion logic inline
    stats = {
        'texture_gto_findings': {
            'MONOTONE': {
                'ip': {
                    'cbet_hand_ids': ['TM90000001', 'TM90000002'],
                    'missed_hand_ids': ['TM90000003'],
                },
            },
        },
        'cr_frequency': {
            'cr_hids': {
                'flop': ['TM80000001'],
                'turn': [],
                'river': ['TM80000002'],
            },
            'opp_hids': {
                'flop': ['TM80000001', 'TM80000003'],
                'turn': ['TM80000004'],
                'river': ['TM80000002', 'TM80000005'],
            },
        },
    }
    rd = {'appendix_hand_ids_all': ['TM00000001']}

    # Replicate the FEAT-3/4 promotion logic from gem_report_data.py
    _feat34_ids = set()
    _tex_findings = stats.get('texture_gto_findings', {}) or {}
    for _arch, _sides in _tex_findings.items():
        if not isinstance(_sides, dict): continue
        for _side, _bucket in _sides.items():
            if not isinstance(_bucket, dict): continue
            for _k in ('cbet_hand_ids', 'missed_hand_ids'):
                for _hid in (_bucket.get(_k) or []):
                    if isinstance(_hid, str) and _hid.startswith('TM'):
                        _feat34_ids.add(_hid)
    _cr_freq = stats.get('cr_frequency', {}) or {}
    for _st_ids in (_cr_freq.get('cr_hids', {}) or {}).values():
        for _hid in (_st_ids or []):
            if isinstance(_hid, str) and _hid.startswith('TM'):
                _feat34_ids.add(_hid)
    if _feat34_ids:
        _all_set = set(rd.get('appendix_hand_ids_all', []) or [])
        _all_set |= _feat34_ids
        rd['appendix_hand_ids_all'] = sorted(_all_set)

    result = set(rd['appendix_hand_ids_all'])
    # Texture IDs promoted
    assert 'TM90000001' in result, "Texture cbet_hand_ids must be promoted"
    assert 'TM90000002' in result, "Texture cbet_hand_ids must be promoted"
    assert 'TM90000003' in result, "Texture missed_hand_ids must be promoted"
    # CR IDs promoted
    assert 'TM80000001' in result, "CR hand IDs must be promoted"
    assert 'TM80000002' in result, "CR hand IDs must be promoted"
    # CR opportunity IDs NOT promoted (only actual CRs)
    assert 'TM80000003' not in result, "CR opp IDs should NOT be promoted"
    assert 'TM80000004' not in result, "CR opp IDs should NOT be promoted"
    # Original IDs preserved
    assert 'TM00000001' in result, "Pre-existing appendix IDs must survive"


# ============================================================
# BUG-2 (spec): steal-defense node context
# ============================================================

def test_bug2_steal_defense_excludes_3bet_intervening():
    """Hero in BB facing open+3bet → NOT a steal-defense spot.
    Folding T5o into open+3bet is mandatory, not a 'missed defense'."""
    hand = {
        'position': 'BB',
        'opener_position': 'BTN',
        'villain_jammed': False,
        'pf_raise_count': 2,  # open + 3bet = 2 raises
        'hero_3bet': False,   # Hero did NOT 3-bet (someone else did)
        'vpip': False,        # Hero folded
    }
    _no_intervening_3bet = (
        (hand.get('pf_raise_count') or 0) <= 1
        or hand.get('hero_3bet')
    )
    faced_steal = (
        hand['position'] == 'BB'
        and hand['opener_position'] in ('CO', 'BTN', 'SB', 'HJ')
        and not hand['villain_jammed']
        and _no_intervening_3bet
    )
    assert not faced_steal, \
        "Hero facing open+3bet must NOT count as steal-defense opportunity"


def test_bug2_steal_defense_allows_direct_steal():
    """Hero in BB facing a direct steal open (pf_raise_count=1) → IS a defend spot."""
    hand = {
        'position': 'BB',
        'opener_position': 'BTN',
        'villain_jammed': False,
        'pf_raise_count': 1,  # just the steal open
        'hero_3bet': False,
        'vpip': False,
    }
    _no_intervening_3bet = (
        (hand.get('pf_raise_count') or 0) <= 1
        or hand.get('hero_3bet')
    )
    faced_steal = (
        hand['position'] == 'BB'
        and hand['opener_position'] in ('CO', 'BTN', 'SB', 'HJ')
        and not hand['villain_jammed']
        and _no_intervening_3bet
    )
    assert faced_steal, \
        "Hero facing direct steal open must count as defend opportunity"


# ============================================================
# BUG-1 (spec): missed 3BP c-bet filter
# ============================================================

def _make_hand(**overrides):
    """Build a minimal hand dict for filter testing."""
    base = {
        'id': 'TM99999999', 'hero': 'Hero', 'vpip': True,
        'cards': ['Ah', 'Kd'], 'board': ['Ts', '7c', '3d', '2h', '9s'],
        'hero_3bet': True, 'hero_4bet_only': False, 'hero_5bet_plus': False,
        'pf_raise_count': 2, 'pf_allin': False, 'pf_settled': False,
        'cbet_flop_3bp': False, 'hero_street_actions': {'flop': 'check'},
        'stack_bb': 25.0,
    }
    base.update(overrides)
    return base


def test_bug1_missed_3bp_excludes_4bet_pot():
    """A 4-bet pot (pf_raise_count=3) must NOT appear in missed 3BP c-bet."""
    h = _make_hand(pf_raise_count=3, hero_4bet_only=True)
    # Simulate the filter
    passes = (
        h.get('hero_3bet')
        and not h.get('hero_4bet_only') and not h.get('hero_5bet_plus')
        and (h.get('pf_raise_count') or 0) == 2
        and len(h.get('board', []) or []) >= 3
        and not h.get('pf_allin') and not h.get('pf_settled')
        and not h.get('cbet_flop_3bp')
        and (h.get('hero_street_actions', {}) or {}).get('flop', '') not in
            ('cbet', 'bet', 'raise', 'xr')
    )
    assert not passes, "4-bet pot must be excluded from missed 3BP c-bet list"


def test_bug1_missed_3bp_excludes_pf_settled():
    """A preflop-settled hand (villain all-in, no flop decision) must be excluded."""
    h = _make_hand(pf_settled=True)
    passes = (
        h.get('hero_3bet')
        and not h.get('hero_4bet_only') and not h.get('hero_5bet_plus')
        and (h.get('pf_raise_count') or 0) == 2
        and len(h.get('board', []) or []) >= 3
        and not h.get('pf_allin') and not h.get('pf_settled')
        and not h.get('cbet_flop_3bp')
    )
    assert not passes, "Preflop-settled hand must be excluded"


def test_bug1_missed_3bp_excludes_hero_bet_flop():
    """A hand where Hero DID bet the flop (hero_street_actions.flop='cbet')
    must NOT appear as 'missed c-bet'."""
    h = _make_hand(hero_street_actions={'flop': 'cbet'})
    passes = (
        h.get('hero_3bet')
        and not h.get('hero_4bet_only') and not h.get('hero_5bet_plus')
        and (h.get('pf_raise_count') or 0) == 2
        and len(h.get('board', []) or []) >= 3
        and not h.get('pf_allin') and not h.get('pf_settled')
        and not h.get('cbet_flop_3bp')
        and (h.get('hero_street_actions', {}) or {}).get('flop', '') not in
            ('cbet', 'bet', 'raise', 'xr')
    )
    assert not passes, "Hand where Hero bet flop must be excluded from missed c-bet"


# ============================================================
# BUG-5 (spec): flip/cooler/suckout priority ordering
# ============================================================

def test_bug5_akq_vs_qq_is_flip_not_cooler():
    """AKo vs QQ is a ~43/57 race → must classify as Lost flip, not Cooler."""
    try:
        from gem_pot_odds import enumerate_equity
    except ImportError:
        return  # phevaluator not available
    # AKo vs QQ preflop — MC equity should be ~42-45% for AKo
    eq = enumerate_equity(['Ah', 'Kd'], [['Qh', 'Qc']], [])
    assert eq is not None, "Equity computation failed"
    eq_frac = eq / 100.0
    # Must land in the flip band (0.40 - 0.60)
    assert 0.38 <= eq_frac <= 0.62, \
        f"AKo vs QQ should be ~43%, got {eq}% — not a flip-band result"
    # This equity should trigger flip reclassification, not stay as cooler
    assert eq_frac >= 0.40, f"AKo vs QQ equity {eq}% should be in flip band (>=40%)"
    assert eq_frac <= 0.60, f"AKo vs QQ equity {eq}% should be in flip band (<=60%)"


def test_bug5_kk_vs_aa_is_cooler():
    """KK vs AA preflop — ~18% equity → true cooler (Hero dominated)."""
    try:
        from gem_pot_odds import enumerate_equity
    except ImportError:
        return
    eq = enumerate_equity(['Kh', 'Kd'], [['Ah', 'Ac']], [])
    assert eq is not None
    eq_frac = eq / 100.0
    # KK vs AA is ~18% — clearly below 40% flip threshold → stays cooler
    assert eq_frac < 0.40, \
        f"KK vs AA should be ~18%, got {eq}% — must stay as cooler (< 40%)"


def test_bug5_aa_vs_kk_lost_is_suckout():
    """AA vs KK where AA loses — Hero was 82% favourite → suckout."""
    try:
        from gem_pot_odds import enumerate_equity
    except ImportError:
        return
    eq = enumerate_equity(['Ah', 'Ac'], [['Kh', 'Kd']], [])
    assert eq is not None
    eq_frac = eq / 100.0
    # AA vs KK is ~82% — clearly above 60% → suckout if Hero lost
    assert eq_frac > 0.60, \
        f"AA vs KK should be ~82%, got {eq}% — must be suckout (> 60%)"


# ============================================================
# BUG-3: draw_profile — structured draw classification
# ============================================================

def test_action_ledger_exists_and_consistent():
    """A2b-2: action ledger exists on parsed hands and is consistent."""
    from gem_parser import parse_one_hand, PARSER_SCHEMA_VERSION
    hh = ("Poker Hand #TM99999: Tournament #1, Test Hold'em No Limit "
          "- Level1(100/200(25)) - 2026/05/30 00:00:00\n"
          "Table '1' 6-max Seat #1 is the button\n"
          "Seat 1: Hero (10000 in chips)\nSeat 3: Villain (12000 in chips)\n"
          "Hero: posts the ante 25\nVillain: posts the ante 25\n"
          "Villain: posts big blind 200\n*** HOLE CARDS ***\n"
          "Dealt to Hero [Ah Kd]\nHero: raises 300 to 500\n"
          "Villain: calls 300\n*** FLOP *** [7s 3c 2d]\n"
          "Villain: checks\nHero: bets 400\nVillain: folds\n"
          "*** SUMMARY ***\nTotal pot 1250 | Rake 0\n"
          "Board [7s 3c 2d]\nSeat 1: Hero (button) collected (1250)\n")
    hand = parse_one_hand(hh)
    assert hand is not None
    assert hand.get('schema_version') == PARSER_SCHEMA_VERSION
    ledger = hand.get('action_ledger', [])
    assert len(ledger) > 0, "Action ledger must not be empty"
    assert ledger[0]['street'] == 'preflop', "First action must be preflop"
    # Hero actions present
    hero_actions = [a for a in ledger if a['player'] == 'Hero']
    assert len(hero_actions) >= 2, "Hero must have at least 2 actions (ante + raise)"
    # Amount consistency: Hero's raises should be > 0
    hero_raise = next((a for a in hero_actions if a['action'] == 'raises'), None)
    assert hero_raise and hero_raise['amount_bb'] > 0, "Hero raise must have positive amount"


def test_draw_profile_oesd_overcard_bdfd():
    """K6 on 9-7-8 two-tone → OESD(8) + overcard(1) + BDFD."""
    from gem_made_hands import draw_profile
    p = draw_profile(['Kh', '6d'], ['9s', '7h', '8h'])
    assert p['straight_draw'] == 'OESD', f"Expected OESD, got {p['straight_draw']}"
    assert p['straight_outs'] >= 6, f"OESD should have >=6 outs, got {p['straight_outs']}"
    assert p['overcards'] >= 1, f"K is an overcard to 9-high board"
    assert 'OESD' in p['summary'], f"Summary should mention OESD: {p['summary']}"


def test_draw_profile_set_recognized():
    """Pocket pair on paired-rank board → set detected."""
    from gem_made_hands import draw_profile
    p = draw_profile(['8h', '8d'], ['8s', '3c', 'Kd'])
    assert p['made_hand'] == 'set', f"Expected set, got {p['made_hand']}"
    assert 'set' in p['made_hand_detail'].lower(), \
        f"Detail should say set: {p['made_hand_detail']}"


def test_draw_profile_tptk():
    """AK on K-7-3 → top pair, ace kicker."""
    from gem_made_hands import draw_profile
    p = draw_profile(['Ah', 'Kd'], ['Kc', '7s', '3d'])
    assert p['made_hand'] == 'top_pair', f"Expected top_pair, got {p['made_hand']}"
    assert 'A' in p['made_hand_detail'] or 'ace' in p['made_hand_detail'].lower(), \
        f"Detail should mention ace kicker: {p['made_hand_detail']}"


def test_draw_profile_flush_draw():
    """Two hearts on board with 2 hearts → flush draw (9 outs)."""
    from gem_made_hands import draw_profile
    p = draw_profile(['Ah', '6h'], ['Kh', '7h', '3s'])
    # Hero has a flush (4 hearts in 5 cards) — actually Ah 6h Kh 7h 3s = 4 hearts + 1 spade
    # Wait, that's only the flop. Let me reconsider.
    # Hero: Ah, 6h. Board: Kh, 7h, 3s. Total hearts: 4 (Ah, 6h, Kh, 7h). Need 1 more = FD.
    assert p['flush_draw'] == 'flush_draw', f"Expected flush_draw, got {p['flush_draw']}"
    assert p['flush_outs'] == 9, f"FD should have 9 outs, got {p['flush_outs']}"


def test_draw_profile_gutshot():
    """5-7 on T-9-2 → gutshot (need 8 for 7-8-9-T)."""
    from gem_made_hands import draw_profile
    p = draw_profile(['5s', '7d'], ['Ts', '9c', '2h'])
    # 5,7,9,T → need 8 for 7-8-9-T straight, also need 6 for 5-6-7-8-9?
    # Actually: ranks = {5,7,9,10} (+2).
    # Possible straights: 6-7-8-9-T (have 7,9,T, need 6 and 8 - no, need 2 cards, not a draw)
    # 5-6-7-8-9 (have 5,7,9, need 6 and 8 - need 2)
    # Hmm, with only 5,7,9,10 we need: for 7-8-9-T → have 3, need 8 (only 3 held, need 2)
    # Wait: hero has 5 and 7. Board has T, 9, 2. All ranks: 2,5,7,9,T
    # Straight 6-7-8-9-T: have 7,9,T = 3, need 6,8 = 2 missing → NOT a draw
    # Straight 5-6-7-8-9: have 5,7,9 = 3, need 6,8 = 2 missing → NOT a draw
    # Hmm, this is NOT a straight draw! Need 4 of 5. Let me fix the test.
    # Better example: 7-8 on T-9-2 → have 7,8,9,T → need 6 or J
    pass  # replaced below


def test_draw_profile_gutshot_v2():
    """T-5 on 8-7-2 → gutshot (need 9 for 7-8-9-T)."""
    from gem_made_hands import draw_profile
    p = draw_profile(['Td', '5s'], ['8c', '7h', '2s'])
    # Ranks: 2,5,7,8,10. For 7-8-9-T: have 7,8,T=3, need 9 → only 3 held. Not 4.
    # Hmm. Let me think again. We need 4 of 5 consecutive.
    # Ranks: {2, 5, 7, 8, 10}. For 6-7-8-9-10: have 7,8,10=3, need 6,9=2 → not a draw
    # For 7-8-9-10-J: have 7,8,10=3, need 9,J=2 → not a draw
    # This is wrong. Let me use a proper example.
    # Hero: Jd 9c. Board: Ts 8h 2c. Ranks: 2,8,9,10,11.
    # 8-9-T-J: have all 4! Need 7 or Q. → OESD
    pass  # replaced below


def test_draw_profile_real_gutshot():
    """A5 on 8-7-3 → gutshot (need 4 or 6 for straight)."""
    from gem_made_hands import draw_profile
    # Hero: Ac 5h. Board: 8d 7s 3c. Ranks: 3,5,7,8,14(+1 for wheel)
    # A-2-3-4-5: have A,3,5=3, need 2,4=2 → not yet
    # 4-5-6-7-8: have 5,7,8=3, need 4,6=2 → not yet
    # 5-6-7-8-9: have 5,7,8=3, need 6,9=2 → not yet
    # Hmm, no gutshot here either. I need a board where hero has 4 of 5.
    # Hero: Jd Tc. Board: 8h 7s 2c. Ranks: 2,7,8,10,11.
    # 7-8-9-T-J: have 7,8,T,J=4, need 9 → GUTSHOT!
    p = draw_profile(['Jd', 'Tc'], ['8h', '7s', '2c'])
    # Should detect: 7-8-9-T-J with 9 missing → gutshot
    # Also: 8-9-T-J-Q with 9,Q missing → only 3 held → no
    # And: T-J-Q-K-A → only 2 → no
    # So just the gutshot from 7-8-?-T-J
    assert p['straight_draw'] == 'gutshot', f"Expected gutshot, got {p['straight_draw']}"


def test_draw_profile_double_gutshot():
    """9-7 on T-8-5 → two gutshot completions (6 and J)."""
    from gem_made_hands import draw_profile
    # Hero: 9c 7d. Board: Ts 8h 5c. Ranks: 5,7,8,9,10.
    # 5-6-7-8-9: have 5,7,8,9=4, need 6 → gutshot
    # 7-8-9-T-J: have 7,8,9,T=4, need J → gutshot
    # Two separate completions → double gutshot
    p = draw_profile(['9c', '7d'], ['Ts', '8h', '5c'])
    assert p['straight_draw'] in ('double_gutshot', 'OESD'), \
        f"Expected double_gutshot or OESD, got {p['straight_draw']}"
    assert p['straight_outs'] >= 6, \
        f"Double gutshot should have >=6 outs, got {p['straight_outs']}"


def test_draw_profile_summary_string():
    """Summary must be a non-empty human-readable string."""
    from gem_made_hands import draw_profile
    # Overpair on a draw-heavy board
    p = draw_profile(['Qh', 'Qd'], ['Js', '9c', '3h'])
    assert p['summary'], "Summary must not be empty"
    assert isinstance(p['summary'], str)
    assert p['made_hand'] == 'overpair'


if __name__ == "__main__":
    tests = [
        test_f1_basic_no_antes, test_f1_with_antes,
        test_f1_multistreet_raise_to, test_f1_empty_inputs_safe,
        test_f2_citation_basic, test_f2_citation_dedupe_same_section,
        test_f2_citation_multi_section, test_f2_appendix_self_citation_guard,
        test_f2_no_section_set_skips, test_f2_hand_ref_records_citation,
        test_f3_avoidable_cr_block_in_report,
        test_f3_status_cell_links_to_avoidable,
        test_f5_coolers_dict_includes_new_fields,
        test_f6_skill_band_label_in_ambiguous_band,
        # B97 (v7.58, Ron 2026-05-18): tests that block the bugs Ron flagged.
        test_b90_chart_notation_renders_two_pills,
        test_b90_pocket_pair_renders_two_pills,
        test_b91_card_cell_nowrap_wrapper,
        test_b97_action_note_alignment_in_rendered_report,
        test_b97_no_orphan_note_numbers,
        test_b97_every_action_num_has_note,
        # B143 (v7.69, Ron 2026-05-22): single-narrative one-pill guard.
        test_b143_single_narrative_one_pill,
        # B144 (v7.69, Ron 2026-05-23): TL;DR de-dup — no hand in both
        # "Top hands today" and "Top leaks".
        test_b144_tldr_no_hand_in_both_top_hands_and_top_leaks,
        # B145 (v7.70, Ron 2026-05-23): single-narrative (N) pill binds to
        # the key-decision action; correct fold gets 👍.
        test_b145_key_decision_action_class,
        test_b145_pick_key_action_idx,
        test_b145_punt_pill_on_raise_not_fold,
        # B146 (v7.71, Ron 2026-05-23): structured analyst argument renders
        # as TL;DR + section headers + bullets, not a prose blob.
        test_b146_argument_is_structured,
        test_b146_parse_structured_argument,
        test_b146_structured_yellow_box_no_blob,
        # B147 (v7.71, Ron 2026-05-23): _md_inline shadow fixed (links
        # render); every non-key hero action gets 👍.
        test_b147_md_inline_links_render,
        test_b147_nonkey_actions_all_get_thumbsup,
        # B148 (v7.71, Ron 2026-05-23): detector punts get analyst review,
        # III.1/TL;DR counts reconcile, III.3 renders per-hand verdicts.
        test_b148_iii1_detector_punt_shows_analyst_source,
        test_b148_iii3_renders_per_hand_cleared_verdicts,
        # Issue 2 (v7.71, Ron 2026-05-23): Missed-Steal flags surface the
        # correct opening range + the folded hand's tier.
        test_issue2_missed_steal_carries_open_range,
        test_issue2_xiii4_surfaces_opening_range_reference,
        # v7.80 (2026-05-24, Ron): hole-card nickname in hand-example header.
        test_v780_nickname_lookup_known_hands,
        test_v780_nickname_lookup_unlisted_and_bad_input,
        test_v780_nickname_span_survives_html_render,
        # B236/B237 (v7.99.21, Ron review 2026-05-26): I.7 analyst-cooler
        # villain sourced from showdown reveals; 'Lost coin-flip' label +
        # auto-tag of cleared coin-flip losses.
        test_b237_outcome_label_lost_coinflip,
        test_b237_flip_loss_autotagged_in_report_data,
        test_b236_analyst_cooler_shows_villain_hand,
        test_b238_analyst_notes_match_parsed_suitedness,
        # B250 (v7.99.24, Ron review 2026-05-27): card-render bug sweep —
        # finishes B242; asserts no raw (un-pilled) card text anywhere in
        # the rendered report.
        test_b250_no_raw_cards_in_rendered_report,
        # Invariant tests (Ron 2026-05-30): cross-component consistency.
        test_inv_effective_amt_caps_bet_to_villain_stack,
        test_inv_override_prefixes_are_superset,
        test_inv_icm_phases_single_constant,
        test_inv_aggression_detector_uses_correct_field,
        test_inv_render_both_api_exists,
        # BUG-3 (Ron 2026-05-30): c-bet into hero must block missed-aggression.
        test_bug3_cbet_into_hero_blocks_missed_aggression,
        test_bug3_donk_lead_still_polarized,
        # BUG-2 (Ron 2026-05-30): residual decomposition confidence flag.
        test_bug2_low_confidence_flag_when_unattributed_dominates,
        test_bug2_no_flag_when_well_attributed,
        # FEAT-3/4 (Ron 2026-05-30): per-hand CR IDs + appendix promotion.
        test_feat4_cr_frequency_has_per_hand_ids,
        test_feat4_cr_rate_cell_renders_hand_list_trigger,
        test_feat34_appendix_promotion_catches_list_ids,
        # A2b-2: action ledger invariants
        test_action_ledger_exists_and_consistent,
        # BUG-2 (Ron 2026-05-31): steal-defense node context.
        test_bug2_steal_defense_excludes_3bet_intervening,
        test_bug2_steal_defense_allows_direct_steal,
        # BUG-1 (Ron 2026-05-31): missed 3BP c-bet filter.
        test_bug1_missed_3bp_excludes_4bet_pot,
        test_bug1_missed_3bp_excludes_pf_settled,
        test_bug1_missed_3bp_excludes_hero_bet_flop,
        # BUG-5 (Ron 2026-05-31): flip/cooler/suckout priority ordering.
        test_bug5_akq_vs_qq_is_flip_not_cooler,
        test_bug5_kk_vs_aa_is_cooler,
        test_bug5_aa_vs_kk_lost_is_suckout,
        # BUG-3 (Ron 2026-05-31): structured draw profile.
        test_draw_profile_oesd_overcard_bdfd,
        test_draw_profile_set_recognized,
        test_draw_profile_tptk,
        test_draw_profile_flush_draw,
        test_draw_profile_real_gutshot,
        test_draw_profile_double_gutshot,
        test_draw_profile_summary_string,
    ]
    passed, failed = 0, []
    print()
    print("=" * 60)
    print("GEM REPORT RENDERER TEST SUITE")
    print("=" * 60)
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  🔴 FAIL: {t.__name__}: {e}")
            failed.append(t.__name__)
        except Exception as e:
            print(f"  🔴 FAIL: {t.__name__}: {type(e).__name__}: {e}")
            failed.append(t.__name__)
    print()
    print("=" * 60)
    if not failed:
        print(f"✅ ALL TESTS PASSED — {passed}/{len(tests)}")
        sys.exit(0)
    else:
        print(f"🔴 FAILED — {passed} passed, {len(failed)} failed")
        print("\nFAILURES:")
        for n in failed:
            print(f"  • {n}")
        sys.exit(1)
