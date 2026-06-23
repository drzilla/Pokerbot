"""Immutable, Git-independent release/build identity for the packaged runtime (owner blocker #5).

The dev tree ships a SELF-DERIVING default (SOURCE_COMMIT is empty, so build_identity() falls back to a
live `git rev-parse`). The package builder (_build_v8200rc_release.py) regenerates this file with the
FROZEN commit + release-candidate identity and bundles THAT copy, so the extracted Claude-Chat runtime
knows exactly what it is WITHOUT a .git directory. The sealed packet, run manifest, report footer, cache
manifest and Chat package manifest all read their runtime identity from here.
"""
import os

# ---- frozen at package build time (the builder overwrites these three lines) ----
RELEASE_CANDIDATE = 'v8.20.0-rc'
SOURCE_COMMIT = ''            # full commit frozen at build; empty in the dev tree (git fallback)
BUILD_ID = ''                # e.g. 'GEM-v8.20.0-rc-<commit12>'; derived when empty
# ----------------------------------------------------------------------------------


def _git_commit():
    try:
        import subprocess
        return subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ''


def build_identity():
    """The release/build identity, usable WITHOUT git. Prefers the frozen embedded SOURCE_COMMIT; in the
    dev tree (no frozen commit) falls back to a live git read so the dev runtime still reports a commit."""
    frozen = bool(SOURCE_COMMIT)
    commit = SOURCE_COMMIT or _git_commit()
    try:
        from gem_version import RUNTIME_VERSION as _rv
    except Exception:
        _rv = ''
    try:
        from gem_report_draft.draft import REPORT_SCHEMA_VERSION as _rs
    except Exception:
        _rs = ''
    return {
        'release_candidate': RELEASE_CANDIDATE,
        'runtime_base': _rv,
        'source_commit': commit,
        'source_commit_short': commit[:12] if commit else '',
        'build_id': BUILD_ID or ('GEM-%s-%s' % (RELEASE_CANDIDATE, commit[:12] if commit else 'dev')),
        'report_schema': _rs,
        'git_independent': frozen,
    }


def runtime_identity_string():
    """One-line human banner, e.g. 'GEM v8.20.0-rc (runtime v8.19.0, commit abc123def456)'."""
    bi = build_identity()
    return 'GEM %s (runtime %s, commit %s)' % (
        bi['release_candidate'], bi['runtime_base'] or '?', bi['source_commit_short'] or 'dev')
