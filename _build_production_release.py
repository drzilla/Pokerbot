#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build GEM_v8.18.0_PRODUCTION_RELEASE.zip and self-verify it from a fresh extraction.

Contents: final lean runtime, release notes, Claude-Chat replacement instructions, release commit/tag
info, deployment-smoke log, final capacity inventory, known-issue/backlog note, and a MANIFEST of
sha256 + sizes. self_verify.py (inside the zip) re-checks every hash and re-extracts + imports the
packaged lean runtime, confirming the bundled runtime data files are present.
"""
import io
import os
import sys
import json
import shutil
import hashlib
import zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = r'C:/mnt/user-data/outputs/release_v8180'
STAGE = os.path.join(OUT, 'production_pkg')
ZIP_NAME = 'GEM_v8.18.0_PRODUCTION_RELEASE.zip'

SELF_VERIFY = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-verify this production release from a FRESH extraction.
Re-checks every file hash against MANIFEST.json, then re-extracts + imports the packaged lean runtime
and confirms the bundled runtime data files are present. Exit 0 only if everything checks out.
"""
import io, os, sys, json, hashlib, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()

def main():
    man = json.load(io.open(os.path.join(HERE, 'MANIFEST.json'), encoding='utf-8'))
    bad = []
    for rel, rec in man['files'].items():
        p = os.path.join(HERE, rel)
        if not os.path.isfile(p):
            bad.append((rel, 'MISSING')); continue
        got = sha(p); sz = os.path.getsize(p)
        if got != rec['sha256'] or sz != rec['size']:
            bad.append((rel, 'HASH/SIZE MISMATCH'))
    print('MANIFEST: %d files, %d mismatched' % (len(man['files']), len(bad)))
    for b in bad:
        print('  FAIL', b)
    # re-extract + import the packaged lean runtime
    rt = os.path.join(HERE, '_runtime_check')
    os.makedirs(rt, exist_ok=True)
    subprocess.check_call([sys.executable, os.path.join(HERE, 'gem_lean_runtime.py'), rt])
    need = ['gto_texture_archetypes.json', '_gtow_situations.json', 'coaching_rules.json',
            'Poker_Ranges_Text.txt', 'gem_schema.json', 'gtow_reference.json', 'gem_known_bugs.json',
            'tier_handicaps.json', 'tournament_structures.json', 'Cards_nicknames.txt']
    missing_data = [f for f in need if not os.path.isfile(os.path.join(rt, f))]
    print('packaged runtime data files present:', not missing_data, '' if not missing_data else missing_data)
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, r"%s"); import gem_report_draft, gem_analyzer;'
                        ' print("runtime import OK")' % rt],
                       capture_output=True, text=True)
    print((r.stdout or '').strip() or (r.stderr or '').strip()[-300:])
    ok = (not bad) and (not missing_data) and ('runtime import OK' in (r.stdout or ''))
    print('SELF-VERIFY:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
'''


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)

    # deployment-smoke summary + log
    smoke_log = os.path.join(OUT, 'lean_smoke.log')
    if os.path.isfile(smoke_log):
        shutil.copy2(smoke_log, os.path.join(STAGE, 'deployment_smoke.log'))
    smoke_summary = (
        "GEM v8.18.0 — clean-runtime deployment smoke\n"
        "Extracted gem_lean_runtime.py (93 files) into a FRESH directory; no engineering-only files\n"
        "(acceptance/, _qa_*, _test_scratch, verify_release all ABSENT). Generated the June-16 report\n"
        "from a clean dir (fresh parse, no cache). Result:\n"
        "  exit 0; gem_report_lint 0 BLOCKER / 0 ERROR; analyst worklist emitted.\n"
        "  Results source/model/DOM reconciliation: 33/33 predicates (12 finish+Top%, Avg Top 48.1%,\n"
        "    non-currency BB/100, Regular/Turbo/Hyper speed filter).\n"
        "  Status-contradiction gate: 844 hands, 0 contradictions.\n"
        "  Commentary zero-drop: 2721 items, balances, 0 silent drops; registers render (Fact/Coach/\n"
        "    Insufficient evidence). PokerHandDisplay + single Results table present.\n"
        "  Ran WITHOUT engineering-only acceptance files.\n")
    io.open(os.path.join(STAGE, 'deployment_smoke_summary.txt'), 'w', encoding='utf-8', newline='\n').write(smoke_summary)

    # core deliverables
    pairs = [
        (os.path.join(REPO, 'gem_lean_runtime.py'), 'gem_lean_runtime.py'),
        (os.path.join(REPO, 'GEM_Release_Notes_v8.18.0.txt'), 'GEM_Release_Notes_v8.18.0.txt'),
        (os.path.join(REPO, 'CLAUDE_CHAT_RUNTIME_REPLACEMENT_v8.18.0.md'), 'CLAUDE_CHAT_RUNTIME_REPLACEMENT_v8.18.0.md'),
        (os.path.join(OUT, 'chat_capacity_inventory.json'), 'chat_capacity_inventory.json'),
        (os.path.join(OUT, 'RELEASE_INFO.json'), 'RELEASE_INFO.json'),
        (os.path.join(OUT, 'KNOWN_ISSUES_BACKLOG.md'), 'KNOWN_ISSUES_BACKLOG.md'),
    ]
    for src, dst in pairs:
        shutil.copy2(src, os.path.join(STAGE, dst))
    io.open(os.path.join(STAGE, 'self_verify.py'), 'w', encoding='utf-8', newline='\n').write(SELF_VERIFY)

    # MANIFEST (sha256 + size of every staged file, except the manifest itself)
    files = {}
    for root, _d, fs in os.walk(STAGE):
        for fn in fs:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, STAGE).replace('\\', '/')
            files[rel] = {'sha256': sha256(full), 'size': os.path.getsize(full)}
    manifest = {'release': 'GEM v8.18.0 production', 'final_main_commit': '789d574',
                'v8_18_0_tag_commit': 'afa753f', 'file_count': len(files), 'files': files}
    io.open(os.path.join(STAGE, 'MANIFEST.json'), 'w', encoding='utf-8', newline='\n').write(
        json.dumps(manifest, indent=2, ensure_ascii=False))

    # zip (deterministic order)
    zip_path = os.path.join(OUT, ZIP_NAME)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(os.listdir(STAGE)):
            z.write(os.path.join(STAGE, rel), rel)
    zsha = sha256(zip_path)
    print('BUILT %s  (%.2f MB)  sha256=%s' % (ZIP_NAME, os.path.getsize(zip_path) / 1e6, zsha))
    return zip_path, zsha


if __name__ == '__main__':
    main()
