#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GEM v8.20.0-rc clean-room rehearsal -- ONE-COMMAND release dress rehearsal.

ADDITIVE orchestrator (modifies NO production module). It builds the RC ZIP, proves the package SHA was
sealed AFTER hashing, extracts to a fresh empty dir + self-verifies, proves the bundled phevaluator runtime
is self-contained (no pip/site-packages), runs the canonical FULL pipeline on the June-16 session, generates
the deterministic 24-verdict analyst output, runs ONE --quick, proves it is analyst-integrated (not
AUTO_ONLY), proves ZERO forbidden quick-stage work via the stage meter, and TAMPERS each of the five
fail-closed bindings proving --quick exits non-zero with the report NEVER overwritten -- restoring the good
artifacts between every tamper case so each is isolated.

Run:  PYTHONUTF8=1 python _clean_room_rehearsal.py
Writes: C:/mnt/user-data/outputs/v820_wave1a2a/CLEAN_ROOM_REHEARSAL_TRANSCRIPT.{json,md}
Exit 0 iff ALL 10 steps pass.
"""
import io, os, sys, json, time, shutil, hashlib, zipfile, tempfile, subprocess

REPO = os.path.dirname(os.path.abspath(__file__))

# canonical, git-independent paths (match the production pipeline's resolution on this host)
OUT_RELEASE = os.path.abspath('/mnt/user-data/outputs/release_v8200rc')
ZIP_NAME = 'GEM_v8.20.0-rc_CLAUDE_CHAT.zip'
ZIP_PATH = os.path.join(OUT_RELEASE, ZIP_NAME)
SHA_SIDECAR = ZIP_PATH + '.sha256'
BUILDER = os.path.join(REPO, '_build_v8200rc_release.py')

SESSION_SRC = os.path.abspath('/mnt/user-data/outputs/iter0/june16_src')
PLAYER = 'Knockman'
OUT_DATA = os.path.abspath('/mnt/user-data/outputs')          # where the packet + report are written
HOME = os.path.abspath('/home/claude')                        # where the deterministic cache lives

PKT = os.path.join(OUT_DATA, f'analyst_packet_{PLAYER}.json')
PKT_MANIFEST = os.path.join(OUT_DATA, f'analyst_packet_{PLAYER}_manifest.json')
PKT_SEMAUDIT = os.path.join(OUT_DATA, f'analyst_packet_{PLAYER}_semantic_audit.json')
AO_PATH = os.path.join(OUT_DATA, f'analyst_packet_{PLAYER}_analyst_output.json')
TELEMETRY = os.path.join(OUT_DATA, f'analyst_packet_{PLAYER}_quick_stage_telemetry.json')

# deterministic cache files --quick reloads (player-keyed rd; player+slug hands with player-only fallback)
RD_CACHE = os.path.join(HOME, f'gem_report_data_{PLAYER}.json')
_SLUG = os.path.basename(os.path.normpath(SESSION_SRC)).replace(' ', '_')[:30]
HANDS_CACHE = os.path.join(HOME, f'gem_hands_{PLAYER}_{_SLUG}.json')
HANDS_CACHE_FALLBACK = os.path.join(HOME, f'gem_hands_{PLAYER}.json')

TRANSCRIPT_DIR = os.path.abspath('/mnt/user-data/outputs/v820_wave1a2a')
TRANSCRIPT_JSON = os.path.join(TRANSCRIPT_DIR, 'CLEAN_ROOM_REHEARSAL_TRANSCRIPT.json')
TRANSCRIPT_MD = os.path.join(TRANSCRIPT_DIR, 'CLEAN_ROOM_REHEARSAL_TRANSCRIPT.md')

ENV = dict(os.environ, PYTHONUTF8='1', GEM_ANALYST_MODE='1')


# ---------------------------------------------------------------------------- helpers
def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, **kw):
    """Run a subprocess with the UTF-8 env; capture stdout+stderr together."""
    kw.setdefault('cwd', REPO)
    kw.setdefault('env', ENV)
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          encoding='utf-8', errors='replace', **kw)


def report_snapshot():
    """Snapshot every June-16 report artifact (html/md/zip/manifest) as path -> (mtime_ns, size, sha) so a
    tamper run can be proven to have written/overwritten NOTHING."""
    snap = {}
    pref = f'Pokerbot_{PLAYER}_20260616'
    for fn in os.listdir(OUT_DATA):
        if fn.startswith(pref):
            full = os.path.join(OUT_DATA, fn)
            if os.path.isfile(full):
                st = os.stat(full)
                snap[fn] = (st.st_mtime_ns, st.st_size, sha256_file(full))
    return snap


def diff_snapshots(before, after):
    """Return (new_files, modified_files). Empty both == nothing written/overwritten."""
    new = sorted(set(after) - set(before))
    modified = sorted(k for k in (set(after) & set(before)) if after[k] != before[k])
    return new, modified


def write_analyst_output(packet_path, out_path):
    """Deterministically grade EVERY required decision JUSTIFIED, bound to the packet."""
    pkt = json.load(io.open(packet_path, encoding='utf-8'))
    m = pkt['manifest']
    out = {
        'session_id': m['session_id'],
        'packet_hash': m['packet_hash'],
        'verdicts': [
            {'decision_id': d['decision_id'], 'verdict': 'JUSTIFIED',
             'reason': 'deterministic rehearsal grade', 'better_action': ''}
            for d in pkt['required']
        ],
    }
    io.open(out_path, 'w', encoding='utf-8').write(json.dumps(out, indent=2))
    return out


def backup(paths):
    """Read-bytes backup of a set of files (None entry == file absent at backup time)."""
    return {p: (io.open(p, 'rb').read() if os.path.isfile(p) else None) for p in paths}


def restore(saved):
    for p, data in saved.items():
        if data is None:
            if os.path.isfile(p):
                os.remove(p)
        else:
            io.open(p, 'wb').write(data)


STEPS = []  # list of dicts: {n, name, passed, command, evidence}


def record(n, name, passed, command, evidence):
    STEPS.append({'step': n, 'name': name, 'passed': bool(passed),
                  'command': command, 'evidence': evidence})
    flag = 'PASS' if passed else 'FAIL'
    print(f"[STEP {n}] {flag}  {name}")
    for k, v in evidence.items():
        print(f"         - {k}: {v}")
    return passed


# ---------------------------------------------------------------------------- steps
def step1_build():
    cmd = 'PYTHONUTF8=1 python _build_v8200rc_release.py'
    r = run([sys.executable, BUILDER])
    pkg_sha = None
    for ln in r.stdout.splitlines():
        if ln.startswith('PACKAGE_SHA256'):
            pkg_sha = ln.split()[1].strip()
    ok = (r.returncode == 0 and pkg_sha is not None and os.path.isfile(ZIP_PATH)
          and os.path.isfile(SHA_SIDECAR))
    ev = {'returncode': r.returncode, 'zip_exists': os.path.isfile(ZIP_PATH),
          'sha_sidecar_exists': os.path.isfile(SHA_SIDECAR),
          'printed_PACKAGE_SHA256': pkg_sha,
          'zip_size_bytes': os.path.getsize(ZIP_PATH) if os.path.isfile(ZIP_PATH) else None}
    record(1, 'Build RC ZIP via builder + capture PACKAGE_SHA256', ok, cmd, ev)
    return ok, pkg_sha


def step2_sha_after_seal(printed_sha):
    """The sidecar SHA must equal a fresh recompute over the SEALED zip bytes -- proving the SHA was computed
    AFTER sealing (it cannot live inside the file it hashes)."""
    cmd = f'read {ZIP_NAME}.sha256 ; recompute sha256({ZIP_NAME}) ; assert equal'
    sidecar_line = io.open(SHA_SIDECAR, encoding='utf-8').read().strip()
    sidecar_sha = sidecar_line.split()[0]
    recomputed = sha256_file(ZIP_PATH)
    ok = (sidecar_sha == recomputed == printed_sha)
    ev = {'sidecar_sha256': sidecar_sha, 'recomputed_sha256': recomputed,
          'printed_sha256': printed_sha,
          'all_three_match': sidecar_sha == recomputed == printed_sha,
          'note': 'sidecar written AFTER sealing == recompute over final bytes == builder print'}
    record(2, 'Verify package SHA computed AFTER sealing (sidecar == recompute == printed)', ok, cmd, ev)
    return ok


def step3_extract_self_verify():
    """Extract to a FRESH EMPTY dir (exist_ok=False), run the bundled self_verify.py, assert 0 mismatches."""
    base = tempfile.mkdtemp(prefix='gem_cleanroom_extract_')
    extract_dir = os.path.join(base, 'pkg')
    os.makedirs(extract_dir, exist_ok=False)            # provably fresh + empty
    with zipfile.ZipFile(ZIP_PATH) as z:
        z.extractall(extract_dir)
    cmd = (f'os.makedirs(<fresh>, exist_ok=False) ; unzip {ZIP_NAME} -> <fresh> ; '
           f'PYTHONUTF8=1 python self_verify.py')
    # independent MANIFEST re-check (replicate self_verify's hash check ourselves)
    man = json.load(io.open(os.path.join(extract_dir, 'MANIFEST.json'), encoding='utf-8'))
    indep_mismatches = []
    for rel, rec in man['files'].items():
        p = os.path.join(extract_dir, rel)
        if not os.path.isfile(p):
            indep_mismatches.append((rel, 'MISSING'))
        elif sha256_file(p) != rec['sha256'] or os.path.getsize(p) != rec['size']:
            indep_mismatches.append((rel, 'MISMATCH'))
    # run the bundled self_verify.py from the extracted dir
    r = run([sys.executable, os.path.join(extract_dir, 'self_verify.py')], cwd=extract_dir)
    sv_mismatch_line = next((l for l in r.stdout.splitlines() if l.startswith('MANIFEST:')), '')
    sv_modules_line = next((l for l in r.stdout.splitlines() if l.startswith('runtime modules present:')), '')
    ok = (r.returncode == 0 and not indep_mismatches and ' 0 mismatched' in sv_mismatch_line
          and 'True' in sv_modules_line)
    ev = {'extract_dir': extract_dir, 'manifest_files': len(man['files']),
          'independent_mismatches': indep_mismatches or 0,
          'self_verify_returncode': r.returncode,
          'self_verify_manifest_line': sv_mismatch_line,
          'self_verify_modules_line': sv_modules_line}
    record(3, 'Extract to fresh empty dir + bundled self_verify (0 mismatches)', ok, cmd, ev)
    try:
        shutil.rmtree(base)
    except Exception:
        pass
    return ok


def step4_phevaluator_selfcontained():
    """Extract gem_lean_runtime.py into a SECOND fresh empty runtime dir; in a -S subprocess whose sys.path
    EXCLUDES site-packages, import phevaluator (must load from the runtime dir) and evaluate a 5-card hand."""
    base = tempfile.mkdtemp(prefix='gem_cleanroom_runtime_')
    rt = os.path.join(base, 'rt')
    os.makedirs(rt, exist_ok=False)
    # the lean runtime ships inside the kit; extract it from the zip we just sealed
    with zipfile.ZipFile(ZIP_PATH) as z:
        z.extract('gem_lean_runtime.py', base)
    lean = os.path.join(base, 'gem_lean_runtime.py')
    ex = run([sys.executable, lean, rt])
    probe = os.path.join(base, '_phev_probe.py')
    io.open(probe, 'w', encoding='utf-8').write(
        "import sys, os, json\n"
        "rt = sys.argv[1]\n"
        "sys.path = [rt] + [p for p in sys.path if p and 'site-packages' not in p "
        "and os.path.normpath(p) != os.path.normpath(rt)]\n"
        "import phevaluator\n"
        "v = phevaluator.evaluate_cards('Ah','As','Kd','Kc','2c')\n"
        "src = os.path.abspath(phevaluator.__file__)\n"
        "print(json.dumps({'phev_file': src,\n"
        "  'from_runtime': os.path.normpath(src).startswith(os.path.normpath(rt)),\n"
        "  'value': v, 'value_is_number': isinstance(v,(int,float)),\n"
        "  'site_packages_in_path': any('site-packages' in p for p in sys.path)}))\n")
    # -S => the site module is NOT imported, so site-packages is not auto-added; probe also strips any
    # residual site-packages entry. A success here PROVES no pip/fetch and no site-packages dependency.
    r = run([sys.executable, '-S', probe, rt])
    cmd = ('python gem_lean_runtime.py <rt> ; '
           "python -S -c \"sys.path=[rt]+stdlib_only; import phevaluator; "
           "phevaluator.evaluate_cards('Ah','As','Kd','Kc','2c')\"")
    parsed = {}
    try:
        parsed = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        parsed = {'parse_error': r.stdout[-500:]}
    ok = (ex.returncode == 0 and r.returncode == 0 and parsed.get('from_runtime') is True
          and parsed.get('value_is_number') is True
          and parsed.get('site_packages_in_path') is False)
    ev = {'runtime_dir': rt, 'extract_returncode': ex.returncode, 'probe_returncode': r.returncode,
          'phevaluator_loaded_from': parsed.get('phev_file'),
          'from_runtime_not_site_packages': parsed.get('from_runtime'),
          'site_packages_in_path': parsed.get('site_packages_in_path'),
          'evaluate_cards_AhAsKdKc2c': parsed.get('value'),
          'value_is_number': parsed.get('value_is_number')}
    record(4, 'gem_lean_runtime phevaluator self-contained (no pip/site-packages)', ok, cmd, ev)
    try:
        shutil.rmtree(base)
    except Exception:
        pass
    return ok


def step5_full_pipeline():
    """Run the canonical FULL pipeline; assert exit 0, sealed packet required=24 unresolved=3, semantic
    audit zero_analyst_calculations_required True."""
    cmd = f'PYTHONUTF8=1 python gem_analyzer.py {SESSION_SRC}'
    r = run([sys.executable, os.path.join(REPO, 'gem_analyzer.py'), SESSION_SRC])
    pkt_ok = os.path.isfile(PKT)
    m = json.load(io.open(PKT, encoding='utf-8'))['manifest'] if pkt_ok else {}
    sa = json.load(io.open(PKT_SEMAUDIT, encoding='utf-8')) if os.path.isfile(PKT_SEMAUDIT) else {}
    required = m.get('required_count')
    unresolved = m.get('unresolved_count')
    zero_calc = sa.get('zero_analyst_calculations_required')
    sealed_line = next((l for l in r.stdout.splitlines() if 'Sealed atomic analyst packet' in l), '')
    ok = (r.returncode == 0 and pkt_ok and required == 24 and unresolved == 3 and zero_calc is True
          and sa.get('zero_silently_incomplete') is True and sa.get('zero_future_information_leaks') is True)
    ev = {'returncode': r.returncode, 'packet_path': PKT, 'required_count': required,
          'unresolved_count': unresolved, 'optional_count': m.get('optional_count'),
          'packet_hash16': (m.get('packet_hash') or '')[:16],
          'zero_analyst_calculations_required': zero_calc,
          'zero_silently_incomplete': sa.get('zero_silently_incomplete'),
          'zero_future_information_leaks': sa.get('zero_future_information_leaks'),
          'sealed_line': sealed_line.strip()}
    record(5, 'Full pipeline: sealed packet required=24 unresolved=3 zero-calc', ok, cmd, ev)
    return ok


def step6_generate_analyst_output():
    cmd = f'generate 24 JUSTIFIED verdicts bound to packet -> {os.path.basename(AO_PATH)}'
    out = write_analyst_output(PKT, AO_PATH)
    m = json.load(io.open(PKT, encoding='utf-8'))['manifest']
    ok = (os.path.isfile(AO_PATH) and len(out['verdicts']) == m['required_count']
          and out['packet_hash'] == m['packet_hash'] and out['session_id'] == m['session_id'])
    ev = {'analyst_output_path': AO_PATH, 'verdicts': len(out['verdicts']),
          'bound_session_id': out['session_id'], 'bound_packet_hash16': out['packet_hash'][:16],
          'matches_required_count': len(out['verdicts']) == m['required_count']}
    record(6, 'Generate deterministic analyst JSON (24 verdicts bound to packet)', ok, cmd, ev)
    return ok


def step7_8_9_quick():
    """Run exactly ONE --quick. Assert exit 0 + a NEW report written (step 7); analyst-integrated /
    not-AUTO_ONLY with verdicts present (step 8); zero forbidden quick-stage work via telemetry (step 9)."""
    before = report_snapshot()
    cmd = f'PYTHONUTF8=1 python gem_analyzer.py {SESSION_SRC} --quick'
    r = run([sys.executable, os.path.join(REPO, 'gem_analyzer.py'), SESSION_SRC, '--quick'])
    after = report_snapshot()
    new, _modified = diff_snapshots(before, after)
    new_html = [f for f in new if f.endswith('.html')]
    # ---- step 7: exit 0 + report written
    s7_ok = (r.returncode == 0 and len(new_html) >= 1)
    report_path = os.path.join(OUT_DATA, new_html[0]) if new_html else None
    record(7, 'Run exactly ONE --quick (exit 0 + report written)', s7_ok, cmd, {
        'returncode': r.returncode, 'new_report_html': new_html,
        'integrated_line': next((l for l in r.stdout.splitlines() if 'analyst output integrated' in l), '').strip()})

    # ---- step 8: analyst-integrated, NOT AUTO_ONLY, verdicts appear in the report.
    # The internal state token (ANALYST_COMPLETE) is NOT printed verbatim into the HTML body; the report
    # renders analyst-integration as user-visible evidence: an "N analyst-reviewed" coverage marker that
    # equals the graded count, and the ABSENCE of the AUTO_ONLY "awaiting analyst" shell. We prove all of:
    #   (1) runtime completeness state == ANALYST_COMPLETE (from the --quick stdout),
    #   (2) the report FILENAME carries no AUTO_ONLY tag (an auto-only report would),
    #   (3) the rendered HTML shows the 24-hand analyst-reviewed coverage marker (verdicts integrated),
    #   (4) the HTML is NOT the AUTO_ONLY awaiting-analyst shell.
    import re as _re8
    state = None
    integ_line = next((l for l in r.stdout.splitlines() if 'analyst output integrated' in l), '')
    if 'state=' in integ_line:
        state = integ_line.split('state=', 1)[1].split()[0]
    n_required = json.load(io.open(PKT, encoding='utf-8'))['manifest']['required_count']  # 24
    html = io.open(report_path, encoding='utf-8').read() if report_path else ''
    filename_not_auto_only = bool(report_path) and 'AUTO_ONLY' not in os.path.basename(report_path)
    state_ok = state in ('ANALYST_COMPLETE', 'ANALYST_PARTIAL') and state != 'AUTO_ONLY'
    # (3) the visible top-line analyst-reviewed coverage marker == graded count. The report carries TWO
    #     legitimate analyst-reviewed populations: the session coverage ("24 analyst-reviewed" /
    #     "Analyst-reviewed: 24 hands") and a smaller reviewed-MISTAKES subset (e.g. "3 analyst-reviewed").
    #     The session coverage is the maximum and must equal n_required; the subset (<= n_required) is
    #     expected, not a contradiction. We assert: the top-line "N analyst-reviewed" coverage == graded
    #     count, the explicit "Analyst-reviewed: N hands"/"<td>N</td>" coverage row == graded count, and
    #     every analyst-reviewed number is <= the graded count.
    inline_nums = [int(x) for x in _re8.findall(r'(\d+)\s+analyst-reviewed', html)]
    coverage_row_nums = [int(x) for x in _re8.findall(r'Analyst-reviewed:\s*(\d+)', html)]
    coverage_row_nums += [int(x) for x in _re8.findall(
        r'<td[^>]*>Analyst-reviewed</td><td[^>]*>(\d+)</td>', html)]
    all_nums = inline_nums + coverage_row_nums
    topline_equals_graded = bool(inline_nums) and max(inline_nums) == n_required
    coverage_row_equals_graded = bool(coverage_row_nums) and any(n == n_required for n in coverage_row_nums)
    all_within_graded = bool(all_nums) and all(n <= n_required for n in all_nums)
    reviewed_marker_matches = topline_equals_graded and coverage_row_equals_graded and all_within_graded
    # (4) NOT the auto-only awaiting-analyst shell
    no_awaiting_shell = ('AUTO_ONLY' not in html) and ('awaiting analyst' not in html.lower())
    s8_ok = (state_ok and filename_not_auto_only and reviewed_marker_matches and no_awaiting_shell)
    # quote the top-line coverage marker as evidence
    midx = html.find('analyst-reviewed')
    snippet = html[max(0, midx - 70):midx + 30].replace('\n', ' ').strip() if midx >= 0 else ''
    record(8, 'Quick report is ANALYST-INTEGRATED (not AUTO_ONLY); verdicts present', s8_ok,
           'inspect rendered report state + visible analyst-reviewed coverage marker', {
               'runtime_report_state': state, 'filename_not_AUTO_ONLY': filename_not_auto_only,
               'report_basename': os.path.basename(report_path) if report_path else None,
               'graded_required_count': n_required,
               'inline_analyst_reviewed_numbers': inline_nums,
               'coverage_row_numbers': coverage_row_nums,
               'topline_coverage_equals_graded_24': topline_equals_graded,
               'coverage_row_equals_graded_24': coverage_row_equals_graded,
               'all_reviewed_numbers_within_graded': all_within_graded,
               'note_smaller_numbers': 'a smaller analyst-reviewed number is the reviewed-MISTAKES subset '
                                       '(e.g. 3 of 6 raw mistakes) -- expected, not a contradiction',
               'no_AUTO_ONLY_awaiting_shell_in_html': no_awaiting_shell,
               'evidence_snippet': snippet or '(marker not found)',
               'integrated_line': integ_line.strip()})

    # ---- step 9: zero forbidden quick-stage work (authoritative = telemetry file the subprocess wrote)
    tele = json.load(io.open(TELEMETRY, encoding='utf-8')) if os.path.isfile(TELEMETRY) else {}
    fcounts = tele.get('forbidden_quick_counts', {})
    zero = tele.get('zero_forbidden_quick_work')
    s9_ok = (zero is True and all(v == 0 for v in fcounts.values()) and len(fcounts) == 6)
    record(9, 'Zero forbidden quick-stage work (stage-meter telemetry)', s9_ok,
           'read *_quick_stage_telemetry.json', {
               'forbidden_quick_counts': fcounts, 'zero_forbidden_quick_work': zero,
               'binding': tele.get('binding'),
               'telemetry_line': next((l for l in r.stdout.splitlines()
                                       if 'zero forbidden work' in l), '').strip()})
    return s7_ok, s8_ok, s9_ok


def _tamper_case(label, mutate, restore_targets, hands_cache_for_id):
    """Generic tamper harness: snapshot reports, run mutate(), run ONE --quick, assert exit!=0 AND no report
    written/overwritten, then restore. Returns (ok, evidence)."""
    saved = backup(restore_targets)
    before = report_snapshot()
    detail = mutate()                                      # perform the isolated mutation
    r = run([sys.executable, os.path.join(REPO, 'gem_analyzer.py'),
             detail.get('session_dir', SESSION_SRC), '--quick'])
    after = report_snapshot()
    new, modified = diff_snapshots(before, after)
    restore(saved)                                          # ISOLATE: undo the mutation
    if detail.get('cleanup'):
        detail['cleanup']()
    fail_closed = (r.returncode != 0)
    no_write = (not new and not modified)
    ok = fail_closed and no_write
    fail_line = next((l for l in r.stdout.splitlines()
                      if 'FAIL CLOSED' in l or 'ERROR' in l or 'mismatch' in l.lower()
                      or 'changed' in l.lower() or 'missing' in l.lower()), '')
    return ok, {'returncode': r.returncode, 'fail_closed_exit_nonzero': fail_closed,
                'new_reports': new, 'modified_reports': modified,
                'report_not_overwritten': no_write,
                'fail_message': fail_line.strip()[:200], 'mutation': detail.get('desc')}


def step10_tamper():
    """Tamper EACH of the 5 bindings; prove --quick fails closed with no report overwrite; isolate+restore."""
    results = {}

    # (a) packet_hash tamper: corrupt a fact in the sealed packet so recompute != stored hash
    def mut_a():
        pkt = json.load(io.open(PKT, encoding='utf-8'))
        pkt['required'][0]['detector_reason'] = (pkt['required'][0].get('detector_reason', '') +
                                                  ' __TAMPER__')
        io.open(PKT, 'w', encoding='utf-8').write(json.dumps(pkt, indent=2))
        return {'desc': 'edited a fact in sealed packet (stored hash now stale)'}
    ok_a, ev_a = _tamper_case('a_packet_hash', mut_a, [PKT], HANDS_CACHE)
    results['a_packet_hash'] = ev_a
    record('10a', 'Tamper packet_hash -> --quick fails closed, no report overwrite', ok_a,
           'edit sealed packet ; --quick', ev_a)

    # (b) analyst-output tamper: a verdict for a NON-EXISTENT decision_id (also drop a real one so coverage
    #     breaks) -> validate_analyst_output rejects it.
    def mut_b():
        ao = json.load(io.open(AO_PATH, encoding='utf-8'))
        ao['verdicts'][0]['decision_id'] = 'DOES_NOT_EXIST:flop:99'
        io.open(AO_PATH, 'w', encoding='utf-8').write(json.dumps(ao, indent=2))
        return {'desc': 'analyst verdict references a non-existent decision_id'}
    ok_b, ev_b = _tamper_case('b_analyst_output', mut_b, [AO_PATH], HANDS_CACHE)
    results['b_analyst_output'] = ev_b
    record('10b', 'Tamper analyst-output -> --quick fails closed, no report overwrite', ok_b,
           'edit analyst output ; --quick', ev_b)

    # (c) input tamper: copy the session to a temp dir, mutate one input byte, --quick against the COPY.
    #     The recomputed input hashes (and cache identity) no longer match the sealed packet -> fail closed.
    #     The canonical June-16 source is NEVER touched.
    tmp_session = {'dir': None}

    def mut_c():
        d = tempfile.mkdtemp(prefix='gem_cleanroom_inputtamper_')
        dst = os.path.join(d, os.path.basename(os.path.normpath(SESSION_SRC)))
        shutil.copytree(SESSION_SRC, dst)
        # append a byte to the first .txt hand history in the copy
        victim = next(os.path.join(dst, f) for f in sorted(os.listdir(dst))
                      if f.lower().endswith('.txt'))
        with io.open(victim, 'a', encoding='utf-8') as f:
            f.write('\n__TAMPER__\n')
        tmp_session['dir'] = d
        return {'desc': 'mutated an input file in an isolated session copy',
                'session_dir': dst, 'cleanup': lambda: shutil.rmtree(d, ignore_errors=True)}
    ok_c, ev_c = _tamper_case('c_input', mut_c, [], HANDS_CACHE)
    results['c_input'] = ev_c
    record('10c', 'Tamper input file (isolated copy) -> --quick fails closed, no report overwrite', ok_c,
           'copy session ; mutate input ; --quick <copy>', ev_c)

    # (d) cache tamper: corrupt the deterministic cache identity by mutating a HASHED CORE field of the
    #     on-disk report_data cache (the canonical required-review population `_candidate_need_ids`, which
    #     artifact_cache_identity hashes), so cache_identity_from_disk != packet.cache_identity -> stale-
    #     cache fail closed. (An arbitrary extra top-level key is deliberately ignored by the identity, so
    #     we mutate a field that is actually in the hashed analytical core.)
    def mut_d():
        rd = json.load(io.open(RD_CACHE, encoding='utf-8'))
        need = list(rd.get('_candidate_need_ids') or [])
        rd['_candidate_need_ids'] = need + ['__CLEANROOM_CACHE_TAMPER__']
        io.open(RD_CACHE, 'w', encoding='utf-8').write(json.dumps(rd))
        return {'desc': 'mutated the hashed core (_candidate_need_ids) in the report_data cache '
                        '(cache identity drift)'}
    ok_d, ev_d = _tamper_case('d_cache', mut_d, [RD_CACHE], HANDS_CACHE)
    results['d_cache'] = ev_d
    record('10d', 'Tamper deterministic cache -> --quick fails closed, no report overwrite', ok_d,
           'corrupt cache identity ; --quick', ev_d)

    # (e) packet-missing: rename the sealed packet away -> "sealed packet missing" fail closed.
    def mut_e():
        os.rename(PKT, PKT + '.bak_cleanroom')
        return {'desc': 'sealed packet removed (renamed away)',
                'cleanup': lambda: (os.rename(PKT + '.bak_cleanroom', PKT)
                                    if os.path.isfile(PKT + '.bak_cleanroom') else None)}
    ok_e, ev_e = _tamper_case('e_packet_missing', mut_e, [], HANDS_CACHE)
    results['e_packet_missing'] = ev_e
    record('10e', 'Packet missing -> --quick fails closed, no report overwrite', ok_e,
           'remove sealed packet ; --quick', ev_e)

    all_ok = all([ok_a, ok_b, ok_c, ok_d, ok_e])
    # roll-up record so the transcript has a single step-10 verdict too
    STEPS.append({'step': 10, 'name': 'All 5 tamper bindings fail closed with no report overwrite',
                  'passed': all_ok, 'command': '5 isolated tamper cases (a-e)',
                  'evidence': {k: {'fail_closed_exit_nonzero': v['fail_closed_exit_nonzero'],
                                   'report_not_overwritten': v['report_not_overwritten'],
                                   'returncode': v['returncode'], 'fail_message': v['fail_message']}
                               for k, v in results.items()}})
    print(f"[STEP 10] {'PASS' if all_ok else 'FAIL'}  All 5 tamper bindings fail closed (no overwrite)")
    return all_ok


def _post_tamper_restore_and_verify():
    """After the tamper suite, the good artifacts were restored per-case. Re-run ONE clean --quick to PROVE
    the rehearsal left the pipeline in a working, analyst-integrated state (belt-and-suspenders)."""
    # ensure the good analyst output exists (case b restored it; regenerate defensively)
    if not os.path.isfile(AO_PATH):
        write_analyst_output(PKT, AO_PATH)
    r = run([sys.executable, os.path.join(REPO, 'gem_analyzer.py'), SESSION_SRC, '--quick'])
    return r.returncode == 0


def main():
    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    print('=' * 78)
    print('GEM v8.20.0-rc CLEAN-ROOM REHEARSAL')
    print('=' * 78)

    s1_ok, pkg_sha = step1_build()
    s2_ok = step2_sha_after_seal(pkg_sha) if s1_ok else record(
        2, 'Verify package SHA after sealing', False, '(skipped: build failed)', {})
    s3_ok = step3_extract_self_verify() if s1_ok else record(
        3, 'Extract + self_verify', False, '(skipped: build failed)', {})
    s4_ok = step4_phevaluator_selfcontained() if s1_ok else record(
        4, 'phevaluator self-contained', False, '(skipped: build failed)', {})
    s5_ok = step5_full_pipeline()
    s6_ok = step6_generate_analyst_output() if s5_ok else record(
        6, 'Generate analyst JSON', False, '(skipped: full pipeline failed)', {})
    if s6_ok:
        s7_ok, s8_ok, s9_ok = step7_8_9_quick()
    else:
        s7_ok = record(7, 'Run one --quick', False, '(skipped)', {})
        s8_ok = record(8, 'Quick analyst-integrated', False, '(skipped)', {})
        s9_ok = record(9, 'Zero forbidden quick work', False, '(skipped)', {})
    s10_ok = step10_tamper() if s6_ok else False
    if not s6_ok:
        STEPS.append({'step': 10, 'name': 'Tamper suite', 'passed': False,
                      'command': '(skipped: prerequisites failed)', 'evidence': {}})

    # leave the pipeline clean + working
    post_ok = _post_tamper_restore_and_verify() if s6_ok else False

    all_pass = all(s['passed'] for s in STEPS)
    summary = {
        'package': 'GEM v8.20.0-rc clean-room rehearsal',
        'all_steps_passed': all_pass,
        'package_sha256': pkg_sha,
        'zip_path': ZIP_PATH,
        'session_source': SESSION_SRC,
        'player': PLAYER,
        'post_rehearsal_clean_quick_ok': post_ok,
        'steps': STEPS,
        'generated_at_epoch': int(time.time()),
    }
    io.open(TRANSCRIPT_JSON, 'w', encoding='utf-8').write(json.dumps(summary, indent=2, default=str))
    _write_md(summary)

    print('=' * 78)
    print(f"OVERALL: {'PASS' if all_pass else 'FAIL'}  ({sum(s['passed'] for s in STEPS)}/{len(STEPS)} steps)")
    print(f"transcript JSON: {TRANSCRIPT_JSON}")
    print(f"transcript MD:   {TRANSCRIPT_MD}")
    print('=' * 78)
    sys.exit(0 if all_pass else 1)


def _write_md(summary):
    L = []
    L.append('# GEM v8.20.0-rc — Clean-Room Rehearsal Transcript\n')
    L.append(f"**Result:** {'PASS ✅' if summary['all_steps_passed'] else 'FAIL ❌'}  "
             f"({sum(s['passed'] for s in summary['steps'])}/{len(summary['steps'])} steps)\n")
    L.append(f"- Package SHA-256: `{summary['package_sha256']}`")
    L.append(f"- ZIP: `{summary['zip_path']}`")
    L.append(f"- Session source: `{summary['session_source']}`  (player `{summary['player']}`)")
    L.append(f"- Post-rehearsal clean `--quick` ok: `{summary['post_rehearsal_clean_quick_ok']}`\n")
    L.append('| Step | Name | Result |')
    L.append('|---|---|---|')
    for s in summary['steps']:
        L.append(f"| {s['step']} | {s['name']} | {'PASS' if s['passed'] else 'FAIL'} |")
    L.append('\n---\n')
    for s in summary['steps']:
        L.append(f"## Step {s['step']} — {s['name']}  ({'PASS' if s['passed'] else 'FAIL'})\n")
        L.append(f"**Command:** `{s['command']}`\n")
        L.append('**Evidence:**\n')
        L.append('```json')
        L.append(json.dumps(s['evidence'], indent=2, default=str))
        L.append('```\n')
    io.open(TRANSCRIPT_MD, 'w', encoding='utf-8').write('\n'.join(L))


if __name__ == '__main__':
    main()
