"""Single source of truth for the GEM runtime/release version.

v8.14.1-preview (real-report QA hotfix): generated outputs were stamping
INCONSISTENT versions — the run manifest used the report-FORMAT version
(gem_report_draft.draft.VERSION, pinned at v8.12.0), the villain worksheet
hard-coded 'v8.9.0', and the worklist carried yet another string. They must all
report ONE runtime/release version. This constant is that source.

NOTE: this is the *runtime/release* version (what code is running). It is
DISTINCT from gem_report_draft.draft.VERSION, which is the report-FORMAT version
(the layout/schema of the rendered report) and is intentionally pinned + canary-
checked. Metadata emitters (run manifest, analyst worklist, villain worksheet,
report footer) should reference RUNTIME_VERSION; the report-format version stays
in draft.VERSION.
"""

RUNTIME_VERSION = 'v8.14.4'
