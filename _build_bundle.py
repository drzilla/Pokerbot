#!/usr/bin/env python3
"""Build gem_src_bundle.py — the self-extracting Chat-project bundle.

v9-capacity architecture (2026-06-12): the Chat project rejects .zip uploads,
so the entire runtime (source + machine data + suite) ships as ONE .py file
carrying a deflate-zip as base64. Sessions run it once at STEP0 and work in
the extracted tree. Prose docs (QR, checklists, references) stay FLAT in the
project so Chat can read them directly — they are NOT bundled.

Usage:  python _build_bundle.py [--project-zip-dir DIR]
Source preference: this repo's copy (authoritative, current release);
falls back to the extracted project zip for keep-files this repo lacks.
"""
import base64, io, os, sys, zipfile, hashlib, datetime

REPO = os.path.dirname(os.path.abspath(__file__))
PROJ_FALLBACK = r'C:\Users\ron\Downloads\_proj_inventory\project'

BUNDLE_VERSION = 'v8.17.1'

# gem_report_draft package members (zipped under gem_report_draft/)
PKG = ['__init__.py', '_state.py', '_helpers.py', '_html.py', '_hand_grid.py',
       '_blocks.py', '_anchor_map.py', '_adapters.py', 'draft.py', 'tldr.py',
       'sections_financial.py', 'sections_mistakes.py', 'sections_iv_xii.py',
       'sections_xiii.py', 'sections_xiv.py', 'sections_issue_explorer.py',
       'sections_tournaments.py']   # v8.15: additive Tournament Tables section

# v8.17.0-rc3 (audit B6): the QA acceptance/decoder harnesses must extract WITH
# the runtime so the README self-verify commands (e.g. `python
# _qa_v817_rc3_acceptance.py`) work directly from the bundle — RC2 shipped them
# package-level only, so the documented command failed from the extracted dir.
QA_HARNESS = ['_qa_v817_rc3_acceptance.py', '_qa_v817_synthetic.py',
              '_qa_v817_assert.py', '_qa_v817_rc2_assert.py', '_qa_decode_lazy.py',
              # v8.17.1 Iter-1 (REV3): the end-to-end parity/semantic gate is now a
              # suite dependency (_test_scratch imports it for the gate-catches tests),
              # so it must extract with the runtime or the clean-room suite breaks.
              '_qa_parity.py',
              # v8.17.1 Iter-1 (REV9): the real production-render holdout — the suite
              # (T-REV9-12) reads its source to prove it invokes render_html, so it must
              # extract with the runtime.
              '_qa_holdout.py']

# Stage-A kill list — never bundled
KILL = {
    'test_parser.py', 'test_report_draft.py', 'test_metrics.py',
    'test_detectors.py', 'test_blocks.py', 'test_lint.py', 'test_drill.py',
    'test_squares.py', 'test_gtow.py', 'test_pot_odds.py', 'test_textures.py',
    'test_solver.py', 'test_cev.py', 'test_coinpoker.py',
    'test_hand_evidence_tier1.py', 'test_skill_index.py', 'test_pko.py',
    'test_bounty.py', 'test_depth_segments.py', 'test_csv_row_complete.py',
    'test_hands.txt', 'test_hands_detectors.txt',
    'gem_drill.py', 'gem_skill_review.py', 'live_to_gg.py',
    'gem_meta_analysis.py', 'gem_drilldown_map.py', 'gem_squares_report.py',
    'gem_run.py', 'gem_report_diff.py', 'gem_leak_detector.py',
    'gem_range_estimator.py', 'live_session_template.py',
    'build_hand_index.py', 'gem_candidate_builder.py',
    # v8.12.6-cap2: the LOCAL dev runner must never reach Chat -- its
    # presence sent the first bundle-era session down the wrong entry
    # point (skips coverage builder / pot-odds / coaching cards).
    '_run_pipeline.py',
    # v8.12.11-preview (GPT-2): now that the file list unions repo modules
    # (below), two repo-present gem_*.py files must be explicitly excluded:
    'gem_src_bundle.py',          # the bundle's OWN output -- never self-include
    'gem_auto_verdict_SPEC.py',   # a design spec, not wired into the runtime
}

# Session-data CSVs stay FLAT in the project (Ron updates them periodically
# without a bundle rebuild). STEP0 copies them into the extracted tree --
# the resolvers glob CWD (local-first / Aviel-isolation pattern).
FLAT_DATA = {
    'session_financials.csv',
    'session_financials_per_tournament.csv',
    'session_history_merged_20251231_to_20260608_recalibrated.csv',
}

# Prose stays flat in the project (Chat-readable) — never bundled
PROSE = {
    'GEM_Quick_Reference.txt', 'GEM_Changelog.txt',
    'Analyst_Writing_Checklist.md', 'Mental_Game_Reference.txt',
    'Live_Poker_Population_Reference.txt', 'MDA_v7_5_Reference.txt',
    'GEM_Parser_Config.txt', 'GEM_Parser_Reference.txt',
    'GEM_GTO_Wizard_Guide.txt', 'GTOW_Chrome_Extension_Extraction_Guide.txt',
    'Live_Session_Guide.md', 'GTO_Texture_Archetypes.txt',
    'SESSION_START_STEP0_package_rebuild.txt', 'SESSION_START_STEP0.txt',
}


# Manifest-tracked prose: rides the bundle (verify_release hashes it there)
# AND is uploaded flat for Chat readability. Same repo source, same release.
BUNDLE_ALSO = {'GEM_Quick_Reference.txt', 'GEM_Changelog.txt',
               'SESSION_START_STEP0_package_rebuild.txt'}


def _repo_runtime_modules():
    """v8.12.11-preview (GPT-2): the file list used to come ONLY from the
    inventory snapshot, so new repo modules (gem_analyst_worklist.py,
    gem_chart_labels.py) were silently dropped from release bundles. Union in
    every repo-present gem_*.py runtime module (KILL still filters the
    non-shippers, incl. the bundle output + design specs)."""
    return {f for f in os.listdir(REPO)
            if f.startswith('gem_') and f.endswith('.py')
            and not f.endswith('_SPEC.py')
            and os.path.isfile(os.path.join(REPO, f))}


def build(project_dir):
    names = set()
    if os.path.isdir(project_dir):
        names = {f for f in os.listdir(project_dir)
                 if os.path.isfile(os.path.join(project_dir, f))}
    names |= _repo_runtime_modules()   # repo-driven: pick up new modules
    names |= BUNDLE_ALSO
    # v8.15: PKG members are bundled from the repo regardless of whether the
    # (possibly stale) inventory-snapshot project_dir lists them — so a NEW
    # gem_report_draft/ member (e.g. sections_tournaments.py) is never silently
    # dropped. Mirrors the _repo_runtime_modules() union for root modules.
    names |= set(PKG)
    # v8.17.0-rc3 (audit B6): bundle the QA acceptance/decoder harnesses from the
    # repo so the README self-verify commands run directly from the extracted ZIP.
    names |= set(QA_HARNESS)
    bundle_names = sorted(n for n in names
                          if n not in KILL and n not in FLAT_DATA
                          and (n not in PROSE or n in BUNDLE_ALSO))
    # The changelog ships flat; everything else by keep-list.
    buf = io.BytesIO()
    chosen = []
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n in bundle_names:
            if n in PKG:
                src = os.path.join(REPO, 'gem_report_draft', n)
                arc = f'gem_report_draft/{n}'
            else:
                src = os.path.join(REPO, n)
                arc = n
            if not os.path.isfile(src):
                src = os.path.join(project_dir, n)
                origin = 'project-zip'
            else:
                origin = 'repo'
            with open(src, 'rb') as f:
                z.writestr(arc, f.read())
            chosen.append((arc, origin))
    raw = buf.getvalue()
    b64 = base64.b64encode(raw).decode()
    lines = '\n'.join(b64[i:i+76] for i in range(0, len(b64), 76))
    sha = hashlib.sha256(raw).hexdigest()[:16]
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    n_repo = sum(1 for _, o in chosen if o == 'repo')
    n_proj = len(chosen) - n_repo
    out = f'''"""GEM source bundle -- self-extracting runtime for Chat sessions.

BUNDLE_VERSION = {BUNDLE_VERSION}   built {stamp}
files: {len(chosen)} ({n_repo} from repo, {n_proj} from prior project)
zip sha256[:16]: {sha}

STEP0 usage:
    python /mnt/project/gem_src_bundle.py /home/claude/gem
    cd /home/claude/gem
    python -c "import gem_report_draft, gem_analyzer; print('imports OK')"
    python verify_release.py --project-dir .
Prose docs (Quick Reference, Analyst checklist, references, changelog) are
NOT in here — read them directly from /mnt/project/.
"""
import base64, io, os, sys, zipfile

BUNDLE_VERSION = {BUNDLE_VERSION!r}

_B64 = """\\
{lines}"""


def extract(target):
    data = base64.b64decode(''.join(_B64.split()))
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(target)
        n = len(z.namelist())
    print(f'GEM bundle {{BUNDLE_VERSION}}: extracted {{n}} files -> {{target}}')
    return n


if __name__ == '__main__':
    extract(sys.argv[1] if len(sys.argv) > 1 else 'gem')
'''
    out_path = os.path.join(REPO, 'gem_src_bundle.py')
    # pure-ASCII output for maximum upload robustness
    out = out.replace('—', '--').replace('’', "'")
    with open(out_path, 'w', encoding='ascii', newline='\n') as f:
        f.write(out)
    print(f'bundle zip: {len(raw)/1024:.0f} KB | b64: {len(b64)/1024:.0f} KB '
          f'| gem_src_bundle.py: {os.path.getsize(out_path)/1024:.0f} KB')
    print(f'files: {len(chosen)} ({n_repo} repo / {n_proj} project-zip) '
          f'| sha {sha}')
    fallback_used = [a for a, o in chosen if o == 'project-zip']
    if fallback_used:
        print('from project zip (not in repo):',
              ', '.join(fallback_used[:20]))
    return out_path


if __name__ == '__main__':
    pd = PROJ_FALLBACK
    if '--project-zip-dir' in sys.argv:
        pd = sys.argv[sys.argv.index('--project-zip-dir') + 1]
    build(pd)
