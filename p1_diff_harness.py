#!/usr/bin/env python3
"""
P1 diff harness — proves the gem_report_draft package split is zero-behavior-change.

GATE 2 of the P1 procedure. Renders the report HTML + MD from BOTH:
  - the frozen pre-split module   (gem_report_draft_ORIG.py)
  - the new package               (gem_report_draft/)
on the same fixture session, and diffs byte-for-byte.

  Empty diff      -> split is provably behavior-neutral. Proceed.
  Non-empty diff  -> split broke something. Do NOT ship. Fix first.

PREREQUISITE (P1 procedure step 2):
  cp gem_report_draft.py gem_report_draft_ORIG.py    # before any edits

FIXTURE INPUTS:
  Real pipeline outputs from a recent session — gem_stats.json, gem_hands.json,
  gem_report_data.json. Point --stats/--hands/--report-data at them. These are the
  JSONs the analyzer writes; any recent real session works. The richer the session
  (mistakes, coolers, multi-tournament, appendix hands), the more of the renderer
  the diff exercises.

USAGE:
  python3 p1_diff_harness.py \
      --stats        gem_stats.json \
      --hands        gem_hands.json \
      --report-data  gem_report_data.json

Exit 0 = both diffs empty. Exit 1 = a diff is non-empty or a render raised.
"""
import argparse, difflib, importlib, json, sys, traceback


def _load(path, label):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        sys.exit(f"FATAL: could not load {label} from {path!r}: {e}")


def _render(modname, stats, report_data, hands):
    """Import a module/package by name and render HTML + MD. Returns (html, md)."""
    try:
        m = importlib.import_module(modname)
    except Exception:
        traceback.print_exc()
        sys.exit(f"FATAL: could not import {modname!r}. "
                 f"For ORIG: ensure gem_report_draft_ORIG.py exists. "
                 f"For the package: ensure gem_report_draft/ is built.")
    try:
        html = m.render_html(stats, report_data, hands)
        md   = m.render_md(stats, report_data, hands)
    except Exception:
        traceback.print_exc()
        sys.exit(f"FATAL: {modname}.render_* raised — render the fixture cleanly "
                 f"before trusting the diff.")
    return html, md


def _diff(old, new, fmt):
    """Byte-compare. Returns True if identical; prints a unified diff if not."""
    if old == new:
        print(f"  [{fmt}] IDENTICAL  ({len(new)} bytes)")
        return True
    o, n = old.splitlines(keepends=True), new.splitlines(keepends=True)
    ud = list(difflib.unified_diff(o, n, fromfile=f"ORIG.{fmt}",
                                   tofile=f"PACKAGE.{fmt}", n=3))
    print(f"  [{fmt}] !!! DIFFERS — {len(ud)} diff lines "
          f"(ORIG {len(old)} bytes, PACKAGE {len(new)} bytes)")
    # cap the printed diff so a large divergence stays readable
    for ln in ud[:200]:
        print("    " + ln.rstrip("\n"))
    if len(ud) > 200:
        print(f"    ... (+{len(ud) - 200} more diff lines)")
    return False


def main():
    ap = argparse.ArgumentParser(description="P1 byte-identical proof harness")
    ap.add_argument("--stats",       default="gem_stats.json")
    ap.add_argument("--hands",       default="gem_hands.json")
    ap.add_argument("--report-data", default="gem_report_data.json")
    ap.add_argument("--orig", default="gem_report_draft_ORIG",
                    help="module name of the frozen pre-split copy")
    ap.add_argument("--new",  default="gem_report_draft",
                    help="package name of the post-split build")
    a = ap.parse_args()

    stats       = _load(a.stats,       "stats")
    hands       = _load(a.hands,       "hands")
    report_data = _load(a.report_data, "report_data")

    print(f"Fixture: {a.stats}, {a.hands}, {a.report_data}")
    print(f"Rendering ORIG  ({a.orig}) ...")
    o_html, o_md = _render(a.orig, stats, report_data, hands)
    print(f"Rendering PACKAGE ({a.new}) ...")
    n_html, n_md = _render(a.new, stats, report_data, hands)

    print("\nByte-diff:")
    ok_html = _diff(o_html, n_html, "HTML")
    ok_md   = _diff(o_md,   n_md,   "MD")

    print()
    if ok_html and ok_md:
        print("GATE 2 PASS — HTML + MD byte-identical. Split is behavior-neutral.")
        sys.exit(0)
    print("GATE 2 FAIL — output diverged. Do NOT ship the split. Fix and re-run.")
    sys.exit(1)


if __name__ == "__main__":
    main()
