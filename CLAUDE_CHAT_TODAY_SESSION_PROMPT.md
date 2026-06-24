# CLAUDE CHAT — TODAY'S SESSION PROMPT (paste after setup passes)

Runtime: `GEM-main-ee5c105` (commit `ee5c105c6684…`, branch `main`), already extracted to `/home/claude/gem`.
Run today's session. Work only from `/home/claude/gem`.

1. I will upload today's session as one or two zips:
   - (A) hand histories — required;
   - (B) tournament game summaries — cash / net / ROI / finishes.
   Extract each upload to a sibling directory of `/home/claude/gem`. If only (A) is attached, say so
   explicitly ("no game summaries attached — cash/ROI columns will be blank").

2. Produce the report with the ONLY production runner — exactly one full run:
   ```
   python gem_analyzer.py <SESSION_DIR>
   ```
   This parses, analyzes, builds the coverage layer (pot odds, coaching cards, candidates + the analyst
   worklist + the sealed atomic analyst packet) and writes `Pokerbot_<Player>_<dates>_V<N>.html`. Do **not**
   use any other runner or a hand-rolled render driver.

3. (Optional) After you write the analyst output JSON — bound to the sealed packet, **outside** the
   hand-history input dir — re-render **at most once**:
   ```
   python gem_analyzer.py <SESSION_DIR> --quick
   ```
   `--quick` is cache- and packet-guarded; it hard-aborts if the analyst output is bound to a different
   packet/session. `--analyst-file` must NOT point inside the hand-history input directory.

   **Do not exceed one full run and one matching `--quick` re-render for a session.**

4. The descriptive Runout Transition notes render automatically in the hand-detail report on eligible
   turn/river decisions — no action needed. They are descriptive only; the strategic action stays *Insufficient
   evidence* (there is no opponent-range / equity model). Do not invent continue/resize/pivot/abandon advice
   from them.

5. Deliver: the report HTML, a short session preamble (what was analyzed, any missing inputs), and your
   analyst handover notes. Read the flat prose references in `/mnt/project/` as needed (Analyst Writing
   Checklist, Quick Reference).

If any setup/verify step from the setup prompt did not pass, STOP and tell Ron before running.
