#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic mobile-overflow regression test (additive harness, no production module touched).

Renders the canonical June-16 report and, via headless Chromium at 360 / 390 / 430 px, asserts the
whole-page acceptance gate the reviewer requires:
  * document.scrollWidth == document.clientWidth  (zero page-level horizontal overflow);
  * every non-scroll-container element stays within the document bounds (no hidden offenders);
  * .od-card.rq-card AND .od-card.cooler-summary-card do not overflow;
  * the Results grouped-aggregate rows remain COMPACT (<= 60px, not the ~410px stacked-card blow-up);
  * the Results tables remain horizontally scrollable inside their designated .table-scroll wrappers.

Drives Chrome through CDP via a generated Node script (Node 22+ has a global WebSocket). Reload-per-width
on ONE freshly-launched instance (stale Chrome processes are killed first) so the measurement is stable.

Run: PYTHONUTF8=1 python _qa_mobile_360_overflow.py [report.html]
Writes C:/mnt/user-data/outputs/v820_wave1a2a/MOBILE_360_OVERFLOW_PROOF.json and exits 0 only if all pass.
"""
import os, sys, json, glob, subprocess, tempfile, time

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath('/mnt/user-data/outputs')
PROOF = os.path.join(OUT, 'v820_wave1a2a', 'MOBILE_360_OVERFLOW_PROOF.json')
CHROME = r'C:/program files/google/chrome/application/chrome.exe'
WIDTHS = [360, 390, 430]
PORT = 9333


def _latest_report():
    """The analyst-integrated report if present, else the newest report; else render one."""
    cands = sorted(glob.glob(os.path.join(OUT, 'Pokerbot_*_V[0-9]*.html')), key=os.path.getmtime, reverse=True)
    cands = [c for c in cands if 'AUTO_ONLY' not in c] or sorted(
        glob.glob(os.path.join(OUT, 'Pokerbot_*AUTO_ONLY*.html')), key=os.path.getmtime, reverse=True)
    if cands:
        return cands[0]
    src = os.path.join(OUT, 'iter0', 'june16_src')
    subprocess.run([sys.executable, os.path.join(REPO, 'gem_analyzer.py'), src],
                   cwd=REPO, env={**os.environ, 'PYTHONUTF8': '1'},
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cands = sorted(glob.glob(os.path.join(OUT, 'Pokerbot_*.html')), key=os.path.getmtime, reverse=True)
    return cands[0] if cands else None


def _kill_chrome():
    try:
        subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                        "Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    time.sleep(2)


_NODE = r'''
const PORT=%(port)d, REPORT=%(url)s, WIDTHS=%(widths)s;
async function rpc(ws,id,method,params){return new Promise(r=>{const h=ev=>{const m=JSON.parse(ev.data);if(m.id===id){ws.removeEventListener('message',h);r(m.result);}};ws.addEventListener('message',h);ws.send(JSON.stringify({id,method,params}));});}
const list=await(await fetch(`http://localhost:${PORT}/json`)).json();
const page=list.find(t=>t.type==='page')||list[0];
const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r));
let id=1;await rpc(ws,id++,'Page.enable',{});await rpc(ws,id++,'Runtime.enable',{});
const EXPR=`(function(){var de=document.documentElement;var W=de.clientWidth;
  var loaded=!!document.querySelector('.tt-aggregate')||!!document.querySelector('.od-card');
  if(!loaded)return JSON.stringify({loaded:false});
  var over=[];[].forEach.call(document.querySelectorAll('body *'),function(e){var r=e.getBoundingClientRect();if(r.right>W+0.5){var p=e,sc=false;while(p&&p!==document.body){var ox=getComputedStyle(p).overflowX;if(ox==='auto'||ox==='scroll'){sc=true;break;}p=p.parentElement;}if(getComputedStyle(e).overflowX==='auto'||getComputedStyle(e).overflowX==='scroll')sc=true;if(!sc&&over.length<8)over.push((e.className||e.tagName).toString().slice(0,32)+'@'+Math.round(r.right));}});
  function rt(sel){var el=document.querySelector(sel);return el?Math.round(el.getBoundingClientRect().right):null;}
  var agg=document.querySelector('table.tt-aggregate');
  var aggMax=agg?Math.max.apply(null,[].map.call(agg.querySelectorAll('tbody tr'),e=>Math.round(e.getBoundingClientRect().height))):null;
  var ttres=document.querySelector('#tt-results');var wrap=ttres?ttres.closest('.table-scroll'):null;
  return JSON.stringify({loaded:true,clientWidth:W,scrollWidth:de.scrollWidth,docOverflow:de.scrollWidth-W,
    nonScrollOverflow:over,rqRight:rt('.od-card.rq-card'),coolerRight:rt('.od-card.cooler-summary-card'),
    aggMaxRowH:aggMax,resultsTableScrollable:wrap?getComputedStyle(wrap).overflowX:'none'});})()`;
const results={};
for(const W of WIDTHS){
  let m={loaded:false};
  for(let a=0;a<3&&!m.loaded;a++){
    await rpc(ws,id++,'Emulation.setDeviceMetricsOverride',{width:W,height:1400,deviceScaleFactor:1,mobile:false});
    await rpc(ws,id++,'Page.reload',{});
    await new Promise(r=>setTimeout(r,5500));
    m=JSON.parse((await rpc(ws,id++,'Runtime.evaluate',{expression:EXPR,returnByValue:true})).result.value);
  }
  results['w'+W]=m;
}
console.log(JSON.stringify(results));
ws.close();process.exit(0);
'''


def measure(report):
    _kill_chrome()
    url = 'file:///' + report.replace('\\', '/')
    proc = subprocess.Popen([CHROME, '--headless=new', '--disable-gpu', '--no-sandbox',
                             '--remote-debugging-port=%d' % PORT, url],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(8)
    try:
        node_src = _NODE % {'port': PORT, 'url': json.dumps(url), 'widths': json.dumps(WIDTHS)}
        f = os.path.join(tempfile.gettempdir(), '_mob360_%d.mjs' % PORT)
        open(f, 'w', encoding='utf-8').write(node_src)
        r = subprocess.run(['node', f], capture_output=True, text=True, timeout=120)
        line = [l for l in r.stdout.splitlines() if l.strip().startswith('{')]
        return json.loads(line[-1]) if line else {'error': r.stderr[:400]}
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        _kill_chrome()


def run():
    report = sys.argv[1] if len(sys.argv) > 1 else _latest_report()
    raw = measure(report)
    per, ok_all = {}, True
    for w in WIDTHS:
        m = raw.get('w%d' % w, {})
        checks = {
            'scrollWidth_eq_clientWidth': m.get('docOverflow') == 0,
            'no_nonscroll_overflow_offenders': m.get('nonScrollOverflow') == [],
            'rq_card_within_bounds': (m.get('rqRight') is None) or (m.get('rqRight') <= m.get('clientWidth', 0)),
            'cooler_summary_card_within_bounds': (m.get('coolerRight') is None) or (m.get('coolerRight') <= m.get('clientWidth', 0)),
            'results_aggregate_rows_compact': (m.get('aggMaxRowH') is None) or (m.get('aggMaxRowH') <= 60),
            'results_tables_horizontally_scrollable': m.get('resultsTableScrollable') == 'auto',
        }
        passed = m.get('loaded') and all(checks.values())
        ok_all = ok_all and passed
        per['w%d' % w] = {'pass': bool(passed), 'checks': checks, 'measured': m}
    out = {'report': os.path.basename(report) if report else None, 'widths': WIDTHS,
           'all_pass': bool(ok_all), 'per_width': per}
    os.makedirs(os.path.dirname(PROOF), exist_ok=True)
    open(PROOF, 'w', encoding='utf-8', newline='\n').write(json.dumps(out, indent=2))
    print('MOBILE 360 OVERFLOW PROOF: all_pass=%s -> %s' % (ok_all, PROOF))
    for w in WIDTHS:
        print('  w%d: pass=%s %s' % (w, per['w%d' % w]['pass'], per['w%d' % w]['checks']))
    return out


if __name__ == '__main__':
    sys.exit(0 if run()['all_pass'] else 1)
