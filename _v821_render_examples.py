"""v8.21 closeout: render the final player-facing "Sizing & Line Patterns" section for the three cases
(repeated under-sizing, repeated over-sizing, no-signal/insufficient-evidence) through the CANONICAL
renderer gem_report_draft.draft._emit_sizing_lines fed by the production build_sizing_leak_signals.
Deterministic fixtures only; no real session needed. Writes v821_sync/RENDERED_EXAMPLES.md."""
import os
import re
import gem_sizing_detector as SD
from gem_report_draft import draft as DR


class Doc:
    def __init__(self):
        self.lines = []
    def w(self, s):
        self.lines.append(s)
    def text(self):
        return '\n'.join(self.lines)


def _bucket(label, judged, comp, hands):
    return {'sample_size_label': label, 'sizing_judged_n': judged, 'sizing_compliance_pct': comp,
            'sizing_hands': hands}


# UNDER: middling_disconnected IP, band 100/125/150, Hero bets 33% (too small), 8/9 off-band.
UNDER = {'middling_disconnected': {'ip': _bucket('sufficient', 9, 11.0,
    [{'id': 'U%d' % i, 'sizing_pct': 33, 'within': False, 'depth_band': '60-999BB'} for i in range(8)]
    + [{'id': 'U8', 'sizing_pct': 100, 'within': True, 'depth_band': '60-999BB'}])}}

# OVER: ace_high_dry IP, band 25, Hero bets 75% (too large), 8/9 off-band.
OVER = {'ace_high_dry': {'ip': _bucket('sufficient', 9, 11.0,
    [{'id': 'O%d' % i, 'sizing_pct': 75, 'within': False, 'depth_band': '40-999BB'} for i in range(8)]
    + [{'id': 'O8', 'sizing_pct': 25, 'within': True, 'depth_band': '40-999BB'}])}}

# NONE: thin sample -> no signal -> insufficient-evidence empty state.
NONE = {'low_two_tone': {'ip': _bucket('thin', 2, 0.0,
    [{'id': 'T1', 'sizing_pct': 33, 'within': False, 'depth_band': '40-999BB'}])}}


def render(findings):
    res = SD.build_sizing_leak_signals(findings)
    rd = {'sizing_leak_signals': res['signals'], 'sizing_leak_excluded': res['excluded_counts']}
    doc = Doc()
    DR._emit_sizing_lines(doc, {}, rd, [])
    return res, doc.text()


def strip(html):
    t = html.replace('<<ANCHOR:sec-SL>>', '')
    t = re.sub(r'<[^>]*>', '', t)
    return '\n'.join(ln.strip() for ln in t.splitlines() if ln.strip())


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v821_sync')
cases = [('REPEATED UNDER-SIZING (bets too small)', UNDER),
         ('REPEATED OVER-SIZING (bets too large)', OVER),
         ('NO SIGNAL / INSUFFICIENT EVIDENCE', NONE)]

md = ['# V821 Sizing & Lines — final player-facing rendered examples\n',
      'Rendered through the canonical `gem_report_draft.draft._emit_sizing_lines` fed by the production '
      '`gem_sizing_detector.build_sizing_leak_signals`. Deterministic fixtures; no renderer-side calculation.\n']
for title, findings in cases:
    res, html = render(findings)
    sig = (res['signals'] or [{}])[0]
    md.append('\n## %s\n' % title)
    md.append('**Detector signal:** direction=`%s` · signals=%d · trigger=`%s`\n'
              % (sig.get('direction', '—'), len(res['signals']), sig.get('trigger', '(none)')))
    md.append('**Player-facing section (rendered, tags stripped):**\n')
    md.append('```\n%s\n```\n' % strip(html))
    print('===', title, '=== signals:', len(res['signals']), '| direction:', sig.get('direction', '—'))
    print(strip(html))
    print()

open(os.path.join(OUT, 'RENDERED_EXAMPLES.md'), 'w', encoding='utf-8').write('\n'.join(md))
print('wrote v821_sync/RENDERED_EXAMPLES.md')
