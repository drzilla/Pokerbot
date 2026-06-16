"""Document builder (class Doc) and HTML/card rendering helpers."""

from gem_report_draft import _state
from gem_report_draft._anchor_map import ANCHOR_MAP, REVERSE_MAP

class Doc:
    """Builds section list with anchors, renders to HTML or MD."""
    STAT_HEADER = "| Metric | Status | Value/Rate | Target | Delta | Sample | Notes |"
    STAT_SEP    = "|---|:---:|---:|---|---|---:|---|"

    def __init__(self):
        self.lines = []
        self.toc = []
        self._open_review = None   # (anchor, title) of subsection awaiting a review row
        # Phase 3 lint: block registry — records every typed block with its
        # line range so the linter can inspect blocks structurally.
        self._block_registry = []
        # Phase 4.6 B3: topbar KPI data (set by draft.py _build)
        self._topbar_kpis = None
        # Phase 4.6 B4: nav section list (set by draft.py _build)
        self._nav_sections = None
        # v8.2.0: extra CSS/JS injection — sections can add custom styles/scripts
        # that get injected into the <head> style block and end-of-body script block,
        # bypassing the markdown converter (which escapes <style>/<script> tags).
        self._extra_css = []
        self._extra_js = []

    def w(self, line=""):
        self.lines.append(line)

    def _emit_review_flush(self):
        """B168: emit the audit review-row sentinel for the subsection that
        just ended (placed at the bottom of its content, before the next
        heading)."""
        if self._open_review:
            anchor, title = self._open_review
            self.w(f"<<REVIEWROW|sub|{anchor}|{title}>>")
            self._open_review = None

    # Phase 4.8: heading override map — aligns section H2 headings with
    # the user's desired tab/nav names. Keyed by anchor (e.g., 'sec-7').
    _HEADING_OVERRIDE = {
        'sec-0': 'Summary',
        'sec-7': 'Coach', 'sec-1': 'Result', 'sec-6': 'KPIs',
        'sec-2': 'Top hands', 'sec-3': 'Leaks', 'sec-4': 'Tourney type',
        'sec-8': 'Preflop', 'sec-9': 'Postflop SRP',
        'sec-10': 'Postflop 3BP/4BP', 'sec-11': 'Mechanics',
        'sec-13': 'Aggression', 'sec-5': 'Action Items',
        'sec-12': 'Progress', 'sec-14': 'QA', 'sec-15': 'Raw Stats',
        'sec-16': 'Glossary', 'sec-17': 'Deviation', 'sec-18': 'Appendix',
    }

    # Sections that should render collapsed (reader expands on demand)
    _COLLAPSED_SECTIONS = {'sec-14', 'sec-15', 'sec-16', 'sec-17', 'sec-18'}

    def section(self, anchor, header, summary):
        self._emit_review_flush()
        # Close any previous collapsed section
        if getattr(self, '_in_collapsed_section', False):
            self.w("</details>")
            self.w("")
            self._in_collapsed_section = False
        self.w(f"<<ANCHOR:{anchor}>>")
        old = REVERSE_MAP.get(anchor)
        if old:
            self.w(f"<<ANCHOR_COMPAT:{old}>>")
        import re as _re_sec
        display_header = self._HEADING_OVERRIDE.get(anchor)
        if not display_header:
            display_header = _re_sec.sub(r'^S\d+\.?\s*', '', header)
        # Collapse QA, Raw Stats, Glossary, Deviation, Appendix
        if anchor in self._COLLAPSED_SECTIONS:
            self.w(f"<details><summary><h2 style='display:inline'>"
                   f"{display_header} — {summary}</h2></summary>")
            self.w("")
            self._in_collapsed_section = True
        else:
            self.w(f"## {display_header} — {summary}")
        self.w("")
        # B-V10: strip S-prefix from ToC entries — user sees "All-Ins" not "S1.4 All-Ins"
        import re as _re_toc
        _toc_header = _re_toc.sub(r'^S\d+[\.\d]*\.?\s*', '', header)
        self.toc.append((anchor, _toc_header, summary, 1))
        self._open_review = None
        _state._set_current_section(anchor, header)

    def subsection(self, anchor, header, summary):
        self._emit_review_flush()
        self.w(f"<<ANCHOR:{anchor}>>")
        # Phase 4 compat: if this anchor was renamed, emit the old anchor
        # as an invisible redirect so existing URLs/citations still resolve.
        old = REVERSE_MAP.get(anchor)
        if old:
            self.w(f"<<ANCHOR_COMPAT:{old}>>")
        # Phase 4.8: strip S-prefix from visible heading
        import re as _re_sub
        display_header = _re_sub.sub(r'^S\d+[\.\d]*\.?\s*', '', header)
        self.w(f"### {display_header} — {summary}")
        self.w("")
        _toc_header_sub = _re_sub.sub(r'^S\d+[\.\d]*\.?\s*', '', header)
        self.toc.append((anchor, _toc_header_sub, summary, 2))
        self._open_review = (anchor, header)  # B168: row goes after its content
        # F2 (v7.49): update module-level current-section for citation tracking
        _state._set_current_section(anchor, header)

    def stat_table_open(self):
        """DEPRECATED — Commit B converted all 6 stat tables to
        write_block(metric_table_block(...)). No production callers remain.
        Kept only for test_blocks.py old-path equivalence tests.
        Remove once those tests are updated to block-only patterns."""
        self.w(self.STAT_HEADER)
        self.w(self.STAT_SEP)

    def write_block(self, blk):
        """Emit a typed block and register it in the block registry.

        Phase 3 lint: the registry records each block dict plus its line
        range so gem_report_lint.py can inspect blocks structurally
        without changing any rendered output.

        heading blocks need Doc state (TOC, review tracking, citation
        section), so they dispatch to section()/subsection() directly.
        All other block types go through _block_to_lines() and append
        via self.w() — producing the EXACT same doc.lines as the
        current emitters.
        """
        if blk.get('type') == 'heading':
            start = len(self.lines)
            if blk.get('level', 1) == 1:
                self.section(blk['anchor'], blk['header'], blk['summary'])
            else:
                self.subsection(blk['anchor'], blk['header'], blk['summary'])
            self._block_registry.append({
                'block': blk,
                'start_line': start,
                'end_line': len(self.lines),
            })
            return
        from gem_report_draft._blocks import _block_to_lines
        start = len(self.lines)
        for line in _block_to_lines(blk):
            self.w(line)
        self._block_registry.append({
            'block': blk,
            'start_line': start,
            'end_line': len(self.lines),
        })

    def block(self, blk):
        """Emit a typed block (Phase 1 render-IR shim).

        Delegates to write_block() which handles both rendering and
        block registry. Kept as an alias for backward compatibility
        with test_blocks.py and any code using doc.block().
        """
        self.write_block(blk)

    def render_md(self):
        self._emit_review_flush()  # B168: flush the final subsection's row marker
        import re
        _CI_TIP_RE = re.compile(r'<span class="ci-tip" title="([^"]+)">ⓘ</span>')
        out = []
        for line in self.lines:
            if line.startswith("<<TOC>>"):
                out.append('<a id="sec-toc"></a>')
                out.append("## 📑 Table of Contents")
                out.append("")
                for anchor, header, summary, level in self.toc:
                    indent = "" if level == 1 else "  "
                    out.append(f"{indent}- [{header}](#{anchor}) — {summary}")
                out.append("")
            elif line.startswith("<<ANCHOR:"):
                continue
            elif line.startswith("<<ANCHOR_COMPAT:"):
                continue  # Phase 4: compat redirects are HTML-only
            elif line.startswith("<<TOCBACK>>"):
                out.append("[↑ Back to ToC](#sec-toc)")
            elif line.startswith("<<REVIEWROW|"):
                continue  # interactive audit layer is HTML-only
            else:
                # metric_status CI tooltip → plaintext for MD render path.
                # HTML gets <span class="ci-tip" title="CI 90%: 15-21%">ⓘ</span>
                # MD gets (CI 90%: 15-21%) — preserves analytical depth.
                out.append(_CI_TIP_RE.sub(r'(\1)', line))
        return "\n".join(out)

    def render_html(self):
        self._emit_review_flush()  # B168: flush the final subsection's row marker
        # Close any trailing collapsed section
        if getattr(self, '_in_collapsed_section', False):
            self.w("</details>")
            self._in_collapsed_section = False
        body_lines = []
        # v7.36 Bug #4 fix: align with D21 spec. Pattern was previously
        # `<a id="X"></a>` followed by `<h2>` (functionally equivalent for
        # anchor nav, but D21 specifies `<h2 id="X">`). Now we attach the
        # pending anchor to the next <<H...>> token so the id sits on the
        # heading itself.
        pending_anchor = None
        for line in self.lines:
            if line.startswith("<<TOC>>"):
                body_lines.append('<nav class="toc" id="sec-toc"><h2>📑 Table of Contents</h2><ul>')
                for anchor, header, summary, level in self.toc:
                    cls = "toc-major" if level == 1 else "toc-sub"
                    body_lines.append(f'<li class="{cls}"><a href="#{anchor}">{_html_escape(header)}</a> <span class="toc-summary">— {_html_escape(summary)}</span></li>')
                body_lines.append('</ul></nav>')
                continue
            if line.startswith("<<ANCHOR:"):
                pending_anchor = line[len("<<ANCHOR:"):-2]
                continue
            if line.startswith("<<ANCHOR_COMPAT:"):
                # Phase 4: invisible redirect for old anchor — zero-height
                # span so existing URLs (#old-anchor) still scroll correctly.
                compat_id = line[len("<<ANCHOR_COMPAT:"):-2]
                body_lines.append(f'<span id="{compat_id}" '
                                  f'class="anchor-compat"></span>')
                continue
            if line.startswith("<<TOCBACK>>"):
                body_lines.append('<a href="#sec-toc" class="toc-back">↑ Back to ToC</a>')
                continue
            if line.startswith("<<REVIEWROW|"):
                # B168: interactive audit review row (HTML-only).
                parts = line[len("<<REVIEWROW|"):-2].split("|", 2)
                if len(parts) == 3:
                    body_lines.append(_audit_row_html(parts[0], parts[1], parts[2]))
                continue
            # If the line is a heading and we have a pending anchor, inject
            # the id into the heading directly (## -> <h2 id="..">).
            # B126 (Ron 2026-05-20): H5 (#####) was missing — XIV.B hand
            # stubs use ##### headings, so their anchors were silently
            # dropped (and leaked onto the next H2/3/4), leaving every
            # XIV.B #sec-app-hand link dead.
            if pending_anchor and (line.startswith("## ") or line.startswith("### ")
                                   or line.startswith("#### ") or line.startswith("##### ")):
                if line.startswith("##### "):
                    rest = line[6:]
                    body_lines.append(f'<<H5 id="{pending_anchor}">>{rest}')
                elif line.startswith("#### "):
                    rest = line[5:]
                    body_lines.append(f'<<H4 id="{pending_anchor}">>{rest}')
                elif line.startswith("### "):
                    rest = line[4:]
                    body_lines.append(f'<<H3 id="{pending_anchor}">>{rest}')
                else:
                    rest = line[3:]
                    body_lines.append(f'<<H2 id="{pending_anchor}">>{rest}')
                pending_anchor = None
                continue
            # B199 (Ron review 2026-05-25): if an <<ANCHOR>> marker is followed
            # by a NON-heading line (e.g. the III.7 inline per-bucket evidence
            # blocks, whose anchor precedes an italic caption, not a heading),
            # the anchor used to sit pending and silently leak onto the next
            # heading — so links like #sec-4-2-ev-missed-bb-defend had no
            # target. Emit a standalone invisible anchor element instead.
            if pending_anchor and line.strip():
                body_lines.append(f'<span id="{pending_anchor}" '
                                  f'class="inline-anchor"></span>')
                pending_anchor = None
                # fall through — the current line is still emitted below
            body_lines.append(line)
        body_md = "\n".join(body_lines)
        body_html = _md_to_html(body_md)
        # v8.14.3 Issue 5 (Ron 2026-06-15): neutralize dangling internal anchors.
        # Some xrefs (e.g. the S12 leak table's '#sec-7-4') point at sections that
        # render only in full mode; in --quick they had no target and the post-
        # render validator reported a broken anchor. Collect every emitted id= and
        # downgrade any internal href="#X" whose target was not emitted to inert
        # text (keeps the visible label, drops the dead link). Lazy hand anchors
        # (sec-app-hand-*) are injected on demand via the payload, so they are
        # NEVER neutralized. The regex matches only internal href="#..." (external
        # links untouched); the JS wrapper is added afterwards so its string
        # templates are out of scope.
        try:
            import re as _re_anchor
            _emitted_ids = set(_re_anchor.findall(r'id="([^"]+)"', body_html))

            def _strip_dead_anchor(_m):
                _tgt = _m.group('tgt')
                if _tgt in _emitted_ids or _tgt.startswith('sec-app-hand-'):
                    return _m.group(0)
                return (f'<span class="dead-xref" '
                        f'data-dead-anchor="#{_tgt}">{_m.group("lbl")}</span>')

            body_html = _re_anchor.sub(
                r'<a\b[^>]*\bhref="#(?P<tgt>[^"]+)"[^>]*>(?P<lbl>.*?)</a>',
                _strip_dead_anchor, body_html)
        except Exception:
            pass
        _final_html = _html_wrap(body_html,
                          topbar_kpis=self._topbar_kpis,
                          nav_sections=self._nav_sections,
                          extra_css=self._extra_css,
                          extra_js=self._extra_js)
        # v8.12.1 R3: flag-gated lazy hand cards (no-op unless
        # GEM_LAZY_HANDS=1; see _maybe_lazyfy_hands).
        return _maybe_lazyfy_hands(_final_html)


def _maybe_lazyfy_hands(html):
    """v8.12.1 R3 (flag-gated, DEFAULT OFF): compressed lazy hand cards.

    When GEM_LAZY_HANDS=1, every <article class='hand-detail-card'> body is
    moved into a deflate-raw+base64 payload (PB codec) and replaced by a
    placeholder that keeps the opening tag (all data-* attrs) and the
    original <h4 id="sec-app-hand-..."> heading — so anchors, TOC jumps and
    Ctrl+F by hand id stay static. PBLazy.ensure(hid) swaps the verbatim
    original back in (no JS re-renderer — pixel-identical by construction).
    Known v1 limits (documented): full-text Ctrl+F and print need Expand all
    (a beforeprint hook also materializes); review-state restore re-runs via
    the existing delegated handlers on materialized content.
    """
    import os
    import re as _re
    import json as _json
    # v8.16.3 Commentary Column v3.4 (router-aware zero-drop migration audit):
    # enumerate every commentary-like source while the per-hand <article> bodies
    # are still INLINE here (compression happens just below) -> source counts are
    # identical with GEM_LAZY_HANDS on or off (lazy parity by construction). The
    # handOpponentContexts payload is decoded and window.coachingCards parsed;
    # NEVER a raw post-lazy HTML grep. Read-only; never blocks the render.
    try:
        from gem_commentary_migration import run_migration_audit as _mig_audit
        _mig_audit(html)
    except Exception as _mig_e:           # pragma: no cover - defensive only
        import sys as _mig_sys
        print('  COMMENTARY-MIGRATION: audit skipped (%s)' % _mig_e,
              file=_mig_sys.stderr)
    # v8.12.2 R4: DEFAULT ON (browser-QA'd: 649/649 materialize, modal
    # + popup + hash-jump + expand-all verified). Opt out with
    # --no-lazy-hand-details / GEM_LAZY_HANDS=0.
    if os.environ.get('GEM_LAZY_HANDS', '1') != '1':
        return html
    try:
        from gem_report_draft._helpers import pb_payload_js
        pat = _re.compile(
            r"<article class='hand-detail-card(?:(?!</article>).)*?</article>",
            _re.S)
        payload = {}
        out = []
        last = 0
        for m in pat.finditer(html):
            seg = m.group(0)
            idm = _re.search(r"data-hand-id='([^']+)'", seg)
            # v8.12.8 QA: XIV.B stubs use ##### -> <h5 id="sec-app-hand-X">
            # headings; the original h4-only pattern swallowed their anchors
            # into the payload, so deep links / middle-click / initial-load
            # hashes were dead for every stub hand (681/741 on the 06-11
            # report) and the placeholder lost the cards/pos/net heading.
            # Match h4 OR h5, any quote style, and keep the heading static.
            h4m = _re.search(
                r"<h([45]) [^>]*id=[\"']sec-app-hand-[^\"']+[\"'][^>]*>"
                r".*?</h\1>", seg, _re.S)
            if not idm:
                continue
            hid = idm.group(1)
            payload[hid] = seg
            open_tag = seg[:seg.find('>') + 1]
            open_tag = open_tag.replace("class='hand-detail-card",
                                        "class='hand-detail-card pb-lazy")
            heading = h4m.group(0) if h4m else f"<h4>Hand <code>{hid}</code></h4>"
            ph = (open_tag
                  + "<div class='mh-top'><div class='mh-title'>" + heading
                  + "</div></div>"
                  + "<button type='button' class='pb-lazy-load' "
                  + f"data-hand-id='{hid}' "
                  + "onclick='if(window.PBLazy)PBLazy.ensure(this.dataset.handId)'>"
                  + "Load hand details</button></article>")
            out.append(html[last:m.start()])
            out.append(ph)
            last = m.end()
        out.append(html[last:])
        html2 = ''.join(out)
        if not payload:
            return html
        pj = pb_payload_js('lazyHands',
                           _json.dumps(payload, ensure_ascii=False),
                           len(payload))
        inject = ('<script>' + pj + '</script>'
                  '<button id="pb-expand-all" type="button" '
                  'onclick="if(window.PBLazy)PBLazy.ensureAll(this)" '
                  'title="Materialize every hand card (needed for full-text '
                  'Ctrl+F and printing)">Expand all hands</button>')
        html2 = html2.replace('</body>', inject + '</body>', 1)
        return html2
    except Exception:
        return html


def _html_escape(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _audit_row_html(rtype, rid, title):
    """B168 (Ron 2026-05-24): single-line HTML for an inline audit review row.
    Renders as a collapsed <details>; rtype is 'sub' (3 verdicts) or 'hand'
    (5 verdicts, adds the two GTOW options)."""
    t = _html_escape(title)
    # v8.14.1 rev-2 (#3): a SECTION review (rtype 'sub', e.g. sec-tldr) must not
    # look like a hand review. Label it "Section review" and add an audit-section
    # class so section-level reviews stay clearly separated from hand reviews
    # (the data-atype="sub" hook already distinguishes them structurally).
    _is_section = (rtype == 'sub')
    _tag = 'Section review' if _is_section else 'Review'
    opts = ('<option value="">— select verdict —</option>'
            '<option>Agree</option><option>Debate</option>'
            '<option>Report bug</option>')
    if rtype == 'hand':
        opts += '<option>GTOW drills</option><option>GTOW hands file</option>'
    return (
        f'<details class="audit-row{" audit-section" if _is_section else ""}" '
        f'data-aid="{_html_escape(rid)}" '
        f'data-atype="{rtype}" data-atitle="{t}">'
        f'<summary class="audit-summary">🔍 <span class="audit-tag">{_tag}</span>'
        f'<span class="audit-context"> · {t}</span>'
        f'<span class="audit-preview"> — not yet reviewed</span></summary>'
        f'<div class="audit-body">'
        f'<label class="audit-l">Verdict</label>'
        f'<select class="audit-status">{opts}</select>'
        f'<label class="audit-l">Notes</label>'
        f'<textarea class="audit-notes" rows="2" '
        f'placeholder="Optional notes — what to debate, the bug, drill focus..."'
        f'></textarea></div></details>'
    )


def _md_to_html(md):
    """Minimal MD → HTML: headers, tables, lists, bold, italic, code, paragraphs."""
    import re
    lines = md.split("\n")
    out = []
    in_table = False
    table_buffer = []

    def flush_table():
        nonlocal in_table, table_buffer
        if not table_buffer:
            return
        rows = [r for r in table_buffer if not _is_table_sep(r)]
        if rows:
            # Phase 4.6 B5: capture header labels for data-label (mobile card-mode)
            headers = [c.strip() for c in rows[0].split("|")[1:-1]]
            # Phase 4.8: detect CI columns → remove column, add tooltip
            # Matches "CI 90%", "90% CI", "95% CI" but NOT "Confidence"
            _ci_col_re = re.compile(r'\bCI\b')
            ci_cols = set()       # indices of CI columns to remove
            ci_target = {}        # ci_col_idx → target_col_idx for tooltip
            for hi, h in enumerate(headers):
                h_plain = re.sub(r'<[^>]+>', '', h).strip()
                if _ci_col_re.search(h_plain):
                    ci_cols.add(hi)
                    # Scan backward: skip delta / expected columns
                    t = hi - 1
                    while t > 0:
                        ht = re.sub(r'<[^>]+>', '', headers[t]).strip().lower()
                        if 'δ' in ht or 'expected' in ht:
                            t -= 1
                        else:
                            break
                    ci_target[hi] = max(t, 0)
            # Phase 4.8 C4: .table-shell wraps .table-scroll (v29 §11)
            # Mobile table readability: classify by header semantics + column count
            _n_vis_cols = len(headers) - len(ci_cols)
            _hdr_plains = [re.sub(r'<[^>]+>', '', h).strip().lower() for h in headers]
            _ev_keywords = {'reason', 'diagnosis', 'what', 'recommendation',
                            'question', 'explanation', 'erratic', 'lesson',
                            'verdict', 'misplay'}
            _has_prose = any(any(kw in hp for kw in _ev_keywords) for hp in _hdr_plains)
            _has_hand = any(hp in ('hand', 'id', '#') or 'hand' in hp for hp in _hdr_plains)
            if _has_prose and _has_hand and _n_vis_cols >= 4:
                _mob_mode = 'evidence-card'
            elif _n_vis_cols >= 5:
                _mob_mode = 'scroll'
            else:
                _mob_mode = 'compact'
            _mob_minw = max(180 * _n_vis_cols, 800) if _mob_mode == 'scroll' else 0
            _mob_style = f' style="--mobile-table-min-width:{_mob_minw}px"' if _mob_minw else ''
            out.append(f'<div class="table-shell" data-mobile-mode="{_mob_mode}"{_mob_style}>'
                       f'<div class="table-scroll"><table class="data-table">')
            for i, r in enumerate(rows):
                cells = [c.strip() for c in r.split("|")[1:-1]]
                if i == 0:
                    out.append('<tr>' + ''.join(
                        f'<th>{_md_inline(c)}</th>'
                        for j, c in enumerate(cells) if j not in ci_cols) + '</tr>')
                else:
                    # Build a map of CI values for this row's target cells
                    ci_tips = {}  # target_col → plain-text CI value
                    for ci_idx, tgt_idx in ci_target.items():
                        if ci_idx < len(cells):
                            ct = re.sub(r'<[^>]+>', '', _md_inline(cells[ci_idx])).strip()
                            if ct and ct != '—' and ct != '-':
                                ci_tips[tgt_idx] = ct
                    parts = []
                    for j, c in enumerate(cells):
                        if j in ci_cols:
                            continue  # drop CI column
                        # B-datatip-label (Phase 4.8): strip HTML tags before
                        # using header text as data-label (plain-text attr).
                        # Can't use simple <[^>]+> because attribute values
                        # may contain '>' (e.g. data-tip="n>=30").  Use a
                        # tag-aware pattern that skips quoted attributes.
                        _raw_lbl = headers[j] if j < len(headers) else ''
                        lbl = _html_escape(re.sub(
                            r'<[a-zA-Z/][^"\']*(?:"[^"]*"|\'[^\']*\')*[^>]*>',
                            '', _raw_lbl).strip())
                        cell_html = _md_inline(c)
                        if j in ci_tips:
                            ci_val = _html_escape(ci_tips[j])
                            cell_html += (f' <span class="ci-tip" '
                                          f'title="CI: {ci_val}">ⓘ</span>')
                        parts.append(
                            f'<td data-label="{lbl}">{cell_html}</td>')
                    out.append('<tr>' + ''.join(parts) + '</tr>')
            out.append('</table></div></div>')
        in_table = False
        table_buffer = []

    _in_chapter = False

    for line in lines:
        s = line.strip()
        if s.startswith('|') and s.endswith('|') and s.count('|') >= 2:
            in_table = True
            table_buffer.append(s)
            continue
        if in_table:
            flush_table()
        # v7.36 Bug #4 fix: <<H2 id="X">>rest and <<H3 id="X">>rest tokens
        # carry the id onto the heading element directly, per D21.
        # v7.36c: extended to <<H4 id="X">> for III.2.N detail subsections.
        if s.startswith('<<H2 id="'):
            close = s.index('">>')
            anchor_id = s[len('<<H2 id="'):close]
            rest = s[close+3:]
            # Phase 4.7 C2: wrap each <<H2>> section in <section class="chapter">
            if _in_chapter:
                out.append('</section>')
            out.append('<section class="chapter">')
            _in_chapter = True
            out.append(f'<h2 id="{anchor_id}">{_md_inline(rest)}</h2>')
        elif s.startswith('<<H3 id="'):
            close = s.index('">>')
            anchor_id = s[len('<<H3 id="'):close]
            rest = s[close+3:]
            out.append(f'<h3 id="{anchor_id}">{_md_inline(rest)}</h3>')
        elif s.startswith('<<H4 id="'):
            close = s.index('">>')
            anchor_id = s[len('<<H4 id="'):close]
            rest = s[close+3:]
            out.append(f'<h4 id="{anchor_id}">{_md_inline(rest)}</h4>')
        elif s.startswith('<<H5 id="'):
            # B126 (Ron 2026-05-20): H5 anchored heading — XIV.B hand stubs.
            close = s.index('">>')
            anchor_id = s[len('<<H5 id="'):close]
            rest = s[close+3:]
            out.append(f'<h5 id="{anchor_id}">{_md_inline(rest)}</h5>')
        elif s.startswith('##### '):
            out.append(f'<h5>{_md_inline(s[6:])}</h5>')
        elif s.startswith('#### '):
            out.append(f'<h4>{_md_inline(s[5:])}</h4>')
        elif s.startswith('### '):
            out.append(f'<h3>{_md_inline(s[4:])}</h3>')
        elif s.startswith('## '):
            out.append(f'<h2>{_md_inline(s[3:])}</h2>')
        elif s.startswith('# '):
            out.append(f'<h1>{_md_inline(s[2:])}</h1>')
        elif s.startswith('> '):
            # B127 (Ron 2026-05-20): single-line blockquote — used by XIV.B
            # hand stubs for the why-flagged note. Without this, "> ..." lines
            # were HTML-escaped to "&gt; ..." literal text.
            out.append(f'<blockquote class="flag-note">{_md_inline(s[2:])}</blockquote>')
        elif s == '---':
            out.append('<hr>')
        elif s.startswith('- '):
            out.append(f'<li>{_md_inline(s[2:])}</li>')
        elif s == '':
            out.append('')
        elif s.startswith('<') and (
                # v7.45 (Ron 2026-05-11): B46 — extended pass-through so raw
                # HTML tags don't render as escaped literal text. Previously
                # only matched specific id/nav/ul/li/h2 patterns; <details>,
                # <summary>, <span class=...> all leaked through as escaped
                # text (visible <p>&lt;details&gt;...</p> in the prior session
                # HTML). Now passes through any non-Markdown HTML element.
                # B51 (v7.54, Ron 2026-05-18): extended to table-internal tags
                # (thead, tbody, tr, th, td) so the visual hand-grid renders
                # as HTML instead of escaped text. Surfaced on the new B48
                # hand-grid layout — without these, every <thead>/<tr>/<td>
                # line fell through to the <p> branch and showed raw markup.
                'id=' in s or 'nav' in s or '/nav' in s
                or '<ul' in s or '</ul' in s or '<li ' in s
                or '<h2>📑' in s
                or s.startswith('<span')
                or s.startswith('<details')
                or s.startswith('</details')
                or s.startswith('<summary')
                or s.startswith('</summary')
                or s.startswith('<div')
                or s.startswith('</div')
                or s.startswith('<table')
                or s.startswith('</table')
                or s.startswith('<thead')
                or s.startswith('</thead')
                or s.startswith('<tbody')
                or s.startswith('</tbody')
                or s.startswith('<tfoot')
                or s.startswith('</tfoot')
                or s.startswith('<tr')
                or s.startswith('</tr')
                or s.startswith('<th')
                or s.startswith('</th')
                or s.startswith('<td')
                or s.startswith('</td')
                or s.startswith('<p>')
                or s.startswith('<p ')
                or s.startswith('<a ')
                or s.startswith('</p>')
                or s.startswith('<article')
                or s.startswith('</article')
                or s.startswith('<section')
                or s.startswith('</section')
                # Phase 4.8: opening dashboard raw HTML tags
                or s.startswith('<aside')
                or s.startswith('</aside')
                or s.startswith('<label')
                or s.startswith('</label')
                or s.startswith('<strong>')
                or s.startswith('<strong ')
                or s.startswith('</strong')
                or s.startswith('<small')
                or s.startswith('</small')
                or s.startswith('<b>')
                or s.startswith('<b ')
                or s.startswith('</b>')
                or s.startswith('<h3>')
                or s.startswith('<h3 ')
                or s.startswith('</h3>')
                or s.startswith('<h4>')
                or s.startswith('<h4 ')
                or s.startswith('</h4>')
                or s.startswith('<header')
                or s.startswith('</header')
                or s.startswith('<footer')
                or s.startswith('</footer')
                or s.startswith('<button')
                or s.startswith('</button')
                or s.startswith('<input')
                or s.startswith('<code')
                or s.startswith('</code')):
            out.append(line)
        else:
            out.append(f'<p>{_md_inline(line)}</p>')
    if in_table:
        flush_table()
    # Phase 4.7 C2: close final chapter section
    if _in_chapter:
        out.append('</section>')
    final = []
    in_list = False
    for ln in out:
        if ln.startswith('<li>') and not in_list:
            final.append('<ul>')
            in_list = True
        elif not ln.startswith('<li>') and in_list and not ln.startswith('<li '):
            final.append('</ul>')
            in_list = False
        final.append(ln)
    if in_list:
        final.append('</ul>')
    return "\n".join(final)


def _is_table_sep(line):
    s = line.strip().strip('|')
    if not s:
        return False
    cells = s.split('|')
    for c in cells:
        c = c.strip()
        if not all(ch in '-: ' for ch in c) or len(c) == 0:
            return False
    return True


def _md_inline(text):
    """Inline markdown → HTML.

    B79 (v7.57, Ron 2026-05-18): preserve pre-rendered HTML spans before
    _html_escape clobbers them. Affected: card-pill spans, hand-net pills,
    villain-card spans, made-hand spans — all emitted by the visual layer
    upstream. Previously these arrived in table cells and headings as
    plain text after escape, leaking literal markup to the page.
    """
    import re
    if text is None:
        return ''
    # B79: protect known pre-rendered HTML spans by stashing them BEFORE escape
    placeholders = []
    def _stash(m):
        placeholders.append(m.group(0))
        return f'\x00HTMLSPAN{len(placeholders)-1}\x00'
    # Match span openings + closing as balanced units. Conservative: must be
    # one of the known span classes the visual layer emits, OR a style="..."
    # nowrap wrapper (B91).
    # B96 (v7.59, Ron 2026-05-19): two-pass stash for nested spans. Previous
    # single-pass with non-greedy `.*?</span>` failed on nowrap-wrapper around
    # card spans — first inner </span> closed the regex match, leaving the
    # outer </span> for escape → leaking `</span>` text in III.1, I.3, etc.
    # Fix: stash innermost (leaf) spans first, then outer wrappers that now
    # contain only placeholders (no real <span> tags).
    # v8.12.5 (browser QA): + verdict-pill — the v8.12.3 hand-bar pill was
    # emitted into XIV headings but was NOT in this whitelist, so every pill
    # arrived on the page as escaped literal text and none ever rendered.
    inner_span_pat = re.compile(
        r'<span\s+class=[\'"](?:card\s+card-[shdc]|hand-net-(?:pos|neg|neu)|'
        r'villain-card|made-hand|board-match|pot-pct|note-num|note-tag|'
        r'ann(?:\s+ann-(?:positive|emoji))?(?:\s+ann-emoji)?|'
        r'cards|label|hero-pos|hero-nick|pot|sd-block|net-pos|net-neg|grid-action[^\'"]*|'
        r'cond-pass|cond-fail|ci-tip|new-badge|verdict-pill|context-pill[^\'"]*)[\'"]'
        r'[^>]*>[^<]*</span>',
        re.IGNORECASE)
    text = inner_span_pat.sub(_stash, text)
    # B-datatip (Phase 4.8): stash <span data-tip="...">text</span> tooltips.
    # These appear in pipe-table header cells (S1.6) and body cells (S1.5,
    # S9.2 K4 matrix) and were being HTML-escaped → literal tag text in
    # the report.  Run AFTER inner spans so any placeholder inside content
    # (if a card span were nested) is already a \x00 token.
    datatip_span_pat = re.compile(
        r'<span\s+data-tip="[^"]*"[^>]*>[^<]*</span>',
        re.IGNORECASE)
    text = datatip_span_pat.sub(_stash, text)
    # Now stash outer nowrap wrappers (no nested <span> remaining inside).
    # B-nowrap-lt (Phase 4.8): the old [^<]* broke on verdict text like
    # "⚪ (n=0<30)" — the literal '<30' matched [^<] prematurely.
    # After inner spans are stashed the only real '<' inside should be the
    # closing </span>.  Use a lazy .*? with DOTALL off (single line) to
    # capture everything up to the FIRST </span>.
    outer_span_pat = re.compile(
        r'<span\s+style=[\'"]white-space:nowrap[\'"][^>]*>.*?</span>',
        re.IGNORECASE)
    text = outer_span_pat.sub(_stash, text)
    # Also stash sup tags (used by 👎ᴺ markers)
    sup_pat = re.compile(r'<sup>.*?</sup>')
    text = sup_pat.sub(_stash, text)
    # B115 (Ron 2026-05-19): also stash <br> / <br/> tags. Without this,
    # _html_escape converted them to &lt;br&gt; → visible as literal text
    # inside table cells (Top Leaks bullets all showed "<br>•" instead of
    # actual line breaks).
    br_pat = re.compile(r'<br\s*/?>', re.IGNORECASE)
    text = br_pat.sub(_stash, text)
    # Renderer link BUG-1: stash hand-list-trigger anchors (FEAT-2/3/4 clickable
    # hand-count links). Pre-rendered <a> tags in markdown table cells; without
    # stashing, _html_escape clobbers them into &lt;a&gt; visible text.
    handlist_pat = re.compile(
        r'<a\s+class=[\'"]hand-list-trigger[\'"][^>]*>[^<]*</a>', re.IGNORECASE)
    text = handlist_pat.sub(_stash, text)
    # CP23: stash <a class="xref"> links (watchlist metric links to sections)
    xref_pat = re.compile(
        r'<a\s+href=[\'"]#[^"\']+[\'"]\s+class=[\'"]xref[\'"][^>]*>[^<]*</a>', re.IGNORECASE)
    text = xref_pat.sub(_stash, text)
    # B-V11 (2026-06-01): stash <strong>…</strong> tags. _bold_hand_in_range()
    # emits raw <strong> for the analyst-notes div (no markdown), but the same
    # string routes through _md_inline in XIV.B grid notes where _html_escape
    # turns it into visible &lt;strong&gt; text.
    strong_pat = re.compile(r'<strong>[^<]*</strong>', re.IGNORECASE)
    text = strong_pat.sub(_stash, text)
    # Now escape what's left
    text = _html_escape(text)
    # B101 (Ron 2026-05-19): restore in REVERSE order. B96 two-pass stash creates
    # nested placeholders (outer wrapper contains inner placeholders textually).
    # Forward iteration replaces inner placeholders BEFORE outer wrapper exposes
    # them — leaking literal "HTMLSPAN0" text. Reverse-order restores outer
    # first, then inner placeholders are visible for the i=0,1,... passes.
    for i in range(len(placeholders) - 1, -1, -1):
        text = text.replace(f'\x00HTMLSPAN{i}\x00', placeholders[i])
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # MD-style link [label](url) — used by _xref() for cross-section navigation.
    # Escapes already applied above, so &amp;quot; etc. are safe inside attrs.
    # B-V15: negative lookbehind for \ — escaped \[ must NOT open a link.
    # After link conversion, strip backslash-escapes so \[ renders as literal [.
    text = re.sub(r'(?<!\\)\[([^\]]+)\]\(([^)]+)\)',
                  lambda m: f'<a href="{m.group(2)}" class="xref">{m.group(1)}</a>',
                  text)
    # Strip backslash-escapes from remaining \[ and \] → literal brackets
    text = text.replace('\\[', '[').replace('\\]', ']')
    # Phase 4.5: upgrade appendix-hand pills with data-hand-id so the modal
    # JS can find them.  Surgical post-process: only xref links pointing to
    # #sec-app-hand-* get the attribute.  Does NOT touch _hand_ref() or the
    # citation side-effect timing (sacred).
    text = re.sub(
        r'<a href="#sec-app-hand-([^"]+)" class="xref">',
        r'<a href="#sec-app-hand-\1" class="hand-ref xref" data-hand-id="\1">',
        text)
    return text


# Phase 4.8 C5: Modal scaffold + JS — v29 .modal architecture
# Single-hand popup: pill → buildModalHand(hid) → curated .modal-hand.
# handSiblingNodes is DELETED — the v29 multi-hand bug is never ported.
# NO h4+sibling fallback.  NO fallback of any kind.
# _loading guard PRESERVED verbatim for review-notes race condition.
# Storage key migration: gem-review-* → pokerbot:handreview:* (non-destructive COPY).
_MODAL_HTML = r"""
<div class="modal" id="hand-modal" aria-hidden="true">
  <div class="modal-backdrop"></div>
  <div class="modal-panel v25-panel" role="dialog" aria-modal="true">
    <!-- V25 STICKY TOP BAR -->
    <div class="v25-topbar" id="v25-topbar">
      <div class="v25-top-identity">
        <span class="v25-top-hand-label">Hand</span>
        <h3 class="v25-top-hid" id="hand-modal-title">review</h3>
        <span class="v25-top-cards" id="v25-top-cards"></span>
        <span class="v25-top-result" id="v25-top-result"></span>
        <span class="v25-top-reviewed" id="v25-top-reviewed" style="display:none"></span>
      </div>
      <button id="hand-modal-close" type="button" class="v25-close">Close</button>
    </div>
    <!-- V25 STICKY QUEUE BAR -->
    <div class="v25-queue-bar" id="hand-queue-context" style="display:none"></div>
    <!-- SCROLLABLE BODY -->
    <div class="modal-body" id="hand-modal-body"></div>
    <!-- STICKY REVIEW BAR -->
    <div class="modal-review">
      <div class="verdict-chip-row">
        <span class="verdict-label">Verdict</span>
        <button type="button" class="verdict-chip verdict-agree" data-verdict="Agree">✅ Agree</button>
        <button type="button" class="verdict-chip verdict-debate" data-verdict="Debate">🤔 Debate</button>
        <button type="button" class="verdict-chip verdict-bug" data-verdict="Report bug">🐞 Report bug</button>
        <button type="button" class="verdict-chip verdict-drill" data-verdict="Drill">🎯 Drill</button>
        <button type="button" class="verdict-chip verdict-rulebook" data-verdict="Rulebook">📘 Rulebook</button>
        <button type="button" class="verdict-clear" data-verdict="">Clear</button>
      </div>
      <select id="modal-review-status" style="display:none">
        <option value="">-- verdict --</option>
        <option>Agree</option><option>Debate</option><option>Report bug</option>
        <option>Drill</option><option>Rulebook</option>
      </select>
      <textarea id="modal-review-notes" placeholder="Hand review notes — auto-saved while typing"></textarea>
      <div class="save-state" id="modal-save-state">Auto-saved</div>
    </div>
  </div>
</div>
<div class="modal" id="list-modal" aria-hidden="true">
  <div class="modal-backdrop list-backdrop"></div>
  <div class="modal-panel list-panel" role="dialog" aria-modal="true">
    <div class="modal-head">
      <h3 id="list-modal-title">Example Hands</h3>
      <button id="list-modal-close" type="button">Close</button>
    </div>
    <div class="modal-body" id="list-modal-body"></div>
  </div>
</div>
<div class="modal" id="villain-evidence-modal" aria-hidden="true">
  <div class="modal-backdrop ve-backdrop"></div>
  <div class="modal-panel" role="dialog" aria-modal="true" style="max-width:960px">
    <div class="modal-head">
      <h3 id="ve-modal-title">Villain Evidence</h3>
      <button id="ve-modal-close" type="button">Close</button>
    </div>
    <div class="modal-body" id="ve-modal-body"></div>
  </div>
</div>
<div class="modal" id="tournament-detail-modal" aria-hidden="true">
  <div class="modal-backdrop ttd-backdrop"></div>
  <div class="modal-panel" role="dialog" aria-modal="true" style="max-width:820px">
    <div class="modal-head">
      <h3 id="ttd-modal-title">Tournament detail</h3>
      <button id="ttd-modal-close" type="button">Close</button>
    </div>
    <div class="modal-body" id="ttd-modal-body"></div>
  </div>
</div>
<div class="tooltip-pop" id="tip-pop"></div>
<script>
(function(){
  /* ---- DOM helpers ---- */
  function clean(s){return (s||'').replace(/\s+/g,' ').trim();}
  function _dedupTextKey(el){
    var t=clean(el.textContent||'').toLowerCase();
    t=t.replace(/^(pre[-\s]?flop|preflop|flop|turn|river)[:\s-]*/,'');
    t=t.replace(/^(opponent context|coach context|coaching context)[:\s-]*/,'');
    return t.substring(0,120);
  }
  /* P0: canonical hand-ID normalizer — strips TM prefix, keeps last 8 digits */
  function normalizeHandId(hid){var m=String(hid||'').match(/(\d{8})$/);return m?m[1]:String(hid||'').replace(/^TM/,'');}
  window.normalizeHandId=normalizeHandId;
  /* v8.12.8: compact 'AhKd' → card spans (same markup as _card_html).
     Hand-list popups read window.handIndex first — lazy articles are empty
     shells until inflated, so DOM scraping alone left columns blank. */
  function fmtCardSpans(cc){
    var sym={s:'♠',h:'♥',d:'♦',c:'♣'},out=[];
    cc=String(cc||'');
    for(var i=0;i+1<cc.length;i+=2){
      var r=cc[i].toUpperCase(),su=cc[i+1].toLowerCase();
      out.push('<span class="card card-'+su+'">'+r+(sym[su]||su)+'</span>');
    }
    return out.join(' ');
  }
  /* ---- v29 heading-sibling walker ---- */
  function handSiblingNodes(target){
    var nodes=[],n=target.nextElementSibling,guard=0;
    while(n&&guard++<80){
      if(/^H[2345]$/.test(n.tagName)&&n.id&&n.id.startsWith('sec-app-hand-'))break;
      if(/^H2$/.test(n.tagName))break;
      if(n.tagName==='HR')break;
      nodes.push(n);
      n=n.nextElementSibling;
    }
    return nodes;
  }
  function firstMatch(nodes,sel){
    for(var i=0;i<nodes.length;i++){
      if(nodes[i].matches&&nodes[i].matches(sel))return nodes[i];
    }
    return null;
  }
  function allMatch(nodes,sel){return nodes.filter(function(n){return n.matches&&n.matches(sel);});}
  function makeChip(text,extra){var s=document.createElement('span');s.className='mh-chip '+(extra||'');s.textContent=text;return s;}
  function splitMeta(text){return clean(text).split(/\s*·\s*/).filter(Boolean).slice(0,8);}
  function classifyNet(text){if(/-[0-9.]+\s*BB/.test(text))return 'bad';if(/\+[0-9.]+\s*BB/.test(text))return 'good';return '';}
  /* ---- buildModalHand(hid): article-first, sibling-fallback ---- */
  /* Finds #sec-app-hand-{hid}. If it lives inside an article.hand-detail-card
     (our generator), uses article children as nodes. Otherwise falls back to
     v29 sibling-walking for bare headings. */
  /* v8.8.6: HTML-escape helper for coaching text injection */
  function _esc(s){var d=document.createElement('div');d.appendChild(document.createTextNode(s));return d.innerHTML;}
  /* V25: extracted opponent coaching — single block renderer (shared by legacy + V25) */
  function _renderOpponentContextBlock(ctx){
    if(ctx.bucket==='passive_read'){
      var _det=document.createElement('details');_det.className='coaching-block coaching-passive';
      _det.innerHTML='<summary>Opponent note: '+_esc(ctx.villain_alias||'')+
        (ctx.read_label?' — '+_esc(ctx.read_label):'')+
        (ctx.n_evidence?' — '+ctx.n_evidence+' evidence':'')+
        '</summary>'+
        '<div class="cb-body cb-compact">'+
        '<div class="cb-note">No direct Hero adjustment flagged in this hand.</div>'+
        '</div>';
      return _det;
    }
    var _bl=document.createElement('div');_bl.className='coaching-block coaching-'+ctx.bucket;
    if(ctx.bucket==='exploit_miss'){
      var _sev=ctx.severity||'C';
      if(_sev==='A'||_sev==='B'){
        _bl.innerHTML='<div class="cb-header cb-miss"><strong>🎯 Opponent Adjustment — ❌ Miss</strong></div>'+
          '<div class="cb-body">'+
          '<div class="cb-villain">Villain: '+_esc(ctx.villain_alias||'')+
            (ctx.v_number?' · '+_esc(ctx.v_number):'')+
            (ctx.read_label?' · '+_esc(ctx.read_label):'')+
          '</div>'+
          '<div class="cb-timing">Read timing: '+_esc(ctx.timing_label||'')+'</div>'+
          (ctx.suggests?'<div class="cb-suggests">Read signal: '+_esc(ctx.suggests)+'</div>':'')+
          (ctx.hero_action?'<div class="cb-hero">Hero action: '+_esc(ctx.hero_action)+'</div>':'')+
          (ctx.so_what?'<div class="cb-sowhat"><strong>So what?</strong> '+_esc(ctx.so_what)+'</div>':'')+
          (ctx.recommended?'<div class="cb-rec"><strong>Next time:</strong> '+_esc(ctx.recommended)+'</div>':'')+
          '</div>';
      } else {
        /* Severity C: enriched compact — spec requires timing + hero action */
        _bl.innerHTML='<div class="cb-header cb-miss-c"><strong>🎯 Opponent Adjustment — Small Miss</strong></div>'+
          '<div class="cb-body cb-compact">'+
          '<div class="cb-villain">Villain: '+_esc(ctx.villain_alias||'')+
            (ctx.v_number?' · '+_esc(ctx.v_number):'')+
            (ctx.read_label?' · '+_esc(ctx.read_label):'')+
          '</div>'+
          (ctx.timing_label?'<div class="cb-timing">Read timing: '+_esc(ctx.timing_label)+'</div>':'')+
          (ctx.suggests?'<div class="cb-suggests">Read signal: '+_esc(ctx.suggests)+'</div>':'')+
          (ctx.hero_action?'<div class="cb-hero">Hero action: '+_esc(ctx.hero_action)+'</div>':'')+
          (ctx.so_what?'<div class="cb-sowhat"><strong>So what?</strong> '+_esc(ctx.so_what)+'</div>':'')+
          (ctx.recommended?'<div class="cb-rec"><strong>Next time:</strong> '+_esc(ctx.recommended)+'</div>':'')+
          '</div>';
      }
    } else if(ctx.bucket==='good_exploit'){
      _bl.innerHTML='<div class="cb-header cb-good"><strong>🎯 Opponent Adjustment — ✅ Good</strong></div>'+
        '<div class="cb-body">'+
        '<div class="cb-villain">Villain: '+_esc(ctx.villain_alias||'')+
          (ctx.v_number?' · '+_esc(ctx.v_number):'')+
          (ctx.read_label?' · '+_esc(ctx.read_label):'')+
        '</div>'+
        '<div class="cb-timing">Read timing: '+_esc(ctx.timing_label||'')+'</div>'+
        (ctx.suggests?'<div class="cb-suggests">Read signal: '+_esc(ctx.suggests)+'</div>':'')+
        (ctx.hero_action?'<div class="cb-hero">Hero action: '+_esc(ctx.hero_action)+'</div>':'')+
        (ctx.so_what?'<div class="cb-sowhat"><strong>Why good:</strong> '+_esc(ctx.so_what)+'</div>':'')+
        (ctx.recommended?'<div class="cb-rec"><strong>Next time:</strong> '+_esc(ctx.recommended)+'</div>':'')+
        '</div>';
    } else if(ctx.bucket==='villain_evidence'){
      _bl.className='coaching-block coaching-villain_evidence v25-ve-inline';
      var _veParts=[];
      _pushUnique(_veParts,ctx.villain_alias);
      _pushUnique(_veParts,ctx.v_number);
      _pushUnique(_veParts,ctx.street);
      if(ctx._clusterCount>1)_veParts.push(ctx._clusterCount+'x');
      var _veLabel=_veParts.length?_veParts.join(' · '):'Unknown villain';
      _bl.innerHTML='<div class="v25-ve-header">'
        +'<span class="v25-ve-badge">! Note</span> '
        +'<span class="v25-ve-type">Villain tell</span> '
        +'<span class="v25-ve-label">'+_esc(_veLabel)+'</span>'
        +'</div>'
        +(ctx.suggests?'<div class="v25-ve-line"><b>Suggests:</b> '+_esc(ctx.suggests)+'</div>':'')
        +(ctx.so_what?'<div class="v25-ve-line"><b>So what?</b> '+_esc(ctx.so_what)+'</div>':'');
    } else if(ctx.bucket==='analyst_learning'){
      _bl.innerHTML='<div class="cb-header cb-learning"><strong>📚 Learning Opportunity</strong></div>'+
        '<div class="cb-body">'+
        '<div class="cb-villain">Villain: '+_esc(ctx.villain_alias||'')+
          (ctx.v_number?' · '+_esc(ctx.v_number):'')+
        '</div>'+
        (ctx.signal_label?'<div class="cb-signal">Signal: '+_esc(ctx.signal_label)+'</div>':'')+
        (ctx.suggests?'<div class="cb-suggests">What it suggests: '+_esc(ctx.suggests)+'</div>':'')+
        (ctx.analyst_coaching?'<div class="cb-analyst-text">'+_esc(ctx.analyst_coaching)+'</div>':'')+
        '</div>';
    }
    if(ctx.analyst_reviewed){
      var _abadge=ctx.analyst_verdict==='confirmed'?'🔍 Analyst confirmed':
                  ctx.analyst_verdict==='borderline'?'🔍 Debatable':
                  ctx.analyst_verdict==='upgraded'?'🔍 Learning opportunity':'';
      if(_abadge){
        var _adiv=document.createElement('div');_adiv.className='cb-analyst';
        _adiv.innerHTML='<strong>'+_abadge+'</strong>'+
          (ctx.analyst_coaching?'<br>'+_esc(ctx.analyst_coaching):'')+
          (ctx.analyst_note?' <em>('+_esc(ctx.analyst_note)+')</em>':'');
        _bl.appendChild(_adiv);
      }
    }
    /* v8.13.0 Villain Teaching Layer: compact, additive coaching block.
       Renders the pre-built teaching projection (archetype + confidence +
       evidence count, the do-not-over-adjust guardrail, PKO cover, and the
       thin-read fallback). All copy is built in Python (gem_villain_teaching)
       so the renderer only displays strings and invents nothing. */
    /* v8.17.0-rc3 (Villain Step-3 visible delivery): the compact villain
       teaching is now rendered from the explicit 7-part lesson object
       (ctx.teaching.lesson_7part: q1..q7 + gradable + non_gradable_reason) as a
       labelled Exploit/read support structure integrated into the Commentary
       hierarchy — Read+Confidence / Cue / Exploit now / Future / Do-not-over-
       adjust guardrail. Strings are built in Python (gem_villain_teaching.
       lesson_7part); the renderer only labels + displays them. ICM caution,
       PKO cover, and the Natural8 tag are preserved from the teaching object.
       data-from="lesson_7part" makes the render source provable. Falls back to
       the legacy teach_lines list only if lesson_7part is absent. */
    if(ctx.teaching&&ctx.teaching.lesson_7part){
      var _t=ctx.teaching;var _L=_t.lesson_7part;var _tp=[];var _thin=!!(_t.fallback)||(!_L.q3_read&&!_L.q2_cue);
      if(_thin){
        _tp.push('<div class="v25-teach-weak">'+_esc(_L.q1_villain_did||'')+'</div>');
      } else {
        if(_L.q1_villain_did){_tp.push('<div class="v25-teach-evid">'+_esc(_L.q1_villain_did)+'</div>');}
        var _head='Read: '+_esc(_L.q3_read||'');
        if(_L.q4_confidence){_head+=' <span class="v25-teach-confchip">'+_esc(_L.q4_confidence)+'</span>';}
        _tp.push('<div class="v25-teach-head">'+_head+'</div>');
        if(_L.q2_cue){_tp.push('<div class="v25-teach-cue">Cue: '+_esc(_L.q2_cue)+'</div>');}
        if(_L.q5_exploit_now){_tp.push('<div class="v25-teach-now">Exploit now: '+_esc(_L.q5_exploit_now)+'</div>');}
        if(_L.q6_exploit_future){_tp.push('<div class="v25-teach-future">Next time: '+_esc(_L.q6_exploit_future)+'</div>');}
        if(_L.q7_do_not_overadjust){_tp.push('<div class="v25-teach-guard">Don’t over-adjust: '+_esc(_L.q7_do_not_overadjust)+'</div>');}
        if(_t.icm_guardrail){_tp.push('<div class="v25-teach-icm">ICM caution: '+_esc(_t.icm_guardrail)+'</div>');}
        if(_t.pko&&_t.pko.cover_label){_tp.push('<div class="v25-teach-pko">Bounty: '+_esc(_t.pko.cover_label)+'</div>');}
      }
      var _tag=_t.tag_suggestion;
      if(_tag&&_tag.label){
        var _tc=_tag.color||'yellow';
        _tp.push('<div class="v25-teach-tag" data-tag-color="'+_esc(_tc)+'">Tag suggestion: '+_esc(_tag.label)+' ('+_esc(_tc)+')</div>');
      }
      var _td=document.createElement('div');_td.className='v25-teach v25-lesson7';
      _td.setAttribute('data-from','lesson_7part');_td.innerHTML=_tp.join('');_bl.appendChild(_td);
    }
    else if(ctx.teaching&&ctx.teaching.teach_lines&&ctx.teaching.teach_lines.length){
      /* Legacy fallback (teaching object without lesson_7part). */
      var _t=ctx.teaching;var _tp=[];
      _t.teach_lines.forEach(function(ln){
        var cls='v25-teach-line';var attr='';
        if(ln.indexOf('Tag suggestion:')===0){
          cls='v25-teach-tag';
          var _m=ln.match(/\(([a-z]+)\)\s*$/);
          if(_m){attr=' data-tag-color="'+_m[1]+'"';}
        }
        else if(_t.fallback){cls='v25-teach-weak';}
        else if(ln.indexOf('Read:')===0){cls='v25-teach-head';}
        else if(ln.indexOf('Confidence:')===0){cls='v25-teach-conf';}
        else if(ln.indexOf('Do not over-adjust:')===0){cls='v25-teach-guard';}
        else if(ln.indexOf('Bounty:')===0){cls='v25-teach-pko';}
        _tp.push('<div class="'+cls+'"'+attr+'>'+_esc(ln)+'</div>');
      });
      var _td=document.createElement('div');_td.className='v25-teach';_td.innerHTML=_tp.join('');_bl.appendChild(_td);
    }
    return _bl;
  }
  /* V25: Why this hand — slim reason line below summary */
  function _appendV25WhyLine(wrap, hid, tail, hocs) {
    var q = window.activeHandQueue;
    var reason = q && q.reasonByHand ? (q.reasonByHand[hid] || '') : '';
    if (!reason) return;
    var line = document.createElement('div');
    line.className = 'v25-why-line';
    var label = document.createElement('span');
    label.className = 'v25-why-label';
    label.textContent = 'Why this hand';
    line.appendChild(label);
    var main = document.createElement('span');
    main.className = 'v25-why-main';
    main.textContent = reason;
    line.appendChild(main);
    var verdict = '';
    (tail || []).some(function(t) {
      if (/justified|correct|cleared|mistake|punt|borderline/i.test(t)) { verdict = t; return true; }
      return false;
    });
    if (verdict) {
      var vp = document.createElement('span');
      vp.className = 'v25-why-pill ' +
        (/mistake|punt|bad/i.test(verdict) ? 'bad' :
         /justified|correct|cleared/i.test(verdict) ? 'good' : 'warn');
      vp.textContent = 'Verdict: ' + verdict;
      line.appendChild(vp);
    }
    var focus = '';
    (hocs || []).some(function(ctx) {
      focus = ctx.hero_decision_street || ctx.street || '';
      return !!focus;
    });
    if (focus) {
      var fp = document.createElement('span');
      fp.className = 'v25-why-pill warn';
      fp.textContent = 'Focus: ' + focus;
      line.appendChild(fp);
    }
    wrap.appendChild(line);
  }
  /* V25: collapsible long commentary sections */
  function hydrateV25CommentaryCollapse(root) {
    (root || document).querySelectorAll('.v25-commentary-section').forEach(function(sec) {
      if (sec.dataset.collapseReady === '1') return;
      sec.dataset.collapseReady = '1';
      var skipRe = /villain.evidence|confirmed.mistake|punt|bug.report/i;
      if (skipRe.test(sec.textContent)) return;
      var children = Array.prototype.slice.call(sec.children)
        .filter(function(n) { return n.tagName !== 'H4'; });
      if (!children.length) return;
      var wrap = document.createElement('div');
      wrap.className = 'v25-commentary-more';
      children.forEach(function(n) { wrap.appendChild(n); });
      sec.appendChild(wrap);
      requestAnimationFrame(function() {
        if (wrap.scrollHeight <= 160) return;
        sec.classList.add('is-collapsible');
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'v25-commentary-toggle';
        btn.textContent = 'Show full analysis';
        btn.addEventListener('click', function() {
          var open = sec.classList.toggle('is-open');
          btn.textContent = open ? 'Collapse analysis' : 'Show full analysis';
        });
        sec.appendChild(btn);
      });
    });
  }
  /* V25: push unique helper for villain evidence labels */
  function _pushUnique(arr,val){if(val&&arr.indexOf(val)===-1)arr.push(val);}
  /* V25: dedup/cluster villain evidence before rendering */
  function _clusterVillainEvidence(ctxs){
    var seen={};
    var out=[];
    ctxs.forEach(function(c){
      if(c.bucket!=='villain_evidence'){out.push(c);return;}
      var vk=c.villain_key||c.v_number||c.villain_alias||'';
      var sk=c.signal_key||c.signal_family||c.signal_label||'';
      if(!sk){out.push(c);return;}
      var stk=c.street||'';
      var key=vk+'|'+sk+'|'+stk;
      if(!seen[key]){
        seen[key]=Object.assign({},c);
        seen[key]._clusterCount=1;
        out.push(seen[key]);
      } else {
        seen[key]._clusterCount++;
        if(c.so_what&&!seen[key].so_what)seen[key].so_what=c.so_what;
        if(c.suggests&&!seen[key].suggests)seen[key].suggests=c.suggests;
      }
    });
    return out;
  }
  /* v8.10.0: render a single coaching display_card into DOM */
  function _renderCoachingCard(card){
    if(!card||!card.card_type)return null;
    var v=card.variant||'';
    var el=document.createElement('div');
    el.className='learn-card'+(v?' '+v:'');
    var hd='<div class="learn-head">'
      +'<span class="learn-title">'+_esc(card.headline||'')+'</span>'
      +'<span class="decision'+(v?' '+v:'')+'">'+_esc(card.poker_verdict||'')+'</span>'
      +'</div>';
    var body='<div class="answer">'+_esc(card.why||'')+'</div>';
    var metrics='';
    if(card.metrics&&card.metrics.length){
      var mc=card.metrics.length>3?'four':'';
      metrics='<div class="metric-row'+(mc?' '+mc:'')+'">';
      card.metrics.forEach(function(m){
        var mv=m.variant?' '+m.variant:'';
        metrics+='<div class="metric'+mv+'">'
          +'<div class="m-label">'+_esc(m.label||'')+'</div>'
          +'<div class="m-value">'+_esc(m.value||'')+'</div></div>';
      });
      metrics+='</div>';
    }
    var ranges='';
    if(card.ranges&&card.ranges.length){
      card.ranges.forEach(function(r){
        var conf=r.confidence||'';
        ranges+='<div class="range-row">'
          +'<span class="range-v">'+_esc(r.villain||'')+'</span>'
          +'<span class="range-text" title="'+_esc(r.range_text||'')+'">'+_esc(r.range_text||'')+'</span>'
          +'<span class="range-conf'+(conf?' '+conf:'')+'">'+_esc(conf)+'</span>'
          +'</div>';
      });
    }
    var learn='';
    if(card.learn)learn+='<div class="learn-line"><b>Learn:</b> '+_esc(card.learn)+'</div>';
    if(card.plan)learn+='<div class="learn-line"><b>Plan:</b> '+_esc(card.plan)+'</div>';
    var src='';
    if(card.provenance){
      src='<div class="source-line">'
        +'<span class="source-chip">'+_esc(card.provenance.facts_generated_by||'programmatic')+'</span>'
        +'<span class="source-chip">'+_esc(card.display_confidence||'')+'</span>'
        +'</div>';
    }
    el.innerHTML=hd+body+metrics+ranges+learn+src;
    return el;
  }
  /* v8.10.0: render all coaching cards for a hand into a container */
  function _renderCoachingCards(hid){
    var ccMap=window.coachingCards||{};
    var ccShort=hid.length>8?hid.slice(-8):hid;
    var cards=ccMap[hid]||ccMap[ccShort];
    if(!cards||!cards.length)return null;
    var stack=document.createElement('div');
    stack.className='coach-stack';
    cards.forEach(function(c){
      var el=_renderCoachingCard(c);
      if(el)stack.appendChild(el);
    });
    return stack.children.length?stack:null;
  }
  /* V25: bulk coaching builder — wraps all contexts with one-liner + fallback label */
  function _buildOpponentCoachingBlocks(hid){
    var _hocMap=window.handOpponentContexts||{};
    var _hocShort=hid.length>8?hid.slice(-8):hid;
    var _hocs=_hocMap[hid]||_hocMap[_hocShort];
    if(!_hocs||!_hocs.length)return null;
    var _cb=document.createElement('div');_cb.className='opponent-coaching';
    var _exploitCtxs=_hocs.filter(function(c){return c.bucket==='exploit_miss'||c.bucket==='good_exploit';});
    if(_exploitCtxs.length){
      var _ol=document.createElement('div');_ol.className='cb-oneliner';
      _ol.innerHTML=_exploitCtxs.map(function(c){
        var _ico=c.bucket==='good_exploit'?'✅ Good':'❌ Miss';
        var _adj=c.so_what?(' — '+_esc(c.so_what).substring(0,80)):'';
        return '🎯 '+_esc(c.villain_alias||'')+(c.read_label?' · '+_esc(c.read_label):'')+_adj+' — '+_ico;
      }).join('<br>');
      _cb.appendChild(_ol);
    }
    var _anyReviewed=_hocs.some(function(c){return c.analyst_reviewed;});
    if(!_anyReviewed&&_exploitCtxs.length){
      var _fb=document.createElement('div');_fb.className='cb-fallback-label';
      _fb.textContent='Deterministic analysis — not yet analyst-reviewed';
      _cb.appendChild(_fb);
    }
    _hocs.forEach(function(ctx){
      var block=_renderOpponentContextBlock(ctx);
      if(block)_cb.appendChild(block);
    });
    return _cb;
  }
  function buildModalHandLegacy(hid){
    var target=document.getElementById('sec-app-hand-'+hid);
    if(!target)return null;
    var article=target.closest('article.hand-detail-card');
    var nodes=article?Array.prototype.slice.call(article.children):handSiblingNodes(target);
    /* Filter out audit rows and the mh-top wrapper (we rebuild it) */
    nodes=nodes.filter(function(n){return !(n.classList&&(n.classList.contains('audit-row')||n.classList.contains('mh-top')));});
    var title=clean(target.textContent).replace(/^Hand\s+/,'');
    var posStack=(title.match(/\(([^)]*BB)\)/)||[])[1]||'';
    var net=(title.match(/([+-]\d+(?:\.\d+)?\s*BB)/)||[])[1]||'';
    var tail=title.split('·').slice(1).map(clean).filter(function(x){return x&&!/^[+-]\d/.test(x);});
    /* Find structured or text-based elements */
    var verdictEl=firstMatch(nodes,'.mh-verdict');
    if(!verdictEl){for(var vi=0;vi<nodes.length;vi++){if(nodes[vi].tagName==='P'&&/^Verdict:/.test(clean(nodes[vi].textContent))){verdictEl=nodes[vi];break;}}}
    var metaEl=firstMatch(nodes,'.mh-meta');
    if(!metaEl){for(var mi=0;mi<nodes.length;mi++){if(nodes[mi].tagName==='P'&&/\d{4}-\d{2}-\d{2}/.test(clean(nodes[mi].textContent))){metaEl=nodes[mi];break;}}}
    var stackEl=firstMatch(nodes,'details.stack-context')||firstMatch(nodes,'.table-shell')||firstMatch(nodes,'.table-stacks');
    var heroEl=firstMatch(nodes,'.hero-hand');
    var gridEl=null;
    for(var gi=0;gi<nodes.length;gi++){
      if(nodes[gi].matches&&nodes[gi].matches('table.hand-grid')){gridEl=nodes[gi];break;}
      if(nodes[gi].querySelector){var g=nodes[gi].querySelector('table.hand-grid');if(g){gridEl=g;break;}}
    }
    var notesEls=allMatch(nodes,'.analyst-notes');
    var gtowBtn=article?article.querySelector('a.gtow-btn'):null;
    /* Build modal */
    var wrap=document.createElement('div');wrap.className='modal-hand';
    var summary=document.createElement('div');summary.className='modal-hand-summary';
    /* Top row: Hand label, ID pill, chips, actions */
    var top=document.createElement('div');top.className='mh-top';
    var titleBox=document.createElement('div');titleBox.className='mh-title';
    titleBox.appendChild(makeChip('Hand',''));
    var idSpan=document.createElement('span');idSpan.className='mh-hand-id';idSpan.textContent=hid;titleBox.appendChild(idSpan);
    if(posStack)titleBox.appendChild(makeChip(posStack));
    tail.slice(0,3).forEach(function(t){titleBox.appendChild(makeChip(t,/mistake|punt|lost|bad/i.test(t)?'bad':/cleared|correct|justified|won/i.test(t)?'good':'warn'));});
    if(net)titleBox.appendChild(makeChip(net,classifyNet(net)));
    var actions=document.createElement('div');actions.className='mh-actions';
    if(gtowBtn)actions.appendChild(gtowBtn.cloneNode(true));
    var appLink=document.createElement('a');appLink.href='#sec-app-hand-'+hid;appLink.className='mh-action appendix-link';appLink.textContent='Open appendix';
    appLink.addEventListener('click',function(){closeHand();});
    actions.appendChild(appLink);
    top.appendChild(titleBox);top.appendChild(actions);summary.appendChild(top);
    /* Meta chips */
    if(metaEl){
      var meta=document.createElement('div');meta.className='mh-meta';
      if(metaEl.classList&&metaEl.classList.contains('mh-meta')){
        metaEl.querySelectorAll('.mh-chip,.chip').forEach(function(c){meta.appendChild(c.cloneNode(true));});
      }else{splitMeta(metaEl.textContent).forEach(function(t){meta.appendChild(makeChip(t));});}
      if(meta.childNodes.length)summary.appendChild(meta);
    }
    /* Verdict */
    if(verdictEl){
      var vd=document.createElement('div');vd.className='mh-verdict';
      if(verdictEl.classList&&verdictEl.classList.contains('mh-verdict')){
        vd.innerHTML=verdictEl.innerHTML;
      }else{
        var vtxt=clean(verdictEl.textContent).replace(/\s*·\s*Mentioned in:.*$/,'');
        vd.innerHTML='<b>'+vtxt.replace(/^Verdict:\s*/,'Verdict: ')+'</b>';
      }
      var vlinks=verdictEl.querySelectorAll('a.xref:not(.hand-ref)');
      if(vlinks.length){var lr=document.createElement('div');lr.className='mh-links';lr.appendChild(document.createTextNode('Used in: '));vlinks.forEach(function(a){lr.appendChild(a.cloneNode(true));});vd.appendChild(lr);}
      summary.appendChild(vd);
    }
    wrap.appendChild(summary);
    /* v8.7.2: facing strip ABOVE Stack Context for immediate villain context */
    var fsEl=article?article.querySelector('.facing-strip'):null;
    if(fsEl)wrap.appendChild(fsEl.cloneNode(true));
    /* Stack context — single collapsed details, no duplicates */
    if(stackEl){
      var det=document.createElement('details');det.className='modal-stack';
      var sm=document.createElement('summary');sm.textContent='Stack context';det.appendChild(sm);
      var sc=stackEl.cloneNode(true);sc.querySelectorAll('.audit-row').forEach(function(ar){ar.remove();});
      det.appendChild(sc);wrap.appendChild(det);
    }
    if(heroEl)wrap.appendChild(heroEl.cloneNode(true));
    if(gridEl)wrap.appendChild(gridEl.cloneNode(true));
    notesEls.forEach(function(n){var c=n.cloneNode(true);c.querySelectorAll('.audit-row').forEach(function(ar){ar.remove();});wrap.appendChild(c);});
    /* v8.8.6 VH Phase 3: opponent coaching blocks (via shared helper) */
    var _coachingEl=_buildOpponentCoachingBlocks(hid);
    if(_coachingEl)wrap.appendChild(_coachingEl);
    return wrap;
  }
  /* V25: street-merged modal builder — see V25_Street_Merged_Modal_Implementation_Plan.md */
  function buildModalHandV25(hid){
    var target=document.getElementById('sec-app-hand-'+hid);
    if(!target)return null;
    var article=target.closest('article.hand-detail-card');
    var nodes=article?Array.prototype.slice.call(article.children):handSiblingNodes(target);
    nodes=nodes.filter(function(n){return !(n.classList&&(n.classList.contains('audit-row')||n.classList.contains('mh-top')));});
    /* --- data extraction (same sources as legacy) --- */
    var title=clean(target.textContent).replace(/^Hand\s+/,'');
    var posMatch=title.match(/\(([A-Z]+)\s/);
    var heroPos=posMatch?posMatch[1]:'';
    var stackMatch=title.match(/(\d+\.?\d*)BB\)/);
    var heroStack=stackMatch?stackMatch[1]+'BB':'';
    var net=(title.match(/([+-]\d+(?:\.\d+)?\s*BB)/)||[])[1]||'';
    var tail=title.split('·').slice(1).map(clean).filter(function(x){return x&&!/^[+-]\d/.test(x);});
    var verdictEl=firstMatch(nodes,'.mh-verdict');
    if(!verdictEl){for(var vi=0;vi<nodes.length;vi++){if(nodes[vi].tagName==='P'&&/^Verdict:/.test(clean(nodes[vi].textContent))){verdictEl=nodes[vi];break;}}}
    var metaEl=firstMatch(nodes,'.mh-meta');
    if(!metaEl){for(var mi=0;mi<nodes.length;mi++){if(nodes[mi].tagName==='P'&&/\d{4}-\d{2}-\d{2}/.test(clean(nodes[mi].textContent))){metaEl=nodes[mi];break;}}}
    /* GAP-7 v8.9.1: prefer details.stack-context first (avoids nesting) */
    var stackEl=firstMatch(nodes,'details.stack-context')||firstMatch(nodes,'.table-shell')||firstMatch(nodes,'.table-stacks');
    var heroEl=firstMatch(nodes,'.hero-hand');
    var gridEl=null;
    for(var gi=0;gi<nodes.length;gi++){
      if(nodes[gi].matches&&nodes[gi].matches('table.hand-grid')){gridEl=nodes[gi];break;}
      if(nodes[gi].querySelector){var g=nodes[gi].querySelector('table.hand-grid');if(g){gridEl=g;break;}}
    }
    var notesEls=allMatch(nodes,'.analyst-notes');
    var gtowBtn=article?article.querySelector('a.gtow-btn'):null;
    var fsEl=article?article.querySelector('.facing-strip'):null;
    /* --- build V25 wrapper --- */
    var wrap=document.createElement('div');wrap.className='v25-hand';
    /* === BUDGET-TRIMMED / NO-GRID FALLBACK (GAP-2 v8.9.1 fix) === */
    /* Only show V25 trimmed fallback for explicitly budget-trimmed hands.
       For other no-grid hands, return null to trigger legacy builder
       which can still render GTOW, meta, analyst content. */
    if(!gridEl){
      if(article&&article.classList.contains('budget-trimmed')){
        var fb=document.createElement('div');fb.className='v25-trimmed-fallback';
        fb.innerHTML='<div class="v25-trimmed-msg">Full hand detail trimmed for report size.</div>';
        wrap.appendChild(fb);
        return wrap;
      }
      return null;
    }
    /* === COMPACT SUMMARY === */
    var summary=document.createElement('div');summary.className='v25-summary';
    /* V25.3 item 5: metadata normalizer — anchored skip regexes (guardrail 4) */
    var _metaSkips=[/^L\d+$/i,/^\dBP$/i,/^SPR\b/i,/^(SRP|HU|MW|LIMP)$/i,/^(Lost|Won|No)\s+SD$/i,
      /* P1-3: skip status/verdict/emoji-prefixed chips */
      /(Mistake|Correct|Borderline|Flagged|Reviewed|Cleared|Punt)/i,
      /^[🔴🟡🟢⚪✅❌⚠️]\s*/u];
    function _isMetaSkip(t){for(var si=0;si<_metaSkips.length;si++){if(_metaSkips[si].test(t))return true;}return false;}
    var metaBar=document.createElement('div');metaBar.className='v25-meta-bar';
    if(metaEl){
      var _rawChips=[];
      if(metaEl.classList&&metaEl.classList.contains('mh-meta')){
        metaEl.querySelectorAll('.mh-chip,.chip').forEach(function(c){_rawChips.push(clean(c.textContent));});
      }else{
        _rawChips=splitMeta(metaEl.textContent);
      }
      /* GPT-QA-4: classify Date → Tournament → Type → Phase → Eff, emit Hero before Eff */
      var _dateChip='',_tourneyChip='',_typeChip='',_phaseChip='',_effChip='',_otherChips=[];
      _rawChips.forEach(function(t){
        if(_isMetaSkip(t))return;
        if(!_dateChip&&/\d{4}-\d{2}-\d{2}/.test(t)){_dateChip=t;return;}
        if(!_typeChip&&/^(BOUNTY|FREEZEOUT|SATELLITE|MYSTERY|RACER|TURBO|HYPER)$/i.test(t)){_typeChip=t;return;}
        if(!_phaseChip&&/(Late Reg|Post Reg|Early|Middle|Bubble|ITM|Final)/i.test(t)){_phaseChip=t;return;}
        if(!_effChip&&/^Eff\s+\d/i.test(t)){_effChip=t;return;}
        if(!_tourneyChip&&t.length>6){_tourneyChip=t;return;}
        _otherChips.push(t);
      });
      /* Fallback: if no tournament found, promote first non-date non-skip chip */
      if(!_tourneyChip&&_otherChips.length){_tourneyChip=_otherChips.shift();}
      /* Emit in order: Date → Tournament → Type → Phase → (Hero injected below) → Eff → others */
      function _emitMeta(txt,cls){if(!txt)return;var mi=document.createElement('span');mi.className=cls||'v25-meta-item';mi.textContent=txt;metaBar.appendChild(mi);}
      _emitMeta(_dateChip);
      _emitMeta(_tourneyChip,'v25-meta-item v25-tourney');
      _emitMeta(_typeChip);
      _emitMeta(_phaseChip);
      /* Hero pos/stack injected here — before Eff */
      if(heroPos||heroStack){_emitMeta('Hero '+heroPos+(heroStack?' '+heroStack:''));}
      _emitMeta(_effChip);
      _otherChips.forEach(function(t){_emitMeta(t);});
      /* Safety fallback: if all chips were skipped, render raw non-skip in source order */
      if(!metaBar.childNodes.length){
        _rawChips.forEach(function(t){if(!_isMetaSkip(t)){var mi=document.createElement('span');mi.className='v25-meta-item';mi.textContent=t;metaBar.appendChild(mi);}});
      }
    } else {
      /* No metaEl — still emit Hero if available */
      if(heroPos||heroStack){
        var _emH=function(txt){var mi=document.createElement('span');mi.className='v25-meta-item';mi.textContent=txt;metaBar.appendChild(mi);};
        _emH('Hero '+heroPos+(heroStack?' '+heroStack:''));
      }
    }
    if(metaBar.childNodes.length)summary.appendChild(metaBar);
    /* Decision row: verdict chips + GTOW */
    var decRow=document.createElement('div');decRow.className='v25-decision-row';
    tail.slice(0,3).forEach(function(t){
      var chip=document.createElement('span');
      chip.className='v25-decision-chip '+(/mistake|punt|lost|bad/i.test(t)?'bad':/cleared|correct|justified|won/i.test(t)?'good':'warn');
      chip.textContent=t;decRow.appendChild(chip);
    });
    if(gtowBtn){var gc=gtowBtn.cloneNode(true);gc.classList.add('v25-gtow-btn');decRow.appendChild(gc);}
    if(decRow.childNodes.length)summary.appendChild(decRow);
    /* GAP-10 v8.9.1: extract verdict text + mentioned-in backlinks */
    if(verdictEl){
      /* P1-4: Extract verdict text WITHOUT xref/link noise.
         Clone the element, strip links, then extract plain text. */
      var vP=verdictEl.querySelector('p')||verdictEl;
      var vClone=vP.cloneNode(true);
      vClone.querySelectorAll('a, .xref, .hand-ref, .mh-links').forEach(function(n){n.remove();});
      var vText=clean(vClone.textContent).replace(/^Verdict:\s*/i,'').replace(/[↑←→]+/g,'').trim();
      if(vText){
        var vDiv=document.createElement('div');vDiv.className='v25-verdict-text';vDiv.textContent=vText;
        summary.appendChild(vDiv);
      }
      /* Mentioned-in backlinks */
      var vlinks=verdictEl.querySelectorAll('a.xref:not(.hand-ref)');
      if(vlinks.length){
        var mentioned=document.createElement('div');mentioned.className='v25-mentioned';
        var mlabel=document.createElement('span');mlabel.className='v25-chip dark';mlabel.textContent='Mentioned in';mentioned.appendChild(mlabel);
        vlinks.forEach(function(a){var ac=a.cloneNode(true);ac.className='v25-chip';mentioned.appendChild(ac);});
        summary.appendChild(mentioned);
      }
    }
    wrap.appendChild(summary);
    /* === VILLAIN ROW === */
    var villainRow=document.createElement('div');villainRow.className='v25-villain-row';
    var _hocMap=window.handOpponentContexts||{};
    var _hocShort=hid.length>8?hid.slice(-8):hid;
    var _hocs=_hocMap[hid]||_hocMap[_hocShort]||[];
    _appendV25WhyLine(wrap, hid, tail, _hocs);
    var villainKey=null;
    for(var vki=0;vki<_hocs.length;vki++){if(_hocs[vki].villain_key){villainKey=_hocs[vki].villain_key;break;}}
    var vi=villainKey&&window.villainIntel?window.villainIntel[villainKey]:null;
    if(vi){
      var vt=document.createElement('span');vt.className='v25-villain-token';
      var initials=(vi.archetype_label||'??').split(/\s+/).map(function(w){return w[0];}).join('').substring(0,2);
      vt.innerHTML='<span class="v25-villain-avatar">'+_esc(initials)+'</span>'+
        '<span>'+_esc(vi.v_number||vi.alias||'')+'</span>'+
        '<span class="v25-villain-type">'+_esc(vi.archetype_label||'')+'</span>';
      villainRow.appendChild(vt);
      if(vi.confidence){var conf=document.createElement('span');conf.className='v25-chip';conf.textContent=vi.confidence+' conf';villainRow.appendChild(conf);}
      if(vi.n_evidence){var ev=document.createElement('span');ev.className='v25-chip';ev.textContent=vi.n_evidence+' hands';villainRow.appendChild(ev);}
      /* V25.3 item 4 + P1-8: coverage pill — row-specific when villain identity available */
      var _covSrc=fsEl?clean(fsEl.textContent):'';
      if(stackEl){
        var _vNum=vi.v_number||'';var _vAlias=vi.alias||'';
        if(_vNum||_vAlias){
          var _sRows=stackEl.querySelectorAll('tr,.stack-row,.v25-stack-row');
          _sRows.forEach(function(row){var rt=clean(row.textContent);
            if((_vNum&&rt.indexOf(_vNum)>=0)||(_vAlias&&rt.indexOf(_vAlias)>=0))_covSrc+=' '+rt;});
        }else{_covSrc+=' '+clean(stackEl.textContent);}
      }
      var covText='';
      if(/covers\s+Hero/i.test(_covSrc)||/✗\s*covers/i.test(_covSrc))covText='Covers Hero';
      else if(/✔\s*Covered/i.test(_covSrc)||/\bHero covers\b/i.test(_covSrc))covText='✔ Covered';
      if(covText){var cp=document.createElement('span');cp.className='v25-coverage-pill';cp.textContent=covText;villainRow.appendChild(cp);}
      /* V25.3 item 4: evidence button */
      if(vi.n_evidence&&villainKey){var evBtn=document.createElement('button');evBtn.type='button';
        evBtn.className='v25-chip v25-evidence-link';evBtn.textContent='Evidence ('+vi.n_evidence+')';
        evBtn.onclick=function(){openVillainEvidence(villainKey);};villainRow.appendChild(evBtn);}
    } else if(fsEl){
      /* P1-7: normalize facing-strip text into compact V25 chips */
      var _fsClone=fsEl.cloneNode(true);
      _fsClone.querySelectorAll('.facing-action,.facing-actions').forEach(function(n){n.remove();});
      var _fsTxt=clean(_fsClone.textContent);
      if(_fsTxt){
        var _fsParts=_fsTxt.split(/\s*[·|]\s*/).map(function(s){return s.trim();}).filter(Boolean);
        _fsParts.forEach(function(p){
          if(/^Evidence\s*\(/i.test(p))return;
          var chip=document.createElement('span');
          chip.className=/covers?\s+Hero|Hero covers|Covered/i.test(p)?'v25-coverage-pill':'v25-chip';
          chip.textContent=p;villainRow.appendChild(chip);
        });
      }
      /* GPT-QA-5: preserve clickable Evidence action from facing-strip */
      var _fsAction=fsEl.querySelector('.facing-action');
      if(_fsAction){var _evClone=_fsAction.cloneNode(true);_evClone.classList.remove('facing-action');
        _evClone.classList.add('v25-chip','v25-evidence-link');villainRow.appendChild(_evClone);}
    }
    if(villainRow.childNodes.length)wrap.appendChild(villainRow);
    /* === STACK CONTEXT (collapsed, cloned — GAP-7 v8.9.1 no double nesting) === */
    if(stackEl){
      var stClone=stackEl.cloneNode(true);
      stClone.querySelectorAll('.audit-row').forEach(function(ar){ar.remove();});
      if((stackEl.tagName||'').toUpperCase()==='DETAILS'){
        /* Already a <details> — just restyle, don't wrap in another <details> */
        stClone.className='v25-stack-details';
        var existSum=stClone.querySelector(':scope > summary');
        if(existSum){var srcText=clean(existSum.textContent).replace(/[▾▼]/g,'').trim();existSum.innerHTML=_esc(srcText||'Stack context')+' <span>&#9662;</span>';}
        wrap.appendChild(stClone);
      }else{
        var v25Stack=document.createElement('details');v25Stack.className='v25-stack-details';
        var stSummary=document.createElement('summary');stSummary.innerHTML='Stack context <span>&#9662;</span>';
        v25Stack.appendChild(stSummary);
        v25Stack.appendChild(stClone);
        wrap.appendChild(v25Stack);
      }
    }
    /* === PARSE STREETS FROM HAND GRID === */
    var ths=gridEl.querySelectorAll('thead th');
    /* P2: prefer .street-actions cells; fall back to all tbody td */
    var tds=gridEl.querySelectorAll('tbody td.street-actions');
    if(!tds.length)tds=gridEl.querySelectorAll('tbody td');
    var streetNames=[];
    for(var si=0;si<ths.length;si++){
      var thText=clean(ths[si].textContent).split(/\s/)[0].toUpperCase();
      if(thText.indexOf('PRE')>=0)streetNames.push('preflop');
      else if(thText.indexOf('FLOP')>=0)streetNames.push('flop');
      else if(thText.indexOf('TURN')>=0)streetNames.push('turn');
      else if(thText.indexOf('RIVER')>=0)streetNames.push('river');
      else streetNames.push(thText.toLowerCase());
    }
    /* --- Parse analyst notes by street (GAP-4 v8.9.1 fix) --- */
    /* Previous bug: headerless notes defaulted to preflop AND got pushed
       to unmatchedNotes, causing misrouted + duplicated commentary.
       Fix: only route to a street when an explicit .note-street header
       sets it; otherwise push to unmatchedNotes (General section). */
    var notesByStreet={};
    var unmatchedNotes=[];
    notesEls.forEach(function(notesDiv){
      /* V25.3 item 2: early-return for headerless divs prevents duplication */
      var hasHeaders=!!notesDiv.querySelector('.note-street');
      if(!hasHeaders){
        var dsAttr=(notesDiv.getAttribute('data-street')||'').toLowerCase().replace(/[\s_-]+/g,'');
        if(dsAttr&&(dsAttr==='preflop'||dsAttr==='flop'||dsAttr==='turn'||dsAttr==='river')){
          if(!notesByStreet[dsAttr])notesByStreet[dsAttr]=[];
          notesByStreet[dsAttr].push(notesDiv.cloneNode(true));
        }else{
          unmatchedNotes.push(notesDiv.cloneNode(true));
        }
        return;
      }
      var currentStreet=null;
      Array.prototype.forEach.call(notesDiv.children,function(child){
        if(child.classList&&child.classList.contains('note-street')){
          var label=clean(child.textContent).toUpperCase();
          if(label.indexOf('PRE')>=0)currentStreet='preflop';
          else if(label.indexOf('FLOP')>=0&&label.indexOf('PRE')<0)currentStreet='flop';
          else if(label.indexOf('TURN')>=0)currentStreet='turn';
          else if(label.indexOf('RIVER')>=0)currentStreet='river';
          return;
        }
        if(currentStreet){
          if(!notesByStreet[currentStreet])notesByStreet[currentStreet]=[];
          notesByStreet[currentStreet].push(child.cloneNode(true));
        }else{
          unmatchedNotes.push(child.cloneNode(true));
        }
      });
    });
    /* --- Opponent coaching: dedup villain evidence, then route by bucket to streets --- */
    _hocs=_clusterVillainEvidence(_hocs);
    var streetSet={};streetNames.forEach(function(s){streetSet[s]=true;});
    var byStreet={};
    var bottomContexts=[];
    var routedIdxs={};
    _hocs.forEach(function(ctx,idx){
      if(ctx.bucket==='exploit_miss'||ctx.bucket==='good_exploit'){
        var st=(ctx.hero_decision_street||'').toLowerCase();
        if(st&&streetSet[st]){if(!byStreet[st])byStreet[st]=[];byStreet[st].push(ctx);routedIdxs[idx]=true;}
        else bottomContexts.push(ctx);
      }else if(ctx.bucket==='villain_evidence'){
        var st2=(ctx.street||'').toLowerCase();
        /* v8.9.7 B141: only pin a villain-evidence note to an in-hand street
           card when it was actionable in THIS hand. Cross-hand aggregate notes
           (e.g. repeated_blind_overfold) are future/other-hand reads — route
           those to General reads instead. */
        var _tim=(ctx.timing||'').toLowerCase();
        var _sameHand=(ctx.same_hand_actionable===true)||_tim==='same_hand_before';
        if(st2&&streetSet[st2]&&_sameHand){if(!byStreet[st2])byStreet[st2]=[];byStreet[st2].push(ctx);routedIdxs[idx]=true;}
        else bottomContexts.push(ctx);
      }else if(ctx.bucket==='analyst_learning'){
        /* P1-5: fall back to ctx.street when hero_decision_street is empty */
        var st3=(ctx.hero_decision_street||ctx.street||'').toLowerCase();
        if(st3&&streetSet[st3]){if(!byStreet[st3])byStreet[st3]=[];byStreet[st3].push(ctx);routedIdxs[idx]=true;}
        else bottomContexts.push(ctx);
      }else{
        bottomContexts.push(ctx);
      }
    });
    /* === STREET CARDS === */
    for(var si2=0;si2<ths.length;si2++){
      var th=ths[si2];
      var td=tds[si2];
      var sName=streetNames[si2]||'unknown';
      /* BUG-C: skip dead streets (no board cards, no actions, no commentary) */
      if(sName!=='preflop'){
        var _hasBoardCards=th.querySelector('.cards')&&th.querySelector('.cards').querySelectorAll('.card').length>=(sName==='turn'?4:sName==='river'?5:3);
        var _hasActions=td&&td.querySelectorAll('.grid-action').length>0;
        var _hasNotes=(notesByStreet[sName]&&notesByStreet[sName].length)||(byStreet[sName]&&byStreet[sName].length);
        if(!_hasBoardCards&&!_hasActions&&!_hasNotes){continue;}
      }
      var section=document.createElement('section');section.className='v25-street';section.id='v25-'+sName;
      /* Street header */
      var sHead=document.createElement('div');sHead.className='v25-street-head';
      var sTitle=document.createElement('div');sTitle.className='v25-street-title';
      sTitle.textContent=sName==='preflop'?'PRE-FLOP':sName.toUpperCase();
      sHead.appendChild(sTitle);
      /* v8.14.0 Slice B: street context sits NEXT TO the street name as compact
         readable chips (pot + hand/board-state), not tiny and far-right. Empty
         state renders no blank chip. */
      var sCtx=document.createElement('div');sCtx.className='v25-street-context';
      var potEl=th.querySelector('.pot');
      var texEl=th.querySelector('.board-tex');
      var drawEl=th.querySelector('.draw-profile');
      var potTxt=potEl?clean(potEl.textContent):'';
      if(potTxt){
        var potChip=document.createElement('span');potChip.className='v25-pot-chip';
        potChip.textContent=/pot/i.test(potTxt)?potTxt:(potTxt+' pot');
        sCtx.appendChild(potChip);
      }
      var stateParts=[];
      if(texEl){var _tx=clean(texEl.textContent);if(_tx)stateParts.push(_tx);}
      if(drawEl){var _dr=clean(drawEl.textContent);if(_dr)stateParts.push(_dr);}
      var stateTxt=stateParts.join(' · ');
      if(stateTxt){
        var stChip=document.createElement('span');stChip.className='v25-strength-chip';
        stChip.textContent=stateTxt;
        sCtx.appendChild(stChip);
      }
      if(sCtx.childNodes.length)sHead.appendChild(sCtx);
      section.appendChild(sHead);
      /* Street body: 3-column grid */
      var sBody=document.createElement('div');sBody.className='v25-street-body';
      /* Column 1: Board + hero hand */
      var boardSec=document.createElement('div');boardSec.className='v25-section v25-board-section';
      if(sName==='preflop'){
        var bh4=document.createElement('h4');bh4.textContent='Hero hand';boardSec.appendChild(bh4);
        if(heroEl){
          var heroInline=document.createElement('div');heroInline.className='v25-hero-inline';
          heroInline.appendChild(document.createTextNode('Hero '));
          heroEl.querySelectorAll('.card').forEach(function(c){heroInline.appendChild(c.cloneNode(true));});
          if(heroPos){var pp=document.createElement('span');pp.className='v25-position-pill';pp.textContent=heroPos;heroInline.appendChild(pp);}
          var heroNick=heroEl.querySelector('.hero-nick');
          var heroPhase=heroEl.querySelector('.hero-phase');
          var hpParts=[];
          if(heroNick)hpParts.push(clean(heroNick.textContent).replace(/^[·\s]+/,''));
          if(heroPhase)hpParts.push(clean(heroPhase.textContent).replace(/^[·\s]+/,''));
          boardSec.appendChild(heroInline);
          if(hpParts.length){var hn=document.createElement('div');hn.className='v25-hand-name-stage';hn.textContent=hpParts.join(' · ');boardSec.appendChild(hn);}
        }
      }else{
        var bh4b=document.createElement('h4');bh4b.textContent='Board + hero hand';boardSec.appendChild(bh4b);
        var boardCards=th.querySelector('.cards');
        if(boardCards){
          var bd=document.createElement('div');bd.className='v25-board';
          var allCards=boardCards.querySelectorAll('.card');
          var newStart=sName==='flop'?0:sName==='turn'?3:sName==='river'?4:allCards.length;
          allCards.forEach(function(c,ci){var cc=c.cloneNode(true);if(ci>=newStart)cc.classList.add('v25-new-card');bd.appendChild(cc);});
          boardSec.appendChild(bd);
        }
        if(heroEl){
          var heroInline2=document.createElement('div');heroInline2.className='v25-hero-inline';
          heroInline2.appendChild(document.createTextNode('Hero '));
          heroEl.querySelectorAll('.card').forEach(function(c){heroInline2.appendChild(c.cloneNode(true));});
          boardSec.appendChild(heroInline2);
        }
      }
      sBody.appendChild(boardSec);
      /* Column 2: Actions */
      var actSec=document.createElement('div');actSec.className='v25-section v25-action-section';
      var ah4=document.createElement('h4');ah4.textContent='Action';actSec.appendChild(ah4);
      if(td){
        td.querySelectorAll('.grid-action').forEach(function(act){actSec.appendChild(act.cloneNode(true));});
      }
      sBody.appendChild(actSec);
      /* Column 3: Commentary (analyst notes for this street + routed coaching) */
      var comSec=document.createElement('div');comSec.className='v25-section v25-commentary-section';
      var ch4=document.createElement('h4');ch4.textContent='Commentary';comSec.appendChild(ch4);
      var hasCommentary=false;
      /* v8.10.0: coaching cards render BEFORE analyst notes */
      var _ccMap=window.coachingCards||{};
      var _ccHid=hid;var _ccShort=hid.length>8?hid.slice(-8):hid;
      var _ccCards=_ccMap[_ccHid]||_ccMap[_ccShort]||[];
      var _ccStreet=_ccCards.filter(function(c){return c.street===sName;});
      if(_ccStreet.length){
        var _ccStack=document.createElement('div');_ccStack.className='coach-stack';
        _ccStreet.forEach(function(c){var el=_renderCoachingCard(c);if(el)_ccStack.appendChild(el);});
        if(_ccStack.children.length){comSec.appendChild(_ccStack);hasCommentary=true;}
      }
      if(notesByStreet[sName]){
        notesByStreet[sName].forEach(function(n){comSec.appendChild(n);hasCommentary=true;});
      }
      var _noteTexts=[];
      if(notesByStreet[sName]){
        notesByStreet[sName].forEach(function(n){
          var nt=_dedupTextKey(n);
          if(nt&&nt.length>=40)_noteTexts.push(nt);
        });
      }
      if(byStreet[sName]){
        /* P1-6: add deterministic fallback label for street-routed exploit blocks */
        var _sCtxs=byStreet[sName];
        var _sExploit=_sCtxs.filter(function(c){return c.bucket==='exploit_miss'||c.bucket==='good_exploit';});
        var _sAnyRev=_sCtxs.some(function(c){return c.analyst_reviewed;});
        if(_sExploit.length&&!_sAnyRev){
          var _sfb=document.createElement('div');_sfb.className='cb-fallback-label';
          _sfb.textContent='Deterministic analysis — not yet analyst-reviewed';
          comSec.appendChild(_sfb);hasCommentary=true;
        }
        _sCtxs.forEach(function(ctx){
          var block=_renderOpponentContextBlock(ctx);
          if(block){
            var bt=_dedupTextKey(block);
            var isDup=false;
            if(bt&&bt.length>=40){
              isDup=_noteTexts.some(function(nt){
                return nt===bt||nt.indexOf(bt.substring(0,80))>=0||bt.indexOf(nt.substring(0,80))>=0;
              });
            }
            if(isDup){return;}
            comSec.appendChild(block);hasCommentary=true;
          }
        });
      }
      /* GAP-13 v8.9.1: suppress "No commentary for this street." noise — empty section is clear enough */
      sBody.appendChild(comSec);
      section.appendChild(sBody);
      wrap.appendChild(section);
    }
    /* === UNMATCHED NOTES (general fallback) === */
    if(unmatchedNotes.length){
      var genDet=document.createElement('details');genDet.className='v25-disclosure';genDet.setAttribute('open','');
      var genSum=document.createElement('summary');genSum.textContent='General commentary';genDet.appendChild(genSum);
      unmatchedNotes.forEach(function(n){genDet.appendChild(n);});
      wrap.appendChild(genDet);
    }
    /* === RESULT BOX === */
    var resultFooter=gridEl.querySelector('tfoot td.result');
    if(resultFooter){
      var resultBox=document.createElement('div');resultBox.className='v25-result-box';
      resultBox.innerHTML=resultFooter.innerHTML;
      wrap.appendChild(resultBox);
    }
    /* === BOTTOM OPPONENT COACHING (non-routed contexts) === */
    if(bottomContexts.length){
      var botDet=document.createElement('details');botDet.className='v25-disclosure';botDet.setAttribute('open','');
      var botSum=document.createElement('summary');botSum.textContent='Opponent coaching';botDet.appendChild(botSum);
      /* One-liner summary for exploit contexts */
      var _bExploit=bottomContexts.filter(function(c){return c.bucket==='exploit_miss'||c.bucket==='good_exploit';});
      if(_bExploit.length){
        var _bol=document.createElement('div');_bol.className='cb-oneliner';
        _bol.innerHTML=_bExploit.map(function(c){
          var _ico=c.bucket==='good_exploit'?'✅ Good':'❌ Miss';
          var _adj=c.so_what?(' — '+_esc(c.so_what).substring(0,80)):'';
          return '🎯 '+_esc(c.villain_alias||'')+(c.read_label?' · '+_esc(c.read_label):'')+_adj+' — '+_ico;
        }).join('<br>');
        botDet.appendChild(_bol);
      }
      /* Fallback label */
      var _bAnyReviewed=_hocs.some(function(c){return c.analyst_reviewed;});
      if(!_bAnyReviewed&&_bExploit.length){
        var _bfb=document.createElement('div');_bfb.className='cb-fallback-label';
        _bfb.textContent='Deterministic analysis — not yet analyst-reviewed';
        botDet.appendChild(_bfb);
      }
      bottomContexts.forEach(function(ctx){
        var block=_renderOpponentContextBlock(ctx);
        if(block)botDet.appendChild(block);
      });
      wrap.appendChild(botDet);
    }
    return wrap;
  }
  /* V25: public entry point — tries V25, falls back to legacy */
  function buildModalHand(hid){
    try{
      var result=buildModalHandV25(hid);
      if(result)return result;
    }catch(e){
      console.warn('V25 modal build failed for '+hid+', falling back to legacy',e);
    }
    return buildModalHandLegacy(hid);
  }
  /* ---- Hand Queue State (v8.4.0) ---- */
  window.activeHandQueue=null;
  /* V25.3 item 10: compact queue header — class-based, no inline styles */
  function _renderQueueContext(hid){
    var cb=document.getElementById('hand-queue-context');
    if(!cb)return;
    var q=window.activeHandQueue;
    if(!q||!q.handIds){cb.style.display='none';return;}
    cb.style.display='';
    var idx=q.currentIndex||0;
    var total=q.handIds.length;
    var prevDis=idx===0?' disabled':'';
    var nextDis=idx>=total-1?' disabled':'';
    var reason=(q.reasonByHand||{})[hid]||'';
    var _isInline=(q.sourceType==='inline_table'||q.sourceType==='inline_table_group');
    var backLabel=_isInline?'Back to table':'Back to list';
    var _title=_esc(q.contextTitle||'Evidence Queue');
    var _spShow=(q.sourcePath&&q.sourcePath!==q.contextTitle)?' · '+_esc(q.sourcePath):'';
    /* Build compact two-row header: main-row + chip-rail */
    var _html='<div class="v25-compact-queue">'
      +'<div class="v25-queue-main-row">'
      +'<button class="v25-queue-btn secondary v25-queue-prev" onclick="_queuePrev()"'+prevDis+'>← Prev</button>'
      +'<div class="v25-queue-title-block">'
      +'<div class="v25-queue-title" title="'+_title+'">'+_title+'</div>'
      +'<div class="v25-queue-subtitle">Hand '+(idx+1)+' of '+total+_spShow+'</div>'
      +'</div>'
      +'<button class="v25-queue-btn v25-queue-back" onclick="_queueBackToList()">'+backLabel+'</button>'
      +'<button class="v25-queue-btn secondary v25-queue-next" onclick="_queueNext()"'+nextDis+'>Next →</button>'
      +'</div>'
      +'<div class="v25-queue-chip-rail">';
    q.handIds.forEach(function(h,i){
      var cls='v25-queue-chip';
      if(i===idx)cls+=' current';
      else if(q.viewed&&q.viewed[h])cls+=' viewed';
      _html+='<button class="'+cls+'" onclick="_queueJump('+i+')">'+(i+1)+' '+(h.length>8?h.slice(-8):h)+'</button>';
    });
    _html+='</div>';
    /* Reason now shown in .v25-why-line inside the hand content */
    _html+='</div>';
    cb.innerHTML=_html;
    /* Feature 3 Case C: check if this hand appears in other IE issues */
    var otherIssues=[];
    var nhid=normalizeHandId(hid);
    document.querySelectorAll('.ie-avail[data-ref-hids]').forEach(function(td){
      var row=td.closest('.ie-row');if(!row)return;
      var ids=(td.getAttribute('data-ref-hids')||'').split(',').map(normalizeHandId);
      if(ids.indexOf(nhid)>=0){
        var name=row.querySelector('.ie-issue b');
        if(name&&name.textContent.trim()!==q.contextTitle)otherIssues.push(name.textContent.trim());
      }
    });
    /* GPT-QA-7: append inside .v25-compact-queue so it stacks vertically */
    if(otherIssues.length>0){
      var _alsoHtml='<div class="v25-queue-also">Also appears in: '
        +otherIssues.map(function(n){return '<span class="ie-wc">'+_esc(n)+'</span>';}).join(' ')+'</div>';
      var cq=cb.querySelector('.v25-compact-queue');
      if(cq){cq.insertAdjacentHTML('beforeend',_alsoHtml);}
      else{cb.innerHTML+=_alsoHtml;}
    }
  }
  function _queueJump(idx){
    var q=window.activeHandQueue;if(!q)return;
    q.currentIndex=idx;var hid=q.handIds[idx];
    if(!q.viewed)q.viewed={};q.viewed[hid]=true;
    openHand(hid);
  }
  function _queuePrev(){var q=window.activeHandQueue;if(!q||q.currentIndex<=0)return;_queueJump(q.currentIndex-1);}
  function _queueNext(){var q=window.activeHandQueue;if(!q||q.currentIndex>=q.handIds.length-1)return;_queueJump(q.currentIndex+1);}
  /* Expose queue functions globally — onclick handlers in dynamic HTML need window scope */
  window._queueJump=_queueJump;
  window._queuePrev=_queuePrev;
  window._queueNext=_queueNext;

  /* ── v8.14.0 Slice C: Compact Hand Review Queue controller ────────────────
     Operates on the server-rendered #review-queue rows (cards stay server-
     rendered — same .card vocabulary). Partitions open vs reviewed from the
     canonical review store, updates counts / top-N / celebratory state, and
     opens a row in the EXISTING V25 modal with the FULL queue as
     activeHandQueue so Prev/Next walks the whole queue, not the visible top-N. */
  /* v8.16.2 Phase E: queue status icons MUST match the modal verdict-chips
     (L816-820) — Agree=✅ check, Debate=🤔 question, Bug=🐞, Drill=🎯, Rulebook=📘.
     Was debate '🟡' (a bare yellow dot) which drifted from the modal's 🤔. */
  var _RQ_META={agree:['✅','Agree','agree'],debate:['🤔','Debate','debate'],
    report_bug:['🐞','Bug','bug'],drill:['🎯','Drill','drill'],
    rulebook:['📘','Rulebook','rulebook']};
  function _rqNorm(raw){
    var k=String(raw||'').trim().toLowerCase();
    if(k==='report bug'||k==='bug')k='report_bug';
    if(k==='clear'||k==='none'||k==='null')k='';
    return _RQ_META[k]?k:'';
  }
  window.PBReviewQueue=(function(){
    var FOLLOWUP={debate:1,report_bug:1,drill:1,rulebook:1};
    function root(){return document.getElementById('review-queue');}
    function _status(hid){
      try{return _rqNorm((_readStore(normalizeHandId(hid))||{}).status);}catch(e){return '';}
    }
    function _openQueueFrom(hid){
      var r=root();if(!r)return;
      var ids=(r.getAttribute('data-queue-ids')||'').split(',').filter(Boolean);
      var reasons={};
      r.querySelectorAll('.rq-row').forEach(function(row){
        var rd=row.getAttribute('data-hand-id');
        var rt=row.querySelector('.rq-row-title');
        reasons[rd]=(row.getAttribute('data-bucket')||'')+(rt&&rt.textContent?(' — '+rt.textContent):'');
      });
      var nid=normalizeHandId(hid);var idx=ids.indexOf(nid);
      var _qt=((r.querySelector('.rq-title')||{}).textContent||'Hands to open first');
      window.activeHandQueue={contextId:'review_queue',title:_qt,
        sourceType:'review_queue',sourcePath:_qt,
        handIds:ids.slice(),currentIndex:idx<0?0:idx,viewed:{},reasonByHand:reasons};
      window.activeHandQueue.viewed[nid]=true;
    }
    function openRow(hid){if(!hid)return;_openQueueFrom(hid);openHand(hid);}
    function refresh(){
      var r=root();if(!r)return;
      var topn=parseInt(r.getAttribute('data-topn')||'6',10)||6;
      var showAll=r.getAttribute('data-showall')==='1';
      var rows=Array.prototype.slice.call(r.querySelectorAll('.rq-list .rq-row'));
      var open=[],reviewed=[],cats={agree:0,debate:0,report_bug:0,drill:0,rulebook:0};
      rows.forEach(function(row){
        var hid=row.getAttribute('data-hand-id');var st=_status(hid);
        var stEl=row.querySelector('.rq-status');
        if(st){var _rvc=(row.querySelector('.handcards')||{}).innerHTML||'';reviewed.push({hid:hid,st:st,cards:_rvc});cats[st]=(cats[st]||0)+1;row.classList.add('is-reviewed');
          if(stEl){stEl.className='rq-status status-pill '+_RQ_META[st][2];stEl.textContent=_RQ_META[st][0]+' '+_RQ_META[st][1];}
        }else{open.push(row);row.classList.remove('is-reviewed');
          if(stEl){stEl.className='rq-status';stEl.textContent='';}}
      });
      rows.forEach(function(row){row.style.display='none';});
      var shown=0;
      open.forEach(function(row){if(showAll||shown<topn){row.style.display='';shown++;}});
      var follow=reviewed.filter(function(x){return FOLLOWUP[x.st];}).length;
      var cEl=document.getElementById('rq-count');
      if(cEl){var _allAuto=r.getAttribute('data-all-auto-clear')==='1';
        cEl.textContent='Your review: '+(_allAuto?(open.length+' auto-cleared · '):(open.length+' open · '))+reviewed.length+' marked by you';}
      var sa=document.getElementById('rq-showall');
      if(sa){if(open.length>topn){sa.hidden=false;sa.textContent=showAll?('Show top '+topn):('Show all '+open.length);}else{sa.hidden=true;}}
      var fn=document.getElementById('rq-foot-note');
      if(fn)fn.textContent=(open.length>shown&&!showAll)?('Showing top '+shown+' of '+open.length+' — Prev/Next in the modal walks the full queue.'):'';
      var rev=document.getElementById('rq-reviewed');
      if(rev){
        if(reviewed.length){rev.hidden=false;
          var lab=rev.querySelector('.rq-rev-label');
          if(lab)lab.textContent='Reviewed ('+reviewed.length+') / follow-ups ('+follow+')';
          var chips=document.getElementById('rq-revchips');
          if(chips){var ch=[];['report_bug','debate','drill','rulebook','agree'].forEach(function(k){
            if(cats[k])ch.push('<span class="rq-revchip '+_RQ_META[k][2]+'">'+_RQ_META[k][0]+' '+_RQ_META[k][1]+' '+cats[k]+'</span>');});
            chips.innerHTML=ch.join('');}
          var rl=document.getElementById('rq-reviewed-list');
          if(rl)rl.innerHTML=reviewed.map(function(x){return '<button type="button" class="rq-rev-row" data-hand-id="'+x.hid+'"><span class="rq-rank">✓</span><span class="rq-hid">'+x.hid+'</span>'+(x.cards?'<span class="handcards">'+x.cards+'</span>':'')+'<span class="rq-main">'+((x.reason||x.note||'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;'))+'</span><span class="status-pill '+_RQ_META[x.st][2]+'">'+_RQ_META[x.st][0]+' '+_RQ_META[x.st][1]+'</span></button>';}).join('');
        }else{rev.hidden=true;}
      }
      var win=document.getElementById('rq-empty-win');var list=document.getElementById('rq-list');
      var cleared=(open.length===0&&rows.length>0);
      if(win)win.hidden=!cleared;
      if(list)list.style.display=cleared?'none':'';
    }
    function init(){
      var r=root();if(!r)return;
      r.addEventListener('click',function(e){
        if(e.target.closest('#rq-showall')||e.target.closest('#rq-reviewed-head'))return;
        var row=e.target.closest('.rq-row,.rq-rev-row');
        if(row&&r.contains(row)){var hid=row.getAttribute('data-hand-id');if(hid)openRow(hid);}
      });
      r.addEventListener('keydown',function(e){
        if(e.key!=='Enter'&&e.key!==' ')return;
        var row=e.target.closest?e.target.closest('.rq-row,.rq-rev-row'):null;
        if(row){e.preventDefault();var hid=row.getAttribute('data-hand-id');if(hid)openRow(hid);}
      });
      var sa=document.getElementById('rq-showall');
      if(sa)sa.addEventListener('click',function(e){e.stopPropagation();
        r.setAttribute('data-showall',r.getAttribute('data-showall')==='1'?'0':'1');refresh();});
      var rh=document.getElementById('rq-reviewed-head');
      if(rh)rh.addEventListener('click',function(e){e.stopPropagation();
        var l=document.getElementById('rq-reviewed-list');if(!l)return;
        var willOpen=l.hidden;l.hidden=!willOpen;rh.setAttribute('aria-expanded',willOpen?'true':'false');
        var cr=document.getElementById('rq-rev-caret');if(cr)cr.textContent=willOpen?'▾':'▸';});
      refresh();
    }
    return {init:init,refresh:refresh,openRow:openRow};
  })();
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',function(){window.PBReviewQueue.init();});}
  else{window.PBReviewQueue.init();}
  function _queueBackToList(){
    var q=window.activeHandQueue;
    if(!q){closeHand();return;}
    /* v8.8.6: inline table queues — close modal and scroll to source */
    if(q.sourceType==='inline_table'||q.sourceType==='inline_table_group'){
      closeHand();
      var target=null;
      if(q.sourceElementId)target=document.getElementById(q.sourceElementId);
      if(!target&&q.contextId)target=document.querySelector('[data-hand-queue-id="'+q.contextId+'"]');
      if(target)target.scrollIntoView({behavior:'smooth',block:'center'});
      return;
    }
    closeHand();
    if(q.sourceType==='read_evidence'&&q.sourcePath){
      openReadEvidence(q.sourcePath);
    } else if(q.sourceType==='exploit_drilldown'&&q.sourcePath){
      openExploitDrilldown(q.sourcePath,q.filterType||'all');
    } else if(q.sourceType==='villain_evidence'&&q.villainKey){
      openVillainEvidence(q.villainKey);
    } else {
      openHandListPopup(q.contextTitle||'Evidence',q.handIds);
    }
  }
  window._queueBackToList=_queueBackToList;

  /* ---- Inline Table Queue Helpers (v8.8.6) ---- */
  function isHandDetailAvailable(hid){
    hid=normalizeHandId(hid);
    return !!document.querySelector('article.hand-detail-card[data-hand-id="'+hid+'"]');
  }
  window.isHandDetailAvailable=isHandDetailAvailable;
  /* V25.3 item 7c: accept element or {container, queueGroupFilter} */
  function collectHandIdsFromQueueContainer(containerOrObj){
    var container=containerOrObj.container||containerOrObj;
    var grpFilter=containerOrObj.queueGroupFilter||null;
    var ids=[],seen={};
    container.querySelectorAll('a.hand-ref[data-hand-id]').forEach(function(a){
      if(grpFilter&&a.getAttribute('data-hand-queue-group')!==grpFilter)return;
      var hid=normalizeHandId(a.getAttribute('data-hand-id'));
      if(!hid||seen[hid])return;
      if(!isHandDetailAvailable(hid))return;
      seen[hid]=true;
      ids.push(hid);
    });
    return ids;
  }
  window.collectHandIdsFromQueueContainer=collectHandIdsFromQueueContainer;
  function _inferQueueTitle(container){
    /* Explicit data attribute */
    var dt=container.getAttribute('data-hand-queue-title');
    if(dt)return dt;
    /* Caption inside the container */
    var cap=container.querySelector('caption');
    if(cap&&cap.textContent.trim())return cap.textContent.trim();
    /* Walk up from container through wrappers to find the real context */
    var anchor=container.closest('.table-shell')||container;
    var prev=anchor.previousElementSibling;
    var maxLook=6;
    while(prev&&maxLook-->0){
      /* Proper heading tags */
      if(/^H[2-5]$/.test(prev.tagName))return prev.textContent.trim();
      /* Bold/strong inline label (markdown renderer emits these for table titles) */
      var strong=prev.querySelector('strong,b');
      if(strong&&strong.textContent.trim().length>4){
        /* Use the full element text (includes count suffixes like "— 2 against Hero") */
        var txt=prev.textContent.trim();
        return txt.length>120?txt.substring(0,120):txt;
      }
      /* Div or span with heading-like content */
      if(prev.tagName==='DIV'||prev.tagName==='SPAN'||prev.tagName==='P'){
        var h=prev.querySelector('h3,h4,h5');
        if(h)return h.textContent.trim();
        /* Non-heading but descriptive (e.g. data-tip span with bold text) */
        var ptxt=prev.textContent.trim();
        if(ptxt.length>6&&ptxt.length<150&&!/^\|/.test(ptxt))return ptxt;
      }
      prev=prev.previousElementSibling;
    }
    /* Section heading */
    var sec=container.closest('section[id],div.section-card,section.chapter');
    if(sec){
      var sh=sec.querySelector('h2,h3,h4');
      if(sh)return sh.textContent.trim();
    }
    return 'Hand list';
  }
  function _findLogicalHandQueueContainer(el){
    /* P2: explicit data-hand-queue-id (could be tbody, div, table) */
    var explicit=el.closest('[data-hand-queue-id]');
    if(explicit)return explicit;
    /* P3: tbody with data-hand-queue-id — already covered above */
    /* P4: nearest table with >=2 hand refs, not inside hand detail/modal */
    var tbl=el.closest('table');
    if(tbl&&!tbl.closest('.hand-detail-card,.modal-hand,.modal,.list-popup')){
      var refs=tbl.querySelectorAll('a.hand-ref[data-hand-id]');
      if(refs.length>=2)return tbl;
    }
    /* Wrapper div with hand refs (some sections use div layouts) */
    var wrap=el.closest('.drill-table,.data-table-wrap,.gate-table-wrap,.ie-drawer');
    if(wrap&&!wrap.closest('.hand-detail-card,.modal-hand,.modal,.list-popup')){
      var wRefs=wrap.querySelectorAll('a.hand-ref[data-hand-id]');
      if(wRefs.length>=2)return wrap;
    }
    return null;
  }
  function _makeStableQueueId(title){
    var h=0,s=title||'';
    for(var i=0;i<s.length;i++){h=((h<<5)-h)+s.charCodeAt(i);h|=0;}
    return 'iq_'+Math.abs(h).toString(36);
  }
  function _inferSourceSectionId(container){
    var sec=container.closest('section[id],div[id],article[id]');
    return sec?sec.id:'';
  }
  /* V25.3 item 7c: check data-hand-queue-group on clicked element or row */
  function _collectByQueueGroup(el){
    var grp=el.getAttribute('data-hand-queue-group');
    var title=el.getAttribute('data-hand-queue-title')||'';
    if(!grp){var row=el.closest('tr');if(row){grp=row.getAttribute('data-hand-queue-group');title=title||row.getAttribute('data-hand-queue-title')||'';}}
    if(!grp)return null;
    var tbl=el.closest('table')||el.closest('.drill-table');
    if(!tbl)return null;
    return {container:tbl,queueGroupFilter:grp,queueTitle:title};
  }
  function buildInlineHandQueueFromClickedRef(handRefEl){
    /* Do not build inline queue inside list popups or modals */
    if(handRefEl.closest('.list-popup,.modal,.modal-hand'))return null;
    /* V25.3: try queue-group scoping first (guardrail 6) */
    var grpResult=_collectByQueueGroup(handRefEl);
    var container=grpResult?grpResult.container:_findLogicalHandQueueContainer(handRefEl);
    if(!container)return null;
    var sourceType='inline_table';
    if(grpResult){
      sourceType='inline_table_group';
    }else if(container.tagName==='TBODY'&&container.hasAttribute('data-hand-queue-id')){
      sourceType='inline_table_group';
    }
    var handIds=collectHandIdsFromQueueContainer(grpResult||container);
    if(handIds.length<=1)return null;
    /* Queue title: prefer group title, then inferred */
    var title=(grpResult&&grpResult.queueTitle)?grpResult.queueTitle:_inferQueueTitle(container);
    var elId=container.getAttribute('data-hand-queue-id')||container.id||'';
    var q={
      contextId:(grpResult&&grpResult.queueGroupFilter)||container.getAttribute('data-hand-queue-id')||_makeStableQueueId(title),
      contextTitle:title,
      sourceType:sourceType,
      sourceSection:_inferSourceSectionId(container),
      sourcePath:'',
      sourceElementId:elId,
      handIds:handIds,
      currentIndex:0,
      viewed:{},
      reasonByHand:{}
    };
    return q;
  }
  window.buildInlineHandQueueFromClickedRef=buildInlineHandQueueFromClickedRef;
  /* ---- Inline Queue Audit (v8.8.6) ---- */
  window.inlineHandQueueAudit=null;
  function _buildInlineQueueAudit(){
    try{
      var audit={total_tables_with_hand_refs:0,direct_hand_refs_in_tables:0,
        queue_enabled_tables:0,queue_enabled_refs:0,skipped_tables:[],by_section:{}};
      var containers=document.querySelectorAll('table,[data-hand-queue-id]');
      containers.forEach(function(tbl){
        if(tbl.closest('.hand-detail-card,.modal-hand,.modal,.list-popup'))return;
        var refs=tbl.querySelectorAll('a.hand-ref[data-hand-id]');
        if(refs.length===0)return;
        audit.total_tables_with_hand_refs++;
        audit.direct_hand_refs_in_tables+=refs.length;
        var queueable=collectHandIdsFromQueueContainer(tbl);
        var secEl=tbl.closest('section[id]');
        var secId=secEl?secEl.id:'other';
        if(!audit.by_section[secId])audit.by_section[secId]={tables:0,refs:0,queue_enabled:0};
        audit.by_section[secId].tables++;
        audit.by_section[secId].refs+=refs.length;
        if(queueable.length>1){
          audit.queue_enabled_tables++;
          audit.queue_enabled_refs+=queueable.length;
          audit.by_section[secId].queue_enabled+=queueable.length;
        } else {
          audit.skipped_tables.push({section:secId,
            reason:queueable.length===1?'only one openable hand ref':'no available hand details'});
        }
      });
      window.inlineHandQueueAudit=audit;
    }catch(e){console.warn('inlineHandQueueAudit error',e);}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',_buildInlineQueueAudit);
  else setTimeout(_buildInlineQueueAudit,0);

  /* ---- openHand / closeHand ---- */
  /* V25: top bar hydration — robust extraction with multi-level fallback */
  function _hydrateV25TopBar(hid,mhEl){
    var titleEl=document.getElementById('hand-modal-title');
    if(titleEl)titleEl.textContent=hid;  /* "Hand" is now a static label chip */
    /* Hero cards — 4-level fallback chain */
    var cardsEl=document.getElementById('v25-top-cards');
    if(cardsEl){
      cardsEl.innerHTML='';
      var firstHero=mhEl.querySelector('.v25-hero-inline');
      var cardSpans=firstHero?firstHero.querySelectorAll('.card'):null;
      if(!cardSpans||!cardSpans.length)cardSpans=mhEl.querySelectorAll('.hero-hand .cards .card');
      if(!cardSpans||!cardSpans.length)cardSpans=mhEl.querySelectorAll('.hero-hand .card');
      if((!cardSpans||!cardSpans.length)&&document.getElementById('sec-app-hand-'+hid)){
        cardSpans=document.getElementById('sec-app-hand-'+hid).querySelectorAll('.card');
      }
      if(cardSpans&&cardSpans.length){
        cardSpans.forEach(function(c){cardsEl.appendChild(c.cloneNode(true));});
      }
    }
    /* Result pill — DOM-first, regex as last resort */
    var resultEl=document.getElementById('v25-top-result');
    if(resultEl){
      var netSpan=mhEl.querySelector('.net-pos,.net-neg,.net-neu');
      if(!netSpan)netSpan=mhEl.querySelector('.hand-net-pos,.hand-net-neg,.hand-net-neu');
      if(!netSpan){
        var srcH=document.getElementById('sec-app-hand-'+hid);
        if(srcH){var srcP=srcH.closest('article.hand-detail-card')||srcH.parentElement;
          if(srcP)netSpan=srcP.querySelector('.hand-net-pos,.hand-net-neg,.hand-net-neu');}
      }
      if(netSpan){
        resultEl.textContent=clean(netSpan.textContent);
        var isPos=netSpan.classList.contains('net-pos')||netSpan.classList.contains('hand-net-pos');
        var isNeg=netSpan.classList.contains('net-neg')||netSpan.classList.contains('hand-net-neg');
        resultEl.className='v25-top-result '+(isPos?'good':(isNeg?'bad':'neutral'));
      }else{
        var resultTd=mhEl.querySelector('td.result,.v25-result-box');
        if(resultTd){
          var m=resultTd.textContent.match(/([+-]\d+\.?\d*)\s*BB/);
          if(m){var nv=parseFloat(m[1]);
            resultEl.textContent=(nv>0?'+':'')+nv.toFixed(1)+' BB';
            resultEl.className='v25-top-result '+(nv>0?'good':(nv<0?'bad':'neutral'));
          }
        }
      }
      /* v8.12.5 / v8.14.0 Slice B: the system verdict rides the top bar next to
         the BB result (hand id + cards + BB result + verdict together). Clone
         the hand's verdict pill, restyle it readable-but-not-dominant
         (.v25-top-verdict; color stays from .verdict-pill[data-verdict]), and
         NEVER expose a raw Roman verdict code in user-facing copy (stripped
         below). Remove any pill from a previous hydrate first. */
      var oldPill=resultEl.parentNode.querySelector('.v25-top-verdict');
      if(oldPill)oldPill.remove();
      var srcPill=mhEl.querySelector('.verdict-pill');
      if(!srcPill){
        var srcH2=document.getElementById('sec-app-hand-'+hid);
        var srcArt=srcH2?(srcH2.closest('article.hand-detail-card')||srcH2.parentElement):null;
        if(!srcArt)srcArt=document.querySelector("article.hand-detail-card[data-hand-id='"+hid+"']");
        if(srcArt)srcPill=srcArt.querySelector('.verdict-pill');
      }
      if(srcPill){
        var vClone=srcPill.cloneNode(true);
        vClone.removeAttribute('id');
        vClone.classList.add('v25-top-verdict');
        vClone.textContent=clean(vClone.textContent)
          .replace(/I{1,3}[.][0-9]+/g,'').replace(/[ ]{2,}/g,' ').trim();
        resultEl.parentNode.insertBefore(vClone,resultEl.nextSibling);
      }
    }
    /* Review status */
    var revEl=document.getElementById('v25-top-reviewed');
    if(revEl){
      var saved=_readStore(hid);
      if(saved&&saved.status){
        revEl.textContent=saved.status==='Agree'?'Reviewed':
                          saved.status==='Debate'?'Debate':
                          saved.status==='Report bug'?'Bug':
                          saved.status==='Drill'?'Drill':
                          saved.status==='Rulebook'?'Rulebook':'';
        revEl.style.display=saved.status?'':'none';
      }else{revEl.style.display='none';}
    }
  }
  /* P1-1: measure actual sticky element heights and sync CSS custom properties.
     Replaces hardcoded 58/42/120px with real rendered sizes. */
  function _syncV25StickyVars(){
    var panel=document.querySelector('.v25-panel');
    if(!panel)return;
    var topbar=document.getElementById('v25-topbar');
    var queue=document.getElementById('hand-queue-context');
    var review=panel.querySelector('.modal-review');
    if(topbar) panel.style.setProperty('--v25-topbar-h', topbar.offsetHeight+'px');
    if(queue) panel.style.setProperty('--v25-queue-h',
      (queue.style.display==='none'?0:queue.offsetHeight)+'px');
    if(review) panel.style.setProperty('--v25-review-h', review.offsetHeight+'px');
    /* v8.16.2 Phase C: tallest street-header height so the sticky Board/Action
       context columns pin exactly BELOW the sticky street header (no overlap,
       even when a header wraps to two lines on narrow widths). */
    var _heads=panel.querySelectorAll('.v25-street-head'),_shh=0;
    _heads.forEach(function(_h){if(_h.offsetHeight>_shh)_shh=_h.offsetHeight;});
    if(_shh) panel.style.setProperty('--v25-street-head-h', _shh+'px');
  }
  async function openHand(hid){
    if(window.PBLazy&&PBLazy.has(hid)){try{await PBLazy.ensure(hid);}catch(e){}}
    hid=normalizeHandId(hid);
    /* BUG 1 fix: clear stale queue if this hand isn't in it */
    if(window.activeHandQueue&&window.activeHandQueue.handIds){
      var found=false;
      for(var qi=0;qi<window.activeHandQueue.handIds.length;qi++){
        if(normalizeHandId(window.activeHandQueue.handIds[qi])===hid){found=true;break;}
      }
      if(!found)window.activeHandQueue=null;
    }
    var mh=buildModalHand(hid);
    var body=document.getElementById('hand-modal-body');
    body.innerHTML='';
    if(!mh){
      var ph=document.createElement('div');ph.className='modal-hand';
      ph.innerHTML='<div class="modal-hand-summary"><div class="mh-title">'
        +'Hand '+hid+'</div><p style="padding:1em;color:var(--muted);">'
        +'This hand has no full detail in the appendix. It may be referenced '
        +'in a table but was not included in the hand-detail build (appendix '
        +'cap or missing hand history). The hand ID is valid — the detail '
        +'record is just not present in this report.</p></div>';
      body.appendChild(ph);
    } else {
      body.appendChild(mh);
      if (mh) hydrateV25CommentaryCollapse(mh);
    }
    /* V25: hydrate sticky top bar (cards, result, review status) */
    _hydrateV25TopBar(hid,mh||body);
    _renderQueueContext(hid);
    loadReview(hid);
    var modal=document.getElementById('hand-modal');
    modal.setAttribute('aria-hidden','false');
    modal.classList.add('is-open');
    document.body.style.overflow='hidden';
    /* GPT-QA-2: measure sticky vars after layout settles (double-rAF) */
    requestAnimationFrame(function(){_syncV25StickyVars();requestAnimationFrame(_syncV25StickyVars);});
  }
  window.openHand=openHand;
  function closeHand(){
    saveReview();_curHid='';
    var modal=document.getElementById('hand-modal');
    modal.setAttribute('aria-hidden','true');
    modal.classList.remove('is-open');
    document.getElementById('hand-modal-body').innerHTML='';
    var cb=document.getElementById('hand-queue-context');if(cb)cb.style.display='none';
    document.body.style.overflow='';
    /* v8.6.2: run full coverage refresh on modal close (discrete event, not keystroke) */
    if(window.pbDecorateReviewTargets)pbDecorateReviewTargets();
  }
  /* ---- Review persistence: pokerbot:handreview:<date>:<hid> keys ---- */
  /* _loading guard — prevents saveReview() during loadReview() when Chrome
     fires change on programmatic select.value= assignments. PRESERVED. */
  var _curHid='',_loading=false,_lsOK=false;
  /* Bug B fix: scope keys per report date so notes don't carry across reports */
  var _reportDate=(document.querySelector('.report-app')||{}).getAttribute&&
    document.querySelector('.report-app').getAttribute('data-report-date')||'unknown';
  try{localStorage.setItem('_gem_probe','1');
    if(localStorage.getItem('_gem_probe')==='1'){_lsOK=true;}
    localStorage.removeItem('_gem_probe');
  }catch(e){}
  function _key(hid){
    /* Normalize hand IDs so TM-prefix and short form resolve to same key.
       Section/issue IDs (sec-*, issue:*) pass through unchanged. */
    var k=String(hid||'');
    if(/^\d+$/.test(k)||/^TM/.test(k))k=normalizeHandId(k);
    return 'pokerbot:handreview:'+_reportDate+':'+k;
  }
  function _readStore(hid){
    var d={};
    try{d=JSON.parse(sessionStorage.getItem(_key(hid))||'null');}catch(e){}
    if(!d&&_lsOK){try{d=JSON.parse(localStorage.getItem(_key(hid))||'null');}catch(e){}}
    return d||{};
  }
  function _writeStore(hid,obj){
    var json=JSON.stringify(obj);
    try{sessionStorage.setItem(_key(hid),json);}catch(e){}
    if(_lsOK){try{localStorage.setItem(_key(hid),json);}catch(e){}}
  }
  /* Bug C fix: Migration bridge — one-shot via sentinel.
     COPY gem-review-* → scoped pokerbot:handreview:<date>:<hid>.
     Legacy keys deleted after copy to prevent perpetual re-import. */
  function _migrateOldKeys(){
    var sentinel='pokerbot:migrated:'+_reportDate;
    try{if(localStorage.getItem(sentinel)==='1')return;}catch(e){}
    var stores=[sessionStorage];if(_lsOK)stores.push(localStorage);
    for(var s=0;s<stores.length;s++){var st=stores[s];
      var toDelete=[];
      try{for(var i=0;i<st.length;i++){var k=st.key(i);
        if(k&&k.indexOf('gem-review-')===0){var hid=k.replace('gem-review-','');
          var newK=_key(hid);
          if(!st.getItem(newK))st.setItem(newK,st.getItem(k));
          toDelete.push(k);
        }
        /* Also migrate old unscoped pokerbot:handreview:<hid> keys */
        if(k&&/^pokerbot:handreview:[^:]+$/.test(k)){
          var hid2=k.replace('pokerbot:handreview:','');
          var newK2=_key(hid2);
          if(!st.getItem(newK2))st.setItem(newK2,st.getItem(k));
          toDelete.push(k);
        }
      }}catch(e){}
      try{toDelete.forEach(function(dk){st.removeItem(dk);});}catch(e){}}
    try{localStorage.setItem(sentinel,'1');}catch(e){}
  }
  _migrateOldKeys();
  function loadReview(hid){
    _loading=true;_curHid=hid;
    var d=_readStore(hid);
    document.getElementById('modal-review-status').value=d.status||'';
    document.getElementById('modal-review-notes').value=d.notes||'';
    document.getElementById('modal-save-state').textContent=(d.status||d.notes)?'Loaded':'';
    /* v8.8.6: sync verdict chip active state from loaded review */
    var _vcr=document.querySelector('.verdict-chip-row');
    if(_vcr){_vcr.querySelectorAll('.verdict-chip').forEach(function(btn){
      btn.classList.toggle('active',btn.getAttribute('data-verdict')===(d.status||''));
    });}
    _loading=false;
  }
  function saveReview(){
    if(!_curHid||_loading)return;
    var st=document.getElementById('modal-review-status').value;
    var nt=document.getElementById('modal-review-notes').value;
    /* B-V10 BUG FIX: always save (even when clearing to empty).
       Without this, resetting verdict to "--Verdict--" doesn't persist
       because the old saved data is never deleted. */
    _writeStore(_curHid,{status:st,notes:nt});
    var ss=document.getElementById('modal-save-state');
    if(st||nt){
      setReviewed(_curHid);
      ss.textContent='Auto-saved';
      /* B-V10 BUG FIX: also update the inline audit-row pill on this hand
         so "Hands to Open" shows green when reviewed via the modal. */
      document.querySelectorAll('.audit-row[data-aid*="'+_curHid+'"]')
        .forEach(function(r){
          var prev=r.querySelector('.audit-preview');
          if(prev)prev.textContent=' — ['+st+']'+(nt?' '+nt.slice(0,40):'');
          r.classList.add('has-feedback');
        });
    } else {
      ss.textContent='Cleared';
      /* Remove reviewed state when both fields are empty */
      document.querySelectorAll('a.hand-ref[data-hand-id="'+_curHid+'"]')
        .forEach(function(el){el.classList.remove('reviewed');});
      document.querySelectorAll('.audit-row[data-aid*="'+_curHid+'"]')
        .forEach(function(r){
          var prev=r.querySelector('.audit-preview');
          if(prev)prev.textContent=' — not yet reviewed';
          r.classList.remove('has-feedback');
        });
    }
    ss.classList.remove('flash');void ss.offsetWidth;ss.classList.add('flash');
    /* V25: sync top bar reviewed status */
    var revTopEl=document.getElementById('v25-top-reviewed');
    if(revTopEl){
      revTopEl.textContent=st==='Agree'?'Reviewed':st==='Debate'?'Debate':
                           st==='Report bug'?'Bug':st==='Drill'?'Drill':
                           st==='Rulebook'?'Rulebook':'';
      revTopEl.style.display=st?'':'none';
    }
    if(window._gemUpdCount)window._gemUpdCount();
    refreshReviewPanel();
    /* v8.14.0 Slice C: re-partition the compact review queue (open vs reviewed)
       and refresh its counts whenever a status changes. */
    if(window.PBReviewQueue)window.PBReviewQueue.refresh();
    if(window.pbUpdateHandRefs)window.pbUpdateHandRefs(_curHid);
  }
  function setReviewed(hid){
    document.querySelectorAll('a.hand-ref[data-hand-id="'+hid+'"]')
      .forEach(function(el){el.classList.add('reviewed');});
  }
  /* B-V10: expose to the audit-row script block so inline edits persist */
  window._gemWriteStore=_writeStore;
  window._gemReadStore=function(hid){return _readStore?_readStore(normalizeHandId(hid)):null;};

  /* ---- PBReview global API (v8.6.2: cached index, no per-hand querySelector) ---- */
  var _pbIndex=null; /* {availableSet, refsByHid} — built once on first use */
  function _pbBuildIndex(){
    if(_pbIndex)return _pbIndex;
    var avail=new Set();
    var refs={};
    document.querySelectorAll('article.hand-detail-card[data-hand-id]').forEach(function(a){
      avail.add(a.getAttribute('data-hand-id'));
    });
    document.querySelectorAll('[id]').forEach(function(el){
      var m=el.id.match(/^sec-app-hand-(\d+)$/);
      if(m)avail.add(m[1]);
    });
    document.querySelectorAll('a.hand-ref[data-hand-id]').forEach(function(a){
      var hid=normalizeHandId(a.getAttribute('data-hand-id'));
      if(!refs[hid])refs[hid]=[];
      refs[hid].push(a);
    });
    _pbIndex={availableSet:avail,refsByHid:refs};
    return _pbIndex;
  }
  window.PBReview={
    normalize:normalizeHandId,
    isReviewed:function(hid){
      var d=_readStore(normalizeHandId(hid));
      return !!(d&&(d.status||d.notes));
    },
    coverage:function(hids){
      var idx=_pbBuildIndex();
      var ids=String(hids||'').split(',').map(normalizeHandId).filter(Boolean);
      var seen={};ids=ids.filter(function(h){if(seen[h])return false;seen[h]=true;return true;});
      var available=ids.filter(function(h){return idx.availableSet.has(h);});
      var reviewed=available.filter(function(h){return window.PBReview.isReviewed(h);});
      return {total:ids.length,available:available.length,missing:ids.length-available.length,
              reviewed:reviewed.length};
    }
  };
  function pbReviewPillHTML(cov,opts){
    opts=opts||{};
    if(!cov||cov.total===0)return '<span class="review-pill review-na">Metric-only</span>';
    if(cov.available===0)return '<span class="review-pill review-missing">0/'+cov.total+' avail</span>';
    /* User-QA-4: clear text instead of cryptic symbols */
    var cls='review-none';
    if(cov.reviewed===cov.available){cls='review-all';}
    else if(cov.reviewed>0){cls='review-some';}
    var text;
    if(cov.reviewed===cov.available){text='Reviewed';}
    else{text=cov.reviewed+'/'+cov.available+(opts.compact?' rev':' reviewed');}
    if(cov.missing>0&&!opts.compact)text+=' \xb7 '+cov.missing+' missing';
    return '<span class="review-pill '+cls+'">'+text+'</span>';
  }
  /* Update only one hand's refs (fast — for saveReview) */
  function pbUpdateHandRefs(hid){
    var idx=_pbBuildIndex();
    var target=normalizeHandId(hid);
    var rev=window.PBReview.isReviewed(target);
    (idx.refsByHid[target]||[]).forEach(function(a){
      a.classList.toggle('reviewed',rev);a.title=rev?'Reviewed':'Not reviewed yet';
    });
  }
  /* Full coverage pill refresh (expensive — only on init, reset, import, modal close) */
  var _pbDecorateTimer=null;
  function pbDecorateReviewTargets(){
    if(!window.PBReview||!window.PBReview.coverage)return;
    var idx=_pbBuildIndex();
    for(var hid in idx.refsByHid){
      var rev=window.PBReview.isReviewed(hid);
      idx.refsByHid[hid].forEach(function(a){
        a.classList.toggle('reviewed',rev);a.title=rev?'Reviewed':'Not reviewed yet';
      });
    }
    document.querySelectorAll('.ie-avail[data-ref-hids]').forEach(function(td){
      var raw=td.getAttribute('data-ref-hids')||'';
      var mo=td.getAttribute('data-metric-only')==='true';
      var cov=mo?{total:0,available:0,missing:0,reviewed:0}:window.PBReview.coverage(raw);
      var old=td.querySelector('.review-pill');if(old)old.remove();
      td.insertAdjacentHTML('beforeend',pbReviewPillHTML(cov,{compact:false}));
    });
    document.querySelectorAll('.hand-list-trigger[data-hids]').forEach(function(a){
      var cov=window.PBReview.coverage(a.getAttribute('data-hids'));
      var next=a.nextElementSibling;
      if(next&&next.classList&&next.classList.contains('review-pill'))next.remove();
      a.insertAdjacentHTML('afterend',pbReviewPillHTML(cov,{compact:true}));
    });
  }
  function pbDecorateDebounced(){
    if(_pbDecorateTimer)clearTimeout(_pbDecorateTimer);
    _pbDecorateTimer=setTimeout(pbDecorateReviewTargets,500);
  }
  window.pbDecorateReviewTargets=pbDecorateReviewTargets;
  function setReviewedNorm(hid){pbUpdateHandRefs(hid);}
  window._gemSetReviewed=setReviewedNorm;
  /* ---- Review notes sidebar panel ---- */
  function refreshReviewPanel(){
    var ch=document.getElementById('context-hands');
    if(!ch)return;
    var prefix='pokerbot:handreview:'+_reportDate+':';
    var items=[];
    /* Collect reviewed hands present in this document */
    var docHids={};
    document.querySelectorAll('article.hand-detail-card[data-hand-id]').forEach(function(a){
      docHids[a.getAttribute('data-hand-id')]=true;
    });
    var stores2=[sessionStorage];if(_lsOK)stores2.push(localStorage);
    var seen={};
    for(var si=0;si<stores2.length;si++){try{
      for(var ri=0;ri<stores2[si].length;ri++){var rk=stores2[si].key(ri);
        if(rk&&rk.indexOf(prefix)===0){
          var hid=rk.replace(prefix,'');
          if(seen[hid]||!docHids[hid])continue;
          seen[hid]=true;
          var d=null;try{d=JSON.parse(stores2[si].getItem(rk));}catch(e){}
          if(d&&(d.status||d.notes)){
            /* Find section context from first pill in DOM */
            var pill=document.querySelector('a.hand-ref[data-hand-id="'+hid+'"]');
            var sec='';
            if(pill){
              var ch2=pill.closest('.chapter');
              if(ch2){var hd=ch2.querySelector('h2,h3');if(hd)sec=hd.textContent.replace(/^[\d.\s]+/,'').trim();}
            }
            items.push({hid:hid,status:d.status||'',notes:d.notes||'',sec:sec});
          }
        }
      }
    }catch(e){}}
    if(items.length===0){
      ch.innerHTML='<p class="raw-ref review-empty">No hands reviewed yet. Open a hand and mark Agree / Debate / Bug to build your review queue.</p>';
      return;
    }
    var html='';
    for(var i=0;i<items.length;i++){
      var it=items[i];
      var scls='';
      var sl=it.status.toLowerCase();
      if(sl==='good'||sl==='ok')scls='s-good';
      else if(sl==='mistake'||sl==='punt'||sl==='bad')scls='s-mistake';
      else if(sl==='debate'||sl==='unclear')scls='s-debate';
      else if(sl==='review'||sl==='flag')scls='s-review';
      var stag=it.status?('<span class="ri-status '+scls+'">'+it.status+'</span>'):'';
      var ntext=it.notes.length>60?it.notes.slice(0,60)+'…':it.notes;
      /* Escape HTML */
      var tmp=document.createElement('span');
      tmp.textContent=ntext;var safeNotes=tmp.innerHTML;
      tmp.textContent=it.sec;var safeSec=tmp.innerHTML;
      html+='<button class="review-item" data-hid="'+it.hid+'">'
        +'<span class="ri-hid">'+it.hid+'</span>'+stag
        +(safeSec?(' <span style="font-size:11px;color:var(--muted);">— '+safeSec+'</span>'):'')
        +(safeNotes?('<span class="ri-notes">'+safeNotes+'</span>'):'')
        +'</button>';
    }
    ch.innerHTML=html;
    ch.querySelectorAll('.review-item').forEach(function(btn){
      btn.addEventListener('click',function(){openHand(btn.getAttribute('data-hid'));});
    });
  }
  /* ---- List popup (hand-evidence sections shown inline) ---- */
  /* Intercepts a.xref links whose target contains hand-ref links.
     Shows the target section content in a popup instead of scrolling. */
  var _listOpen=false;
  function collectSectionNodes(target){
    /* Walk siblings from target, collecting content until next same-level
       heading boundary. Handles: anchor-compat spans, H3/H4 headings. */
    var nodes=[],n=target,guard=0,stopTag='H2';
    /* If target is an inline element (span, a), advance to next sibling.
       If that sibling is an H3/H4/H5, include it and set stop boundary. */
    if(/^(SPAN|A)$/i.test(target.tagName)){
      n=target.nextElementSibling;
      if(n&&/^H[345]$/.test(n.tagName)){
        nodes.push(n);stopTag=n.tagName;n=n.nextElementSibling;
      }
    }
    /* If target IS a heading, include it and set stop boundary */
    else if(/^H[345]$/.test(target.tagName)){
      nodes.push(target);stopTag=target.tagName;n=target.nextElementSibling;
    }
    while(n&&guard++<200){
      /* Stop at same-level or higher heading (H2 always stops) */
      if(n.tagName==='H2')break;
      if(n.tagName===stopTag&&nodes.length>1)break;
      if(n.tagName==='HR')break;
      /* Skip anchor-compat spans and toc-back links */
      if(n.tagName==='SPAN'&&n.classList.contains('anchor-compat')){n=n.nextElementSibling;continue;}
      if(n.tagName==='A'&&n.classList.contains('toc-back')){n=n.nextElementSibling;continue;}
      nodes.push(n);
      n=n.nextElementSibling;
    }
    return nodes;
  }
  function hasHandList(nodes){
    /* Strict check: only return true when the collected content is a
       STRUCTURED hand-evidence list — a data-table with hand-ref cells,
       or a <details> block with hand-ref items.
       Does NOT trigger on <ul>/<ol> analysis bullets that merely mention
       a hand in passing — those stay as normal scroll-to links. */
    for(var i=0;i<nodes.length;i++){
      var n=nodes[i];if(!n.querySelector)continue;
      /* Table with hand-ref cells (deviation tables in S17, evidence in S4) */
      if((n.matches&&n.matches('.table-shell'))||n.querySelector&&n.querySelector('.table-shell')){
        var t=n.querySelector?n.querySelector('.data-table'):null;
        if(t&&t.querySelector('a[data-hand-id]'))return true;
      }
      if(n.matches&&n.matches('table.data-table')&&n.querySelector('a[data-hand-id]'))return true;
      /* Details block with hand-refs (bet/check evidence in S11) */
      if(n.tagName==='DETAILS'&&n.querySelector('a[data-hand-id]'))return true;
    }
    return false;
  }
  function openListPopup(targetId){
    var target=document.getElementById(targetId);
    if(!target)return false;
    var nodes=collectSectionNodes(target);
    if(!nodes.length||!hasHandList(nodes))return false;
    /* Determine title from first heading in collected nodes */
    var title='Example Hands';
    for(var ti=0;ti<nodes.length;ti++){
      if(/^H[345]$/.test(nodes[ti].tagName)){
        title=clean(nodes[ti].textContent).replace(/^S\d+(\.\d+)*\s*[-–—]\s*/,'');
        break;
      }
    }
    /* Build popup content */
    var body=document.getElementById('list-modal-body');
    body.innerHTML='';
    for(var ci=0;ci<nodes.length;ci++){
      var el=nodes[ci];
      /* Skip headings — we already show title in modal head */
      if(/^H[345]$/.test(el.tagName))continue;
      /* Transform <details> with <ul> hand evidence → table */
      if(el.tagName==='DETAILS'&&el.querySelector('ul a[data-hand-id]')){
        var items=el.querySelectorAll('li');
        if(items.length){
          var tbl=document.createElement('table');tbl.className='data-table';
          var hdr=document.createElement('tr');
          ['Hand','Tournament','Position','Cards','Net'].forEach(function(h){
            var th=document.createElement('th');th.textContent=h;hdr.appendChild(th);
          });
          tbl.appendChild(hdr);
          items.forEach(function(li){
            var row=document.createElement('tr');
            var pill=li.querySelector('a[data-hand-id]');
            var txt=li.textContent||'';
            /* Parse: ... · HANDID • TOURNEY • POS STACK — CARDS, TYPE on BOARD · net ±XXBB */
            var parts=txt.split('•');
            var handCell=document.createElement('td');
            handCell.setAttribute('data-label','Hand');
            if(pill)handCell.appendChild(pill.cloneNode(true));
            else handCell.textContent='-';
            row.appendChild(handCell);
            /* Tournament */
            var tCell=document.createElement('td');
            tCell.setAttribute('data-label','Tournament');
            tCell.textContent=clean(parts.length>1?parts[1]:'');
            row.appendChild(tCell);
            /* Position+stack (from part after 2nd •, before —) */
            var posRaw=parts.length>2?parts[2]:'';
            var dashSplit=posRaw.split('—');
            var pCell=document.createElement('td');
            pCell.setAttribute('data-label','Position');
            pCell.textContent=clean(dashSplit[0]||'');
            row.appendChild(pCell);
            /* Cards (after —, before · net) */
            var cardNet=dashSplit.length>1?dashSplit[1]:'';
            var netSplit=cardNet.split('·');
            var cCell=document.createElement('td');
            cCell.setAttribute('data-label','Cards');
            /* Clone card spans for colored rendering */
            var cardSpans=li.querySelectorAll('span.card');
            if(cardSpans.length){cardSpans.forEach(function(s){cCell.appendChild(s.cloneNode(true));cCell.appendChild(document.createTextNode(' '));});}
            else{cCell.textContent=clean(netSplit[0]||'');}
            row.appendChild(cCell);
            /* Net */
            var nCell=document.createElement('td');
            nCell.setAttribute('data-label','Net');
            var netTxt=netSplit.length>1?clean(netSplit[netSplit.length-1]):'';
            nCell.textContent=netTxt.replace(/^net\s*/i,'');
            var netEl=li.querySelector('.hand-net-neg,.hand-net-pos');
            if(netEl){nCell.className=netEl.className;}
            row.appendChild(nCell);
            tbl.appendChild(row);
          });
          var shell=document.createElement('div');shell.className='table-shell';
          var scroll=document.createElement('div');scroll.className='table-scroll';
          scroll.appendChild(tbl);shell.appendChild(scroll);
          body.appendChild(shell);
          continue;
        }
      }
      var clone=el.cloneNode(true);
      /* Open any remaining <details> */
      if(clone.tagName==='DETAILS')clone.open=true;
      if(clone.querySelectorAll){
        clone.querySelectorAll('details:not(.audit-row)').forEach(function(d){d.open=true;});
        clone.querySelectorAll('.audit-row').forEach(function(ar){ar.remove();});
      }
      body.appendChild(clone);
    }
    document.getElementById('list-modal-title').textContent=title;
    var modal=document.getElementById('list-modal');
    modal.setAttribute('aria-hidden','false');
    modal.classList.add('is-open');
    document.body.style.overflow='hidden';
    _listOpen=true;
    return true;
  }
  function closeListPopup(){
    if(!_listOpen)return;
    var modal=document.getElementById('list-modal');
    modal.setAttribute('aria-hidden','true');
    modal.classList.remove('is-open');
    document.getElementById('list-modal-body').innerHTML='';
    document.body.style.overflow='';
    _listOpen=false;
    /* P0 #6: clear queue when list popup fully closes */
    if(!_listWasOpen)window.activeHandQueue=null;
  }
  /* ---- FEAT-2/3/4: generic hand-list popup from hand IDs ---- */
  /* v8.12.8 QA3: client-side popup column sort. Numeric where the cell
     parses (Hand id, Net BB), lexical otherwise; Cards always lexical
     (rank letters strip to garbage numerically). Availability rows
     (colspan) stay pinned to the bottom. */
  function _sortPopupTable(tbl,ci,th){
    var rows=Array.prototype.slice.call(tbl.querySelectorAll('tr')).slice(1);
    var dataRows=rows.filter(function(r){return r.children.length>=5;});
    var rest=rows.filter(function(r){return r.children.length<5;});
    var asc=th.getAttribute('data-sort')!=='asc';
    Array.prototype.forEach.call(tbl.querySelectorAll('th'),function(t){
      t.removeAttribute('data-sort');
      t.textContent=t.textContent.replace(/ [▲▼]$/,'');
    });
    th.setAttribute('data-sort',asc?'asc':'desc');
    th.textContent=th.textContent.replace(/ [▲▼]$/,'')+(asc?' ▲':' ▼');
    dataRows.sort(function(a,b){
      var x=(a.children[ci]?a.children[ci].textContent:'').trim();
      var y=(b.children[ci]?b.children[ci].textContent:'').trim();
      var cmp;
      if(ci===2){cmp=x.localeCompare(y);}
      else{
        var nx=parseFloat(x.replace(/[^\d.+-]/g,''));
        var ny=parseFloat(y.replace(/[^\d.+-]/g,''));
        cmp=(!isNaN(nx)&&!isNaN(ny))?(nx-ny):x.localeCompare(y);
      }
      return asc?cmp:-cmp;
    });
    dataRows.concat(rest).forEach(function(r){tbl.appendChild(r);});
  }
  function openHandListPopup(title,hids){
    if(!hids||!hids.length)return false;
    hids=hids.map(normalizeHandId);
    /* v8.17 B8: a count of exactly ONE opens the hand directly (one click),
       not a one-row popup. Falls through to the list popup when the single
       hand is not openable, so the availability reason still shows. */
    if(hids.length===1){
      var _only=hids[0]; if(_only.length>8)_only=_only.slice(-8);
      var _art=document.querySelector('article.hand-detail-card[data-hand-id="'+_only+'"]');
      var _lazy=!!(window.PB_PAYLOADS&&window.PB_PAYLOADS.lazyHands);
      if(_art||_lazy){ try{openHand(_only);return true;}catch(e){} }
    }
    var body=document.getElementById('list-modal-body');
    body.innerHTML='';
    var tbl=document.createElement('table');tbl.className='data-table';
    var hdr=document.createElement('tr');
    /* Dynamic Position header: "Vs Pos" for defend popups where Hero pos is always the same */
    var _posHeader='Position';
    if(title&&(title.indexOf('defend')>=0||title.indexOf('Defend')>=0||
       title.indexOf('BB ')===0||title.indexOf('SB ')===0||
       title.indexOf('Missed BB')>=0||title.indexOf('Missed SB')>=0||
       title.indexOf('Wide BB')>=0||title.indexOf('Wide SB')>=0))
      _posHeader='Vs Pos';
    ['Hand',_posHeader,'Cards','Net','Verdict'].forEach(function(h,ci){
      var th=document.createElement('th');th.textContent=h;
      /* v8.12.8 QA3 (feature request): sortable columns */
      th.style.cursor='pointer';
      th.title='Click to sort';
      th.addEventListener('click',function(){_sortPopupTable(tbl,ci,th);});
      hdr.appendChild(th);
    });
    tbl.appendChild(hdr);
    var _shownCount=0;
    hids.forEach(function(rawHid){
      /* B-V10: normalize to short 8-digit form */
      var hid=rawHid;
      if(hid.length>8)hid=hid.slice(-8);
      var art=document.querySelector('article.hand-detail-card[data-hand-id="'+hid+'"]');

      /* v8.8.6 HA Phase 2: three-state availability display */
      if(!art){
        var _mr=document.createElement('tr');_mr.style.opacity='0.5';
        var _mc=document.createElement('td');_mc.colSpan=5;
        var _reason=(window.handAvailability||{})[normalizeHandId(hid)]||'not_rendered';
        var _labels={
          'non_replayable':'No replay — raw hand data missing',
          'not_rendered':'Not selected for detail view',
          'appendix_cap':'Not selected — appendix cap reached',
          'budget_trimmed':'Not selected — file size budget'
        };
        _mc.innerHTML='<code>'+hid+'</code> — '+(_labels[_reason]||_labels['not_rendered']);
        _mr.appendChild(_mc);tbl.appendChild(_mr);return;
      }
      _shownCount++;

      /* ---- ROBUST DATA EXTRACTION with multiple fallback paths ---- */
      /* v8.12.8: window.handIndex FIRST — with --lazy-hand-details the
         article is an empty shell until PBLazy inflates it, so the DOM
         scrape below produced blank Position/Cards/Net for every hand the
         user hadn't opened yet. The index is emitted at build time. */
      var _hpos='',_hcards='',_hnet='',_hverdict='';
      var _idx=(window.handIndex||{})[normalizeHandId(hid)]||{};
      /* v8.12.8 QA3: "Vs Pos" means the OPENER Hero defended against —
         the cell always showed Hero's own position (BB on every row) */
      if(_posHeader==='Vs Pos'){_hpos=_idx.o||'—';}
      else if(_idx.p)_hpos=_idx.p;
      if(_idx.c)_hcards=fmtCardSpans(_idx.c);
      if(typeof _idx.n==='number')_hnet=(_idx.n>0?'+':'')+_idx.n.toFixed(1)+' BB';
      if(art){
        /* 1. Parse the heading — most reliable source */
        var _htxt=art.querySelector('h4,h5');
        if(_htxt){
          var _ht=_htxt.textContent||'';
          var _pm=_ht.match(/\((\w[\w+]*)\s+[\d.]+BB\)/);
          if(_pm&&!_hpos)_hpos=_pm[1];
          var _nm=_ht.match(/([+-][\d.]+)\s*BB/);
          if(_nm&&!_hnet)_hnet=_nm[1]+' BB';
        }
        /* 2. Cards from .hero-hand, then from heading */
        var _hero=art.querySelector('.hero-hand');
        if(_hero&&!_hcards){
          var _cs=_hero.querySelectorAll('span.card');
          if(_cs.length)_hcards=Array.prototype.map.call(_cs,function(s){return s.outerHTML;}).join(' ');
        }
        if(!_hcards&&_htxt){
          /* Fallback: grab card spans from the heading itself */
          var _hcs=_htxt.querySelectorAll('span.card');
          if(_hcs.length)_hcards=Array.prototype.map.call(_hcs,function(s){return s.outerHTML;}).join(' ');
        }
        /* 3. Position from .hero-hand "in the XX", then .mh-chip, then heading */
        if(!_hpos&&_hero){
          var _hpt=_hero.textContent||'';
          var _hpm=_hpt.match(/in the (\w[\w+]*)/);
          if(_hpm)_hpos=_hpm[1];
        }
        if(!_hpos){
          var _mchips=art.querySelectorAll('.mh-chip');
          for(var _mc=0;_mc<_mchips.length;_mc++){
            var _mct=_mchips[_mc].textContent.trim();
            if(/^(UTG|UTG\+1|UTG\+2|MP|HJ|CO|BTN|SB|BB|LJ)$/i.test(_mct)){_hpos=_mct;break;}
          }
        }
        /* 4. Net from .hand-net-*, then heading, then tfoot */
        var _netEl=art.querySelector('.hand-net-neg,.hand-net-pos,.hand-net-neu');
        if(_netEl&&!_hnet)_hnet=_netEl.textContent.trim();
        if(!_hnet){
          var _tfoot=art.querySelector('tfoot .result');
          if(_tfoot){
            var _tfm=_tfoot.textContent.match(/([+-][\d.]+)\s*BB/);
            if(_tfm)_hnet=_tfm[1]+' BB';
          }
        }
        /* 5. Verdict — multiple sources, priority order */
        /* a. Analyst verdict from .mh-verdict */
        var vdiv=art.querySelector('.mh-verdict');
        if(vdiv){
          var vtext=vdiv.textContent.trim();
          var vm=vtext.match(/(I{1,3}\.\d\S*\s+\w[\w\s-]*\w)/);
          if(vm)_hverdict=vm[1].trim();
        }
        /* a2. v8.12.9 (GPT QA P1.5): the static heading carries the
           verdict-pill BEFORE lazy inflation — read it so popup rows show
           "Cooler"/"Justified" instead of "not individually reviewed". */
        if(!_hverdict){
          var _vpill=art.querySelector('.verdict-pill');
          if(_vpill){
            _hverdict=(_vpill.getAttribute('data-verdict')
                       ||_vpill.textContent||'').trim();
          }
        }
        /* b1. Push-range verdict (<=25BB open-shove chart check) */
        if(!_hverdict){
          var _pushGrid=art.querySelector('table.hand-grid[data-push-verdict]');
          if(_pushGrid){
            _hverdict=_pushGrid.getAttribute('data-push-verdict');
          }
        }
        /* b2. Push verdict from visible .push-verdict element */
        if(!_hverdict){
          var _pushDiv=art.querySelector('.push-verdict');
          if(_pushDiv&&_pushDiv.textContent.trim())
            _hverdict=_pushDiv.textContent.trim();
        }
        /* b. All-in equity + classification from footer */
        if(!_hverdict){
          var _footText=art.querySelector('tfoot');
          if(_footText){
            var _ft=_footText.textContent||'';
            /* Extract equity + favorite/underdog + luck label to build
               a meaningful classification, not just "33% (underdog)" */
            var _eq_m=_ft.match(/All-in equity:\s*(\d+)%\s*\(([^)]+)\)/);
            var _luck_m=_ft.match(/got (lucky|unlucky)/);
            if(_eq_m){
              var _eq_pct=parseInt(_eq_m[1]);
              var _eq_side=_eq_m[2]; /* favorite or underdog */
              var _won=_ft.indexOf('WON')>=0;
              /* Multiway-aware classification: use fair share as midpoint.
                 HU fair=50 → flip=42-58. 3-way fair=33 → flip=25-41.
                 data-n-allin on the equity span carries the player count. */
              var _nAllin=2;
              var _eqSpan=_footText.querySelector('[data-n-allin]');
              if(_eqSpan)_nAllin=parseInt(_eqSpan.getAttribute('data-n-allin'))||2;
              var _fairShare=Math.round(100/_nAllin);
              var _flipLo=_fairShare-8;
              var _flipHi=_fairShare+8;
              /* Classify: equity + result + multiway thresholds */
              if(_eq_side==='favorite'&&!_won&&_luck_m)
                _hverdict='Suckout ('+_eq_pct+'% fav)';
              else if(_eq_side==='underdog'&&_won&&_luck_m)
                _hverdict='Got lucky ('+_eq_pct+'%)';
              else if(_eq_pct>=_flipLo&&_eq_pct<=_flipHi)
                _hverdict='Flip ('+_eq_pct+'%'+ (_nAllin>2?' '+_nAllin+'-way':'')+')';
              else if(_eq_pct>_flipHi)
                _hverdict='Ahead ('+_eq_pct+'%)';
              else
                _hverdict='Behind ('+_eq_pct+'%)';
            }
          }
        }
        /* d. Analyst notes yellow block — look for verdict keywords */
        if(!_hverdict){
          var _notes=art.querySelector('.analyst-notes');
          if(_notes){
            var _nt=_notes.textContent||'';
            var _nvm=_nt.match(/(I{1,3}\.\d\S*\s+\w[\w\s-]*?)[\.\—\n]/);
            if(_nvm)_hverdict=_nvm[1].trim();
          }
        }
      }

      var row=document.createElement('tr');
      /* Hand pill — always clickable */
      var hc=document.createElement('td');
      hc.setAttribute('data-label','Hand');
      var pill=document.querySelector('a.hand-ref[data-hand-id="'+hid+'"]');
      if(pill){hc.appendChild(pill.cloneNode(true));}
      else{
        var newPill=document.createElement('a');
        newPill.className='hand-ref';
        newPill.setAttribute('data-hand-id',hid);
        newPill.href='#sec-app-hand-'+hid;
        newPill.textContent=hid;
        newPill.style.cursor='pointer';
        hc.appendChild(newPill);
      }
      row.appendChild(hc);
      /* Position */
      var pc=document.createElement('td');
      pc.setAttribute('data-label',_posHeader);
      pc.textContent=_hpos;
      row.appendChild(pc);
      /* Cards — use innerHTML to preserve card-suit coloring */
      var cc=document.createElement('td');
      cc.setAttribute('data-label','Cards');
      if(_hcards){cc.innerHTML=_hcards;}
      row.appendChild(cc);
      /* Net */
      var nc=document.createElement('td');
      nc.setAttribute('data-label','Net');
      nc.textContent=_hnet;
      if(_hnet&&_hnet.indexOf('-')===0)nc.style.color='var(--bad)';
      else if(_hnet&&_hnet.indexOf('+')===0)nc.style.color='var(--good)';
      row.appendChild(nc);
      /* Verdict — with emoji mapping and user review as additive */
      var vc=document.createElement('td');
      vc.setAttribute('data-label','Verdict');
      vc.style.fontSize='0.85em';vc.style.color='#64748b';
      /* Map roman numeral verdicts to emoji + human label */
      var _emojiMap={
        'I.7':'🧊 Cooler','III.0':'✅ Cleared','III.1':'👎 Punt',
        'III.2':'👎 Mistake','III.3':'✅ Cleared','III.4':'🤔 Read-dep',
        'III.5':'🎲 Justified','III.8':'🎯 Pick'};
      var _displayVerdict=_hverdict||'';
      if(_displayVerdict){
        /* Replace leading roman prefix with emoji */
        var _vm2=_displayVerdict.match(/^(I{1,3}\.\d+)\s*(.*)/);
        if(_vm2&&_emojiMap[_vm2[1]]){
          _displayVerdict=_emojiMap[_vm2[1]]+(_vm2[2]?' — '+_vm2[2]:'');
        }else{
          /* v8.12.9 policy: Roman codes never reach the user — strip any
             unmapped prefix and keep the plain-language label. */
          _displayVerdict=_displayVerdict.replace(/^[IVX]+\.\d+\s*/,'');
        }
      }
      if(_displayVerdict)vc.textContent=_displayVerdict;
      else vc.textContent='⚪ not individually reviewed';
      /* Check localStorage for user review — ADDITIVE, not override */
      try{var rk2='pokerbot:handreview:'+_reportDate+':'+hid;
        var rd2=JSON.parse(sessionStorage.getItem(rk2)||localStorage.getItem(rk2)||'null');
        if(rd2&&rd2.status){
          /* Append user review after analyst verdict, don't replace */
          var _userBadge=' ['+rd2.status+']';
          if(_displayVerdict)vc.textContent=_displayVerdict+_userBadge;
          else vc.textContent=rd2.status;
        }
      }catch(e){}
      row.appendChild(vc);
      tbl.appendChild(row);
    });
    var shell=document.createElement('div');shell.className='table-shell';
    var scroll=document.createElement('div');scroll.className='table-scroll';
    scroll.appendChild(tbl);shell.appendChild(scroll);
    body.appendChild(shell);
    var titleEl=document.getElementById('list-modal-title');
    /* v8.8.6 HA Phase 2: header count — "N hands · M openable" */
    var _unavail=hids.length-_shownCount;
    var _countTxt=' ('+hids.length+' hand'+(hids.length!==1?'s':'')+
      (_unavail>0?' · '+_shownCount+' openable':'')+ ')';
    titleEl.textContent=title+_countTxt;
    if(window.PBReview&&window.PBReview.coverage&&hids.length){
      var _pcov=window.PBReview.coverage(hids.join(','));
      titleEl.insertAdjacentHTML('beforeend','<span class="list-review-summary">'+pbReviewPillHTML(_pcov,{compact:false})+'</span>');
    }
    var modal=document.getElementById('list-modal');
    modal.setAttribute('aria-hidden','false');
    modal.classList.add('is-open');
    document.body.style.overflow='hidden';
    _listOpen=true;
    return true;
  }
  /* ==== v8.12.0 R1: PB payload codec (single decode path) ==============
     Payloads are emitted as deflate-raw+base64 entries in window.PB_PAYLOADS
     (see _helpers.pb_payload_js). Native DecompressionStream('deflate-raw')
     with an embedded tiny-inflate fallback (port of Joergen Ibsen's tinf,
     MIT). Decode is eager (kick below) so the sync modal builders read the
     materialized globals exactly as before; the three villain entry points
     also await PBData.ready() as a hard guard. Decode failure shows a
     visible banner — never silent. */
  var PBInflateFallback=(function(){
    function Tree(){this.t=new Uint16Array(16);this.trans=new Uint16Array(288);}
    var sltree=new Tree(),sdtree=new Tree();
    var length_bits=new Uint8Array(30),length_base=new Uint16Array(30);
    var dist_bits=new Uint8Array(30),dist_base=new Uint16Array(30);
    var clcidx=new Uint8Array([16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15]);
    function build_bits_base(bits,base,delta,first){var i,sum;
      for(i=0;i<delta;i++)bits[i]=0;
      for(i=0;i<30-delta;i++)bits[i+delta]=(i/delta)|0;
      for(sum=first,i=0;i<30;i++){base[i]=sum;sum+=1<<bits[i];}}
    build_bits_base(length_bits,length_base,4,3);
    build_bits_base(dist_bits,dist_base,2,1);
    length_bits[28]=0;length_base[28]=258;
    (function(){var i;
      for(i=0;i<16;i++)sltree.t[i]=0;
      sltree.t[7]=24;sltree.t[8]=152;sltree.t[9]=112;
      for(i=0;i<24;i++)sltree.trans[i]=256+i;
      for(i=0;i<144;i++)sltree.trans[24+i]=i;
      for(i=0;i<8;i++)sltree.trans[24+144+i]=280+i;
      for(i=0;i<112;i++)sltree.trans[24+144+8+i]=144+i;
      for(i=0;i<16;i++)sdtree.t[i]=0;
      sdtree.t[5]=30;
      for(i=0;i<30;i++)sdtree.trans[i]=i;})();
    function build_tree(t,lengths,off,num){var offs=new Uint16Array(16),i,sum;
      for(i=0;i<16;i++)t.t[i]=0;
      for(i=0;i<num;i++)t.t[lengths[off+i]]++;
      t.t[0]=0;
      for(sum=0,i=0;i<16;i++){offs[i]=sum;sum+=t.t[i];}
      for(i=0;i<num;i++)if(lengths[off+i])t.trans[offs[lengths[off+i]]++]=i;}
    function Data(src){this.s=src;this.i=0;this.tag=0;this.bitcount=0;
      this.dest=[];this.lt=new Tree();this.dt=new Tree();}
    function read_bits(d,num,base){if(!num)return base;
      while(d.bitcount<24&&d.i<d.s.length){d.tag|=d.s[d.i++]<<d.bitcount;d.bitcount+=8;}
      var val=d.tag&(0xffff>>>(16-num));d.tag>>>=num;d.bitcount-=num;return val+base;}
    function decode_symbol(d,t){
      while(d.bitcount<24&&d.i<d.s.length){d.tag|=d.s[d.i++]<<d.bitcount;d.bitcount+=8;}
      var sum=0,cur=0,len=0,tag=d.tag;
      do{cur=2*cur+(tag&1);tag>>>=1;++len;sum+=t.t[len];cur-=t.t[len];}while(cur>=0);
      d.tag=tag;d.bitcount-=len;return t.trans[sum+cur];}
    function decode_trees(d,lt,dt){var hlit,hdist,hclen,i,num,length;
      hlit=read_bits(d,5,257);hdist=read_bits(d,5,1);hclen=read_bits(d,4,4);
      var code_tree=new Tree();var lengths=new Uint8Array(19);
      for(i=0;i<hclen;i++)lengths[clcidx[i]]=read_bits(d,3,0);
      build_tree(code_tree,lengths,0,19);
      var lens=new Uint8Array(288+32);
      for(num=0;num<hlit+hdist;){var sym=decode_symbol(d,code_tree);
        if(sym===16){var prev=lens[num-1];for(length=read_bits(d,2,3);length;length--)lens[num++]=prev;}
        else if(sym===17){for(length=read_bits(d,3,3);length;length--)lens[num++]=0;}
        else if(sym===18){for(length=read_bits(d,7,11);length;length--)lens[num++]=0;}
        else{lens[num++]=sym;}}
      build_tree(lt,lens,0,hlit);build_tree(dt,lens,hlit,hdist);}
    function inflate_block_data(d,lt,dt){
      for(;;){var sym=decode_symbol(d,lt);
        if(sym===256)return;
        if(sym<256){d.dest.push(sym);}
        else{sym-=257;
          var length=read_bits(d,length_bits[sym],length_base[sym]);
          var distsym=decode_symbol(d,dt);
          var offs=d.dest.length-read_bits(d,dist_bits[distsym],dist_base[distsym]);
          for(var i=offs;i<offs+length;i++)d.dest.push(d.dest[i]);}}}
    function inflate_uncompressed_block(d){
      while(d.bitcount>=8){d.i--;d.bitcount-=8;}
      d.bitcount=0;d.tag=0;
      var length=256*d.s[d.i+1]+d.s[d.i];
      var invlength=256*d.s[d.i+3]+d.s[d.i+2];
      if(length!==((~invlength)&0xffff))throw new Error('stored block integrity');
      d.i+=4;
      for(var i=length;i;i--)d.dest.push(d.s[d.i++]);}
    function inflateToBytes(src){var d=new Data(src);var bfinal,btype;
      do{bfinal=read_bits(d,1,0);btype=read_bits(d,2,0);
        if(btype===0)inflate_uncompressed_block(d);
        else if(btype===1)inflate_block_data(d,sltree,sdtree);
        else if(btype===2){decode_trees(d,d.lt,d.dt);inflate_block_data(d,d.lt,d.dt);}
        else throw new Error('bad deflate block type '+btype);
      }while(!bfinal);
      return new Uint8Array(d.dest);}
    function inflateToString(bytes){var out=inflateToBytes(bytes);
      if(typeof TextDecoder!=='undefined')return new TextDecoder('utf-8').decode(out);
      var s='';for(var i=0;i<out.length;i+=8192)
        s+=String.fromCharCode.apply(null,out.subarray(i,i+8192));
      return decodeURIComponent(escape(s));}
    return {inflateToBytes:inflateToBytes,inflateToString:inflateToString};
  })();
  async function _pbInflateRawB64(b64){
    var bin=atob(b64);var bytes=new Uint8Array(bin.length);
    for(var i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
    if(typeof DecompressionStream!=='undefined'){
      try{
        var st=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
        return await new Response(st).text();
      }catch(e){console.error('[PB] native inflate failed — using fallback',e);}
    }
    return PBInflateFallback.inflateToString(bytes);
  }
  var PBData=(function(){
    var cache={};var pending={};var readyP=null;
    function _banner(msg){
      try{
        var el=document.getElementById('pb-decode-error');
        if(!el){el=document.createElement('div');el.id='pb-decode-error';
          el.style.cssText='position:fixed;bottom:8px;left:8px;background:#fef2f2;color:#991b1b;border:1px solid #fecaca;padding:6px 10px;border-radius:6px;font-size:12px;z-index:99999;';
          if(document.body)document.body.appendChild(el);}
        el.textContent=msg;
      }catch(e){}
    }
    function decodeJson(name){
      if(cache[name])return Promise.resolve(cache[name]);
      if(pending[name])return pending[name];
      var reg=(window.PB_PAYLOADS||{})[name];
      if(!reg){console.error('[PB] payload not registered: '+name);return Promise.resolve(null);}
      if(reg.encoding!=='deflate-raw+base64'||reg.version!==1){
        console.error('[PB] unknown encoding/version for '+name);return Promise.resolve(null);}
      var pr=_pbInflateRawB64(reg.data).then(function(txt){
        var obj=JSON.parse(txt);
        if(reg.itemCount!=null){
          var n=Object.keys(obj).length;
          if(n!==reg.itemCount)console.error('[PB] '+name+' itemCount mismatch: decoded '+n+' expected '+reg.itemCount);
        }
        cache[name]=obj;delete pending[name];return obj;
      }).catch(function(e){
        delete pending[name];
        console.error('[PB] decode FAILED for '+name,e);
        _banner('Data decode failed ('+name+') — some popups may be empty. See console.');
        return null;
      });
      pending[name]=pr;return pr;
    }
    function ready(){
      if(readyP)return readyP;
      var reg=window.PB_PAYLOADS||{};
      if(!reg.villainIntel&&!reg.handOpponentContexts){
        return new Promise(function(res){
          var f=function(){res(ready());};
          if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',f);
          else setTimeout(f,80);
        });
      }
      readyP=Promise.all([decodeJson('villainIntel'),decodeJson('handOpponentContexts')])
        .then(function(vals){
          var vi=vals[0]||{};var hoc=vals[1]||{};
          try{
            Object.defineProperty(window,'villainIntel',{value:vi,writable:true,configurable:true});
            Object.defineProperty(window,'handOpponentContexts',{value:hoc,writable:true,configurable:true});
          }catch(e){window.villainIntel=vi;window.handOpponentContexts=hoc;}
          return {villainIntel:vi,handOpponentContexts:hoc};
        });
      return readyP;
    }
    return {decodeJson:decodeJson,ready:ready,
      villainIntel:function(){return ready().then(function(r){return r.villainIntel;});},
      handOpponentContexts:function(){return ready().then(function(r){return r.handOpponentContexts;});}};
  })();
  (function(){
    /* dev-trap: direct global reads before decode resolve are loud and
       return an empty object. PBData.ready() replaces the traps with the
       materialized objects, so all existing sync code reads real data. */
    function trap(name){
      try{Object.defineProperty(window,name,{configurable:true,
        get:function(){console.error('[PB] direct window.'+name+' read before PBData.ready() resolved — returning empty object');return {};},
        set:function(v){Object.defineProperty(window,name,{value:v,writable:true,configurable:true});}});
      }catch(e){}
    }
    trap('villainIntel');trap('handOpponentContexts');
    if(document.readyState==='loading'){
      document.addEventListener('DOMContentLoaded',function(){PBData.ready();});
    }else{setTimeout(function(){PBData.ready();},0);}
  })();
  /* ==== v8.12.1 R3: PBLazy — flag-gated lazy hand cards ============== */
  var PBLazy=(function(){
    var matDone={};
    /* v8.12.5 (QA leftover): payload keys are SHORT ids ('41017558') but
       count-cell popup rows pass FULL TM-form ids ('TM6041017558'). _swap
       looked up map[hid] RAW, returned false, and openHand's try/catch
       swallowed it -> silent dead click on every TM-form caller. Normalize
       once here, for the map lookup, the placeholder selector and the
       matDone cache alike. */
    function _norm(hid){
      hid=String(hid||'');
      if(window.normalizeHandId){try{return normalizeHandId(hid);}catch(e){}}
      var m=hid.match(/(\d{8})$/);
      return m?m[1]:hid.replace(/^TM/,'');
    }
    function has(hid){
      var reg=window.PB_PAYLOADS||{};
      return !!reg.lazyHands && !matDone[_norm(hid)];
    }
    function _swap(hid,map){
      hid=_norm(hid);
      if(matDone[hid])return true;
      var seg=map&&map[hid];
      if(!seg)return false;
      var ph=document.querySelector(".hand-detail-card.pb-lazy[data-hand-id='"+hid+"']");
      if(!ph){matDone[hid]=true;return true;}
      var tmp=document.createElement('div');
      tmp.innerHTML=seg;
      var art=tmp.firstElementChild;
      if(!art)return false;
      ph.parentNode.replaceChild(art,ph);
      matDone[hid]=true;
      try{document.dispatchEvent(new CustomEvent('pb-lazy-done',{detail:{handId:hid,el:art}}));}catch(e){}
      return true;
    }
    async function ensure(hid){
      if(!(window.PB_PAYLOADS||{}).lazyHands)return false;
      if(matDone[_norm(hid)])return true;
      var map=await PBData.decodeJson('lazyHands');
      return _swap(hid,map||{});
    }
    async function ensureAll(btn){
      if(!(window.PB_PAYLOADS||{}).lazyHands)return;
      if(btn){btn.disabled=true;btn.textContent='Loading all hands…';}
      var map=await PBData.decodeJson('lazyHands')||{};
      var ids=Object.keys(map);
      for(var i=0;i<ids.length;i++){
        _swap(ids[i],map);
        if(btn&&i%50===0)btn.textContent='Loading… '+i+'/'+ids.length;
        /* v8.12.5: yield to the event loop — with 1800+ hands a single
           blocking loop froze the page for ~8s; chunked it stays alive
           and the progress label actually paints. */
        if(i%100===99)await new Promise(function(r){setTimeout(r,0);});
      }
      if(btn){btn.textContent='All hands loaded';}
    }
    window.addEventListener('beforeprint',function(){ensureAll(document.getElementById('pb-expand-all'));});
    /* v8.12.8 QA: shared hash handler + INITIAL-LOAD materialization —
       hashchange never fires for a deep link present at load time, so
       #sec-app-hand-X arrivals stayed un-materialized. After ensure(),
       re-scroll if the anchor only just entered the DOM. */
    function _hashEnsure(){
      var m=(location.hash||'').match(/^#sec-app-hand-(.+)$/);
      if(!m)return;
      var id='sec-app-hand-'+_norm(m[1]);
      var p=ensure(m[1]);
      if(p&&p.then)p.then(function(){
        var el=document.getElementById(id);
        /* always re-scroll: same-page hash navigation and big-document
           layout shifts both defeat the browser's native anchor scroll.
           behavior MUST be 'instant' — the stylesheet's
           scroll-behavior:smooth makes default scrolls animate across a
           ~65k-px lazy document and Chrome aborts them on the layout
           shifts that materialization itself causes. */
        if(el){try{el.scrollIntoView({behavior:'instant',block:'start'});}
               catch(e){el.scrollIntoView();}}
      });
    }
    window.addEventListener('hashchange',_hashEnsure);
    if(document.readyState==='loading'){
      document.addEventListener('DOMContentLoaded',_hashEnsure);
    }else{_hashEnsure();}
    return {has:has,ensure:ensure,ensureAll:ensureAll};
  })();
  window.PBLazy=PBLazy;  /* onclick handlers + openHand guard reference window.PBLazy */
  /* v8.12.2 Phase-C: delegated villain-mini clicks (replaces ~1,100
     inline onclick attrs; also covers lazily materialized cards). */
  document.addEventListener('click',function(e){
    var vm=e.target.closest&&e.target.closest('.villain-mini[data-vk]');
    if(vm){showVillainMiniCard(vm.getAttribute('data-vk'),vm);}
  });
  /* v8.12.2 Phase-C: static tooltip classes -> title attrs at load */
  function _pbFillTitles(root){
    (root||document).querySelectorAll('.pb-tt1').forEach(function(el){
      if(!el.title)el.title='No analyst note \u2014 standard play';});
    (root||document).querySelectorAll('.pb-tt2').forEach(function(el){
      if(!el.title)el.title='Not the flagged decision \u2014 see note';});
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',function(){_pbFillTitles();});
  }else{_pbFillTitles();}
  document.addEventListener('pb-lazy-done',function(e){
    if(e.detail&&e.detail.el)_pbFillTitles(e.detail.el);
  });
  window.PBData=PBData;  /* debug/QA access */
  /* ---- v8.7.0: Villain evidence popup (UX wiring fix: single braces for raw string) ---- */
  /* v8.12.0 R1: villainIntel decodes via PBData (init guard removed). */
  async function openVillainEvidence(villainKey){
    var _viMap=await PBData.villainIntel();
    var intel=_viMap[villainKey];
    if(!intel){return false;}
    var alias=intel.alias||'?';
    var vnum=intel.v_number||'?';
    var archetype=intel.archetype_label||intel.archetype||'';
    var emoji=intel.archetype_emoji||'';
    var conf=intel.confidence||'';
    var nEvidence=intel.n_evidence||0;
    var atoms=intel.evidence_atoms||[];
    var body=document.getElementById('ve-modal-body');
    body.innerHTML='';
    /* Compute reviewable/evidence-only counts */
    var atomHids={};
    atoms.forEach(function(a){
      var nid=window.normalizeHandId?normalizeHandId(a.hand_id):a.hand_id;
      atomHids[nid]=1;
    });
    var allHids=Object.keys(atomHids);
    var nReviewable=allHids.filter(function(id){return _isReviewable(id);}).length;
    var nEvidenceOnly=allHids.length-nReviewable;
    /* Header */
    var hdr=document.createElement('div');
    hdr.className='ve-header';
    hdr.innerHTML='<div class="ve-header-icon">'+emoji+'</div>'
      +'<div class="ve-header-info">'
      +'<h4>'+alias+' · '+vnum+'</h4>'
      +'<p>'+archetype+(conf?' · '+conf+' conf':'')+' · '+nEvidence+' evidence hands'
      +' · '+nReviewable+' reviewable · '+nEvidenceOnly+' evidence-only</p>'
      +'</div>';
    body.appendChild(hdr);
    /* Filters */
    var fbar=document.createElement('div');
    fbar.className='ve-filters';
    ['All','Notes','Pivots','Misses','Hero involved'].forEach(function(lbl){
      var btn=document.createElement('span');
      btn.className='ve-filter'+(lbl==='All'?' active':'');
      btn.textContent=lbl;
      btn.onclick=function(){
        fbar.querySelectorAll('.ve-filter').forEach(function(b){b.classList.remove('active');});
        btn.classList.add('active');
        filterVillainEvidence(body,lbl.toLowerCase(),atoms,alias,villainKey);
      };
      fbar.appendChild(btn);
    });
    body.appendChild(fbar);
    /* Table */
    buildVillainEvidenceTable(body,atoms,'all',alias,villainKey);
    /* Show modal */
    var titleEl=document.getElementById('ve-modal-title');
    titleEl.textContent='Villain Evidence: '+alias+' · '+vnum+' ('+nEvidence+')';
    var modal=document.getElementById('villain-evidence-modal');
    modal.setAttribute('aria-hidden','false');
    modal.classList.add('is-open');
    document.body.style.overflow='hidden';
    return true;
  }
  window.openVillainEvidence=openVillainEvidence;
  function buildVillainEvidenceTable(container,atoms,filter,alias,villainKey){
    var old=container.querySelector('.ve-table-shell');
    if(old)old.remove();
    var shell=document.createElement('div');
    shell.className='table-shell ve-table-shell';
    var tbl=document.createElement('table');
    tbl.className='data-table';
    tbl.innerHTML='<tr><th>Hand</th><th>Street</th><th>V Pos</th><th>Hero?</th>'
      +'<th>Signal</th><th>Evidence</th><th>Read Impact</th><th>Detail</th></tr>';
    var shown=0;
    var totalAtoms=atoms.length;
    /* Teaching-first ordering (Step 2 / Option B): surface the most instructive
       cues first (miss > good > pivot > note), STABLE within a badge. Reversible
       + contained — a local sorted copy only; the original `atoms` array (and the
       raw-evidence fallback passed to openHandFromEvidence) is untouched. */
    var _veOrd={miss:0,good:1,pivot:2,note:3};
    var _veAtoms=atoms.map(function(a,i){return [a,i];});
    _veAtoms.sort(function(x,y){
      var dx=(_veOrd[x[0].badge]==null?4:_veOrd[x[0].badge]);
      var dy=(_veOrd[y[0].badge]==null?4:_veOrd[y[0].badge]);
      return dx!==dy?dx-dy:x[1]-y[1];
    });
    _veAtoms=_veAtoms.map(function(p){return p[0];});
    _veAtoms.forEach(function(a){
      if(filter!=='all'){
        if(filter==='notes' && a.badge!=='note')return;
        if(filter==='pivots' && a.badge!=='pivot')return;
        if(filter==='misses' && a.badge!=='miss')return;
        if(filter==='hero involved' && !a.hero_involved)return;
      }
      var hid=window.normalizeHandId?window.normalizeHandId(a.hand_id):a.hand_id;
      var isRev=_isReviewable(hid);
      var tr=document.createElement('tr');
      var td0=document.createElement('td');
      if(isRev){
        var link=document.createElement('a');
        link.href='#';link.textContent=hid;
        link.onclick=function(){openHandFromEvidence(hid,alias||'',atoms,villainKey);return false;};
        td0.appendChild(link);
      }else{
        td0.textContent=hid;td0.style.color='#94a3b8';
      }
      tr.innerHTML='<td></td>'
        +'<td>'+a.street+'</td>'
        +'<td>'+(a.villain_position||'')+'</td>'
        +'<td>'+(a.hero_involved?'✔':'')+'</td>'
        +'<td><span class="ve-signal '+a.badge+'">'+(a.label||'')
        +(a.signal_label?' · '+a.signal_label:'')+'</span></td>'
        +'<td>'+a.evidence_text+'</td>'
        +'<td>'+a.read_impact+'</td>'
        +'<td style="font-size:11px;color:'+(isRev?'#1e40af':'#94a3b8')+'">'
        +(isRev?'Open hand':'Evidence only')+'</td>';
      tr.replaceChild(td0,tr.firstChild);
      tbl.appendChild(tr);
      shown++;
    });
    if(shown===0){
      var tr=document.createElement('tr');
      tr.innerHTML='<td colspan="8" style="text-align:center;color:#94a3b8;padding:20px">'
        +(totalAtoms>0?'No matches for this filter.':'No villain evidence captured yet.')+'</td>';
      tbl.appendChild(tr);
    }
    shell.appendChild(tbl);
    container.appendChild(shell);
  }
  function filterVillainEvidence(container,filter,atoms,alias,villainKey){
    buildVillainEvidenceTable(container,atoms,filter,alias,villainKey);
  }
  function closeVillainEvidence(){
    var modal=document.getElementById('villain-evidence-modal');
    if(modal){modal.setAttribute('aria-hidden','true');modal.classList.remove('is-open');}
    document.body.style.overflow='';
  }
  window.closeVillainEvidence=closeVillainEvidence;
  /* v8.7.0: open hand from evidence popup with queue context */
  function openHandFromEvidence(hid, alias, atoms, villainKey){
    var handIds=atoms.map(function(a){return window.normalizeHandId?window.normalizeHandId(a.hand_id):a.hand_id;});
    var uniqueIds=[]; var seen={};
    handIds.forEach(function(id){if(!seen[id]){seen[id]=1;uniqueIds.push(id);}});
    var idx=uniqueIds.indexOf(hid);
    if(idx<0)idx=0;
    /* v8.7.2: build per-hand reasons from evidence atoms */
    var reasons={};
    atoms.forEach(function(a){
      var nid=window.normalizeHandId?window.normalizeHandId(a.hand_id):a.hand_id;
      var r=(a.villain_alias||alias)+': '+(a.signal_label||a.label||'')+' — '+(a.evidence_text||'');
      if(reasons[nid]){reasons[nid]+='; '+r;}else{reasons[nid]=r;}
    });
    window.activeHandQueue={
      contextId:'villain_evidence_'+alias,
      contextTitle:'Villain Evidence: '+alias,
      sourceType:'villain_evidence',
      sourcePath:alias,
      villainKey:villainKey||'',
      handIds:uniqueIds,
      currentIndex:idx,
      reasonByHand:reasons,
      viewed:{}
    };
    closeVillainEvidence();
    if(window.openHand)window.openHand(hid);
  }
  window.openHandFromEvidence=openHandFromEvidence;
  /* v8.7.0: mini-card on villain alias click */
  async function showVillainMiniCard(villainKey, anchorEl){
    var _viMap2=await PBData.villainIntel();
    var intel=_viMap2[villainKey];
    if(!intel)return;
    var existing=document.getElementById('villain-minicard');
    if(existing)existing.remove();
    var card=document.createElement('div');
    card.id='villain-minicard';
    card.className='villain-minicard';
    var dispAlias=intel.alias||'?';
    var dispVnum=intel.v_number||'?';
    var dispName=(dispAlias===dispVnum)?dispAlias:(dispAlias+' · '+dispVnum);
    card.innerHTML='<div style="font-weight:900;font-size:14px">'+
      (intel.archetype_emoji||'')+' '+dispName+'</div>'+
      '<div style="font-size:12px;color:#475467">'+(intel.archetype_label||'Read building')+
      (intel.confidence?' · '+intel.confidence:'')+
      ' · '+(intel.n_evidence||0)+' evidence</div>'+
      '<div style="margin-top:6px"><span class="facing-action" onclick="openVillainEvidence(\''+
      villainKey+'\');var mc=document.getElementById(\'villain-minicard\');if(mc)mc.remove();">'+
      'Open evidence</span></div>';
    // Position near anchor
    var rect=anchorEl.getBoundingClientRect();
    card.style.position='fixed';
    card.style.left=Math.min(rect.left,window.innerWidth-220)+'px';
    card.style.top=(rect.bottom+4)+'px';
    document.body.appendChild(card);
    // Close on outside click — use subtree check to avoid race
    setTimeout(function(){
      document.addEventListener('click',function _mc(e){
        if(!card.contains(e.target)&&!anchorEl.contains(e.target)){
          card.remove();document.removeEventListener('click',_mc);
        }
      });
    },0);
  }
  window.showVillainMiniCard=showVillainMiniCard;
  /* Close villain evidence modal on close button / backdrop */
  document.addEventListener('click',function(e){
    if(e.target.id==='ve-modal-close'||e.target.classList.contains('ve-backdrop')){
      closeVillainEvidence();
    }
  });
  /* v8.7.3: read-level evidence drilldown from Matrix */
  /* Build set of appendix hand IDs for reviewable detection */
  var _appendixIds=new Set();
  document.querySelectorAll('article.hand-detail-card[data-hand-id]').forEach(function(el){
    _appendixIds.add(el.getAttribute('data-hand-id'));
  });
  /* Also index by sec-app-hand- anchors */
  document.querySelectorAll('[id^="sec-app-hand-"]').forEach(function(el){
    _appendixIds.add(el.id.replace('sec-app-hand-',''));
  });
  function _isReviewable(hid){return _appendixIds.has(hid);}

  /* v8.8.0: exploit opportunity drilldown from Matrix */
  window.exploitOpportunities=window.exploitOpportunities||[];
  function openExploitDrilldown(readLabel,filterType){
    var allExp=window.exploitOpportunities||[];
    var filtered=allExp.filter(function(e){
      return e.read_label===readLabel;
    });
    if(filterType==='missed'){
      filtered=filtered.filter(function(e){
        return e.auto_verdict==='missed_exploit'||e.badge==='miss';
      });
    }
    if(filterType==='good'){
      filtered=filtered.filter(function(e){
        return e.auto_verdict==='good_exploit'||e.badge==='good';
      });
    }
    if(!filtered.length){return;}
    /* v8.17 Epic 3: count-of-one opens the single hand directly (0 muted /
       1 direct open / >1 popup), mirroring the PKO aggregate behavior. A lone
       reviewable example needs no intermediate one-row table. */
    var _revFiltered=filtered.filter(function(e){
      return _isReviewable(window.normalizeHandId?window.normalizeHandId(e.hand_id):e.hand_id);
    });
    if(_revFiltered.length===1){
      var _solo=window.normalizeHandId?window.normalizeHandId(_revFiltered[0].hand_id):_revFiltered[0].hand_id;
      openHandFromExploitDrilldown(_solo,readLabel,filterType,filtered);
      return;
    }
    var body=document.getElementById('ve-modal-body');
    body.innerHTML='';
    var title=filterType==='missed'
      ?'Missed Exploits — '+readLabel+' ('+filtered.length+')'
      :filterType==='good'
      ?'Good Exploits — '+readLabel+' ('+filtered.length+')'
      :'Exploit Opportunities — '+readLabel+' ('+filtered.length+')';
    /* Header */
    var hdr=document.createElement('div');
    hdr.className='ve-header';
    var missed=filtered.filter(function(e){return e.badge==='miss';}).length;
    var good=filtered.filter(function(e){return e.badge==='good';}).length;
    var reviewable=filtered.filter(function(e){
      return _isReviewable(normalizeHandId(e.hand_id));
    }).length;
    var evidenceOnly=filtered.length-reviewable;
    hdr.innerHTML='<div class="ve-header-info" style="width:100%">'
      +'<h4>'+title+'</h4>'
      +'<p style="font-size:12px;color:#475467">'+filtered.length+' opportunities'
      +(missed?' · '+missed+' missed':'')
      +(good?' · '+good+' good':'')
      +(reviewable?' · '+reviewable+' reviewable':'')
      +(evidenceOnly?' · '+evidenceOnly+' evidence-only':'')+'</p>'
      +'</div>';
    body.appendChild(hdr);
    /* Table */
    var shell=document.createElement('div');
    shell.className='table-shell ve-table-shell';
    var tbl=document.createElement('table');
    tbl.className='data-table';
    tbl.innerHTML='<tr><th>Hand</th><th>Villain</th><th>Street</th><th>Hero Action</th>'
      +'<th>Read</th><th>Verdict</th><th>Opportunity</th><th>Recommended</th>'
      +'<th>Sev</th><th>Detail</th></tr>';
    filtered.forEach(function(e){
      var hid=window.normalizeHandId?window.normalizeHandId(e.hand_id):e.hand_id;
      var isRev=_isReviewable(hid);
      var tr=document.createElement('tr');
      var td0=document.createElement('td');
      if(isRev){
        var link=document.createElement('a');
        link.href='#';link.textContent=hid;
        link.onclick=function(){
          openHandFromExploitDrilldown(hid,readLabel,filterType,filtered);
          return false;
        };
        td0.appendChild(link);
      }else{
        td0.textContent=hid;td0.style.color='#94a3b8';
      }
      var valias=(e.villain_alias||'')+(e.v_number?' · '+e.v_number:'');
      tr.innerHTML='<td></td>'
        +'<td>'+valias+'</td>'
        +'<td>'+(e.hero_decision_street||'')+'</td>'
        +'<td>'+(e.hero_action||'')+'</td>'
        +'<td>'+(e.villain_read_before_decision||'')+'</td>'
        +'<td><span class="ve-signal '+(e.badge||'')+'">'+(e.label||'')+'</span></td>'
        +'<td style="font-size:12px">'+(e.evidence_text||'')
        +(e.assumption_source?'<div style="margin-top:4px;font-size:11px;color:#6b7280">'
        +'<span class="assumption-conf '+(e.assumption_confidence||'')+'" style="display:inline-block;border-radius:3px;padding:1px 5px;margin-right:4px;font-weight:600;font-size:10px;'
        +(e.assumption_confidence==='high'?'background:#dcfce7;color:#166534;border:1px solid #86efac'
        :e.assumption_confidence==='medium'?'background:#fef3c7;color:#92400e;border:1px solid #fcd34d'
        :'background:#fee2e2;color:#991b1b;border:1px solid #fca5a5')
        +'">'+((e.assumption_confidence||'').toUpperCase())+'</span>'
        +e.assumption_source+'</div>':'')
        +'</td>'
        +'<td style="font-size:12px">'+(e.recommended_exploit||'')+'</td>'
        +'<td>'+(e.severity||'')+'</td>'
        +'<td style="font-size:11px;color:'+(isRev?'#1e40af':'#94a3b8')+'">'
        +(isRev?'Open hand':'Evidence only')+'</td>';
      tr.replaceChild(td0,tr.firstChild);
      tbl.appendChild(tr);
    });
    shell.appendChild(tbl);
    body.appendChild(shell);
    var titleEl=document.getElementById('ve-modal-title');
    titleEl.textContent=title;
    var modal=document.getElementById('villain-evidence-modal');
    modal.setAttribute('aria-hidden','false');
    modal.classList.add('is-open');
    document.body.style.overflow='hidden';
  }
  window.openExploitDrilldown=openExploitDrilldown;
  function openHandFromExploitDrilldown(hid,readLabel,filterType,exploits){
    var handIds=exploits.map(function(e){
      return window.normalizeHandId?window.normalizeHandId(e.hand_id):e.hand_id;
    });
    var uniqueIds=[];var seen={};
    handIds.forEach(function(id){if(!seen[id]){seen[id]=1;uniqueIds.push(id);}});
    var reviewableIds=uniqueIds.filter(function(id){return _isReviewable(id);});
    if(!reviewableIds.length)reviewableIds=uniqueIds;
    var idx=reviewableIds.indexOf(hid);if(idx<0)idx=0;
    var reasons={};
    exploits.forEach(function(e){
      var nid=window.normalizeHandId?window.normalizeHandId(e.hand_id):e.hand_id;
      var r=(filterType==='missed'?'Missed exploit':'Exploit opportunity')
        +' vs '+readLabel+' — '+(e.hero_action||'')
        +'. Recommended: '+(e.recommended_exploit||'');
      reasons[nid]=r;
    });
    var qTitle=filterType==='missed'
      ?'Opponent Exploit Queue: '+readLabel+' — missed exploits'
      :'Opponent Exploit Queue: '+readLabel+' — all opportunities';
    window.activeHandQueue={
      contextId:'exploit_'+readLabel.replace(/\s/g,'_')+'_'+filterType,
      contextTitle:qTitle,
      sourceType:'exploit_drilldown',
      sourcePath:readLabel,
      filterType:filterType,
      handIds:reviewableIds,
      currentIndex:idx,
      reasonByHand:reasons,
      viewed:{}
    };
    closeVillainEvidence();
    if(window.openHand)window.openHand(hid);
  }

  /* ---- v8.17 Epic 4: unified Tournament Results — sortable + row drilldown ---- */
  function _ttNum(v){
    var n=parseFloat(String(v==null?'':v).replace(/[^0-9.+-]/g,''));
    return isNaN(n)?null:n;
  }
  function _ttSort(tbl,th){
    var ci=parseInt(th.getAttribute('data-tt-sort'),10);
    var numeric=th.getAttribute('data-tt-num')==='1';
    var asc=th.getAttribute('data-tt-dir')!=='asc';
    var body=tbl.querySelector('tbody')||tbl;
    var rows=Array.prototype.slice.call(body.querySelectorAll('tr')).filter(function(r){
      return r.querySelector('td')&&!r.hasAttribute('data-tt-total');});
    var totals=Array.prototype.slice.call(body.querySelectorAll('tr[data-tt-total]'));
    Array.prototype.forEach.call(tbl.querySelectorAll('th[data-tt-sort]'),function(t){
      t.removeAttribute('data-tt-dir');
      t.textContent=t.textContent.replace(/ [▲▼]$/,'');});
    th.setAttribute('data-tt-dir',asc?'asc':'desc');
    th.textContent=th.textContent.replace(/ [▲▼]$/,'')+(asc?' ▲':' ▼');
    rows.sort(function(a,b){
      var ca=a.children[ci],cb=b.children[ci];
      var xa=ca?(ca.getAttribute('data-sort-value')!=null?ca.getAttribute('data-sort-value'):ca.textContent):'';
      var xb=cb?(cb.getAttribute('data-sort-value')!=null?cb.getAttribute('data-sort-value'):cb.textContent):'';
      var cmp;
      if(numeric){var na=_ttNum(xa),nb=_ttNum(xb);
        if(na==null&&nb==null)cmp=0;else if(na==null)cmp=-1;else if(nb==null)cmp=1;else cmp=na-nb;}
      else cmp=String(xa).trim().localeCompare(String(xb).trim());
      return asc?cmp:-cmp;});
    rows.forEach(function(r){body.appendChild(r);});
    totals.forEach(function(r){body.appendChild(r);});
  }
  function initTournamentResultsTable(){
    var tbl=document.getElementById('tt-unified-table');
    if(!tbl||tbl._ttSortWired)return; tbl._ttSortWired=true;
    Array.prototype.forEach.call(tbl.querySelectorAll('th[data-tt-sort]'),function(th){
      th.style.cursor='pointer'; th.title='Click to sort';
      th.addEventListener('click',function(){_ttSort(tbl,th);});});
  }
  window.initTournamentResultsTable=initTournamentResultsTable;
  function _ttEsc(s){var d=document.createElement('div');d.textContent=(s==null?'':String(s));return d.innerHTML;}
  function openTournamentDetail(eventId){
    var evs=window.tournamentEvents||[];
    var e=null;for(var i=0;i<evs.length;i++){if(evs[i].event_id===eventId){e=evs[i];break;}}
    if(!e)return false;
    var body=document.getElementById('ttd-modal-body');if(!body)return false;
    function row(k,v){if(v==null||v==='')return '';return '<div class="ttd-k">'+_ttEsc(k)+'</div><div class="ttd-v">'+_ttEsc(v)+'</div>';}
    var html='<div class="ttd-grid">';
    html+=row('Date',e.event_day);
    html+=row('Format',e.format);
    html+=row('Bullets',e.bullets+(e.entry_pattern==='multi_bullet'?' (re-entries)':''));
    html+=row('Buy-in',e.buy_in);
    html+=row('Invested',e.cost);
    html+=row('Finish',e.finish_txt);
    html+=row('Return',e.return_txt);
    html+=row('Net',e.net_txt);
    html+=row('ROI',e.roi_txt);
    html+=row('Status',e.status);
    html+='</div>';
    if(e.return_breakdown&&e.return_breakdown.length){
      html+='<h4 class="ttd-sub">Return breakdown</h4><ul class="ttd-list">';
      e.return_breakdown.forEach(function(b){html+='<li>'+_ttEsc(b)+'</li>';});
      html+='</ul>';}
    if(e.drivers&&e.drivers.length){
      html+='<h4 class="ttd-sub">Deep run &amp; stack arc</h4><ul class="ttd-list">';
      e.drivers.forEach(function(d){html+='<li>'+_ttEsc(d)+'</li>';});
      html+='</ul>';}
    if(e.notes)html+='<p class="ttd-note">'+_ttEsc(e.notes)+'</p>';
    if(e.hand_ids&&e.hand_ids.length){
      html+='<h4 class="ttd-sub">Hands ('+e.hand_ids.length+')</h4>';
      html+='<button type="button" class="ttd-hands-btn" onclick=\'openHandListPopup('
        +JSON.stringify((e.name||"Tournament")+" — hands")+','+JSON.stringify(e.hand_ids)
        +');return false;\'>Open the event’s hands</button>';}
    else{html+='<p class="ttd-note">No reviewable hands captured for this event.</p>';}
    body.innerHTML=html;
    var t=document.getElementById('ttd-modal-title');if(t)t.textContent=(e.name||'Tournament')+' — detail';
    var modal=document.getElementById('tournament-detail-modal');
    modal.setAttribute('aria-hidden','false');modal.classList.add('is-open');
    document.body.style.overflow='hidden';
    return false;
  }
  window.openTournamentDetail=openTournamentDetail;
  function closeTournamentDetail(){
    var modal=document.getElementById('tournament-detail-modal');
    if(modal){modal.setAttribute('aria-hidden','true');modal.classList.remove('is-open');}
    document.body.style.overflow='';
  }
  window.closeTournamentDetail=closeTournamentDetail;
  (function(){
    var c=document.getElementById('ttd-modal-close');if(c)c.addEventListener('click',closeTournamentDetail);
    var m=document.getElementById('tournament-detail-modal');
    if(m){var bd=m.querySelector('.modal-backdrop');if(bd)bd.addEventListener('click',closeTournamentDetail);}
  })();
  /* The payload is set via _extra_js; if it loaded before this script, wire now. */
  if(window.tournamentEvents)initTournamentResultsTable();

  /* v8.8.4: dimension-to-read support mapping for evidence partition */
  var READ_SUPPORT_DIMS={
    'Aggressive':['aggressive','pivot'],
    'Nit / Rock':['tight'],
    'Loose Passive':['loose_passive'],
    'Sticky Passive':['sticky']
  };
  /* v8.8.4: coaching one-liners per read */
  var READ_COACHING={
    'Aggressive':'Pressure/pivot signals. Adjust by trapping stronger, calling down selectively, and avoiding ego bluffs.',
    'Nit / Rock':'Overfold/tight signals. Adjust by stealing more and respecting sudden aggression.',
    'Loose Passive':'Limp/call/passive signals. Adjust by value-betting wider and bluffing less.',
    'Sticky Passive':'Call-down/sticky signals. Adjust by value-betting thinner and reducing bluffs.'
  };

  async function openReadEvidence(readLabel){
    var vi=(await PBData.villainIntel())||{};
    var allAtoms=[];
    var villainCount=0;
    var handSet={};
    for(var vk in vi){
      var v=vi[vk];
      if(!v.archetype_label)continue;
      if(v.archetype_label!==readLabel)continue;
      var atoms=v.evidence_atoms||[];
      if(!atoms.length)continue;
      villainCount++;
      atoms.forEach(function(a){
        a._vk=vk;a._valias=v.alias||'?';a._vnum=v.v_number||'';
        allAtoms.push(a);
        handSet[a.hand_id]=1;
      });
    }
    if(!allAtoms.length){openHandListPopup(readLabel+' — no evidence',[]); return;}
    var body=document.getElementById('ve-modal-body');
    body.innerHTML='';
    /* v8.8.4: partition atoms into supporting vs other */
    var supportDims=READ_SUPPORT_DIMS[readLabel]||[];
    var supporting=allAtoms.filter(function(a){return supportDims.indexOf(a.dimension)>=0;});
    var other=allAtoms.filter(function(a){return supportDims.indexOf(a.dimension)<0;});
    /* Compute reviewable/evidence-only counts */
    var handCount=Object.keys(handSet).length;
    var reviewable=0;var evidenceOnly=0;
    for(var hk in handSet){
      var nid=window.normalizeHandId?window.normalizeHandId(hk):hk;
      if(_isReviewable(nid)){reviewable++;}else{evidenceOnly++;}
    }
    var heroCount=allAtoms.filter(function(a){return a.hero_involved;}).length;
    var nonHeroCount=allAtoms.length-heroCount;
    /* Header with full metadata */
    var hdr=document.createElement('div');
    hdr.className='ve-header';
    hdr.innerHTML='<div class="ve-header-info" style="width:100%">'
      +'<h4>'+readLabel+' — Read Evidence</h4>'
      +'<p>'+allAtoms.length+' total signals · '+supporting.length+' supporting · '
      +other.length+' other signals from same villains</p>'
      +'<p style="font-size:12px;color:#475467">'+villainCount+' villains · '
      +handCount+' evidence hands · '+reviewable+' reviewable · '
      +evidenceOnly+' evidence-only · '
      +heroCount+' Hero-involved · '+nonHeroCount+' observed</p>'
      +(READ_COACHING[readLabel]?'<p style="font-size:12px;color:#1e40af;margin-top:4px"><em>'
      +READ_COACHING[readLabel]+'</em></p>':'')
      +'</div>';
    body.appendChild(hdr);
    /* Signal breakdown */
    var sigCounts={};
    allAtoms.forEach(function(a){var s=a.signal_label||a.signal||'?';sigCounts[s]=(sigCounts[s]||0)+1;});
    var breakdown=document.createElement('div');
    breakdown.style.cssText='font-size:12px;color:#475467;margin:4px 0 10px;';
    var parts=[];for(var s in sigCounts)parts.push(s+': '+sigCounts[s]);
    breakdown.textContent='Signals: '+parts.join(' · ');
    body.appendChild(breakdown);
    /* Filters — default to Supporting */
    var fbar=document.createElement('div');
    fbar.className='ve-filters';
    ['Supporting','Other signals','All','Hero involved','Pivots','Notes','Reviewable only'].forEach(function(lbl){
      var btn=document.createElement('span');
      btn.className='ve-filter'+(lbl==='Supporting'?' active':'');
      btn.textContent=lbl+(lbl==='Supporting'?' ('+supporting.length+')':'')
        +(lbl==='Other signals'?' ('+other.length+')':'');
      btn.onclick=function(){
        fbar.querySelectorAll('.ve-filter').forEach(function(b){b.classList.remove('active');});
        btn.classList.add('active');
        var filterAtoms=lbl==='Supporting'?supporting:lbl==='Other signals'?other:allAtoms;
        var filterKey=lbl==='Supporting'?'all':lbl==='Other signals'?'all':lbl.toLowerCase();
        buildReadEvidenceTable(body,filterAtoms,filterKey,readLabel);
      };
      fbar.appendChild(btn);
    });
    body.appendChild(fbar);
    /* Table — default to supporting evidence only */
    buildReadEvidenceTable(body,supporting,'supporting',readLabel);
    if(!supporting.length){var w=document.createElement('div');w.className='ev-warn';w.textContent='No supporting evidence available for this read. This may indicate missing atom dimensions or a read-mapping issue.';body.appendChild(w);}
    /* Show modal */
    var titleEl=document.getElementById('ve-modal-title');
    titleEl.textContent=readLabel+' Evidence ('+allAtoms.length+')';
    var modal=document.getElementById('villain-evidence-modal');
    modal.setAttribute('aria-hidden','false');
    modal.classList.add('is-open');
    document.body.style.overflow='hidden';
  }
  window.openReadEvidence=openReadEvidence;
  /* Open hand from read-level evidence with proper read context */
  function openHandFromReadEvidence(hid,readLabel,atoms){
    var handIds=atoms.map(function(a){return window.normalizeHandId?window.normalizeHandId(a.hand_id):a.hand_id;});
    var uniqueIds=[];var seen={};
    handIds.forEach(function(id){if(!seen[id]){seen[id]=1;uniqueIds.push(id);}});
    // Filter to reviewable only for queue navigation
    var reviewableIds=uniqueIds.filter(function(id){return _isReviewable(id);});
    if(!reviewableIds.length)reviewableIds=uniqueIds;
    var idx=reviewableIds.indexOf(hid);if(idx<0)idx=0;
    var reasons={};
    atoms.forEach(function(a){
      var nid=window.normalizeHandId?window.normalizeHandId(a.hand_id):a.hand_id;
      var r=readLabel+' evidence — '+(a._valias||a.villain_alias||'')+': '
        +(a.signal_label||a.label||'')+' — '+(a.evidence_text||'');
      if(reasons[nid]){reasons[nid]+='; '+r;}else{reasons[nid]=r;}
    });
    window.activeHandQueue={
      contextId:'read_evidence_'+readLabel.replace(/\s/g,'_'),
      contextTitle:'Read Evidence: '+readLabel,
      sourceType:'read_evidence',
      sourcePath:readLabel,
      handIds:reviewableIds,
      currentIndex:idx,
      reasonByHand:reasons,
      viewed:{}
    };
    closeVillainEvidence();
    if(window.openHand)window.openHand(hid);
  }
  function buildReadEvidenceTable(container,atoms,filter,readLabel){
    var old=container.querySelector('.ve-table-shell');
    if(old)old.remove();
    var shell=document.createElement('div');
    shell.className='table-shell ve-table-shell';
    var tbl=document.createElement('table');
    tbl.className='data-table';
    tbl.innerHTML='<tr><th>Hand</th><th>Villain</th><th>Street</th><th>V Pos</th>'
      +'<th>Hero?</th><th>Signal</th><th>Evidence</th><th>Read Impact</th><th>Detail</th></tr>';
    var shown=0;
    atoms.forEach(function(a){
      if(filter!=='all'){
        if(filter==='hero involved' && !a.hero_involved)return;
        if(filter==='pivots' && a.badge!=='pivot')return;
        if(filter==='notes' && a.badge!=='note')return;
        if(filter==='reviewable only'){
          var nid2=window.normalizeHandId?window.normalizeHandId(a.hand_id):a.hand_id;
          if(!_isReviewable(nid2))return;
        }
      }
      var hid=window.normalizeHandId?window.normalizeHandId(a.hand_id):a.hand_id;
      var isRev=_isReviewable(hid);
      var tr=document.createElement('tr');
      var td0=document.createElement('td');
      if(isRev){
        var link=document.createElement('a');
        link.href='#';link.textContent=hid;
        link.onclick=function(){openHandFromReadEvidence(hid,readLabel,atoms);return false;};
        td0.appendChild(link);
      }else{
        td0.textContent=hid;
        td0.style.color='#94a3b8';
      }
      var detailText=isRev?'Open hand':'Evidence only';
      tr.innerHTML='<td></td>'
        +'<td>'+(a._valias||'')+(a._vnum?' · '+a._vnum:'')+'</td>'
        +'<td>'+a.street+'</td>'
        +'<td>'+(a.villain_position||'')+'</td>'
        +'<td>'+(a.hero_involved?'✔':'')+'</td>'
        +'<td><span class="ve-signal '+a.badge+'">'+(a.label||'')
        +(a.signal_label?' · '+a.signal_label:'')+'</span></td>'
        +'<td>'+a.evidence_text+(a.context_text?'<br><small style="color:#64748b">'+a.context_text+'</small>':'')+'</td>'
        +'<td>'+a.read_impact+'</td>'
        +'<td style="font-size:11px;color:'+(isRev?'#1e40af':'#94a3b8')+'">'+detailText+'</td>';
      tr.replaceChild(td0,tr.firstChild);
      tbl.appendChild(tr);
      shown++;
    });
    if(shown===0){
      var tr=document.createElement('tr');
      tr.innerHTML='<td colspan="9" style="text-align:center;color:#94a3b8;padding:20px">'
        +'No evidence for this read.</td>';
      tbl.appendChild(tr);
    }
    shell.appendChild(tbl);
    container.appendChild(shell);
  }
  /* P1-10: enhance naked-number hand-list triggers with descriptive labels */
  document.querySelectorAll('.hand-list-trigger').forEach(function(a){
    var txt=a.textContent.trim();
    if(/hands|hand|›|open|view/i.test(txt))return;
    if(/^\d+$/.test(txt)){a.textContent=txt+' hands ›';}
    else if(/^\d+\/\d+$/.test(txt)){a.textContent=txt+' hands ›';}
    else if(/^[+-]?\d+\.?\d*$/.test(txt)){a.textContent=txt+' BB · hands ›';}
    var lt=a.getAttribute('data-list-title');
    if(lt&&!a.getAttribute('aria-label')){a.setAttribute('aria-label','Open hands for '+lt);a.setAttribute('title','Open hands for '+lt);}
  });
  /* ---- .hand-list-trigger click handler (v8.4.0: builds queue context) ---- */
  document.addEventListener('click',function(e){
    var trig=e.target.closest('.hand-list-trigger');
    if(!trig)return;
    e.preventDefault();
    var hids=(trig.getAttribute('data-hids')||'').split(',').filter(Boolean).map(normalizeHandId);
    var title=trig.getAttribute('data-list-title')||'Example Hands';
    /* If clicked inside hand modal, close it first so list appears on top */
    if(trig.closest('#hand-modal')){closeHand();}
    /* Build queue context so hands opened from this list get prev/next */
    window.activeHandQueue={
      contextId:'list_'+title.replace(/\s+/g,'_').toLowerCase().slice(0,40),
      contextTitle:title,
      sourceType:'hand_list',
      sourceSection:trig.closest('[id]')?(trig.closest('[id]').id||''):'',
      sourcePath:title,
      handIds:hids,
      currentIndex:0,
      viewed:{},
      reasonByHand:{}
    };
    openHandListPopup(title,hids);
  });
  /* ---- Modal stacking: list popup survives hand-review open/close ---- */
  var _listWasOpen=false;  /* tracks whether list popup was open when hand modal opened */
  function hideListPopup(){
    /* Visually hide but preserve state so we can restore after hand modal closes */
    var m=document.getElementById('list-modal');
    m.style.display='none';
  }
  function showListPopup(){
    var m=document.getElementById('list-modal');
    m.style.display='';
  }
  /* Wrap closeHand to restore list popup if it was behind the hand modal */
  var _origCloseHand=closeHand;
  closeHand=function(){
    _origCloseHand();
    if(_listWasOpen&&_listOpen){showListPopup();_listWasOpen=false;}
  };
  /* ---- CI tooltip popover (immediate, not native title delay) ---- */
  var _tipPop=document.getElementById('tip-pop');
  function showTip(e){
    /* Bug A fix: mouseenter capture fires for text nodes / document where
       e.target has no .closest(). Guard before use. */
    if(!e.target||typeof e.target.closest!=='function')return;
    var el=e.target.closest('[data-tip]')||e.target.closest('.ci-tip[title]');
    if(!el)return;
    var text=el.getAttribute('data-tip')||el.getAttribute('title');
    if(!text)return;
    _tipPop.textContent=text;
    _tipPop.classList.add('is-open');
    var r=el.getBoundingClientRect();
    _tipPop.style.left=Math.min(r.left,window.innerWidth-320)+'px';
    _tipPop.style.top=(r.bottom+6)+'px';
  }
  function hideTip(){_tipPop.classList.remove('is-open');}
  document.addEventListener('mouseenter',showTip,true);
  document.addEventListener('mouseleave',function(e){
    if(!e.target||typeof e.target.closest!=='function')return;
    if(e.target.closest('[data-tip]')||e.target.closest('.ci-tip[title]'))hideTip();
  },true);
  /* ---- Event wiring ---- */
  document.addEventListener('click',function(e){
    /* Bug A fix: guard against non-Element targets (e.g. SVG text nodes) */
    if(!e.target||typeof e.target.closest!=='function')return;
    /* Hand-ref pills: open hand review modal (highest priority).
       If list popup is open, hide it (don't close) so we can restore. */
    var pill=e.target.closest('a.hand-ref[data-hand-id]');
    if(pill){
      e.preventDefault();
      var phid=normalizeHandId(pill.getAttribute('data-hand-id'));
      if(_listOpen){
        _listWasOpen=true;hideListPopup();
        /* Set queue index when opening from list popup */
        var q=window.activeHandQueue;
        if(q&&q.handIds){
          var qi=q.handIds.indexOf(phid);
          if(qi===-1)qi=q.handIds.indexOf('TM'+phid);
          if(qi>=0){q.currentIndex=qi;if(!q.viewed)q.viewed={};q.viewed[phid]=true;}
        }
      } else {
        /* v8.8.6: build inline table queue for on-page hand refs */
        var inlineQueue=buildInlineHandQueueFromClickedRef(pill);
        if(inlineQueue&&inlineQueue.handIds&&inlineQueue.handIds.length>1){
          window.activeHandQueue=inlineQueue;
          var iqIdx=inlineQueue.handIds.map(normalizeHandId).indexOf(phid);
          window.activeHandQueue.currentIndex=iqIdx>=0?iqIdx:0;
          window.activeHandQueue.viewed=window.activeHandQueue.viewed||{};
          window.activeHandQueue.viewed[phid]=true;
        } else {
          window.activeHandQueue=null;
        }
      }
      openHand(phid);
      return;
    }
    /* xref links: check if target has hand evidence → list popup
       Skip if click originated inside a modal (no nested popups). */
    var xref=e.target.closest('a.xref:not(.hand-ref)');
    if(xref&&!xref.closest('.modal')){
      var href=xref.getAttribute('href');
      if(href&&href.charAt(0)==='#'){
        var tid=href.substring(1);
        if(openListPopup(tid)){e.preventDefault();return;}
      }
    }
    /* Backdrop clicks */
    if(e.target.closest('.list-backdrop')){closeListPopup();return;}
    if(e.target.closest('.modal-backdrop')&&!e.target.closest('.list-backdrop')){
      if(window.activeHandQueue){_queueBackToList();}else{closeHand();}return;}
  });
  document.getElementById('hand-modal-close').addEventListener('click',function(){
    if(window.activeHandQueue){_queueBackToList();}else{closeHand();}
  });
  document.getElementById('list-modal-close').addEventListener('click',function(){_listWasOpen=false;closeListPopup();});
  document.addEventListener('keydown',function(e){
    var hm=document.getElementById('hand-modal');
    var hmOpen=hm.classList.contains('is-open');
    if(e.key==='Escape'){
      if(hmOpen){
        if(window.activeHandQueue){_queueBackToList();}else{closeHand();}
        return;
      }
      if(_listOpen){_listWasOpen=false;closeListPopup();}
    }
    /* Queue navigation: arrow keys when hand modal open and queue active.
       v8.8.9 FEATURE: skip when focus is in an editable field so Ctrl+Arrow
       word-jump and in-text caret movement still work. */
    if(hmOpen&&window.activeHandQueue){
      var _ae=document.activeElement;
      var _inEdit=(_ae&&(_ae.tagName==='TEXTAREA'||_ae.tagName==='INPUT'||_ae.contentEditable==='true'));
      if(!_inEdit){
        if(e.key==='ArrowRight'){e.preventDefault();_queueNext();}
        if(e.key==='ArrowLeft'){e.preventDefault();_queuePrev();}
      }
    }
  });
  document.getElementById('modal-review-status').addEventListener('change',saveReview);
  /* v8.8.6: verdict chip click handlers — update hidden select, dispatch change,
     toggle active state.  Chips: .verdict-chip (3 verdicts), .verdict-clear (reset). */
  document.querySelectorAll('.verdict-chip-row .verdict-chip, .verdict-chip-row .verdict-clear').forEach(function(btn){
    btn.addEventListener('click',function(){
      var v=btn.getAttribute('data-verdict')||'';
      var sel=document.getElementById('modal-review-status');
      if(sel){sel.value=v;sel.dispatchEvent(new Event('change',{bubbles:true}));}
      var row=btn.closest('.verdict-chip-row');
      if(row){row.querySelectorAll('.verdict-chip').forEach(function(b){
        b.classList.toggle('active',b.getAttribute('data-verdict')===v&&v!=='');
      });}
    });
  });
  /* V25: street nav smooth-scroll handler */
  document.addEventListener('click',function(e){
    var navLink=e.target.closest('.v25-street-nav a');
    if(!navLink)return;
    e.preventDefault();
    var targetId=navLink.getAttribute('href').replace('#','');
    var targetEl=document.getElementById(targetId);
    if(targetEl)targetEl.scrollIntoView({behavior:'smooth',block:'start'});
  });
  /* v8.6.2: debounce notes textarea to prevent per-keystroke full-page scan */
  var _saveTimer=null;
  document.getElementById('modal-review-notes').addEventListener('input',function(){
    if(_saveTimer)clearTimeout(_saveTimer);
    _saveTimer=setTimeout(saveReview,500);
  });
  /* Mark already-reviewed hands on page load (Bug B fix: scoped prefix) */
  var _scopedPrefix='pokerbot:handreview:'+_reportDate+':';
  var stores2=[sessionStorage];if(_lsOK)stores2.push(localStorage);
  for(var si=0;si<stores2.length;si++){try{
    for(var ri=0;ri<stores2[si].length;ri++){var rk=stores2[si].key(ri);
      if(rk&&rk.indexOf(_scopedPrefix)===0){
        var rh=rk.replace(_scopedPrefix,'');
        var rd2={};try{rd2=JSON.parse(stores2[si].getItem(rk)||'null');}catch(e2){}
        if(rd2&&(rd2.status||rd2.notes))setReviewed(rh);
      }
    }
  }catch(e3){}}
  /* Populate review notes sidebar panel on load */
  refreshReviewPanel();
  /* Hide expandable hand-evidence <details> in report body — popups replace them.
     Targets: <details> whose <summary> ends with "click to expand". */
  document.querySelectorAll('details:not(.audit-row):not(.stack-context):not(.modal-stack)').forEach(function(d){
    var s=d.querySelector('summary');
    if(s&&/click to expand/i.test(s.textContent)){d.style.display='none';}
  });
  /* P1-1: re-sync sticky vars on resize (only when modal is open) */
  var _stickyTimer=null;
  window.addEventListener('resize',function(){
    if(_stickyTimer)clearTimeout(_stickyTimer);
    _stickyTimer=setTimeout(function(){
      if(document.getElementById('hand-modal').classList.contains('is-open')){
        _syncV25StickyVars();
      }
    },120);
  });
  /* GPT-QA-3: resync --v25-review-h when review bar resizes (textarea drag / content wrap) */
  var _reviewEl=document.querySelector('#hand-modal .modal-review');
  if(window.ResizeObserver&&_reviewEl){
    var _ro=new ResizeObserver(function(){
      if(document.getElementById('hand-modal').classList.contains('is-open')){
        _syncV25StickyVars();
      }
    });
    _ro.observe(_reviewEl);
  }
  /* v8.16.4 Obj 2: the nav/queue area can grow to MULTIPLE rows (>=20 chips
     wrapping, overflow rows, secondary context text) AFTER the one-shot measure,
     leaving --v25-queue-h stale so street headers overlap the nav. Observe the
     queue bar itself so any height change re-measures the offset from the actual
     bottom of the rendered nav area. */
  var _queueEl=document.getElementById('hand-queue-context');
  if(window.ResizeObserver&&_queueEl){
    var _roq=new ResizeObserver(function(){
      if(document.getElementById('hand-modal').classList.contains('is-open')){
        _syncV25StickyVars();
      }
    });
    _roq.observe(_queueEl);
  }
})();
</script>
"""

_AUDIT_HTML = r"""
<button id="audit-export-btn" onclick="auditExport()">📋 Copy Review Notes</button>
<button class="review-json-btn" onclick="auditExportJSON()" title="Export all review notes as JSON for backup/transfer">💾 Export JSON</button>
<button class="review-json-btn" onclick="auditImportJSON()" title="Import review notes from a previous export">📥 Import JSON</button>
<button id="audit-reset-btn" onclick="auditReset()">🗑 Reset notes…</button>
<script>
(function(){
  var _rd2=(document.querySelector('.report-app')||{}).getAttribute&&
    document.querySelector('.report-app').getAttribute('data-report-date')||'unknown';
  function upd(row){
    var sel=row.querySelector('.audit-status');
    var ta=row.querySelector('.audit-notes');
    var prev=row.querySelector('.audit-preview');
    var st=sel?sel.value:'';
    var nt=ta?(ta.value||'').trim():'';
    if(st||nt){
      row.classList.add('has-feedback');
      var p=nt.length>64?nt.slice(0,64)+'\u2026':nt;
      prev.textContent=' \u2014 '+(st?('['+st+']'):'[no verdict]')+(p?(' '+p):'');
    } else {
      row.classList.remove('has-feedback');
      prev.textContent=' \u2014 not yet reviewed';
    }
    /* B-V10: persist inline audit-row edits to storage + mark pills green.
       Without this, inline edits are visual-only and lost on page refresh. */
    var aid=row.getAttribute('data-aid')||'';
    var hid=aid.replace(/^TM\d{2}/,'');  /* TM6024565664 \u2192 24565664 */
    if(hid){
      if(window._gemWriteStore)window._gemWriteStore(hid,{status:st,notes:nt});
      if(st||nt){
        if(window._gemSetReviewed)window._gemSetReviewed(hid);
      } else {
        document.querySelectorAll('a.hand-ref[data-hand-id="'+hid+'"]')
          .forEach(function(el){el.classList.remove('reviewed');});
      }
    }
    updCount();
  }
  function updCount(){
    var n=0;
    document.querySelectorAll('.audit-row').forEach(function(r){
      if(r.classList.contains('has-feedback'))n++;
    });
    /* Also count modal hand reviews from storage (Bug B fix: scoped prefix) */
    var prefix='pokerbot:handreview:'+_rd2+':';
    var seenHids={};
    document.querySelectorAll('.audit-row[data-aid]').forEach(function(r){
      seenHids[r.getAttribute('data-aid')]=true;
    });
    /* Bug B fix: only count hand-ids present in this document */
    var docHids={};
    document.querySelectorAll('article.hand-detail-card[data-hand-id]').forEach(function(a){
      docHids[a.getAttribute('data-hand-id')]=true;
    });
    var stores=[];try{stores.push(sessionStorage);}catch(e){}
    try{if(localStorage.getItem)stores.push(localStorage);}catch(e){}
    for(var si=0;si<stores.length;si++){try{
      for(var ki=0;ki<stores[si].length;ki++){
        var k=stores[si].key(ki);
        if(k&&k.indexOf(prefix)===0){
          var hid=k.replace(prefix,'');
          if(seenHids[hid])continue;
          if(!docHids[hid])continue;
          var d=null;try{d=JSON.parse(stores[si].getItem(k));}catch(e2){}
          if(d&&(d.status||d.notes)){n++;seenHids[hid]=true;}
        }
      }
    }catch(e3){}}
    var b=document.getElementById('audit-export-btn');
    if(b)b.textContent=n>0?('\ud83d\udccb Copy Review Notes ('+n+')')
                          :'\ud83d\udccb Copy Review Notes';
  }
  window._gemUpdCount=updCount;
  function fallback(md,done){
    var t=document.createElement('textarea');
    t.value=md;t.style.position='fixed';t.style.opacity='0';
    document.body.appendChild(t);t.focus();t.select();
    try{document.execCommand('copy');}catch(e){}
    document.body.removeChild(t);done();
  }
  window.auditExport=function(){
    var subs=[],hands=[],n=0;
    var seenHids={};
    document.querySelectorAll('.audit-row').forEach(function(row){
      var sel=row.querySelector('.audit-status');
      var ta=row.querySelector('.audit-notes');
      var st=sel?sel.value:'';
      var nt=ta?(ta.value||'').trim():'';
      if(!st&&!nt)return;
      n++;
      var rec={title:row.getAttribute('data-atitle')||row.getAttribute('data-aid'),
               status:st||'(no verdict)',notes:nt};
      if(row.getAttribute('data-atype')==='hand'){
        hands.push(rec);
        var aid=normalizeHandId(row.getAttribute('data-aid')||'');
        if(aid)seenHids[aid]=true;
      }else{subs.push(rec);}
    });
    /* Phase 4.8: also collect modal reviews from scoped storage */
    var prefix='pokerbot:handreview:'+_rd2+':';
    var stores=[]; try{stores.push(sessionStorage);}catch(e){}
    try{if(localStorage.getItem)stores.push(localStorage);}catch(e){}
    for(var si=0;si<stores.length;si++){
      try{
        for(var ki=0;ki<stores[si].length;ki++){
          var k=stores[si].key(ki);
          if(k&&k.indexOf(prefix)===0){
            var hid=k.replace(prefix,'');
            if(seenHids[hid])continue; /* de-dup vs inline audit */
            var d=null;
            try{d=JSON.parse(stores[si].getItem(k));}catch(e2){}
            if(d&&(d.status||d.notes)){
              n++; seenHids[hid]=true;
              hands.push({title:'Hand '+hid,
                          status:d.status||'(no verdict)',
                          notes:d.notes||''});
            }
          }
        }
      }catch(e3){}
    }
    if(n===0){_toast('No review items yet \u2014 select a verdict or type a note first.');return;}
    function blk(a){return a.map(function(r){
      return '### '+r.title+'\n- **Verdict:** '+r.status+
             (r.notes?('\n- **Notes:** '+r.notes):'')+'\n';
    }).join('\n');}
    var md='# Pokerbot Report \u2014 Review Notes\n\n';
    if(subs.length)md+='## Section Reviews\n\n'+blk(subs)+'\n';
    if(hands.length)md+='## Hand Reviews\n\n'+blk(hands)+'\n';
    function done(){_toast('Copied '+n+' review item'+(n===1?'':'s')+' to clipboard.');}
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(md).then(done,function(){fallback(md,done);});
    } else { fallback(md,done); }
  };
  /* Reset all review notes for this report */
  window.auditReset=function(){
    if(!confirm('Reset ALL review notes for this report? This cannot be undone.'))return;
    /* Clear audit-row form fields */
    document.querySelectorAll('.audit-row').forEach(function(row){
      var sel=row.querySelector('.audit-status');
      var ta=row.querySelector('.audit-notes');
      if(sel)sel.value='';
      if(ta)ta.value='';
      row.classList.remove('has-feedback');
      var prev=row.querySelector('.audit-preview');
      if(prev)prev.textContent=' — not yet reviewed';
    });
    /* Clear scoped storage keys for this report */
    var prefix='pokerbot:handreview:'+_rd2+':';
    var stores=[];try{stores.push(sessionStorage);}catch(e){}
    try{if(localStorage.getItem)stores.push(localStorage);}catch(e){}
    for(var si=0;si<stores.length;si++){try{
      var toRm=[];
      for(var ki=0;ki<stores[si].length;ki++){
        var k=stores[si].key(ki);
        if(k&&k.indexOf(prefix)===0)toRm.push(k);
      }
      toRm.forEach(function(dk){stores[si].removeItem(dk);});
    }catch(e3){}}
    /* Clear .reviewed class from hand-ref pills */
    document.querySelectorAll('a.hand-ref.reviewed').forEach(function(el){
      el.classList.remove('reviewed');
    });
    updCount();
    if(window.pbDecorateReviewTargets)window.pbDecorateReviewTargets();
    _toast('All review notes for this report have been reset.');
  };
  /* BUG 4: Export/import review notes as JSON for cross-render persistence */
  window.auditExportJSON=function(){
    var prefix='pokerbot:handreview:'+_rd2+':';
    var notes={};var n=0;
    var stores=[];try{stores.push(sessionStorage);}catch(e){}
    try{if(localStorage.getItem)stores.push(localStorage);}catch(e){}
    for(var si=0;si<stores.length;si++){try{
      for(var ki=0;ki<stores[si].length;ki++){var k=stores[si].key(ki);
        if(k&&k.indexOf(prefix)===0){
          var hid=k.replace(prefix,'');
          try{notes[hid]=JSON.parse(stores[si].getItem(k));n++;}catch(e){}
        }
      }
    }catch(e){}}
    if(n===0){_toast('No review notes to export.');return;}
    var json=JSON.stringify({reportDate:_rd2,notes:notes},null,2);
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(json).then(function(){_toast('Exported '+n+' review notes to clipboard.');});
    }else{_toast('Clipboard unavailable. Check console.');console.log(json);}
  };
  window.auditImportJSON=function(){
    var input=prompt('Paste review notes JSON:');
    if(!input)return;
    try{
      var data=JSON.parse(input);
      var notes=data.notes||data;var n=0;
      var prefix='pokerbot:handreview:'+_rd2+':';
      for(var hid in notes){
        if(!notes.hasOwnProperty(hid))continue;
        var val=JSON.stringify(notes[hid]);
        try{localStorage.setItem(prefix+hid,val);}catch(e){}
        try{sessionStorage.setItem(prefix+hid,val);}catch(e){}
        n++;
      }
      if(window.pbDecorateReviewTargets)window.pbDecorateReviewTargets();
      _toast('Imported '+n+' review notes.');
    }catch(e){_toast('Invalid JSON: '+e.message);}
  };
  function init(){
    document.querySelectorAll('.audit-row').forEach(function(row){
      ['.audit-status','.audit-notes'].forEach(function(sel){
        var el=row.querySelector(sel);
        if(el){
          el.addEventListener('input',function(){upd(row);});
          el.addEventListener('change',function(){upd(row);});
        }
      });
    });
    /* B-V10: on page load, mark pills green for hands that have saved
       reviews from a previous visit. Without this, pills start uncolored
       even when localStorage has a verdict. */
    var _prefix2='pokerbot:handreview:'+_rd2+':';
    var _stores3=[];try{_stores3.push(sessionStorage);}catch(e){}
    try{if(localStorage.getItem)_stores3.push(localStorage);}catch(e){}
    for(var _si3=0;_si3<_stores3.length;_si3++){try{
      for(var _ki3=0;_ki3<_stores3[_si3].length;_ki3++){
        var _k3=_stores3[_si3].key(_ki3);
        if(_k3&&_k3.indexOf(_prefix2)===0){
          var _hid3=_k3.replace(_prefix2,'');
          var _d3=null;try{_d3=JSON.parse(_stores3[_si3].getItem(_k3));}catch(e){}
          if(_d3&&(_d3.status||_d3.notes)){
            if(window._gemSetReviewed)window._gemSetReviewed(_hid3);
          }
        }
      }
    }catch(e){}}
    /* Restore section/issue audit row values from storage */
    document.querySelectorAll('.audit-row[data-aid]').forEach(function(row){
      var aid=row.getAttribute('data-aid')||'';
      var hid=aid.replace(/^TM\d{2}/,'');
      if(!hid)return;
      var d=null;
      if(window._gemReadStore){
        try{d=window._gemReadStore(hid)||null;}catch(e){}
      }
      if(d&&(d.status||d.notes)){
        var sel=row.querySelector('.audit-status');
        var ta=row.querySelector('.audit-notes');
        var prev=row.querySelector('.audit-preview');
        if(sel&&d.status)sel.value=d.status;
        if(ta&&d.notes)ta.value=d.notes;
        row.classList.add('has-feedback');
        if(prev){
          var p=(d.notes||'').length>64?(d.notes||'').slice(0,64)+'…':(d.notes||'');
          prev.textContent=' — '+(d.status?('['+d.status+']'):'[no verdict]')+(p?(' '+p):'');
        }
      }
    });
    updCount();
    if(window.pbDecorateReviewTargets)window.pbDecorateReviewTargets();
  }
  if(document.readyState==='loading')
    document.addEventListener('DOMContentLoaded',init);
  else init();
})();
</script>
<script>
/* ==== MOBILE TABLE READABILITY — client-side row builder + audit ==== */
(function(){
  function _esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
  function _buildMobileHandRows(){
    document.querySelectorAll('[data-mobile-mode="hand-list"]').forEach(function(shell){
      if(shell.querySelector('.mobile-hand-list'))return;
      var tbl=shell.querySelector('table');
      if(!tbl)return;
      var ths=tbl.querySelectorAll('thead th');
      /* Build column index map from header text */
      var ci={};
      ths.forEach(function(th,i){
        var t=th.textContent.trim().toLowerCase();
        if(t==='hand'||t==='id')ci.hand=i;
        else if(t==='cards')ci.cards=i;
        else if(t==='spot'||t==='position'||t==='pos')ci.spot=i;
        else if(t==='stack')ci.stack=i;
        else if(t==='net'||t==='result')ci.net=i;
        else if(t==='type'||t==='verdict'||t==='status')ci.type=i;
        else if(t==='open')ci.open=i;
      });
      var list=document.createElement('div');
      list.className='mobile-hand-list';
      tbl.querySelectorAll('tbody tr').forEach(function(tr){
        var tds=tr.querySelectorAll('td');
        if(!tds.length)return;
        var row=document.createElement('article');
        row.className='mobile-hand-row';
        /* Main section */
        var main=document.createElement('div');
        main.className='mobile-hand-main';
        /* Topline: hand ref + cards + spot/stack */
        var topline=document.createElement('div');
        topline.className='mobile-hand-topline';
        /* Hand link */
        var handTd=tds[ci.hand!==undefined?ci.hand:1];
        if(handTd){
          var aRef=handTd.querySelector('a.hand-ref,a.xref');
          if(aRef){
            var a2=aRef.cloneNode(true);
            a2.classList.add('hand-ref');
            topline.appendChild(a2);
          } else {
            var sp=document.createElement('span');
            sp.className='hand-ref';
            sp.textContent=handTd.textContent.trim().substring(0,10);
            topline.appendChild(sp);
          }
        }
        /* Cards */
        if(ci.cards!==undefined && tds[ci.cards]){
          tds[ci.cards].querySelectorAll('.card').forEach(function(c){
            topline.appendChild(c.cloneNode(true));
          });
        }
        /* Spot + Stack tag */
        var tagParts=[];
        if(ci.spot!==undefined && tds[ci.spot]) tagParts.push(tds[ci.spot].textContent.trim());
        if(ci.stack!==undefined && tds[ci.stack]) tagParts.push(tds[ci.stack].textContent.trim());
        if(tagParts.length){
          var tag=document.createElement('span');
          tag.className='mobile-tag';
          tag.textContent=tagParts.join(' ');
          topline.appendChild(tag);
        }
        main.appendChild(topline);
        /* Meta: type/verdict */
        if(ci.type!==undefined && tds[ci.type]){
          var meta=document.createElement('div');
          meta.className='mobile-hand-meta';
          var typeText=tds[ci.type].textContent.trim();
          if(typeText){
            var typeBadge=document.createElement('span');
            var isErr=/error|wrong|bad|miss/i.test(typeText);
            var isGood=/good|correct|counter/i.test(typeText);
            typeBadge.className='mobile-tag'+(isErr?' bad':(isGood?' good':''));
            typeBadge.textContent=typeText;
            meta.appendChild(typeBadge);
          }
          main.appendChild(meta);
        }
        row.appendChild(main);
        /* Side: net + open button */
        var side=document.createElement('div');
        side.className='mobile-hand-side';
        if(ci.net!==undefined && tds[ci.net]){
          var netTd=tds[ci.net];
          var netSpan=document.createElement('span');
          netSpan.className=netTd.classList.contains('net-pos')?'net-pos':
                           (netTd.classList.contains('net-neg')?'net-neg':'');
          netSpan.textContent=netTd.textContent.trim();
          side.appendChild(netSpan);
        }
        /* Open button from hand link */
        if(handTd){
          var aOpen=handTd.querySelector('a[data-hand-id]');
          if(aOpen){
            var btn=document.createElement('a');
            btn.className='open-hand-btn';
            btn.href=aOpen.href||'#';
            btn.setAttribute('data-hand-id',aOpen.getAttribute('data-hand-id')||'');
            btn.textContent='Open';
            side.appendChild(btn);
          }
        }
        row.appendChild(side);
        list.appendChild(row);
      });
      shell.appendChild(list);
      shell.classList.add('has-mobile-cards');
    });
  }
  /* Evidence-card builder — parse table rows into rich mobile cards */
  function _buildMobileEvidenceCards(){
    document.querySelectorAll('[data-mobile-mode="evidence-card"]').forEach(function(shell){
      if(shell.querySelector('.mobile-evidence-list'))return;
      var tbl=shell.querySelector('table');
      if(!tbl)return;
      /* User-QA-2: fall back to first-row th when thead is absent */
      var ths=tbl.querySelectorAll('thead th');
      if(!ths.length)ths=tbl.querySelectorAll('tr:first-child th');
      if(!ths.length)return;
      var headers=[];
      ths.forEach(function(th){headers.push(th.textContent.trim());});
      /* Identify hand column and prose columns by header text */
      var handCol=-1, proseThreshold=20;
      var _evKw=/reason|diagnosis|what|recommendation|question|explanation|erratic|lesson|verdict|misplay/i;
      headers.forEach(function(h,i){
        var lc=h.toLowerCase();
        if(lc==='hand'||lc==='id'||lc==='#'||lc.indexOf('hand')>=0) handCol=i;
      });
      var list=document.createElement('div');
      list.className='mobile-evidence-list';
      tbl.querySelectorAll('tbody tr').forEach(function(tr){
        var tds=tr.querySelectorAll('td');
        if(!tds.length)return;
        var card=document.createElement('article');
        card.className='mobile-evidence-card';
        /* Head: hand ref + short fields */
        var head=document.createElement('div');
        head.className='mobile-evidence-head';
        var title=document.createElement('div');
        title.className='mobile-evidence-title';
        if(handCol>=0 && tds[handCol]){
          var aRef=tds[handCol].querySelector('a.hand-ref,a.xref,a[data-hand-id]');
          if(aRef){
            var a2=aRef.cloneNode(true);
            a2.classList.add('hand-ref');
            title.appendChild(a2);
          } else {
            var sp=document.createElement('span');
            sp.className='hand-ref';
            sp.textContent=tds[handCol].textContent.trim().substring(0,10);
            title.appendChild(sp);
          }
        }
        head.appendChild(title);
        card.appendChild(head);
        /* Grid: short fields as key/value pairs; prose/preview with priority */
        var _previewPriority=['verdict','reason','question','what to do','diagnosis'];
        var grid=document.createElement('div');
        grid.className='mobile-evidence-grid';
        var previewCandidates=[];
        var detailBlocks=[];
        var shortFields=[];
        for(var ci=0;ci<tds.length;ci++){
          if(ci===handCol)continue;
          var hdr=headers[ci]||('Col '+(ci+1));
          var val=tds[ci].textContent.trim();
          if(!val)continue;
          var hdrLc=hdr.toLowerCase();
          /* Check if this column matches a priority preview field */
          var priIdx=-1;
          for(var pi=0;pi<_previewPriority.length;pi++){
            if(hdrLc===_previewPriority[pi]||hdrLc.indexOf(_previewPriority[pi])>=0){priIdx=pi;break;}
          }
          if(priIdx>=0){
            previewCandidates.push({idx:priIdx,label:hdr,html:tds[ci].innerHTML,text:val});
          } else if(_evKw.test(hdr) || val.length>proseThreshold){
            detailBlocks.push({label:hdr,html:tds[ci].innerHTML});
          } else {
            shortFields.push({label:hdr,val:val});
          }
        }
        /* Sort preview candidates by priority index; first becomes preview */
        previewCandidates.sort(function(a,b){return a.idx-b.idx;});
        var previewField=previewCandidates.length?previewCandidates[0]:null;
        /* Remaining priority fields go to details */
        for(var ri=1;ri<previewCandidates.length;ri++){
          detailBlocks.push({label:previewCandidates[ri].label,html:previewCandidates[ri].html});
        }
        /* If no priority preview, use first detail block as preview */
        if(!previewField&&detailBlocks.length){
          previewField={label:detailBlocks[0].label,html:detailBlocks[0].html,text:''};
          detailBlocks.splice(0,1);
        }
        /* Short fields in grid */
        shortFields.forEach(function(sf){
          var kv=document.createElement('div');
          kv.className='kv';
          kv.innerHTML='<span>'+_esc(sf.label)+'</span><b>'+_esc(sf.val)+'</b>';
          grid.appendChild(kv);
        });
        if(grid.children.length) card.appendChild(grid);
        /* Preview field (max 2 lines via CSS) */
        if(previewField){
          var prev=document.createElement('div');
          prev.className='mobile-evidence-preview';
          prev.innerHTML=previewField.html;
          card.appendChild(prev);
        }
        /* Detail blocks in collapsible <details> — no duplication of preview */
        if(detailBlocks.length){
          var det=document.createElement('details');
          det.className='mobile-evidence-details';
          var sum=document.createElement('summary');
          sum.textContent='Details';
          det.appendChild(sum);
          detailBlocks.forEach(function(db){
            var body=document.createElement('div');
            body.className='mobile-evidence-body';
            body.innerHTML='<div class="mobile-evidence-body-label">'+_esc(db.label)+'</div>'+db.html;
            det.appendChild(body);
          });
          card.appendChild(det);
        }
        list.appendChild(card);
      });
      shell.appendChild(list);
      shell.classList.add('has-mobile-cards');
    });
  }
  /* Audit object */
  function _buildMobileTableAudit(){
    var audit={total_tables:0,classified:0,
      by_mode:{scroll:0,hand_list:0,evidence_card:0,compact:0,unclassified:0},
      wide_unclassified:[]};
    document.querySelectorAll('table').forEach(function(t){
      audit.total_tables++;
      var shell=t.closest('[data-mobile-mode]');
      if(shell){
        audit.classified++;
        var m=(shell.getAttribute('data-mobile-mode')||'').replace(/-/g,'_');
        if(audit.by_mode[m]!==undefined)audit.by_mode[m]++;
        else audit.by_mode.unclassified++;
      } else {
        var cols=t.querySelectorAll('thead th').length;
        if(cols>=6)audit.wide_unclassified.push({
          id:t.id||'',cls:t.className,cols:cols,
          parent:(t.parentElement||{}).className||''
        });
        audit.by_mode.unclassified++;
      }
    });
    window.mobileTableAudit=audit;
  }
  function _initMobileTables(){
    _buildMobileHandRows();
    _buildMobileEvidenceCards();
    _buildMobileTableAudit();
  }
  if(document.readyState==='loading')
    document.addEventListener('DOMContentLoaded',_initMobileTables);
  else _initMobileTables();
})();
</script>
<script>
/* v8.8.5: Per-Tournament P&L sortable/filterable table
   v8.8.6: idempotent, callable after data assignment */
window.initPerTournamentPnlTable=function(){
  if(window.__pnlInitialized)return;
  var rows=window.perTournamentPnlRows;
  if(!rows||!rows.length)return;
  /* Find the sec-1-1 section's first table-shell and replace */
  var sec=document.getElementById('sec-1-1');
  if(!sec)return;
  var shell=sec.closest('details');
  if(!shell)shell=sec.parentElement;
  var oldTbl=shell?shell.querySelector('.table-shell'):null;
  if(!oldTbl)return;
  window.__pnlInitialized=true;
  /* State */
  var sortCol='hands',sortAsc=false,filterFn=null,showN=20;
  var numCols={bullets:1,hands:1,buyin:1,cash:1,net_usd:1,roi:1,net_bb:1,bb100:1};
  var cols=[
    {key:'date',label:'Date'},{key:'name',label:'Tournament'},
    {key:'bullets',label:'Bullets'},{key:'hands',label:'Hands'},
    {key:'buyin',label:'BI'},{key:'net_bb',label:'NetBB'},
    {key:'bb100',label:'bb/100'},{key:'format',label:'Format'}
  ];
  function render(){
    var sorted=rows.slice();
    if(filterFn)sorted=sorted.filter(filterFn);
    sorted.sort(function(a,b){
      var va=a[sortCol],vb=b[sortCol];
      if(numCols[sortCol]){va=parseFloat(va)||0;vb=parseFloat(vb)||0;}
      else{va=String(va||'').toLowerCase();vb=String(vb||'').toLowerCase();}
      return sortAsc?(va>vb?1:va<vb?-1:0):(va<vb?1:va>vb?-1:0);
    });
    var showing=showN>0?sorted.slice(0,showN):sorted;
    var html='<table class="data-table"><thead><tr>';
    cols.forEach(function(c){
      var arrow=c.key===sortCol?(sortAsc?' ▲':' ▼'):'';
      html+='<th data-col="'+c.key+'" style="cursor:pointer">'+c.label+arrow+'</th>';
    });
    html+='</tr></thead><tbody>';
    showing.forEach(function(r){
      var cls=r.net_bb>0?'net-pos':r.net_bb<0?'net-neg':'';
      html+='<tr>'
        +'<td>'+r.date+'</td>'
        +'<td>'+r.name.substring(0,40)+'</td>'
        +'<td>'+r.bullets+'</td>'
        +'<td>'+r.hands+'</td>'
        +'<td>'+(r.buyin?'$'+r.buyin.toFixed(0):'—')+'</td>'
        +'<td class="'+cls+'">'+r.net_bb.toFixed(1)+'</td>'
        +'<td class="'+cls+'">'+r.bb100.toFixed(1)+'</td>'
        +'<td>'+r.format+'</td>'
        +'</tr>';
    });
    html+='</tbody></table>';
    if(sorted.length>showing.length)
      html+='<div style="font-size:12px;color:var(--muted);margin-top:4px;">Showing '
        +showing.length+' of '+sorted.length+' tournaments</div>';
    tblDiv.innerHTML=html;
    /* Bind header clicks */
    tblDiv.querySelectorAll('th[data-col]').forEach(function(th){
      th.addEventListener('click',function(){
        var c=th.getAttribute('data-col');
        if(sortCol===c)sortAsc=!sortAsc;else{sortCol=c;sortAsc=numCols[c]?false:true;}
        render();
      });
    });
  }
  /* Build container */
  var wrap=document.createElement('div');wrap.className='pnl-sortable';
  /* Controls bar */
  var cbar=document.createElement('div');
  cbar.style.cssText='display:flex;gap:8px;margin-bottom:6px;flex-wrap:wrap;align-items:center;';
  /* Show N controls */
  [20,50,0].forEach(function(n){
    var btn=document.createElement('button');
    btn.className='filter-btn';btn.textContent=n?'Show '+n:'All';
    btn.addEventListener('click',function(){showN=n;render();});
    cbar.appendChild(btn);
  });
  /* Filter buttons */
  var sep=document.createElement('span');sep.textContent=' | ';sep.style.color='var(--muted)';
  cbar.appendChild(sep);
  [{label:'All',fn:null},{label:'Winning',fn:function(r){return r.net_bb>0;}},
   {label:'Losing',fn:function(r){return r.net_bb<0;}},
   {label:'Bustouts',fn:function(r){return r.net_bb<0&&Number(r.roi)<=-99;}}
  ].forEach(function(f){
    var btn=document.createElement('button');btn.className='filter-btn';btn.textContent=f.label;
    btn.addEventListener('click',function(){filterFn=f.fn;render();});
    cbar.appendChild(btn);
  });
  wrap.appendChild(cbar);
  var tblDiv=document.createElement('div');tblDiv.className='table-shell';
  wrap.appendChild(tblDiv);
  oldTbl.replaceWith(wrap);
  render();
};
if(document.readyState==='loading')
  document.addEventListener('DOMContentLoaded',window.initPerTournamentPnlTable);
else window.initPerTournamentPnlTable();
/* Phase 4.6 B4 / 4.8 C2: active-section tracking — nav rail + workflow tabs + indicator.
   Degrades gracefully — if IO unavailable, nav/tabs are still working links. */
(function(){
  if(!('IntersectionObserver' in window))return;
  var indicator=document.getElementById('section-indicator');
  var navObserver=new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if(e.isIntersecting){
        var id=e.target.id;
        /* Nav rail active state */
        document.querySelectorAll('.nav-row.active').forEach(function(n){
          n.classList.remove('active');
        });
        var row=document.querySelector('.nav-row[href="#'+id+'"]');
        if(row){row.classList.add('active');row.scrollIntoView({block:'nearest'});}
        /* Workflow tabs active state */
        document.querySelectorAll('.wf-tab[aria-current]').forEach(function(t){
          t.removeAttribute('aria-current');
        });
        var tab=document.querySelector('.wf-tab[data-section="'+id+'"]');
        if(tab){tab.setAttribute('aria-current','true');
          tab.scrollIntoView({block:'nearest',inline:'nearest'});}
        /* Section indicator chip */
        if(indicator){
          var heading=e.target.textContent||'';
          /* Trim summary after " — " */
          var dash=heading.indexOf(' — ');
          if(dash>0)heading=heading.substring(0,dash);
          indicator.innerHTML='<span class="reading-section-chip">Now reading: '+heading+'</span>';
        }
      }
    });
  },{rootMargin:'-20% 0px -70% 0px'});
  document.querySelectorAll('h2[id^="sec-"]').forEach(function(h){
    navObserver.observe(h);
  });
  /* B255: auto-open <details> when an anchor link targets a sibling anchor.
     Pattern: <a id="sec-11-11-flop-missed"></a><details>...
     On hash change, find the anchor, check if nextElementSibling is a <details>,
     open it, and close other details in the same group. */
  function openTargetDetails(){
    var h=location.hash;if(!h)return;
    var el=document.getElementById(h.slice(1));if(!el)return;
    /* v8.17.0-rc3: also expand any ANCESTOR <details> the target sits INSIDE
       (e.g. sec-1-1 / sec-1-3 now live in the collapsed s1-recon-detail
       secondary reconciliation block — a KPI card or section backlink must
       auto-open it, not leave the reader inside a closed disclosure). */
    var anc=el.closest('details');
    while(anc){anc.setAttribute('open','');anc=anc.parentElement&&anc.parentElement.closest('details');}
    var det=el.nextElementSibling;
    /* Skip anchor-compat nodes */
    while(det&&det.tagName==='A')det=det.nextElementSibling;
    if(!det||det.tagName!=='DETAILS')return;
    /* Close sibling details in same parent to focus on just this one */
    var parent=det.parentElement;
    if(parent){parent.querySelectorAll(':scope > details:not(.audit-row)').forEach(function(d){
      if(d!==det)d.removeAttribute('open');
    });}
    det.setAttribute('open','');
    det.scrollIntoView({block:'start',behavior:'smooth'});
  }
  window.addEventListener('hashchange',openTargetDetails);
  openTargetDetails();/* fire on initial load if URL has hash */
  /* P3 #10: Safe storage wrapper */
  function _safeGet(key){try{return sessionStorage.getItem(key)||localStorage.getItem(key);}catch(e){return null;}}
  function _safeSet(key,val){try{sessionStorage.setItem(key,val);}catch(e){try{localStorage.setItem(key,val);}catch(e2){}}}
  /* P1 #9: Toast notification instead of alert — exposed globally */
  window._toast=function _toast(msg,ms){
    var t=document.createElement('div');
    t.textContent=msg;
    t.style.cssText='position:fixed;bottom:20px;left:50%;transform:translateX(-50%);'
      +'background:#172554;color:#fff;padding:10px 20px;border-radius:10px;font-size:13px;'
      +'font-weight:700;z-index:9999;box-shadow:0 4px 20px rgba(0,0,0,.3);transition:opacity .3s;';
    document.body.appendChild(t);
    setTimeout(function(){t.style.opacity='0';setTimeout(function(){t.remove();},400);},ms||2500);
  }
  /* P1 #4: Sidebar search — hand ID opens modal, text scrolls to section */
  var _searchBox=document.getElementById('report-search');
  if(_searchBox){
    _searchBox.addEventListener('keydown',function(e){
      if(e.key==='Escape'){_searchBox.value='';return;}
      if(e.key!=='Enter')return;
      var q=(_searchBox.value||'').trim();if(!q)return;
      /* Try as hand ID first */
      var nq=normalizeHandId(q);
      if(nq.length>=6&&/^\d+$/.test(nq)){
        var art=document.getElementById('sec-app-hand-'+nq)||document.querySelector('[data-hand-id="'+nq+'"]');
        if(art){window.activeHandQueue=null;openHand(nq);_searchBox.value='';return;}
      }
      /* Try as section/heading text */
      var ql=q.toLowerCase();
      var headings=document.querySelectorAll('h2,h3,h4');
      for(var i=0;i<headings.length;i++){
        if(headings[i].textContent.toLowerCase().indexOf(ql)>=0){
          headings[i].scrollIntoView({block:'start',behavior:'smooth'});
          headings[i].classList.add('deep-link-highlight');
          setTimeout(function(){headings[i].classList.remove('deep-link-highlight');},2500);
          _searchBox.value='';return;
        }
      }
      /* Try IE issue rows */
      var ieRows=document.querySelectorAll('.ie-row .ie-issue,.ie-row .ie-ev');
      for(var j=0;j<ieRows.length;j++){
        if(ieRows[j].textContent.toLowerCase().indexOf(ql)>=0){
          var row=ieRows[j].closest('.ie-row');
          if(row){row.scrollIntoView({block:'center',behavior:'smooth'});
            row.style.outline='3px solid #f59e0b';
            setTimeout(function(){row.style.outline='';},2500);}
          _searchBox.value='';return;
        }
      }
      /* v8.12.8 QA-GPT P2.1: lazy hand bodies aren't searchable until
         materialized — on a miss, inflate everything once, then search
         hand text and open the first match. */
      if(window.PBLazy&&(window.PB_PAYLOADS||{}).lazyHands){
        var _phOld=_searchBox.placeholder;
        _searchBox.placeholder='Loading all hands to search…';
        var _pAll=PBLazy.ensureAll(null);
        if(_pAll&&_pAll.then)_pAll.then(function(){
          _searchBox.placeholder=_phOld;
          var arts=document.querySelectorAll('article.hand-detail-card');
          for(var k2=0;k2<arts.length;k2++){
            if(arts[k2].textContent.toLowerCase().indexOf(ql)>=0){
              var hid2=arts[k2].getAttribute('data-hand-id');
              if(hid2){window.activeHandQueue=null;openHand(hid2);
                _searchBox.value='';return;}
            }
          }
          if(window._toast)_toast('No match for "'+q+'"');
        });
      }
    });
  }
  /* P3: runtime broken-anchor detector */
  var _broken=[];
  document.querySelectorAll('a[href^="#"]').forEach(function(a){
    var id=a.getAttribute('href').slice(1);
    if(id&&!document.getElementById(id))_broken.push(id);
  });
  if(_broken.length){
    console.warn('Pokerbot: '+_broken.length+' broken anchor links:',_broken.slice(0,20));
    var _qa=document.getElementById('sec-14');
    if(_qa){var _w=document.createElement('div');
      _w.style.cssText='background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:8px 12px;margin:8px 0;font-size:12px;color:#991b1b;';
      _w.textContent='⚠️ '+_broken.length+' internal links point to missing targets. See console for details.';
      _qa.parentNode.insertBefore(_w,_qa.nextSibling);}
  }
  /* P3 #20: Runtime health check */
  var _health=[];
  if(document.getElementById('hand-modal'))_health.push('modal:ok');
  else _health.push('modal:MISSING');
  if(document.getElementById('ie-main-table'))_health.push('ie:ok');
  if(window._queueJump)_health.push('queue:ok');
  if(window._toast)_health.push('toast:ok');
  if(_safeGet)_health.push('storage:ok');
  /* health log available via: document._pbHealth = _health; */
  if(location.search.indexOf('debug=1')>=0)console.log('Pokerbot health: '+_health.join(' · '));
})();
</script>
"""


def _topbar_html(kpis, nav_sections=None):
    """Phase 4.6 B3 / 4.8 C2: generate the sticky topbar with brand lockup,
    12-card stat strip, workflow tabs, and section indicator.
    Returns empty string if no KPI data supplied."""
    if not kpis:
        return ''
    player = _html_escape(kpis.get('player', 'Knockman'))
    date = _html_escape(kpis.get('date', ''))

    # Build 12 stat cards — ordered per PDF §5
    cards = []
    def _card(label, value, href, css_extra='', tip=''):
        v_cls = ''
        if css_extra == 'pos':
            css_extra = ' stat-pos'
            v_cls = ' class="value-pos"'
        elif css_extra == 'neg':
            css_extra = ' stat-neg'
            v_cls = ' class="value-neg"'
        else:
            css_extra = ''
        tip_attr = f' data-tip="{_html_escape(tip)}"' if tip else ''
        cards.append(
            f'<a class="stat-card{css_extra}" href="#{_html_escape(href)}"{tip_attr}>'
            f'<span>{_html_escape(label)}</span>'
            f'<b{v_cls}>{_html_escape(str(value))}</b></a>')

    def _signed(val):
        """Return 'pos', 'neg', or '' for sign coloring."""
        if val is None:
            return ''
        try:
            return 'pos' if float(val) > 0 else ('neg' if float(val) < 0 else '')
        except (ValueError, TypeError):
            return ''

    # 1. Hands (neutral)
    _card('Hands', f"{kpis.get('n_hands', 0):,}", 'sec-18',
          tip='Total hands in sample')
    # 2. Tourneys (neutral) — v8.14.3 Issue 1: canonical (settled) count, with an
    # explicit "+N in progress" annotation for unresolved HH-only events (e.g. a
    # 2-day event with no game summary yet), so header and by-day agree on the
    # settled count and the 44-vs-43 gap is never shown unexplained.
    _nt_val = kpis.get('n_tourneys', 0)
    _nt_note = kpis.get('n_tourneys_note') or ''
    _nt_disp = f"{_nt_val} +{_nt_note}" if _nt_note else f"{_nt_val}"
    _card('Tourneys', _nt_disp, 'sec-1-1',
          tip=(f'{_nt_val} settled + {_nt_note} (HH-only, no summary yet)'
               if _nt_note else 'Tournaments played'))
    # 3. Bullets (neutral)
    _card('Bullets', kpis.get('bullets', 0), 'sec-1-1',
          tip='Total entries including re-entries')
    # 4. ABI (neutral) — B-V10: show cents when fractional
    abi = kpis.get('avg_buyin')
    # Strip .00 only (keep .40 as-is for proper currency display)
    def _usd_strip(s):
        return s[:-3] if s.endswith('.00') else s
    _abi_s = _usd_strip(f"${abi:,.2f}") if abi is not None else '—'
    _card('ABI', _abi_s, 'sec-1', tip='Average buy-in')
    # 5. Invested (neutral)
    inv = kpis.get('total_invested')
    _inv_s = _usd_strip(f"${inv:,.2f}") if inv is not None else '—'
    _card('Invested', _inv_s, 'sec-1', tip='Total amount invested')
    # 6. Net (signed)
    net = kpis.get('net')
    if net is not None:
        _net_s = _usd_strip(f"${net:+,.2f}")
        _card('Net', _net_s, 'sec-1', _signed(net),
              tip='Net profit/loss ($)')
    else:
        _card('Net', '—', 'sec-1', tip='Net profit/loss ($)')
    # 7. ROI (signed)
    roi = kpis.get('roi')
    if roi is not None:
        _card('ROI', f"{roi:+.1f}%", 'sec-1', _signed(roi),
              tip='Return on investment')
    else:
        _card('ROI', '—', 'sec-1', tip='Return on investment')
    # 8. BB/100 (signed)
    bb100 = kpis.get('bb100')
    if bb100 is not None:
        _card('BB/100', f"{bb100:+.1f}", 'sec-6', _signed(bb100),
              tip='Big blinds won per 100 hands')
    else:
        _card('BB/100', '—', 'sec-6', tip='Big blinds won per 100 hands')
    # 9. True EV (signed) — fully variance-adjusted BB/100 (all 4 layers:
    # all-in equity, card quality, made-hand run, cooler frequency).
    # Ron 2026-05-31: replaced EV bb/100 (single-layer) with True EV
    # (full attribution) — one number, no confusion.
    true_ev = kpis.get('true_ev')
    if true_ev is not None:
        _card('True EV', f"{true_ev:+.1f}", 'sec-6', _signed(true_ev),
              tip='Fully variance-adjusted BB/100 (all 4 layers: all-in luck, card quality, made hands, coolers)')
    else:
        _card('True EV', '—', 'sec-6', tip='Fully variance-adjusted BB/100')
    # 10. Punts/100 (neutral)
    punts = kpis.get('punts_per_100')
    _card('Punts/100', f"{punts:.2f}" if punts is not None else '—', 'sec-2',
          tip='Punts per 100 hands')
    # 11. Mistakes/100 (neutral)
    mistakes = kpis.get('mistakes_per_100')
    _card('Mistakes/100', f"{mistakes:.2f}" if mistakes is not None else '—',
          'sec-2', tip='Confirmed mistakes per 100 hands')
    # 12. Skill (neutral — conditional, show dash if empty)
    skill = kpis.get('skill_index')
    if skill and str(skill).strip():
        _card('Skill', str(skill), 'sec-15', tip='Composite skill index')
    else:
        _card('Skill', '—', 'sec-15', tip='Composite skill index')

    strip = '\n    '.join(cards)

    # Workflow tabs — concise labels from nav_sections
    # Phase 4.8: tab labels aligned with user's desired naming.
    # S16 (Glossary) restored.
    _TAB_SHORT = {
        'S7': 'Coach', 'S1': 'Result', 'S6': 'KPIs',
        'S2': 'Top hands', 'S3': 'Leaks', 'S4': 'Tourney type',
        'S8': 'Preflop', 'S9': 'Postflop SRP', 'S10': 'Postflop 3BP/4BP',
        'S11': 'Mechanics', 'S13': 'Aggression', 'S5': 'Action Items',
        'S12': 'Progress', 'S14': 'QA', 'S15': 'Raw Stats',
        'S16': 'Glossary', 'S17': 'Deviation', 'S18': 'Appendix',
    }
    tabs = []
    if nav_sections:
        for anchor, label, _subtitle in nav_sections:
            # Extract S-label from anchor (sec-3 → S3)
            sec_num = anchor.replace('sec-', '')
            short = _TAB_SHORT.get(f'S{sec_num}', label.split(' · ')[-1] if ' · ' in label else label)
            tabs.append(
                f'<a class="wf-tab" href="#{_html_escape(anchor)}" '
                f'data-section="{_html_escape(anchor)}">{_html_escape(short)}</a>')
    tabs_html = '\n    '.join(tabs)

    return f"""<header class="topbar">
  <div class="top-title"><div class="brand-lockup">
    <div class="pb-logo" aria-hidden="true">PB</div>
    <div class="brand-copy"><h1>{player}, {date}</h1>
    <p>Poker coaching report with GTO analysis</p></div>
  </div></div>
  <div class="stat-strip">
    {strip}
  </div>
  <nav class="workflow-tabs">
    {tabs_html}
  </nav>
  <div class="section-indicator" id="section-indicator"></div>
</header>
"""


def _sidebar_html(nav_sections):
    """Phase 4.6 B4 / 4.8 C3: generate the left sidebar with collapsible
    panels — nav rail, search, and context-hands panel.
    Returns empty string if no section list supplied."""
    if not nav_sections:
        return ''
    rows = []
    for anchor, label, subtitle in nav_sections:
        rows.append(
            f'<a class="nav-row" href="#{_html_escape(anchor)}">'
            f'<b>{_html_escape(label)}</b>'
            f'<small>{_html_escape(subtitle)}</small></a>')
    nav_inner = '\n'.join(rows)
    return f"""<details class="panel nav-panel nav-collapsed">
<summary>Report order</summary>
<div class="nav-collapsed-inner">
{nav_inner}
</div>
</details>
<!-- UX-4: search panel open by default -->
<details class="panel tools" open>
<summary>Search &amp; view controls</summary>
<div class="tool-inner">
<input type="text" id="report-search" placeholder="Search hand ID, issue, section, or tournament…"
  aria-label="Search report sections">
</div>
</details>
<div class="panel">
<div class="panel-title">Review notes</div>
<div id="context-hands">
<p class="raw-ref review-empty">No hands reviewed yet. Open a hand and mark Agree / Debate / Bug to build your review queue.</p>
</div>
</div>"""


def _html_wrap(body, topbar_kpis=None, nav_sections=None,
               extra_css=None, extra_js=None):
    topbar = _topbar_html(topbar_kpis, nav_sections)
    sidebar_content = _sidebar_html(nav_sections)
    # Phase 4.8: embed report date for per-report storage key scoping (Bug B fix)
    _report_date = _html_escape(topbar_kpis.get('date', 'unknown')) if topbar_kpis else 'unknown'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pokerbot Report — {_html_escape(topbar_kpis.get('player', 'Knockman') if topbar_kpis else 'Knockman')} Session</title>
<style>
  /* Phase 4.8 C1: box-sizing reset + smooth scroll (v29 spec §2) */
  *, *::before, *::after {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  /* Phase 4.8 C1: .report-app root container (v29 spec §2) */
  .report-app {{ width: 100%; min-height: 100vh; }}
  /* Phase 4.6 B1: design tokens — single palette the whole report shares */
  :root{{
    --bg:#f6f7fb; --paper:#fff; --ink:#111827; --muted:#667085; --line:#d7dce8;
    --brand:#172554; --brand2:#1d4ed8; --soft:#eef2ff;
    --good:#166534; --bad:#991b1b; --warn:#92400e; --warnbg:#fff7cc;
    --okbg:#ecfdf3; --badbg:#fef2f2; --shadow:0 10px 30px rgba(15,23,42,.08);
  }}
  body {{ font: 15px/1.55 Inter, ui-sans-serif, system-ui, -apple-system,
    BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif !important;
    max-width: none !important; margin: 0 !important; padding: 0 !important;
    color: var(--ink) !important; background: var(--bg) !important; }}
  a {{ color: #1d4ed8; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
  h1, h2, h3 {{ color: var(--brand); line-height: 1.3; }}
  h1 {{ border-bottom: 3px solid var(--brand); padding-bottom: 0.3em; }}
  :root {{ --sticky-offset: 210px; }}
  h2 {{ margin-top: 2.2em; border-bottom: 2px solid var(--line); padding-bottom: 0.25em; scroll-margin-top: var(--sticky-offset); }}
  h3 {{ margin-top: 1.6em; color: var(--brand); scroll-margin-top: var(--sticky-offset); }}
  h4, .anchor-compat, article.hand-detail-card {{ scroll-margin-top: var(--sticky-offset); }}
  /* Bug 6: suppress raw H1 in main — topbar owns report identity */
  .main > h1:first-child {{ display: none !important; }}
  /* Hide ToC — sidebar handles navigation */
  nav.toc, a.toc-back {{ display: none !important; }}
  /* Phase 4.8: chapter cards (v29 rounded) */
  .chapter {{ background: var(--paper); border: 1px solid var(--line);
    border-radius: 22px; padding: 20px; margin-bottom: 22px;
    box-shadow: var(--shadow); }}
  .chapter > h2 {{ border: 0 !important; margin: 0 0 14px !important;
    padding: 0 !important; font-size: 24px !important; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.92em; }}
  th, td {{ border: 1px solid var(--line); padding: 0.45em 0.7em; text-align: left; vertical-align: top; }}
  th {{ background: #e9ecef; font-weight: 600; color: var(--brand); }}
  tr:nth-child(even) td {{ background: #f5f5fa; }}
  /* Phase 4.8: data-table styling (v29) */
  .table-scroll {{ overflow: auto; }}
  .data-table {{ width: 100% !important; margin: 0 !important;
    border-collapse: separate !important; border-spacing: 0 !important;
    font-size: 13px !important; }}
  .data-table th {{ position: sticky; top: 0; background: #eff4ff !important;
    color: #172554 !important; border: 0 !important;
    border-bottom: 1px solid var(--line) !important;
    padding: 0.5em 0.7em; text-align: left; font-weight: 600;
    white-space: nowrap; }}
  .data-table td {{ border: 0 !important; border-bottom: 1px solid #eef2f7 !important;
    background: #fff !important; padding: 0.45em 0.7em; vertical-align: top; }}
  .data-table tr:nth-child(even) td {{ background: #fbfdff !important; }}
  /* Phase 4.7 C3: mh-* hand card vocabulary (v29) */
  .mh-top {{ display: flex; align-items: flex-start; justify-content: space-between;
    gap: 12px; flex-wrap: wrap; }}
  .mh-title {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .mh-meta {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 12px; }}
  .mh-chip {{ display: inline-flex; align-items: center; border-radius: 999px;
    background: #f1f5f9; border: 1px solid var(--line); color: #334155;
    padding: 3px 8px; font-size: 12px; font-weight: 700; }}
  .mh-chip.bad {{ background: var(--badbg); border-color: #fecaca; color: var(--bad); }}
  .mh-chip.good {{ background: var(--okbg); border-color: #bbf7d0; color: var(--good); }}
  .mh-chip.warn {{ background: var(--warnbg); border-color: #fde68a; color: var(--warn); }}
  .context-pill {{ display: inline-block; border-radius: 999px; padding: 2px 8px;
    font-size: 11px; font-weight: 700; vertical-align: middle; margin-left: 4px; }}
  .context-pill.satellite {{ background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }}
  .context-pill.racer {{ background: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; }}
  .context-pill.mystery {{ background: #ede9fe; color: #5b21b6; border: 1px solid #c4b5fd; }}
  .context-pill.icm-caution {{ background: #fff1f2; color: #be123c; border: 1px solid #fda4af; }}
  .ev-warn {{ color: var(--warn); font-style: italic; padding: 8px; font-size: 0.9em; }}
  /* CR-G: condition pass/fail coloring for gate checks */
  .cond-pass {{ color: var(--good, #16a34a); }}
  .cond-fail {{ color: var(--bad, #dc2626); }}
  .mh-verdict {{ margin-top: 10px; color: #334155; font-size: 0.92em; line-height: 1.45; }}
  .mh-verdict b {{ color: var(--ink); }}
  .mh-links {{ margin-top: 6px; font-size: 0.85em; color: var(--muted);
    display: flex; flex-wrap: wrap; gap: 6px; }}
  .modal-stack {{ background: var(--paper); border: 1px solid var(--line);
    border-radius: 14px; margin: 10px 0; overflow: hidden; }}
  .modal-stack > summary {{ cursor: pointer; padding: 9px 12px; font-weight: 800;
    color: #334155; background: #f8fafc; list-style: none; }}
  .modal-stack > summary::-webkit-details-marker {{ display: none; }}
  code {{ background: #eee; padding: 0.12em 0.4em; border-radius: 3px;
    font-size: 0.88em; font-family: 'SF Mono', Monaco, Menlo, monospace; }}
  nav.toc {{ background: var(--paper); border: 1px solid var(--line); padding: 1em 1.5em;
    border-radius: 6px; margin: 1.5em 0; }}
  /* B167 (spec 1.2): floating Back-to-ToC heading link */
  a.toc-back {{ display: block; font-size: 0.72em; font-weight: 400;
    color: var(--muted); text-decoration: none; margin: -0.4em 0 1.1em 0;
    letter-spacing: 0.02em; }}
  a.toc-back:hover {{ color: var(--brand2); text-decoration: underline; }}
  /* B167 (spec 2.1): anti-blob whitespace — breathing room between blocks */
  p {{ margin: 0.7em 0; line-height: 1.62; }}
  ul, ol {{ margin: 0.7em 0; }}
  li {{ margin: 0.35em 0; }}
  h2 {{ margin-top: 2.2em; }}
  details {{ margin: 1em 0; }}
  nav.toc h2 {{ border: 0; margin-top: 0; }}
  nav.toc ul {{ list-style: none; padding: 0; margin: 0.5em 0 0 0; }}
  nav.toc li.toc-major {{ font-weight: 600; margin-top: 0.6em; }}
  nav.toc li.toc-sub {{ padding-left: 2em; font-size: 0.92em; font-weight: 400; }}
  nav.toc a {{ color: var(--brand2); text-decoration: none; }}
  nav.toc a:hover {{ text-decoration: underline; }}
  nav.toc .toc-summary {{ color: var(--muted); font-weight: 400; }}
  hr {{ border: 0; border-top: 1px solid var(--line); margin: 2em 0; }}
  em {{ color: var(--muted); }}
  strong {{ color: var(--ink); }}
  ul {{ padding-left: 1.5em; }}
  p {{ margin: 0.4em 0; }}
  a {{ color: var(--brand2); }}
  /* Phase 4.6 B2: layout grid — sidebar + content */
  .layout{{ display:grid; grid-template-columns:220px minmax(0,1fr); gap:18px;
    max-width:1500px; margin:0 auto; padding:18px; }}
  .sidebar{{ position:sticky; top:156px; height:calc(100vh - 170px); overflow:auto;
    align-self:start; }}
  .main{{ min-width:0; }}
  /* Phase 4.6 B3: sticky topbar + stat strip */
  .topbar{{ position:sticky; top:0; z-index:50;
    background:rgba(248,250,252,.97) !important;
    backdrop-filter:blur(10px); border-bottom:1px solid var(--line);
    box-shadow:0 2px 14px rgba(15,23,42,.05); }}
  .top-title{{ padding:8px 22px 4px; }}
  .brand-lockup{{ display:flex !important; align-items:center !important;
    gap:12px !important; min-width:0 !important; }}
  .pb-logo{{ width:42px !important; height:42px !important; border-radius:10px !important;
    background:#2f5fd0 !important; color:#fff !important;
    display:inline-flex !important; align-items:center !important;
    justify-content:center !important; font-weight:900 !important;
    font-size:14px !important; letter-spacing:.02em !important;
    box-shadow:0 6px 16px rgba(47,95,208,.22) !important;
    flex:0 0 auto !important; }}
  .brand-copy{{ min-width:0 !important; }}
  .brand-copy h1{{ font-size:24px !important; line-height:1.05 !important;
    color:#111827 !important; font-weight:850 !important;
    letter-spacing:-.02em !important; white-space:nowrap !important;
    overflow:hidden !important; text-overflow:ellipsis !important;
    margin:0 !important; border:0 !important; padding:0 !important; }}
  .brand-copy p{{ font-size:13px !important; color:#64748b !important;
    margin:5px 0 0 !important; }}
  .stat-strip{{ display:flex; gap:6px; overflow-x:auto; overflow-y:hidden;
    padding:0 22px 8px; scrollbar-width:thin; }}
  .stat-strip::-webkit-scrollbar{{ height:4px; }}
  .stat-strip::-webkit-scrollbar-thumb{{ background:#cbd5e1; border-radius:9px; }}
  .stat-card{{ flex:0 0 auto; min-width:90px; max-width:140px;
    background:#eef5ff; border:1px solid #c7d2fe;
    color:#172554; border-radius:10px; box-shadow:0 1px 0 rgba(30,64,175,.04);
    text-decoration:none; display:block; padding:5px 9px; }}
  .stat-card:hover,.stat-card:focus{{ background:#e0edff; border-color:#93c5fd;
    box-shadow:0 6px 18px rgba(59,130,246,.12); transform:translateY(-1px); }}
  .stat-card span{{ display:block; font-size:10px; color:#50658d; font-weight:800;
    text-transform:uppercase; letter-spacing:.04em; line-height:1.2; }}
  .stat-card b{{ display:block; font-size:14px; white-space:nowrap; color:#111827; }}
  .stat-card b.value-pos{{ color:#15803d !important; }}
  .stat-card b.value-neg{{ color:#b91c1c !important; }}
  .stat-card.stat-pos{{ border-color:#bbf7d0 !important; background:#effdf4 !important; }}
  .stat-card.stat-neg{{ border-color:#fecaca !important; background:#fff1f2 !important; }}
  /* Phase 4.8: workflow tabs + section indicator (v29 pill style) */
  .workflow-tabs{{ display:flex; gap:4px; overflow-x:auto; padding:0 20px 10px; }}
  .wf-tab,.workflow-tabs a{{ padding:6px 10px; border-radius:999px;
    text-decoration:none; color:#334155; font-size:13px; white-space:nowrap; }}
  .wf-tab:hover,.wf-tab.active,.workflow-tabs a.active,.workflow-tabs a:hover{{
    background:#dbeafe; color:#1e40af; }}
  .wf-tab[aria-current="true"]{{ background:#dbeafe; color:#1e40af; font-weight:600; }}
  .section-indicator{{ padding:6px 22px; border-top:1px solid #eef2f7;
    font-size:13px; color:#344054; }}
  .reading-section-chip{{ display:inline-block; background:#111827; color:#fff;
    border-radius:999px; padding:2px 8px; margin-right:8px; font-size:11px;
    text-transform:uppercase; letter-spacing:.04em; }}
  /* Phase 4.6 B4: left nav rail */
  .nav-row{{ display:block; text-decoration:none; border-radius:10px;
    padding:8px 9px; color:#1f2937; }}
  .nav-row b{{ display:block; font-size:13px; }}
  .nav-row small{{ display:block; color:var(--muted); font-size:11px; }}
  .nav-row.active,.nav-row.is-active,.nav-row:hover{{ background:var(--soft); color:#1e3a8a; }}
  /* Phase 4.8: sidebar card panels (v29) */
  .panel{{ background:var(--paper); border:1px solid var(--line);
    border-radius:16px; box-shadow:var(--shadow); padding:12px;
    margin-bottom:12px; }}
  .panel summary{{ cursor:pointer; font-size:13px; font-weight:800;
    color:#334155; padding:4px 0; user-select:none; list-style:none; }}
  .panel summary::-webkit-details-marker{{ display:none; }}
  .panel summary:hover{{ color:var(--brand2); }}
  .panel-title{{ font-weight:800; margin-bottom:8px; color:#111827; }}
  .nav-collapsed{{ padding:0 !important; overflow:hidden; }}
  .nav-collapsed > summary{{ cursor:pointer; padding:10px 12px !important;
    font-weight:800; color:#334155; list-style:none; }}
  .nav-collapsed > summary::-webkit-details-marker{{ display:none !important; }}
  .nav-collapsed-inner{{ padding:0 8px 10px; max-height:34vh; overflow:auto; }}
  .nav-collapsed:not([open]){{ background:#f8fafc; }}
  .nav-collapsed:not([open]) .nav-collapsed-inner{{ display:none; }}
  .nav-collapsed .nav-row b{{ font-size:12px !important; }}
  .nav-collapsed .nav-row small{{ display:none; }}
  .sidebar .tools{{ margin-top:0; }}
  #report-search{{ width:100%; padding:6px 10px; font-size:13px;
    border:1px solid var(--line); border-radius:8px; font-family:inherit;
    background:var(--paper); color:var(--ink); }}
  #report-search:focus{{ outline:2px solid var(--brand2); outline-offset:1px;
    border-color:var(--brand2); }}
  #context-hands{{ font-size:13px; max-height:45vh; overflow-y:auto; }}
  #context-hands .hand-ref{{ margin:2px 0; display:inline-block; }}
  .review-item{{ display:block; padding:6px 8px; margin:0 -8px 1px;
    border-radius:6px; cursor:pointer; border:none; background:none;
    text-align:left; width:calc(100% + 16px); font:inherit; color:inherit;
    line-height:1.35; }}
  .review-item:hover{{ background:var(--bg-alt,#f1f5f9); }}
  .review-item .ri-hid{{ font-weight:700; font-size:11px; color:var(--brand2);
    font-family:'Cascadia Mono','Fira Code',monospace; }}
  .review-item .ri-status{{ display:inline-block; font-size:10px; font-weight:700;
    padding:1px 5px; border-radius:4px; margin-left:4px;
    background:#e2e8f0; color:#334155; vertical-align:middle; }}
  .review-item .ri-status.s-good{{ background:#d1fae5; color:#065f46; }}
  .review-item .ri-status.s-mistake{{ background:#fee2e2; color:#991b1b; }}
  .review-item .ri-status.s-debate{{ background:#fef3c7; color:#92400e; }}
  .review-item .ri-status.s-review{{ background:#dbeafe; color:#1e40af; }}
  .review-item .ri-notes{{ display:block; font-size:12px; color:var(--muted);
    margin-top:2px; white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis; max-width:100%; }}
  .review-empty{{ color:var(--muted); font-style:italic; font-size:12px; }}
  /* metric_status CI tooltip — hover shows Wilson CI range on value cell */
  .ci-tip {{ cursor: help; color: var(--muted); font-size: 0.82em; margin-left: 0.15em; }}
  /* v7.36: cross-section reference links (_xref). Subtle so the prose itself
     isn't all blue — the icon-style links (↗) sit small at end of summary
     rows; the inline-label links (II.7, V.1) appear in tables. */
  a.xref {{ color: #5a6fa8; text-decoration: none; font-weight: 500;
    border-bottom: 1px dotted var(--line); padding: 0 1px; }}
  a.xref:hover {{ color: var(--brand2); border-bottom: 1px solid var(--brand2); }}
  /* v7.45 (Ron 2026-05-11): action display coloring for appendix preflop
     action — fold muted gray, call neutral, bet/raise emphasized, all-in
     bold red, Hero highlighted in blue. */
  span.action-fold {{ display: block; color: #888; font-size: 0.88em;
    padding: 0.1em 0.6em; margin: 0.1em 0; font-family: 'SF Mono', Monaco, Menlo, monospace; }}
  span.action-call {{ display: block; color: #333; padding: 0.15em 0.6em;
    margin: 0.1em 0; background: #f5f7f9; border-left: 3px solid #b0b7c0;
    font-family: 'SF Mono', Monaco, Menlo, monospace; }}
  span.action-bet {{ display: block; color: #6a4500; padding: 0.15em 0.6em;
    margin: 0.1em 0; background: #fff7e0; border-left: 3px solid #e6a020;
    font-family: 'SF Mono', Monaco, Menlo, monospace; }}
  span.action-raise {{ display: block; color: #a02020; padding: 0.15em 0.6em;
    margin: 0.1em 0; background: #fbeaea; border-left: 3px solid #c83030;
    font-weight: 600; font-family: 'SF Mono', Monaco, Menlo, monospace; }}
  span.action-allin {{ display: block; color: #ffffff; padding: 0.2em 0.7em;
    margin: 0.1em 0; background: #b32020; border-left: 5px solid #800;
    font-weight: 700; font-family: 'SF Mono', Monaco, Menlo, monospace; }}
  span.action-hero {{ background: #e8f0ff !important; border-left-color: #1a55c0 !important;
    color: #1a1a2e !important; }}
  span.action-allin.action-hero {{ background: #1a55c0 !important; color: #fff !important; }}
  /* B48 (v7.53, Ron 2026-05-18): Visual hand grid — GG/GTOW-style horizontal
     street layout with numbered analyst footnotes. Each street = a column,
     stacked vertically for mobile/narrow viewports. Color-coded by action
     type, hero highlighted, analyst comments inline (1), (2)... below. */
  table.hand-grid {{ width: 100%; border-collapse: collapse; margin: 0.5em 0 1em 0;
    font-family: 'SF Mono', Monaco, Menlo, monospace; font-size: 0.9em;
    table-layout: fixed; }}
  table.hand-grid th {{ background: #1a1a2e; color: #f5d75e; padding: 0.5em 0.6em;
    text-align: left; font-weight: 600; border: 1px solid #2a2a4e;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif; }}
  table.hand-grid th .pot {{ color: #9ab; font-weight: 400; font-size: 0.85em;
    display: block; margin-top: 0.1em; }}
  table.hand-grid th .cards {{ font-family: 'SF Mono', Monaco, Menlo, monospace;
    font-size: 1.05em; letter-spacing: 0.05em; color: #fff; }}
  table.hand-grid td {{ padding: 0.4em 0.5em; vertical-align: top;
    border: 1px solid #d8dbe2; background: #fafbfc; }}
  table.hand-grid td.street-actions {{ padding: 0.3em; }}
  table.hand-grid .grid-action {{ display: block; padding: 0.25em 0.55em;
    margin: 0.15em 0; border-radius: 3px; font-size: 0.85em;
    border-left: 3px solid transparent; }}
  table.hand-grid .grid-action.act-fold {{ color: #888; background: transparent;
    font-size: 0.78em; }}
  table.hand-grid .grid-action.act-check {{ color: #777; background: #f0f1f3;
    border-left-color: #b0b7c0; }}
  table.hand-grid .grid-action.act-call {{ color: #2a2a2a; background: #eef5ff;
    border-left-color: #6090d0; }}
  table.hand-grid .grid-action.act-bet {{ color: #5a3500; background: #fff4d8;
    border-left-color: #e6a020; font-weight: 600; }}
  table.hand-grid .grid-action.act-raise {{ color: #801818; background: #fce4e4;
    border-left-color: #c83030; font-weight: 600; }}
  table.hand-grid .grid-action.act-allin {{ color: #fff; background: #b32020;
    border-left-color: #800; font-weight: 700; }}
  table.hand-grid .grid-action.is-hero {{ background: #1a55c0 !important;
    color: #fff !important; border-left-color: #f5d75e !important;
    font-weight: 700; }}
  table.hand-grid .grid-action.is-hero.act-fold {{ background: #44557a !important;
    color: #cdd !important; }}
  table.hand-grid .grid-action .ann {{ display: inline-block; background: #f5d75e;
    color: #1a1a2e; font-weight: 700; padding: 1px 0.45em; border-radius: 10px;
    margin-left: 0.4em; font-size: 0.78em; vertical-align: middle;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    line-height: 1.4; }}
  /* B66 (v7.56, Ron 2026-05-18): emojis inside pills need to be much larger
     to be noticeable. Override base font-size when the pill contains only
     an emoji marker (👍 / 👎) without an (N) number — use class .ann-emoji. */
  table.hand-grid .grid-action .ann.ann-emoji {{ font-size: 1.15em;
    padding: 0 0.3em; line-height: 1.4; }}
  table.hand-grid .grid-action.is-hero .ann {{ background: #f5d75e; color: #1a1a2e; }}
  /* B57 (v7.55, Ron 2026-05-18): red 👎 marker — "good move + here's why".
     Distinguishes positive-confirming notes (red bg) from critical numbered
     notes (yellow bg) from silent good plays (yellow 👍). */
  table.hand-grid .grid-action .ann.ann-positive {{ background: #15803d; color: #fff; }}
  table.hand-grid .grid-action.is-hero .ann.ann-positive {{ background: #15803d; color: #fff; }}
  table.hand-grid .grid-action .ann.ann-positive sup {{ color: #ffe; font-size: 0.8em;
    margin-left: 0.15em; vertical-align: super; }}
  /* v8.12.8 (QA F): trigger = routing marker (amber ↪), NOT evidence —
     red is reserved for villain-tell badges (.vb-evid) */
  table.hand-grid .grid-action .ann.ann-trigger {{ background: #d97706; color: #fff; }}
  table.hand-grid .grid-action .ann.ann-trigger sup {{ color: #ffe; font-size: 0.8em;
    margin-left: 0.15em; vertical-align: super; }}
  table.hand-grid .grid-action .ann.ann-critical {{ background: #dc2626; color: #fff; }}
  table.hand-grid .grid-action .ann.ann-critical sup {{ color: #ffe; font-size: 0.8em;
    margin-left: 0.15em; vertical-align: super; }}
  /* B109 (v7.59, Ron 2026-05-19): bare 👍 — no pill background, no border.
     Standalone thumbs-up on hero actions that have NO analyst note. The
     prior .ann.ann-emoji class wrapped 👍 in a yellow pill which made the
     emoji hard to read and added visual noise — Ron flagged in 5/18 review. */
  table.hand-grid .grid-action .ann-bare {{ display: inline-block;
    margin-left: 0.4em; font-size: 1.15em; vertical-align: middle;
    line-height: 1.4; background: transparent; border: none; padding: 0;
    border-radius: 0; }}
  /* v8.12.1 R3: lazy-card placeholder + expand-all control */
  .pb-lazy-load {{ margin: 8px 14px 14px; padding: 5px 12px; border-radius: 8px;
    border: 1px dashed #94a3b8; background: #f8fafc; color: #334155;
    font-size: 12px; cursor: pointer; }}
  /* v8.12.3 (Ron QA): stacked above Copy Review Notes - was overlapping */
  #pb-expand-all {{ position: fixed; bottom: 58px; right: 10px; z-index: 9999;
    padding: 7px 12px; border-radius: 8px; border: 1px solid #1e293b;
    background: #101c2c; color: #38bdf8; font-size: 12px; cursor: pointer; }}
  /* v8.12.1 R2: hot inline styles -> classes (byte reduction; visuals identical) */
  .pb-ip {{ font-size: 0.7em; padding: 1px 4px; border-radius: 3px; font-weight: 700; }}
  .pb-ip-y {{ background: #22c55e20; color: #22c55e; }}
  .pb-ip-n {{ background: #f59e0b20; color: #f59e0b; }}
  .pb-lbl {{ font-size: 0.75em; color: var(--muted, #94a3b8); letter-spacing: 0.3px; }}
  .pb-mut-i {{ font-size: 0.8em; color: var(--muted, #888); font-style: italic; }}
  .pb-ring {{ box-shadow: 0 0 0 2px #f5d75e; border-radius: 5px; }}
  .pb-nw {{ white-space: nowrap; }}
  /* v8.12.3: 1-2 word verdict pill in the hand title bar (Ron QA) */
  .verdict-pill {{ display: inline-block; font-size: 0.55em; padding: 2px 9px;
    border-radius: 999px; background: #1e293b; color: #93c5fd;
    border: 1px solid #334155; font-weight: 800; vertical-align: middle;
    letter-spacing: 0.4px; text-transform: uppercase; }}
  .verdict-pill[data-verdict='Punt'], .verdict-pill[data-verdict='Mistake']
    {{ background: #450a0a; color: #fca5a5; border-color: #7f1d1d; }}
  .verdict-pill[data-verdict='Cooler'], .verdict-pill[data-verdict='Flip'],
  .verdict-pill[data-verdict='Suckout']
    {{ background: #1e1b4b; color: #c7d2fe; border-color: #3730a3; }}
  .verdict-pill[data-verdict='Correct'], .verdict-pill[data-verdict='Justified'],
  .verdict-pill[data-verdict='Standard']
    {{ background: #052e16; color: #86efac; border-color: #14532d; }}
  /* v8.12.0 PKO research layer: count cells + delta colors + coverage chip */
  .count-link {{ font-weight: 800; text-decoration: none;
    color: var(--brand2, #2563eb); border-bottom: 1px dotted var(--brand2, #2563eb);
    cursor: pointer; }}
  .count-link:hover, .count-link:focus {{ background: #eff6ff; border-radius: 4px; }}
  .muted-count {{ color: var(--muted, #94a3b8); }}
  .pko-delta-pos {{ color: var(--good, #16a34a); font-weight: 800; }}
  .pko-delta-neg {{ color: var(--bad, #dc2626); font-weight: 800; }}
  .pko-delta-neutral {{ color: var(--muted, #64748b); font-weight: 700; }}
  .pko-cov-chip {{ display: inline-block; font-size: 0.78em; padding: 1px 6px;
    border-radius: 999px; background: #eef2ff; color: #3730a3;
    border: 1px solid #c7d2fe; font-weight: 700; vertical-align: middle; }}
  /* v8.8.6 VH Phase 4: inline villain badges in hand grid */
  .villain-badge {{ display: inline-block; font-size: 0.7em; padding: 1px 5px;
    border-radius: 3px; margin-left: 4px; vertical-align: middle; font-weight: 700; }}
  .vb-note {{ background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; }}
  .vb-pivot {{ background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }}
  .vb-miss {{ background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }}
  .vb-good {{ background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }}
  /* v8.17 Epic 4: unified Tournament Results table + per-event drilldown modal */
  table.tt-unified th[data-tt-sort] {{ cursor: pointer; white-space: nowrap; }}
  table.tt-unified th[data-tt-sort]:hover {{ background: #eef2ff; }}
  table.tt-unified td.tt-details-cell a {{ font-weight: 600; white-space: nowrap; }}
  #tournament-detail-modal .ttd-grid {{ display: grid;
    grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 0 0 10px 0; }}
  #tournament-detail-modal .ttd-k {{ font-weight: 700; color: #475467; }}
  #tournament-detail-modal .ttd-v {{ color: #111827; }}
  #tournament-detail-modal .ttd-sub {{ margin: 12px 0 4px 0; font-size: 0.95em;
    color: #1e3a8a; }}
  #tournament-detail-modal .ttd-list {{ margin: 0 0 8px 1.1em; padding: 0; }}
  #tournament-detail-modal .ttd-list li {{ margin: 2px 0; }}
  #tournament-detail-modal .ttd-note {{ color: #475467; font-size: 0.92em; }}
  #tournament-detail-modal .ttd-hands-btn {{ margin-top: 4px; padding: 6px 14px;
    border: 1px solid #c7d2fe; border-radius: 6px; background: #eef2ff;
    color: #3730a3; font-weight: 600; cursor: pointer; }}
  #tournament-detail-modal .ttd-hands-btn:hover {{ background: #e0e7ff; }}
  html.dark #tournament-detail-modal .ttd-v {{ color: #e5e7eb; }}
  html.dark #tournament-detail-modal .ttd-k {{ color: #9ca3af; }}
  html.dark table.tt-unified th[data-tt-sort]:hover {{ background: #1e1b3a; }}
  /* mobile: keep the high-value columns; the shell already scroll-contains the rest */
  @media (max-width: 768px) {{
    table.tt-unified {{ font-size: 0.86em; }}
  }}
  /* v8.12.8 (QA F): red ! evidence badge — villain tell ON the action row,
     explained by the ❗ Note block under the grid (same atom) */
  .vb-evid {{ background: #fef2f2; color: #dc2626; border: 1px solid #fca5a5;
    font-weight: 700; }}
  div.analyst-notes {{ background: #fffbe8; border-left: 4px solid #f5d75e;
    padding: 0.7em 1em 0.7em 1em; margin: 0.5em 0 1.2em 0; border-radius: 4px; }}
  /* v8.17 Epic A §9 — the visible DECISION CAPSULE: a register-classified, scannable
     LEAD block, visually distinct from the routed detail notes below it. */
  div.analyst-notes.pb-capsule {{ background: #f1f5ff; border-left-width: 5px;
    border-left-color: #6366f1; box-shadow: 0 1px 2px rgba(15,23,42,.06);
    font-size: 0.98em; margin-bottom: 0.6em; }}
  div.analyst-notes.pb-capsule strong {{ color: #1e1b4b; }}
  div.analyst-notes.pb-cap-coaching {{ background: #fef6f1; border-left-color: #ea7c3c; }}
  div.analyst-notes.pb-cap-factual {{ background: #f0faf3; border-left-color: #3aa564; }}
  div.analyst-notes.pb-cap-no_clear_lesson {{ background: #f6f7f9; border-left-color: #94a3b8; }}
  html.dark div.analyst-notes.pb-capsule {{ background: #1e1b3a !important; border-left-color: #818cf8 !important; }}
  html.dark div.analyst-notes.pb-cap-coaching {{ background: #3a1f12 !important; border-left-color: #f59e6b !important; }}
  html.dark div.analyst-notes.pb-cap-factual {{ background: #0f2a1b !important; border-left-color: #4ade80 !important; }}
  html.dark div.analyst-notes.pb-cap-no_clear_lesson {{ background: #20242b !important; border-left-color: #94a3b8 !important; }}
  div.analyst-notes .note-num {{ display: inline-block; background: #f5d75e;
    color: #1a1a2e; font-weight: 700; padding: 0 0.5em; border-radius: 10px;
    margin-right: 0.4em; font-size: 0.85em;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif; }}
  div.analyst-notes p {{ margin: 0.35em 0; }}
  /* B96 (v7.58, Ron 2026-05-18): street-grouped notes. PRE-FLOP / FLOP /
     TURN / RIVER headers organize notes so the (N) number in the action
     grid is immediately findable under the matching street header below. */
  div.analyst-notes p.note-street {{ margin: 0.8em 0 0.3em 0;
    color: #6a4d00; letter-spacing: 0.05em; font-size: 0.82em; }}
  div.analyst-notes p.note-street:first-child {{ margin-top: 0; }}
  div.analyst-notes p.note-empty {{ color: #999; font-style: italic;
    font-size: 0.9em; }}
  /* B68 (v7.56, Ron 2026-05-18): structured-note sub-rows.
     The first sub-row has the (N) pill + emoji tag; continuation rows
     have just the emoji tag, indented to align under the first row's text. */
  div.analyst-notes p.note-cont {{ margin: 0.25em 0 0.25em 2.4em; }}
  div.analyst-notes .note-tag {{ display: inline-block; margin-right: 0.45em;
    font-size: 1.05em; vertical-align: middle; }}
  /* B146 (v7.71, Ron 2026-05-23): structured-argument rendering — TL;DR
     line, ### section sub-headers, and bulleted breakdowns. Replaces the
     prose-blob the auto-structurer produced for long analyst arguments. */
  div.analyst-notes p.note-tldr {{ margin: 0.15em 0 0.55em 0; }}
  div.analyst-notes p.note-section {{ margin: 0.75em 0 0.2em 0;
    color: #8a6d3b; letter-spacing: 0.04em; font-size: 0.8em;
    font-weight: 700; text-transform: uppercase; }}
  div.analyst-notes ul.note-bullets {{ margin: 0.2em 0 0.45em 0;
    padding-left: 1.5em; }}
  div.analyst-notes ul.note-bullets li {{ margin: 0.3em 0;
    line-height: 1.45; }}
  /* Mobile: stack streets vertically when narrow */
  @media (max-width: 720px) {{
    table.hand-grid, table.hand-grid thead, table.hand-grid tbody,
    table.hand-grid tr, table.hand-grid th, table.hand-grid td {{
      display: block; width: 100% !important; }}
    /* v8.12.9 (GPT QA P1.9 + Ron's original ask): in stacked mobile mode
       the CURRENT street header stays pinned until the next street's
       header pushes it away. Offset clears the sticky modal top bar. */
    table.hand-grid th {{ margin-top: 0.6em;
      position: sticky; top: var(--v25-topbar-h, 0px); z-index: 4; }}
  }}
  /* B52 (v7.55, Ron 2026-05-18): Suit symbols with colored backgrounds.
     Each suit gets a colored pill with white symbol+rank for readability. */
  span.card {{ display: inline-block; padding: 1px 6px; margin: 0 2px;
    border-radius: 4px; font-family: 'SF Mono', Monaco, Menlo, monospace;
    font-weight: 700; color: #ffffff !important; min-width: 22px; text-align: center;
    font-size: 1em; line-height: 1.4; vertical-align: middle;
    white-space: nowrap; }}
  /* B91 (v7.58, Ron 2026-05-18): table cells containing card pills must not
     wrap mid-pair. Default browser behavior wrapped 'A♠ J♠' to two rows
     when the column was narrow. Force the pair to stay together as a unit. */
  table td span.card:first-of-type {{ margin-left: 0; }}
  span.card-s {{ background: #3a3a3a; }}  /* spades — dark gray, not pure black (B65 v7.56) */
  span.card-h {{ background: #c83030; }}  /* hearts — red */
  span.card-d {{ background: #2070d0; }}  /* diamonds — blue */
  span.card-c {{ background: #2a8030; }}  /* clubs — green */
  /* Hero hand display (above grid) */
  div.hero-hand {{ margin: 0.4em 0 0.6em 0; font-size: 1.15em;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif; }}
  div.hero-hand .label {{ color: #888; font-size: 0.85em; margin-right: 0.5em; }}
  div.hero-hand .cards {{ font-weight: 700; }}
  div.hero-hand .hero-pos {{ color: #888; font-weight: 400; font-size: 0.92em;
    margin-left: 0.3em; }}
  /* v7.80: hole-card nickname, hand-example grid header only */
  div.hero-hand .hero-nick {{ color: #b08a3e; font-weight: 400;
    font-style: italic; font-size: 0.9em; }}
  div.hero-hand .hero-nick::before {{ content: "\u00b7"; color: #888;
    font-style: normal; margin: 0 0.4em; }}
  /* B74 (v7.56, Ron 2026-05-18): heading BB pills — green/red bg with white
     text so scanning the appendix is purely visual, no emoji ambiguity. */
  span.hand-net-pos {{ background: #2a8030; color: #ffffff !important;
    padding: 0 0.45em; border-radius: 4px; font-weight: 700; }}
  span.hand-net-neg {{ background: #c83030; color: #ffffff !important;
    padding: 0 0.45em; border-radius: 4px; font-weight: 700; }}
  span.hand-net-neu {{ background: #888; color: #ffffff !important;
    padding: 0 0.45em; border-radius: 4px; font-weight: 700; }}
  /* Pot % bracket annotation on bets/raises */
  table.hand-grid .grid-action .pot-pct {{ color: #aac; font-weight: 400;
    font-size: 0.85em; margin-left: 0.3em; }}
  table.hand-grid .grid-action.is-hero .pot-pct {{ color: #ffd; }}
  /* Result row at bottom of grid */
  table.hand-grid tfoot td.result {{ background: #1a1a2e; color: #fff;
    padding: 0.6em 0.8em; font-weight: 600;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    border-top: 2px solid #f5d75e; }}
  table.hand-grid tfoot td.result .net-pos {{ color: #6fd66f; }}
  table.hand-grid tfoot td.result .net-neg {{ color: #ff7a7a; }}
  table.hand-grid tfoot td.result .villain-card {{ display: inline-block;
    margin: 0 2px; vertical-align: middle; font-size: 1.15em; }}
  table.hand-grid tfoot td.result .sd-block {{ margin-top: 0.3em;
    font-size: 0.9em; color: #d8dbe2; }}
  table.hand-grid tfoot td.result .made-hand {{ color: #f5d75e;
    font-style: italic; font-size: 0.95em; margin-left: 0.25em; }}
  table.hand-grid tfoot td.result .board-match {{ display: inline-block;
    width: 0.5em; height: 0.5em; background: #f5d75e; border-radius: 50%;
    margin: 0 0 0.5em -0.1em; vertical-align: super; font-size: 0.5em;
    color: transparent; }}
  /* Hand replay readability bump — scoped only to the hand grid */
  table.hand-grid {{ font-size: 14px !important; line-height: 1.38 !important; }}
  table.hand-grid th {{ font-size: 14px !important; line-height: 1.28 !important; }}
  table.hand-grid th .cards {{ font-size: 1.12em !important; }}
  table.hand-grid th .pot {{ font-size: 12.5px !important; line-height: 1.35 !important; }}
  table.hand-grid th .board-tex,
  table.hand-grid th .draw-profile {{ font-size: 12px !important; line-height: 1.35 !important; }}
  table.hand-grid .grid-action,
  table.hand-grid .grid-action[style] {{ font-size: 13px !important; line-height: 1.38 !important; }}
  table.hand-grid .grid-action.act-fold,
  table.hand-grid .grid-action.act-fold[style] {{ font-size: 12px !important; }}
  table.hand-grid .grid-action .pot-pct {{ font-size: 12px !important; }}
  table.hand-grid tfoot td.result {{ font-size: 15.5px !important; line-height: 1.45 !important; }}
  table.hand-grid tfoot td.result .sd-block {{ font-size: 14px !important; line-height: 1.45 !important; }}
  table.hand-grid tfoot td.result .made-hand {{ font-size: 13.5px !important; }}
  /* Phase 4.8: audit review rows (v29 rounded cards) */
  .audit-row {{ margin: .8em 0 0 !important; border: 1px solid #d1d5db !important;
    border-left: 3px solid #cbd5e1 !important; border-radius: 10px !important;
    background: #f8fafc !important; }}
  .audit-row summary {{ padding: .35rem .65rem !important;
    font-size: 12px !important; cursor: pointer; list-style: none;
    user-select: none; color: #70708c; }}
  .audit-row summary::-webkit-details-marker {{ display: none; }}
  .audit-row.has-feedback {{ background: #f0fdf4 !important;
    border-left-color: #16a34a !important; }}
  .audit-row .audit-tag {{ font-weight: 700; color: #5a5a8e;
    letter-spacing: 0.02em; }}
  .audit-row.has-feedback .audit-tag {{ color: #2f7a3f; }}
  .audit-row .audit-context {{ color: #9a9ab0; }}
  .audit-row .audit-preview {{ font-style: italic; }}
  .audit-row.has-feedback .audit-preview {{ color: #2f7a3f;
    font-style: normal; font-weight: 600; }}
  .audit-body {{ padding: 8px 10px !important; display: flex;
    flex-direction: column; gap: 0.25em; }}
  .audit-body .audit-l {{ font-size: 0.68em; font-weight: 700; color: #9090a4;
    text-transform: uppercase; letter-spacing: 0.04em; margin-top: 0.3em; }}
  .audit-status, .audit-notes {{ width: 100%; border: 1px solid #cbd5e1;
    border-radius: 8px; padding: 7px; background: #fff; font-family: inherit;
    font-size: 0.86em; color: #1a1a2e; }}
  .audit-notes {{ resize: vertical; min-height: 2.4em; }}
  .audit-status {{ max-width: 16em; }}
  #audit-export-btn {{ position: fixed; bottom: 18px; right: 18px; z-index: 9999;
    background: #172554; color: #fff; border: 0; border-radius: 999px;
    padding: 10px 16px; font-size: 0.9em; font-weight: 700; cursor: pointer;
    box-shadow: var(--shadow); font-family: inherit; }}
  #audit-export-btn:hover {{ background: #1e3a8a; }}
  /* P1-12: de-emphasized reset — outline style, not solid red */
  #audit-reset-btn {{ position: fixed; bottom: 18px; right: 240px; z-index: 9999;
    background: #fff; color: #991b1b; border: 1px solid #fecaca; border-radius: 999px;
    padding: 10px 16px; font-size: 0.9em; font-weight: 700; cursor: pointer;
    box-shadow: 0 4px 14px rgba(15,23,42,.08); font-family: inherit; }}
  #audit-reset-btn:hover {{ background: #fef2f2; color: #7f1d1d; }}
  /* P2: Export/Import JSON as secondary pills */
  .review-json-btn {{ border: 1px solid #cbd5e1; background: #fff; color: #334155;
    border-radius: 999px; padding: 8px 12px; font-weight: 700; cursor: pointer;
    font-size: 0.85em; margin-left: 6px; font-family: inherit; }}
  .review-json-btn:hover {{ background: #f8fafc; border-color: #94a3b8; }}
  /* Phase 4.5 commit 6: contrast / readability fixes (spec §7).
     Defensive rules: ensure highlight/total/summary rows never get light-on-
     light text. Covers both existing generator output and any future table
     classes ported from redesign HTML. */
  tr.highlight td, tr.total td, tr.summary td {{ color: var(--ink); }}
  .highlight {{ background: var(--warnbg); color: var(--ink); }}
  .total {{ background: #e2e8f0; color: var(--ink); font-weight: 600; }}
  /* Ensure all standard table cells have sufficient base contrast */
  table td, table th {{ color: var(--ink); }}
  /* Override: dark-bg result rows keep their white text */
  table.hand-grid tfoot td.result,
  table.hand-grid tfoot td.result * {{ color: #fff; }}
  table.hand-grid tfoot td.result .net-pos {{ color: #6fd66f; }}
  table.hand-grid tfoot td.result .net-neg {{ color: #ff7a7a; }}
  table.hand-grid tfoot td.result .sd-block {{ color: #d8dbe2; }}
  /* Phase 4.5: hand-detail-card component (v27 spec §4) */
  article.hand-detail-card {{ max-width: 1040px; margin: 18px auto 22px;
    background: var(--paper); border: 1px solid var(--line); border-radius: 16px;
    padding: 18px; box-shadow: var(--shadow); }}
  article.hand-detail-card + hr {{ display: none; }}
  article.hand-detail-card h4,
  article.hand-detail-card h5 {{ margin-top: 0.4em; }}
  .hand-meta-chips {{ display: flex; flex-wrap: wrap; gap: 6px;
    margin: 8px 0 12px; }}
  .hand-meta-chips .chip {{ display: inline-block; background: var(--soft);
    color: var(--muted); border: 1px solid var(--line); border-radius: 6px;
    padding: 2px 10px; font-size: 0.82em; white-space: nowrap; }}
  /* Phase 4.8: GTOW button (v29 dark gradient, inside mh-actions) */
  .gtow-btn {{ display: inline-flex; align-items: center; justify-content: center;
    gap: 6px; background: linear-gradient(135deg,#101c2c 0%,#0b121f 100%);
    color: #38bdf8 !important; border: 1px solid #1e293b; border-radius: 8px;
    padding: 6px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco,
    Consolas, monospace; font-size: 11px; font-weight: 800;
    text-decoration: none !important; text-transform: uppercase;
    letter-spacing: .05em; box-shadow: 0 1px 3px rgba(0,0,0,.25);
    transition: background .15s ease, border-color .15s ease, color .15s ease; }}
  .gtow-btn:hover,.gtow-btn:focus {{ background: linear-gradient(135deg,#1e293b 0%,#0f172a 100%);
    border-color: #38bdf8; color: #fff !important;
    box-shadow: 0 0 10px rgba(56,189,248,.38); transform: translateY(-1px);
    outline: 2px solid var(--brand2); outline-offset: 2px; }}
  .gtow-btn .gtow-flash {{ color: #f5d75e; font-size: 10px; margin-right: 2px; }}
  .gtow-btn.disabled {{ background: #94a3b8; cursor: not-allowed;
    pointer-events: none; }}
  .gtow-btn.approximate {{ background: #f59e0b; color: #1e293b; }}
  /* Stack-context disclosure within cards */
  details.stack-context {{ margin: 6px 0 10px; }}
  details.stack-context summary {{ cursor: pointer; color: var(--muted);
    font-size: 0.88em; font-weight: 600; }}
  /* Phase 4.8: hand-ref pills (v29 rounded inline) */
  .hand-ref {{ display: inline-flex; align-items: center; gap: 4px;
    border: 1px solid #c7d2fe; background: #eef2ff; border-radius: 999px;
    padding: 1px 7px; text-decoration: none; white-space: nowrap; cursor: pointer; }}
  .hand-ref code {{ background: transparent !important; padding: 0 !important;
    color: #1e40af; }}
  .hand-ref.reviewed {{ background: #dcfce7; border-color: #86efac; }}
  .od-hand-row .od-hand-id.reviewed {{ background: #dcfce7 !important; border-color: #86efac !important; color: #166534 !important; }}
  .new-badge {{ font-size:0.7em; padding:1px 5px; border-radius:3px; background:#dbeafe; color:#1e40af; font-weight:700; vertical-align:middle; margin-left:4px; }}
  /* Phase 4.8 C3: relevant-hands-trigger removed — context-hands panel replaces it */
  /* Phase 4.7 C4: remaining v29 CSS selectors */
  .chip.bad {{ background: var(--badbg); color: var(--bad); }}
  .chip.good {{ background: var(--okbg); color: var(--good); }}
  .chip.warn {{ background: var(--warnbg); color: var(--warn); }}
  .section-purpose {{ background: #f8fafc; border: 1px dashed #cbd5e1;
    border-radius: 12px; color: #475467; padding: 8px 10px; margin: 8px 0 12px; }}
  /* hand-ref code and .reviewed moved to hand-ref pill block above */
  .info-dot {{ display: inline-flex; align-items: center; justify-content: center;
    width: 17px; height: 17px; border-radius: 50%; background: #e0e7ff;
    color: var(--brand2); font-size: 11px; font-weight: 800; cursor: pointer; }}
  .save-state.flash {{ animation: fadeSave 1.2s ease-out; }}
  @keyframes fadeSave {{ 0%{{opacity:0}} 20%{{opacity:1}} 100%{{opacity:0}} }}
  .method-note,.reading-note,.note-bundle {{ display: none !important; }}
  .source-raw {{ display: none; }}
  .raw-ref {{ font-size: 12px; color: #64748b; }}
  .validation-note {{ background: #fff7ed; border: 1px solid #fed7aa;
    color: #7c2d12; border-radius: 14px; padding: 12px; margin: 14px 0; }}
  .appendix-hidden-warning {{ font-size: 12px; color: #64748b; margin: 8px 0; }}
  /* v29 generic chip */
  .chip {{ display: inline-block; border-radius: 999px; padding: 2px 8px;
    background: #e2e8f0; font-size: 12px; color: #334155; }}
  /* Phase 4.8: table-shell (v29 card wrapping) */
  .table-shell {{ border: 1px solid var(--line); border-radius: 14px;
    overflow: hidden; margin: 12px 0; background: #fff; }}
  .table-toolbar {{ display: flex; align-items: center;
    justify-content: space-between; background: #f8fafc;
    border-bottom: 1px solid var(--line); padding: 8px 10px; }}
  .table-title {{ font-weight: 750; font-size: 13px; color: #1f2937; }}
  .total-row td, .is-total td {{ font-weight: 700; background: #fff7cc !important;
    color: #1f2937 !important; }}
  .data-table tr:has(td:first-child strong) td {{ background: #fff7cc !important;
    color: #1f2937 !important; font-weight: 700; }}
  .group-cell {{ background: #f8fafc !important; font-weight: 700; color: #334155; }}
  /* Phase 4.8: subsection cards (v29) */
  .subsection {{ border: 1px solid #e5e7eb; border-radius: 16px; padding: 16px;
    margin: 16px 0; background: #fff; }}
  .subsection > h3, .subsection > h4 {{ font-size: 18px !important;
    margin: 0 0 10px !important; border: 0 !important; padding: 0 !important;
    color: #172554 !important; }}
  /* Phase 4.8: coach grid (v29) */
  .coach-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px; }}
  .coach-card {{ border: 1px solid var(--line); border-radius: 16px;
    padding: 14px; background: #fff; }}
  .coach-card h3 {{ font-size: 16px; margin: 0 0 8px; color: #172554; }}
  /* Phase 4.8: Opening Dashboard — card-based TL;DR */
  .opening-dashboard {{ margin: -6px 0 18px; }}
  .od-row {{ display: grid; grid-template-columns: minmax(0,1.45fr) minmax(290px,.55fr);
    gap: 16px; align-items: stretch; margin-bottom: 16px; }}
  .opening-hero {{ background: var(--paper); border: 1px solid var(--line);
    border-radius: 24px; box-shadow: var(--shadow); padding: 22px;
    position: relative; overflow: hidden; }}
  .opening-hero::after {{ content: ""; position: absolute; right: -80px; top: -110px;
    width: 260px; height: 260px; border-radius: 50%;
    background: rgba(29,78,216,.07); pointer-events: none; }}
  .od-eyebrow {{ display: inline-flex; align-items: center; gap: 7px;
    border-radius: 999px; padding: 5px 10px; font-size: 12px; font-weight: 900;
    text-transform: uppercase; letter-spacing: .06em; }}
  .od-eyebrow-green {{ border: 1px solid #bbf7d0; background: #ecfdf3; color: #15803d; }}
  .od-eyebrow-amber {{ border: 1px solid #fde68a; background: #fffbeb; color: #92400e; }}
  .od-eyebrow-red {{ border: 1px solid #fecaca; background: #fef2f2; color: #b91c1c; }}
  .od-eyebrow-neutral {{ border: 1px solid var(--line); background: #f1f5f9; color: #475569; }}
  .od-headline {{ margin: 12px 0 8px !important; font-size: 34px !important;
    line-height: 1.06 !important; letter-spacing: -.05em !important;
    color: #0f172a !important; border: 0 !important; padding: 0 !important; }}
  .od-lead {{ max-width: 760px; margin: 0 !important; color: #475569 !important;
    font-size: 16px !important; line-height: 1.5 !important; }}
  .belief-grid {{ margin-top: 16px; display: grid; grid-template-columns: 1fr 1fr;
    gap: 10px; }}
  .belief-card {{ border: 1px solid #edf2f7; background: #fbfdff;
    border-radius: 14px; padding: 12px; }}
  .belief-card .od-label {{ display: block; color: #64748b; font-size: 11px;
    font-weight: 900; text-transform: uppercase; letter-spacing: .07em;
    margin-bottom: 4px; }}
  .belief-card .od-text {{ display: block; font-size: 14px; line-height: 1.35;
    font-weight: 600; color: #0f172a; }}
  .session-scorecard {{ background: #0f172a; color: #fff; border-radius: 24px;
    box-shadow: var(--shadow); padding: 18px; display: grid;
    align-content: space-between; gap: 14px; }}
  .session-scorecard .od-card-title {{ margin: 0; color: #e2e8f0 !important;
    font-size: 14px !important; font-weight: 800; letter-spacing: -.01em; }}
  .od-score {{ display: grid; gap: 10px; }}
  .od-score-row {{ display: grid; grid-template-columns: 1fr auto; align-items: baseline;
    gap: 10px; border-bottom: 1px solid rgba(255,255,255,.1); padding-bottom: 8px; }}
  .od-score-row:last-child {{ border-bottom: 0; padding-bottom: 0; }}
  .od-score-row .od-score-label {{ color: #94a3b8; font-weight: 850; font-size: 11px;
    text-transform: uppercase; letter-spacing: .07em; }}
  .od-score-row .od-score-val {{ font-size: 22px; font-weight: 850;
    letter-spacing: -.03em; white-space: nowrap; color: #fff; }}
  .od-score-row .od-score-val.od-green {{ color: #86efac; }}
  .od-score-row .od-score-val.od-red {{ color: #fca5a5; }}
  .od-score-note {{ color: #cbd5e1; font-size: 13px; margin: 0; }}
  .opening-metric-grid {{ display: grid; grid-template-columns: repeat(6, 1fr);
    gap: 9px; margin-bottom: 16px; }}
  .od-metric {{ border: 1px solid var(--line); background: #fff; border-radius: 14px;
    padding: 10px 12px; min-width: 0; }}
  .od-metric .od-metric-label {{ display: block; color: #64748b; font-size: 11px;
    font-weight: 900; text-transform: uppercase; letter-spacing: .07em; }}
  .od-metric .od-metric-val {{ display: block; margin-top: 4px; font-size: 17px;
    font-weight: 850; letter-spacing: -.02em; color: #0f172a; }}
  .od-metric.od-metric-good {{ background: #ecfdf3; border-color: #bbf7d0; }}
  .od-metric.od-metric-good .od-metric-val {{ color: #15803d; }}
  .od-metric.od-metric-bad {{ background: #fef2f2; border-color: #fecaca; }}
  .od-metric.od-metric-bad .od-metric-val {{ color: #b91c1c; }}
  .od-card {{ background: #fff; border: 1px solid var(--line); border-radius: 20px;
    box-shadow: 0 8px 24px rgba(15,23,42,.05); padding: 18px; }}
  .od-card-header {{ display: flex; align-items: center; justify-content: space-between;
    gap: 10px; margin-bottom: 10px; }}
  .od-card-title {{ margin: 0 !important; color: #172554 !important;
    font-size: 17px !important; font-weight: 800 !important;
    letter-spacing: -.02em !important; border: 0 !important; padding: 0 !important; }}
  .od-badge {{ display: inline-flex; align-items: center; gap: 5px;
    border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 850;
    white-space: nowrap; }}
  .od-badge-green {{ background: #ecfdf3; color: #15803d; border: 1px solid #bbf7d0; }}
  .od-badge-amber {{ background: #fffbeb; color: #92400e; border: 1px solid #fde68a; }}
  .od-badge-blue {{ background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }}
  .od-badge-purple {{ background: #f5f3ff; color: #6d28d9; border: 1px solid #ddd6fe; }}
  .od-badge-red {{ background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }}
  .od-card-desc {{ margin: 0 0 10px !important; color: #475569 !important;
    font-size: 14px !important; }}
  .variance-story-card .od-vrows {{ display: grid; gap: 8px; }}
  .variance-row {{ display: grid; grid-template-columns: auto 1fr auto; gap: 9px;
    align-items: center; padding: 9px 10px; border: 1px solid #edf2f7;
    border-radius: 13px; background: #fbfdff; }}
  .variance-row .od-vr-emoji {{ font-size: 17px; }}
  .variance-row .od-vr-title {{ font-size: 14px; font-weight: 700; color: #0f172a; }}
  .variance-row .od-vr-detail {{ display: block; color: #64748b; font-size: 12px;
    margin-top: 1px; }}
  .variance-row .od-vr-num {{ font-weight: 950; white-space: nowrap; font-size: 14px; }}
  .variance-row.od-vr-good .od-vr-num {{ color: #15803d; }}
  .variance-row.od-vr-bad .od-vr-num {{ color: #b91c1c; }}
  .next-fix-card .od-fix-list {{ display: grid; gap: 10px; }}
  .od-decision-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 10px 0; }}
  .od-dec-card {{ background: #f8fafc; border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; }}
  .od-dec-card .od-label {{ display: block; font-size: 11px; text-transform: uppercase;
    letter-spacing: .05em; color: var(--muted); font-weight: 800; margin-bottom: 4px; }}
  .od-dec-card .od-text {{ display: block; font-size: 13px; line-height: 1.5; margin: 2px 0; }}
  @media(max-width:768px){{ .od-decision-grid {{ grid-template-columns: 1fr; }} }}
  .od-top3 {{ margin: 10px 0; padding: 8px 12px; background: #fefce8; border: 1px solid #fde68a;
    border-radius: 10px; }}
  .od-top3-item {{ margin: 4px 0; font-size: 13px; }}
  .od-fix-item {{ border: 1px solid #fde68a; background: #fffbeb;
    border-radius: 16px; padding: 12px; display: grid;
    grid-template-columns: auto 1fr; gap: 10px; }}
  .od-fix-item.od-fix-blue {{ background: #eff6ff; border-color: #bfdbfe; }}
  .od-fix-item.od-fix-purple {{ background: #f5f3ff; border-color: #ddd6fe; }}
  .od-fix-rank {{ width: 30px; height: 30px; border-radius: 10px;
    display: grid; place-items: center; color: #fff; background: #172554;
    font-weight: 950; font-size: 13px; }}
  .od-fix-title {{ margin: 0 0 3px !important; font-size: 15px !important;
    font-weight: 700 !important; color: #0f172a !important;
    border: 0 !important; padding: 0 !important; }}
  .od-fix-desc {{ margin: 0 !important; font-size: 13px !important;
    color: #475569 !important; }}
  .od-fix-rule {{ margin-top: 8px; border: 1px dashed #d6dbe6; background: #fff;
    border-radius: 10px; padding: 7px 9px; color: #111827 !important;
    font-size: 12px !important; }}
  .coach-watchlist-card .od-watch-grid {{ display: grid;
    grid-template-columns: repeat(3, 1fr); gap: 9px; margin-top: 10px; }}
  .od-watch-item {{ border: 1px solid var(--line); background: #fbfdff;
    border-radius: 14px; padding: 10px; }}
  .od-watch-item .od-watch-name {{ display: block; font-size: 14px;
    font-weight: 700; color: #0f172a; }}
  .od-watch-item .od-watch-desc {{ display: block; color: #64748b;
    font-size: 12px; margin-top: 3px; }}
  .od-drill-list {{ display: grid; gap: 8px; counter-reset: od-drill; }}
  .od-drill {{ counter-increment: od-drill; display: grid;
    grid-template-columns: auto 1fr; gap: 9px; align-items: start;
    border: 1px solid #edf2f7; border-radius: 13px; padding: 9px 10px;
    background: #fbfdff; }}
  .od-drill::before {{ content: counter(od-drill); width: 22px; height: 22px;
    border-radius: 7px; display: grid; place-items: center;
    background: #e2e8f0; color: #334155; font-size: 11px; font-weight: 900; }}
  .od-drill .od-drill-text {{ margin: 0 !important; color: #334155 !important;
    font-size: 13px !important; }}
  .od-hand-queue {{ display: grid; gap: 7px; }}
  .od-hand-row {{ display: grid; grid-template-columns: auto 1fr auto;
    gap: 9px; align-items: center; border: 1px solid #edf2f7;
    background: #fbfdff; border-radius: 13px; padding: 9px 10px; }}
  .od-hand-row .od-hand-id {{ background: #eef2ff; color: #1e3a8a;
    border: 1px solid #c7d2fe; border-radius: 999px; padding: 2px 7px;
    font-size: 12px; font-weight: 900; font-family: ui-monospace, SFMono-Regular,
    Menlo, Monaco, Consolas, monospace; text-decoration: none; }}
  .od-hand-row .od-hand-info {{ font-size: 13px; font-weight: 700; color: #0f172a; }}
  .od-hand-row .od-hand-detail {{ display: block; color: #64748b; font-size: 12px; }}
  .od-hand-row .od-hand-tag {{ font-size: 12px; font-weight: 850; color: #475569; }}
  .cooler-summary-card .od-vrows {{ display: grid; gap: 8px; }}
  .od-footer-note {{ margin: 8px 0 0; color: #64748b; font-size: 13px;
    border: 1px dashed var(--line); border-radius: 14px; padding: 10px 12px;
    background: #fbfdff; }}
  /* ── v8.14.0 Slice C: Compact Hand Review Queue ── */
  .rq-card {{ padding: 0; overflow: hidden; }}
  .rq-head {{ display: flex; align-items: flex-start; justify-content: space-between;
    gap: 10px; padding: 12px 14px; border-bottom: 1px solid #eef2f7; }}
  .rq-title {{ font-weight: 950; color: var(--brand, #1e3a8a); font-size: 15px; }}
  .rq-sub {{ margin-top: 2px; font-size: 12px; color: #64748b; }}
  .rq-count {{ border-radius: 999px; border: 1px solid #facc15; background: #fffbeb;
    color: #92400e; font-weight: 900; font-size: 12px; padding: 5px 9px; white-space: nowrap; }}
  .rq-priority {{ display: flex; gap: 5px; align-items: center; overflow-x: auto;
    padding: 8px 14px; border-bottom: 1px solid #eef2f7; background: #fffdf4; }}
  .rq-priority-label {{ font-size: 11px; font-weight: 950; color: #92400e; white-space: nowrap; }}
  .rq-bcount {{ font-size: 11px; font-weight: 850; padding: 3px 7px; border: 1px solid #fde68a;
    background: #fff7cc; color: #92400e; border-radius: 999px; white-space: nowrap; }}
  /* v8.16.2 Phase E: denser open rows on desktop (less wasted space); the mobile
     @620px block below keeps 52px tap targets. rq-list caps its expanded height so
     a 20+ "Show all" scrolls WITHIN the card instead of pushing the whole page. */
  .rq-list {{ display: grid; max-height: 60vh; overflow-y: auto; }}
  .rq-row {{ display: grid; grid-template-columns: 26px auto auto auto minmax(0,1fr) auto auto;
    gap: 8px; align-items: center; padding: 6px 12px; border-bottom: 1px solid #eef2f7;
    cursor: pointer; min-height: 38px; }}
  .rq-row:hover {{ background: #f8fafc; }}
  .rq-row:focus-visible {{ outline: 2px solid var(--brand2, #2563eb); outline-offset: -2px; }}
  .rq-rank {{ width: 24px; height: 24px; border-radius: 999px; background: #eef2ff;
    color: #1e3a8a; display: grid; place-items: center; font-size: 12px; font-weight: 950; }}
  .rq-hid {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: #eef2ff; color: #1e40af; border: 1px solid #c7d2fe; border-radius: 999px;
    padding: 2px 7px; font-weight: 950; font-size: 12px; white-space: nowrap; }}
  .rq-row .handcards {{ display: inline-flex; gap: 3px; white-space: nowrap; }}
  .rq-row .reason {{ border-radius: 999px; border: 1px solid #fed7aa; background: #fff7ed;
    color: #9a3412; padding: 3px 7px; font-size: 11px; font-weight: 850; white-space: nowrap; }}
  .rq-row .reason-punt {{ background: #fef2f2; color: #991b1b; border-color: #fecaca; }}
  .rq-row .reason-analyst_mistake {{ background: #fff1f2; color: #9f1239; border-color: #fecdd3; }}
  .rq-row .reason-known_leak {{ background: #eef2ff; color: #1e40af; border-color: #c7d2fe; }}
  .rq-row .reason-auto_clear {{ background: #f0fdf4; color: #166534; border-color: #bbf7d0; }}
  .rq-row .reason-marginal {{ background: #f8fafc; color: #475569; border-color: #e2e8f0; }}
  .rq-main {{ min-width: 0; }}
  .rq-row-title {{ font-weight: 800; font-size: 13px; color: #0f172a; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; display: block; }}
  .rq-row .bb-pill {{ display: inline-flex; align-items: center; border-radius: 5px;
    padding: 1px 6px; font-size: 12px; font-weight: 950; white-space: nowrap; }}
  .rq-row .bb-pill.neg {{ background: #fee2e2; color: #991b1b; }}
  .rq-row .bb-pill.pos {{ background: #dcfce7; color: #166534; }}
  .rq-row .bb-pill.neu {{ background: #f1f5f9; color: #475569; }}
  .rq-status {{ font-size: 11px; font-weight: 900; white-space: nowrap; justify-self: end; }}
  .status-pill {{ display: inline-flex; align-items: center; gap: 4px; border-radius: 999px;
    border: 1px solid #cbd5e1; background: #f8fafc; color: #475569; padding: 2px 8px;
    font-size: 11px; font-weight: 900; white-space: nowrap; }}
  .status-pill.agree {{ background: #ecfdf3; color: #166534; border-color: #bbf7d0; }}
  .status-pill.bug {{ background: #fef2f2; color: #991b1b; border-color: #fecaca; }}
  .status-pill.debate {{ background: #fffbeb; color: #92400e; border-color: #fde68a; }}
  .status-pill.drill {{ background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }}
  .status-pill.rulebook {{ background: #f5f3ff; color: #6d28d9; border-color: #ddd6fe; }}
  .rq-row.is-reviewed {{ background: #fbfdff; }}
  .rq-reviewed {{ border-top: 1px solid #eef2f7; }}
  .rq-reviewed-head {{ width: 100%; text-align: left; border: 0; background: #f8fafc;
    cursor: pointer; padding: 9px 14px; font: inherit; font-size: 12px; font-weight: 900;
    color: #334155; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .rq-rev-label {{ white-space: nowrap; }}
  .rq-revchips {{ display: inline-flex; gap: 5px; flex-wrap: wrap; }}
  .rq-revchip {{ display: inline-flex; align-items: center; gap: 4px; border-radius: 999px;
    padding: 2px 7px; font-size: 11px; font-weight: 850; border: 1px solid #e2e8f0; background: #fff; }}
  .rq-revchip.bug {{ background: #fef2f2; color: #991b1b; border-color: #fecaca; }}
  .rq-revchip.agree {{ background: #ecfdf3; color: #166534; border-color: #bbf7d0; }}
  .rq-revchip.debate {{ background: #fffbeb; color: #92400e; border-color: #fde68a; }}
  .rq-revchip.drill {{ background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }}
  .rq-revchip.rulebook {{ background: #f5f3ff; color: #6d28d9; border-color: #ddd6fe; }}
  .rq-reviewed-list {{ display: grid; }}
  /* v8.14.1 P0-7: the .rq-reviewed-list display:grid above (author-origin, later,
     tied id/class specificity) silently beats the UA `[hidden]{{display:none}}`,
     so the collapsed reviewed-list stayed visible. Force the hidden attribute to
     win for both the wrapper and the inner list. */
  #rq-reviewed[hidden], #rq-reviewed-list[hidden] {{ display: none !important; }}
  /* v8.16.4 Obj 1: 5 cells emitted (rank|hid|cards|note|status) but the grid
     declared 4 cols, so the status pill wrapped to a 2nd line. Named grid-areas
     pin every cell to row 1 regardless of whether the optional cards cell is
     present, so the status pill is always right-aligned on a single line. */
  .rq-rev-row {{ display: grid; grid-template-columns: 26px auto auto minmax(0,1fr) auto;
    grid-template-areas: "rank hid cards note status"; gap: 8px;
    align-items: center; width: 100%; text-align: left; border: 0; background: #fff;
    border-top: 1px solid #f1f5f9; cursor: pointer; padding: 7px 14px; font: inherit; }}
  .rq-rev-row .rq-rank {{ grid-area: rank; }}
  .rq-rev-row .rq-hid {{ grid-area: hid; justify-self: start; }}
  .rq-rev-row .handcards {{ grid-area: cards; }}
  .rq-rev-row .rq-main {{ grid-area: note; min-width: 0; color: #64748b;
    font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .rq-rev-row .status-pill {{ grid-area: status; justify-self: end; white-space: nowrap; }}
  .rq-rev-row:hover {{ background: #f8fafc; }}
  /* v8.16.4 Obj 6: shared preflop range-membership highlight (green=inside,
     amber=boundary/mixed, red=outside, neutral=no exact source). Applied ON the
     range expression itself by gem_ranges.highlight_range_expression. */
  .rng-hl {{ font-weight: 800; border-radius: 5px; padding: 0 3px; }}
  .rng-hl-green {{ background: #e7f6ee; color: #0f7a48; }}
  .rng-hl-amber {{ background: #fff3d7; color: #a15c00; }}
  .rng-hl-red {{ background: #feeceb; color: #b42318; }}
  .rng-hl-neutral {{ background: #eef1f5; color: #53606f; }}
  @media(max-width:620px){{
    .rq-rev-row {{ grid-template-columns: 22px auto auto minmax(0,1fr) auto;
      padding: 8px 10px; gap: 6px; }}
  }}
  .rq-empty-win {{ padding: 18px 14px; text-align: center;
    background: linear-gradient(180deg,#ffffff,#f0fdf4); }}
  .rq-trophy {{ font-size: 26px; }}
  .rq-win-title {{ font-weight: 950; color: #166534; margin-top: 2px; }}
  .rq-win-sub {{ color: #475569; font-size: 12px; }}
  .rq-footer {{ display: flex; align-items: center; justify-content: space-between;
    gap: 8px; padding: 9px 14px; background: #f8fafc; }}
  .rq-foot-note {{ font-size: 12px; color: #475569; }}
  .rq-showall {{ border: 1px solid #c7d2fe; background: #eef2ff; color: #1e40af;
    border-radius: 999px; padding: 6px 12px; font: inherit; font-size: 12px;
    font-weight: 900; cursor: pointer; }}
  .rq-showall:hover {{ background: #dbeafe; }}
  @media(max-width:620px){{
    .rq-row {{ grid-template-columns: 22px auto minmax(0,1fr) auto;
      grid-template-areas: "rank hid main bb" "rank cards main status"; gap: 5px 6px;
      padding: 9px 10px; min-height: 52px; }}
    .rq-row .rq-rank {{ grid-area: rank; }}
    .rq-row .rq-hid {{ grid-area: hid; justify-self: start; }}
    .rq-row .handcards {{ grid-area: cards; }}
    .rq-row .reason {{ display: none; }}
    .rq-row .rq-main {{ grid-area: main; }}
    .rq-row .bb-pill {{ grid-area: bb; justify-self: end; }}
    .rq-row .rq-status {{ grid-area: status; justify-self: end; }}
    .rq-row-title {{ white-space: normal; }}
  }}
  @media(max-width:980px){{
    .od-row {{ grid-template-columns: 1fr !important; }}
    .opening-metric-grid {{ grid-template-columns: repeat(3, 1fr) !important; }}
    .coach-watchlist-card .od-watch-grid {{ grid-template-columns: 1fr !important; }}
  }}
  @media(max-width:620px){{
    .opening-hero,.session-scorecard,.od-card {{ border-radius: 16px !important;
      padding: 14px !important; }}
    .od-headline {{ font-size: 26px !important; }}
    .od-lead {{ font-size: 14px !important; }}
    .belief-grid {{ grid-template-columns: 1fr !important; }}
    .opening-metric-grid {{ grid-template-columns: repeat(2, 1fr) !important; }}
    .od-hand-row {{ grid-template-columns: 1fr !important; }}
  }}
  /* Phase 4.8: copy button (v29 fixed pill) */
  .copy-btn {{ position: fixed; right: 18px; bottom: 18px; z-index: 100;
    background: #172554; color: #fff; border: 0; border-radius: 999px;
    padding: 10px 16px; box-shadow: var(--shadow); font-weight: 700;
    cursor: pointer; font-family: inherit; }}
  .copy-btn:hover {{ background: #1e3a8a; }}
  /* Phase 4.8: v29 modal selectors */
  .modal {{ position: fixed; inset: 0; z-index: 200; display: none; }}
  .modal.is-open {{ display: block; }}
  .modal-backdrop {{ position: absolute; inset: 0; background: rgba(15,23,42,.65); }}
  .modal-panel {{ position: absolute; inset: 4vh 4vw; background: #fff;
    border-radius: 18px; box-shadow: 0 20px 80px rgba(0,0,0,.35);
    display: flex; flex-direction: column; overflow: hidden; }}
  @media (min-width:901px) {{
    .modal-panel {{ inset: auto !important; top: 4vh !important; left: 50% !important;
      right: auto !important; bottom: auto !important;
      transform: translateX(-50%) !important;
      width: min(1080px, calc(100vw - 56px)) !important;
      max-height: 92vh !important; }}
  }}
  .modal-head {{ display: flex; gap: 12px; align-items: center;
    justify-content: space-between; padding: 12px 16px;
    border-bottom: 1px solid var(--line); background: #0f172a; color: #fff; }}
  .modal-head h3 {{ margin: 0; color: #fff !important; font-size: 16px !important;
    letter-spacing: .02em; }}
  /* P2: enlarged tap targets for modal close buttons */
  .modal-head button {{ background: #fff; color: #0f172a; border: 0;
    border-radius: 999px; padding: 8px 14px; min-height: 36px;
    font-weight: 700; cursor: pointer; }}
  .modal-body {{ padding: 16px; overflow: auto; background: #f8fafc; flex: 1; }}
  .modal-review {{ border-top: 1px solid var(--line); background: #fff;
    padding: 12px 16px; }}
  .modal-review select {{ border: 1px solid #cbd5e1; border-radius: 10px;
    padding: 7px; margin-bottom: 6px; font-family: inherit; font-size: 0.88em; }}
  .modal-review textarea {{ width: 100%; min-height: 54px; border: 1px solid #cbd5e1;
    border-radius: 10px; padding: 8px; font-family: inherit; font-size: 0.88em;
    resize: vertical; }}
  /* v8.8.6: verdict chip row — replaces visible select dropdown */
  .verdict-chip-row {{ display: flex; flex-wrap: wrap; align-items: center;
    gap: 6px; margin-bottom: 8px; }}
  .verdict-chip-row .verdict-label {{ font-size: 0.78em; font-weight: 700;
    color: #9090a4; text-transform: uppercase; letter-spacing: 0.04em;
    margin-right: 2px; }}
  .verdict-chip {{ border: 1px solid #cbd5e1; background: #fff; color: #334155;
    border-radius: 999px; padding: 7px 12px; font-weight: 800; cursor: pointer;
    font-family: inherit; font-size: 0.84em; transition: background .12s, border-color .12s; }}
  .verdict-chip:hover {{ background: #f1f5f9; }}
  .verdict-chip.verdict-agree.active {{ background: #ecfdf3; border-color: #86efac;
    color: #166534; }}
  .verdict-chip.verdict-debate.active {{ background: #fffbeb; border-color: #fde68a;
    color: #92400e; }}
  .verdict-chip.verdict-bug.active {{ background: #fef2f2; border-color: #fecaca;
    color: #991b1b; }}
  /* v8.14.0 Slice C: Drill + Rulebook review statuses */
  .verdict-chip.verdict-drill.active {{ background: #eff6ff; border-color: #bfdbfe;
    color: #1d4ed8; }}
  .verdict-chip.verdict-rulebook.active {{ background: #f5f3ff; border-color: #ddd6fe;
    color: #6d28d9; }}
  .verdict-clear {{ border: 0; background: transparent; color: #64748b;
    text-decoration: underline; text-underline-offset: 3px; font-weight: 700;
    cursor: pointer; padding: 6px 4px; font-family: inherit; font-size: 0.82em; }}
  .verdict-clear:hover {{ color: #475569; }}
  /* v8.4.0: Hand queue context bar */
  .hand-queue-context {{ background: #fff; border-bottom: 1px solid var(--line);
    padding: 12px 16px; }}
  .queue-chip {{ display: inline-block; padding: 3px 7px; border-radius: 999px;
    border: 1px solid #cbd5e1; background: #fff; color: #334155;
    font-size: 11px; font-weight: 800; cursor: pointer; white-space: nowrap; }}
  .queue-chip:hover {{ background: #f1f5f9; }}
  .queue-chip.current {{ background: var(--brand); color: #fff; border-color: var(--brand); }}
  .queue-chip.viewed {{ background: #dcfce7; border-color: #86efac; color: var(--good); }}
  .btn {{ border: 1px solid #c7d2fe; background: #eef2ff; color: #1e40af;
    border-radius: 999px; padding: 5px 10px; font: inherit; font-size: 12px;
    font-weight: 800; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; }}
  .btn:hover {{ background: #dbeafe; }}
  .btn.secondary {{ background: #fff; color: #334155; border-color: #cbd5e1; }}
  .btn:disabled {{ opacity: .4; cursor: not-allowed; }}
  /* v8.4.0: Villain identity */
  .villain-pill {{ display: inline-flex; align-items: center; gap: 4px;
    border-radius: 999px; padding: 2px 7px; font-size: 11px; font-weight: 800; white-space: nowrap; }}
  .villain-tag-reg {{ background: #ffedd5; color: #7c2d12; border: 1px solid #fed7aa; }}
  .villain-tag-fish {{ background: #dbeafe; color: #1e40af; border: 1px solid #bfdbfe; }}
  .villain-tag-nit {{ background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; }}
  .villain-tag-lag {{ background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }}
  .villain-tag-station {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }}
  .villain-tag-unknown {{ background: #f5f3ff; color: #6d28d9; border: 1px solid #ddd6fe; }}
  .villain-mini {{ display: inline; padding: 1px 4px; border-radius: 4px;
    background: #fff7ed; color: #7c2d12; font-size: 10px; font-weight: 800; }}
  .modal-hand {{ max-width: 1040px; margin: 0 auto; }}
  .modal-hand-summary {{ background: #fff; border: 1px solid #dbe3ef;
    border-radius: 16px; box-shadow: 0 8px 30px rgba(15,23,42,.08);
    padding: 14px; margin-bottom: 12px; }}
  .mh-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .08em;
    color: #64748b; font-weight: 800; }}
  .mh-hand-id {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    background: #eef2ff; color: #1e3a8a; border: 1px solid #c7d2fe;
    border-radius: 999px; padding: 3px 9px; font-weight: 800; }}
  .mh-actions {{ display: flex; align-items: center; gap: 8px;
    flex-wrap: wrap; margin-left: auto; }}
  .mh-action {{ display: inline-flex; align-items: center; justify-content: center;
    gap: 6px; border-radius: 8px; border: 1px solid #cbd5e1; background: #fff;
    color: #1e3a8a !important; padding: 6px 10px; text-decoration: none !important;
    font-size: 12px; font-weight: 800; }}
  .mh-action:hover {{ background: #eff6ff; border-color: #93c5fd; }}
  .mh-actions .gtow-btn {{ margin: 0; }}
  .mh-meta .mh-chip {{ font-weight: 600; background: #f8fafc; }}
  .mh-links {{ margin-top: 6px; font-size: 12px; color: #64748b;
    display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
  .mh-links a {{ font-size: 12px; }}
  .modal-stack > summary:before {{ content: '▸'; display: inline-block;
    margin-right: 6px; color: #64748b; }}
  .modal-stack[open] > summary:before {{ content: '▾'; }}
  .modal-stack .table-shell {{ margin: 0 !important; border: 0 !important;
    border-top: 1px solid #e2e8f0 !important; border-radius: 0 !important;
    box-shadow: none !important; }}
  .modal-hand .hero-hand {{ margin: 12px 0 8px !important;
    background: #eef4ff !important; border: 1px solid #dbeafe;
    border-radius: 12px; padding: 10px 12px; font-size: 15px !important; }}
  .modal-hand .hand-grid {{ margin-top: 0 !important; }}
  /* v8.8.6 VH Phase 3: opponent coaching blocks */
  .opponent-coaching {{ margin-top: 12px; }}
  .coaching-block {{ border-radius: 10px; margin-bottom: 8px; overflow: hidden; }}
  .cb-header {{ padding: 8px 12px; font-size: 13px; }}
  .cb-header.cb-miss {{ background: #fef2f2; color: #991b1b; border-bottom: 1px solid #fecaca; }}
  .cb-header.cb-miss-c {{ background: #fffbeb; color: #92400e; border-bottom: 1px solid #fde68a; }}
  .cb-header.cb-good {{ background: #f0fdf4; color: #166534; border-bottom: 1px solid #bbf7d0; }}
  .cb-header.cb-evidence {{ background: #eff6ff; color: #1e40af; border-bottom: 1px solid #bfdbfe; }}
  .cb-body {{ padding: 8px 12px; font-size: 12px; line-height: 1.5; background: #fafbfc; }}
  .cb-body.cb-compact {{ padding: 6px 12px; }}
  .cb-villain {{ font-weight: 600; margin-bottom: 4px; }}
  .cb-timing {{ color: #64748b; font-size: 11px; margin-bottom: 4px; }}
  .cb-hero {{ margin-bottom: 4px; }}
  .cb-sowhat {{ margin-bottom: 4px; }}
  .cb-rec {{ color: #047857; font-weight: 600; }}
  .cb-note {{ color: #64748b; font-style: italic; margin-bottom: 4px; }}
  .cb-signal {{ margin-bottom: 4px; color: #475569; }}
  .cb-suggests {{ color: #4338ca; margin-bottom: 4px; }}
  .cb-street {{ color: #64748b; font-size: 11px; margin-bottom: 4px; text-transform: capitalize; }}
  .cb-oneliner {{ padding: 8px 12px; font-size: 13px; font-weight: 600;
    background: #fef9e7; border: 1px solid #fde68a; border-radius: 8px;
    margin-bottom: 8px; line-height: 1.6; }}
  .coaching-passive {{ border: 1px solid #e2e8f0; }}
  .coaching-passive > summary {{ padding: 8px 12px; font-size: 12px; color: #64748b;
    cursor: pointer; background: #f8fafc; }}
  .coaching-passive[open] {{ background: #fafbfc; }}
  .coaching-exploit_miss {{ border: 1px solid #fecaca; }}
  .coaching-good_exploit {{ border: 1px solid #bbf7d0; }}
  .coaching-villain_evidence {{ border: 1px solid #bfdbfe; }}
  .v25-ve-inline {{ border: 0 !important; background: transparent !important;
    padding: 4px 0 !important; margin-bottom: 4px !important; }}
  .v25-ve-header {{ display: flex; align-items: center; gap: 6px;
    flex-wrap: wrap; font-size: 12px; line-height: 1.35; }}
  .v25-ve-badge {{ display: inline-flex; align-items: center;
    background: #dc2626; color: #fff; border-radius: 999px;
    padding: 2px 8px; font-size: 11px; font-weight: 900; }}
  .v25-ve-type {{ color: #475569; font-weight: 700; }}
  .v25-ve-label {{ color: #0f172a; font-weight: 600; }}
  .v25-ve-line {{ font-size: 12px; line-height: 1.4; color: #334155;
    padding-left: 28px; margin-top: 2px; }}
  /* v8.13.0 villain teaching layer — compact, isolated to avoid cascade */
  .v25-teach {{ margin: 4px 10px 8px; padding: 6px 8px; border-left: 3px solid #14b8a6;
    background: #f0fdfa; border-radius: 6px; font-size: 12px; line-height: 1.45; }}
  .v25-teach-head {{ font-weight: 600; color: #0f766e; margin-bottom: 2px; }}
  .v25-teach-guard {{ color: #92400e; margin-top: 2px; }}
  .v25-teach-pko {{ color: #1e3a5f; margin-top: 2px; }}
  .v25-teach-weak {{ color: #64748b; font-style: italic; }}
  /* v8.17.0-rc3 (Villain Step-3 visible delivery): compact lesson_7part rows */
  .v25-teach-evid {{ color: #475569; font-size: 11px; margin-bottom: 2px; }}
  .v25-teach-cue {{ color: #334155; margin: 1px 0; }}
  .v25-teach-now {{ color: #0f766e; font-weight: 600; margin-top: 2px; }}
  .v25-teach-future {{ color: #475569; margin-top: 1px; }}
  .v25-teach-icm {{ color: #92400e; margin-top: 1px; font-size: 11px; }}
  .v25-teach-confchip {{ display: inline-block; font-size: 10px; font-weight: 600;
    color: #475569; background: #e2e8f0; border-radius: 999px; padding: 0 6px;
    margin-left: 4px; vertical-align: middle; }}
  /* v8.14.0 Slice D: confidence line + Natural8 candidate-tag swatch */
  .v25-teach-conf {{ color: #475569; font-size: 11px; margin-bottom: 2px; }}
  .v25-teach-tag {{ margin-top: 3px; font-weight: 600; color: #334155;
    border-left: 3px solid #cbd5e1; padding-left: 6px; }}
  .v25-teach-tag[data-tag-color="red"] {{ border-left-color: #dc2626; color: #991b1b; }}
  .v25-teach-tag[data-tag-color="purple"] {{ border-left-color: #7c3aed; color: #5b21b6; }}
  .v25-teach-tag[data-tag-color="brown"] {{ border-left-color: #92400e; color: #78350f; }}
  .v25-teach-tag[data-tag-color="orange"] {{ border-left-color: #ea580c; color: #9a3412; }}
  .v25-teach-tag[data-tag-color="pink"] {{ border-left-color: #db2777; color: #9d174d; }}
  .v25-teach-tag[data-tag-color="blue"] {{ border-left-color: #2563eb; color: #1e40af; }}
  .v25-teach-tag[data-tag-color="cyan"] {{ border-left-color: #0891b2; color: #155e75; }}
  .v25-teach-tag[data-tag-color="lime"] {{ border-left-color: #65a30d; color: #3f6212; }}
  .v25-teach-tag[data-tag-color="yellow"] {{ border-left-color: #ca8a04; color: #854d0e; }}
  .coaching-analyst_learning {{ border: 1px solid #c084fc; }}
  .cb-header.cb-learning {{ background: #faf5ff; color: #6b21a8; border-bottom: 1px solid #c084fc; }}
  .cb-analyst {{ padding: 8px 12px; font-size: 12px; background: #f0f9ff;
    border-top: 1px dashed #93c5fd; color: #1e3a5f; line-height: 1.5; }}
  .cb-analyst strong {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .cb-analyst-text {{ color: #374151; margin-top: 4px; }}
  .cb-fallback-label {{ padding: 4px 12px; font-size: 11px; color: #94a3b8;
    font-style: italic; text-align: right; }}
  /* v8.10.0: coaching card styles */
  .coach-stack {{ display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; }}
  .learn-card {{ border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;
    background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
  .learn-card.good {{ border-color: #86efac; }}
  .learn-card.warn {{ border-color: #fbbf24; }}
  .learn-card.bad {{ border-color: #f87171; }}
  .learn-card.blue {{ border-color: #93c5fd; }}
  .learn-head {{ display: flex; align-items: center; gap: 8px; padding: 8px 12px;
    background: #f8fafc; border-bottom: 1px solid #e2e8f0; }}
  .learn-card.good .learn-head {{ background: #f0fdf4; border-color: #86efac; }}
  .learn-card.warn .learn-head {{ background: #fffbeb; border-color: #fbbf24; }}
  .learn-card.bad .learn-head {{ background: #fef2f2; border-color: #f87171; }}
  .learn-card.blue .learn-head {{ background: #eff6ff; border-color: #93c5fd; }}
  .learn-title {{ font-weight: 700; font-size: 13px; color: #0f172a; flex: 1; }}
  .decision {{ display: inline-flex; padding: 2px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 700; background: #f1f5f9; color: #475569; }}
  .decision.good {{ background: #dcfce7; color: #166534; }}
  .decision.warn {{ background: #fef3c7; color: #92400e; }}
  .decision.bad {{ background: #fee2e2; color: #991b1b; }}
  .answer {{ padding: 8px 12px; font-size: 12px; line-height: 1.5; color: #334155; }}
  .metric-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px;
    padding: 4px 12px 8px; }}
  .metric-row.four {{ grid-template-columns: repeat(4, 1fr); }}
  .metric {{ text-align: center; padding: 6px 4px; background: #f8fafc;
    border-radius: 6px; border: 1px solid #e2e8f0; }}
  .metric .m-label {{ font-size: 10px; color: #64748b; text-transform: uppercase;
    letter-spacing: 0.05em; }}
  .metric .m-value {{ font-size: 14px; font-weight: 700; color: #0f172a; margin-top: 2px; }}
  .metric.money .m-value {{ color: #166534; }}
  .metric.bad .m-value {{ color: #991b1b; }}
  .range-row {{ display: grid; grid-template-columns: auto 1fr auto; gap: 6px;
    padding: 4px 12px; align-items: center; }}
  .range-v {{ font-weight: 600; font-size: 12px; color: #475569; }}
  .range-text {{ font-size: 12px; color: #0f172a; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; max-width: 200px; }}
  .range-conf {{ font-size: 10px; padding: 1px 6px; border-radius: 999px;
    background: #f1f5f9; color: #64748b; }}
  .range-conf.high {{ background: #dcfce7; color: #166534; }}
  .range-conf.medium {{ background: #fef3c7; color: #92400e; }}
  .learn-line {{ padding: 4px 12px 8px; font-size: 11px; color: #64748b;
    line-height: 1.5; }}
  .learn-line b {{ color: #475569; }}
  .source-line {{ display: flex; align-items: center; gap: 4px; padding: 4px 12px 6px;
    border-top: 1px solid #f1f5f9; }}
  .source-chip {{ font-size: 10px; padding: 1px 6px; border-radius: 999px;
    background: #f1f5f9; color: #94a3b8; }}
  @media(max-width:560px) {{
    .metric-row {{ grid-template-columns: repeat(2, 1fr); }}
    .range-row {{ grid-template-columns: 1fr; }}
    .range-text {{ max-width: 100%; }}
  }}
  /* v8.8.6 VH Phase 4: yellow street notes below hand grid */
  .villain-street-notes {{ background: #fffceb; border-left: 4px solid #f5d75e;
    padding: 6px 12px; margin: 6px 0 8px 0; border-radius: 4px; font-size: 0.85em; }}
  .villain-street-notes .vsn-entry {{ margin: 2px 0; line-height: 1.5; }}
  .villain-street-notes .vsn-header {{ margin-top: 6px; font-size: 0.9em; }}
  .villain-street-notes .vsn-street {{ display: inline-block; background: #f5d75e;
    color: #1a1a2e; font-weight: 700; padding: 0 5px; border-radius: 3px;
    font-size: 0.85em; margin-right: 4px; }}
  .villain-street-notes .vsn-villain {{ color: #64748b; font-weight: 400; }}
  .villain-street-notes .vsn-suggests {{ padding-left: 1.2em; color: #4338ca; }}
  .villain-street-notes .vsn-sowhat {{ padding-left: 1.2em; }}
  .villain-street-notes .vsn-timing {{ padding-left: 1.2em; color: #64748b; font-size: 0.9em; }}
  .modal-hand .analyst-notes {{ margin-top: 12px !important; }}
  .modal-review .save-state {{ font-size: 12px; color: #15803d;
    margin-top: 4px; opacity: 0; }}
  /* ======== V25 STREET-MERGED MODAL CSS ======== */
  :root {{ --v25-topbar-h: 58px; --v25-queue-h: 42px; --v25-review-h: 120px; --v25-street-head-h: 56px; }}
  .v25-panel {{ position: absolute; inset: 4vh 4vw; background: #fff;
    border-radius: 22px; display: flex; flex-direction: column;
    overflow-y: auto; box-shadow: 0 24px 80px rgba(15,23,42,.18); z-index: 11; }}
  .v25-topbar {{ background: #0f1736; color: #fff; padding: 10px 14px;
    min-height: var(--v25-topbar-h); display: flex; align-items: center;
    justify-content: space-between; gap: 10px; position: sticky; top: 0;
    z-index: 90; box-shadow: 0 3px 12px rgba(0,0,0,.25);
    border-radius: 22px 22px 0 0; flex-shrink: 0; }}
  .v25-top-identity {{ display: flex; align-items: center; gap: 10px;
    min-width: 0; overflow: hidden; }}
  /* v8.14.0 Slice B: "Hand" label + id are one clean cluster (same size +
     line-height); every top-bar chip uses line-height:1 so the verdict pill
     does not create a row-height jump. */
  .v25-top-hand-label {{ margin: 0; font-size: 15px; line-height: 1; font-weight: 900;
    color: #f5d75e; white-space: nowrap; align-self: center; }}
  .v25-top-hid {{ margin: 0; font-size: 15px; line-height: 1; font-weight: 900;
    white-space: nowrap; color: #fff; align-self: center; }}
  .v25-top-cards .card {{ font-size: 15px; min-width: 30px; padding: 2px 7px;
    line-height: 1; align-self: center; }}
  .v25-top-result {{ display: inline-flex; align-items: center; border-radius: 999px;
    padding: 4px 9px; font-size: 12px; font-weight: 950; line-height: 1;
    white-space: nowrap; align-self: center; }}
  /* v8.14.0 Slice B: system verdict readable but NOT dominant. Size/height from
     here (2-class selector wins over .verdict-pill's 0.55em); color stays from
     .verdict-pill[data-verdict=...] (class+attr, higher specificity). */
  .v25-top-identity .v25-top-verdict {{ display: inline-flex; align-items: center;
    gap: 6px; min-height: 28px; padding: 5px 12px; border-radius: 999px;
    font-size: 12px; font-weight: 900; line-height: 1; letter-spacing: .4px;
    text-transform: uppercase; white-space: nowrap; align-self: center;
    vertical-align: middle; }}
  .v25-top-result.good {{ background: #dcfce7; color: #166534; border: 1px solid #86efac; }}
  .v25-top-result.bad {{ background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }}
  /* GAP-15: neutral result pill */
  .v25-top-result.neutral {{ background: #f1f5f9; color: #475569; border: 1px solid #e2e8f0; }}
  .v25-top-reviewed {{ display: inline-flex; border-radius: 999px; padding: 4px 8px;
    font-size: 11px; font-weight: 950; background: #eef2ff; color: #1e3a8a;
    border: 1px solid #c7d2fe; }}
  .v25-close {{ background: #fff; color: #0f1736; border-radius: 999px;
    padding: 7px 12px; font-weight: 900; white-space: nowrap; cursor: pointer; border: 0; }}
  .v25-close:hover {{ background: #e2e8f0; }}
  /* Queue bar */
  /* GPT-QA-1: block layout so multi-row queue content stacks vertically */
  .v25-queue-bar {{ background: #fff; border-bottom: 1px solid var(--line);
    padding: 6px 10px; display: block;
    overflow-x: hidden; overflow-y: visible; position: sticky;
    /* v8.16.4 Obj 2: nav (queue) z-index ABOVE street headers (70) so a sticky
       street header can never paint over the navigation; still below topbar (90). */
    top: var(--v25-topbar-h); z-index: 80;
    box-shadow: 0 2px 8px rgba(15,23,42,.06); min-height: 0;
    flex-shrink: 0; }}
  /* V25 hand wrapper */
  .v25-hand {{ padding: 14px; padding-bottom: calc(var(--v25-review-h) + 20px);
    max-width: 1220px; margin: 0 auto; width: 100%; }}
  /* Compact summary */
  .v25-summary {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 14px;
    padding: 12px; margin-bottom: 12px; }}
  .v25-meta-bar {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center;
    margin-bottom: 6px; }}
  .v25-meta-item {{ font-size: 12px; color: #475569; background: #f1f5f9;
    border-radius: 999px; padding: 3px 8px; white-space: nowrap; }}
  .v25-meta-item.v25-tourney {{ max-width: 220px; overflow: hidden;
    text-overflow: ellipsis; }}
  .v25-decision-row {{ display: flex; gap: 8px; flex-wrap: wrap;
    align-items: center; margin-bottom: 6px; }}
  .v25-decision-chip {{ font-size: 12px; font-weight: 700; border-radius: 999px;
    padding: 3px 9px; }}
  .v25-decision-chip.warn {{ background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }}
  .v25-decision-chip.bad {{ background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }}
  .v25-decision-chip.good {{ background: #dcfce7; color: #166534; border: 1px solid #86efac; }}
  .v25-gtow-btn {{ display: inline-flex; align-items: center; gap: 4px;
    border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 800;
    background: #eef2ff; color: #1e40af; border: 1px solid #c7d2fe;
    text-decoration: none !important; white-space: nowrap; }}
  .v25-gtow-btn:hover {{ background: #dbeafe; }}
  /* GAP-10: verdict text in compact summary */
  .v25-verdict-text {{ font-size: 12px; color: #475569; line-height: 1.45;
    margin-bottom: 4px; border-left: 3px solid #e2e8f0; padding-left: 8px; }}
  .v25-mentioned {{ display: flex; gap: 5px; flex-wrap: wrap; align-items: center; }}
  .v25-chip {{ font-size: 11px; background: #f1f5f9; color: #475569;
    border-radius: 999px; padding: 3px 8px; text-decoration: none !important;
    border: 1px solid #e2e8f0; white-space: nowrap; }}
  .v25-chip.dark {{ background: #334155; color: #fff; border-color: #334155; }}
  .v25-chip:hover {{ background: #e2e8f0; }}
  /* Villain row */
  .v25-villain-row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
    background: #fefce8; border: 1px solid #fde68a; border-radius: 12px;
    padding: 8px 12px; margin-bottom: 12px; }}
  .v25-villain-token {{ display: inline-flex; align-items: center; gap: 6px;
    font-weight: 700; font-size: 13px; }}
  .v25-villain-avatar {{ width: 28px; height: 28px; border-radius: 999px;
    background: #0f1736; color: #f5d75e; display: inline-flex;
    align-items: center; justify-content: center; font-size: 11px;
    font-weight: 900; flex-shrink: 0; }}
  .v25-villain-type {{ color: #64748b; font-weight: 600; font-size: 12px; }}
  .v25-coverage-pill {{ display: inline-block; font-size: 11px; font-weight: 700;
    background: #dcfce7; color: #166534; border-radius: 999px; padding: 2px 7px;
    border: 1px solid #86efac; margin-left: 4px; }}
  /* Stack context */
  .v25-stack-details {{ border: 1px solid #e2e8f0; border-radius: 12px;
    margin-bottom: 12px; background: #fff; }}
  .v25-stack-details > summary {{ padding: 8px 12px; font-size: 13px;
    font-weight: 700; color: #475569; cursor: pointer; }}
  .v25-stack-details > summary span {{ font-size: 11px; color: #94a3b8; }}
  .v25-stack-details .table-shell {{ margin: 0 !important; border: 0 !important;
    border-top: 1px solid #e2e8f0 !important; border-radius: 0 !important;
    box-shadow: none !important; }}
  /* Street nav */
  .v25-street-nav {{ display: flex; gap: 6px; margin-bottom: 12px;
    overflow-x: auto; padding: 0 2px; }}
  .v25-street-nav a {{ display: inline-block; padding: 5px 12px;
    border-radius: 999px; font-size: 12px; font-weight: 800;
    background: #f1f5f9; color: #475569; text-decoration: none !important;
    border: 1px solid #e2e8f0; white-space: nowrap; }}
  .v25-street-nav a:hover {{ background: #e2e8f0; color: #1e293b; }}
  /* Street cards */
  .v25-street {{ background: #fff; border: 1px solid var(--line);
    border-radius: 18px; box-shadow: 0 6px 16px rgba(15,23,42,.05);
    margin-bottom: 14px; overflow: visible;
    /* P1-2: scroll-margin keeps street header visible below sticky topbar+queue */
    scroll-margin-top: calc(var(--v25-topbar-h) + var(--v25-queue-h) + 8px); }}
  .v25-street-nav {{ display: none !important; }}
  /* v8.14.0 Slice B: street context sits NEXT TO the title (flex row), not in a
     tiny far-right grid cell. Wraps cleanly under the title on narrow screens.
     Sticky behavior unchanged. */
  .v25-street-head {{ background: #121832; color: #fff; padding: 10px 12px;
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    border-radius: 17px 17px 0 0;
    position: sticky !important;
    top: calc(var(--v25-topbar-h, 58px) + var(--v25-queue-h, 0px)) !important;
    z-index: 70 !important;
    box-shadow: 0 3px 12px rgba(15,23,42,.22) !important; }}
  .v25-street-title {{ flex: 0 0 auto; font-size: 15px; font-weight: 1000;
    color: #f5d75e; letter-spacing: .04em; line-height: 1; }}
  .v25-street-context {{ display: flex; align-items: center; gap: 8px;
    min-width: 0; flex-wrap: wrap; }}
  .v25-pot-chip, .v25-strength-chip {{ display: inline-flex; align-items: center;
    border-radius: 999px; font-size: 12px; font-weight: 800; line-height: 1.25;
    padding: 5px 10px; }}
  .v25-pot-chip {{ color: #e5e7eb; border: 1px solid rgba(226,232,240,.45);
    background: rgba(15,23,42,.35); white-space: nowrap; }}
  .v25-strength-chip {{ color: #fff; border: 1px solid rgba(147,197,253,.65);
    background: rgba(29,78,216,.75); white-space: normal; }}
  .v25-street-meta {{ font-size: 12px; color: #94a3b8; }}
  .v25-street-body {{ padding: 12px; display: grid; gap: 10px; }}
  .v25-section {{ background: #f8fbff; border: 1px solid #e1e8f6;
    border-radius: 14px; padding: 11px; min-width: 0; }}
  .v25-section h4 {{ margin: 0 0 7px; color: #4b5d8e; font-size: 11px;
    text-transform: uppercase; letter-spacing: .07em; }}
  .v25-board {{ display: flex; gap: 3px; align-items: center;
    flex-wrap: nowrap; white-space: nowrap; margin-bottom: 8px; }}
  .v25-board .card {{ flex: 0 0 auto; font-size: 15px; min-width: 30px;
    padding: 2px 7px; line-height: 1.35; margin: 0; box-sizing: border-box; }}
  /* GAP-8: yellow border on newest board card per street */
  .v25-board .card.v25-new-card {{ border: 2px solid #f5d75e;
    box-shadow: 0 0 4px rgba(245,215,94,.45); }}
  .v25-hero-inline {{ display: flex; align-items: center; gap: 5px;
    flex-wrap: wrap; font-size: 15px; font-weight: 700;
    line-height: 1.35; margin-bottom: 0; }}
  .v25-hero-inline .card {{ flex: 0 0 auto; font-size: 15px; min-width: 30px;
    padding: 2px 7px; line-height: 1.35; margin: 0; box-sizing: border-box; }}
  .v25-board-section {{ padding-left: 10px; padding-right: 10px; }}
  .v25-position-pill {{ font-size: 11px; background: #eef2ff; color: #1e3a8a;
    border-radius: 999px; padding: 1px 6px; font-weight: 800;
    border: 1px solid #c7d2fe; }}
  .v25-hand-name-stage {{ font-size: 11px; color: #64748b; }}
  .v25-why-line {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    padding: 10px 12px; margin-bottom: 10px; background: #f8fafc;
    border: 1px solid #e2e8f0; border-radius: 14px; }}
  .v25-why-label {{ display: inline-flex; align-items: center; border-radius: 999px;
    background: #172554; color: #fff; padding: 4px 9px; font-size: 11px;
    font-weight: 950; letter-spacing: .06em; text-transform: uppercase; }}
  .v25-why-main {{ font-size: 14px; font-weight: 900; color: #0f172a;
    min-width: 0; overflow-wrap: anywhere; }}
  .v25-why-pill {{ display: inline-flex; align-items: center; border-radius: 999px;
    padding: 4px 9px; font-size: 12px; font-weight: 900;
    border: 1px solid #e2e8f0; background: #fff; color: #334155; white-space: nowrap; }}
  .v25-why-pill.good {{ background: #ecfdf3; border-color: #bbf7d0; color: #15803d; }}
  .v25-why-pill.warn {{ background: #fffbeb; border-color: #fde68a; color: #92400e; }}
  .v25-why-pill.bad {{ background: #fef2f2; border-color: #fecaca; color: #b91c1c; }}
  .v25-commentary-more {{ overflow: hidden; }}
  .is-collapsible .v25-commentary-more {{ max-height: 160px;
    -webkit-mask-image: linear-gradient(black 60%, transparent);
    mask-image: linear-gradient(black 60%, transparent); }}
  .is-collapsible.is-open .v25-commentary-more {{ max-height: none;
    -webkit-mask-image: none; mask-image: none; }}
  .v25-commentary-toggle {{ display: block; margin: 8px auto 0; padding: 5px 14px;
    border-radius: 999px; border: 1px solid #e2e8f0; background: #f8fafc;
    color: #334155; font-size: 12px; font-weight: 700; cursor: pointer; }}
  .v25-commentary-toggle:hover {{ background: #e2e8f0; }}
  .v25-no-commentary {{ color: #94a3b8; font-size: 12px; font-style: italic; margin: 0; }}
  /* V25 action spans in street body (GAP-1 v8.9.1: full styling parity) */
  .v25-section .grid-action {{ display: block; padding: 0.25em 0.55em;
    border-bottom: 1px solid #f0f2f5; font-size: 13px; line-height: 1.38;
    border-radius: 6px; margin-bottom: 1px; }}
  .v25-section .grid-action:last-child {{ border-bottom: 0; }}
  .v25-section .grid-action.act-fold {{ color: #888; background: transparent;
    font-size: 12px; opacity: .85; }}
  .v25-section .grid-action.act-check {{ color: #777; background: #f0f1f3;
    border-left: 3px solid #bfc5d1; }}
  .v25-section .grid-action.act-call {{ color: #2a2a2a; background: #eef5ff;
    border-left: 3px solid #7faef5; }}
  .v25-section .grid-action.act-bet {{ color: #5a3500; background: #fff4d8;
    border-left: 3px solid #f5c542; }}
  .v25-section .grid-action.act-raise {{ color: #801818; background: #fce4e4;
    border-left: 3px solid #e07070; }}
  .v25-section .grid-action.act-allin {{ color: #fff; background: #b32020;
    font-weight: 700; border-left: 3px solid #7f1616; }}
  .v25-section .grid-action.is-hero {{ background: #1a55c0 !important;
    color: #fff !important; font-weight: 700; border-left: 3px solid #0d3a8c; }}
  .v25-section .grid-action.is-hero.act-fold {{ background: #44557a !important;
    color: #c4cfe0 !important; }}
  .v25-section .grid-action .ann {{ display: inline-block; background: #f5d75e;
    color: #1a1a2e; border-radius: 4px; padding: 0 5px; font-weight: 700;
    font-size: 0.85em; vertical-align: middle; margin-left: 3px; }}
  .v25-section .grid-action .ann.ann-emoji {{ font-size: 1.15em;
    background: transparent; padding: 0; }}
  .v25-section .grid-action.is-hero .ann {{ background: #f5d75e; color: #1a1a2e; }}
  .v25-section .grid-action .ann.ann-positive {{ background: #15803d; color: #fff; }}
  .v25-section .grid-action.is-hero .ann.ann-positive {{ background: #15803d; color: #fff; }}
  .v25-section .grid-action .ann.ann-positive sup {{ color: #ffe; font-size: 0.8em;
    vertical-align: baseline; position: relative; top: -0.3em; }}
  .v25-section .grid-action .ann.ann-trigger {{ background: #d97706; color: #fff; }}
  .v25-section .grid-action .ann.ann-trigger sup {{ color: #ffe; font-size: 0.8em;
    vertical-align: baseline; position: relative; top: -0.3em; }}
  .v25-section .grid-action .ann.ann-critical {{ background: #dc2626; color: #fff; }}
  .v25-section .grid-action .ann.ann-critical sup {{ color: #ffe; font-size: 0.8em;
    vertical-align: baseline; position: relative; top: -0.3em; }}
  .v25-section .grid-action .ann-bare {{ display: inline-block; margin-left: 0.4em;
    font-size: 1.15em; vertical-align: middle; line-height: 1.4;
    background: transparent; border: none; padding: 0; border-radius: 0; }}
  .v25-section .grid-action .pot-pct {{ color: #aac; font-weight: 400;
    font-size: 12px; }}
  .v25-section .grid-action.is-hero .pot-pct {{ color: #ffd; }}
  /* Result box */
  .v25-result-box {{ background: #f8fafc; border: 1px solid #e2e8f0;
    border-radius: 14px; padding: 14px; font-size: 14px; font-weight: 700;
    margin-bottom: 14px; line-height: 1.6; }}
  .v25-result-box .net-pos {{ color: #166534; font-weight: 900; }}
  .v25-result-box .net-neg {{ color: #991b1b; font-weight: 900; }}
  .v25-result-box .sd-block {{ font-size: 12px; font-weight: 400;
    color: #64748b; margin-top: 4px; }}
  /* GAP-9: made-hand, villain-card, board-match styling in V25 result box */
  .v25-result-box .made-hand {{ color: #b45309; font-style: italic;
    font-size: 13px; font-weight: 600; margin-left: 0.25em; }}
  .v25-result-box .villain-card {{ display: inline-block; margin: 0 2px;
    vertical-align: middle; font-size: 1.15em; }}
  .v25-result-box .board-match {{ display: inline-block; width: 0.5em;
    height: 0.5em; background: #f5d75e; border-radius: 50%;
    margin: 0 0 0.5em -0.1em; vertical-align: super; font-size: 0.5em;
    color: transparent; }}
  /* Disclosures */
  .v25-disclosure {{ border: 1px solid #e2e8f0; border-radius: 14px;
    margin-bottom: 12px; background: #fff; }}
  .v25-disclosure > summary {{ padding: 10px 14px; font-weight: 700;
    font-size: 13px; cursor: pointer; color: #334155; }}
  .v25-disclosure[open] > summary {{ border-bottom: 1px solid #e2e8f0; }}
  .v25-disclosure .coaching-block {{ margin: 6px 10px; }}
  /* Trimmed fallback */
  .v25-trimmed-fallback {{ padding: 32px 16px; text-align: center; }}
  .v25-trimmed-msg {{ color: #64748b; font-size: 14px; background: #f8fafc;
    border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px;
    max-width: 420px; margin: 0 auto; }}
  /* V25 modal-body: NO overflow (scroll container is .v25-panel) */
  .v25-panel .modal-body {{ overflow: visible; padding: 0; flex: 1 1 auto; }}
  /* V25 modal-review: sticky bottom */
  .v25-panel .modal-review {{ position: sticky; bottom: 0; z-index: 80;
    background: #fff; border-top: 1px solid var(--line);
    padding: 10px 14px; box-shadow: 0 -3px 12px rgba(15,23,42,.08);
    border-radius: 0 0 22px 22px; flex-shrink: 0; }}
  /* ---- V25 mobile overrides ---- */
  @media(max-width:768px){{
    .v25-panel {{ inset: 0; border-radius: 0; }}
    /* v8.14.0 Slice B: top identity + street header WRAP cleanly on mobile
       (no horizontal overflow; pills stay readable but compact). */
    .v25-topbar {{ border-radius: 0; min-height: 0; }}
    .v25-top-identity {{ flex-wrap: wrap; overflow: visible; row-gap: 6px; }}
    .v25-top-hand-label {{ font-size: 13px; }}
    .v25-top-identity .v25-top-verdict {{ font-size: 11px; min-height: 24px; padding: 4px 9px; }}
    .v25-pot-chip, .v25-strength-chip {{ font-size: 11px; padding: 4px 8px; }}
    .v25-street-body {{ grid-template-columns: 1fr; padding: 10px; gap: 9px; }}
    .v25-top-hid {{ font-size: 13px; }}
    .v25-top-cards .card {{ font-size: 11.5px; }}
    .v25-top-result {{ font-size: 10.5px; padding: 3px 6px; }}
    .v25-meta-bar {{ display: flex; overflow-x: auto; gap: 5px;
      scrollbar-width: thin; flex-wrap: nowrap; }}
    .v25-meta-item {{ flex: 0 0 auto; font-size: 11px; }}
    .v25-hand {{ padding: 10px; padding-bottom: calc(var(--v25-review-h) + 20px); }}
    .v25-panel .modal-review {{ border-radius: 0; }}
  }}
  /* V25.3 item 15: scroll-container model (guardrails 2+3) */
  .modal-panel.v25-panel {{ overflow-x: hidden !important; overflow-y: auto !important; }}
  /* V25.3 item 15: desktop panel width + unequal column grid */
  @media (min-width: 1200px) {{
    .modal-panel.v25-panel {{ inset: 4vh auto !important;
      width: min(1320px, calc(100vw - 56px)) !important;
      left: 50% !important; transform: translateX(-50%) !important; }}
    .v25-street-body {{ grid-template-columns: 190px 390px minmax(0, 1fr); gap: 8px; padding: 12px; }}
  }}
  @media (min-width: 900px) and (max-width: 1199px) {{
    .modal-panel.v25-panel {{ inset: 4vh auto !important;
      width: min(1180px, calc(100vw - 56px)) !important;
      left: 50% !important; transform: translateX(-50%) !important; }}
    .v25-street-body {{ grid-template-columns: 190px 360px minmax(0, 1fr); gap: 8px; padding: 12px; }}
  }}
  @media (max-width: 899px) {{
    .v25-street-body {{ grid-template-columns: 1fr; }}
  }}
  /* v8.16.2 Phase C — Sticky Hand Context. Within each street card the Board/Hero
     and Action columns pin BELOW the sticky street header while the (often long)
     Commentary column scrolls past. Sticky is bounded by .v25-street-body so it
     never overflows into the next street; z-index 30 stays under the street
     header (70) so the header always covers it; align-self:start is required for
     sticky to move inside a grid row. */
  @media (min-width: 900px) {{
    .v25-board-section, .v25-action-section {{
      position: sticky; align-self: start; z-index: 30;
      top: calc(var(--v25-topbar-h, 58px) + var(--v25-queue-h, 0px)
                + var(--v25-street-head-h, 56px) + 8px);
      max-height: calc(100vh - var(--v25-topbar-h, 58px) - var(--v25-queue-h, 0px)
                - var(--v25-street-head-h, 56px) - var(--v25-review-h, 120px) - 28px);
      overflow-y: auto; overflow-x: hidden; background: #f8fbff; border-radius: 14px; }}
  }}
  /* Mobile / narrow: ONE shared renderer — only the compact Board/Hero strip
     pins (a sticky action column would crowd the narrow viewport). Still bounded
     by .v25-street-body and offset below the sticky street header. */
  @media (max-width: 899px) {{
    .v25-board-section {{
      position: sticky; z-index: 30; background: #f8fbff;
      top: calc(var(--v25-topbar-h, 58px) + var(--v25-queue-h, 0px)
                + var(--v25-street-head-h, 56px) + 4px);
      box-shadow: 0 2px 8px rgba(15,23,42,.10); border-radius: 12px; }}
  }}
  /* V25.3 item 15: overflow prevention for grid columns */
  .v25-commentary-section p {{ overflow-wrap: anywhere; }}
  /* V25.3 item 10: compact queue header */
  .v25-compact-queue {{ padding: 8px 12px; background: #fff;
    border-bottom: 1px solid var(--line); max-width: 100%; overflow: hidden; }}
  .v25-queue-main-row {{ display: flex; align-items: center; gap: 8px; min-width: 0; }}
  .v25-queue-title-block {{ flex: 1 1 auto; min-width: 0; }}
  .v25-queue-title {{ font-weight: 850; color: #172554; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; line-height: 1.25; }}
  .v25-queue-subtitle {{ color: #64748b; font-size: 12px; margin-top: 1px;
    white-space: nowrap; }}
  .v25-queue-btn {{ flex: 0 0 auto; border: 1px solid #c7d2fe; background: #eef2ff;
    color: #1e40af; border-radius: 999px; padding: 6px 10px; font: inherit;
    font-size: 12px; font-weight: 850; cursor: pointer; }}
  .v25-queue-btn.secondary {{ background: #fff; color: #334155; border-color: #cbd5e1; }}
  .v25-queue-chip-rail {{ display: flex; gap: 5px; overflow-x: auto; overflow-y: hidden;
    max-width: 100%; padding: 7px 0 1px; scrollbar-width: thin; }}
  .v25-queue-chip {{ flex: 0 0 auto; border: 1px solid #cbd5e1; background: #fff;
    color: #334155; border-radius: 999px; padding: 3px 8px; font-size: 11px;
    font-weight: 850; white-space: nowrap; cursor: pointer; }}
  .v25-queue-chip.current {{ background: #172554; color: #fff; border-color: #172554; }}
  .v25-queue-chip.viewed {{ background: #dcfce7; color: #166534; border-color: #86efac; }}
  /* P2: queue reason + also-appears-in classes (replace inline styles) */
  .v25-queue-reason {{ margin-top: 6px; border-left: 3px solid #f59e0b;
    background: #fffbeb; padding: 5px 10px; border-radius: 6px;
    font-size: 12px; color: #4b5563; }}
  .v25-queue-also {{ font-size: 11px; color: var(--muted); margin-top: 4px; }}
  /* V25.3 item 10: compact queue mobile */
  @media (max-width: 640px) {{
    .v25-queue-main-row {{ display: grid; grid-template-columns: auto 1fr auto;
      grid-template-areas: "prev back next" "title title title"; gap: 6px; }}
    .v25-queue-prev {{ grid-area: prev; }}
    .v25-queue-back {{ grid-area: back; justify-self: center; }}
    .v25-queue-next {{ grid-area: next; justify-self: end; }}
    .v25-queue-title-block {{ grid-area: title; }}
    .v25-queue-title {{ font-size: 13px; }}
    .v25-compact-queue {{ padding: 7px 10px; }}
  }}
  /* List popup — hand-evidence tables/lists shown inline */
  #list-modal .modal-body {{ padding: 16px 20px; }}
  #list-modal .modal-body h3,
  #list-modal .modal-body h4,
  #list-modal .modal-body h5 {{ margin: 16px 0 8px; font-size: 14px; color: #334155; }}
  #list-modal .modal-body h3:first-child,
  #list-modal .modal-body h4:first-child,
  #list-modal .modal-body h5:first-child {{ margin-top: 0; }}
  #list-modal .modal-body .table-shell {{ margin: 8px 0 16px; }}
  #list-modal .modal-body ul {{ padding-left: 1.4em; }}
  #list-modal .modal-body li {{ margin-bottom: 10px; line-height: 1.5; }}
  #list-modal .modal-body details {{ margin: 8px 0; background: #fff;
    border: 1px solid #e2e8f0; border-radius: 12px; }}
  #list-modal .modal-body details > summary {{ padding: 10px 14px; font-weight: 700;
    cursor: pointer; }}
  #list-modal .modal-body details[open] > summary {{ border-bottom: 1px solid #e2e8f0; }}
  #list-modal .modal-body p {{ margin: 6px 0; }}
  /* Tooltip popover */
  .tooltip-pop {{ position: fixed; z-index: 300; max-width: 320px;
    background: #111827; color: #fff; border-radius: 10px; padding: 9px 11px;
    font-size: 13px; box-shadow: 0 12px 40px rgba(0,0,0,.25); display: none; }}
  .tooltip-pop.is-open {{ display: block; }}
  /* Phase 4.8: mobile responsive (v29) */
  @media(max-width:900px){{
    .layout{{ display:block !important; padding:10px !important; }}
    .sidebar{{ position:static !important; height:auto !important; }}
    .nav-collapsed{{ display:none !important; }}
    .nav-panel{{ display:flex; overflow:auto; gap:4px; padding:8px; }}
    .nav-panel .panel-title{{ display:none; }}
    .nav-row{{ min-width:110px; white-space:nowrap; padding:6px 12px;
      font-size:12px; }}
    .nav-row small{{ display:none; }}
    .top-title{{ padding:10px 12px 8px !important; }}
    .pb-logo{{ width:38px !important; height:38px !important; border-radius:9px !important; }}
    .brand-copy h1{{ font-size:20px !important; }}
    .brand-copy p{{ font-size:12px !important; }}
    .stat-strip{{ display:grid !important; grid-template-columns:repeat(3,minmax(0,1fr)) !important;
      overflow:visible !important; gap:6px !important; padding:0 12px 8px !important; }}
    .workflow-tabs{{ padding:0 12px 8px !important; }}
    .section-indicator{{ padding:5px 12px; }}
    .chapter{{ padding:14px; border-radius:16px; }}
    .subsection{{ padding:12px; }}
    .coach-grid{{ grid-template-columns:1fr; }}
    .main{{ max-width:100%; }}
    .modal-panel{{ inset:0; border-radius:0; }}
    .modal-hand-summary{{ border-radius:12px; padding:10px; }}
    .mh-top{{ display:block; }}
    .mh-actions{{ margin-top:10px; }}
    .mh-actions .gtow-btn,.mh-action{{ width:100%; }}
    .mh-meta{{ gap:5px; }}
    .modal-body{{ padding:10px !important; }}
    .modal-hand .hero-hand{{ font-size:14px !important; }}
    /* Table card-mode: only tables WITHOUT explicit mobile mode */
    .table-shell:not([data-mobile-mode]) .data-table,
    .table-shell:not([data-mobile-mode]) .data-table thead,
    .table-shell:not([data-mobile-mode]) .data-table tbody,
    .table-shell:not([data-mobile-mode]) .data-table tr,
    .table-shell:not([data-mobile-mode]) .data-table th,
    .table-shell:not([data-mobile-mode]) .data-table td{{ display:block !important; width:100% !important; }}
    .table-shell:not([data-mobile-mode]) .data-table thead{{ display:none !important; }}
    .table-shell:not([data-mobile-mode]) .data-table tr{{ border-bottom:1px solid var(--line); padding:8px; }}
    .table-shell:not([data-mobile-mode]) .data-table td{{ display:grid !important;
      grid-template-columns:40% 1fr; gap:8px;
      border:0 !important; padding:5px 2px !important; }}
    .table-shell:not([data-mobile-mode]) .data-table td:before{{ content:attr(data-label);
      font-weight:700; color:#64748b; }}
    .table-shell:not([data-mobile-mode]) .data-table td[rowspan]{{ display:grid !important; }}
    .table-shell:not([data-mobile-mode]) .table-scroll{{ overflow:visible; }}
    .copy-btn{{ left:12px; right:12px; width:calc(100% - 24px); }}
    #audit-export-btn{{ left:12px; right:auto; width:calc(50% - 18px); }}
    #audit-reset-btn{{ left:auto; right:12px; width:calc(50% - 18px); bottom:18px; }}
    /* v8.6.1: mobile table fixes — prevent truncation from desktop rules */
    .table-shell:not([data-mobile-mode]) .data-table td{{ max-width:none !important; white-space:normal !important;
      overflow:visible !important; }}
    /* User-QA-1: scroll-mode tables must stay real tables — override card-mode rules */
    [data-mobile-mode="scroll"] .data-table {{ display: table !important; }}
    [data-mobile-mode="scroll"] .data-table thead {{ display: table-header-group !important; }}
    [data-mobile-mode="scroll"] .data-table tbody {{ display: table-row-group !important; }}
    [data-mobile-mode="scroll"] .data-table tr {{ display: table-row !important; border-bottom: 0; padding: 0; }}
    [data-mobile-mode="scroll"] .data-table th,
    [data-mobile-mode="scroll"] .data-table td {{ display: table-cell !important; width: auto !important; }}
    [data-mobile-mode="scroll"] .data-table td {{ grid-template-columns: unset; }}
    [data-mobile-mode="scroll"] .data-table td:before {{ content: none; }}
    code,pre,.raw-ref{{ overflow-wrap:anywhere; word-break:break-word; }}
  }}
  /* v8.8.8 PRD: mobile sticky header — only nav tabs stay sticky.
     display:contents unwraps .topbar so .workflow-tabs can stick independently. */
  @media(max-width:768px){{
    :root{{ --sticky-offset:50px; }}
    .topbar{{ display:contents !important; }}
    .workflow-tabs{{ position:sticky !important; top:0 !important; z-index:60 !important;
      background:rgba(248,250,252,.98) !important; backdrop-filter:blur(10px);
      border-bottom:1px solid var(--line); padding:6px 12px !important;
      box-shadow:0 2px 8px rgba(15,23,42,.06);
      scrollbar-width:none; }}
    .workflow-tabs::-webkit-scrollbar{{ display:none; }}
    .section-indicator{{ display:none !important; }}
    html.dark .workflow-tabs{{ background:rgba(30,41,59,.98) !important; }}
  }}
  @media(max-width:600px){{
    .stat-strip{{ display:flex !important; overflow-x:auto !important;
      grid-template-columns:none !important; gap:6px !important; }}
    .stat-card{{ min-width:120px; }}
  }}
  @media(max-width:480px){{
    .stat-strip{{ display:grid !important; grid-template-columns:repeat(2,minmax(0,1fr)) !important;
      overflow:visible !important; gap:6px !important; }}
    .stat-card{{ padding:7px 9px !important; }}
    .stat-card b{{ font-size:14px !important; }}
  }}

  /* ==== MOBILE TABLE READABILITY SYSTEM (PRD 2026-06-10) ==== */
  /* Desktop: hide mobile-only views */
  .mobile-hand-list {{ display: none; }}
  .mobile-evidence-list {{ display: none; }}
  @media(max-width:768px){{
    /* ── Mode: scroll — dense metric/matrix tables ── */
    [data-mobile-mode="scroll"] {{
      position: relative;
    }}
    [data-mobile-mode="scroll"]::before {{
      content: "←  swipe table  →";
      display: block;
      padding: 6px 10px;
      color: #64748b;
      font-size: 11px;
      font-weight: 800;
      background: #f8fafc;
      border-bottom: 1px solid var(--line);
    }}
    [data-mobile-mode="scroll"] .table-scroll {{
      overflow-x: auto;
      overflow-y: visible;
      -webkit-overflow-scrolling: touch;
    }}
    /* Generic min-width fallback for non-.table-shell scroll containers (e.g. IE drilldown) */
    [data-mobile-mode="scroll"] table {{
      min-width: var(--mobile-table-min-width, 860px);
    }}
    .table-shell[data-mobile-mode="scroll"] .data-table {{
      display: table !important;
      width: max-content !important;
      min-width: var(--mobile-table-min-width, 860px) !important;
      border-collapse: separate !important;
      border-spacing: 0 !important;
    }}
    .table-shell[data-mobile-mode="scroll"] .data-table thead {{ display: table-header-group !important; }}
    .table-shell[data-mobile-mode="scroll"] .data-table tbody {{ display: table-row-group !important; }}
    .table-shell[data-mobile-mode="scroll"] .data-table tr {{
      display: table-row !important;
      width: auto !important;
      padding: 0 !important;
      border-bottom: 0 !important;
    }}
    .table-shell[data-mobile-mode="scroll"] .data-table th,
    .table-shell[data-mobile-mode="scroll"] .data-table td {{
      display: table-cell !important;
      width: auto !important;
      min-width: auto !important;
      max-width: none !important;
      padding: 7px 10px !important;
      border-bottom: 1px solid #eef2f7 !important;
      white-space: nowrap !important;
      vertical-align: middle !important;
    }}
    .table-shell[data-mobile-mode="scroll"] .data-table td::before {{
      content: none !important;
      display: none !important;
    }}
    .table-shell[data-mobile-mode="scroll"] .data-table th {{
      background: #eff4ff !important;
      color: #172554 !important;
      font-weight: 800 !important;
    }}
    .table-shell[data-mobile-mode="scroll"] .data-table th:first-child,
    .table-shell[data-mobile-mode="scroll"] .data-table td:first-child {{
      position: sticky !important;
      left: 0 !important;
      z-index: 2 !important;
      background: #fff !important;
      box-shadow: 1px 0 0 #d7dce8 !important;
    }}
    .table-shell[data-mobile-mode="scroll"] .data-table th:first-child {{
      z-index: 3 !important;
      background: #eff4ff !important;
    }}
    .table-shell[data-mobile-mode="scroll"] .data-table td.long-text,
    .table-shell[data-mobile-mode="scroll"] .data-table td.notes,
    .table-shell[data-mobile-mode="scroll"] .data-table td[data-label="Why"],
    .table-shell[data-mobile-mode="scroll"] .data-table td[data-label="Detail"],
    .table-shell[data-mobile-mode="scroll"] .data-table td[data-label="What to do"] {{
      white-space: normal !important;
      min-width: 260px !important;
      max-width: 360px !important;
      vertical-align: top !important;
    }}
    /* ── Mode: hand-list — compact poker hand rows ── */
    /* Only hide table when JS-generated replacement exists */
    [data-mobile-mode="hand-list"].has-mobile-cards > table,
    [data-mobile-mode="hand-list"].has-mobile-cards > .table-scroll > table {{
      display: none;
    }}
    /* Fallback: if no mobile cards, keep table scrollable */
    [data-mobile-mode="hand-list"]:not(.has-mobile-cards) > .table-scroll {{
      overflow-x: auto; -webkit-overflow-scrolling: touch;
    }}
    [data-mobile-mode="hand-list"] .mobile-hand-list {{
      display: block;
      padding: 8px 10px 10px;
      background: #f8fafc;
    }}
    .mobile-hand-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      padding: 9px 10px;
      margin: 8px 0;
      box-shadow: 0 3px 10px rgba(15,23,42,.035);
    }}
    .mobile-hand-main {{ min-width: 0; }}
    .mobile-hand-topline,
    .mobile-hand-meta {{
      display: flex;
      align-items: center;
      gap: 5px;
      flex-wrap: wrap;
    }}
    .mobile-hand-meta {{
      margin-top: 5px;
      color: #64748b;
      font-size: 12px;
    }}
    .mobile-hand-side {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 5px;
      white-space: nowrap;
    }}
    .open-hand-btn {{
      border: 1px solid #c7d2fe;
      background: #eef2ff;
      color: #1e40af;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 850;
      text-decoration: none;
      cursor: pointer;
    }}
    .mobile-tag {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 2px 7px;
      font-size: 11px;
      font-weight: 850;
      border: 1px solid #e2e8f0;
      background: #f8fafc;
      color: #475569;
    }}
    .mobile-tag.bad {{ background: #fef2f2; color: #991b1b; border-color: #fecaca; }}
    .mobile-tag.good {{ background: #ecfdf3; color: #166534; border-color: #bbf7d0; }}
    .mobile-tag.warn {{ background: #fffbeb; color: #92400e; border-color: #fde68a; }}
    /* ── Mode: evidence-card — richer rows with prose ── */
    /* Only hide table when JS-generated replacement exists */
    [data-mobile-mode="evidence-card"].has-mobile-cards > table,
    [data-mobile-mode="evidence-card"].has-mobile-cards > .table-scroll > table {{
      display: none;
    }}
    /* Fallback: if no mobile cards, keep table scrollable */
    [data-mobile-mode="evidence-card"]:not(.has-mobile-cards) > .table-scroll {{
      overflow-x: auto; -webkit-overflow-scrolling: touch;
    }}
    [data-mobile-mode="evidence-card"] .mobile-evidence-list {{
      display: block;
      padding: 8px 10px;
      background: #f8fafc;
    }}
    .mobile-evidence-card {{
      border: 1px solid #e2e8f0;
      border-radius: 15px;
      background: #fff;
      padding: 10px;
      margin: 8px 0;
      box-shadow: 0 3px 10px rgba(15,23,42,.035);
    }}
    .mobile-evidence-head {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      border-bottom: 1px solid #eef2f7;
      padding-bottom: 8px;
    }}
    .mobile-evidence-title {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
      min-width: 0;
    }}
    .mobile-evidence-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px 10px;
      margin-top: 8px;
      font-size: 12px;
    }}
    .mobile-evidence-grid .kv span {{
      display: block; color: #64748b; font-size: 10px;
      text-transform: uppercase; font-weight: 950; letter-spacing: .04em;
    }}
    .mobile-evidence-grid .kv b {{
      display: block; color: #111827; font-weight: 800;
    }}
    .mobile-evidence-body {{
      margin-top: 8px;
      background: #fffbeb;
      border-left: 3px solid #f5d75e;
      border-radius: 8px;
      padding: 7px 8px;
      font-size: 12.5px;
      line-height: 1.38;
    }}
    /* ── Mode: compact — small simple tables ── */
    /* Scoped to .table-shell like scroll-mode to avoid nested table issues */
    .table-shell[data-mobile-mode="compact"] .data-table {{
      display: table !important;
      width: 100% !important;
      min-width: 0 !important;
      font-size: 12px !important;
    }}
    .table-shell[data-mobile-mode="compact"] .data-table thead {{ display: table-header-group !important; }}
    .table-shell[data-mobile-mode="compact"] .data-table tbody {{ display: table-row-group !important; }}
    .table-shell[data-mobile-mode="compact"] .data-table tr {{
      display: table-row !important;
      padding: 0 !important;
      border-bottom: 0 !important;
    }}
    .table-shell[data-mobile-mode="compact"] .data-table th,
    .table-shell[data-mobile-mode="compact"] .data-table td {{
      display: table-cell !important;
      width: auto !important;
      padding: 6px 7px !important;
      white-space: normal !important;
      vertical-align: top !important;
    }}
    .table-shell[data-mobile-mode="compact"] .data-table td::before {{
      content: none !important;
      display: none !important;
    }}
    /* ── Evidence preview/details (4H) ── */
    .mobile-evidence-preview {{
      margin-top: 6px;
      color: #334155;
      font-size: 12px;
      line-height: 1.35;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .mobile-evidence-details {{
      margin-top: 6px;
      font-size: 12px;
      border-top: 1px solid #eef2f7;
      padding-top: 6px;
    }}
    .mobile-evidence-details > summary {{
      cursor: pointer;
      font-weight: 800;
      color: #1d4ed8;
      list-style: none;
    }}
    .mobile-evidence-details > summary::-webkit-details-marker {{ display: none; }}
    .mobile-evidence-details > summary::after {{ content: " ▾"; }}
    .mobile-evidence-details[open] > summary::after {{ content: " ▴"; }}
    /* ── Prevent page-level horizontal overflow ── */
    .table-shell {{ max-width: 100%; overflow: hidden; }}
    /* ── Bottom controls padding (4F) ── */
    .report-app,.main {{ padding-bottom: 132px !important; }}
    #audit-export-btn,#audit-reset-btn {{ bottom: calc(18px + env(safe-area-inset-bottom, 0px)) !important; }}
  }}
  /* ==== END MOBILE TABLE READABILITY ==== */

  /* ---- UX-1: table cells wrap by default (no truncation) ---- */
  .data-table td {{ max-width: 420px; white-space: normal;
    word-break: break-word; line-height: 1.45; }}

  /* ---- UX-2: hand-list triggers as visible clickable pills ---- */
  .hand-list-trigger {{ display: inline-flex; align-items: center; gap: 3px;
    padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 700;
    background: #eef2ff; color: #1e40af; border: 1px solid #c7d2fe;
    text-decoration: none !important; white-space: nowrap; cursor: pointer; }}
  .hand-list-trigger:hover {{ background: #dbeafe; border-color: #93c5fd; }}

  /* P1-9: review pill styling for hand-list triggers + IE rows */
  .review-pill {{ display: inline-flex; align-items: center; gap: 4px;
    margin-left: 6px; padding: 2px 7px; border-radius: 999px;
    font-size: 11px; font-weight: 800; white-space: nowrap;
    border: 1px solid #cbd5e1; background: #f8fafc; color: #475569; }}
  .review-pill.review-none {{ background: #f8fafc; border-color: #cbd5e1; color: #64748b; }}
  .review-pill.review-some {{ background: #fffbeb; border-color: #fde68a; color: #92400e; }}
  .review-pill.review-all {{ background: #ecfdf3; border-color: #bbf7d0; color: #166534; }}
  .review-pill.review-na {{ background: #f1f5f9; border-color: #e2e8f0; color: #94a3b8;
    font-style: italic; }}
  .review-pill.review-missing {{ background: #fef2f2; border-color: #fecaca; color: #991b1b; }}

  /* ---- UX-5: bottom padding for fixed controls ---- */
  .report-app {{ padding-bottom: 70px; }}

  /* ---- Dark mode (opt-in only — add class="dark" to <html> to activate) ---- */
  html.dark {{
      --bg:#0f172a; --paper:#1e293b; --ink:#e2e8f0; --muted:#94a3b8;
      --line:#334155; --brand:#93c5fd; --brand2:#60a5fa; --soft:#1e3a5f;
      --good:#4ade80; --bad:#f87171; --warn:#fbbf24; --warnbg:#422006;
      --okbg:#052e16; --badbg:#450a0a; --shadow:0 10px 30px rgba(0,0,0,.3);
  }}
  html.dark body {{ color: var(--ink) !important; background: var(--bg) !important; }}
  html.dark a {{ color: var(--brand2); }}
  html.dark h1, html.dark h2, html.dark h3 {{ color: var(--brand); }}
  html.dark th {{ background: #1e293b !important; color: var(--brand) !important; }}
  html.dark tr:nth-child(even) td {{ background: #1a2332; }}
  html.dark .data-table th {{ background: #1e3a5f !important; }}
  html.dark .data-table td:hover {{ background: var(--paper); }}
  html.dark .stat-card {{ background: var(--paper) !important; border-color: var(--line) !important; }}
  html.dark .chapter {{ background: var(--paper); border-color: var(--line); }}
  html.dark .topbar {{ background: var(--brand) !important; }}
  html.dark .analyst-notes {{ background: #422006 !important; border-color: #854d0e !important; }}
  html.dark .modal-panel {{ background: var(--paper) !important; color: var(--ink) !important; }}
  html.dark .modal-head {{ background: #0f172a !important; }}
  html.dark input, html.dark textarea, html.dark select {{ background: var(--paper) !important;
    color: var(--ink) !important; border-color: var(--line) !important; }}

  /* ---- Print styles ---- */
  @media print {{
    .topbar, .sidebar, nav.toc, a.toc-back,
    .modal, .modal-backdrop, .audit-row,
    .workflow-tabs, .section-indicator {{ display: none !important; }}
    details {{ display: block !important; }}
    details > summary {{ display: none !important; }}
    details > *:not(summary) {{ display: block !important; }}
    .chapter {{ box-shadow: none !important; border: 1px solid #ccc !important;
      break-inside: avoid; page-break-inside: avoid; }}
    body {{ font-size: 11px !important; }}
    h2 {{ page-break-after: avoid; }}
    table {{ font-size: 10px !important; }}
    .stat-strip {{ display: none !important; }}
  }}
  /* v8.7.0 PR2: Opponent Intelligence — badge pills, facing strip, villain evidence */
  .vi-badge {{ display:inline-flex;align-items:center;gap:3px;border-radius:999px;
    padding:1px 7px;font-size:10px;font-weight:800;margin-left:5px;border:1px solid transparent;
    font-family:Inter,system-ui,sans-serif;vertical-align:middle; }}
  .vi-badge.note {{ background:#fef2f2;color:#991b1b;border-color:#fecaca; }}
  .vi-badge.pivot {{ background:#fff7cc;color:#92400e;border-color:#fde68a; }}
  .vi-badge.miss {{ background:#fef2f2;color:#991b1b;border-color:#fecaca; }}
  .vi-badge.good {{ background:#ecfdf3;color:#166534;border-color:#bbf7d0; }}
  .facing-strip {{ display:flex;align-items:center;justify-content:space-between;gap:10px;
    flex-wrap:nowrap;border:1px solid #c7d2fe;background:#eef2ff;border-radius:12px;
    padding:7px 10px;margin:8px 0 10px;min-height:38px; }}
  .facing-strip.has-exploit {{ border-color:#fecaca;background:#fff1f2; }}
  .facing-main {{ display:flex;align-items:center;gap:8px;min-width:0;flex:1 1 auto; }}
  .facing-icon {{ width:24px;height:24px;border-radius:999px;background:#fff;
    display:flex;align-items:center;justify-content:center;font-size:14px;
    border:1px solid #c7d2fe;flex:0 0 auto; }}
  .facing-strip.has-exploit .facing-icon {{ border-color:#fecaca; }}
  .facing-title {{ font-weight:900;color:#0f172a;font-size:13px;white-space:nowrap;
    overflow:hidden;text-overflow:ellipsis; }}
  .facing-sub {{ font-size:12px;color:#475467;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis; }}
  .facing-inline {{ display:flex;align-items:center;gap:6px;min-width:0; }}
  .facing-sep {{ color:#94a3b8; }}
  .facing-actions {{ display:flex;flex-wrap:nowrap;gap:5px;flex:0 0 auto; }}
  .facing-action {{ display:inline-flex;align-items:center;gap:4px;border-radius:999px;
    padding:2px 7px;background:#fff;border:1px solid #cbd5e1;color:#334155;
    font-size:11px;font-weight:800;white-space:nowrap;cursor:pointer; }}
  .facing-action:hover {{ background:#eef2ff; }}
  @media (max-width: 760px) {{
    .facing-strip {{ align-items:flex-start;flex-direction:column;gap:6px; }}
    .facing-title,.facing-sub {{ white-space:normal; }}
  }}
  /* Villain evidence modal */
  #villain-evidence-modal .modal-panel {{ max-width:960px; }}
  .ve-header {{ display:flex;align-items:center;gap:12px;margin-bottom:12px; }}
  .ve-header-icon {{ width:36px;height:36px;border-radius:999px;background:#eef2ff;
    display:flex;align-items:center;justify-content:center;font-size:18px;
    border:1px solid #c7d2fe; }}
  .ve-header-info h4 {{ margin:0;font-size:17px;color:#172554; }}
  .ve-header-info p {{ margin:2px 0 0;font-size:13px;color:#667085; }}
  .ve-filters {{ display:flex;flex-wrap:wrap;gap:5px;margin:10px 0; }}
  .ve-filter {{ display:inline-flex;align-items:center;gap:4px;padding:5px 10px;
    border:1px solid #c7d2fe;background:#eef2ff;color:#1e40af;border-radius:999px;
    font-weight:800;font-size:12px;cursor:pointer; }}
  .ve-filter:hover,.ve-filter.active {{ background:#172554;color:#fff;border-color:#172554; }}
  .ve-signal {{ display:inline-flex;align-items:center;gap:4px;font-size:11px;
    padding:2px 8px;border-radius:999px;font-weight:800;border:1px solid transparent;
    white-space:nowrap; }}
  .ve-signal.note {{ background:#fef2f2;color:#991b1b;border-color:#fecaca; }}
  .ve-signal.pivot {{ background:#fff7cc;color:#92400e;border-color:#fde68a; }}
  .ve-signal.miss {{ background:#fef2f2;color:#991b1b;border-color:#fecaca; }}
  .ve-signal.good {{ background:#ecfdf3;color:#166534;border-color:#bbf7d0; }}
  .opponent-context {{ margin:0.8em 0;padding:8px 12px;background:#fffbe8;
    border-left:3px solid #f5d75e;border-radius:4px; }}
  .opponent-context .oc-heading {{ font-size:11px;font-weight:900;color:#6a4d00;
    text-transform:uppercase;letter-spacing:.05em;margin:0 0 4px; }}
  .opponent-context p {{ margin:3px 0;font-size:13px; }}
  /* v8.7.0 PR6: villain mini-card popup */
  .villain-minicard {{ position:fixed;z-index:100;background:#fff;border:1px solid #c7d2fe;
    border-radius:12px;padding:10px 14px;box-shadow:0 8px 24px rgba(15,23,42,.12);
    min-width:180px;max-width:260px; }}
  .villain-mini[data-vk] {{ cursor:pointer; }}
  .villain-mini[data-vk]:hover {{ background:#eef2ff;border-radius:4px; }}
  /* v8.2.0: dynamically injected section CSS */
  {''.join(extra_css or [])}
</style>
</head>
<body>
<div class="report-app" data-report-date="{_report_date}">
{topbar}
<div class="layout">
<aside class="sidebar" aria-label="Report navigation" id="gem-sidebar">
{sidebar_content}
</aside>
<main class="main">
{body}
</main>
</div>
""" + _MODAL_HTML + _AUDIT_HTML + """
</div>
<script>
/* v8.2.0: dynamically injected section JS */
""" + '\n'.join(extra_js or []) + """
</script>
</body>
</html>"""


# ============================================================
# B52 (v7.55, Ron 2026-05-18): Card → colored suit-pill HTML
# ============================================================
# Renders a card like "Ah" as <span class="card card-h">A♥</span> —
# a pill with colored background (red for hearts, blue diamonds,
# black spades, green clubs) and white rank+suit symbol.

_SUIT_HTML = {
    's': ('♠', 'card-s'),  # spades — black
    'h': ('♥', 'card-h'),  # hearts — red
    'd': ('♦', 'card-d'),  # diamonds — blue
    'c': ('♣', 'card-c'),  # clubs — green
}

def _card_html(card_str):
    """Convert a card token like 'Ah' or '7d' into a colored pill HTML span.

    Markdown viewers that don't render HTML still get the rank+suit symbol
    text (via the inner content). HTML rendering gets the full colored pill.
    """
    if not card_str or len(card_str) < 2:
        return card_str or ''
    rank = card_str[0].upper()
    suit_char = card_str[1].lower()
    sym, cls = _SUIT_HTML.get(suit_char, ('', ''))
    if not sym:
        return card_str  # fallback
    return f'<span class="card {cls}">{rank}{sym}</span>'


def _cards_html(cards, sort_desc=False):
    """Render a list/iterable of card tokens to a space-joined HTML string.

    B70 (v7.56, Ron 2026-05-18): when sort_desc=True, sort cards by rank
    descending (Ace high). E.g. ['3h','Ah'] → 'Ah 3h'. Used for hero/villain
    hole-cards display. Board cards are NOT sorted (chronological order
    of dealing is meaningful for streets).
    """
    if not cards:
        return ''
    if isinstance(cards, str):
        # Handle "AhJh" or "Ah Jh" or list-like
        cards = cards.split() if ' ' in cards else [cards[i:i+2] for i in range(0, len(cards), 2)]
    if sort_desc:
        cards = _sort_cards_desc(cards)
    return ' '.join(_card_html(c) for c in cards if c)


# B70 (v7.56) + B80 (v7.57): card sort order. Rank DESC primary, suit secondary
# (♠ > ♥ > ♦ > ♣ — standard bridge/poker convention).
_RANK_VALUES = {'A': 14, 'K': 13, 'Q': 12, 'J': 11, 'T': 10,
                '9': 9, '8': 8, '7': 7, '6': 6, '5': 5, '4': 4, '3': 3, '2': 2}
_SUIT_VALUES = {'s': 4, 'h': 3, 'd': 2, 'c': 1}

def _sort_cards_desc(cards):
    """Sort card tokens by rank DESC, suit DESC (♠ > ♥ > ♦ > ♣).
    Example: ['Kd','Kc','Ks','Kh'] → ['Ks','Kh','Kd','Kc'].
    """
    if not cards:
        return cards
    def _key(c):
        if not c or len(c) < 2:
            return (-1, 0)
        r = _RANK_VALUES.get(c[0].upper(), 0)
        s = _SUIT_VALUES.get(c[1].lower(), 0)
        return (r, s)
    return sorted(cards, key=_key, reverse=True)


def _describe_made_hand(hole_cards, board_cards):
    """B72 (v7.56, Ron 2026-05-18): describe villain's made hand from their
    hole cards + the board. Used in the result row to explain WHY hero lost
    at showdown without forcing the reader to scan board+hand and reconstruct.

    Returns a short human-readable string like:
      "two pair, Aces and Kings"
      "straight, T-high"
      "flush, Ace-high"
      "set of Queens"
      "pair of Kings"
      "high card, Ace"

    Approximation — covers 95% of common cases. Uses 5-best-of-7 evaluation.
    """
    if not hole_cards or len(hole_cards) < 2 or not board_cards or len(board_cards) < 3:
        return ''
    # Normalize tokens
    all_cards = list(hole_cards) + list(board_cards)
    ranks = []
    suits = []
    for c in all_cards:
        if not c or len(c) < 2: continue
        ranks.append(c[0].upper())
        suits.append(c[1].lower())

    rank_val = {'A':14,'K':13,'Q':12,'J':11,'T':10,'9':9,'8':8,'7':7,'6':6,'5':5,'4':4,'3':3,'2':2}
    rank_name = {14:'Ace',13:'King',12:'Queen',11:'Jack',10:'Ten',
                 9:'Nine',8:'Eight',7:'Seven',6:'Six',5:'Five',
                 4:'Four',3:'Three',2:'Two'}
    rank_name_plural = {14:'Aces',13:'Kings',12:'Queens',11:'Jacks',10:'Tens',
                        9:'Nines',8:'Eights',7:'Sevens',6:'Sixes',5:'Fives',
                        4:'Fours',3:'Threes',2:'Twos'}

    vals = sorted([rank_val.get(r, 0) for r in ranks], reverse=True)
    val_counts = {}
    for v in vals:
        val_counts[v] = val_counts.get(v, 0) + 1
    suit_counts = {}
    for s in suits:
        suit_counts[s] = suit_counts.get(s, 0) + 1

    # Flush check (5+ of one suit)
    flush_suit = None
    for s, c in suit_counts.items():
        if c >= 5:
            flush_suit = s; break

    # Straight check (any run of 5 consecutive in vals)
    unique_vals = sorted(set(vals), reverse=True)
    # Wheel: A,2,3,4,5 → treat A as 1
    if 14 in unique_vals:
        unique_vals_with_wheel = unique_vals + [1]
    else:
        unique_vals_with_wheel = unique_vals
    straight_high = None
    for i in range(len(unique_vals_with_wheel) - 4):
        window = unique_vals_with_wheel[i:i+5]
        if window[0] - window[4] == 4 and len(set(window)) == 5:
            straight_high = window[0]; break

    # Straight flush check
    if flush_suit and straight_high:
        suited_vals = sorted([rank_val.get(r, 0) for r, s in zip(ranks, suits) if s == flush_suit], reverse=True)
        if 14 in suited_vals:
            suited_vals_w = suited_vals + [1]
        else:
            suited_vals_w = suited_vals
        for i in range(len(suited_vals_w) - 4):
            w = suited_vals_w[i:i+5]
            if w[0] - w[4] == 4 and len(set(w)) == 5:
                if w[0] == 14:
                    return 'royal flush'
                return f'straight flush, {rank_name[w[0]]}-high'

    # Quads
    for v, c in sorted(val_counts.items(), key=lambda kv: -kv[0]):
        if c >= 4:
            return f'four of a kind, {rank_name_plural[v]}'

    # Full house
    trips = sorted([v for v, c in val_counts.items() if c >= 3], reverse=True)
    pairs_for_fh = sorted([v for v, c in val_counts.items() if c >= 2 and v not in trips[:1]], reverse=True)
    if trips and pairs_for_fh:
        return f'full house, {rank_name_plural[trips[0]]} full of {rank_name_plural[pairs_for_fh[0]]}'
    if len(trips) >= 2:
        return f'full house, {rank_name_plural[trips[0]]} full of {rank_name_plural[trips[1]]}'

    # Flush (not straight flush)
    if flush_suit:
        suited_high = max([rank_val.get(r, 0) for r, s in zip(ranks, suits) if s == flush_suit])
        return f'flush, {rank_name[suited_high]}-high'

    # Straight
    if straight_high:
        if straight_high == 5:
            return 'straight, 5-high (wheel)'
        return f'straight, {rank_name[straight_high]}-high'

    # Trips (set vs trips — set = pocket pair matching board card; trips = one hole card pair matching board pair)
    if trips:
        # Determine if it's a "set" — both hole cards are same rank as the trips
        hole_vals = [rank_val.get(c[0].upper(), 0) for c in hole_cards if c and len(c) >= 2]
        if hole_vals.count(trips[0]) == 2:
            return f'set of {rank_name_plural[trips[0]]}'
        return f'three of a kind, {rank_name_plural[trips[0]]}'

    # Two pair
    pairs = sorted([v for v, c in val_counts.items() if c >= 2], reverse=True)
    if len(pairs) >= 2:
        return f'two pair, {rank_name_plural[pairs[0]]} and {rank_name_plural[pairs[1]]}'

    # One pair
    if pairs:
        return f'pair of {rank_name_plural[pairs[0]]}'

    # High card
    return f'{rank_name[vals[0]]}-high'


def _real_cards_pills(rec, hands_by_id, sort_desc=True):
    """B242 (Ron review 2026-05-26): render a record's REAL dealt cards as
    pills. Deviation / screening records store the chart-class NOTATION (e.g.
    'A6o') in .cards, which loses the true suits — _cards_str_to_pills then
    synthesizes arbitrary suits, so the same hand can show 6h in one table and
    6d in another (XIII.2 vs the appendix). This looks up the actual hand by
    id and renders its dealt cards; falls back to the notation if the hand
    cannot be found."""
    if isinstance(rec, dict) and hands_by_id:
        hid = rec.get('id') or rec.get('hand_id')
        h = hands_by_id.get(hid) if hid else None
        if h:
            real = h.get('cards')
            if real and len(real) == 2:
                return _cards_str_to_pills(''.join(real), sort_desc=sort_desc)
    fallback = rec.get('cards') if isinstance(rec, dict) else rec
    return _cards_str_to_pills(fallback or '—', sort_desc=sort_desc)


def _cards_str_to_pills(cards_str, sort_desc=True):
    """B76 (v7.56) + B90 (v7.58, Ron 2026-05-18): convert card-string formats
    to colored pills. Accepts two flavors:

    1. Concrete cards: '3hAh', 'AhJh', '6s 7d' — pairs of rank+suit tokens.
       Always rendered with the actual suits. Optionally sorted DESC.

    2. Chart notation: 'AKo', 'AKs', 'JTo', '44', 'TT', 'A8o' — chart-class
       abbreviations from chart classification. Expanded to a representative
       2-card combo for visualization:
         Pair (XX) → X♠ X♥
         Suited (XYs) → X♠ Y♠
         Offsuit (XYo) → X♠ Y♥

    Returns the input unchanged if it doesn't match either format.
    """
    if not cards_str or cards_str in ('—', '??', '-', 'N/A'):
        return cards_str or '—'
    import re as _re_cs
    raw = cards_str.strip()

    # B90: chart notation check first (before concrete-card regex)
    # Format: 2 rank chars optionally followed by 's' or 'o'
    chart_m = _re_cs.match(r'^([2-9TJQKA])([2-9TJQKA])([so]?)$', raw, _re_cs.IGNORECASE)
    if chart_m:
        r1, r2, mod = chart_m.group(1).upper(), chart_m.group(2).upper(), chart_m.group(3).lower()
        if r1 == r2:
            # Pocket pair → ♠ + ♥
            tokens = [f"{r1}s", f"{r2}h"]
        elif mod == 's':
            # Suited → both ♠
            tokens = [f"{r1}s", f"{r2}s"]
        else:
            # Offsuit (or unspecified, e.g. 'AK') → ♠ + ♥
            tokens = [f"{r1}s", f"{r2}h"]
        # Always sort desc (visually consistent with hole-card display)
        if sort_desc:
            tokens = _sort_cards_desc(tokens)
        pills = ' '.join(_card_html(t) for t in tokens)
        return f'<span style="white-space:nowrap">{pills}</span>'

    # Concrete-card format: "AhJh" or "3h Ah" etc.
    tokens = _re_cs.findall(r'[2-9TJQKA][shdc]', raw, _re_cs.IGNORECASE)
    if not tokens:
        return cards_str  # not card-like; return unchanged
    if sort_desc:
        tokens = _sort_cards_desc(tokens)
    # B91 (v7.58): wrap in nowrap span so table cells don't break the pair
    # vertically when the column is narrow (III.4 Read-Dep was showing card1
    # and card2 on separate rows because the cell width forced wrap).
    pills = ' '.join(_card_html(t) for t in tokens)
    return f'<span style="white-space:nowrap">{pills}</span>'


def _cards_text_to_pills(text):
    """B71/B78 (v7.56, Ron 2026-05-18): scan free text for card tokens and
    replace with colored pills. Used inside analyst notes where boards/hands
    are written as plain text like 'Kd2d5sTs3s' or 'AhJh HJ'.

    Conservative pattern: 2-7 consecutive card tokens (rank+suit, no spaces),
    OR space-separated. Preserves leading and trailing whitespace consumed
    by the regex so adjacent words don't mash into the rendered pills.
    B78: explicit trailing-space preservation — was emitting 'A♥ J♥HJ' when
    source was 'AhJh HJ' because the trailing space was consumed by ``\\s*`` in
    the group but the replacement didn't re-emit it.

    Preserves ORIGINAL ORDER (boards are temporal — don't sort). Use
    _cards_str_to_pills for hole-card-cell renders where DESC sort applies.
    """
    if not text:
        return text
    if '<' in text and 'class="card' in text:
        # Skip if text already contains rendered pills
        return text
    import re as _re_ctp
    # Outer capture: leading word-boundary + tokens; suffix space tracked separately
    pat = _re_ctp.compile(
        r'(?<![A-Za-z0-9])((?:[2-9TJQKA][shdc])(?:\s*[2-9TJQKA][shdc]){1,6})(?![A-Za-z0-9])')
    def _replace(m):
        raw = m.group(1)
        tokens = _re_ctp.findall(r'[2-9TJQKA][shdc]', raw)
        if len(tokens) < 2:
            return m.group(0)
        # B173 (Ron 2026-05-24): wrap each pill-run in a nowrap span — matches
        # _cards_str_to_pills. Without it, a board in a narrow table cell (I.7
        # Confirmed Coolers) broke vertically across two rows; now the board
        # stays on one line and the wider text column (Hand Reference) wraps.
        pills = ' '.join(_card_html(t) for t in tokens)
        return f'<span style="white-space:nowrap">{pills}</span>'
    return pat.sub(_replace, text)



# ============================================================
# B48 (v7.53, Ron 2026-05-18): VISUAL HAND-GRID RENDERER
# ============================================================
# Replaces the verbose per-street action prose with a compact horizontal
# action grid (GG/GTOW-style) plus inline numbered annotations + a
# notes block below referencing the numbers.
#
# Numbered annotations: when analyst commentary exists for a specific
# action/decision point, that action gets a (1)/(2)/(3)... marker
# inline. The text of each note appears in a notes block immediately
# below the grid.
# ============================================================

# B145 (v7.70, Ron 2026-05-23): action-class verbs for binding the single-
# narrative analyst note to the action the analyst actually means.
_KD_CLASS_VERB = {'fold': 'folds', 'check': 'checks', 'call': 'calls',
                  'bet': 'bets', 'raise': 'raises'}
_KD_CLASS_PATTERNS = {
    'fold':  r'\bfold(s|ing|ed)?\b',
    'check': r'\bcheck(s|ing|-?back)?\b',
    'call':  r'\b(call|flat|flatt|defend|defens|overcall|cold[- ]?call)',
    'bet':   r'\b(bet|c-?bet|barrel|lead|donk|stab|probe)',
    'raise': r'\b(rais|iso|open|3-?bet|4-?bet|5-?bet|squeez|jam|shov|push'
             r'|re-?jam|reshov|re-?rais)',
}


