"""
gem_auto_verdict.py — Bucket 1 automatable verdict rules (HIGH confidence).

Each rule takes (hand, stats, eai) and returns:
    {"verdict": str, "argument": str, "confidence": "HIGH",
     "rule": str, "role": str|None}
or None if the rule does not apply.

The dispatcher runs rules in priority order and returns the FIRST match.
Order matters: noise-suppress and explicit detector flags are checked before
the equity-driven all-in rules, and the winner/no-flag catch is last.

Data fields consumed (all already produced by the parser/analyzer except where
noted as a REQUESTED enhancement):
    hand['pf_allin']          bool
    hand['went_to_sd']        bool
    hand['pf_action']         'raise'|'3bet'|'call'|'fold'|'jam'
    hand['first_in']          bool
    hand['hero_faced_raise']  bool
    hand['villain_jammed']    bool
    hand['eff_stack_bb']      float   (effective stack — min of hero/shortest active villain)
    hand['net_bb']            float
    hand['hand_strength']     str
    hand['matchups']          {villain_id: {hero_cards, villain_cards}}   (showdown only)
    hand['tournament_phase']  'late_reg'|'bubble_zone'|'post_bubble'|'final_table'|...
    hand['icm_context']       {near_bubble, bounty_covers_villain, ...}
    flag (mistake_type / detector flag, e.g. 'Missed Steal (CLEAR)', 'M1 ...')

    eai['hero_equity']        float   realized all-in equity (REQUESTED: also populate
                                      for POSTFLOP all-ins, not just preflop; fall back
                                      to computing from hand['matchups'] when present)

    stats[...]                position open ranges / push ranges (membership checks)

NOISE_FLOOR_BB = 0.20   # project EV noise threshold (sub-0.2BB deltas are not findings)
FLIP_LO, FLIP_HI = 0.40, 0.60
CALL_PRICED_EQ = 0.45   # caller-of-jam threshold for "priced-in flip" (HIGH)
PUSH_DEPTH_MAX = 15     # eff stack at/below which an open-shove is a pure push/fold spot
"""

NOISE_FLOOR_BB = 0.20
FLIP_LO, FLIP_HI = 0.40, 0.60
CALL_PRICED_EQ = 0.45
PUSH_DEPTH_MAX = 15


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def hero_role(hand):
    """Classify hero's preflop role in an all-in pot.

    Distinguishes the three situations whose verdicts diverge at the same
    equity: an open-shove (wide range, called by better = standard), a 3-bet
    jam (aggressor, low eq = ran into top of range = cooler), and calling a
    jam (a CHOICE to commit, low eq = loose call unless priced/bounty).
    """
    pa = hand.get("pf_action")
    if hand.get("villain_jammed") and pa in ("call", "3bet") and not hand.get("first_in"):
        return "caller_vs_jam"
    if pa == "call":
        return "caller"
    if pa == "3bet" or hand.get("hero_3bet"):
        return "threebet_jam"
    if pa in ("raise", "jam") and hand.get("first_in"):
        return "open_shove"
    if pa == "fold":
        return "folder"
    return "other"


def allin_equity(hand, eai):
    """Realized all-in equity. Prefer the eai field; fall back to computing
    from known showdown holecards in hand['matchups'] via phevaluator.

    REQUESTED ENHANCEMENT: populate eai['hero_equity'] for POSTFLOP all-ins too.
    Right now it is null for postflop stack-offs, which forces those hands into
    the wrong bucket (see TM6031278832/TM6032579578 this session).
    """
    eq = (eai or {}).get("hero_equity")
    if eq is not None:
        return eq
    mm = hand.get("matchups") or {}
    if mm:
        return compute_equity_from_matchups(hand)   # phevaluator vs known villain cards
    return None


def icm_override_active(hand):
    """True if bubble/FT ICM pressure could legitimately justify a fold that
    would otherwise be a 'missed steal' or change a get-in verdict."""
    phase = hand.get("tournament_phase", "")
    ic = hand.get("icm_context") or {}
    return phase in ("bubble_zone", "final_table") or ic.get("near_bubble", False)


# ---------------------------------------------------------------------------
# RULES (return dict or None). Dispatcher applies them in this order.
# ---------------------------------------------------------------------------
def rule_R0_noise_suppress(hand, stats, eai, flag="") -> dict | None:
    """Marginal missed-steal below the EV noise floor → suppress, no verdict."""
    if "marginal" in flag.lower() and "steal" in flag.lower():
        if abs(hand.get("net_bb", 0)) < NOISE_FLOOR_BB:
            return {"verdict": "SUPPRESS", "rule": "R0_noise", "confidence": "HIGH",
                    "role": None,
                    "argument": "Sub-0.2BB missed steal — collapsed to a count, "
                                "below the EV noise floor."}
    return None


def rule_R1_missed_steal_clear(hand, stats, eai, flag="") -> dict | None:
    """CO/BTN fold of a hand inside the position open-range, no ICM override."""
    if "clear" in flag.lower() and "steal" in flag.lower():
        if not icm_override_active(hand):
            return {"verdict": "III.2", "rule": "R1_missed_steal_clear",
                    "confidence": "HIGH", "role": hero_role(hand),
                    "argument": "Folded a hand inside the position open range with "
                                "no ICM override — a clear missed steal."}
        # ICM could justify the fold → demote to analyst
        return None
    return None


def rule_R2_open_shove_push(hand, stats, eai) -> dict | None:
    """First-in open-shove at <=15BB inside the push range. Wide range called
    by a tighter one = standard; result (incl. low realized eq) is variance."""
    if not (hand.get("pf_allin") and hand.get("went_to_sd")):
        return None
    if hero_role(hand) != "open_shove" or hand.get("eff_stack_bb", 99) > PUSH_DEPTH_MAX:
        return None
    if not in_push_range(hand, stats):          # range membership at exact depth/position
        return None                              # outside push range → analyst (could be a punt)
    return {"verdict": "III.5", "rule": "R2_open_shove_push", "confidence": "HIGH",
            "role": "open_shove",
            "argument": "Short-stack open-shove inside the push range — standard, "
                        "the result is variance."}


def rule_R3_R4_threebet_jam(hand, stats, eai) -> dict | None:
    """Hero is the 3-bet jammer. Equity splits the verdict:
       eq >= 0.40  → III.5 (near-flip get-in, standard)
       eq <  0.40  → I.7  (ran into the narrow top of the calling range = cooler)."""
    if not (hand.get("pf_allin") and hand.get("went_to_sd")):
        return None
    if hero_role(hand) != "threebet_jam":
        return None
    eq = allin_equity(hand, eai)
    if eq is None:
        return None
    if eq >= FLIP_LO:
        return {"verdict": "III.5", "rule": "R3_3betjam_flip", "confidence": "HIGH",
                "role": "threebet_jam",
                "argument": "3-bet jam taken as a near-flip inside the jamming "
                            "range — standard get-in."}
    return {"verdict": "I.7", "rule": "R4_3betjam_cooler", "confidence": "HIGH",
            "role": "threebet_jam",
            "argument": "3-bet jam that ran into the narrow top of villain's "
                        "calling range — a structural cooler."}


def rule_R5_call_jam_priced(hand, stats, eai) -> dict | None:
    """Hero CALLED a jam as a near-flip with the price (eq >= 0.45). HIGH.
    Below 0.45 this does NOT fire — that path is the MEDIUM R6 (analyst confirms
    pot-odds/bounty), because calling sub-flip is a choice, not a forced get-in."""
    if not (hand.get("pf_allin") and hand.get("went_to_sd")):
        return None
    if hero_role(hand) not in ("caller", "caller_vs_jam"):
        return None
    eq = allin_equity(hand, eai)
    if eq is None or eq < CALL_PRICED_EQ:
        return None
    return {"verdict": "III.5", "rule": "R5_call_jam_priced", "confidence": "HIGH",
            "role": "caller_vs_jam",
            "argument": "Called the jam getting the right price as a near-flip — "
                        "standard, lost to variance."}


def rule_R14_fold_to_4bet(hand, stats, eai) -> dict | None:
    """Disciplined fold of a non-premium hand to a 4-bet at <20BB. No showdown,
    no equity needed. III.3 cleared (standard laydown)."""
    if hand.get("pf_allin") or hand.get("went_to_sd"):
        return None
    if hero_role(hand) != "folder" or not hand.get("hero_faced_raise"):
        return None
    if hand.get("eff_stack_bb", 99) >= 20:
        return None
    if not folded_to_4bet(hand):                 # pf_raise sequence shows hero open -> villain 4bet -> hero fold
        return None
    if hand_in_premium_4bet_call_range(hand, stats):  # if hero SHOULD have continued, it's a leak → analyst
        return None
    return {"verdict": "III.3", "rule": "R14_fold_to_4bet", "confidence": "HIGH",
            "role": "folder",
            "argument": "Folded a non-premium holding to a 4-bet at short depth — "
                        "a standard, disciplined laydown."}


def rule_R10_winner_no_flag(hand, stats, eai) -> dict | None:
    """Winning hand with no detector flag → no negative verdict required.
    Guard against lucky all-in wins (won as a big dog) so they aren't silently
    cleared — those route to III.5 (or analyst) instead."""
    if hand.get("net_bb", 0) <= 0:
        return None
    if has_any_mistake_flag(hand):
        return None
    eq = allin_equity(hand, eai)
    if eq is not None and eq < 0.35:
        return None    # lucky win — let an all-in rule or analyst handle it
    return {"verdict": "NO-FLAG", "rule": "R10_winner", "confidence": "HIGH",
            "role": None,
            "argument": "Winning hand, no detector flag — no negative verdict "
                        "required (III.8 Pick remains a curated decision)."}


# ---------------------------------------------------------------------------
# MEDIUM-confidence proposers (Bucket 2) — emit a verdict but tag needs_confirm
# ---------------------------------------------------------------------------
def rule_R6_call_jam_lowEq(hand, stats, eai) -> dict | None:
    """Hero called a jam BELOW flip equity. Propose I.7 cooler, but the real
    verdict depends on pot-odds and bounty credit — promote to HIGH only when
    required_equity_by_decision (REQUESTED) and bounty-adjusted requirement are
    attached. Without them, analyst confirms."""
    if not (hand.get("pf_allin") and hand.get("went_to_sd")):
        return None
    if hero_role(hand) not in ("caller", "caller_vs_jam"):
        return None
    eq = allin_equity(hand, eai)
    if eq is None or eq >= CALL_PRICED_EQ:
        return None
    return {"verdict": "I.7", "rule": "R6_call_jam_lowEq", "confidence": "MEDIUM",
            "role": "caller_vs_jam", "needs_confirm": True,
            "argument": "Called a jam below flip equity — proposed cooler; confirm "
                        "the pot odds (and any bounty credit) made the call correct."}


def rule_R9_m1(hand, stats, eai, flag="") -> dict | None:
    """M1 missed delayed c-bet flagged. Propose III.2; promote to HIGH when the
    solver EV delta (aggressive vs passive line) is attached and confirms the
    leak magnitude."""
    if "m1" in flag.lower() or "delayed c-bet" in flag.lower():
        return {"verdict": "III.2", "rule": "R9_m1", "confidence": "MEDIUM",
                "role": None, "needs_confirm": True,
                "argument": "Missed turn delayed c-bet (M1) — proposed III.2; "
                            "confirm against the solver EV delta."}
    return None


# ---------------------------------------------------------------------------
# DISPATCHER
# ---------------------------------------------------------------------------
HIGH_RULES = [
    rule_R0_noise_suppress,        # flag-aware
    rule_R1_missed_steal_clear,    # flag-aware
    rule_R2_open_shove_push,
    rule_R3_R4_threebet_jam,
    rule_R5_call_jam_priced,
    rule_R14_fold_to_4bet,
    rule_R10_winner_no_flag,       # last: only fires if nothing else claimed the hand
]
MEDIUM_RULES = [
    rule_R6_call_jam_lowEq,
    rule_R9_m1,                    # flag-aware
]


def auto_classify(hand, stats, eai, flag="") -> dict:
    """Return the first matching verdict, tagging bucket by confidence.
    Falls through to {'bucket':'B3'} (requires analyst) if nothing matches."""
    for rule in HIGH_RULES:
        try:
            r = rule(hand, stats, eai, flag) if _takes_flag(rule) else rule(hand, stats, eai)
        except TypeError:
            r = rule(hand, stats, eai)
        if r:
            r["bucket"] = "B1"
            return r
    for rule in MEDIUM_RULES:
        r = rule(hand, stats, eai, flag) if _takes_flag(rule) else rule(hand, stats, eai)
        if r:
            r["bucket"] = "B2"
            return r
    return {"bucket": "B3", "verdict": None, "confidence": "LOW",
            "rule": "R11_postflop",
            "argument": "Multi-street / villain-range-dependent decision — "
                        "requires analyst review."}


# Stubs to be implemented against the live schema:
#   compute_equity_from_matchups(hand)        -> float  (phevaluator vs showdown cards)
#   in_push_range(hand, stats)                -> bool   (Poker_Ranges_Text PUSH charts by depth/pos)
#   folded_to_4bet(hand)                      -> bool   (pf_sequence: open -> villain 4bet -> hero fold)
#   hand_in_premium_4bet_call_range(hand,...) -> bool
#   has_any_mistake_flag(hand)                -> bool
#   _takes_flag(rule)                         -> bool   (rule signature introspection)
