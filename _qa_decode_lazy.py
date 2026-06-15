#!/usr/bin/env python3
"""QA helper: decode window.PB_PAYLOADS["lazyHands"] from a generated report.

The hand-detail cards are NOT in the static HTML shell — they are lazily
swapped in from a deflate-raw + base64 payload (PB_PAYLOADS["lazyHands"]).
Any QA of the user-VISIBLE hand-detail content MUST decode this payload;
checking the static shell alone is insufficient (this was the gap that let a
shallow QA pass a report the user then found broken).

Usage:
    python _qa_decode_lazy.py <report.html> [--dump <dir>] [--hand <id>...]
    python _qa_decode_lazy.py <report.html> --grep "inside range"

Programmatic:
    from _qa_decode_lazy import decode_lazy_hands
    cards = decode_lazy_hands(html_text)   # {bare_hand_id: card_html}
"""
import sys, re, json, base64, zlib


def _decode_payload(html, key):
    """Return the decoded object stored in PB_PAYLOADS[key], or None."""
    # The JSON object value has no nested '}' (values are strings/numbers and
    # base64 contains no braces), so a single non-'}' run captures it.
    m = re.search(r'PB_PAYLOADS\[(?:"|\')' + re.escape(key) + r'(?:"|\')\]\s*=\s*(\{[^}]*\})', html)
    if not m:
        return None
    obj = json.loads(m.group(1))
    enc = obj.get('encoding')
    data_b64 = obj.get('data', '')
    raw = base64.b64decode(data_b64)
    if enc == 'deflate-raw+base64':
        raw = zlib.decompress(raw, -15)          # raw deflate (no zlib header)
    elif enc in ('deflate+base64', 'zlib+base64'):
        raw = zlib.decompress(raw)
    txt = raw.decode('utf-8')
    return json.loads(txt)


def decode_lazy_hands(html):
    """Decode the lazyHands map: {bare_hand_id: card_html}.

    Keys are normalised to the bare numeric id (TM60-prefix stripped) so
    callers can look up by the id the user sees.
    """
    m = _decode_payload(html, 'lazyHands')
    if m is None:
        return {}
    out = {}
    for k, v in m.items():
        bare = re.sub(r'^TM\d*?(\d{6,})$', r'\1', str(k))
        # if the regex didn't bite, also try stripping a leading TM60 chunk
        if bare == str(k):
            mm = re.search(r'(\d{6,})$', str(k))
            bare = mm.group(1) if mm else str(k)
        out[bare] = v
        out[str(k)] = v   # keep the raw key too
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    html_path = sys.argv[1]
    html = open(html_path, encoding='utf-8', errors='replace').read()
    cards = decode_lazy_hands(html)
    bare = {k: v for k, v in cards.items() if not str(k).startswith('TM')}
    print(f"decoded lazy hand cards: {len(bare)} (unique bare ids)")
    if '--dump' in sys.argv:
        import os
        d = sys.argv[sys.argv.index('--dump') + 1]
        os.makedirs(d, exist_ok=True)
        for k, v in bare.items():
            with open(os.path.join(d, f"hand_{k}.html"), 'w', encoding='utf-8') as f:
                f.write(v)
        print(f"dumped {len(bare)} cards -> {d}")
    if '--hand' in sys.argv:
        for hid in sys.argv[sys.argv.index('--hand') + 1:]:
            if hid.startswith('--'):
                break
            print(f"\n===== hand {hid} ({len(cards.get(hid, ''))} chars) =====")
            print(cards.get(hid, '(not found)'))
    if '--grep' in sys.argv:
        pat = sys.argv[sys.argv.index('--grep') + 1]
        n = sum(1 for k, v in bare.items() if re.search(pat, v))
        print(f"cards matching /{pat}/: {n}")


if __name__ == '__main__':
    main()
