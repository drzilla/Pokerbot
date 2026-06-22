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
LEAN_VERSION = 'v8.19.0-lean'

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
    names |= {'SESSION_START_STEP0_package_rebuild.txt'}  # startup instructions only
    names |= _runtime_data_files()                   # v8.18.0: ship the runtime data lookups (self-sufficient)
    names = {n for n in names
             if n not in BB.KILL and n not in BB.FLAT_DATA
             and n not in ('GEM_Changelog.txt', 'GEM_Quick_Reference.txt')   # prose, replaced by release notes
             and not n.startswith('_qa_') and n != '_test_scratch.py'}
    return names


def build():
    buf = io.BytesIO()
    chosen, excluded = [], []
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n in sorted(runtime_names()):
            arc = ('gem_report_draft/%s' % n) if n in BB.PKG else n
            src = os.path.join(REPO, 'gem_report_draft', n) if n in BB.PKG else os.path.join(REPO, n)
            if not os.path.isfile(src) or _is_excluded(arc):
                continue
            with open(src, 'rb') as f:
                z.writestr(arc, f.read())
            chosen.append(arc)
        # concise current-state release notes REPLACE the full changelog inside the lean package.
        notes = ("GEM v8.19.0 -- lean Chat runtime (report generation only). Product Closure & Trust Baseline.\n"
                 "Trust/correctness: ONE canonical required-review owner shared by the coverage gate and the\n"
                 "completeness layer (gem_report_data.canonical_required_review_ids); the analyst worklist\n"
                 "RETAINS reviewed-decision provenance past reviewed-hand exclusion; non-NLH (PLO/Omaha) hands\n"
                 "are quarantined from every required-review + finality surface; biggest-loss screens are\n"
                 "populated before the candidate contract is written and never auto-resolved; an invalid\n"
                 "analyst street falls back safely instead of crashing the render; the runtime imports without\n"
                 "phevaluator (postflop equity bucketing degrades loud). Carried-forward canonical owners:\n"
                 "gem_final_status, gem_report_draft/_cards (PokerHandDisplay), gem_commentary_capsule,\n"
                 "gem_tournament_model, gem_villain_teaching. DEFERRED to v8.20: the preflop/exploit universal\n"
                 "eligibility-owner (steals/squeezes/3-bets/4-bets/exploit).\n"
                 "Verification apparatus (acceptance/, _qa_*, _test_scratch) is NOT in this package -- run\n"
                 "the full release bundle to verify a release.\n"
                 "STEP0: python /mnt/project/gem_lean_runtime.py /home/claude/gem && cd /home/claude/gem\n"
                 "  && cp /mnt/project/session_*.csv . && python -c \"import gem_report_draft, gem_analyzer;"
                 " print('runtime OK')\"\n")
        z.writestr('RELEASE_NOTES_v8.19.0.txt', notes.encode())
        chosen.append('RELEASE_NOTES_v8.19.0.txt')
    raw = buf.getvalue()
    b64 = base64.b64encode(raw).decode()
    lines = '\n'.join(b64[i:i + 76] for i in range(0, len(b64), 76))
    sha = hashlib.sha256(raw).hexdigest()[:16]
    out = ('"""GEM lean runtime -- self-extracting report-generation closure (no verification apparatus).\n'
           'LEAN_VERSION = %s\nfiles: %d | zip sha256[:16]: %s\n'
           'STEP0: python /mnt/project/gem_lean_runtime.py /home/claude/gem\n"""\n'
           'import base64, io, os, sys, zipfile\nLEAN_VERSION = %r\n_B64 = """\\\n%s"""\n\n\n'
           'def extract(target):\n'
           '    data = base64.b64decode("".join(_B64.split()))\n'
           '    os.makedirs(target, exist_ok=True)\n'
           '    with zipfile.ZipFile(io.BytesIO(data)) as z:\n'
           '        z.extractall(target); n = len(z.namelist())\n'
           '    print("GEM lean runtime %%s: extracted %%d files -> %%s" %% (LEAN_VERSION, n, target))\n'
           '    return n\n\n\n'
           'if __name__ == "__main__":\n'
           '    extract(sys.argv[1] if len(sys.argv) > 1 else "gem")\n'
           % (LEAN_VERSION, len(chosen), sha, LEAN_VERSION, lines))
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
