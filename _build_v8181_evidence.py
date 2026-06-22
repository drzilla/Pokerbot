#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build GEM_v8.18.1_VILLAIN_TEACHING_HOTFIX_RC_EVIDENCE.zip and self-verify it from a fresh extraction.

HARD GATE: runs the independent quality verifier FIRST and ABORTS (non-zero, no zip) unless
FINAL_QUALITY_AUDIT all_passed is true. No warning-only mode. The zip self-verifies: self_verify.py
re-checks every file hash and re-runs the quality verifier against the INCLUDED report + cache.
"""
import io
import os
import sys
import json
import shutil
import hashlib
import zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
V = r'C:/mnt/user-data/outputs/v8181'
STAGE = os.path.join(V, 'evidence_pkg')
ZIP_NAME = 'GEM_v8.18.1_VILLAIN_TEACHING_HOTFIX_RC_EVIDENCE.zip'
AUTO = r'C:/mnt/user-data/outputs/Pokerbot_Knockman_20260616_AUTO_ONLY_V1.html'
ANALYST = r'C:/mnt/user-data/outputs/Pokerbot_Knockman_20260616_V3.html'
STATS = r'C:/home/claude/gem_stats.json'
DATA = r'C:/home/claude/gem_report_data_Knockman.json'

SELF_VERIFY = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-verify this v8.18.1 hotfix evidence package from a FRESH extraction.
Re-checks every file hash against MANIFEST.json, extracts the bundled lean runtime, and re-runs the
independent quality verifier against the INCLUDED report + cache. Exit 0 only if all_passed + hashes ok.
"""
import io, os, sys, json, hashlib, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f: h.update(f.read())
    return h.hexdigest()
def main():
    man = json.load(io.open(os.path.join(HERE, 'MANIFEST.json'), encoding='utf-8'))
    bad = [r for r, rec in man['files'].items()
           if not os.path.isfile(os.path.join(HERE, r))
           or sha(os.path.join(HERE, r)) != rec['sha256'] or os.path.getsize(os.path.join(HERE, r)) != rec['size']]
    print('MANIFEST: %d files, %d mismatched' % (len(man['files']), len(bad)))
    for b in bad: print('  FAIL', b)
    rt = os.path.join(HERE, '_runtime'); os.makedirs(rt, exist_ok=True)
    subprocess.check_call([sys.executable, os.path.join(HERE, 'gem_lean_runtime.py'), rt])
    for f in ('_qa_v8181_future_exploit_quality.py', '_qa_decode_lazy.py'):
        io.open(os.path.join(rt, f), 'w', encoding='utf-8', newline='\n').write(
            io.open(os.path.join(HERE, f), encoding='utf-8').read())
    sys.path.insert(0, rt); os.environ['PYTHONUTF8'] = '1'
    import _qa_v8181_future_exploit_quality as Q
    doc = Q.run(os.path.join(HERE, 'report', 'Pokerbot_Knockman_20260616_AUTO_ONLY_V1.html'),
                os.path.join(HERE, 'report', 'Pokerbot_Knockman_20260616_V3.html'),
                os.path.join(HERE, 'cache', 'gem_stats.json'),
                os.path.join(HERE, 'cache', 'gem_report_data_Knockman.json'),
                os.path.join(HERE, 'self_verify_out'))
    print('SELF-VERIFY quality all_passed=%s (%d predicates, %d failed)'
          % (doc['all_passed'], doc['predicate_count'], len(doc['failed_predicates'])))
    ok = (not bad) and doc['all_passed']
    print('SELF-VERIFY:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1
if __name__ == '__main__':
    sys.exit(main())
'''


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    sys.path.insert(0, REPO)
    import _qa_v8181_future_exploit_quality as Q
    doc = Q.run(AUTO, ANALYST, STATS, DATA, V)
    if not doc['all_passed']:
        print('ABORT: FINAL_QUALITY_AUDIT all_passed=False (%d failed). No evidence zip built.'
              % len(doc['failed_predicates']))
        for p in doc['failed_predicates']:
            print('  FAIL %s: expected %r observed %r' % (p['predicate'], p['expected'], p['observed']))
        return 1
    print('GATE PASSED: %d/%d quality predicates. Assembling...'
          % (doc['predicate_count'] - len(doc['failed_predicates']), doc['predicate_count']))

    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    for d in ('', 'report', 'cache', 'logs'):
        os.makedirs(os.path.join(STAGE, d))

    def cp(src, dst):
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(STAGE, dst))

    # audits + artifacts (written by the verifier into V)
    for f in ('FINAL_QUALITY_AUDIT.json', 'villain_full_population_audit.json',
              'villain_133_corrected_lessons.json', 'before_after.json',
              'v8181_future_exploit_review.html', 'distinct_lessons.json',
              'chat_capacity_inventory.json', 'adversarial_review.json',
              'regression_summary.txt', 'implementation_diff.patch', 'KNOWN_ISSUES_BACKLOG.md'):
        cp(os.path.join(V, f), f)
    # the verifier + decoder
    cp(os.path.join(REPO, '_qa_v8181_future_exploit_quality.py'), '_qa_v8181_future_exploit_quality.py')
    cp(os.path.join(REPO, '_qa_decode_lazy.py'), '_qa_decode_lazy.py')
    # release docs
    cp(os.path.join(REPO, 'GEM_Release_Notes_v8.18.1.txt'), 'GEM_Release_Notes_v8.18.1.txt')
    cp(os.path.join(REPO, 'CLAUDE_CHAT_RUNTIME_REPLACEMENT_v8.18.1.md'), 'CLAUDE_CHAT_RUNTIME_REPLACEMENT_v8.18.1.md')
    # lean runtime + reports + cache
    cp(os.path.join(REPO, 'gem_lean_runtime.py'), 'gem_lean_runtime.py')
    cp(AUTO, os.path.join('report', os.path.basename(AUTO)))
    cp(ANALYST, os.path.join('report', os.path.basename(ANALYST)))
    cp(STATS, os.path.join('cache', os.path.basename(STATS)))
    cp(DATA, os.path.join('cache', os.path.basename(DATA)))
    # logs
    for lg in ('regen_auto.log', 'regen_analyst.log', 'full_regen.log', 'lean_smoke.log', 'parity.json'):
        cp(os.path.join(V, lg), os.path.join('logs', lg))
    io.open(os.path.join(STAGE, 'self_verify.py'), 'w', encoding='utf-8', newline='\n').write(SELF_VERIFY)

    # MANIFEST
    files = {}
    for root, _d, fs in os.walk(STAGE):
        for fn in fs:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, STAGE).replace('\\', '/')
            files[rel] = {'sha256': sha256(full), 'size': os.path.getsize(full)}
    io.open(os.path.join(STAGE, 'MANIFEST.json'), 'w', encoding='utf-8', newline='\n').write(json.dumps(
        {'release': 'GEM v8.18.1 Villain Teaching hotfix RC', 'branch': 'hotfix/v8.18.1-villain-teaching-future-exploit',
         'commit': '24a7025', 'file_count': len(files), 'files': files}, indent=2, ensure_ascii=False))

    zip_path = os.path.join(V, ZIP_NAME)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _d, fs in os.walk(STAGE):
            for fn in sorted(fs):
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, STAGE))
    print('BUILT %s  (%.2f MB)  sha256=%s' % (ZIP_NAME, os.path.getsize(zip_path) / 1e6, sha256(zip_path)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
