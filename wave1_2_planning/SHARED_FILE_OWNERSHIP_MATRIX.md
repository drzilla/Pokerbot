# Shared-File Ownership Matrix — Wave 1 + Wave 2 (v8.18.0 train)

One owner per shared fact. No two lanes may independently redefine the same fact. A lane that needs a
shared fact CONSUMES the owner read-only. Filled from the W1-A recon (`wave1a-recon`).

## Shared facts → single owner

| Shared fact | Single owner (file:symbol) | Consumers (read-only) | Locked by |
|---|---|---|---|
| Top-level report generator | `gem_report_data.py:prepare_report_data` → `gem_report_draft/draft.py:render_html` | every section renderer | verify_release manifest |
| Per-hand canonical verdict | `gem_report_draft/_helpers.py:build_canonical_verdicts` (→ `gem_review_trust.resolve_canonical_verdict`) | topbar, grid, capsule, queue, hand-list | manifest + canary |
| **Canonical Final Decision Status** | **`gem_final_status.py:derive_final_status`** (stamped onto `cv['final_status']` in `build_canonical_verdicts`) | every status surface (card root, pill, topbar) | manifest + 6 canaries |
| **Status serialization (typed)** | **`gem_final_status.py:FinalStatus.to_dict/from_dict`** | lazy payload + static shell (one value) | T-W1A-07 + manifest |
| **Status rendering (HTML)** | **`gem_final_status.py:final_status_pill_html`** (the ONLY status-pill HTML producer) | sections_xiv both card paths | canary + T-W1A-08 |
| **Status-contradiction QA** | **`_qa_status_consistency.py:run_status_consistency`** | the suite (T-W1A-09/10) + the real-report gate | manifest + canary |
| Gradeability (UNGRADED contract) | `gem_decision_snapshot.py:decision_grade_eligibility` (+ `build_decision_snapshot.no_hero_decision`) | gem_final_status.hand_gradeability | REV13 canary (frozen) |
| Action sizing / row identity | `gem_decision_snapshot.py:canonical_action_replay` + the frozen `acceptance/` gates | the grid renderer (REV17) | **REV17 frozen — W1-A does not touch** |
| Navigation registry / anchors | `gem_report_draft/_anchor_map.py` + `_html.py:section anchors` | all sections | manifest |
| Global CSS / colour tokens | `gem_report_draft/_html.py` (`:root` custom props + the pill CSS block) | all pills/badges | manifest + canary |
| Shared JS bootstrap | `gem_report_draft/_html.py` (lazy loader, topbar hydrate, popup) | the page | manifest |
| Lazy payload schema | `gem_report_draft/_html.py` (`PB_PAYLOADS` lazyHands) + `_qa_decode_lazy.py` | the report + every QA gate | manifest |
| Package / version metadata | `gem_version.py:RUNTIME_VERSION` (+ `verify_release.VERSION`, `_build_bundle.BUNDLE_VERSION`) | manifest / worklist / footer | self-canary |
| Review state (analyst) | the review controls / store (`.verdict-chip`, `.status-pill` review queue) | review surfaces only | **SEPARATE from system status — never crosses** |

## W1-A ownership boundary (this execution)

W1-A **created** `gem_final_status.py` (status owner + serialization + rendering) and
`_qa_status_consistency.py` (status QA), and **stamps** the status onto `cv['final_status']` in the
existing `build_canonical_verdicts` owner. It **consumes read-only**: the canonical verdict
(`gem_review_trust`), gradeability (`gem_decision_snapshot`), and the EAI suckout/flip facts on the
hand. It **does not touch**: action sizing, the REV17 row-binding / ownership contract, the frozen
`acceptance/` gates, tournament truth, or the lazy-payload schema. Review state remains a separate
owner that the system status never reads and that never sets the system status.

## Future-lane reservations (not implemented this execution)

| Future lane | Will own | Must consume (not redefine) |
|---|---|---|
| W2-A Commentary Capsule | the capsule register + zero-drop ledger | the canonical status + verdict |
| W2-B Villain Teaching | the 7-part teaching contract | villain chronology/identity |
| H4 PokerHandDisplay | `CardVM`/`HandVM` + `render_poker_hand` | the hand data (no re-markup) |
| W1-B Tournament Results | the typed event/bullet/multi-day model | the results truth (no recompute) |
| R2 DataTable | the typed table foundation | the data it renders |
