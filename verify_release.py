#!/usr/bin/env python3
"""
GEM v8.9.0 Release Integrity Verifier

Run AFTER copying files to the project to confirm nothing is stale or missing.
Usage:
    python verify_release.py                         # verify project files match release
    python verify_release.py --generate              # regenerate manifest from release folder
    python verify_release.py --project-dir /path     # verify a specific project directory
"""
import hashlib, os, sys, json

VERSION = "v8.16.4"   # v8.16.4 (Review Precision & Decision-Trust hotfix: reviewed-row layout, sticky nav re-measure, NEW gem_review_trust pure helpers [why-review/verdict-reconcile/allin-math/multiway/bounty-provenance/attribution], gem_ranges range-highlight + Range Lens pruning)

# Manifest: relative_path -> (sha256, size_bytes, one-line purpose)
# Generated from the release folder. If a file doesn't match, the copy is stale.
MANIFEST = {
    "GEM_Changelog.txt": ("202be7154a216a25fc4d5899b50b72e80a2197b7d6f1b757715867ac3c6cb0b1", 121665, "v8.16.4 Review Precision & Decision-Trust Hotfix entry (+ DTI live-path blockers 1+2)"),
    "GEM_Quick_Reference.txt": ("e64b74b80bebeba3e374a723dcfe78e19ed03aa3cfd31940be2144e53d1efe99", 101982, "quick reference (whitespace-trimmed)"),
    "Poker_Ranges_Text.txt": ("a90713804a5a0a5cb8872e1f61807afdc2e84e12c13c10d35edf44498cd443d1", 107309, "v8.12.0 D1: wrong-node SBD_* block QUARANTINED"),
    "SESSION_START_STEP0_package_rebuild.txt": ("302a6522a8d4be8eb4c2d3efd5c314a2d392a8a5925c8019e5aa4cc2ab6da60b", 4167, "v8.16.4: 42 files, 412 canaries"),
    "_gtow_situations.json": ("cc93b265fd8a90872ac951fd713d408a6156e0efc4264c45b48b48fa00c36449", 354785, "v8.12.0a: curated GTOW stacks lookup (enables stacks= param)"),
    "_test_scratch.py": ("b4ea61b605503675c211abd105c11bfb878aa439d2a70acdf58fe219e62fff98", 518848, "v8.17 B6/B7: +T-PKO817-01..07 (how-PKO-changes-the-decision + 4-state provenance)"),
    "coaching_rules.json": ("9fdecf6ef5143d000e81874837b5f871f1d03ff30b30f52128d614f69ca7f045", 4953, "v8.12.0a: +N14-N18 Amit rules"),
    "gem_analyst_villain.py": ("a1f16e0a81caeff7212561f71e01b10884cb28fca35e15dc55d90368107f54c7", 22675, "v8.14.1 hotfix: worksheet pipeline_version from RUNTIME_VERSION"),
    "gem_analyst_worklist.py": ("f056e11bcf6175277c42cd9ce15748e3d15ff981a7dce82a064440f74c9e02b1", 49450, "v8.16.4 DTI Obj4: additive why_contract (street+action+category) in worklist"),
    "gem_analyzer.py": ("b409e6afa1f97f16cf7a685748838034051686b84e19f934eb128f85e6d6ac69", 584897, "v8.16.4 DTI Obj5: validator Check 14 calls verdict_validation_issue"),
    "gem_chart_labels.py": ("888e5f961efcb47197e5ee3eaee3cd2bba7fab0a9eea4681a04a508784decdf2", 5554, "v8.14.4: + find_raw_chart_ids_in_user_text / humanize_raw_chart_ids (centralized raw-chart-ID guard)"),
    "gem_coaching_cards.py": ("9327a09b5edb2e1d7e384f592c2f4d4d61ed5c10f67c239aa4be09365901efa3", 47332, "v8.14.1 rev-3: not-collectible card reads canonical collectibility"),
    "gem_coverage_audit.py": ("1d8b610cc020b28deb242f0e0c2fd049fa2638a156d6513926d12b244d29cce4", 15323, "v8.12.2: G7-G10 registry + preflop_deviations fix"),
    "gem_coverage_builder.py": ("a7ac54b791b2fe103b6eac5e09cf09d7e48dbcba106231488496a7571f227780", 128365, "v8.14.1 REV5: re-jam key strips '+' + resolves at any depth (REJAM_MPvsUTG1, 72692569)"),
    "gem_eai_equity.py": ("4313ade454b4dd4f163b9576832d42ca28fdadffc406e7438558c32131b9abfb", 8687, "v8.9.9: except Exception + smoke value compare + MC comment fix"),
    "gem_gtow.py": ("680aa0c462e2cf2799c4946d7bdc898a6cb24dc11459ab10e4048cfe066d77a7", 32085, "v8.12.0a: builder v2.2.1 (verification-pass fixes + pf_settled gate)"),
    "gem_known_bugs.json": ("daa07f7d009b05eefe7e334748826da88ad9aa350ea75adda57398143f00d7e7", 46594, "v8.12.1: open bugs live; fixed history archived"),
    "gem_leak_watchlist.py": ("4d0b4c199374ab5604bd79b82ca727949b003186b05687a96f116ba632f168f0", 19406, "v8.12.4: aim clamp + thin-sample downgrade + bluff synthesis"),
    "gem_parser.py": ("81a255eddf4b5065c9b38d92c3e255571e455bf220d0171a1cb79485362a7735", 103111, "v8.12.0a B150: table_size = dealt players (+table_capacity)"),
    "gem_pko_research.py": ("6c56e998ab6c032739cfba79233ad65bd8ace933a3a41527433e7879ae0f7a9d", 55172, "v8.17 B6/B7: how_pko_changes_decision() + pko_trust_render exposes how_changes_md + reconciled facts"),
    "gem_pot_odds.py": ("52a01bccb5478f46cdbd253ca6b581f733fba2e551daef4e48d7cb17cceab5f0", 49529, "v8.12.8 QA3: folded-reveal exclusion + main-pot price"),
    "gem_tournament_model.py": ("c0cd004fbaddc981fe6e86b1e59f65a48589fb1b005084b40ac3d97739959c1e", 11955, "v8.15.0: typed event-level Tournament Tables model (SP-1)"),
    "gem_quality.py": ("4d8b8074d6c7b7ab067c10cabe053ac837ca78cf8f1d686e60e6fbd176790bc5", 31386, "v8.12.4: all-zeros learnings carry section detail"),
    "gem_report_data.py": ("e5a891a0d0ebdf91edba7ca9f48bfd56e1423583e7f95af17bcfbc83cf2cd1da", 224254, "v8.14.3 Issue 1: top-level financials canonicalised from parsed USD overlay (+total_ticket_value)"),
    "gem_report_draft/_hand_grid.py": ("d847cc12ea7770a561e335c8c317302b68fb858158e7025180508439f4b01865", 80499, "v8.14.1 rev-3: human chart labels + call-jam reconciled vs analyst + depth caveat"),
    "gem_report_draft/_helpers.py": ("6f2052a557d0ad966da0f666445f196379d69a22420b5a1072597fd8405eeab3", 65127, "v8.16.1 hotfix: call-vs-check wording + auto_verdict_needs_review (Bug 2a/2b)"),
    "gem_report_draft/_html.py": ("ce786c00caf803e04452b521df80264f5a48dc3bf89fb3fd3d3ee3e5bd80918b", 388724, "v8.16.4 Obj1/2/6: reviewed-row grid + queue ResizeObserver + range-highlight CSS"),
    "gem_report_draft/_state.py": ("c05440f911443532cdc76be5bce06918f90841c453fc4cd80ebe6c10e53c73c4", 4551, "v8.16.2 Phase B: _FULL_CARD_IDS dedup registry"),
    "gem_report_draft/draft.py": ("a3b6172e186d88f4fca4939dd2100d9e9d916104e00a32020209c494525823f8", 35268, "v8.16.2 Phase D: STT nav label -> Tournament Results"),
    "gem_report_draft/sections_financial.py": ("742454bb03cd349eef3c639ecf3076be68bdf8292ad7b97828dd87cf7f6801b7", 131012, "v8.14.3 Issue 1+2: cash+ticket basis footnote + large-loss verdict relabel when ANALYST_COMPLETE"),
    "gem_report_draft/sections_issue_explorer.py": ("677fc0b4c14e91373e8eb8f6d31a64feedc3269e85205663c56a77a41b006393", 50058, "v8.14.1 rev-4: humanize chart ids in rep-example deviation notes"),
    "gem_report_draft/sections_iv_xii.py": ("80520701383157257ee6d46e83fa35bb6f5033f3ea0c45dc8d037372ee5432ae", 225848, "v8.16.0 villain: matrix Teaching Signals wording"),
    "gem_report_draft/sections_mistakes.py": ("f50c6f85bdda88c506abe019aa323ec1ea0eb80068d2d5ba3b835c475e5a21ce", 123884, "v8.14.0 Slice E rev-2: PKO opportunity table rename (Opportunity/Wrong/Missed)"),
    "gem_report_draft/sections_tournaments.py": ("15c0e301521a6a4d64372cb6bf3fb36021451793a3adf46d348190196c0068d6", 8812, "v8.16.2 Phase D: Tournament Results title/strip/cEV polish"),
    "gem_report_draft/sections_xiii.py": ("553a2cda24c42d263a179289d3db66a892e27c3e03455163fbab96f33c7371eb", 68332, "v8.14.1 REV4: body shows true seat + labels short-table proxy chart (72807590)"),
    "gem_report_draft/sections_xiv.py": ("b194a660ac09a4d3f4df719c4c0547f348e1020aae76426afe8d579b31075f98", 221055, "v8.17 B6/B7: how-PKO-changes-the-decision coaching + 4-state provenance on BOTH XIV.A + XIV.B PKO pills"),
    "gem_report_draft/tldr.py": ("0b4f29698f408f8dac5b707b14e4a28dcd772a24028fb7b8e6f0a3256e49b157", 148637, "v8.16.4 DTI Blocker 1: build_review_queue routes through aggregate_review_queue (bounded + aggregated + internal-QA)"),
    "gem_report_lint.py": ("7f2f6c15a89f13b8f2e8cccfb868fbb7b480b27d82bb9a6b7d70c2a6fca3c5d8", 28188, "v8.9.8: P2-D lint finding visibility"),
    "gem_review_flags.py": ("826fcb7e119fa298bdc7dcc2c82d39e6cc618152804f2c85687bf9f24eaeffc2", 9665, "v8.12.2: +G6 check-raise review + P4 worksheet"),
    "gem_villain_intel.py": ("eb45c5eef2fb710270ea0559d1b68712bec1b0055460355b2fc847cb7532fa63", 117987, "v8.16.0 villain: timestamp chronology (Step 1) + loose_passive scorer fix"),
    "gem_villain_teaching.py": ("4c2f93996d8cf9bcc2a55aafcf11d9cb66e60b6822782f98c109aca76b3f0eda", 38644, "v8.16.0 villain: status-safe cards + grade gate + calibrated node-specific mixed/split caveat + ICM caution"),
    "gem_version.py": ("3ff7688f239fa7fca14058b3cfac4a505b364157de823f916206be19de66efe0", 880, "v8.16.4: RUNTIME_VERSION single source of truth"),
}

# Canary checks: specific strings that MUST be present in key files.
# These catch the exact failure modes this release fixes.
CANARIES = [
    # v8.11.0 version canary
    ("gem_report_draft/draft.py",
     'VERSION = "v8.12.0"',
     "version stamp"),
    ("gem_villain_intel.py",
     "_EXPLOIT_READ_MAP",
     "v8.8.3: detector-to-label mapping constant present"),
    ("gem_villain_intel.py",
     "VALID_EXPLOIT_READ_LABELS",
     "v8.8.3: valid labels constant present"),
    ("gem_villain_intel.py",
     "def _stamp_exploit_read(",
     "v8.8.3: stamp helper present"),
    ("gem_villain_intel.py",
     "'exploit_read_label'",
     "v8.8.3: exploit_read_label field in template"),
    ("gem_report_draft/sections_xiv.py",
     "exploit_read_label",
     "v8.8.3: JS serialization reads exploit_read_label"),
    ("gem_report_draft/sections_iv_xii.py",
     "exploit_read_label",
     "v8.8.3: Matrix grouping reads exploit_read_label"),
    ("gem_report_draft/sections_iv_xii.py",
     "_infer_read_label_from_text",
     "v8.8.3: legacy text fallback present for backward compat"),

    # v8.8.6 canaries
    ("gem_report_draft/draft.py",
     'VERSION = "v8.12.0"',
     "v8.11.0: version stamp"),
    ("gem_report_draft/_html.py",
     'initPerTournamentPnlTable',
     "v8.8.6 B2: P&L idempotent DOMContentLoaded init"),
    ("gem_report_draft/_html.py",
     'Bustouts',
     "v8.8.6 B6: Bustouts filter"),
    ("gem_report_draft/sections_financial.py",
     '_st_cev',
     "v8.8.6 B4: subtotal cEV/100 computation"),
    ("gem_report_draft/sections_xiv.py",
     'chipEV-only',
     "v8.8.6 S1: satellite caveat text"),
    ("gem_villain_intel.py",
     "_RANK_VAL",
     "v8.8.5: card rank sort constant present"),
    ("gem_villain_intel.py",
     "def _hand_context(",
     "v8.8.5: P0.3 hand context helper present"),
    ("gem_villain_intel.py",
     "'hero_position': hero_position",
     "v8.8.5: P0.3 context fields in _make_atom"),
    ("gem_villain_intel.py",
     "'dimension': a.get('dimension'",
     "v8.8.5: P0.1 dimension in popup serialization"),
    ("gem_villain_intel.py",
     "'assumption_source'",
     "v8.8.5: assumption_source field present"),
    ("gem_villain_intel.py",
     "'assumption_confidence'",
     "v8.8.5: assumption_confidence field present"),
    ("gem_report_draft/sections_xiv.py",
     "assumption_source",
     "v8.8.5: assumption_source serialized to JS"),
    ("gem_report_draft/sections_xiv.py",
     "perTournamentPnlRows",
     "v8.8.5: P&L rows serialized to JS"),
    ("gem_report_draft/_helpers.py",
     "'AMBIGUOUS', 'AMBIGUOUS_AGGRESSIVE'",
     "v8.8.5: vague diagnostic fix — AMBIGUOUS gates enumerated"),
    ("gem_parser.py",
     "'RACER'",
     "v8.8.5: RACER format detection"),

    # v8.8.6 V6 QA canaries
    ("gem_villain_intel.py",
     "_READ_EMOJI",
     "v8.8.6: emoji display lookup separated from canonical labels"),
    ("gem_villain_intel.py",
     "'exploit_read_display'",
     "v8.8.6: display field with emoji for exploit reads"),
    ("gem_villain_intel.py",
     "atom_word",
     "v8.8.6: atom/atoms grammar fix"),
    ("gem_report_draft/sections_xiii.py",
     "SATELLITE",
     "v8.8.6: satellite caveat in S17 deviation tables"),
    ("gem_report_draft/sections_iv_xii.py",
     "def _canon(",
     "v8.8.6: canonical label normalisation for Matrix grouping"),
    ("gem_report_draft/sections_xiv.py",
     "exploit_read_display",
     "v8.8.6: display label serialized to JS popup"),
    ("gem_report_draft/_html.py",
     "Number(r.roi)",
     "v8.8.6: Bustouts filter uses Number() for robustness"),

    # v8.8.6 S1-fix canaries: satellite caveat propagation to all 3 emit paths
    ("gem_report_draft/sections_xiv.py",
     "_xivb_fmt",
     "v8.8.6 S1-fix: XIV.B satellite format check"),
    ("gem_report_draft/sections_xiv.py",
     "_xivb_icm",
     "v8.8.6 S1-fix: XIV.B satellite ICM check"),
    ("gem_report_draft/sections_xiv.py",
     "_mda_expl = _mda_expl.replace(",
     "v8.8.6 S1-fix: MDA path satellite caveat substitution"),
    ("gem_report_draft/sections_xiv.py",
     "_d_fmt_xiv",
     "v8.8.6 S1-fix: deviation label satellite format check"),

    # v8.8.6 raise-size display canaries
    ("gem_report_draft/_hand_grid.py",
     "_current_bet = 1.0 if street ==",
     "v8.8.6: raise-size preflop bet level tracking"),
    ("gem_report_draft/_hand_grid.py",
     "'Open to'",
     "v8.8.6: preflop open label"),
    ("gem_report_draft/_hand_grid.py",
     "'3-bet to'",
     "v8.8.6: preflop 3-bet label"),
    ("gem_report_draft/_hand_grid.py",
     "_raise_to = _current_bet + amt",
     "v8.8.6: raise-to computation formula"),

    # v8.8.6 verdict chip canaries
    ("gem_report_draft/_html.py",
     "verdict-chip-row",
     "v8.8.6: verdict chip container in modal HTML"),
    ("gem_report_draft/_html.py",
     'data-verdict="Agree"',
     "v8.8.6: Agree verdict chip data attribute"),
    ("gem_report_draft/_html.py",
     "verdict-clear",
     "v8.8.6: Clear verdict button"),
    ("gem_report_draft/_html.py",
     "verdict-agree.active",
     "v8.8.6: verdict chip active state CSS"),

    # v8.8.6 VH+HA architecture canaries
    ("gem_villain_intel.py",
     "SIGNAL_COACHING",
     "v8.8.6 VH1: coaching map for atom signals"),
    ("gem_villain_intel.py",
     "_EXPLOIT_COACHING",
     "v8.8.6 VH1: coaching map for exploit detectors"),
    ("gem_villain_intel.py",
     "'suggests': SIGNAL_COACHING",
     "v8.8.6 VH1: coaching stamped on atoms"),
    ("gem_report_draft/draft.py",
     "handReferenceAudit",
     "v8.8.6 HA1: hand reference audit instrumentation"),
    ("gem_report_draft/draft.py",
     "handAvailability",
     "v8.8.6 HA1: per-hand availability state"),
    ("gem_report_draft/sections_xiv.py",
     "_build_hand_opponent_contexts",
     "v8.8.6 VH2: 4-bucket opponent context builder"),
    ("gem_report_draft/sections_xiv.py",
     "_classify_timing",
     "v8.8.6 VH2: timing classifier for trust requirement"),
    ("gem_report_draft/sections_xiv.py",
     "handOpponentContexts",
     "v8.8.6 VH2: serialized to JS"),
    ("gem_report_draft/_html.py",
     "opponent-coaching",
     "v8.8.6 VH3: coaching block container in modal"),
    ("gem_report_draft/_html.py",
     "handAvailability",
     "v8.8.6 HA2: three-state availability in popup"),
    ("gem_report_draft/_hand_grid.py",
     "villain_badges",
     "v8.8.6 VH4: villain badge parameter in grid"),
    ("gem_report_draft/sections_xiv.py",
     "_build_villain_badges",
     "v8.8.6 VH4: villain badge builder"),
    ("gem_report_draft/sections_xiv.py",
     "villain-street-notes",
     "v8.8.6 VH4: yellow street notes"),

    # v8.8.6 HA Phase 3 canaries
    ("gem_report_draft/_state.py",
     "_APPENDIX_HAND_PRIORITIES",
     "v8.8.6 HA3: priority dict in state"),
    ("gem_report_draft/_state.py",
     "def _register_hand_priority",
     "v8.8.6 HA3: priority registration accessor"),
    ("gem_report_draft/_helpers.py",
     "priority=2",
     "v8.8.6 HA3: default priority in registration functions"),
    ("gem_report_draft/draft.py",
     "handPriorityBudget",
     "v8.8.6 HA3: budget planner serialization"),
    ("gem_report_draft/draft.py",
     "_SOFT_CAP_KB",
     "v8.8.6 HA3: file size budget constant"),
    ("gem_report_draft/_html.py",
     "budget_trimmed",
     "v8.8.6 HA3: budget_trimmed state label"),
    ("gem_report_draft/sections_issue_explorer.py",
     "_register_hand_priority(hid, 0)",
     "v8.8.6 HA3: P0 Issue Explorer"),
    ("gem_report_draft/draft.py",
     "# P0: exploit hands",
     "v8.8.6 HA3-fix: exploit opportunity P0 registration"),
    ("gem_report_draft/sections_xiv.py",
     "atoms_by_hid = vi.get('atoms_by_hand'",
     "v8.8.6 VH2-fix: atoms_by_hand key for Bucket C"),
    ("gem_report_draft/_html.py",
     "cb-oneliner",
     "v8.8.6 VH gap-fill: top one-liner for exploit hands"),
    ("gem_report_draft/_html.py",
     "Read signal: ",
     "v8.8.6 VH gap-fill: suggests line in exploit blocks"),
    ("gem_report_draft/sections_xiv.py",
     "Actionable now?",
     "v8.8.6 VH gap-fill: actionability in yellow street notes"),
    ("gem_report_draft/sections_xiv.py",
     "vsn-suggests",
     "v8.8.6 VH gap-fill: structured street notes with badge"),
    ("gem_report_draft/sections_xiv.py",
     "_abh_xiv.get(hid, []) or _abh_xiv.get(hid_short, [])",
     "v8.8.6 hid-format fix: atoms_by_hand keyed by full hid, yellow notes try both"),
    ("gem_report_draft/_html.py",
     "_hocMap[_hocShort]",
     "v8.8.6 hid-format fix: JS modal coaching fallback to short hid"),

    # v8.8.6 inline table queue navigation canaries
    ("gem_report_draft/_html.py",
     "buildInlineHandQueueFromClickedRef",
     "v8.8.6 inline queue: main resolver function"),
    ("gem_report_draft/_html.py",
     "inline_table_group",
     "v8.8.6 inline queue: grouped table queue sourceType"),
    ("gem_report_draft/_html.py",
     "_inferQueueTitle",
     "v8.8.6 inline queue: title inference from table context"),
    ("gem_report_draft/_html.py",
     "_findLogicalHandQueueContainer",
     "v8.8.6 inline queue: container discovery with priority cascade"),
    ("gem_report_draft/_html.py",
     "data-hand-queue-id",
     "v8.8.6 inline queue: explicit queue ID data attribute"),
    ("gem_report_draft/sections_issue_explorer.py",
     "data-hand-queue-id",
     "v8.8.6 inline queue: IE rep tables emit queue metadata"),
    ("gem_report_draft/sections_issue_explorer.py",
     "data-hand-queue-title",
     "v8.8.6 inline queue: IE rep tables emit queue title"),

    # v8.9.0-prep LLM analyst handoff canaries
    ("gem_analyst_villain.py",
     "build_opponent_adjustment_candidates",
     "v8.9.0-prep: candidate builder public API"),
    ("gem_analyst_villain.py",
     "analyst_verdict",
     "v8.9.0-prep: analyst verdict field in schema"),
    ("gem_analyst_villain.py",
     "schema_version",
     "v8.9.0-prep: worksheet schema versioning"),
    ("gem_analyst_villain.py",
     "_stable_candidate_id",
     "v8.9.0-prep: collision-safe candidate ID generator"),
    ("gem_analyst_villain.py",
     "MAX_COACHING_CHARS",
     "v8.9.0-prep: coaching length limit (req I)"),
    ("gem_analyst_villain.py",
     "by_hand_villain",
     "v8.9.0-prep: convenience index for renderer lookup"),

    # v8.9.0-prep renderer integration canaries
    ("gem_report_draft/sections_xiv.py",
     "analyst_review=None",
     "v8.9.0-prep: analyst_review kwarg in context builder"),
    ("gem_report_draft/sections_xiv.py",
     "_find_analyst",
     "v8.9.0-prep: analyst lookup helper in context builder"),
    ("gem_report_draft/sections_xiv.py",
     "analyst_reviewed",
     "v8.9.0-prep: analyst overlay field on contexts"),
    ("gem_report_draft/sections_xiv.py",
     "analyst_learning",
     "v8.9.0-prep: upgraded atom bucket type"),
    ("gem_report_draft/sections_xiv.py",
     "analyst_villain_review",
     "v8.9.0-prep: review threaded from report_data"),
    ("gem_report_draft/_html.py",
     "cb-analyst",
     "v8.9.0-prep: analyst badge container in modal"),
    ("gem_report_draft/_html.py",
     "Analyst confirmed",
     "v8.9.0-prep: confirmed verdict badge text"),
    ("gem_report_draft/_html.py",
     "cb-fallback-label",
     "v8.9.0-prep req H: fallback label for non-reviewed"),
    ("gem_report_draft/_html.py",
     "analyst_learning",
     "v8.9.0-prep: learning opportunity bucket rendering"),
    ("gem_analyzer.py",
     "--analyst-villain-file",
     "v8.9.0-prep: CLI flag for analyst villain review file"),
    ("gem_analyzer.py",
     "--max-villain-candidates",
     "v8.9.0-prep: CLI flag for candidate budget"),
    ("gem_analyzer.py",
     "build_opponent_adjustment_candidates",
     "v8.9.0-prep: worksheet generation in pipeline"),
    ("gem_analyzer.py",
     "load_analyst_villain_review",
     "v8.9.0-prep: review loading before render"),

    # v8.8.7 canaries
    ("gem_report_draft/_state.py",
     "_BUDGET_TRIMMED_IDS",
     "v8.8.7: budget-trimmed IDs shared state"),
    ("gem_report_draft/sections_xiv.py",
     "budget-trimmed",
     "v8.8.7: XIV.C budget-trimmed anchor stubs"),
    ("gem_report_draft/_hand_grid.py",
     "== 'posts'",
     "v8.8.7: ante posts suppression in hand grid render"),

    # v8.8.8 canaries
    ("gem_analyzer.py",
     "all_hands = hands",
     "v8.8.8 BUG-1: PLO exclusion shadow variable"),
    ("gem_analyzer.py",
     "game_type_counts",
     "v8.8.8 BUG-1: game-type breakdown in volume metadata"),
    ("gem_report_draft/_html.py",
     "display:contents",
     "v8.8.8 PRD: mobile sticky header — topbar unwrapped on mobile"),
    ("gem_report_draft/_html.py",
     "--sticky-offset:50px",
     "v8.8.8 PRD: reduced mobile sticky offset for compact nav"),

    # v8.8.9 canaries (BUG-1/3/4/5/6 + V25 modal + keyboard navigation)
    ("gem_coverage_builder.py",
     "_in_rj = None",
     "v8.8.9 BUG-6: rejam range membership flag initialization (moved to coverage builder v8.9.9)"),
    ("gem_coverage_builder.py",
     "R4_3betjam_out_of_range",
     "v8.8.9 BUG-6: rejam out-of-range auto_rule (moved to coverage builder v8.9.9)"),
    ("gem_analyzer.py",
     "REJAM_",
     "v8.8.9 BUG-6: REJAM_ chart prefix search for 3-bet jam ranges"),
    ("gem_report_draft/_html.py",
     "ArrowLeft",
     "v8.8.9: keyboard arrow navigation in hand modal"),
    ("gem_report_draft/_html.py",
     "ArrowRight",
     "v8.8.9: keyboard arrow navigation forward in hand modal"),

    # v8.9.0 canaries (BUG-2: push/fold range-gated verdicts)
    ("gem_coverage_builder.py",
     "_PUSH_DEPTH_MAX = 25",
     "v8.9.0 BUG-2: extended push depth gate to 25BB (moved to coverage builder v8.9.9)"),
    ("gem_coverage_builder.py",
     "_STEAL_DEPTH_MAX = 15",
     "v8.9.0 BUG-2: separate missed-steal depth gate preserved at 15BB (moved to coverage builder v8.9.9)"),
    ("gem_coverage_builder.py",
     "R2_open_shove_out_of_range",
     "v8.9.0 BUG-2: R2 open-shove out-of-range auto_rule (moved to coverage builder v8.9.9)"),
    ("gem_coverage_builder.py",
     "_in_push = None",
     "v8.9.0 BUG-2: push range membership flag initialization (moved to coverage builder v8.9.9)"),
    ("gem_coverage_builder.py",
     "_POS_ALIAS",
     "v8.9.0 BUG-2: position alias map for 6-max/8-max chart lookup (moved to coverage builder v8.9.9)"),
    ("gem_coverage_builder.py",
     "No GTO jam range",
     "v8.9.0 BUG-2: no-jam-range detection for position at depth tier (moved to coverage builder v8.9.9)"),
    ("Poker_Ranges_Text.txt",
     "GTOW ChipEV 6-max JAM RANGES",
     "v8.9.0: GTOW jam range section header in range file"),
    ("Poker_Ranges_Text.txt",
     "PUSH_8BB_LJ",
     "v8.9.0: 8BB LJ push chart present"),
    ("Poker_Ranges_Text.txt",
     "JAM_12BB_CO",
     "v8.9.0: 12BB CO jam chart present"),
    ("Poker_Ranges_Text.txt",
     "JAM_20BB_BTN",
     "v8.9.0: 20BB BTN jam chart present"),
    ("Poker_Ranges_Text.txt",
     "JAM_25BB_SB",
     "v8.9.0: 25BB SB jam chart (only position that jams at 25BB)"),

    # Prior version canaries (inherited, must still hold)
    ("gem_opponent_profiler.py",
     "if vname == _hero:",
     "BUG-B: Hero exclusion guard"),
    ("gem_opponent_profiler.py",
     "_pf_voluntary = _pf_raisers | _pf_callers",
     "BUG-B: VPIP dedup (set union, not double-count)"),
    ("gem_analyzer.py",
     "report_data.get('analyst_commentary', {})",
     "BUG-A: fixed NameError (was _analyst_data)"),
    ("gem_made_hands.py",
     "paired_board = {r for r, n in bc.items() if n >= 2}",
     "v8.8.2: pocket pair on paired board reroute"),

    # v8.9.3 V25.4 QA canaries
    ("gem_report_draft/_html.py",
     "_syncV25StickyVars",
     "v8.9.3 P1-1: dynamic sticky CSS vars function"),
    ("gem_report_draft/_html.py",
     "scroll-margin-top",
     "v8.9.3 P1-2: street scroll-margin-top"),
    ("gem_report_draft/_html.py",
     "Mistake|Correct|Borderline|Flagged|Reviewed|Cleared|Punt",
     "v8.9.3 P1-3: metadata skip hardening"),
    ("gem_report_draft/_html.py",
     "vClone.querySelectorAll",
     "v8.9.3 P1-4: verdict xref stripping via clone"),
    ("gem_report_draft/_html.py",
     "ctx.hero_decision_street||ctx.street||",
     "v8.9.3 P1-5: analyst_learning street fallback"),
    ("gem_report_draft/_html.py",
     "has-mobile-cards",
     "v8.9.3 P0-A: mobile blank table gating"),
    ("gem_report_draft/_html.py",
     "review-json-btn",
     "v8.9.3 P2: export/import JSON button class"),

    # v8.9.7 canaries
    ("gem_villain_intel.py",
     "v_ranks[0] == v_ranks[1]",
     "v8.9.7 B138: pocket-pair guard in _is_weak_showdown"),
    ("gem_villain_intel.py",
     "evidence_atoms.sort(key=_atom_sort_key)",
     "v8.9.7 B139: deterministic atom sort"),
    ("gem_villain_intel.py",
     "exploit_opportunities.sort(key=",
     "v8.9.7 B139: deterministic exploit sort"),
    ("gem_report_draft/sections_xiv.py",
     "idx = -1",
     "v8.9.7 B140: sentinel key for null hero_decision_index"),
    ("gem_report_draft/sections_xiv.py",
     "'same_hand_actionable'",
     "v8.9.7 B141: same_hand_actionable in context dict"),
    ("gem_report_draft/_hand_grid.py",
     "_hero_last_idx_by_street",
     "v8.9.7 B140: precomputed hero last action index"),
    ("gem_report_draft/_html.py",
     "same_hand_actionable",
     "v8.9.7 B141: evidence routing gate"),
    ("gem_analyzer.py",
     "_session_fingerprint",
     "v8.9.7 B142: session fingerprint in intermediates"),
    ("gem_report_draft/_hand_grid.py",
     "_trigger_markers",
     "v8.9.7 B143: trigger marker precomputation"),
    ("gem_report_draft/_html.py",
     "ann-trigger",
     "v8.9.7 B143: trigger marker CSS"),
    # ── v8.9.8 Phase 1 canaries ──
    ("gem_analyzer.py",
     "_is_preflop_terminal_allin",
     "v8.9.8 P2-A: shared preflop-terminal-allin helper"),
    ("gem_analyzer.py",
     "_PLO_CANDIDATE_BUCKETS",
     "v8.9.8 P2-C: centralized PLO quarantine tuple"),
    ("gem_coverage_builder.py",
     "R5_micro_potodds",
     "v8.9.8 P2-B: micro-stack pot-odds routing rule (moved to coverage builder v8.9.9)"),
    ("gem_analyzer.py",
     "REJAM_",
     "v8.9.8 P1-C: reshove REJAM chart lookup"),
    ("gem_report_lint.py",
     "LINT:",
     "v8.9.8 P2-D: per-finding lint detail format"),
    # ── v8.9.9 Phase 2 canaries ──
    ("gem_coverage_builder.py",
     "def build_and_write(",
     "v8.9.9 P1-A: coverage builder extraction entry point"),
    ("gem_analyzer.py",
     "_log_profile",
     "v8.9.9: --profile RSS/timing helper"),
    ("gem_analyzer.py",
     "--resume-from-cache",
     "v8.9.9 P1-B: crash recovery flag"),
    ("gem_analyzer.py",
     "def _versioned_path(directory, prefix, date, ext, pname_file",
     "v8.9.9 P3-A: single module-level _versioned_path (v8.12.10: +tag arg)"),
    # ── v8.10.0 Coaching Cards canaries ──
    ("gem_coaching_cards.py",
     "def build_coaching_cards(",
     "v8.10.0: coaching cards entry point"),
    ("gem_coaching_cards.py",
     "def derive_quality_gates(",
     "v8.10.0: quality gates derivation"),
    ("gem_coaching_cards.py",
     "_COACHING_VERSION",
     "v8.11.0: coaching version constant"),
    ("gem_analyzer.py",
     "from gem_coaching_cards import build_coaching_cards",
     "v8.10.0: coaching cards pipeline integration"),
    ("gem_report_draft/_html.py",
     "function _renderCoachingCard(",
     "v8.10.0: JS coaching card renderer"),
    ("gem_report_draft/_html.py",
     ".learn-card",
     "v8.10.0: coaching card CSS class"),

    # ── v8.11.0 Coaching Cards Phase 2 canaries ──
    ("gem_coaching_cards.py",
     "def _compute_blocker_facts(",
     "v8.11.0: blocker facts computation"),
    ("gem_coaching_cards.py",
     "def _compute_hero_range_facts(",
     "v8.11.0: hero range facts computation"),
    ("gem_coaching_cards.py",
     "def _tmpl_blocker_insight(",
     "v8.11.0: blocker insight template"),
    ("gem_coaching_cards.py",
     "def _tmpl_range_awareness(",
     "v8.11.0: range awareness template"),
    ("gem_coaching_cards.py",
     "_INSIGHT_TEMPLATES",
     "v8.11.0: insight template priority list"),

    # ── v8.11.0b R1-R4 / A3-A5 canaries ──
    ("gem_report_data.py",
     "_pos_map",
     "v8.11.0b R1: showdown hash-to-position resolution map"),
    ("gem_pot_odds.py",
     "villain_range_spec",
     "v8.11.0b A5: villain range spec field in pot-odds"),
    ("gem_report_draft/_html.py",
     "1.15em",
     "v8.11.0b R2: villain card font-size"),
    ("gem_report_draft/_hand_grid.py",
     "_humanize_verdicts",
     "v8.11.0b R4: verdict humanization helper"),
    ("gem_report_draft/sections_xiv.py",
     "_mw_tag",
     "v8.11.0b A3: multiway tag in pot-odds display"),
    ("gem_report_draft/sections_xiv.py",
     "Hero does not cover",
     "v8.11.0b A4: bounty context when discount is zero"),
    ("gem_report_draft/sections_mistakes.py",
     "reclassified as",
     "v8.11.0b R4: reclassified verdict label text"),

    # ── v8.11.0c RC1-RC3 canaries ──
    ("gem_analyzer.py",
     "_build_cc_resume",
     "v8.11.0c RC2: coaching cards in --resume-from-cache path"),
    ("gem_analyzer.py",
     "icm_steal_note",
     "v8.11.0c: ICM gate for missed-steal demotion"),
    ("gem_report_draft/sections_xiv.py",
     "note-street",
     "v8.11.0c RC3: per-street headers in aggression commentary"),
    ("gem_report_draft/sections_xiv.py",
     "street_of_interest",
     "v8.11.0c RC3: street routing for aggression candidates"),

    # v8.11.0d QA fixes
    ("gem_report_draft/_hand_grid.py",
     "_has_negative_pf_verdict",
     "v8.11.0d Q4: pre-computed wrong-push flag suppresses bare 👍"),
    ("gem_report_draft/_hand_grid.py",
     "openVillainEvidence",
     "v8.11.0d Q6: villain archetype links to evidence modal"),
    ("gem_report_draft/sections_xiv.py",
     "_allin_range_note",
     "v8.11.0d Q5: all-in range enrichment function"),
    ("gem_report_draft/sections_xiv.py",
     "Hero equity vs shown hand",
     "v8.11.0d Q3: exact_vs_shown label fix"),

    # v8.12.0 canaries
    ("gem_pko_research.py", "PKO_RESEARCH_BUCKETS",
     "v8.12.0: research bucket table present"),
    ("gem_pko_research.py", "def can_collect_bounty",
     "v8.12.0: collectibility separated from research coverage"),
    ("gem_report_data.py", "pko_research",
     "v8.12.0: enrichment wired into report data"),
    ("gem_report_draft/_helpers.py", "def render_count_cell",
     "v8.12.0: shared count-cell helper"),
    ("gem_report_draft/_helpers.py", "def pb_payload_js",
     "v8.12.0 R1: payload codec emitter"),
    ("gem_report_draft/_html.py", "PBInflateFallback",
     "v8.12.0 R1: embedded inflate fallback"),
    ("gem_report_draft/_html.py", "async function openVillainEvidence",
     "v8.12.0 R1: async guard on villain evidence"),
    ("gem_analyzer.py", "GEM_COVERAGE_AUDIT",
     "v8.12.0 P0: coverage-audit flag"),
    ("gem_coverage_audit.py", "UNCOVERED_REASONS",
     "v8.12.0 P0: uncovered-reason taxonomy"),
    ("Poker_Ranges_Text.txt", "--- QUARANTINED BLOCK (v8.12.0 D1",
     "v8.12.0 D1: SBD quarantine header present"),
    ("gem_report_draft/sections_mistakes.py", "S4.5 Out-of-Scope PKO Spots",
     "v8.12.0: S4 restructure emitted"),

    # v8.12.0a canaries (GTOW handover merge)
    ("gem_gtow.py", 'VERSION = "2.2.1"', "v8.12.0a: gtow builder v2.2.1"),
    ("gem_gtow.py", "pf_settled", "v8.12.0a B149: settled-preflop gate"),
    ("gem_gtow.py", "_is_bounty_hand", "v2.2.0: bounty honesty label"),
    ("gem_gtow.py", "GEM_GTOW_PKO_ROUTING", "v2.2.0: PKO routing flag (default OFF)"),
    ("gem_parser.py", "hand['table_capacity']", "v8.12.0a B150: dealt-vs-capacity split"),
    ("coaching_rules.json", '"N18"', "v8.12.0a: Amit rules N14-N18"),
    ("gem_known_bugs.json", '"B151"', "v8.12.0a: handover bugs registered (renumbered)"),
    ("gem_report_draft/sections_xiv.py", "data-eff-bb=",
     "v8.12.0a: machine-readable appendix card attrs"),

    # v8.12.1 canaries
    ("gem_analyzer.py", "_pko_open_chart_bonus", "v8.12.1 C2: chart-diff bonus"),
    ("gem_analyzer.py", "req_eq -= 8.0 * _pko_scale", "v8.12.1 C1 authoritative"),
    ("gem_analyzer.py", "_g1_g2_chart_deviations", "v8.12.1 P1: G1/G2 detectors"),
    ("gem_review_flags.py", "river_bluffcatch_review", "v8.12.1 P2: G4 review flag"),
    ("gem_coaching_cards.py", "_tmpl_pko_pressure", "v8.12.1: pko card"),
    ("gem_report_draft/_html.py", "_maybe_lazyfy_hands", "v8.12.1 R3: lazy hands (flag-gated)"),
    ("gem_report_draft/_html.py", ".pb-ip-y", "v8.12.1 R2: style classes"),

    # v8.12.2 canaries
    ("gem_report_draft/_html.py", "window.PBLazy=PBLazy",
     "v8.12.2: lazy click-path fix (window exposure)"),
    ("gem_report_draft/_html.py", "GEM_LAZY_HANDS', '1'",
     "v8.12.2 R4: lazy default ON"),
    ("gem_analyzer.py", "_dark_chart_detectors",
     "v8.12.2: G7-G10 dark scaffolding"),
    ("gem_review_flags.py", "missed_value_checkraise", "v8.12.2: G6"),
    ("gem_review_flags.py", "build_p4_worksheet", "v8.12.2: P4 worksheet"),

    # v8.12.3 canaries
    ("gem_report_draft/_helpers.py",
     "def short_verdict_pill(",
     "v8.12.3: 1-2 word verdict pill helper"),
    ("gem_report_draft/sections_xiv.py",
     "short_verdict_pill",
     "v8.12.3: pill wired into XIV hand headings"),
    ("gem_report_draft/_html.py",
     "bottom: 58px",
     "v8.12.3: expand-all stacked above Copy Review Notes"),
    ("gem_report_draft/_html.py",
     ".verdict-pill",
     "v8.12.3: verdict pill CSS variants"),
    ("gem_report_draft/_hand_grid.py",
     'title="Trigger:',
     "v8.12.3/v8.12.8: trigger tooltip names the villain action"),
    ("gem_coaching_cards.py",
     "players_at_flop",
     "v8.12.3: multiway card counts pot entrants, not dealt players"),

    # v8.12.4 canaries
    ("gem_parser.py",
     "_CBET_FIRST_ACTIONS",
     "v8.12.4: composite bet-then-X codes count as c-bets"),
    ("gem_parser.py",
     "_river_bet_is_value",
     "v8.12.4: river value requires beating the board"),
    ("gem_report_data.py",
     "_refresh_results_attribution",
     "v8.12.4: post-analyst cooler/mistake attribution refresh"),
    ("gem_report_data.py",
     "GEM_APPENDIX_CAP",
     "v8.12.4: lazy-aware appendix cap"),
    ("gem_report_draft/tldr.py",
     "The two spines disagree on this session",
     "v8.12.4: BB-vs-cEV reconciliation note"),
    ("gem_report_draft/sections_iv_xii.py",
     "opportunity-weighted target",
     "v8.12.4: defend-matrix aggregate target blend"),
    ("gem_analyzer.py",
     "GEM_QUICK_ALLOW_STALE",
     "v8.12.4: --quick hard-abort on stale cache"),
    ("gem_leak_watchlist.py",
     "synthesis_notes",
     "v8.12.4: watchlist coherence notes"),

    # v8.12.5 canaries
    ("gem_report_draft/_html.py",
     "function _norm(hid)",
     "v8.12.5: PBLazy normalizes TM-form ids (popup dead-click fix)"),
    ("gem_report_draft/_html.py",
     "verdict-pill|context-pill",
     "v8.12.5: pill span in the _md_inline stash whitelist (pills render)"),
    ("gem_report_draft/_html.py",
     "rides the top bar",
     "v8.12.5/v8.14.0: modal top bar carries the system verdict"),
    ("gem_report_data.py",
     "content-sniffed sibling fallback",
     "v8.12.5: game-summary discovery finds sibling dirs"),
    ("gem_report_data.py",
     "unresolved_hh_tournaments",
     "v8.12.5: unresolved/flighted tournament accounting"),
    ("gem_report_data.py",
     "_wilson_pl",
     "v8.12.5: CI-gated leak promotion"),
    ("gem_report_draft/tldr.py",
     "Unsettled:",
     "v8.12.5: TLDR unsettled-tournaments line"),

    # v8.12.6 canaries
    ("gem_analyzer.py",
     "stats['_non_nlh_ids'] = _non_nlh_ids_main",
     "v8.12.6: __main__ NameError fix (was s[...])"),
    ("gem_report_draft/sections_xiv.py",
     "matches no street window",
     "v8.12.6: W-POT any-street acceptance windows"),

    # v8.12.7 canaries (PKO3 Part-1 bake)
    ("gem_pko_research.py", "PKO3 v3 panel-validated",
     "v8.12.7: Part-1 verified extraction baked"),
    ("gem_pko_research.py", "'delta_range_pp': [29.5, 29.5]",
     "v8.12.7: 3way-short v3 point measurement"),
    ("gem_pko_research.py", "added region ~96% flat calls",
     "v8.12.7: flat-call-dominated added region (jam narrative retired)"),
    ("_test_scratch.py", "T-PKO-24",
     "v8.12.7: v3 bake pin present"),

    # v8.12.8 canaries (Ron QA omnibus)
    ("gem_report_draft/draft.py", "window.handIndex=",
     "v8.12.8: static hand index for lazy-safe popup rows"),
    ("gem_report_draft/_html.py", "function fmtCardSpans",
     "v8.12.8: popup index-first card spans"),
    ("gem_pko_research.py", "out_of_scope_sb_opener",
     "v8.12.8: SB opens never borrow BTN aggregate"),
    ("gem_pko_research.py", "aggregate_fit",
     "v8.12.8: nearest-aggregate honesty fields"),
    ("gem_pot_odds.py", "def compute_nonallin_pot_odds",
     "v8.12.8: street-calls pot odds (handover Issue 1)"),
    ("gem_analyzer.py", "heuristic_fallback_n",
     "v8.12.8: EAI degradation stamp (handover Issue 2)"),
    ("gem_villain_intel.py", "read_supported_standard",
     "v8.12.8: standard-open gate on Good Exploit"),
    ("gem_report_draft/_hand_grid.py", "_grid_bet_pcts",
     "v8.12.8: rendered sizings stashed for W-PCT lint"),
    ("SESSION_START_STEP0_package_rebuild.txt", "pip install --quiet phevaluator",
     "v8.12.8: Chat env installs the equity engine"),
    # v8.12.8 QA2 canaries (pre-upload deep-QA pass)
    ("gem_report_draft/_html.py", "function _hashEnsure",
     "v8.12.8 QA2: initial-load deep-link materialization + instant scroll"),
    ("gem_report_draft/_html.py", "<h([45]) [^>]*id=",
     "v8.12.8 QA2: lazyfier preserves h4 AND h5 anchored headings"),
    ("gem_report_draft/sections_xiv.py", "def _emit_villain_street_notes",
     "v8.12.8 QA2: shared villain note block (stub pairing)"),
    ("gem_report_draft/_hand_grid.py", "_vb_exp = _vb.get('expect')",
     "v8.12.8 QA2: badge action-kind guard (never-wrong placement)"),
    ("gem_analyzer.py", "_slug_q",
     "v8.12.8 QA2: --quick reads the session-suffixed hash marker"),
    # v8.12.8 QA3 canaries (Ron's hand-review fixes)
    ("gem_coverage_builder.py", "_rv.get(r1, 0) > _rv.get(r0, 0)",
     "v8.12.8 QA3: chart notation sorts ranks (8Ao membership bug)"),
    ("gem_analyzer.py", "_sb_chart_hit",
     "v8.12.8 QA3: SB100 missed-open records the chart actually hit"),
    ("gem_pot_odds.py", "_folded_players",
     "v8.12.8 QA3: folded reveals excluded from showdown equity"),
    ("gem_pot_odds.py", "priced on the main pot",
     "v8.12.8 QA3: side-pot-aware required equity"),
    ("gem_report_draft/_html.py", "function _sortPopupTable",
     "v8.12.8 QA3: sortable hand-list columns"),
    ("gem_report_draft/sections_xiv.py", "def _embolden_hand_in_range",
     "v8.12.8 QA3: hero hand bolded in range strings"),
    # v8.12.8 QA-GPT canaries
    ("gem_report_draft/_helpers.py", "charge the raiser the full catch-up delta",
     "v8.12.8 QA-GPT: pot walk converts raise increments to totals"),
    ("gem_report_draft/_hand_grid.py", "_street_commit",
     "v8.12.8 QA-GPT: grid running pot uses commit deltas"),
    ("gem_coverage_builder.py", "equity-driven get-in",
     "v8.12.8 QA-GPT: rejam TL;DR uses the membership boolean"),
    ("gem_report_draft/sections_xiv.py", "def _oversize_open_note",
     "v8.12.8 QA-GPT: villain sizing-read teaching note"),
    ("gem_report_draft/_html.py", "Loading all hands to search",
     "v8.12.8 QA-GPT: lazy-aware search fallback"),
    # v8.12.10 canaries (Slices B + C)
    ("gem_villain_intel.py", "def _chart_label",
     "v8.12.9: single canonical hand-label owner (no JJo)"),
    ("gem_report_data.py", "def compute_report_completeness",
     "v8.12.10: report completeness single owner"),
    ("gem_analyzer.py", "def _quick_validate_render",
     "v8.12.10: --quick render validation"),
    ("gem_report_draft/tldr.py", "AUTO-ONLY REPORT",
     "v8.12.10: completeness banner"),
    ("gem_report_draft/_html.py", "position: sticky; top: var(--v25-topbar-h, 0px); z-index: 4;",
     "v8.12.9: mobile sticky street headers"),

    # v8.12.11 canaries (Slice E: analyst_worklist_v1)
    ("gem_analyst_worklist.py", "def build_analyst_worklist(",
     "v8.12.11: worklist builder entry point"),
    ("gem_analyst_worklist.py", 'SCHEMA = "analyst_worklist_v1"',
     "v8.12.11: worklist schema id"),
    ("gem_analyst_worklist.py", "def _auto_clear_gate(",
     "v8.12.11 GPT-3: narrow multi-condition auto_clear gate"),
    ("gem_analyst_worklist.py", "def _line_from_ledger(",
     "v8.12.11 GPT-5: ledger-built canonical action line"),
    ("gem_analyst_worklist.py", "adjustment_applied_to_decision",
     "v8.12.11 GPT-6: split bounty-context fields"),
    ("gem_analyst_worklist.py", "'price_unavailable'",
     "v8.12.11 GPT-4: null-safe call amount + failure mode"),
    ("gem_analyst_worklist.py", "def _decision_kind(",
     "v8.12.11 GPT#2: explicit decision kind / basis"),
    ("gem_analyst_worklist.py", "def _preflop_effective_bb(",
     "v8.12.11 GPT#2: clean preflop stack (not overwritten by later all-in)"),
    ("gem_analyst_worklist.py", "stop in ('first', 'last')",
     "v8.12.11 GPT#2/#4: ledger line stops at Hero's reviewed decision"),
    ("gem_analyst_worklist.py", "price_not_applicable",
     "v8.12.11 GPT#3: first-in decisions carry no call price"),
    ("gem_analyst_worklist.py", "def _hero_faces_preflop_raise(",
     "v8.12.11 GPT#3: facing-vs-first-in price detector"),
    ("gem_analyst_worklist.py", "def _preflop_allin_event(",
     "v8.12.11 GPT#4: reviewed-event selector (last action, not first open)"),
    ("gem_analyst_worklist.py", "def _allin_sizing(",
     "v8.12.11 GPT#5: raw size vs decision-effective stack separation"),
    ("gem_analyst_worklist.py", "'jam_size_bb'",
     "v8.12.11 GPT#5: explicit raw jam-size field"),
    ("gem_analyst_worklist.py", "requires side-pot/overjam reconciliation",
     "v8.12.11 GPT#5: unreconcilable-price failure mode"),
    ("gem_chart_labels.py", "def chart_display_label(",
     "v8.12.11: chart-id -> human label registry"),
    ("gem_analyzer.py", "build_analyst_worklist",
     "v8.12.11: worklist emit hook wired in pipeline"),

    # v8.12.12 / Slice E.1 — report trust + source-truth cleanup
    ("gem_report_draft/sections_mistakes.py", "def _analyst_punt_street_label(",
     "v8.12.12 Obj-A: preflop-vs-postflop punt street label"),
    ("gem_report_draft/sections_financial.py", "def _neutral_unreviewed_large_loss_verdict(",
     "v8.12.12 Obj-B: neutral AUTO_ONLY/unreviewed large-loss labels"),
    ("gem_report_draft/sections_financial.py", "elif hid in i7_ids:",
     "v8.12.12 Obj-B: only analyst I.7 renders as a cooler verdict"),
    ("gem_analyst_worklist.py", "'price_source':",
     "v8.12.12 Obj-C: decision-node price provenance"),
    ("gem_report_data.py", "'awaiting_by_bucket'",
     "v8.12.12 Obj-D: per-bucket unreviewed breakdown"),
    ("gem_report_draft/tldr.py", "ANALYST_COMPLETE",
     "v8.12.12 Obj-D: complete-coverage banner"),

    # v8.12.12 rev-2/rev-3 / Slice E.1 (F-H) — cover table, PKO math, Roman removal
    ("gem_report_draft/sections_xiv.py", "def _stack_cover_label(",
     "v8.12.12 Obj-F: per-villain cover direction+delta helper"),
    ("gem_report_draft/sections_xiv.py", "PKO-adjusted call needs",
     "v8.12.12 Obj-G: chip-only vs PKO-adjusted call threshold (cover-aware)"),
    ("gem_report_draft/sections_xiv.py", "Dollar bounty unavailable in HH export",
     "v8.12.12 rev-3 Obj-G: explicit dollar-unavailable fallback (no faked $)"),
    ("gem_report_draft/sections_xiv.py", "def _pko_bounty_usd(",
     "v8.12.12 rev-3 Obj-G: safe per-bounty dollar lookup (None when absent)"),
    ("gem_report_draft/sections_xiv.py", "PKO adjustment unavailable",
     "v8.12.12 Obj-G: unsafe/unknown PKO -> review manually (no faked discount)"),
    ("gem_report_draft/_hand_grid.py", "def _verdict_display_label(",
     "v8.12.12 Obj-H: strip Roman verdict code from user-facing labels"),

    # v8.13.0 — Slice F: villain exploitation teaching layer
    ("gem_villain_teaching.py", "def build_villain_teaching(",
     "v8.13.0: villain teaching projection builder"),
    ("gem_villain_teaching.py", "FALLBACK_LINE =",
     "v8.13.0: fixed safe-fallback line for thin/hindsight-gated reads"),
    ("gem_villain_teaching.py", "def _no_hindsight(",
     "v8.13.0: structural no-hindsight guard (showdown atoms can't be a cue)"),
    ("gem_villain_teaching.py", "do_not_overadjust",
     "v8.13.0: derived over-adjust guardrail copy (never a villain fact)"),
    ("gem_report_draft/sections_xiv.py", "_ctx['teaching'] = _vt_exp(",
     "v8.13.0: teaching object attached to exploit contexts"),
    ("gem_report_draft/sections_xiv.py", "_ctx['teaching'] = _vt_atom(",
     "v8.13.0: teaching object attached to evidence contexts"),
    ("gem_report_draft/_html.py", "v25-teach",
     "v8.13.0: compact villain teaching block in the modal context render"),
    # v8.13.0 rev-2 (GPT product-fail fixes)
    ("gem_report_draft/_html.py", "teach_lines.forEach",
     "v8.13.0 rev-2: renderer shows the FULL teach_lines (incl villain_did), not just the header"),
    ("gem_villain_teaching.py", "def derive_do_not_overadjust(",
     "v8.13.0 rev-2: generic/context-safe low-confidence guardrail (not PKO-specific by default)"),
    ("gem_villain_teaching.py", "same_hand_actionable",
     "v8.13.0 rev-2: atom no-hindsight requires same_hand_actionable"),
    # ── v8.14.0 Slice D: villain exploitation v2 (teaching contract + N8 tags) ──
    ("gem_villain_teaching.py", "def suggest_natural8_tag(",
     "v8.14.0 Slice D: Natural8 candidate client-tag mapper (label+colour)"),
    ("gem_villain_teaching.py", "_N8_TAG_UNSURE",
     "v8.14.0 Slice D: weak read -> explicit 'Unsure / Tag-me-later' (never forced)"),
    ("gem_villain_teaching.py", "def _candidate_archetype(",
     "v8.14.0 Slice D: candidate read language unless high confidence"),
    ("gem_villain_teaching.py", "def build_villain_evidence_summary(",
     "v8.14.0 Slice D: per-STABLE-villain evidence aggregation"),
    ("gem_villain_teaching.py", "What villain did: ",
     "v8.14.0 Slice D: per-hand teaching contract label"),
    ("gem_villain_teaching.py", "Tag suggestion: ",
     "v8.14.0 Slice D: tag-suggestion teach line (label + colour)"),
    ("gem_report_draft/_html.py", "v25-teach-tag",
     "v8.14.0 Slice D: Natural8 candidate-tag swatch in the teaching block"),
    ("gem_report_draft/_html.py", "Do not over-adjust:",
     "v8.14.0 Slice D: renamed guardrail label in the teach-line classifier"),
    ("gem_report_draft/_html.py", "data-tag-color",
     "v8.14.0 Slice D: tag colour-swatch attribute (driven by the (colour) token)"),
    # ── v8.14.0 Slice E: PKO v2 trust reconciliation + copy clarity ──
    ("gem_pko_research.py", "def reconcile_pko_trust(",
     "v8.14.0 Slice E: single PKO trust reconciliation (cover/collect/bounty)"),
    ("gem_pko_research.py", "PKO trust check failed",
     "v8.14.0 Slice E: contradiction guard — no bounty conclusion fights its math"),
    ("gem_pko_research.py", "def pko_trust_render(",
     "v8.14.0 Slice E rev-2: render-path trust (threshold/discount/overjam + downgrade)"),
    ("gem_pko_research.py", "**Bounty trust:**",
     "v8.14.0 Slice E rev-2: the on-page bounty-trust strip markdown"),
    ("gem_report_draft/sections_xiv.py", "_pko_trust_render(",
     "v8.14.0 Slice E rev-2: PKO pill wires pot-odds threshold facts into the strip"),
    ("gem_report_draft/sections_mistakes.py", "| Opportunity | PKO",
     "v8.14.0 Slice E rev-2: PKO opportunity table header rename (Wrong/Missed split)"),
    ("gem_report_draft/sections_financial.py", "cEV/100 = chip-EV per 100 hands",
     "v8.14.0 Slice E: concise cEV/BB-100 unit gloss (copy clarity)"),
    # ── v8.14.1: real-report QA hotfix ──
    ("gem_version.py", "RUNTIME_VERSION = 'v8.16.4'",
     "v8.16.4: runtime/release version single source of truth"),
    # ── v8.16.4: Review Precision & Decision-Trust hotfix ──
    ("gem_review_trust.py", "def build_why_review(",
     "v8.16.4 Obj4: actionable why-this-hand contract (street+action+reason+category)"),
    ("gem_review_trust.py", "def reconcile_verdict(",
     "v8.16.4 Obj5: verdict/action reconciliation (downgrade unsubstantiated Mistake)"),
    ("gem_review_trust.py", "def multiway_render_plan(",
     "v8.16.4 Obj8: multiway snapshot suppresses heads-up required-equity"),
    ("gem_review_trust.py", "def bounty_provenance_label(",
     "v8.16.4 Obj9: PKO bounty provenance (exact/estimated/flat-starting-BB/effective)"),
    ("gem_ranges.py", "def highlight_range_expression(",
     "v8.16.4 Obj6: ONE shared green/amber/red/neutral range-expression highlighter"),
    ("gem_ranges.py", "def _lens_hero_relative(",
     "v8.16.4 Obj10: postflop lens mentions Hero only for blocker/value/bluff-catch"),
    ("gem_report_draft/_html.py", 'grid-template-areas: "rank hid cards note status"',
     "v8.16.4 Obj1: reviewed-row 5-col grid (status pill no longer wraps)"),
    ("gem_report_draft/_html.py", "_roq=new ResizeObserver",
     "v8.16.4 Obj2: queue-bar ResizeObserver re-syncs sticky street-header offset"),
    ("gem_report_draft/sections_xiv.py", "Objective 10: when Hero is all-in PREFLOP",
     "v8.16.4 Obj10: no postflop Range Lens after a preflop all-in"),
    # ── v8.16.4 DECISION-TRUST INTEGRATION: pure contracts wired into live render ──
    ("gem_ranges.py", "def preflop_range_lens(ev, ranges, highlight=False)",
     "v8.16.4 DTI Obj6: range-lens highlight param (render path opt-in)"),
    ("gem_report_draft/sections_xiv.py", "preflop_range_lens(_ev, _ranges, highlight=True)",
     "v8.16.4 DTI Obj6: range expression highlighted in the live lens"),
    ("gem_report_draft/sections_xiv.py", "multiway_render_plan as _mw_render_plan",
     "v8.16.4 DTI Obj8: multiway all-in suppresses heads-up required-equity"),
    ("gem_report_draft/sections_xiv.py", "bounty_provenance_label as _bpl2",
     "v8.16.4 DTI Obj9: bounty provenance label on the canonical bounty block"),
    ("gem_analyzer.py", "verdict_validation_issue as _vvi14",
     "v8.16.4 DTI Obj5: validator Check 14 flags unsubstantiated Mistake/Punt"),
    ("gem_analyst_worklist.py", "build_why_review as _bwr",
     "v8.16.4 DTI Obj4: additive why_contract (street+action+category) in worklist"),
    # ── v8.16.3: Commentary & Range Explanation v1 + Commentary Column v3.4 ──
    ("gem_ranges.py", "def postflop_range_lens(",
     "v8.16.3: source-safe postflop Range Lens (made/draw/air, board texture)"),
    ("gem_ranges.py", "def compress_range(",
     "v8.16.3: compact preflop range notation (suited != offsuit)"),
    ("gem_commentary_migration.py", "def run_migration_audit(",
     "v8.16.3 v3.4: router-aware zero-drop commentary migration audit"),
    ("gem_commentary_migration.py", "def route_street_attr(",
     "v8.16.3 v3.4: faithful V25 router street-rule port (misbucket proof)"),
    ("gem_commentary_migration.py", "def opp_context_is_in_cell(",
     "v8.16.3 v3.4: in-cell vs bottom firewall predicate (no bottom in cell)"),
    ("gem_report_draft/_html.py", "from gem_commentary_migration import run_migration_audit",
     "v8.16.3 v3.4: migration audit hook (pre-compression, lazy-parity safe)"),
    ("gem_report_draft/sections_xiv.py", "def _emit_range_lens(",
     "v8.16.3: Range Lens emitted as router-compatible .analyst-notes[data-street]"),
    ("gem_villain_intel.py", "def build_hand_chronology(",
     "v8.16.0 villain: cross-hand chronology by parsed timestamp (Step 1)"),
    ("gem_villain_intel.py", "score = _prior_dims.get('loose', 0) + _prior_dims.get('passive', 0)",
     "v8.16.0 villain: loose_passive composite-dimension scorer fix"),
    ("gem_villain_teaching.py", "def _grade_bucket(",
     "v8.16.0 villain: trusted-baseline grade gate (no broad missed/good)"),
    ("gem_villain_teaching.py", "_TRUSTED_BASELINE_DETECTORS",
     "v8.16.0 villain: trusted-baseline detector allowlist"),
    ("gem_villain_teaching.py", "def derive_profile(",
     "v8.16.0 villain: mixed/split profile caveat (cue-axis vs read-axis)"),
    ("gem_report_draft/sections_iv_xii.py", "Teaching Signals",
     "v8.16.0 villain: matrix 'Teaching Signals' wording (no false opps=missed+good)"),
    ("gem_analyzer.py", "'report_format_version'",
     "v8.14.1 #5: manifest emits runtime version + report-format version"),
    ("gem_analyzer.py", "_run_log_",
     "v8.14.1 #7: human-readable run log written to outputs"),
    ("gem_pko_research.py", "chip-vs-PKO threshold not modelled at this depth",
     "v8.14.1 #2: PKO threshold-unavailable stated explicitly, not silent"),
    ("gem_report_draft/tldr.py", "Auto-cleared — quick scan",
     "v8.14.1 #4: auto-clear queue rows are not titled 'mistake'"),
    ("gem_report_draft/tldr.py", "Why cEV, not BB/100?",
     "v8.14.1 #1: dense cEV paragraph collapsed into a <details>"),
    ("gem_coverage_builder.py", "from gem_chart_labels import chart_display_label",
     "v8.14.1 #71725727: human-readable chart labels, not raw REJAM_/PUSH_ ids"),
    ("gem_report_draft/sections_xiv.py", "not how often you are ahead right now",
     "v8.14.1 #73281169: required-equity-vs-range teaching copy"),
    ("gem_report_draft/sections_financial.py", "cash-settlement (session-end) date",
     "v8.14.1 #6: financial aggregate date labelled as session-end/settlement"),
    # ── v8.14.1 rev-2: review-list cosmetics + section-review separation ──
    ("gem_report_draft/_html.py", "Section review",
     "v8.14.1 rev-2 #3: section reviews labelled distinctly (not as hands)"),
    ("gem_report_draft/_html.py", "cards:_rvc",
     "v8.14.1 rev-2 #2: reviewed-list rows carry Hero cards next to the hand id"),
    ("gem_report_draft/tldr.py", "rq-rev-caret",
     "v8.14.1 rev-2 #1: reviewed/completed list collapsed by default + caret affordance"),
    # ── v8.13.1: analyst-coverage + verdict-contradiction trust ──
    ("gem_report_data.py", "_CRITICAL_NEED_BUCKETS",
     "v8.13.1 P0: ANALYST_COMPLETE gated on critical-loss coverage"),
    ("gem_report_data.py", "critical_unreviewed",
     "v8.13.1 P0: critical-coverage gate stamps unreviewed count"),
    ("gem_report_data.py", "coverage_line",
     "v8.13.1 P0: quantified analyst coverage line"),
    ("gem_coverage_builder.py", "def build_loss_screens(",
     "v8.13.1 P1: biggest-loss + postflop-loss coverage screens"),
    ("gem_coverage_builder.py", "POSTFLOP_LOSS_SCREEN_BB",
     "v8.13.1 P1: configurable postflop-loss screen threshold (-15BB)"),
    ("gem_analyst_worklist.py", "postflop_loss_screen",
     "v8.13.1 P1: loss screens wired into the worklist source buckets"),
    ("gem_analyst_worklist.py", "def effective_stack_safety(",
     "v8.13.1 P1: effective-vs-total stack safety for shove/overjam verdicts"),
    ("gem_report_draft/_hand_grid.py", "def reconcile_push_widget(",
     "v8.13.1 P1: auto push widget reconciled against final analyst verdict"),
    ("gem_report_draft/_hand_grid.py", "auto pre-review",
     "v8.13.1 P1: unreviewed auto push check labelled 'auto pre-review'"),
    ("gem_report_draft/sections_xiv.py", "def _wpot_claim_ok(",
     "v8.13.1 P2: W-POT accepts _pot_odds per-street 'call X into Y' pots"),
    ("gem_report_draft/_helpers.py", "def monotone_overcommit_lesson(",
     "v8.13.1 P2: monotone over-commit sequence lesson (not 'missed flop aggression')"),
    # ── v8.14.0 Slice B: V25 hand-detail modal redesign (top bar + street headers) ──
    ("gem_report_draft/_html.py", ".v25-top-identity .v25-top-verdict",
     "v8.14.0 Slice B: readable-but-not-dominant top-bar system-verdict chip"),
    ("gem_report_draft/_html.py", "v25-top-hand-label",
     "v8.14.0 Slice B: Hand label + id render as one clean cluster"),
    ("gem_report_draft/_html.py", "v25-street-context",
     "v8.14.0 Slice B: street context chips sit next to the street title"),
    ("gem_report_draft/_html.py", "v25-strength-chip",
     "v8.14.0 Slice B: street hand/board-state context chip"),
    ("gem_report_draft/_html.py", "replace(/I{1,3}[.][0-9]+/g",
     "v8.14.0 Slice B: top verdict strips raw Roman verdict codes"),
    # ── v8.14.0 Slice C: Compact Hand Review Queue ──
    ("gem_report_draft/tldr.py", "def build_review_queue(",
     "v8.14.0 Slice C: prioritized (5-bucket) compact review queue builder"),
    ("gem_report_draft/tldr.py", "def normalize_review_status(",
     "v8.14.0 Slice C: status normalizer (Drill/Rulebook in; Ignore rejected)"),
    ("gem_report_draft/tldr.py", "id=\"review-queue\"",
     "v8.14.0 Slice C: 'Hands to open first' upgraded to the compact review queue"),
    ("gem_report_draft/_html.py", "window.PBReviewQueue",
     "v8.14.0 Slice C: review-queue controller (open/reviewed partition + counts)"),
    ("gem_report_draft/_html.py", "data-verdict=\"Drill\"",
     "v8.14.0 Slice C: Drill + Rulebook review statuses in the modal"),
    ("gem_report_draft/_html.py", "grid-template-areas: \"rank hid main bb\"",
     "v8.14.0 Slice C: compact queue rows stack on mobile (no horizontal overflow)"),
    # ── v8.14.1 REV3: legacy "Correct range" prose defers to the canonical
    #    Range-evidence block (no HJ-vs-MP membership contradiction, 72807590) ──
    ("gem_report_draft/sections_xiv.py", "def _canon_supersede(h):",
     "v8.14.1 REV3: canonical Range-evidence block supersedes legacy Correct-range prose"),
    ("gem_report_draft/sections_xiv.py", "'inside this chart')",
     "v8.14.1 REV3: W-RANGE-CONTRADICT lint flags chart-membership claims (range-standard/inside this chart) beside an OUTSIDE chart"),
    # ── v8.14.1 REV4: report-body leak rows show Hero's real seat + label a
    #    short-table proxy chart (no "HJ 23BB" for a 7-max MP hand, 72807590) ──
    ("gem_report_draft/sections_xiii.py", "def _proxy_info(d):",
     "v8.14.1 REV4: body rows use the real seat + label a short-table proxy chart"),
    ("gem_report_draft/_helpers.py", "label += ' (short-table proxy)'",
     "v8.14.1 REV4: _emit_correct_ranges labels short-table proxy charts"),
    # ── v8.14.1 REV5: re-jam chart-existence trust (72692569) — coverage-builder
    #    key matches the canonical selector; a no-chart claim can't sit beside a
    #    canonical Reference ──
    ("gem_coverage_builder.py", 'REJAM_{_pos.replace("+", "")}vs{_opener.replace("+", "")}',
     "v8.14.1 REV5: re-jam key strips '+' to match gem_ranges (no false 'no rejam chart')"),
    ("gem_report_draft/sections_xiv.py", "W-RANGE-CHART-EXISTS",
     "v8.14.1 REV5: lint — 'no chart' claim may not appear beside a canonical Reference"),
    # ── v8.14.1 REV6: chart-support prose vs canonical no-charted-range (73559949) ──
    ("gem_report_draft/sections_xiv.py", "W-RANGE-NO-CHART",
     "v8.14.1 REV6: lint — chart-support prose may not appear when canonical has NO charted range"),
    # ── v8.14.3: post-report QA hotfix (financial SoT, analyst-critical trim
    #    guard, awaiting-vs-COMPLETE, validator decodes the lazy payload, dead
    #    cross-ref neutralizer) ──
    ("gem_report_data.py", "_financial_source",
     "v8.14.3 Issue 1: top-level financials canonicalised from the parsed USD overlay"),
    ("gem_report_data.py", "total_ticket_value",
     "v8.14.3 Issue 1: overlay totals carry the satellite-ticket value (cash+ticket basis)"),
    ("gem_report_draft/sections_financial.py", "cash + ticket",
     "v8.14.3 Issue 1: by-day table labels the cash+ticket basis (not cash-only)"),
    ("gem_report_draft/sections_financial.py", "outside required review set",
     "v8.14.3 Issue 2: large-loss verdict relabels (not 'awaiting') when ANALYST_COMPLETE"),
    ("gem_report_draft/draft.py", "_analyst_full_ids",
     "v8.14.3 Issue 3: analyst/critical hands are P0/P1-protected from the HA3 byte trim + rescued"),
    ("gem_report_draft/_html.py", "dead-xref",
     "v8.14.3 Issue 5: dangling internal cross-refs neutralised to a span (no dead #anchor)"),
    ("gem_analyzer.py", "def _decode_lazy_cards(",
     "v8.14.3 Issue 4: render validator DECODES the lazy payload inline (works in the shipped bundle, not just shell markers)"),
    ("gem_analyzer.py", "ANALYST_COMPLETE report (Issue 2)",
     "v8.14.3 Issue 4: validator gates 'awaiting analyst' on ANALYST_COMPLETE state"),
    # ── v8.14.4: cash + ticket return-basis disclosure on the ACTIVE financial
    #    surface (the v8.14.3 footnote was in the disabled S7 path) ──
    ("gem_report_draft/tldr.py", "cash + ticket basis, not cash only",
     "v8.14.4: cash+ticket return-basis disclosure rendered on the active S1.1a by-day table"),
    ("gem_analyzer.py", "cash + ticket return-basis disclosure on the rendered",
     "v8.14.4: validator gates ticket>0 against a rendered cash+ticket disclosure"),
    # ── v8.14.4: centralized raw chart-ID guard (no PUSH_/CALLJAM_/REJAM_/OPEN_/
    #    JAM_ in user-facing prose) ──
    ("gem_chart_labels.py", "def find_raw_chart_ids_in_user_text(",
     "v8.14.4: centralized raw-chart-ID detector (strips tags/attrs/JS; flags only visible prose)"),
    ("gem_chart_labels.py", "def humanize_raw_chart_ids(",
     "v8.14.4: safe sanitization layer — replace raw chart ids with human labels"),
    ("gem_analyzer.py", "raw chart ID(s) in user-facing",
     "v8.14.4: validator flags raw chart IDs in rendered prose / decoded cards / commentary"),
    # ── v8.15.0: Tournament Tables — typed event-level model + additive section ──
    ("gem_tournament_model.py", "def build_tournament_model(",
     "v8.15.0: typed event-level tournament model (unit=event, canonical usd_overlay totals, cash+ticket)"),
    ("gem_report_draft/sections_tournaments.py", "def _emit_tournament_tables(",
     "v8.15.0: additive event-level Tournament Tables render section"),
    ("gem_report_draft/sections_tournaments.py", "per-event cEV/100: unavailable",
     "v8.16.2: per-event cEV column hidden when no canonical source (trust-line audit note)"),
    ("gem_report_draft/draft.py", "('STT', _emit_tournament_tables)",
     "v8.15.0: Tournament Tables wired additively AFTER S1 (old Results tables retained)"),
    # ── v8.16.4 DTI blockers: bounded queue + decision evidence on every path ──
    ("gem_review_trust.py", "def aggregate_review_queue(",
     "v8.16.4 DTI Blocker 1: canonical bounded + aggregated review-queue helper"),
    ("gem_review_trust.py", "def classify_preflop_allin(",
     "v8.16.4 DTI Blocker 2: structurally-provable all-in decision-kind classifier"),
    ("gem_review_trust.py", "def attribution_render_line(",
     "v8.16.4 DTI: optional root/downstream attribution render-line helper"),
    ("gem_report_draft/tldr.py", "aggregate_review_queue as _agg_q",
     "v8.16.4 DTI Blocker 1: dashboard build_review_queue routes through the bounded aggregator"),
    ("gem_report_draft/tldr.py", "_REVIEW_QUEUE_CAP",
     "v8.16.4 DTI Blocker 1: explicit configurable review-budget cap"),
    ("gem_report_draft/sections_xiv.py", "classify_preflop_allin as _cpa_b",
     "v8.16.4 DTI Blocker 2: decision-kind label on the XIV.B compact path"),
    ("gem_report_draft/sections_xiv.py", "classify_preflop_allin as _cpa_a",
     "v8.16.4 DTI Blocker 2: decision-kind label on the XIV.A full-card path (every path)"),
    ("gem_report_draft/sections_xiv.py", "attribution_render_line as _arl_b",
     "v8.16.4 DTI: optional attribution render wired into the compact path"),
    # ── v8.17 Epic B (B6/B7): how-PKO-changes-the-decision coaching + provenance ──
    ("gem_pko_research.py", "def how_pko_changes_decision(",
     "v8.17 B7: explicit how-the-bounty-changes-the-decision coaching helper"),
    ("gem_pko_research.py", "'how_changes_md': how_changes_md",
     "v8.17 B7: pko_trust_render exposes the coaching prose (single call, no recompute)"),
    ("gem_report_draft/sections_xiv.py", "_pk_render['how_changes_md']",
     "v8.17 B7: how-PKO-changes-the-decision rendered on the XIV.A full-card pill"),
    ("gem_report_draft/sections_xiv.py", "_pkb_render['how_changes_md']",
     "v8.17 B7/C2: same coaching rendered on the XIV.B compact pill (parity)"),
    ("gem_report_draft/sections_xiv.py", "Bounty value unavailable",
     "v8.17 B6: explicit 4-state provenance incl. the unavailable state on the pill"),
]

# Anti-canaries: strings that must NOT appear (old bug patterns).
# If found, the fix has regressed.
ANTI_CANARIES = [
    # v8.12.0 D1: the old wrong-node SB defend charts must stay quarantined.
    # A live (non-prefixed) chart line starting with SBD_ would re-enable the
    # broken _sb_missed_gated recommendations. Quarantined lines carry the
    # '--- QUARANTINED' prefix, so a newline followed directly by 'SBD_'
    # only exists if someone un-quarantines a chart.
    ("Poker_Ranges_Text.txt", "\nSBD_",
     "v8.12.0 D1: wrong-node SB defend charts re-enabled (must stay quarantined)"),
    # v8.12.7: artifact-era jam-mix claims must stay retired
    ("gem_pko_research.py", "call:shove",
     "v8.12.7: v1 jam-mix ratio claim resurfaced (artifact-era)"),
    ("gem_pko_research.py", "'jam_heavy': True",
     "v8.12.7: jam-heavy flag resurfaced (v3 measured all-False)"),
    # v8.12.8: the raw red-! trigger glyph must stay retired (red = evidence)
    ("gem_report_draft/_hand_grid.py", "'!<sup>",
     "v8.12.8: raw ! trigger glyph resurfaced (red is reserved for evidence)"),
    # v8.12.8 QA3: the thumbs-down "Good move" pill must stay dead
    ("gem_report_draft/_hand_grid.py", "👎<sup>",
     "v8.12.8 QA3: positive marker is thumbs-down again"),
    # v8.12.12 Obj-B: the exculpatory "unclassified variance" verdict default
    # must stay retired in BOTH large-loss audits (an unreviewed loss is not
    # graded "variance" as if it were a decision verdict).
    ("gem_report_draft/sections_financial.py", "🎲 unclassified variance",
     "v8.12.12 Obj-B: exculpatory variance verdict resurfaced in S1.3 large-loss"),
    ("gem_report_draft/sections_xiii.py", "🎲 unclassified variance",
     "v8.12.12 Obj-B: exculpatory variance verdict resurfaced in S17.6 large-loss"),
    ("gem_villain_intel.py", "+ ('s' if suited else 'o')",
     "v8.12.9: JJo-producing label builder resurfaced"),
    # v8.12.12 Obj-F: the BB-only "= equal" cover fallback must stay retired
    # (every villain seat is now compared to Hero from the real chip stacks).
    ("gem_report_draft/sections_xiv.py", "vs_str = '= equal'",
     "v8.12.12 Obj-F: BB-only '= equal' cover fallback resurfaced"),
    # v8.12.11 GPT-3: the old broad auto_clear gate must stay retired.
    ("gem_analyst_worklist.py", "is_premium or (eff and eff <= 22)",
     "v8.12.11 GPT-3: broad auto_clear gate resurfaced (premium-OR-short)"),
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        data = f.read()
    if data[:3] == b'\xef\xbb\xbf':
        data = data[3:]
    h.update(data)
    return h.hexdigest(), len(data)


def _resolve_path(project_dir, rel_path):
    """Resolve a manifest/canary path, trying both packaged and loose layouts.

    The gem_report_draft renderer ships as 16 loose files at the project
    root (reassembled into gem_report_draft/ by Step 0).  This helper tries
    the canonical path first (gem_report_draft/foo.py), then falls back to
    the flat path (foo.py) so verify_release works in both layouts.
    """
    full = os.path.join(project_dir, rel_path)
    if os.path.exists(full):
        return full
    # Fallback: try the basename directly under project_dir
    if os.sep in rel_path or '/' in rel_path:
        flat = os.path.join(project_dir, os.path.basename(rel_path))
        if os.path.exists(flat):
            return flat
    return None


def verify(project_dir):
    print(f"GEM Release Integrity Verifier -- {VERSION}")
    print(f"Project: {os.path.abspath(project_dir)}")
    print("=" * 70)

    ok = 0
    stale = []
    missing = []

    # 1. Hash check every file in manifest
    print(f"\n[1/4] File hash verification ({len(MANIFEST)} files)")
    for rel_path, (expected_hash, expected_size, desc) in sorted(MANIFEST.items()):
        full = _resolve_path(project_dir, rel_path)
        if not full:
            missing.append((rel_path, desc))
            print(f"  MISSING  {rel_path}  ({desc})")
            continue
        actual_hash, actual_size = sha256_file(full)
        if actual_hash != expected_hash:
            stale.append((rel_path, desc, expected_size, actual_size))
            print(f"  STALE    {rel_path}  (hash mismatch, {desc})")
            if actual_size != expected_size:
                print(f"           expected {expected_size} bytes, got {actual_size}")
        else:
            ok += 1

    # 2. Canary string checks (catch specific fix regressions)
    print(f"\n[2/4] Canary checks ({len(CANARIES)} fix markers)")
    canary_pass = 0
    canary_fail = []
    for rel_path, needle, label in CANARIES:
        full = _resolve_path(project_dir, rel_path)
        if not full:
            canary_fail.append((rel_path, label, "file missing"))
            print(f"  FAIL  {label}")
            print(f"        {rel_path} not found")
            continue
        with open(full, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        if needle in content:
            canary_pass += 1
        else:
            canary_fail.append((rel_path, label, "string not found"))
            print(f"  FAIL  {label}")
            print(f"        expected '{needle}' in {rel_path}")

    # 3. Anti-canary checks (old bug patterns must NOT be present)
    # v8.12.0a (handover 2026-06-11): _gtow_situations.json is required
    # for the stacks= param in GTOW URLs. Absence is a WARN, not a
    # failure - GTOW falls back to a default stack row (grids render).
    _sit = _resolve_path(project_dir, "_gtow_situations.json")
    if not _sit:
        print("\n  WARN  _gtow_situations.json not found - stacks= "
              "will be omitted from all GTOW URLs (GTOW picks a "
              "default stack row).")

    print(f"\n[3/4] Anti-canary checks ({len(ANTI_CANARIES)} old bug patterns)")
    anti_pass = 0
    anti_fail = []
    for rel_path, needle, label in ANTI_CANARIES:
        full = _resolve_path(project_dir, rel_path)
        if not full:
            anti_pass += 1  # file missing = bug can't be present
            continue
        with open(full, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        if needle in content:
            anti_fail.append((rel_path, label))
            print(f"  REGRESSED  {label}")
            print(f"             found '{needle}' in {rel_path}")
        else:
            anti_pass += 1

    # 4. Package structure check
    print(f"\n[4/4] Package structure")
    pkg_dir = os.path.join(project_dir, 'gem_report_draft')
    if os.path.isdir(pkg_dir):
        pkg_files = [f for f in os.listdir(pkg_dir) if f.endswith('.py')]
        print(f"  gem_report_draft/ has {len(pkg_files)} .py files (assembled package)")
    else:
        # Loose layout: renderer files at top level (pre-Step 0)
        _renderer_names = {'draft.py', '_html.py', '_helpers.py',
                           'sections_financial.py', 'sections_xiv.py',
                           'sections_iv_xii.py', '_state.py', '_hand_grid.py',
                           'sections_issue_explorer.py'}
        loose = [f for f in os.listdir(project_dir)
                 if f.endswith('.py') and f in _renderer_names]
        print(f"  gem_report_draft/ not assembled — {len(loose)} renderer files at top level (loose layout)")

    # Summary
    print("\n" + "=" * 70)
    total = len(MANIFEST)
    all_ok = not stale and not missing and not canary_fail and not anti_fail
    if all_ok:
        print(f"[PASS] All {ok}/{total} files match, {canary_pass}/{len(CANARIES)} canaries pass, "
              f"{anti_pass}/{len(ANTI_CANARIES)} anti-canaries pass.")
        print(f"       Project is a clean {VERSION} copy.")
        return True
    else:
        print(f"[FAIL] {ok}/{total} files OK, {len(stale)} stale, {len(missing)} missing, "
              f"{len(canary_fail)} canary failures, {len(anti_fail)} regressions.")
        if stale:
            print(f"\n  Stale files (copy from release folder to fix):")
            for rel, desc, exp_sz, act_sz in stale:
                print(f"    {rel}  ({desc})")
        if missing:
            print(f"\n  Missing files:")
            for rel, desc in missing:
                print(f"    {rel}  ({desc})")
        if canary_fail:
            print(f"\n  Failed canaries (specific fixes not present):")
            for rel, label, reason in canary_fail:
                print(f"    {label}: {reason} in {rel}")
        if anti_fail:
            print(f"\n  REGRESSIONS (old bug patterns found):")
            for rel, label in anti_fail:
                print(f"    {label} in {rel}")
        return False


def generate_manifest(release_dir):
    """Regenerate MANIFEST dict from a release folder (for future versions)."""
    print(f"Generating manifest from {release_dir}...")
    items = {}
    for root, dirs, files in os.walk(release_dir):
        for fn in sorted(files):
            if not (fn.endswith('.py') or fn.endswith('.txt')):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, release_dir).replace('\\', '/')
            h, sz = sha256_file(full)
            items[rel] = (h, sz)
            print(f'    "{rel}": ("{h}", {sz}, ""),')
    print(f"\n{len(items)} files.")


if __name__ == '__main__':
    if '--generate' in sys.argv:
        release_dir = sys.argv[sys.argv.index('--generate') + 1] if len(sys.argv) > sys.argv.index('--generate') + 1 else '.'
        generate_manifest(release_dir)
    else:
        # Default: verify the parent directory (project root)
        if '--project-dir' in sys.argv:
            idx = sys.argv.index('--project-dir')
            proj = sys.argv[idx + 1]
        else:
            proj = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
        success = verify(proj)
        sys.exit(0 if success else 1)
