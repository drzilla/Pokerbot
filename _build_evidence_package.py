#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build GEM_v8.18.0_FINAL_RELEASE_CANDIDATE_EVIDENCE.zip.

HARD GATE: this builder runs the independent verifier (_qa_v818_final_product_truth) FIRST and ABORTS
(non-zero exit, no zip) if FINAL_PREPACKAGE_AUDIT.json all_passed is not true. There is no warning-only
mode. The produced zip is self-verifying: self_verify.py extracts the bundled runtime, re-runs the
verifier against the INCLUDED report + raw summaries + cache, and asserts all_passed.
"""
import io
import os
import sys
import json
import shutil
import hashlib
import zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = r'C:/mnt/user-data/outputs/wave1_2'
EVIDENCE = os.path.join(OUT_ROOT, 'evidence')
ZIP_NAME = 'GEM_v8.18.0_FINAL_RELEASE_CANDIDATE_EVIDENCE.zip'
AUTO_HTML = r'C:/mnt/user-data/outputs/Pokerbot_Knockman_20260616_AUTO_ONLY_V1.html'
ANALYST_HTML = r'C:/mnt/user-data/outputs/Pokerbot_Knockman_20260616_V3.html'
SUMMARIES = r'C:/mnt/user-data/outputs/iter0/june16_src/game_summaries'
DATA = r'C:/home/claude/gem_report_data_Knockman.json'
STATS = r'C:/home/claude/gem_stats.json'

SELF_VERIFY = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-verify this evidence package from a FRESH extraction.

Extracts the bundled runtime (gem_src_bundle.py), then re-runs the independent verifier against the
INCLUDED report + raw summaries + cache and asserts FINAL_PREPACKAGE_AUDIT.json all_passed == true.
Exit 0 only if every frozen predicate passes against the included product.
"""
import io, os, sys, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
RT = os.path.join(HERE, '_runtime')

def main():
    os.makedirs(RT, exist_ok=True)
    # 1) extract the runtime from the self-extracting bundle
    subprocess.check_call([sys.executable, os.path.join(HERE, 'gem_src_bundle.py'), RT])
    # 2) make the verifier + its decoder importable from the runtime
    for f in ('_qa_v818_final_product_truth.py', '_qa_decode_lazy.py'):
        io.open(os.path.join(RT, f), 'w', encoding='utf-8', newline='\n').write(
            io.open(os.path.join(HERE, f), encoding='utf-8').read())
    sys.path.insert(0, RT)
    os.environ['PYTHONUTF8'] = '1'
    import _qa_v818_final_product_truth as V
    doc = V.run(
        os.path.join(HERE, 'report', 'Pokerbot_Knockman_20260616_AUTO_ONLY_V1.html'),
        os.path.join(HERE, 'self_verify_out'),
        os.path.join(HERE, 'cache', 'gem_report_data_Knockman.json'),
        os.path.join(HERE, 'cache', 'gem_stats.json'),
        os.path.join(HERE, 'raw_source', 'game_summaries'))
    print('SELF-VERIFY all_passed=%s  (%d predicates, %d failed)'
          % (doc['all_passed'], doc['predicate_count'], len(doc['failed_predicates'])))
    for p in doc['failed_predicates']:
        print('  FAIL %s: expected %r observed %r' % (p['predicate'], p['expected'], p['observed']))
    return 0 if doc['all_passed'] else 1

if __name__ == '__main__':
    sys.exit(main())
'''


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    # ---- HARD GATE: run the independent verifier first ----
    sys.path.insert(0, REPO)
    import _qa_v818_final_product_truth as V
    doc = V.run(AUTO_HTML, OUT_ROOT, DATA, STATS, SUMMARIES, ANALYST_HTML)
    if not doc['all_passed']:
        print('ABORT: FINAL_PREPACKAGE_AUDIT all_passed=False (%d failed). No evidence zip built.'
              % len(doc['failed_predicates']))
        for p in doc['failed_predicates']:
            print('  FAIL %s: expected %r observed %r' % (p['predicate'], p['expected'], p['observed']))
        return 1
    print('GATE PASSED: %d/%d predicates. Assembling evidence package...'
          % (doc['predicate_count'] - len(doc['failed_predicates']), doc['predicate_count']))

    # ---- assemble the staging dir ----
    if os.path.isdir(EVIDENCE):
        shutil.rmtree(EVIDENCE)
    os.makedirs(EVIDENCE)
    os.makedirs(os.path.join(EVIDENCE, 'report'))
    os.makedirs(os.path.join(EVIDENCE, 'raw_source', 'game_summaries'))
    os.makedirs(os.path.join(EVIDENCE, 'cache'))

    def cp(src, dst):
        shutil.copy2(src, os.path.join(EVIDENCE, dst))

    # audit + source-truth artifacts (written by the verifier into OUT_ROOT)
    for f in ('FINAL_PREPACKAGE_AUDIT.json', 'results_source_truth.json',
              'results_source_model_dom_reconciliation.json', 'villain_full_population_audit.json',
              'villain_133_corrected_lessons.json'):
        cp(os.path.join(OUT_ROOT, f), f)
    # the verifier + decoder (reproducible)
    cp(os.path.join(REPO, '_qa_v818_final_product_truth.py'), '_qa_v818_final_product_truth.py')
    cp(os.path.join(REPO, '_qa_decode_lazy.py'), '_qa_decode_lazy.py')
    # the regenerated reports
    cp(AUTO_HTML, os.path.join('report', os.path.basename(AUTO_HTML)))
    cp(ANALYST_HTML, os.path.join('report', os.path.basename(ANALYST_HTML)))
    # the raw source the verifier re-parses
    for f in sorted(os.listdir(SUMMARIES)):
        cp(os.path.join(SUMMARIES, f), os.path.join('raw_source', 'game_summaries', f))
    # cache the villain reconstruction needs
    cp(DATA, os.path.join('cache', os.path.basename(DATA)))
    cp(STATS, os.path.join('cache', os.path.basename(STATS)))
    # the release runtime bundle + self-verify
    cp(os.path.join(REPO, 'gem_src_bundle.py'), 'gem_src_bundle.py')
    io.open(os.path.join(EVIDENCE, 'self_verify.py'), 'w', encoding='utf-8', newline='\n').write(SELF_VERIFY)
    # completion report (copied if present)
    cr = os.path.join(OUT_ROOT, 'COMPLETION_REPORT_v8180_FINAL_PRODUCT_TRUTH.md')
    if os.path.exists(cr):
        cp(cr, 'COMPLETION_REPORT_v8180_FINAL_PRODUCT_TRUTH.md')

    # ---- zip ----
    zip_path = os.path.join(OUT_ROOT, ZIP_NAME)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(EVIDENCE):
            for fn in sorted(files):
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, EVIDENCE))
    print('BUILT %s  (%.1f MB)  sha256=%s'
          % (ZIP_NAME, os.path.getsize(zip_path) / 1e6, sha(zip_path)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
