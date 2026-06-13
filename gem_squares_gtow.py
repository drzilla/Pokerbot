#!/usr/bin/env python3
"""
gem_squares_gtow.py — v7.31 (2026-05-05)

Bridge between Squares analysis and GTO Wizard study workflow.
Produces a Session-18-template study setup per top actionable square:
  - Decoded scenario (positions / depth / pot / ICM phase)
  - GTOW solver setup parameters
  - Specific tactical questions (NOT generic "line check")
  - 3 representative sample hands per square
  - PER-SQUARE GTOW HH FILES — 20-25 hands matching the square shape, ready
    for GTOW HH-import / replay study (v7.31 addition).

Filters out structural-fold squares (BB/SB folds = blind tax, not studyable).

USAGE:
  python3 gem_squares_gtow.py \\
    --squares gem_squares.json \\
    --hands gem_hands_lean.json \\
    --hh-index hand_index.json \\
    --output GTOW_Study_Setup.md \\
    --hh-out-dir gtow_hh/

If --hh-index is provided AND --hh-out-dir is provided, per-square HH files
will be written to <hh-out-dir>/<square_id>.txt for GTOW import.
"""
import argparse
import json
import sys
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

# Import square classification logic from gem_squares
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gem_squares import assign_preflop_square, assign_postflop_square


def is_actionable_square(sid):
    """A square is actionable if Hero made a decision Hero can study.
    Excludes: fold, walked, other (these are baseline structural squares).
    """
    if sid.startswith('PostF_'):
        return True
    parts = sid.split('_')
    if len(parts) < 4:
        return False
    node = '_'.join(parts[3:])
    return node not in ('fold', 'walked', 'other')


def decode_pf_square(sid):
    """PF_<pos>_<bucket>_<node> → dict of components."""
    parts = sid.split('_')
    return {'kind': 'preflop', 'pos': parts[1], 'stack_bucket': parts[2],
            'node': '_'.join(parts[3:])}


def decode_postf_square(sid):
    """PostF_<IP|OOP>_<pot>_<spr>_<phase> → dict of components."""
    parts = sid.split('_')
    return {'kind': 'postflop', 'pos_class': parts[1], 'pot_type': parts[2],
            'spr_bucket': parts[3], 'icm_phase': '_'.join(parts[4:])}


def stack_bucket_to_solver_depth(bucket):
    """Map stack bucket to a representative GTOW depth."""
    return {'<12': 10, '12-25': 20, '25-40': 30, '40-60': 50, '60+': 100}.get(bucket, 100)


# ============================================================
# Question templates per scenario shape
# ============================================================

def build_questions_pf(decoded, hands):
    """Generate specific tactical questions for a preflop square."""
    pos = decoded['pos']
    bucket = decoded['stack_bucket']
    node = decoded['node']
    depth = stack_bucket_to_solver_depth(bucket)

    if node == 'cold_call':
        opener_dist = Counter(h.get('opener_position') for h in hands if h.get('opener_position'))
        top_openers = ', '.join(p for p, _ in opener_dist.most_common(3))
        if pos == 'SB':
            return [
                f"At {depth}bb effective from SB, is cold-calling EVER better than 3-bet-or-fold? "
                f"Most modern theory says no — verify by solving SB defense vs {top_openers} opens at {depth}bb.",
                f"For the hands we DID cold-call (sample shows A7s, A6s, 22), what's the per-hand EV gap "
                f"between flat and 3-bet at {depth}bb? Are these +EV flats or chip leaks?",
                f"When we cold-call SB and BB squeezes, what's our defend frequency target? "
                f"Are we folding too often to BB squeezes given pot odds and dead money?"
            ]
        elif pos == 'BB':
            return [
                f"At {depth}bb effective in BB facing {top_openers} opens, what's the 3-bet bluff vs flat split? "
                f"v5 ranges suggest specific 3-bet bluff freq; verify postflop EV for borderline flats.",
                f"For the hands we cold-called and lost on (sample: J9s, KQs), was the leak preflop "
                f"(should have been 3-bet or fold) or postflop (played the runout poorly)?",
                f"At SPR ~2-3 postflop, what's our check-call vs check-raise mix on flops we connect? "
                f"Pipeline shows Caller IP Agg is 18.5% (target 30-40%) — same leak applies OOP in BB."
            ]
    elif node == 'RFI':
        if pos == 'MP':
            return [
                f"At {depth}bb, is our MP open frequency aligned with OPEN_100BB_MP (target ~18.9%)? "
                f"Verify range matches v5 chart.",
                f"When MP-opens-faces-3bet at {depth}bb, what's the call/4bet/fold mix? "
                f"With Hero 4-Bet at 5.5% (in target), we may be folding too much to 3-bets.",
                f"Postflop in SRP OOP at SPR ~5-7, are we c-betting profitably? "
                f"Population folds-to-cbet ~53% — sizing matters."
            ]
        elif pos == 'BTN':
            return [
                f"At {depth}bb BTN, is our open frequency at the chart target (~46.9%)? "
                f"Sample stack 100bb so this is the deep-postflop-IP zone.",
                f"Facing 3-bets from blinds at {depth}bb, what's our 4-bet bluff frequency? "
                f"Pipeline shows ~5.5% Hero 4-Bet rate which may be light on bluffs.",
                f"In SRP IP postflop, are we c-betting too often on dynamic boards? "
                f"Caller IP Agg leak is on the OTHER side of this — opponents should be doing more, "
                f"but it's worth checking our c-bet selection too."
            ]
    elif node == '3bet':
        return [
            f"At {depth}bb, is our 3-bet sizing correct (Dave: 25-40bb→3x, 40+bb→3.5x IP from {pos})?",
            f"What's the value/bluff ratio of our 3-bet range from {pos}? "
            f"Pipeline overall 3-bet rate is 9.4% (top of 6-9% range) — may be over-3-betting bluffs.",
            f"When opponents 4-bet at {depth}bb, what's our call/5-bet jam threshold? "
            f"Hero 5-bet rate is 1.3% which is low — verify we're not folding too tight to 4-bets."
        ]
    return [
        f"What's the GTO frequency for {node} from {pos} at {depth}bb?",
        f"What's our current frequency vs the GTO baseline?",
        f"Where does the EV leak come from — preflop selection or postflop play?"
    ]


def build_questions_postf(decoded, hands):
    """Generate specific tactical questions for a postflop square."""
    pc = decoded['pos_class']
    pot = decoded['pot_type']
    spr = decoded['spr_bucket']
    phase = decoded['icm_phase']

    pos_dist = Counter((h.get('position'), h.get('opener_position')) for h in hands)
    top_pair = pos_dist.most_common(1)[0][0] if pos_dist else (None, None)
    arch_dist = Counter(h.get('board_archetype') for h in hands if h.get('board_archetype'))
    top_arch = arch_dist.most_common(2)

    if spr == 'unknown':
        return [
            f"SPR=unknown means these are typically all-in or near-all-in spots. "
            f"At {phase} phase {pc} in {pot}, are we getting all-in too wide preflop and then losing "
            f"the equity lottery, or is the issue postflop equity-realization?",
            f"For {top_pair[0]} vs {top_pair[1]} dynamic in this pot type, "
            f"what's the GTO commit threshold given our position and ICM?",
            f"On boards like {', '.join(a for a, _ in top_arch)}, what's our equity-realization "
            f"vs pure equity? Bad realization is the leak signature for low-SPR postflop."
        ]
    elif pot == '3BP':
        return [
            f"In {pot} with SPR {spr}, {pc}, {phase}: what's the c-bet frequency by board archetype? "
            f"Top archetypes here: {', '.join(a for a, _ in top_arch)}.",
            f"When the 3-bet caller leads or check-raises in {pot}, what's our continue threshold "
            f"at this SPR? Pipeline shows possible over-folds to aggressive lines.",
            f"For value-3bet hands that miss the flop, what's our barrel frequency on turns? "
            f"Pipeline shows 36.7% turn cbet which may be too low in 3BP IP."
        ]
    elif pot == 'SRP':
        return [
            f"In SRP {pc} at SPR {spr} during {phase}, what's our c-bet selection? "
            f"Population fold-to-cbet is ~53% — board archetypes matter.",
            f"For {top_pair[0]} (Hero) vs {top_pair[1]} (opener) dynamic, "
            f"are we taking the right line OOP after flatting?",
            f"When facing turn probes/leads at this SPR, what's our raise-bluff frequency? "
            f"Pipeline shows 0 triple-barrel raise-bluff rivers — the same passivity may carry to turn."
        ]
    elif pot == '4BP':
        return [
            f"4BP at SPR {spr} is essentially commit-or-fold geometry. "
            f"What's our flop check-back range when {pc}?",
            f"In {phase} ICM context, what's the commit threshold against villain leads in 4BP?",
            f"Are we 4-bet-bluffing hands that play badly postflop in 4BP? "
            f"Hero 4-Bet 5.5% suggests tight; verify 5-bet jam threshold."
        ]
    return [
        f"What's the GTO baseline for {pc} {pot} SPR-{spr} at {phase}?",
        f"What's our actual frequency mix?",
        f"Where's the EV leak — preflop selection, c-bet selection, or barrel frequencies?"
    ]


# ============================================================
# Sample hand formatter
# ============================================================

def format_sample_hand(h):
    """Compact one-line hand summary."""
    cards = h.get('cards') or ['?', '?']
    cards_str = ''.join(cards) if isinstance(cards, list) else str(cards)
    pos = h.get('position', '?')
    stack = h.get('stack_bb')
    stack_str = f"{stack:.0f}bb" if stack is not None else "?bb"
    opener = h.get('opener_position', '?')
    board = h.get('board') or []
    board_str = ' '.join(board) if board else '(no flop)'
    net = h.get('net_bb', 0)
    net_str = f"{'+' if net > 0 else ''}{net:.1f}bb"
    arch = h.get('board_archetype', '')
    arch_str = f" [{arch}]" if arch else ""
    return (f"`{cards_str}` {pos} {stack_str} vs opener={opener} | "
            f"board={board_str}{arch_str} | net={net_str}")


# ============================================================
# GTOW solver setup builder
# ============================================================

def build_gtow_setup(decoded, hands):
    """Concrete GTO Wizard solver setup parameters."""
    if decoded['kind'] == 'preflop':
        depth = stack_bucket_to_solver_depth(decoded['stack_bucket'])
        pos = decoded['pos']
        node = decoded['node']

        if node == 'RFI':
            return [
                f"**Effective stack:** {depth}bb",
                f"**Hero position:** {pos}",
                f"**Scenario:** Open-raise + facing-3-bet decision tree",
                f"**GTOW path:** Solver → Spots → Preflop → 8-max → {pos} open → "
                f"vary villain 3-bet position to match opener distribution",
            ]
        elif node == 'cold_call':
            opener_dist = Counter(h.get('opener_position') for h in hands if h.get('opener_position'))
            top_opener = opener_dist.most_common(1)[0][0] if opener_dist else '?'
            return [
                f"**Effective stack:** {depth}bb",
                f"**Hero position:** {pos}",
                f"**Villain (opener):** {top_opener} (most common; also see {', '.join(p for p,_ in opener_dist.most_common(3))})",
                f"**Scenario:** {pos} vs {top_opener} open — flat/3bet/fold decision",
                f"**GTOW path:** Solver → Spots → Preflop → {top_opener} open → {pos} response",
            ]
        elif node == '3bet':
            opener_dist = Counter(h.get('opener_position') for h in hands if h.get('opener_position'))
            top_opener = opener_dist.most_common(1)[0][0] if opener_dist else '?'
            return [
                f"**Effective stack:** {depth}bb",
                f"**Hero position:** {pos} (3-bettor)",
                f"**Villain (opener):** {top_opener}",
                f"**Scenario:** Hero 3-bets {top_opener} open → faces 4-bet decision tree",
                f"**GTOW path:** Solver → Spots → Preflop → {top_opener} open → {pos} 3-bet",
            ]
    elif decoded['kind'] == 'postflop':
        spr_b = decoded['spr_bucket']
        spr_for_solver = {'<1': 0.5, '1-3': 2.0, '3-7': 5.0, '7+': 8.0, 'unknown': '~all-in'}.get(spr_b, '?')
        avg_stack = sum(h.get('eff_stack_bb', 0) for h in hands) / max(len(hands), 1)
        pos_dist = Counter((h.get('position'), h.get('opener_position')) for h in hands)
        top_pair = pos_dist.most_common(1)[0][0] if pos_dist else ('?', '?')
        return [
            f"**Pot type:** {decoded['pot_type']}",
            f"**Hero position class:** {decoded['pos_class']} (most common: {top_pair[0]} vs {top_pair[1]})",
            f"**Effective stack (avg):** {avg_stack:.0f}bb",
            f"**Target SPR:** {spr_for_solver} (bucket: {spr_b})",
            f"**ICM phase:** {decoded['icm_phase']} {'— enable ICM in solver' if decoded['icm_phase'] in ('bubble_zone','post_bubble','ft_zone') else ''}",
            f"**GTOW path:** Solver → Spots → Postflop → {decoded['pot_type']} → {decoded['pos_class']} at SPR {spr_for_solver}",
        ]
    return [f"**Setup:** (decoded shape unsupported)"]


# ============================================================
# Per-square HH export for GTOW import (v7.31 addition)
# ============================================================

def stratified_sample(hands, n_max=25):
    """
    Stratified sampling for GTOW replay study.
    Returns up to n_max hands optimizing for variance coverage:
      - Top 1/3 = biggest losses (where the leak shows up)
      - Middle 1/3 = closest-to-mean (typical play)
      - Bottom 1/3 = biggest wins (what's working — for contrast)

    For squares with n_total <= n_max: returns all hands.
    For larger squares: returns the strata sample.
    """
    if len(hands) <= n_max:
        return list(hands)

    sorted_by_net = sorted(
        hands,
        key=lambda h: float(h.get('net_bb') or 0),
    )
    n_each = n_max // 3
    n_remaining = n_max - 2 * n_each  # middle gets the remainder

    biggest_losses = sorted_by_net[:n_each]
    biggest_wins = sorted_by_net[-n_each:] if n_each > 0 else []

    # Closest-to-mean: pick from the middle of the sorted list
    nets = [float(h.get('net_bb') or 0) for h in hands]
    mean_net = sum(nets) / len(nets) if nets else 0
    middle_pool = sorted(hands, key=lambda h: abs(float(h.get('net_bb') or 0) - mean_net))[:n_remaining * 3]
    # Take every 3rd to spread chronologically, falling back to first n if too short
    middle = middle_pool[::3][:n_remaining] if len(middle_pool) >= n_remaining else middle_pool[:n_remaining]

    # Dedupe (a hand might rank in two strata if dataset is small)
    seen = set()
    out = []
    for batch in (biggest_losses, middle, biggest_wins):
        for h in batch:
            hid = h.get('id')
            if hid and hid not in seen:
                seen.add(hid)
                out.append(h)
    return out


def load_hand_index(index_path):
    """Load the hand_id → (file_path, byte_start, byte_end) index."""
    with open(index_path) as f:
        return json.load(f)


def fetch_raw_hh(hand_id, hand_index):
    """Read the raw hand history text for a hand_id from the source files."""
    if hand_id not in hand_index:
        return None
    file_path, start, end = hand_index[hand_id]
    if not os.path.exists(file_path):
        return None
    with open(file_path, 'r') as f:
        f.seek(start)
        return f.read(end - start)


def write_square_hh(square_id, hands_for_square, hand_index, out_dir, n_max=25):
    """
    Write a GTOW-compatible HH file for a square.
    Stratified sample of up to n_max hands.
    Returns (n_written, output_path).
    """
    sample = stratified_sample(hands_for_square, n_max=n_max)
    chunks = []
    for h in sample:
        raw = fetch_raw_hh(h.get('id'), hand_index)
        if raw:
            chunks.append(raw.rstrip() + '\n')
    if not chunks:
        return 0, None
    os.makedirs(out_dir, exist_ok=True)
    # Sanitize square_id for filename (slashes etc.)
    safe_name = square_id.replace('/', '_').replace(' ', '_')
    out_path = os.path.join(out_dir, f"{safe_name}.txt")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(chunks))
    return len(chunks), out_path


# ============================================================
# Main report builder
# ============================================================

def build_report(squares_data, hands, n_top=8, hand_index=None, hh_out_dir=None, hh_n_max=25):
    """Build the GTO Wizard study setup report as markdown.

    If hand_index and hh_out_dir are provided, also writes per-square HH files
    for GTOW import and references them in the report.
    """
    # Re-bucket hands by square
    square_hands = defaultdict(list)
    for h in hands:
        pf_id = assign_preflop_square(h)
        post_id = assign_postflop_square(h)
        if pf_id:
            square_hands[pf_id].append(h)
        if post_id:
            square_hands[post_id].append(h)

    # Filter actionable, take top N by study score
    actionable = [s for s in squares_data['squares'] if is_actionable_square(s['square_id'])]
    top = sorted(actionable, key=lambda x: -x.get('study_score', 0))[:n_top]

    n_total = squares_data.get('total_hands', sum(len(square_hands[k]) for k in square_hands))
    n_filtered_out = len(squares_data['squares']) - len(actionable)

    write_hh = hand_index is not None and hh_out_dir is not None

    lines = [
        f"# GTO Wizard Study Setup — Top {n_top} Actionable Squares",
        f"_Generated {datetime.now(timezone.utc).isoformat()} | "
        f"{n_total:,} hands | {len(actionable)} actionable squares "
        f"(filtered out {n_filtered_out} structural-fold/walked/other squares)_",
        "",
        "**Methodology.** Top squares from `gem_squares.json` ranked by study score, "
        "filtered to those involving an actionable Hero decision (excludes pure-fold and "
        "walked-BB squares which are structural blind tax, not studyable patterns). "
        "For each square: GTOW solver setup parameters, 3 specific tactical questions to "
        "think through BEFORE running the solver, and 3 representative sample hands.",
        "",
        "**Per Session 18 template:** Cluster by specific leak pattern, include sample-hand "
        "details (cards/board/SPR/stacks/position), ask specific tactical question at a "
        "specific decision point — never generic 'line check' questions.",
        "",
    ]
    if write_hh:
        lines.append(f"**HH replay files:** Each square has a companion `.txt` HH file in "
                     f"`{hh_out_dir}/` (up to {hh_n_max} stratified hands: biggest losses + "
                     f"closest-to-mean + biggest wins) that can be imported directly into "
                     f"GTO Wizard for replay study. Stratification gives variance coverage "
                     f"so you see what's leaking AND what's working in each square.")
        lines.append("")
    lines.append("---")
    lines.append("")

    hh_summary = []  # for footer
    for i, s in enumerate(top, 1):
        sid = s['square_id']
        hs = square_hands.get(sid, [])
        if sid.startswith('PF_'):
            decoded = decode_pf_square(sid)
            questions = build_questions_pf(decoded, hs)
        else:
            decoded = decode_postf_square(sid)
            questions = build_questions_postf(decoded, hs)
        setup = build_gtow_setup(decoded, hs)

        # Per-square HH export
        hh_path = None
        n_written = 0
        if write_hh:
            n_written, hh_path = write_square_hh(sid, hs, hand_index, hh_out_dir, n_max=hh_n_max)
            if hh_path:
                hh_summary.append((sid, n_written, hh_path))

        # Header
        lines.append(f"## #{i}: `{sid}`")
        lines.append("")
        lines.append(f"- **Volume:** {s['n_total']} hands ({s['freq_pct']:.2f}% of session)")
        lines.append(f"- **Performance:** {s['net_bb_mean']:+.2f} BB/hand "
                     f"(σ={s['net_bb_stddev']:.2f}, study score {s['study_score']:.0f})")
        lines.append(f"- **Avg stack:** {s['avg_eff_stack_bb']:.0f}bb")
        if hh_path:
            rel_path = os.path.relpath(hh_path, os.path.dirname(hh_out_dir.rstrip('/'))) if hh_out_dir else hh_path
            lines.append(f"- **HH replay file:** `{os.path.basename(hh_path)}` "
                         f"({n_written} stratified hands — load into GTOW)")

        # Setup
        lines.append("")
        lines.append("### Solver setup")
        for line in setup:
            lines.append(f"- {line}")

        # Questions
        lines.append("")
        lines.append("### Specific tactical questions to think through BEFORE solving")
        for j, q in enumerate(questions, 1):
            lines.append(f"{j}. {q}")

        # Sample hands
        lines.append("")
        lines.append("### Representative sample hands")
        for sh in hs[:3]:
            lines.append(f"- {format_sample_hand(sh)}")

        lines.append("")
        lines.append("---")
        lines.append("")

    # Footer
    lines.append("")
    if hh_summary:
        lines.append("## HH replay files written")
        lines.append("")
        lines.append("| Square | Hands | File |")
        lines.append("|--------|-------|------|")
        for sid, n, path in hh_summary:
            lines.append(f"| `{sid}` | {n} | `{os.path.basename(path)}` |")
        lines.append("")
    lines.append("## Notes on the squares pipeline")
    lines.append("")
    lines.append("- **`unknown` SPR bucket** appears at #1, #4, #7. These are spots where "
                 "Hero went all-in PF or saw flop with very low SPR. Avg pot/stack ratio "
                 "looks inflated because pot proxy uses `spr * eff_stack` formula which "
                 "fails when SPR is None. v7.32 candidate: distinguish 'all-in PF' from "
                 "'shallow postflop' as separate categories.")
    lines.append("- **`60+` stack bucket** lumps everything from 60bb to 200bb+. Solver "
                 "depth varies materially across this range (60bb 4-bet jam threshold "
                 "differs from 100bb mostly-flat-call). Worth subdividing into 60-100 / "
                 "100+ in v7.32.")
    lines.append("- **Stratified sampling for HH export** picks 1/3 biggest losses + "
                 "1/3 closest-to-mean + 1/3 biggest wins. This gives variance coverage "
                 "for replay study — you see what's leaking AND what's working in the same "
                 "square, which is essential for separating 'bad strategy' from 'good "
                 "strategy with bad runouts'.")
    lines.append("")
    lines.append("---")
    lines.append("_Generated by gem_squares_gtow.py v7.31._")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="GEM v7.31 GTOW study setup builder")
    ap.add_argument("--squares", default="gem_squares.json", help="Squares snapshot input")
    ap.add_argument("--hands", default="gem_hands_lean.json", help="Lean hands input")
    ap.add_argument("--output", default="GTOW_Study_Setup.md", help="Markdown output")
    ap.add_argument("--top", type=int, default=8, help="Number of top actionable squares")
    ap.add_argument("--hh-index", default=None, help="Hand_id → raw HH index JSON (from build_hand_index.py)")
    ap.add_argument("--hh-out-dir", default=None, help="Directory to write per-square HH files")
    ap.add_argument("--hh-n-max", type=int, default=25, help="Max hands per square HH export")
    args = ap.parse_args()

    with open(args.squares) as f:
        squares_data = json.load(f)
    with open(args.hands) as f:
        hands = json.load(f)

    hand_index = None
    if args.hh_index:
        if not os.path.exists(args.hh_index):
            sys.stderr.write(f"[gem_squares_gtow] WARNING: hh-index not found at {args.hh_index} — skipping HH export\n")
        else:
            hand_index = load_hand_index(args.hh_index)
            sys.stderr.write(f"[gem_squares_gtow] loaded {len(hand_index)} hand_id → HH mappings\n")

    report = build_report(
        squares_data, hands,
        n_top=args.top,
        hand_index=hand_index,
        hh_out_dir=args.hh_out_dir,
        hh_n_max=args.hh_n_max,
    )
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)
    sys.stderr.write(f"[gem_squares_gtow] wrote {args.output}\n")
    if args.hh_out_dir and hand_index:
        sys.stderr.write(f"[gem_squares_gtow] wrote per-square HH files to {args.hh_out_dir}/\n")


if __name__ == "__main__":
    main()
