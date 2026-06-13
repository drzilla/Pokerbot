#!/usr/bin/env python3
"""
gem_drill_export.py — v7.62 (2026-05-19)

Build GTO Wizard custom drill (.txt) files from GEM data.

GTOW drill schema
=================
Each drill is a single-line JSON object:
  {"id": "<uuid>", "query": {...71 fields IN REFERENCE ORDER...},
   "name": "...", "description": "..."}

Empirical findings from upload tests (v7.59 → v7.62):
  - GTOW ignores the top-level `tags` field. Off by default in v7.62.
  - GTOW collapses whitespace in description.
  - GTOW import REQUIRES fields in a specific order. v7.62 emits
    `query` keys in the canonical reference order extracted from GTOW's
    own export of "MTT all". v7.61 (arbitrary dataclass order) → 400.
  - Descriptions stay short + plain prose (no ▸, no Tags line).
    The bracket prefix in the name carries the metadata.

Filter fields (discovered from Ron's edited drill, 2026-05-19):
  - fh_groups_selection: "manual" (default, fh_groups used) | "hand_class"
    (fh_hands and/or fh_draws used)
  - fh_hands: comma-separated hand-class list. Valid values:
      ace_high, king_high, no_made_hand, low_pair, second_pair,
      third_pair, underpair, top_pair, two_pair, overpair, trips, set,
      straight, flush, fullhouse, quads, straight_flush
  - fh_draws: comma-separated draw list:
      no_draw, onecard_bdfd, twocards_bdfd, gutshot, oesd,
      flush_draw, nut_flush_draw, combo_draw
  - flop_suits / flop_paired / flop_connectedness: comma-separated sets
      flop_suits in {rainbow, flush_draw, monotone}
      flop_paired in {not_paired, paired, tripled}
      flop_connectedness in {disconnected, oesd_possible, connected}
  - flop_high_card, flop_mid_card, flop_low_card: single letter
      ("A","K","Q","J","T","9","8",...,"2")

Naming convention
=================
  <YYMMDD>_<NN> [<Street>/<Pot>/<Pos-or-Players>/<Stack>/<Format>] <body>

Usage
=====
  python3 gem_drill_export.py --leaks J29,L1,L5 --output drills.txt
  python3 gem_drill_export.py --squares gem_squares.json \\
      --hands gem_hands_lean.json --top 8 --output drills_squares.txt
"""
import argparse
import json
import os
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import date as _date
from typing import Optional, List, Dict, Any

VERSION = "7.62"

# ============================================================================
# RANGE PRESETS
# ============================================================================
# Three preset ranges, copied verbatim from GTOW reference exports so they
# round-trip cleanly. Use whichever fits the drill scope.

# Full 169-combo range — every starting hand. Default for "wide net" drills.
RANGE_ALL = (
    "22,33,44,55,66,77,88,99,AA,KK,QQ,JJ,TT,AKs,AKo,AQs,AJs,AQo,KQs,ATs,AJo,"
    "KJs,KQo,QJs,KTs,A9s,ATo,QTs,A8s,JTs,A7s,A5s,KJo,K9s,A4s,A6s,Q9s,A3s,T9s,"
    "QJo,J9s,A2s,KTo,A9o,K8s,QTo,K7s,JTo,Q8s,K6s,T8s,A8o,J8s,K5s,98s,A5o,A7o,"
    "K4s,K9o,Q7s,K3s,Q6s,A4o,T7s,A6o,K2s,J7s,Q9o,T9o,Q5s,97s,A3o,J9o,87s,Q4s,"
    "Q3s,A2o,K8o,76s,Q2s,J6s,T6s,J5s,65s,96s,86s,54s,K7o,J4s,Q8o,T8o,J3s,J8o,"
    "K6o,75s,98o,J2s,T5s,K5o,T4s,64s,53s,85s,95s,T3s,K4o,T2s,43s,Q7o,74s,K3o,"
    "Q6o,T7o,J7o,97o,63s,87o,K2o,52s,Q5o,93s,84s,94s,42s,92s,Q4o,32s,73s,76o,"
    "Q3o,65o,54o,86o,T6o,Q2o,J6o,96o,62s,J5o,83s,82s,J4o,75o,J3o,72s,64o,53o,"
    "J2o,85o,T5o,95o,T4o,43o,T3o,T2o,74o,63o,52o,42o,84o,93o,94o,92o,32o,73o,"
    "62o,82o,83o,72o"
)

# ~80-combo top range used in ICM/short-stack drills. From the reference file.
RANGE_TOP80 = (
    "22,33,44,55,66,77,88,99,AA,KK,QQ,JJ,TT,AKs,AKo,AQs,AJs,AQo,KQs,ATs,AJo,"
    "KJs,KQo,QJs,KTs,A9s,ATo,QTs,A8s,JTs,A7s,A5s,KJo,K9s,A4s,A6s,Q9s,A3s,T9s,"
    "QJo,J9s,A2s,KTo,A9o,K8s,QTo,K7s,JTo,Q8s,K6s,T8s,A8o,J8s,K5s,98s,A5o,A7o,"
    "K4s,K9o,Q7s,K3s,Q6s,A4o,T7s,A6o,K2s,J7s,Q9o,T9o,Q5s,97s,A3o,J9o,87s,Q4s,"
    "Q3s,A2o,K8o,76s,Q2s,J6s,T6s,J5s,65s,96s,86s,54s,K7o"
)

# EP push/fold range — short stack open-shove from EP. ~55 combos.
RANGE_EP_PUSH = (
    "22,33,44,55,66,77,88,ATo,A8s,A7s,A5s,KJo,A4s,A6s,A3s,QJo,A2s,KTo,A9o,K8s,"
    "QTo,K7s,JTo,Q8s,K6s,T8s,A8o,J8s,K5s,98s,A5o,A7o,K4s,Q7s,A4o,A6o,A3o,87s,"
    "A2o,76s,K9o,65s,54s,K3s,Q9s,J9s,T9s,JTs,QTs,K9s,KTs,J7s,97s,T7s,K8o"
)


# ============================================================================
# MAPPING TABLES
# ============================================================================

# Stack-bucket label (from gem_squares.py) → GTOW depth value.
# Same mapping as gem_squares_gtow.stack_bucket_to_solver_depth so squares
# drills and squares HH-replay study share one stack convention.
STACK_BUCKET_TO_DEPTH_BB = {
    "<12": 10,
    "12-25": 20,
    "25-40": 30,
    "40-60": 50,
    "60+": 100,
    "unknown": 100,
}

# ICM phase (from gem tournament_phase) → GTOW gametype string.
# late_reg/post_reg are chip-EV (no ICM). bubble_zone uses bubble-mid ICM
# preset. post_bubble/ft_zone get heavier ICM presets. These match the
# gametype strings observed in the reference drill file.
ICM_PHASE_TO_GAMETYPE = {
    "late_reg": "MTTGeneral",
    "post_reg": "MTTGeneral",
    "bubble_zone": "MTTGeneral_ICM8m200PTBUBBLEMID",
    "post_bubble": "MTTGeneral_ICM9m200PTPCT37",
    "ft_zone": "MTTGeneral_ICM8m1000PTFT",
    "unknown": "MTTGeneral",
}


def depth_to_str(bb: int) -> str:
    """GTOW depth field is encoded as '<bb>.125' (e.g. 25 → '25.125')."""
    return f"{bb}.125"


# ============================================================================
# CANONICAL FIELD ORDER
# ============================================================================
# GTOW's import validator appears to require fields in a specific order.
# This list is extracted verbatim from GTOW's export of "MTT all" — the
# reference drill that round-trips cleanly. Emitting query fields in any
# other order produces a 400 error on import.

REFERENCE_QUERY_FIELD_ORDER = (
    "fh_hero", "fh_actions", "fh_start_spot",
    "fh_trainer_mode", "fh_trainer_grouping", "fh_trainer_game_mode",
    "fh_trainer_game_speed", "fh_trainer_tables", "fh_groups_selection",
    "board", "gametype", "depth", "stacks", "custree_id", "solution_type",
    "depth_list", "stacks_list", "average_stack",
    "gmff_stacks_type", "gmff_opening_type", "gmff_tournament_phase",
    "gmff_players", "gmff_variant", "gmff_cash_drop", "gmff_biggest_stack",
    "gmff_depth", "gmff_type", "gmff_rake", "gmff_opening_size",
    "gmff__3bet_size", "gmff_simplified_position",
    "fh_hero_stack_type", "fh_opponent", "fh_alternate", "fh_rel_positions",
    "fh_groups", "fh_hands", "fh_draws",
    "fh_trainer_result", "fh_trainer_result_chart",
    "fh_trainer_autoplay", "fh_trainer_timebank",
    "fh_trainer_hero_frequency", "fh_trainer_quick_result",
    "fh_trainer_learning_mode", "fh_trainer_hero_range",
    "fh_trainer_equity_chart", "fh_trainer_opponent_range",
    "fh_trainer_ranges_comparison", "fh_trainer_hand_strength",
    "fh_trainer_total_frequency", "fh_trainer_category_hands",
    "fh_trainer_category_draws", "fh_trainer_hero_strategy",
    "fh_trainer_rng_visible", "fh_trainer_streak_visible",
    "fh_rng", "fh_trainer_session",
    "flop_suits", "flop_paired", "flop_connectedness", "flop_subset",
    "flop_high_card", "flop_mid_card", "flop_low_card",
    "turn_suit", "turn_paired", "turn_card",
    "river_suit", "river_paired", "river_card",
)
assert len(REFERENCE_QUERY_FIELD_ORDER) == 71, "Reference field count must be 71"


# ============================================================================
# TAG DERIVATION
# ============================================================================
# Tags Ron wants surfaced in the drill list / filterable in the UI:
#   - Street: Preflop / Postflop (and Flop/Turn/River sub-tag for postflop)
#   - Pot type: SRP / 3BP / 4BP / All
#   - Players: HU / MW
#   - Position: OOP / IP (postflop only)
#   - Stack: <12bb / 12-25bb / 25-40bb / 40-60bb / 60bb+
#   - Format: cEV / ICM / Bubble / FT / <N>%-Field / PKO
# Auto-derived where possible from drill fields; recipe overrides the rest.

import re as _re


def derive_street_tags(fh_start_spot: str) -> List[str]:
    """preflop → ['Preflop']; flop/turn/river → ['Postflop', '<Street>']."""
    if fh_start_spot == "preflop":
        return ["Preflop"]
    return ["Postflop", fh_start_spot.capitalize()]


def derive_stack_tag(depth_str: str) -> str:
    """Map '<bb>.125' depth string to a bucket label. Int-truncates the .125
    so '60.125' → 60 → '40-60bb' (matches user mental model 'this is 60bb')."""
    try:
        bb = int(float(depth_str))
    except (TypeError, ValueError):
        return "unknown-stack"
    if bb < 12:
        return "<12bb"
    if bb <= 25:
        return "12-25bb"
    if bb <= 40:
        return "25-40bb"
    if bb <= 60:
        return "40-60bb"
    return "60bb+"


def derive_format_tags(gametype: str) -> List[str]:
    """
    gametype like 'MTTGeneral', 'MTTGeneral_ICM8m200PTBUBBLEMID',
    'MTTGeneral_ICMPKO8m200PTPCT50' → tags like ['cEV'], ['ICM', 'Bubble'],
    ['PKO', '50%-Field'].
    """
    tags: List[str] = []
    is_icm = "ICM" in gametype
    is_pko = "PKO" in gametype
    if is_pko:
        tags.append("PKO")
    if is_icm and not is_pko:
        tags.append("ICM")
    if is_icm or is_pko:
        if "BUBBLE" in gametype:
            tags.append("Bubble")
        elif "FT" in gametype:
            tags.append("FT")
        else:
            m = _re.search(r"PCT(\d+)", gametype)
            if m:
                tags.append(f"{m.group(1)}%-Field")
    if not (is_icm or is_pko):
        tags.append("cEV")
    return tags


def make_drill_name(
    body: str,
    fh_start_spot: str,
    depth_str: str,
    gametype: str,
    pot_type: str = "SRP",
    pos_or_players: str = "HU",
) -> str:
    """
    Compose the bracketed-tag-prefixed name.
      [<Street>/<Pot>/<Pos-or-Players>/<Stack>/<Format>] <body>

    pot_type: 'SRP' / '3BP' / '4BP' / 'All' / '-' (use '-' when pot doesn't apply)
    pos_or_players: e.g. 'SB-BB', 'OOP-HU', 'IP-HU', 'PFR-HU', 'EP', 'Blinds', 'All'
    """
    street_tags = derive_street_tags(fh_start_spot)
    street_label = "Pre" if street_tags == ["Preflop"] else street_tags[1]  # Flop/Turn/River
    stack_label = derive_stack_tag(depth_str)
    fmt_label = "/".join(derive_format_tags(gametype))
    bracket = f"[{street_label}/{pot_type}/{pos_or_players}/{stack_label}/{fmt_label}]"
    return f"{bracket} {body}"


def assemble_tags(
    fh_start_spot: str,
    depth_str: str,
    gametype: str,
    pot_type: str = "SRP",
    players: str = "HU",
    position: Optional[str] = None,
    extra: Optional[List[str]] = None,
) -> List[str]:
    """
    Build a canonical tag list matching Ron's categories. Order:
    street → pot → players → position (if any) → stack → format → extras.
    """
    tags = list(derive_street_tags(fh_start_spot))
    if pot_type and pot_type != "-":
        tags.append(pot_type)
    if players and players != "-":
        tags.append(players)
    if position:
        tags.append(position)
    tags.append(derive_stack_tag(depth_str))
    tags.extend(derive_format_tags(gametype))
    if extra:
        tags.extend(extra)
    # De-dupe preserving order
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ============================================================================
# DRILL DATACLASS
# ============================================================================

@dataclass
class Drill:
    """
    One GTOW custom drill. Default values match the most-permissive setup
    (full range, preflop start, all positions, 100bb chip-EV, normal speed,
    stop end-of-hand, all trainer flags on). Override only what matters
    for the specific drill — leaving defaults gives a clean baseline.
    """
    # Required
    name: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)

    # Hero / opponent positions
    fh_hero: str = ""              # e.g. "BB,SB" — empty = all positions
    fh_opponent: str = ""          # e.g. "BTN,CO" — empty = all
    fh_rel_positions: str = ""
    fh_alternate: str = ""
    fh_hero_stack_type: str = ""

    # Action / start spot
    fh_actions: str = "StartOfHand"        # "" or "StartOfHand"
    fh_start_spot: str = "preflop"          # preflop/flop/turn/river

    # Trainer behaviour
    fh_trainer_mode: str = "stop_end_of_hand"   # stop_end_of_hand / stop_end_of_street / stop_after_action
    fh_trainer_grouping: str = "swv_grouping_none"
    fh_trainer_game_mode: str = "trainer_actions"
    fh_trainer_game_speed: str = "normal"        # normal/fast/turbo
    fh_trainer_tables: str = "1"
    fh_groups_selection: str = "manual"
    fh_trainer_session: str = "50"               # hands per session
    fh_trainer_autoplay: str = ""                # "" or "3_sec"
    fh_trainer_timebank: str = ""                # "" or "15_sec"

    # Game / stack
    gametype: str = "MTTGeneral"
    depth: str = "100.125"
    stacks: str = ""              # explicit per-seat stacks "30.125-50.125-..."
    depth_list: str = ""          # multi-depth like "60.125,80.125,100.125"
    stacks_list: str = ""
    average_stack: str = ""
    custree_id: str = ""
    solution_type: str = "gwiz"

    # gmff_* (game-mode flag/filter) — almost always empty
    gmff_stacks_type: str = ""
    gmff_opening_type: str = ""
    gmff_tournament_phase: str = ""
    gmff_players: str = ""
    gmff_variant: str = ""
    gmff_cash_drop: str = ""
    gmff_biggest_stack: str = ""
    gmff_depth: str = ""
    gmff_type: str = ""
    gmff_rake: str = ""
    gmff_opening_size: str = ""
    gmff__3bet_size: str = ""
    gmff_simplified_position: str = ""

    # Range
    fh_groups: str = RANGE_ALL
    fh_hands: str = ""
    fh_draws: str = ""

    # Board / runout filters (all empty = random)
    board: str = ""
    flop_suits: str = ""           # rainbow / two-tone / monotone (UI-driven)
    flop_paired: str = ""
    flop_connectedness: str = ""
    flop_subset: str = ""
    flop_high_card: str = ""
    flop_mid_card: str = ""
    flop_low_card: str = ""
    turn_suit: str = ""
    turn_paired: str = ""
    turn_card: str = ""
    river_suit: str = ""
    river_paired: str = ""
    river_card: str = ""

    # Display flags — defaults match GTOW reference (all empty). Recipes
    # can override to "on" if they want richer trainer feedback, but the
    # safe default is empty since some import paths reject non-standard
    # configs.
    fh_trainer_result: str = ""
    fh_trainer_result_chart: str = ""
    fh_trainer_hero_frequency: str = ""
    fh_trainer_quick_result: str = ""
    fh_trainer_learning_mode: str = ""
    fh_trainer_hero_range: str = ""
    fh_trainer_equity_chart: str = ""
    fh_trainer_opponent_range: str = ""
    fh_trainer_ranges_comparison: str = ""
    fh_trainer_hand_strength: str = ""
    fh_trainer_total_frequency: str = ""
    fh_trainer_category_hands: str = ""
    fh_trainer_category_draws: str = ""
    fh_trainer_hero_strategy: str = ""
    fh_trainer_rng_visible: str = ""
    fh_trainer_streak_visible: str = ""
    fh_rng: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Produce {id, query, name, description} with query in canonical
        reference order. Top-level `tags` is opt-in via to_json_line(include_tags)
        because GTOW currently ignores it."""
        raw = asdict(self)
        name = raw.pop("name")
        description = raw.pop("description")
        raw.pop("tags", None)
        # Build query dict in canonical reference order. Missing fields → "".
        query = {k: raw.get(k, "") for k in REFERENCE_QUERY_FIELD_ORDER}
        # Sanity-check we have all 71 fields and no orphans
        unknown = set(raw.keys()) - set(REFERENCE_QUERY_FIELD_ORDER)
        if unknown:
            raise ValueError(f"Drill has unknown fields not in reference order: {unknown}")
        return {
            "id": str(uuid.uuid4()),
            "query": query,
            "name": name,
            "description": description,
        }

    def to_json_line(self) -> str:
        """One-line minified JSON, matching GTOW import format."""
        return json.dumps(self.to_dict(), separators=(",", ":"))


# ============================================================================
# DESCRIPTION BUILDER
# ============================================================================
# Empirical: GTOW collapses whitespace AND special unicode markers like ▸
# made descriptions long enough to risk rejection. v7.62 keeps descriptions
# short and plain. The bracket prefix in the name carries the metadata.
#
# Recipe convention: descriptions are 1-3 sentences max. Setup, target,
# leak. No bullets, no symbols, no Tags line.

def build_description(setup: str, target: str = "", leak: str = "") -> str:
    parts = [setup.rstrip(".") + "."]
    if target:
        parts.append("Target: " + target.rstrip(".") + ".")
    if leak:
        parts.append("Leak: " + leak.rstrip(".") + ".")
    return " ".join(parts)


# ============================================================================
# LEAK REGISTRY — recipes for confirmed leaks
# ============================================================================
# Each function returns a Drill (or list of Drills) targeting one leak.
# Keep recipes short and opinionated — the goal is to drill the exact spot
# the leak shows up in, not to teach the general topic.

def leak_J29_sb_bvb() -> Drill:
    """
    J29 — SB BvB limp-vs-raise discipline.
    Confirmed leak: Hero raises ~33% vs J29's ~10% target; under-limps.
    """
    depth = depth_to_str(30)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "J29 BvB limp discipline (raise<10%, limp~80%)",
            fh_start_spot="preflop", depth_str=depth, gametype=gametype,
            pot_type="SRP", pos_or_players="SB-BB",
        ),
        description=build_description(
            setup="SB vs BB at 30bb, preflop limp/raise/fold decision",
            target="Limp ~80%, raise ~10%, fold ~10% per Dave's J29",
            leak="Hero over-raising ~33%, under-limping (J29 violation)",
        ),
        tags=assemble_tags(
            fh_start_spot="preflop", depth_str=depth, gametype=gametype,
            pot_type="SRP", players="HU", extra=["BvB", "J29", "SB"],
        ),
        fh_hero="SB", fh_opponent="BB", depth=depth, gametype=gametype,
        fh_start_spot="preflop", fh_actions="StartOfHand",
        fh_trainer_mode="stop_end_of_hand",
        fh_trainer_game_speed="normal",
        fh_groups=RANGE_ALL,
    )


def leak_caller_ip_flop_agg() -> Drill:
    """Caller IP Flop Aggression — confirmed chronic leak (<30% vs 30-40% target)."""
    depth = depth_to_str(60)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "Caller flop aggression target 30-40% (Hero <30%)",
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="SRP", pos_or_players="IP-HU",
        ),
        description=build_description(
            setup="Hero flats vs an open from BTN/CO/HJ, sees flop IP heads-up, villain checks",
            target="30-40% bet frequency (caller IP range advantage)",
            leak="Hero <30% (chronic passivity across sessions)",
        ),
        tags=assemble_tags(
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="SRP", players="HU", position="IP",
            extra=["Caller", "CallerIPAgg"],
        ),
        fh_hero="BTN,CO,HJ", fh_opponent="UTG,UTG+1,LJ,HJ,CO",
        depth=depth, gametype=gametype,
        fh_start_spot="flop", fh_actions="",
        fh_trainer_mode="stop_end_of_street",
        fh_trainer_game_speed="fast", fh_trainer_autoplay="3_sec",
        fh_groups=RANGE_ALL,
    )


def leak_one_and_done() -> Drill:
    """One-and-done barreling — Hero c-bets flop, gives up too often on turn."""
    depth = depth_to_str(50)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "One-and-done turn barrel frequency",
            fh_start_spot="turn", depth_str=depth, gametype=gametype,
            pot_type="SRP", pos_or_players="PFR-HU",
        ),
        description=build_description(
            setup="Hero opened, c-bet flop, gets called. Turn decision: barrel or check back",
            target="Barrel turn when range + texture favour continued aggression",
            leak="Hero high one-and-done rate (surrenders turn even when story justifies barrel)",
        ),
        tags=assemble_tags(
            fh_start_spot="turn", depth_str=depth, gametype=gametype,
            pot_type="SRP", players="HU", extra=["PFR", "OneAndDone", "TurnBarrel"],
        ),
        fh_hero="BTN,CO,HJ,SB", fh_opponent="",
        depth=depth, gametype=gametype,
        fh_start_spot="turn", fh_actions="",
        fh_trainer_mode="stop_end_of_street",
        fh_trainer_game_speed="fast", fh_trainer_autoplay="3_sec",
        fh_groups=RANGE_ALL,
    )


def leak_oop_pfr_xc_xc_showdown() -> Drill:
    """Check-call-call-showdown OOP as PFR — biggest single bleed pattern."""
    depth = depth_to_str(50)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "OOP PFR x/c/c surrender pattern (biggest bleed)",
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="SRP", pos_or_players="OOP-HU",
        ),
        description=build_description(
            setup="Hero opened OOP (UTG/MP/SB), got flatted, plays flop+ out of position",
            target="Mix bet-flop / x-r / x-c / x-f based on texture + range; protect value when checking",
            leak="Biggest confirmed bleed — x/c flop, x/c turn, x to showdown surrender pattern. Loses to villain's nut-leaning continue range",
        ),
        tags=assemble_tags(
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="SRP", players="HU", position="OOP",
            extra=["PFR", "XCXC", "MultiStreet"],
        ),
        fh_hero="UTG,UTG+1,LJ,HJ,SB", fh_opponent="",
        depth=depth, gametype=gametype,
        fh_start_spot="flop", fh_actions="",
        fh_trainer_mode="stop_end_of_hand",
        fh_trainer_game_speed="normal",
        fh_groups=RANGE_ALL,
    )


def leak_mid_pairs_66_99() -> Drill:
    """Mid pairs 66-99 underperforming — confirmed leak."""
    depth = depth_to_str(100)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "Mid pairs 66-99 set-mine + bluff-catch isolation",
            fh_start_spot="preflop", depth_str=depth, gametype=gametype,
            pot_type="All", pos_or_players="All",
        ),
        description=build_description(
            setup="Range locked to 66/77/88/99. All positions, 60-100bb depth across deep-stack levels",
            target="Solver mix — open/3-bet pre, c-bet small or check-fold on overcards, fold-vs-call lines on overcard turns",
            leak="Mid pairs underperforming vs expectation across confirmed-leak window. Recurring overplay on overcard runouts",
        ),
        tags=assemble_tags(
            fh_start_spot="preflop", depth_str=depth, gametype=gametype,
            pot_type="All", players="-", extra=["MidPairs", "66-99", "Deep"],
        ),
        fh_hero="", fh_opponent="",
        depth=depth, gametype=gametype,
        depth_list="60.125,80.125,100.125",
        fh_start_spot="preflop", fh_actions="StartOfHand",
        fh_trainer_mode="stop_end_of_hand",
        fh_trainer_game_speed="normal",
        fh_groups="66,77,88,99",
    )


def leak_3bet_construction_blinds() -> Drill:
    """3-bet construction from blinds — confirmed leak."""
    depth = depth_to_str(80)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "3-bet construction from blinds (mix value+blocker bluffs)",
            fh_start_spot="preflop", depth_str=depth, gametype=gametype,
            pot_type="3BP", pos_or_players="Blinds",
        ),
        description=build_description(
            setup="Hero defends SB/BB vs opens from BTN/CO/HJ across 40-100bb depths",
            target="Polar 3-bet range — value (TT+/AQ+) + bluff blockers (Axs, KQo type). Sized 3-3.5x IP",
            leak="3-bet range construction off — under-bluffing or wrong blocker selection",
        ),
        tags=assemble_tags(
            fh_start_spot="preflop", depth_str=depth, gametype=gametype,
            pot_type="3BP", players="HU", extra=["Blinds", "3BetConstruction"],
        ),
        fh_hero="SB,BB", fh_opponent="BTN,CO,HJ",
        depth=depth, gametype=gametype,
        depth_list="40.125,60.125,80.125,100.125",
        fh_start_spot="preflop", fh_actions="StartOfHand",
        fh_trainer_mode="stop_end_of_hand",
        fh_trainer_game_speed="normal",
        fh_groups=RANGE_ALL,
    )


def leak_L1_bb_cr_overcommit() -> Drill:
    """L1 — BB CR overcommit when equity dies on turn.
    Tightened with flop filter: two-tone (flush-draw-present) + connected
    or oesd-possible textures, where x/r impulse fires most often.
    """
    depth = depth_to_str(50)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "L1 BB x/r turn equity-shift plan (draw-heavy flops)",
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="SRP", pos_or_players="BB-HU",
        ),
        description=build_description(
            setup="BB defending vs single open at 50bb. Flop two-tone + connected/oesd-possible (draw-heavy)",
            target="Plan all three turn branches (FD bust, brick, equity-completing) BEFORE clicking x/r",
            leak="L1 — over-commit on equity-killing turns. -135.6 BB across 3 hands last week",
        ),
        tags=assemble_tags(
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="SRP", players="HU", position="OOP",
            extra=["BB", "L1", "CR-Overcommit"],
        ),
        fh_hero="BB", fh_opponent="BTN,CO,HJ,LJ,UTG,UTG+1,MP",
        depth=depth, gametype=gametype,
        fh_start_spot="flop", fh_actions="",
        fh_trainer_mode="stop_end_of_hand",
        fh_trainer_game_speed="normal",
        fh_groups=RANGE_ALL,
        # NEW: tighten to draw-heavy flops where the leak fires
        flop_suits="flush_draw",   # two-tone (one suited pair present)
        flop_connectedness="oesd_possible,connected",
    )


def leak_L3_multiway_3bp_overjam() -> Drill:
    """
    L3 — Multi-way 3BP over-jamming when one villain is a capped flatter.
    Confirmed leak: when a 3-bet is flatted in multi-way pots, the flatter's
    range narrows to ~QQ+/AK in MTT mid-stakes pools. Hero ignoring this
    and 4-bet jamming marginal hands (77, ATs, AJo) treats the spot as HU.
    """
    depth = depth_to_str(50)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "L3 multi-way 3BP 4-bet jam discipline (flatter caps to QQ+/AK)",
            fh_start_spot="preflop", depth_str=depth, gametype=gametype,
            pot_type="4BP", pos_or_players="MW",
        ),
        description=build_description(
            setup="Hero opens UTG-CO at 40-60bb. Villain 3-bets, second villain flats the 3-bet. Hero faces 4-bet-or-fold decision",
            target="Range-narrow before jamming — flatter's range in MTT mid-stakes ~80% value (AA/KK/QQ trap-flats, JJ/AKs occasionally). Hero's continue range must beat THAT range, not the 3-bettor's",
            leak="Hero 4-bet jams 77, ATs, AJo treating spot as HU vs 3-bettor — dominated by flatter's range. -96 BB across 2 hands last week (77 HJ, ATs MP)",
        ),
        tags=assemble_tags(
            fh_start_spot="preflop", depth_str=depth, gametype=gametype,
            pot_type="4BP", players="MW",
            extra=["L3", "Multiway", "FlatterCaps"],
        ),
        fh_hero="UTG,UTG+1,LJ,HJ,MP,CO", fh_opponent="",
        depth=depth, gametype=gametype,
        fh_start_spot="preflop", fh_actions="StartOfHand",
        fh_trainer_mode="stop_end_of_hand",
        fh_trainer_game_speed="normal",
        fh_groups=RANGE_ALL,
    )


def leak_river_bluff_no_blocker() -> Drill:
    """
    River no-blocker overbet/jam discipline. Multiple confirmed III.1 punts
    (4h3h donk-overbet -33.5 BB, QT BB 170%-overbet, K5s monotone-paired).
    Starts at flop (known-working spot) and plays through to river where
    the actual decision lives.
    """
    depth = depth_to_str(50)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "River bluff discipline — no-blocker overbet check",
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="SRP", pos_or_players="All",
        ),
        description=build_description(
            setup="Heads-up postflop, plays through to river. Hero faces overbet/jam-as-bluff decisions",
            target="Two-gate check before any river bluff-jam: is villain CAPPED, and do I hold a key blocker. If neither, do not jam",
            leak="Confirmed III.1 pattern — multiple no-blocker overbet jams last 7 days. Pool calls wider than Hero models",
        ),
        tags=assemble_tags(
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="SRP", players="HU",
            extra=["RiverBluff", "NoBlocker", "III.1"],
        ),
        fh_hero="", fh_opponent="",
        depth=depth, gametype=gametype,
        fh_start_spot="flop", fh_actions="",
        fh_trainer_mode="stop_end_of_hand",
        fh_trainer_game_speed="normal",
        fh_groups=RANGE_ALL,
    )


def leak_L4_polar_3bet_xr_oop() -> Drill:
    """L4 — Polar 3-bettor x/r OOP with second-best hand."""
    depth = depth_to_str(100)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "L4 polar 3-bet x/r vs second-best (never x/r second-best)",
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="3BP", pos_or_players="OOP-HU",
        ),
        description=build_description(
            setup="Hero 3-bet OOP, gets called, sees flop. Decision tree: c-bet / x-c / x-r / x-f",
            target="Vs narrow polar 3-bet continue range (AA/KK/QQ/AK), never x/r second-best — call-down or check-fold instead",
            leak="L4 — x/r with JJ/TT folds out only what Hero beats; keeps in everything that crushes",
        ),
        tags=assemble_tags(
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="3BP", players="HU", position="OOP",
            extra=["L4", "PolarRange", "Deep"],
        ),
        fh_hero="UTG,UTG+1,MP,LJ,HJ,CO,BTN,SB,BB", fh_opponent="",
        depth=depth, gametype=gametype,
        fh_start_spot="flop", fh_actions="",
        fh_trainer_mode="stop_end_of_hand",
        fh_trainer_game_speed="normal",
        fh_groups=RANGE_ALL,
    )


def leak_L5_low_dry_ip_hu_cbet() -> Drill:
    """L5 — Low-dry IP HU under-c-bet as PFR."""
    depth = depth_to_str(50)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "L5 low-dry IP HU c-bet target 60-80% (Hero 33%)",
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="SRP", pos_or_players="IP-HU",
        ),
        description=build_description(
            setup="Hero IP HU as PFR. Flop is low-dry rainbow (top card ≤ 8, no flush, no straight draw)",
            target="60-80% c-bet small (B25-B33) — Dave's Q-series range-bet target on this texture",
            leak="L5 — Hero c-bets only 33% of these spots (chronic passivity, surrenders range advantage)",
        ),
        tags=assemble_tags(
            fh_start_spot="flop", depth_str=depth, gametype=gametype,
            pot_type="SRP", players="HU", position="IP",
            extra=["L5", "PFR", "LowDry", "RangeBet"],
        ),
        fh_hero="BTN,CO,HJ", fh_opponent="UTG,UTG+1,MP,LJ,HJ,CO,SB,BB",
        depth=depth, gametype=gametype,
        fh_start_spot="flop", fh_actions="",
        fh_trainer_mode="stop_end_of_street",
        fh_trainer_game_speed="fast", fh_trainer_autoplay="3_sec",
        fh_groups=RANGE_ALL,
        flop_suits="rainbow", flop_paired="unpaired", flop_high_card="8",
    )


def leak_short_stack_push_fold() -> Drill:
    """<12bb push/fold discipline — Dave's J-series short-stack rules."""
    depth = depth_to_str(10)
    gametype = "MTTGeneral"
    return Drill(
        name=make_drill_name(
            "Short-stack push/fold discipline (10bb EP-CO)",
            fh_start_spot="preflop", depth_str=depth, gametype=gametype,
            pot_type="SRP", pos_or_players="EP",
        ),
        description=build_description(
            setup="Single-spot push/fold drill from UTG-CO at 10bb",
            target="J-series short-stack ranges — open-shove or fold cleanly, no postflop play",
            leak="Maintenance drill — keeps short-stack discipline sharp between sessions",
        ),
        tags=assemble_tags(
            fh_start_spot="preflop", depth_str=depth, gametype=gametype,
            pot_type="SRP", players="-", extra=["EP", "PushFold", "J-series"],
        ),
        fh_hero="UTG,UTG+1,LJ,HJ,CO", fh_opponent="",
        depth=depth, gametype=gametype, depth_list="10.125",
        fh_start_spot="preflop", fh_actions="StartOfHand",
        fh_trainer_mode="stop_after_action",
        fh_trainer_game_speed="turbo",
        fh_groups=RANGE_EP_PUSH,
    )


def diagnostic_newline_test() -> Drill:
    """
    Diagnostic drill — tests whether GTOW renders any form of line break
    in the description. If any of the markers below render on their own
    line in the GTOW UI, that's the character we should switch to for
    real descriptions. If none render, the ▸ section markers remain
    the best we can do.
    """
    return Drill(
        name="DIAGNOSTIC: newline rendering test (delete after testing)",
        description=(
            "If you see this on ONE line, no break renders. "
            "Below: 5 different break candidates — note which (if any) "
            "create an actual line break in the UI: "
            "[A]\nplain-LF "
            "[B]\n\ndouble-LF "
            "[C]\r\nCRLF "
            "[D]\u2028U+2028-LSEP "
            "[E]\u2029U+2029-PSEP "
            "[F]<br>HTML-br "
            "[end]"
        ),
        tags=[],
        fh_hero="", depth=depth_to_str(100), gametype="MTTGeneral",
        fh_start_spot="preflop", fh_actions="StartOfHand",
        fh_trainer_mode="stop_end_of_hand",
        fh_groups=RANGE_ALL,
    )


LEAK_REGISTRY = {
    # Confirmed Hero leaks from memory
    "J29": (leak_J29_sb_bvb, "SB BvB raise/limp/fold distribution (J29)"),
    "CALLER_IP_AGG": (leak_caller_ip_flop_agg, "Caller IP flop aggression below target"),
    "ONE_AND_DONE": (leak_one_and_done, "One-and-done turn barrel frequency"),
    "OOP_PFR_XCXC": (leak_oop_pfr_xc_xc_showdown, "Check-call-call-showdown OOP as PFR"),
    "MID_PAIRS": (leak_mid_pairs_66_99, "Mid pairs 66-99 underperforming"),
    "BLIND_3BET": (leak_3bet_construction_blinds, "3-bet construction from blinds"),
    # L-series from Knockman_Leaks_Index.md
    "L1": (leak_L1_bb_cr_overcommit, "BB CR overcommit on equity-killing turns"),
    "L3": (leak_L3_multiway_3bp_overjam, "Multi-way 3BP over-jamming (flatter caps to QQ+/AK)"),
    "L4": (leak_L4_polar_3bet_xr_oop, "Polar 3-bettor x/r OOP with second-best"),
    "L5": (leak_L5_low_dry_ip_hu_cbet, "Low-dry IP HU under-c-bet"),
    "RIVER_BLUFF_NO_BLOCKER": (leak_river_bluff_no_blocker, "River no-blocker overbet jam discipline (III.1 punts)"),
    # Skill maintenance
    "PUSHFOLD": (leak_short_stack_push_fold, "Short stack push/fold maintenance"),
    # Diagnostic
    "DIAG_NEWLINE": (diagnostic_newline_test, "DIAGNOSTIC: test if GTOW renders any newline character"),
}


# ============================================================================
# SQUARES → DRILL
# ============================================================================

def drill_from_pf_square(square: Dict[str, Any], hands_in_square: List[Dict]) -> Drill:
    """
    Build a drill from a preflop square. Square ID is PF_<pos>_<bucket>_<node>.
    The node tells us where Hero is in the action tree; we set up the drill
    to put Hero in that exact decision context.
    """
    sid = square["square_id"]
    parts = sid.split("_")
    pos = parts[1]
    stack_bucket = parts[2]
    node = "_".join(parts[3:])

    depth_bb = STACK_BUCKET_TO_DEPTH_BB.get(stack_bucket, 100)
    depth = depth_to_str(depth_bb)
    n = square.get("n_total", len(hands_in_square))
    ev = square.get("net_bb_mean", 0)
    gametype = "MTTGeneral"   # preflop squares are chip-EV by default

    # For 3-bet, cold-call, and faced_3bet nodes we want to know who opened.
    opener = ""
    if hands_in_square:
        c = Counter(h.get("opener_position") for h in hands_in_square if h.get("opener_position"))
        if c:
            opener = ",".join(p for p, _ in c.most_common(3))

    # Map node → pot type tag
    pot_type = {
        "RFI": "SRP",
        "cold_call": "SRP",
        "3bet": "3BP",
        "4bet_plus": "4BP",
        "faced_3bet_as_opener": "3BP",
        "call_jam": "All-in",
        "hero_jams": "All-in",
    }.get(node, "SRP")

    body = f"Sq:{sid} (n={n}, EV={ev:+.2f}BB) — {node} from {pos}"
    name = make_drill_name(
        body=body,
        fh_start_spot="preflop", depth_str=depth, gametype=gametype,
        pot_type=pot_type, pos_or_players=pos,
    )
    description = (
        f"Auto-generated from GEM square {sid}. n={n}, mean EV={ev:+.2f} BB. "
        f"Drill exposes the recurring decision in this square's shape."
    )
    if opener and node in ("cold_call", "3bet", "faced_3bet_as_opener"):
        description += f" Common opener positions in sample: {opener}."

    tags = assemble_tags(
        fh_start_spot="preflop", depth_str=depth, gametype=gametype,
        pot_type=pot_type, players="-",
        extra=["Squares", pos, node],
    )

    drill = Drill(
        name=name,
        description=description,
        tags=tags,
        fh_hero=pos,
        depth=depth, gametype=gametype,
        fh_start_spot="preflop",
        fh_actions="StartOfHand",
        fh_trainer_mode="stop_end_of_hand",
        fh_groups=RANGE_ALL if depth_bb >= 25 else RANGE_EP_PUSH,
    )
    if opener and node in ("cold_call", "3bet", "faced_3bet_as_opener"):
        drill.fh_opponent = opener
    # Short stacks → push/fold UI feel
    if depth_bb < 15:
        drill.fh_trainer_mode = "stop_after_action"
        drill.fh_trainer_game_speed = "turbo"
    return drill


def drill_from_postf_square(square: Dict[str, Any], hands_in_square: List[Dict]) -> Drill:
    """
    Build a drill from a postflop square. ID is
    PostF_<IP|OOP>_<pot>_<spr>_<phase>.
    """
    sid = square["square_id"]
    parts = sid.split("_")
    pos_class = parts[1]
    pot_type = parts[2]
    spr_bucket = parts[3]
    phase = "_".join(parts[4:])

    n = square.get("n_total", len(hands_in_square))
    ev = square.get("net_bb_mean", 0)

    # SPR + pot type imply a depth: 3BP at SPR 1-3 means very deep relative to
    # a small SRP at the same SPR. We approximate with a depth that produces
    # roughly that SPR after typical preflop action.
    if pot_type == "3BP":
        depth_bb = 60 if spr_bucket in ("3-7", "7+") else 30
    elif pot_type == "4BP":
        depth_bb = 100   # 4BP only deep makes sense — short stacks would be all-in
    else:  # SRP
        depth_bb = {"<1": 15, "1-3": 25, "3-7": 50, "7+": 100}.get(spr_bucket, 60)
    depth = depth_to_str(depth_bb)

    gametype = ICM_PHASE_TO_GAMETYPE.get(phase, "MTTGeneral")

    # Common Hero position in the square — used as fh_hero so the trainer
    # routes Hero to the typical seat. Empty string → all positions.
    hero_pos = ""
    if hands_in_square:
        c = Counter(h.get("position") for h in hands_in_square if h.get("position"))
        if c:
            hero_pos = ",".join(p for p, _ in c.most_common(3))

    body = f"Sq:{sid} (n={n}, EV={ev:+.2f}BB) — {pos_class} {pot_type} SPR-{spr_bucket}"
    name = make_drill_name(
        body=body,
        fh_start_spot="flop", depth_str=depth, gametype=gametype,
        pot_type=pot_type, pos_or_players=f"{pos_class}-HU",
    )
    description = (
        f"Auto-generated from GEM square {sid}. n={n}, mean EV={ev:+.2f} BB. "
        f"{pos_class} {pot_type} at SPR {spr_bucket} during {phase}. "
        f"Drill starts on flop and plays out the postflop tree."
    )
    tags = assemble_tags(
        fh_start_spot="flop", depth_str=depth, gametype=gametype,
        pot_type=pot_type, players="HU", position=pos_class,
        extra=["Squares", f"SPR-{spr_bucket}", phase],
    )

    drill = Drill(
        name=name,
        description=description,
        tags=tags,
        fh_hero=hero_pos,
        depth=depth,
        gametype=gametype,
        fh_start_spot="flop",
        fh_actions="",
        fh_trainer_mode="stop_end_of_hand",
        fh_trainer_game_speed="normal",
        fh_groups=RANGE_ALL,
    )
    return drill


def drill_from_square(square: Dict[str, Any], hands_by_square: Dict[str, List[Dict]]) -> Optional[Drill]:
    """Dispatch square → preflop or postflop drill builder."""
    sid = square["square_id"]
    hands = hands_by_square.get(sid, [])
    if sid.startswith("PF_"):
        return drill_from_pf_square(square, hands)
    if sid.startswith("PostF_"):
        return drill_from_postf_square(square, hands)
    return None


def is_actionable_square(sid: str) -> bool:
    """Same gate as gem_squares_gtow — exclude structural-fold squares."""
    if sid.startswith("PostF_"):
        return True
    parts = sid.split("_")
    if len(parts) < 4:
        return False
    node = "_".join(parts[3:])
    return node not in ("fold", "walked", "other")


# ============================================================================
# WRITER
# ============================================================================

def write_drills(drills: List[Drill], output_path: str,
                 date_prefix: bool = True,
                 date_str: Optional[str] = None,
                 start_number: int = 1) -> None:
    """
    Serialize drills to a .txt file. One JSON object per line, blank-line
    separators (matches GTOW's export format).

    date_prefix: if True (default), prepend '<YYMMDD>_<NN> ' to each drill
      name so generated drills sort chronologically in My Drills.
    date_str: override the date string (format YYMMDD). Default: today.
    start_number: counter starting value (default 1). Useful when chaining
      batches generated on the same day.
    """
    if date_prefix and date_str is None:
        date_str = _date.today().strftime("%y%m%d")
    lines = []
    for i, d in enumerate(drills):
        obj = d.to_dict()
        if date_prefix:
            obj["name"] = f"{date_str}_{start_number + i:02d} {obj['name']}"
        lines.append(json.dumps(obj, separators=(",", ":")))
    sep = "\n\n\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(sep.join(lines))
        f.write("\n")


# ============================================================================
# CLI
# ============================================================================

def cmd_list_leaks() -> None:
    print(f"Available leak drill codes (gem_drill_export v{VERSION}):")
    print()
    for code, (_, desc) in LEAK_REGISTRY.items():
        print(f"  {code:18s}  {desc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=f"GEM drill export v{VERSION}")
    ap.add_argument("--leaks", default="",
                    help="Comma-separated leak codes (e.g. 'J29,L1,L5'). See --list-leaks.")
    ap.add_argument("--list-leaks", action="store_true",
                    help="List available leak codes and exit.")
    ap.add_argument("--squares", default=None,
                    help="Path to gem_squares.json. Generates drills from top squares.")
    ap.add_argument("--hands", default=None,
                    help="Path to gem_hands_lean.json. Required with --squares.")
    ap.add_argument("--top", type=int, default=8,
                    help="Top N actionable squares (default: 8).")
    ap.add_argument("--output", default="gtow_drills.txt",
                    help="Output .txt file path.")
    ap.add_argument("--date", default=None,
                    help="Date prefix (YYMMDD format, e.g. 260519). Default: today.")
    ap.add_argument("--start-number", type=int, default=1,
                    help="Counter starting value (default 1).")
    ap.add_argument("--no-date-prefix", action="store_true",
                    help="Skip the '<YYMMDD>_<NN> ' name prefix entirely.")
    args = ap.parse_args()

    if args.list_leaks:
        cmd_list_leaks()
        return 0

    drills: List[Drill] = []

    # Leak-based
    if args.leaks:
        for code in [c.strip() for c in args.leaks.split(",") if c.strip()]:
            if code not in LEAK_REGISTRY:
                print(f"WARN: unknown leak code '{code}' — skipping. "
                      f"Use --list-leaks to see options.", file=sys.stderr)
                continue
            builder, _ = LEAK_REGISTRY[code]
            drills.append(builder())

    # Squares-based
    if args.squares:
        if not args.hands:
            print("ERROR: --squares requires --hands.", file=sys.stderr)
            return 2
        with open(args.squares) as f:
            squares_data = json.load(f)
        with open(args.hands) as f:
            hands = json.load(f)
        # Re-bucket hands by square id (matches gem_squares assignment logic)
        from collections import defaultdict
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from gem_squares import assign_preflop_square, assign_postflop_square
        except ImportError:
            print("ERROR: gem_squares.py not importable — needed for hand bucketing. "
                  "Make sure both modules are in the same dir.", file=sys.stderr)
            return 2
        hands_by_square: Dict[str, List[Dict]] = defaultdict(list)
        for h in hands:
            pf = assign_preflop_square(h)
            po = assign_postflop_square(h)
            if pf:
                hands_by_square[pf].append(h)
            if po:
                hands_by_square[po].append(h)

        squares = squares_data.get("squares", [])
        actionable = [s for s in squares if is_actionable_square(s["square_id"])]
        actionable.sort(key=lambda s: -s.get("study_score", 0))
        for sq in actionable[: args.top]:
            d = drill_from_square(sq, hands_by_square)
            if d:
                drills.append(d)

    if not drills:
        print("ERROR: no drills built. Pass --leaks and/or --squares.", file=sys.stderr)
        return 2

    write_drills(
        drills, args.output,
        date_prefix=not args.no_date_prefix,
        date_str=args.date,
        start_number=args.start_number,
    )
    print(f"Wrote {len(drills)} drill(s) to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
