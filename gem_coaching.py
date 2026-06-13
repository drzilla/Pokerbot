"""gem_coaching.py — coaching-rule registry accessor (v7.67).

Maps a rule/leak code to {source, label}. Reports route codes through
describe() so they render as "Source - plain-language meaning (CODE)"
instead of an opaque code.

Source convention (an INVARIANT enforced here, not just stored):
  J* = Dave, N* = Amit, K* = Jaka.  L* (leak codes) carry an explicit
  tier in the registry. Deriving J/N/K source from the prefix makes the
  historical "J29 = Jaka" mis-attribution impossible by construction.

Unregistered codes fall back to the bare code unchanged, so routing any
code through describe() can never regress output.
"""

import json
import os

_REGISTRY_FILENAME = "coaching_rules.json"

# J/N/K source is DERIVED from the prefix — registry 'source' for these
# is cross-checked against this map (load_rules raises on mismatch).
_PREFIX_SOURCE = {"J": "Dave", "N": "Amit", "K": "Jaka"}

_cache = None


def _registry_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        _REGISTRY_FILENAME)


def load_rules():
    """Return {code: {source, label}} from coaching_rules.json.

    For J*/N*/K* codes the prefix-derived source is authoritative; if the
    registry stores a conflicting 'source' that is a data error and raises.
    """
    global _cache
    if _cache is not None:
        return _cache
    with open(_registry_path()) as f:
        data = json.load(f)
    rules = data.get("rules", {})
    for code, entry in rules.items():
        prefix = code[:1].upper()
        if prefix in _PREFIX_SOURCE:
            derived = _PREFIX_SOURCE[prefix]
            stored = entry.get("source")
            if stored and stored != derived:
                raise ValueError(
                    f"coaching_rules.json: {code} stored source "
                    f"{stored!r} conflicts with prefix-derived {derived!r}")
            entry["source"] = derived
    _cache = rules
    return _cache


def all_codes():
    """All registered codes, in registry insertion order."""
    return list(load_rules().keys())


def rule_source(code):
    """Coaching source for a code.

    J*/N*/K* derive from the prefix (invariant). L* (and any other
    registered code) uses the explicit registry 'source'. Unregistered
    codes return ''.
    """
    if not code:
        return ""
    prefix = code[:1].upper()
    if prefix in _PREFIX_SOURCE:
        return _PREFIX_SOURCE[prefix]
    entry = load_rules().get(code)
    return entry.get("source", "") if entry else ""


def label(code):
    """Plain-language meaning, or '' if unregistered."""
    entry = load_rules().get(code)
    return entry.get("label", "") if entry else ""


def describe(code, with_code=True):
    """'Source - plain-language meaning (CODE)'.

    with_code=False drops the trailing '(CODE)' — used where the code is
    already shown in an adjacent column (e.g. the Section XII glossary).
    Unregistered code -> bare code unchanged (graceful fallback).
    """
    entry = load_rules().get(code)
    if not entry:
        return code
    src = rule_source(code)
    lbl = entry.get("label", "")
    if src and lbl:
        base = f"{src} - {lbl}"
    elif lbl:
        base = lbl
    else:
        return code
    return f"{base} ({code})" if with_code else base


if __name__ == "__main__":
    for c in all_codes():
        print(f"  {c:5s} {describe(c)}")
