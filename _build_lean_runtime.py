#!/usr/bin/env python3
"""Build the LEAN Claude-Chat runtime package (v8.18.0).

The full release bundle (gem_src_bundle.py) ships the production runtime PLUS the Stage-F/Stage-P
acceptance apparatus, the QA harnesses, the full unit suite, and design specs -- needed to VERIFY a
release, but NOT to GENERATE a report. The Chat project sits near 97% capacity carrying all of it.

This lean package keeps only the production report-generation closure (the runtime gem_*.py modules,
the gem_report_draft/ renderer package incl. the v8.18.0 typed owners gem_final_status.py +
gem_report_draft/_cards.py + gem_commentary_capsule.py + gem_tournament_model.py, the parser config,
and a compact STEP0 + concise release notes) and EXCLUDES the verification/test/acceptance apparatus.
Session-input CSVs stay flat in the project (copied at STEP0), as before.

Output: gem_lean_runtime.py (a self-extracting bundle, same mechanism as gem_src_bundle.py).
Reports old vs new bytes + the included / excluded inventory.
"""
import base64, io, os, zipfile, hashlib, datetime
import _build_bundle as BB

REPO = BB.REPO
# v8.20.0 FINAL: the extracted runtime banner must NOT claim v8.19.0-lean (owner blocker #5). The
# embedded git-independent identity lives in gem_build_identity.py (frozen by the package builder).
LEAN_VERSION = 'v8.20.0'

# Excluded from the lean runtime (present in the full release bundle):
#   - every QA harness (_qa_*.py) -- verification, not report generation
#   - the full unit suite (_test_scratch.py)
#   - the whole acceptance/ tree (Stage-F/Stage-P gates, seeds, fixtures, mutation audit)
#   - design specs (*_SPEC.py -- already filtered by _repo_runtime_modules)
def _is_excluded(arc):
    base = arc.split('/')[-1]
    if arc.startswith('acceptance/'):
        return True
    if base == '_test_scratch.py':
        return True
    if base.startswith('_qa_'):
        return True
    if base.endswith('_SPEC.py'):
        return True
    return False


# The non-module runtime DATA files the full bundle ships (json/txt lookups the resolvers glob at
# runtime). The lean runtime MUST carry these or report generation fails (e.g. gto_texture_archetypes.json
# is read by analyze_session). Explicit allow-list -- used directly, and as a fallback if the canonical
# inventory snapshot is unavailable at build time.
_RUNTIME_DATA = (
    'Cards_nicknames.txt', 'Poker_Ranges_Text.txt', '_gtow_situations.json',
    'coaching_rules.json', 'gem_known_bugs.json', 'gem_schema.json',
    'gto_texture_archetypes.json', 'gtow_reference.json', 'requirements.txt',
    'tier_handicaps.json', 'tournament_structures.json',
)


def _runtime_data_files():
    """Runtime DATA files the lean runtime needs to GENERATE a report -- exactly the set the full bundle
    ships (non-module json/txt, minus prose + verification). Derived from the canonical inventory
    snapshot (BB.PROJ_FALLBACK) when present, unioned with the explicit allow-list, restricted to files
    that actually exist in the repo so a missing snapshot never ships a broken runtime."""
    out = set()
    snap = getattr(BB, 'PROJ_FALLBACK', None)
    if snap and os.path.isdir(snap):
        for f in os.listdir(snap):
            if not (f.endswith('.json') or f.endswith('.txt')):
                continue
            if f in BB.PROSE or f in BB.KILL or f in BB.FLAT_DATA:
                continue
            if f.startswith('test_') or f.startswith('_qa_'):
                continue
            if f in ('GEM_Changelog.txt', 'GEM_Quick_Reference.txt'):
                continue
            if os.path.isfile(os.path.join(REPO, f)):
                out.add(f)
    for f in _RUNTIME_DATA:                           # always ship the known lookups (repo-present)
        if os.path.isfile(os.path.join(REPO, f)):
            out.add(f)
    return out


def runtime_names():
    """The production report-generation file set: root gem_*.py modules + the renderer package members +
    the runtime DATA lookups the resolvers read at generation time. The runtime imports no prose, so the
    full changelog (135 KB) + quick reference (102 KB) are NOT bundled here -- the lean package ships
    concise release notes instead; STEP0 instructions stay."""
    names = set(BB._repo_runtime_modules())          # every repo gem_*.py runtime module
    names |= set(BB.PKG)                              # gem_report_draft/ members
    # NOTE: the lean STEP0 is NOT the repo's (bundle-flavored) SESSION_START_STEP0_package_rebuild.txt --
    # that file documents the FULL bundle (verify_release / _test_scratch, neither shipped in the lean). The
    # lean builder GENERATES its own lean-specific STEP0 (txt + md) inline; see build().
    names |= _runtime_data_files()                   # v8.18.0: ship the runtime data lookups (self-sufficient)
    names = {n for n in names
             if n not in BB.KILL and n not in BB.FLAT_DATA
             and n not in ('GEM_Changelog.txt', 'GEM_Quick_Reference.txt')   # prose, replaced by release notes
             and not n.startswith('_qa_') and n != '_test_scratch.py'}
    return names


def vendor_phevaluator(z):
    """QA-BLOCK-003 (self-containment): bundle the EXACT evaluator dependency (phevaluator) INTO the package
    so the extracted Chat runtime computes exact equity with NO pip install / network fetch. phevaluator's
    __init__ uses lazy (PEP-562) submodule imports, so `import phevaluator` + `evaluate_cards(...)` (the only
    surface the NLH-only report uses) works WITHOUT the two large Omaha lookup tables (omaha_*.dat, ~30 MB) --
    those are excluded to keep the upload lean. Vendored from the build env's installed package; fails LOUD
    if phevaluator is absent at build time so a release can never ship a half-bundled evaluator."""
    import phevaluator as _pv
    pv_dir = os.path.dirname(os.path.abspath(_pv.__file__))
    bundled = []
    for root, _dirs, files in os.walk(pv_dir):
        if '__pycache__' in root:
            continue
        for f in sorted(files):
            if f.endswith(('.pyc', '.dat', '.pyo')):
                continue   # .dat = the multi-MB Omaha tables the NLH report never touches
            src = os.path.join(root, f)
            arc = 'phevaluator/' + os.path.relpath(src, pv_dir).replace(os.sep, '/')
            with open(src, 'rb') as fh:
                z.writestr(arc, fh.read())
            bundled.append(arc)
    ver = getattr(_pv, '__version__', '?')
    print('  vendored phevaluator %s: %d files (Omaha .dat excluded)' % (ver, len(bundled)))
    return bundled


def _freeze_identity(text, commit, label):
    """Freeze gem_build_identity.py for the bundled (git-independent) runtime: stamp the FULL source commit +
    an OPERATIONAL build label (never a release tag) into the three builder-owned lines, so the extracted
    Chat runtime reports its exact source WITHOUT a .git directory."""
    import re
    text = re.sub(r"^RELEASE_CANDIDATE = .*$",
                  "RELEASE_CANDIDATE = %r   # operational lean build from main; NOT a release tag" % label,
                  text, count=1, flags=re.M)
    text = re.sub(r"^SOURCE_COMMIT = .*$",
                  "SOURCE_COMMIT = %r            # frozen at lean build" % commit, text, count=1, flags=re.M)
    text = re.sub(r"^BUILD_ID = .*$", "BUILD_ID = %r" % label, text, count=1, flags=re.M)
    return text


def _lean_step0_txt(label, full, branch):
    """The LEAN-specific STEP0 (plain text). Documents the lean activation path: extract gem_lean_runtime.py
    (NOT gem_src_bundle.py), preserve the session_*.csv history, vendored phevaluator (no pip), a MINIMAL
    readiness check (the lean ships NO verify_release / unit suite), identity confirmation, one-run-one-quick."""
    return (
"GEM LEAN RUNTIME -- SESSION STEP 0\n"
"operational build %s | source commit %s | branch %s\n"
"(operational refresh, NOT a release; no tag exists)\n"
"\n"
"This Claude Chat project is the LEAN report-generation runtime. Run these steps in order at the start\n"
"of every session. Do NOT extract gem_src_bundle.py -- this project uses gem_lean_runtime.py.\n"
"\n"
"1. Extract the lean runtime to a working dir and work ONLY there:\n"
"     python /mnt/project/gem_lean_runtime.py /home/claude/gem\n"
"     cd /home/claude/gem\n"
"   Expect a success line naming the build label: 'GEM lean runtime %s: extracted N files'.\n"
"\n"
"2. Keep the existing project session files -- DO NOT delete them. Copy the flat data the resolvers\n"
"   read into the working dir (these are inputs, not the runtime):\n"
"     cp /mnt/project/gem_pipeline_learnings.csv .\n"
"     cp /mnt/project/session_*.csv .\n"
"   The session history (session_financials.csv, session_financials_per_tournament.csv,\n"
"   session_history_merged_*.csv) and the analyst contract/schema files stay in the project untouched.\n"
"\n"
"3. phevaluator is VENDORED inside the lean runtime -- no pip install / network needed. Confirm it\n"
"   imports from the extracted runtime:\n"
"     python -c \"import phevaluator; print('phevaluator OK:', phevaluator.evaluate_cards('Ah','As','Kd','Kc','2c'))\"\n"
"   (Only if it is somehow missing: pip install --quiet phevaluator.)\n"
"\n"
"4. Minimal readiness check. The lean runtime carries report generation ONLY -- it does NOT include\n"
"   verify_release.py or the unit suite (_test_scratch.py / test_runout_*.py). Do not look for them:\n"
"     python -c \"import gem_report_draft, gem_analyzer, gem_runout_transition; print('runtime OK')\"\n"
"\n"
"5. Confirm the runtime's exact source identity (git-independent, frozen at build):\n"
"     python -c \"import gem_build_identity as b; i=b.build_identity(); print(i['build_id'], i['source_commit'])\"\n"
"   Expect exactly: %s %s\n"
"\n"
"6. Generate today's report with the ONE production runner -- exactly one full run:\n"
"     python gem_analyzer.py <SESSION_DIR>\n"
"   It parses, analyzes, builds the coverage layer + analyst worklist + the sealed atomic analyst packet,\n"
"   and writes Pokerbot_<Player>_<dates>_V<N>.html.\n"
"\n"
"7. (Optional) After you write the analyst output JSON (bound to the sealed packet, OUTSIDE the\n"
"   hand-history input dir), re-render AT MOST ONCE:\n"
"     python gem_analyzer.py <SESSION_DIR> --quick\n"
"   Do not exceed one full run + one matching --quick re-render per session.\n"
"\n"
"8. The descriptive Runout Transition notes render automatically on eligible turn/river decisions.\n"
"   Descriptive only -- the strategic action stays 'Insufficient evidence' (no opponent-range / equity /\n"
"   EV / fold-equity). Do not invent continue/resize/pivot/abandon advice from them.\n"
"\n"
"On any import or identity failure, STOP and tell Ron -- do not improvise or rebuild from an old copy.\n"
        % (label, full, branch, label, label, full))


def _lean_step0_md(label, full, branch):
    """STEP0.md -- the markdown twin of the lean STEP0 (same activation path, GitHub-flavored)."""
    return (
"# GEM Lean Runtime -- STEP 0 (session start)\n\n"
"**Operational build `%s`** -- source commit `%s`, branch `%s`. Operational refresh, **not** a release; no tag exists.\n\n"
"This project is the **lean report-generation runtime**. Run these in order each session. **Do not extract\n"
"`gem_src_bundle.py`** -- this project uses `gem_lean_runtime.py`.\n\n"
"1. **Extract the lean runtime** and work only there:\n"
"   ```\n"
"   python /mnt/project/gem_lean_runtime.py /home/claude/gem\n"
"   cd /home/claude/gem\n"
"   ```\n"
"   Expect: `GEM lean runtime %s: extracted N files`.\n\n"
"2. **Keep the session files** -- do **not** delete them. Copy the flat inputs the resolvers read:\n"
"   ```\n"
"   cp /mnt/project/gem_pipeline_learnings.csv .\n"
"   cp /mnt/project/session_*.csv .\n"
"   ```\n"
"   Leave `session_financials.csv`, `session_financials_per_tournament.csv`, `session_history_merged_*.csv`\n"
"   and the analyst contract/schema files untouched in the project.\n\n"
"3. **phevaluator is vendored** in the lean runtime -- no pip needed:\n"
"   ```\n"
"   python -c \"import phevaluator; print('phevaluator OK:', phevaluator.evaluate_cards('Ah','As','Kd','Kc','2c'))\"\n"
"   ```\n\n"
"4. **Minimal readiness** (the lean ships report generation only -- no `verify_release` / unit suite):\n"
"   ```\n"
"   python -c \"import gem_report_draft, gem_analyzer, gem_runout_transition; print('runtime OK')\"\n"
"   ```\n\n"
"5. **Confirm source identity** (git-independent, frozen at build):\n"
"   ```\n"
"   python -c \"import gem_build_identity as b; i=b.build_identity(); print(i['build_id'], i['source_commit'])\"\n"
"   ```\n"
"   Expect exactly: `%s %s`\n\n"
"6. **One full run** (the only production runner):\n"
"   ```\n"
"   python gem_analyzer.py <SESSION_DIR>\n"
"   ```\n\n"
"7. **Optional, at most one** packet-bound re-render: `python gem_analyzer.py <SESSION_DIR> --quick`.\n"
"   Do not exceed one full run + one matching `--quick` per session.\n\n"
"8. **Runout Transition** notes render automatically on eligible turn/river decisions -- descriptive only;\n"
"   the strategic action stays *Insufficient evidence* (no range / equity / EV / fold-equity). Do not invent\n"
"   continue/resize/pivot/abandon advice from them.\n\n"
"On any import or identity failure, **STOP** and tell Ron -- do not improvise or rebuild from an old copy.\n"
        % (label, full, branch, label, label, full))


def build():
    full, short, branch = BB._git_identity()
    label = 'GEM-%s-%s' % (branch, short)   # operational build label -- NOT a release tag
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    buf = io.BytesIO()
    chosen, excluded = [], []
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        chosen += vendor_phevaluator(z)   # bundle the exact evaluator dependency (no pip in Chat)
        for n in sorted(runtime_names()):
            arc = ('gem_report_draft/%s' % n) if n in BB.PKG else n
            src = os.path.join(REPO, 'gem_report_draft', n) if n in BB.PKG else os.path.join(REPO, n)
            if not os.path.isfile(src) or _is_excluded(arc):
                continue
            data = open(src, 'rb').read()
            if n == 'gem_build_identity.py':                       # freeze the git-independent identity
                data = _freeze_identity(data.decode('utf-8'), full, label).encode('utf-8')
            z.writestr(arc, data)
            chosen.append(arc)
        # concise current-state release notes REPLACE the full changelog inside the lean package.
        notes = (
            "GEM lean Chat runtime (report generation only) -- operational build %s\n"
            "Source commit: %s (branch %s). Operational refresh, NOT a release; no tag exists.\n\n"
            "NEW: the descriptive Runout Transition feature (merged into main). On eligible turn/river\n"
            "decisions the hand-detail report adds ONE note explaining what the new card objectively changed,\n"
            "what remains true, and what to reassess. Deterministic and result-independent; renders in both\n"
            "AUTO_ONLY and analyst-integrated reports; adds NO analyst-packet decisions and NO analyst-LLM work;\n"
            "the strategic action stays 'Insufficient evidence' (no opponent-range / equity / EV / fold-equity\n"
            "calculation); unresolved / all-in nodes render nothing.\n\n"
            "Ships the production report-generation runtime + the vendored phevaluator (NLH tables; Omaha .dat\n"
            "excluded) so the Chat runtime computes exact equity with NO pip install. EXCLUDES the verification\n"
            "apparatus (acceptance/, _qa_*, _test_scratch) -- run the full release bundle to verify a release.\n\n"
            "STEP0: python /mnt/project/gem_lean_runtime.py /home/claude/gem && cd /home/claude/gem\n"
            "  && cp /mnt/project/gem_pipeline_learnings.csv . && cp /mnt/project/session_*.csv .\n"
            "  && python -c \"import gem_report_draft, gem_analyzer, gem_runout_transition, phevaluator;"
            " print('runtime OK; exact equity:', phevaluator.evaluate_cards('Ah','As','Kd','Kc','2c'))\"\n"
        ) % (label, full, branch)
        z.writestr('RELEASE_NOTES.txt', notes.encode())
        chosen.append('RELEASE_NOTES.txt')
        # LEAN-specific STEP0 (txt + md) -- generated inline, NOT the repo's bundle-flavored STEP0.
        z.writestr('SESSION_START_STEP0_package_rebuild.txt', _lean_step0_txt(label, full, branch).encode())
        z.writestr('STEP0.md', _lean_step0_md(label, full, branch).encode())
        chosen += ['SESSION_START_STEP0_package_rebuild.txt', 'STEP0.md']
    raw = buf.getvalue()
    b64 = base64.b64encode(raw).decode()
    lines = '\n'.join(b64[i:i + 76] for i in range(0, len(b64), 76))
    sha = hashlib.sha256(raw).hexdigest()[:16]
    out = ('"""GEM lean runtime -- self-extracting report-generation closure (no verification apparatus).\n'
           'BUILD_LABEL    = %s   (operational; NOT a release tag)\n'
           'SOURCE_COMMIT  = %s\nSOURCE_BRANCH  = %s\nBUILD_TIMESTAMP = %s\n'
           'files: %d | zip sha256[:16]: %s\n'
           'STEP0: python /mnt/project/gem_lean_runtime.py /home/claude/gem\n"""\n'
           'import base64, io, os, sys, zipfile\n'
           'BUILD_LABEL = %r            # operational build label, not a release tag\n'
           'SOURCE_COMMIT = %r\nSOURCE_COMMIT_SHORT = %r\nSOURCE_BRANCH = %r\nBUILD_TIMESTAMP = %r\n'
           'LEAN_VERSION = %r\n_B64 = """\\\n%s"""\n\n\n'
           'def extract(target):\n'
           '    data = base64.b64decode("".join(_B64.split()))\n'
           '    os.makedirs(target, exist_ok=True)\n'
           '    with zipfile.ZipFile(io.BytesIO(data)) as z:\n'
           '        z.extractall(target); n = len(z.namelist())\n'
           '    print("GEM lean runtime %%s: extracted %%d files -> %%s" %% (BUILD_LABEL, n, target))\n'
           '    return n\n\n\n'
           'if __name__ == "__main__":\n'
           '    extract(sys.argv[1] if len(sys.argv) > 1 else "gem")\n'
           % (label, full, branch, stamp, len(chosen), sha,
              label, full, short, branch, stamp, label, lines))
    out_path = os.path.join(REPO, 'gem_lean_runtime.py')
    with open(out_path, 'w', encoding='ascii', newline='\n') as f:
        f.write(out)
    # measure vs the full release bundle
    full_path = os.path.join(REPO, 'gem_src_bundle.py')
    full_bytes = os.path.getsize(full_path) if os.path.isfile(full_path) else 0
    lean_bytes = os.path.getsize(out_path)
    print('LEAN runtime: %d files, lean zip sha %s' % (len(chosen), sha))
    print('full gem_src_bundle.py : %d bytes' % full_bytes)
    print('lean gem_lean_runtime.py: %d bytes' % lean_bytes)
    if full_bytes:
        print('reduction: %d bytes (%.1f%%)' % (full_bytes - lean_bytes,
                                                100.0 * (full_bytes - lean_bytes) / full_bytes))
    return out_path, chosen


if __name__ == '__main__':
    build()
