"""Phase 4 anchor mapping — old Roman-numeral anchors to new Arabic anchors.

Populated in commit 4.  Every doc.section / doc.subsection call now uses the
new S-notation anchor (sec-1, sec-2-1, …).  The compat layer in Doc emits
invisible redirect spans for the old anchors so existing URLs still resolve.

ANCHOR_MAP: {'sec-iii-1': 'sec-2-1', ...}  — old → new
REVERSE_MAP: {'sec-2-1': 'sec-iii-1', ...} — new → old

Segment assignment (Coach-first 18-segment order):
  S1  = I    (Reality Check)         S10 = VII  (3BP/4BP Postflop)
  S2  = III  header+punts+mistakes   S11 = VIII (Macro Postflop)
  S3  = III  strategic leaks         S12 = IX   (Leak Persistence)
  S4  = III  clinical/picks          S13 = III  cleared/justified
  S5  = IV   (Action Card)           S14 = X    (Pipeline Bugs)
  S6  = II   verdict+KPIs            S15 = XI   (Stat Reference)
  S7  = II   mental+bluff            S16 = XII  (Glossary)
  S8  = V    (Pre-Flop Engine)       S17 = XIII (Deviation Lists)
  S9  = VI   (Post-Flop SRP)         S18 = XIV  (Appendix)

Dynamic anchors (runtime-generated, NOT in this static map):
  sec-iii-2-{i}              → sec-3-{i}
  sec-iii-7-ev-{slug}        → sec-4-2-ev-{slug}
  sec-viii-11-{st}-{verdict}  → sec-11-11-{st}-{verdict}
  sec-xiii-1-{pos}            → sec-17-1-{pos}
  sec-xiii-2-vs-{opener}      → sec-17-2-vs-{opener}
  sec-xiii-3-{pos}            → sec-17-3-{pos}
"""

ANCHOR_MAP = {
    # ── S1 = Section I (Reality Check) ──────────────────────────
    'sec-i':    'sec-1',
    'sec-i-0b': 'sec-1-0b',
    'sec-i-0':  'sec-1-0',
    'sec-i-0a': 'sec-1-0a',
    'sec-i-1':  'sec-1-1',
    'sec-i-2':  'sec-1-2',
    'sec-i-3':  'sec-1-3',
    'sec-i-4':  'sec-1-4',
    'sec-i-5':  'sec-1-5',
    'sec-i-6':  'sec-1-6',
    'sec-i-7':  'sec-1-7',
    'sec-i-8':  'sec-1-8',
    'sec-i-9':  'sec-1-9',

    # ── S2 = Section III header + punts + confirmed mistakes ────
    'sec-iii':              'sec-2',
    'sec-iii-1':            'sec-2-1',
    'sec-iii-2-confirmed':  'sec-2-2',

    # ── S3 = Section III strategic leaks ────────────────────────
    'sec-iii-2': 'sec-3',

    # ── S4 = Section III clinical / picks ───────────────────────
    'sec-iii-6': 'sec-4-1',
    'sec-iii-7': 'sec-4-2',
    'sec-iii-8': 'sec-4-3',

    # ── S5 = Section IV (Action Card & GTO Shortlist) ───────────
    'sec-iv':   'sec-5',
    'sec-iv-1': 'sec-5-1',
    'sec-iv-2': 'sec-5-2',
    'sec-iv-3': 'sec-5-3',
    'sec-iv-4': 'sec-5-4',
    'sec-iv-5': 'sec-5-5',
    'sec-iv-6': 'sec-5-6',
    'sec-iv-7': 'sec-5-7',
    'sec-iv-8': 'sec-5-8',

    # ── S6 = Section II header + verdict + KPIs ─────────────────
    'sec-ii':   'sec-6',
    'sec-ii-1': 'sec-6-1',
    'sec-ii-2': 'sec-6-2',

    # ── S7 = Section II mental game + bluff + exploits ──────────
    'sec-ii-3': 'sec-7-1',
    'sec-ii-4': 'sec-7-2',
    'sec-ii-5': 'sec-7-3',

    # ── S8 = Section V (Pre-Flop Engine) ────────────────────────
    'sec-v':   'sec-8',
    'sec-v-1': 'sec-8-1',
    'sec-v-2': 'sec-8-2',
    'sec-v-3': 'sec-8-3',
    'sec-v-4': 'sec-8-4',
    'sec-v-5': 'sec-8-5',
    'sec-v-6': 'sec-8-6',
    'sec-v-7': 'sec-8-7',
    'sec-v-8': 'sec-8-8',

    # ── S9 = Section VI (Post-Flop SRP) ─────────────────────────
    'sec-vi':   'sec-9',
    'sec-vi-1': 'sec-9-1',
    'sec-vi-2': 'sec-9-2',
    'sec-vi-3': 'sec-9-3',
    'sec-vi-4': 'sec-9-4',
    'sec-vi-5': 'sec-9-5',

    # ── S10 = Section VII (3BP & 4BP Postflop) ──────────────────
    'sec-vii': 'sec-10',

    # ── S11 = Section VIII (Macro Post-Flop Mechanics) ──────────
    'sec-viii':             'sec-11',
    'sec-viii-1':           'sec-11-1',
    'sec-viii-2':           'sec-11-2',
    'sec-viii-3':           'sec-11-3',
    'sec-viii-4':           'sec-11-4',
    'sec-viii-4b':          'sec-11-4b',
    'sec-viii-5':           'sec-11-5',
    'sec-viii-6':           'sec-11-6',
    'sec-viii-7':           'sec-11-7',
    'sec-viii-7-avoidable': 'sec-11-7-avoidable',
    'sec-viii-8':           'sec-11-8',
    'sec-viii-9':           'sec-11-9',
    'sec-viii-10':          'sec-11-10',
    'sec-viii-11':          'sec-11-11',

    # ── S12 = Section IX (Leak Persistence) ─────────────────────
    'sec-ix':   'sec-12',
    'sec-ix-1': 'sec-12-1',
    'sec-ix-2': 'sec-12-2',

    # ── S13 = Section III cleared / justified ───────────────────
    'sec-iii-3': 'sec-13-1',
    'sec-iii-4': 'sec-13-2',
    'sec-iii-5': 'sec-13-3',

    # ── S14 = Section X (Pipeline Bug Tracker) ──────────────────
    'sec-x': 'sec-14',

    # ── S15 = Section XI (Complete Stat Reference) ──────────────
    'sec-xi': 'sec-15',

    # ── S16 = Section XII (Glossary) ────────────────────────────
    'sec-xii': 'sec-16',

    # ── S17 = Section XIII (Full Deviation Lists) ───────────────
    'sec-xiii':             'sec-17',
    'sec-xiii-1':           'sec-17-1',
    'sec-xiii-2':           'sec-17-2',
    'sec-xiii-3':           'sec-17-3',
    'sec-xiii-4':           'sec-17-4',
    'sec-xiii-4-confirmed': 'sec-17-4-confirmed',
    'sec-xiii-4-marginal':  'sec-17-4-marginal',
    'sec-xiii-4-tail':      'sec-17-4-tail',
    'sec-xiii-4-review':    'sec-17-4-review',
    'sec-xiii-4-reviewed':  'sec-17-4-reviewed',
    'sec-xiii-4-autocorr':  'sec-17-4-autocorr',
    'sec-xiii-5':           'sec-17-5',
    'sec-xiii-6':           'sec-17-6',
    'sec-xiii-7':           'sec-17-7',

    # ── S18 = Section XIV (Appendix) ────────────────────────────
    'sec-xiv': 'sec-18',
}

REVERSE_MAP = {v: k for k, v in ANCHOR_MAP.items()}
