#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the actual GEM v8.20.0-rc Claude Chat release candidate ZIP and emit its SHA-256.

The package identity is v8.20.0-rc (a release CANDIDATE), distinct from the released v8.19.0 runtime: the
runtime base is v8.19.0 plus this branch's atomic-packet + cache-only-quick work (current HEAD). Contents:
the self-extracting runtime (gem_lean_runtime.py -- every production module incl. gem_analyst_packet.py +
gem_stage_meter.py), the verifier + suite for clean-room proof, STEP0, the one-pass analyst contract, the
packet schema, the upload manifest, dry-run prompts, rollback, and a MANIFEST.json of sha256 + sizes.

No tag, no deploy. Output: C:/mnt/user-data/outputs/release_v8200rc/.
"""
import io, os, sys, json, shutil, hashlib, zipfile, subprocess

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = r'C:/mnt/user-data/outputs/release_v8200rc'
STAGE = os.path.join(OUT, 'pkg')
ZIP_NAME = 'GEM_v8.20.0-rc_CLAUDE_CHAT.zip'
PKG_ID = 'v8.20.0-rc'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()


def commit():
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                                       stderr=subprocess.DEVNULL).decode().strip()[:12]
    except Exception:
        return 'unknown'


STEP0 = """# STEP0 — GEM {pkg} setup (Claude Chat + local clean-room)

This package's runtime base is the released v8.19.0 runtime PLUS the v8.20 atomic analyst-packet and
cache-only quick-render work (commit {commit}). Package identity: {pkg} (release CANDIDATE — not deployed).

## Extract the runtime (always first)
```
python gem_lean_runtime.py /home/claude/gem && cd /home/claude/gem
```
This self-extracts every production module (incl. gem_analyst_packet.py + gem_stage_meter.py) and the
runtime data files.

## Canonical full run (emits the ONE sealed atomic analyst packet + deterministic cache)
```
python gem_analyzer.py <SESSION_DIR>
```
Emits, next to the report: analyst_packet_<player>.json (semantically atomic, one verdict-ready record per
required decision), _manifest.json, _semantic_audit.json (must be 0 failing / 0 future-information leaks),
_completeness.json, _coverage.json, _oracle.json (prior verdicts kept OUT of the analyst packet), and the
cache-identity fingerprint. In analyst mode a non-atomic packet FAILS CLOSED.

## Cache-only quick render (after the analyst returns one JSON)
```
python gem_analyzer.py <SESSION_DIR> --quick
```
Validates the packet hash + analyst-output binding and renders only from the deterministic cache. It does
ZERO parse/reference/analyze/detector/worklist/packet work (proven in
analyst_packet_<player>_quick_stage_telemetry.json) and fails closed on a tampered packet, an unbound or
invalid analyst output, or a stale/missing cache (no silent full-run fallback).
"""

UPLOAD = """# Upload manifest — what to give private Claude Chat, in order

Upload ONLY these to the private Claude Chat project (the runtime is self-contained):

1. `gem_lean_runtime.py`  — the self-extracting production runtime
2. `STEP0.md`             — setup + the two canonical commands
3. `ANALYST_ONE_PASS_CONTRACT.md` — the one-pass review rules
4. `ANALYST_PACKET_SCHEMA.json`   — the packet + output schema

Then, per session, upload the emitted `analyst_packet_<player>.json` for the analyst to review.

The remaining files in this ZIP (`verify_release.py`, `_test_scratch.py`, `self_verify.py`,
`MANIFEST.json`) are for the LOCAL clean-room proof and are not uploaded to Chat.
"""

SETUP_PROMPT = """# Setup prompt (paste once into the private Claude Chat project)

You are the GEM poker analyst. You will receive ONE sealed analyst packet JSON per session. It already
contains every fact and every pre-completed calculation. Follow ANALYST_ONE_PASS_CONTRACT.md exactly:
review every `required` decision once, review `optional` up to `manifest.optional_cap`, emit one
schema-valid JSON, and stop. Do not fetch, search, decode the report, run code, or compute any new number.
"""

ANALYST_PROMPT = """# One-pass analyst prompt (paste with each packet)

Here is `analyst_packet_<player>.json`. Review it in a single pass per ANALYST_ONE_PASS_CONTRACT.md and
return ONLY this JSON (no prose):

{
  "session_id": "<manifest.session_id>",
  "packet_hash": "<manifest.packet_hash>",
  "verdicts": [
    {"decision_id": "<id>", "verdict": "CONFIRMED_MISTAKE|JUSTIFIED|READ_DEPENDENT|INSUFFICIENT_EVIDENCE|DETECTOR_BUG",
     "reason": "<only numbers already in the decision record>",
     "better_action": "<required only when CONFIRMED_MISTAKE>"}
  ]
}

Exactly one verdict per `required` decision. Cite no number that is not already in the decision record.
Save your reply locally as `analyst_packet_<player>_analyst_output.json`.
"""

ROLLBACK = """# Rollback

This package is a release CANDIDATE ({pkg}, commit {commit}); nothing is deployed by installing it.

- To stop using it: delete the extracted `/home/claude/gem` runtime and re-extract the prior
  released v8.19.0 runtime. The released v8.19.0 Claude Chat project is unchanged by this candidate.
- The analyst packet + quick-render flow are additive: a full run without the analyst step still
  produces the standard report. Removing the packet files has no effect on a fresh full run.
- No production branch, tag, or Claude Chat project was modified to build this candidate.
"""

PROMOTION = """# Promotion (only after a passing private dry run)

If the private Claude Chat dry run passes the checklist, the EXACT unchanged ZIP
({zip} sha256 {zsha}) may be promoted: upload its four Chat files to the production project, replacing the
prior runtime. Do not rebuild or re-extract; promote the identical bytes. If the dry run fails, make ONE
bounded fix based only on the observed failure and rebuild.
"""

CHECKLIST = """# Pass/fail checklist (private dry run)

- [ ] STEP0 extracts the runtime with no import errors.
- [ ] `python gem_analyzer.py <SESSION_DIR>` exits 0 and prints "Sealed atomic analyst packet ... semantic_failing=0 future_leaks=0".
- [ ] analyst_packet_<player>_semantic_audit.json: zero_silently_incomplete and zero_future_information_leaks both true.
- [ ] The analyst returns ONE JSON with exactly one verdict per required decision (no extra prose, no invented numbers).
- [ ] `python gem_analyzer.py <SESSION_DIR> --quick` exits 0 and prints "zero forbidden work {parse,reference,analyze,detector,worklist,packet}=0".
- [ ] A deliberately edited packet or analyst output makes --quick exit non-zero (fail-closed).
- [ ] The rendered report reflects the analyst verdicts.
"""


def _freeze_identity(c):
    """Bake the git-independent build identity into gem_build_identity.py so the EXTRACTED runtime knows it
    is v8.20.0-rc @ <commit> WITHOUT git (owner blocker #5)."""
    import re
    p = os.path.join(REPO, 'gem_build_identity.py')
    src = io.open(p, encoding='utf-8').read()
    src = re.sub(r"SOURCE_COMMIT = '[^']*'", "SOURCE_COMMIT = '%s'" % c, src, count=1)
    src = re.sub(r"BUILD_ID = '[^']*'", "BUILD_ID = 'GEM-%s-%s'" % (PKG_ID, c[:12]), src, count=1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(src)


def _restore_identity():
    """Restore the dev (self-deriving) gem_build_identity.py so the repo is left clean after the build."""
    subprocess.run(['git', 'checkout', '--', 'gem_build_identity.py'], cwd=REPO,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _regen_lean():
    """Regenerate gem_lean_runtime.py so it bundles the frozen gem_build_identity.py + the current runtime."""
    subprocess.check_call([sys.executable, os.path.join(REPO, '_build_lean_runtime.py')], cwd=REPO,
                          stdout=subprocess.DEVNULL)


def main():
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)
    c = commit()
    _freeze_identity(c)          # bake the git-independent identity, then bundle it
    try:
        _regen_lean()            # gem_lean_runtime.py now carries the frozen v8.20.0-rc identity
        _build_body(c)
    finally:
        _restore_identity()      # leave the repo clean (dev identity restored)


def _build_body(c):
    import gem_build_identity as _bid
    _idy = _bid.build_identity()
    # 1) runtime + clean-room verifier/suite + schema (copied from the repo at HEAD)
    for f in ('gem_lean_runtime.py', 'verify_release.py', '_test_scratch.py', 'gem_schema.json'):
        shutil.copy2(os.path.join(REPO, f), os.path.join(STAGE, f))
    # 2) the one-pass contract (authored earlier this branch)
    contract_src = r'C:/mnt/user-data/outputs/v820_wave1a2a/ANALYST_ONE_PASS_CONTRACT.md'
    if os.path.isfile(contract_src):
        shutil.copy2(contract_src, os.path.join(STAGE, 'ANALYST_ONE_PASS_CONTRACT.md'))
    # 3) the packet schema (from the live module identity)
    import gem_analyst_packet as ap
    schema = {'schema': ap.SCHEMA_VERSION, 'allowed_verdicts': sorted(ap.ALLOWED_VERDICTS),
              'required_output_fields': list(getattr(ap, 'REQUIRED_OUTPUT_FIELDS', [])),
              'decision_record_fields': ['decision_id', 'hand_id', 'family', 'street', 'hero_action',
                  'hero_cards', 'board', 'made_hand_class', 'draw_profile', 'board_texture', 'position',
                  'ip_oop', 'active_players', 'pot_before_bb', 'amount_to_call_bb', 'chosen_incremental_bb',
                  'chosen_total_bb', 'eff_stack_bb', 'action_line_through_decision', 'detector_reason',
                  'evidence_ref', 'evidence_tier', 'allowed_verdicts'],
              'output': {'session_id': 'str', 'packet_hash': 'str',
                         'verdicts': [{'decision_id': 'str', 'verdict': 'enum', 'reason': 'str',
                                       'better_action': 'str (when CONFIRMED_MISTAKE)'}]}}
    io.open(os.path.join(STAGE, 'ANALYST_PACKET_SCHEMA.json'), 'w', encoding='utf-8').write(
        json.dumps(schema, indent=2))
    # 4) docs
    docs = {'STEP0.md': STEP0, 'UPLOAD_MANIFEST.md': UPLOAD, 'SETUP_PROMPT.md': SETUP_PROMPT,
            'ANALYST_PROMPT.md': ANALYST_PROMPT, 'ROLLBACK.md': ROLLBACK, 'PROMOTION.md': PROMOTION,
            'PASS_FAIL_CHECKLIST.md': CHECKLIST}
    for name, body in docs.items():
        body = (body.replace('{pkg}', PKG_ID).replace('{commit}', c)
                    .replace('{zip}', ZIP_NAME).replace('{zsha}', 'see ' + ZIP_NAME + '.sha256'))
        io.open(os.path.join(STAGE, name), 'w', encoding='utf-8', newline='\n').write(body)
    # 5) self_verify.py (re-checks MANIFEST hashes + re-extracts the runtime + imports it)
    io.open(os.path.join(STAGE, 'self_verify.py'), 'w', encoding='utf-8', newline='\n').write(SELF_VERIFY)
    # 6) MANIFEST.json (sha256 + size of every staged file except the manifest)
    files = {}
    for rel in sorted(os.listdir(STAGE)):
        full = os.path.join(STAGE, rel)
        if os.path.isfile(full):
            files[rel] = {'sha256': sha256(full), 'size': os.path.getsize(full)}
    manifest = {'package': 'GEM %s Claude Chat candidate' % PKG_ID, 'runtime_base': 'v8.19.0',
                'runtime_commit': c, 'release_candidate': PKG_ID, 'build_identity': _idy,
                'report_schema': _idy.get('report_schema'), 'packet_schema': ap.SCHEMA_VERSION,
                'files': files}
    io.open(os.path.join(STAGE, 'MANIFEST.json'), 'w', encoding='utf-8', newline='\n').write(
        json.dumps(manifest, indent=2, ensure_ascii=False))
    # 7) zip + package sha
    os.makedirs(OUT, exist_ok=True)
    zip_path = os.path.join(OUT, ZIP_NAME)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(os.listdir(STAGE)):
            z.write(os.path.join(STAGE, rel), rel)
    zsha = sha256(zip_path)
    print('BUILT %s  (%.2f MB)  files=%d  commit=%s' % (ZIP_NAME, os.path.getsize(zip_path) / 1e6,
                                                        len(files), c))
    print('PACKAGE_SHA256 %s' % zsha)
    io.open(os.path.join(OUT, ZIP_NAME + '.sha256'), 'w', encoding='utf-8', newline='\n').write(
        zsha + '  ' + ZIP_NAME + '\n')


SELF_VERIFY = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-verify this candidate from a FRESH extraction: re-check every MANIFEST hash, then re-extract +
import the packaged runtime and confirm gem_analyst_packet + gem_stage_meter are present. Exit 0 if OK."""
import io, os, sys, json, hashlib, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f: h.update(f.read())
    return h.hexdigest()
man = json.load(io.open(os.path.join(HERE, 'MANIFEST.json'), encoding='utf-8'))
bad = []
for rel, rec in man['files'].items():
    p = os.path.join(HERE, rel)
    if not os.path.isfile(p): bad.append((rel, 'MISSING')); continue
    if sha(p) != rec['sha256'] or os.path.getsize(p) != rec['size']: bad.append((rel, 'MISMATCH'))
print('MANIFEST: %d files, %d mismatched' % (len(man['files']), len(bad)))
for b in bad: print('  FAIL', b)
rt = os.path.join(HERE, '_rt')
os.makedirs(rt, exist_ok=True)
subprocess.check_call([sys.executable, os.path.join(HERE, 'gem_lean_runtime.py'), rt])
need = ['gem_analyzer.py', 'gem_analyst_packet.py', 'gem_stage_meter.py']
miss = [f for f in need if not os.path.isfile(os.path.join(rt, f))]
print('runtime modules present:', not miss, '' if not miss else miss)
sys.exit(0 if (not bad and not miss) else 1)
'''


if __name__ == '__main__':
    main()
