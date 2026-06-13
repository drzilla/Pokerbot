#!/usr/bin/env python3
"""
gem_run.py — Single-command orchestration for a GEM session.

Replaces the prior ad-hoc workflow (run analyzer → manually call render_html →
manually move files to outputs → manually write run_log) with one entry point
that covers the full pipeline:

  1. (Optional) Run test suites and gate on failures
  2. Parse the session and compute stats (gem_analyzer)
  3. Schema-validate the data flowing into the renderer
  4. Emit analyst_candidates_<date>.json (typed buckets for the analyst step)
  5. If session_analysis_<date>.json is present, load it as analyst commentary
  6. Render HTML primary + MD secondary to /mnt/user-data/outputs/
  7. Print a clean summary

Usage:
  python3 gem_run.py /path/to/session/dir/ [--name session_name]
                                            [--no-tests] [--strict-schema]
                                            [--section <Roman>]

The --section flag (deferred — placeholder for partial-render mode that lets
you target only specific report sections, saving tokens on follow-up reads.)

This is a thin orchestrator. Heavy lifting stays in gem_analyzer / gem_parser /
gem_report_data / gem_report_draft modules.
"""

import argparse
import os
import subprocess
import sys


def run_test_suites(strict=False):
    """Run the four test suites; return (n_passed, n_failed, blocking).

    blocking=True if strict mode and any failures detected.
    """
    suites = ['test_parser.py', 'test_detectors.py', 'test_solver.py', 'test_metrics.py']
    here = os.path.dirname(os.path.abspath(__file__)) or '.'
    failures = []
    print(f"{'='*60}\nTEST SUITES (v7.36 D-pipeline gate)\n{'='*60}")
    for suite in suites:
        path = os.path.join(here, suite)
        if not os.path.exists(path):
            # Try /mnt/project as fallback (tests live alongside the modules)
            alt = os.path.join('/mnt/project', suite)
            if os.path.exists(alt):
                path = alt
            else:
                print(f"  ⚠ {suite} not found — skipping")
                continue
        try:
            r = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=180)
            if r.returncode == 0:
                # Parse "X tests passed" or similar from output
                last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ''
                print(f"  ✓ {suite}  {last[:80]}")
            else:
                print(f"  ✗ {suite}  exit code {r.returncode}")
                tail = r.stdout.strip().splitlines()[-3:] if r.stdout.strip() else []
                for ln in tail:
                    print(f"      {ln}")
                failures.append(suite)
        except subprocess.TimeoutExpired:
            print(f"  ✗ {suite}  TIMEOUT (>180s)")
            failures.append(suite)
        except Exception as e:
            print(f"  ✗ {suite}  exception: {e}")
            failures.append(suite)
    print(f"\n  Test suites: {len(suites) - len(failures)}/{len(suites)} passed")
    blocking = bool(failures) and strict
    if failures and not strict:
        print(f"  ⚠ {len(failures)} suite(s) failing; not blocking (use --strict-schema "
              f"to gate)")
    return (len(suites) - len(failures), len(failures), blocking)


def run_pipeline(session_dir, session_name, run_tests=True, strict_schema=False,
                  section=None, analyst_file=None, require_analyst=False,
                  strict_lint=False, qa_block=False, gtow_links=False,
                  gtow_manifest=False, player=None, quick=False,
                  reanalyze=False, render_only=False):
    """Run the full pipeline on session_dir."""
    # v8.4.0: fail-fast if phevaluator is missing (needed by equity enrichment + ranges)
    try:
        import phevaluator
    except ImportError:
        print("\n⚠️  phevaluator not installed. Run:")
        print("    pip install phevaluator")
        print("  Without it: equity enrichment skipped, range checks fail at render.\n")

    # Phase 3 lint: propagate flags via env vars so the renderer picks them
    # up without modifying gem_analyzer.py's call to render_html().
    if strict_lint:
        os.environ['GEM_STRICT_LINT'] = '1'
    if qa_block:
        os.environ['GEM_QA_BLOCK'] = '1'
    if gtow_links:
        os.environ['GEM_GTOW_LINKS'] = '1'
    if gtow_manifest:
        os.environ['GEM_GTOW_MANIFEST'] = '1'
    if run_tests:
        passed, failed, blocking = run_test_suites(strict=strict_schema)
        if blocking:
            print("\n  BLOCKED — fix test failures or re-run with --no-tests")
            return 1

    # Delegate to gem_analyzer's main pipeline. The analyzer already handles
    # parser → analyzer → report_data → schema_validation → analyst_candidates →
    # render_html → render_md → outputs/ in v7.36, so this is just a wrapper.
    here = os.path.dirname(os.path.abspath(__file__)) or '.'
    analyzer = os.path.join(here, 'gem_analyzer.py')
    if not os.path.exists(analyzer):
        analyzer = '/mnt/project/gem_analyzer.py'
    print(f"\n{'='*60}\nGEM PIPELINE → {session_dir}\n{'='*60}")
    cmd = [sys.executable, analyzer, session_dir, session_name]
    if player:
        cmd.extend(['--player', player])
    if quick:
        cmd.append('--quick')
    if reanalyze:
        cmd.append('--reanalyze')
    if render_only:
        cmd.append('--render-only')
    if section:
        cmd.extend(['--section', section])
    if analyst_file:
        cmd.extend(['--analyst-file', analyst_file])
    if require_analyst:
        cmd.append('--require-analyst')
    r = subprocess.run(cmd)
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description='GEM session pipeline.')
    ap.add_argument('session_dir', help='Directory containing GG hand history files')
    ap.add_argument('--name', default='session', help='Session name label')
    ap.add_argument('--no-tests', action='store_true',
                    help='Skip test-suite gate (faster for iteration)')
    ap.add_argument('--strict-schema', action='store_true',
                    help='Fail run if any test suite fails or schema validation fails')
    ap.add_argument('--section', default=None,
                    help='Render only a subset of sections (e.g. III or III,IV,XIII). '
                         'Output filename gets a _section_<roman>... suffix.')
    ap.add_argument('--analyst-file', default=None,
                    help='Explicit path to session_analysis_*.json. Overrides '
                         'the search-order resolution (Fix B).')
    ap.add_argument('--require-analyst', action='store_true',
                    help='Hard-fail if analyst coverage is incomplete. Use on '
                         're-runs where full analyst verdicts are expected (Fix A).')
    ap.add_argument('--strict-lint', action='store_true',
                    help='Hard-fail if the Phase 3 structural linter finds '
                         'any BLOCKER-severity findings.')
    ap.add_argument('--qa-block', action='store_true',
                    help='Append a collapsed QA lint report to the rendered '
                         'output (post-appendix). Off by default.')
    ap.add_argument('--gtow-links', action='store_true',
                    help='Enable per-hand GTOW simulation links in the appendix. '
                         'Off by default — enable only after manually verifying '
                         'the manifest sample URLs against gtowizard.com.')
    ap.add_argument('--gtow-manifest', action='store_true',
                    help='Build _gtow_manifest.json with per-hand GTOW URLs for '
                         'manual sample-testing. Links remain OFF in the report.')
    ap.add_argument('--player', default=None,
                    help='Player name for multi-player support. Scopes output '
                         'filenames, auto-isolates non-Ron data.')
    ap.add_argument('--quick', action='store_true',
                    help='Quick re-render: skip parse+analyze, load cached data, '
                         're-render only (~3s vs ~30s). Use after analyst edits.')
    ap.add_argument('--render-only', action='store_true',
                    help='Render-only mode: load cached hands+stats+report_data, '
                         'attach analyst file, refresh discipline tier, render. '
                         'Analyst file is NOT part of the cache hash. ~3-5s.')
    ap.add_argument('--reanalyze', action='store_true',
                    help='Re-analyze: load cached hands (skip parse), re-run '
                         'analyze+render. Use when detector logic changes.')
    ap.add_argument('--diff', default=None, metavar='OLD.html',
                    help='Compare the new report against OLD.html and print '
                         'a structured diff of what changed.')
    args = ap.parse_args()
    rc = run_pipeline(args.session_dir, args.name,
                      run_tests=(not args.no_tests),
                      strict_schema=args.strict_schema,
                      section=args.section,
                      analyst_file=args.analyst_file,
                      require_analyst=args.require_analyst,
                      strict_lint=args.strict_lint,
                      qa_block=args.qa_block,
                      gtow_links=args.gtow_links,
                      gtow_manifest=args.gtow_manifest,
                      player=args.player,
                      quick=args.quick,
                      reanalyze=args.reanalyze,
                      render_only=getattr(args, 'render_only', False))
    sys.exit(rc)


if __name__ == '__main__':
    main()
