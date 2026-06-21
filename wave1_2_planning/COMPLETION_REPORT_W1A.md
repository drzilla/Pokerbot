# Wave-1A — Canonical Final Decision Status — Completion Report (v8.18.0 checkpoint)

Branch `feature/wave1a-canonical-status` off the released `main @ 378846b` (tag `v8.17.1`, held).
This is a **Wave-1A checkpoint**, not the final v8.18.0 release: no merge / tag / push, no other lane.

## What shipped

One canonical **Final Decision Status** owner drives every status surface, so a hand can never show a
contradictory or blank status, and a result never silently becomes a strategic grade.

- **`gem_final_status.py`** (new owner): `FinalDecisionStatus` = MISTAKE | CONDITIONAL | CLEARED |
  UNGRADED, with SEPARATE secondary reasons SUCKOUT/FLIP/COOLER/JUSTIFIED/READ_DEPENDENT. Typed
  (`FinalStatus` dataclass, `to_dict`/`from_dict` for a future web frontend), with the precedence fold
  (`combine_statuses`), the verdict-code-authoritative classifier (`status_from_canonical_verdict`),
  the gradeability bridge (`hand_gradeability` → `decision_grade_eligibility`), and the SINGLE
  status-pill HTML producer (`final_status_pill_html`). Status is derived from canonical decision
  evidence + gradeability, **never the result alone**; review state is never consulted.
- **`gem_report_draft/_helpers.py:build_canonical_verdicts`** stamps `cv['final_status']` once, in the
  data layer, onto the same `cv` every surface already reads.
- **`gem_report_draft/sections_xiv.py`** (both hand-detail-card paths): stamp `data-final-status` on
  the card root and render the canonical pill as the primary status; the verdict-nuance pill is kept
  only when it adds information (Punt/Correct/Pick), dropped when it would merely repeat the status.
- **`gem_report_draft/_html.py`**: `.final-status-pill` CSS (distinct mistake/conditional/cleared/
  ungraded colours, desktop + mobile), the inline-whitelist passes the pill through markdown, and the
  sticky top bar mirrors the canonical status pill (verdict-pill fallback kept).
- **`_qa_status_consistency.py`** (new gate): every hand exactly one status; no CLEARED/UNGRADED shows
  a mistake pill; pill == card; reports the distribution. Wired into the suite (T-W1A-09/10).

Because the lazy hand body **is** the same `<article>` HTML, the static shell and the lazy payload
carry one identical serialized status — they cannot disagree.

## Required-outcome checklist (all met)

1. one canonical status drives every touched surface — yes (data layer → both card paths → topbar).
2. no hand says MISTAKE without a graded action error — yes (only a Punt/Mistake verdict; gate C3/C4).
3. cleared hands show CLEARED, not blank — yes (839/844 on the real report were previously blank).
4. result-only hands are not strategically graded — yes (UNGRADED; real `84078253` forced all-in).
5. review state never redefines the system status — yes (status never reads Agree/Debate; separate).
6. lazy and static representations agree — yes (one article HTML).
7. summary/list/header/commentary labels do not contradict — yes (0 contradictions, both reports).

## Validation

| Check | Result |
|---|---|
| Unit suite | **1774 / 1774** (1763 base + 11 T-W1A) |
| `verify_release` | **58/58 files, 618 canaries, 12 anti** (+2 modules, +6 W1-A canaries) |
| Clean-extract | **150-file bundle** → clean-room verify 58/58 + suite PASS |
| Parity A–R (REV17 frozen) | **PASS** (P 3177 sized/0, Q 0 fallback, R 0 dead-blind) |
| Holdout | **0 semantic violations** |
| Frozen Stage-F seeds | **45/45** (gates untouched, read-only) |
| Status-contradiction gate (real AUTO_ONLY) | **0 contradictions** over 844 hands |
| Status-contradiction gate (analyst demo) | **0 contradictions** over 844 hands |
| Browser smoke (desktop 1280 + mobile 375) | pills render distinct/readable; **no overflow** at 375px |

## Status distribution (real June-16 report)

- **AUTO_ONLY** (no analyst, the canonical real report): CLEARED 839 · UNGRADED 5 — secondary
  JUSTIFIED 26. Zero MISTAKE is correct: no analyst- or auto-confirmed error exists, so the system
  invents none.
- **Analyst demo** (5 real hands reviewed, to exercise the full taxonomy): CLEARED 836 · MISTAKE 2 ·
  CONDITIONAL 1 · UNGRADED 5 — secondary COOLER 1, READ_DEPENDENT 1, JUSTIFIED 26.

## Representative before → after (real hands)

| Case | Hand | Before | After |
|---|---|---|---|
| Genuine MISTAKE | 84611155 | verdict pill only (would double) | **Mistake** |
| MISTAKE + Punt nuance | 84611067 | — | **Mistake** · Punt |
| CLEARED + Cooler | 84611627 | blank | **Cleared** · Cooler |
| CONDITIONAL + Read-dependent | 84611544 | blank | **Conditional** · Read-dependent |
| CLEARED + Justified | 83507453 | "Justified Justified"-risk | **Cleared** · Justified |
| UNGRADED (forced all-in) | 84078253 | (no status) | **No decision** |
| Previously blank → CLEARED | 84032086 | blank | **Cleared** |

## Measurements (before → after)

- Generated HTML (AUTO_ONLY, 844 hands): 2,636,645 → **2,793,734 bytes (+5.96%)** — a status on every
  hand, base64-inflated in the lazy payload (the per-pill tooltip was dropped to keep this lean; the
  rationale stays in the typed dict).
- Source bundle: **148 → 150 files** (+`gem_final_status.py`, +`_qa_status_consistency.py`).
- Runtime: quick re-render ~7.8 s (844 hands); the owner adds one decision-snapshot read per hand in
  the data layer.

## Known non-blocking debt

- The verdict-nuance pill still appears beside the status for III.3 (`Cleared` + `Correct`) — semantically
  consistent, mildly redundant; a later pass can fold `Correct`/`Standard` into the cleared synonym set.
- Status legend: the four labels are self-explanatory but a one-line legend block would aid first-time
  readers (the rationale text already lives in the typed dict).
- Carried from REV17 (unchanged, out of scope): holdout frozen-gate zero counters; the 0.12/0.1BB
  attribute; `_qa_report_deep.py` regex.

## Not done (staged for the next combined packet)

W2-A Commentary Capsule · W2-B Villain Teaching · H4 PokerHandDisplay · W1-B Tournament Results ·
R2 DataTable · the lean Claude Chat runtime package. No Wave 3. Awaits one GPT acceptance of this
checkpoint + one Ron product review.
