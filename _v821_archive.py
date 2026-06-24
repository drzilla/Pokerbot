"""v8.21 closeout Task 3: archive obsolete per-hand pilot evidence to an EXTERNAL ZIP (outside the repo),
with full provenance, then prepare removal from the tree. Writes v821_sync/V821_SIZING_LINES_ARCHIVE_MANIFEST.json
and the ZIP + .sha256 sidecar on the Desktop (outside the worktree)."""
import os
import hashlib
import json
import zipfile
import subprocess

REPO = os.path.dirname(os.path.abspath(__file__))
ZIP_OUT = r'C:\Users\ron\OneDrive\Desktop\V821_SIZING_LINES_EVIDENCE_ARCHIVE.zip'


def git(*a):
    return subprocess.check_output(['git', '-C', REPO, *a]).decode().strip()


branch = git('rev-parse', '--abbrev-ref', 'HEAD')
commit = git('rev-parse', 'HEAD')

# obsolete per-hand pilot evidence (fixture-era PILOT_* + real-session REAL_* raw queues/metrics).
FILES = [
    'v03_pilot/REAL_CANDIDATE_QUEUE.json', 'v03_pilot/REAL_REVIEWED_QUEUE.json',
    'v03_pilot/REAL_CORPUS_PROVENANCE.json', 'v03_pilot/REAL_OPPORTUNITY_BASELINE.json',
    'v03_pilot/REAL_PRODUCT_VALUE_METRICS.json', 'v03_pilot/PILOT_CANDIDATE_QUEUE.json',
    'v03_pilot/PILOT_REVIEWED_QUEUE.json', 'v03_pilot/PILOT_PRODUCT_VALUE_METRICS.json',
    'v03_pilot/PILOT_COST_COMPARISON.json', 'v03_pilot/OPPORTUNITY_BASELINE.json',
]


def sha256_bytes(b):
    h = hashlib.sha256(); h.update(b); return h.hexdigest()


entries = []
for rel in FILES:
    b = open(os.path.join(REPO, rel), 'rb').read()
    entries.append({'repo_path': rel, 'bytes': len(b), 'sha256': sha256_bytes(b)})

README = """# V821 Sizing & Lines — archived obsolete pilot evidence (AUDIT ONLY)

These files are the RAW per-hand pilot evidence from the Pokerbot v8.21 Sizing & Lines workstream:
- `PILOT_*.json` / `OPPORTUNITY_BASELINE.json` — fixture-era per-hand pilot queues and metrics;
- `REAL_*.json` — real-session per-hand candidate/review queues, corpus provenance and metrics
  (3 approved sessions, 3,609 hands).

## Why they are archived (no longer active product authority)

The per-hand flop c-bet sizing approach was **rejected**: it produced **0 confirmed mistakes across 3,609
real hands** because the archetype band is a range-level reference and cannot prove that an individual hand
was a mistake without inventing range/equity. The **accepted, shipped** feature is the **AGGREGATE** flop
c-bet sizing-leak detector (repeated too-large / too-small habits per board class), gated to heads-up
single-raised-pot non-all-in c-bets.

These raw queues are kept for **audit** only. The narrative that explains the decision remains in the
repository under `v03_pilot/` (marked SUPERSEDED): `CORRECTED_CLAIM_MATRIX.md`,
`V03_DEEP_VALIDATION_PACKAGE.md`, `SECOND_FAMILY_SAFETY_ASSESSMENT.md`, `PRODUCTION_PATH_VERIFICATION.md`.

## Provenance

- Source repository: drzilla/Pokerbot
- Source branch: %s
- Source commit (files present): %s
- Per-file path / byte size / SHA-256: see `ARCHIVE_MANIFEST.json` in this archive (and
  `v821_sync/V821_SIZING_LINES_ARCHIVE_MANIFEST.json` in the repo).

The files were removed from the working tree in the subsequent closeout commit; this archive is the
audit copy.
""" % (branch, commit)

manifest = {
    'archive_zip': os.path.basename(ZIP_OUT),
    'archive_zip_location_outside_repo': ZIP_OUT,
    'purpose': 'Audit archive of obsolete per-hand pilot evidence; no longer active product authority.',
    'accepted_feature': 'AGGREGATE flop c-bet sizing-leak detector (heads-up single-raised-pot non-all-in).',
    'source_repository': 'drzilla/Pokerbot',
    'source_branch': branch,
    'source_commit': commit,
    'file_count': len(entries),
    'total_bytes': sum(e['bytes'] for e in entries),
    'files': entries,
    'removed_from_repo': True,
    'retained_in_repo_for_understanding': [
        'v03_pilot/CORRECTED_CLAIM_MATRIX.md', 'v03_pilot/V03_DEEP_VALIDATION_PACKAGE.md',
        'v03_pilot/SECOND_FAMILY_SAFETY_ASSESSMENT.md', 'v03_pilot/PRODUCTION_PATH_VERIFICATION.md',
        'v03_pilot/PRODUCTION_REPORT_EXCERPT.md', 'v03_pilot/AGGREGATE_CLOSEOUT_PACKAGE.md',
        'v03_pilot/DEFERRED_FINDINGS.md', 'v821_sync/ (sync + closeout reports)',
    ],
}

with zipfile.ZipFile(ZIP_OUT, 'w', zipfile.ZIP_DEFLATED) as z:
    for rel in FILES:
        z.write(os.path.join(REPO, rel), arcname=rel)
    z.writestr('README.md', README)
    z.writestr('ARCHIVE_MANIFEST.json', json.dumps(manifest, indent=2))

zsha = sha256_bytes(open(ZIP_OUT, 'rb').read())
open(ZIP_OUT + '.sha256', 'w', encoding='utf-8').write('%s  %s\n' % (zsha, os.path.basename(ZIP_OUT)))
manifest['archive_zip_sha256'] = zsha
json.dump(manifest, open(os.path.join(REPO, 'v821_sync', 'V821_SIZING_LINES_ARCHIVE_MANIFEST.json'),
                         'w', encoding='utf-8'), indent=2)

print('archived %d files (%d bytes) -> %s' % (len(entries), manifest['total_bytes'], ZIP_OUT))
print('zip sha256:', zsha)
print('sidecar   :', ZIP_OUT + '.sha256')
print('manifest  : v821_sync/V821_SIZING_LINES_ARCHIVE_MANIFEST.json')
