    core = s.get('core', {})
    csv = s.get('csv_row', {})

    # Phase 4.8: Groups A+B merged into one table with grouped Exploit column.
    # Group labels: "Float Flop / CR cbet" and "BB Iso vs SB Limp".
    _ex_hdr = "| Exploit | Metric | Status | Rate | Target | Delta | Sample | Notes |"
    _ex_sep = "|---|---|:---:|---:|---|---|---:|---|"
    _ex_rows = []

    # Float Flop / CR cbet rows
    fl_pct = core.get('call_cbet_ip_pct', 0)
    fl_n = core.get('call_cbet_ip_n', 0)
    fl_count = round(fl_pct * fl_n / 100) if fl_n else 0
    cr_pct = core.get('raise_cbet_oop_pct', 0)
    cr_n = core.get('raise_cbet_oop_n', 0)
    cr_count = round(cr_pct * cr_n / 100) if cr_n else 0
    for label, x, n, tlo, thi, note in [
        ("Float Flop (Call CBet IP)", fl_count, fl_n, 35, 50,
         "J#5: float vs over-cbetters in position"),
        ("Raise CBet OOP (CR)", cr_count, cr_n, 8, 15,
         "J#4 OOP half"),
    ]:
        if n == 0 or n is None:
            _ex_rows.append(
                f"| Float Flop / CR cbet | {label} | ⚪ | — | "
                f"{tlo}-{thi}% | — | — | {note} |")
        else:
            rate = 100.0 * x / n
            ci_lo, ci_hi = _wilson_ci(x, n)
            verdict = _verdict_ci(x, n, tlo, thi, n_min=10)
            ci_tip = f'<span class="ci-tip" title="CI 90%: {ci_lo:.0f}-{ci_hi:.0f}%">ⓘ</span>'
            delta = rate - (tlo + thi) / 2
            _ex_rows.append(
                f"| Float Flop / CR cbet | {label} | {verdict} | "
                f"{rate:.1f}% {ci_tip} | {tlo}-{thi}% | {delta:+.1f} pp | "
                f"n={n} | {note} |")

    # BB Iso vs SB Limp rows
    bb_iso_pct = core.get('bb_iso_sb_limp_pct', 0)
    bb_iso_n = core.get('bb_iso_sb_limp_n', 0)
    bb_iso_count = round(bb_iso_pct * bb_iso_n / 100) if bb_iso_n else 0
    if bb_iso_n == 0 or bb_iso_n is None:
        _ex_rows.append(
            "| BB Iso vs SB Limp | BB Iso vs SB Limp | ⚪ | — | "
            "65-85% | — | — | J#2: punish weak SB limp range |")
    else:
        rate = 100.0 * bb_iso_count / bb_iso_n
        ci_lo, ci_hi = _wilson_ci(bb_iso_count, bb_iso_n)
        verdict = _verdict_ci(bb_iso_count, bb_iso_n, 65, 85, n_min=10)
        ci_tip = f'<span class="ci-tip" title="CI 90%: {ci_lo:.0f}-{ci_hi:.0f}%">ⓘ</span>'
        delta = rate - 75.0
        _ex_rows.append(
            f"| BB Iso vs SB Limp | BB Iso vs SB Limp | {verdict} | "
            f"{rate:.1f}% {ci_tip} | 65-85% | {delta:+.1f} pp | "
            f"n={bb_iso_n} | J#2: punish weak SB limp range |")
    bb_check_pct = core.get('bb_check_sb_limp_pct', 0)
    if bb_iso_n > 0:
        bb_check_count = round(bb_check_pct * bb_iso_n / 100)
        _ex_rows.append(
            f"| BB Iso vs SB Limp | ↳ BB Check (took flop) | — | "
            f"{bb_check_pct:.1f}% ({bb_check_count}/{bb_iso_n}) | "
            f"15-35% (residual) | — | n={bb_iso_n} | "
            f"informational — rest of distribution |")

    _ex_blk = variance_ledger_block("t4-exploit-merged", _ex_hdr, _ex_sep, _ex_rows)
    doc.write_block(_ex_blk)
    doc.w("")

    # Fold-to-CBet by Sizing Bucket (Jasper #1 + #3)
    # Phase 4.8: status 2nd column, Folds/Opps second-to-last, street grouped
    doc.w("**Fold-to-CBet by Sizing Bucket:**")
    doc.w("")
    doc.w("| Street | Status | Bucket | Rate | Target | Folds/Opps | Notes |")
    doc.w("|---|:---:|---|---|---|---|---|")
    f_buckets = core.get('fold_to_cbet_by_size', {})
    for bucket, target_band, note in [
        ('small',  (0, 55),  "J#1: defend wider vs block bets"),
        ('medium', (45, 65), "merged middle-strength M20 zone"),
        ('large',  (55, 70), "polarized — pool more value-heavy"),
    ]:
        d = f_buckets.get(bucket, {})
        opps, folds, pct = d.get('opps', 0), d.get('folds', 0), d.get('pct', 0)
        if opps > 0:
            verdict = _verdict_ci(folds, opps, target_band[0], target_band[1], n_min=10)
            doc.w(f"| Flop | {verdict} | {bucket} | {pct:.1f}% | "
                  f"{target_band[0]}-{target_band[1]}% | {folds}/{opps} | {note} |")
    t_buckets = core.get('fold_to_turn_cbet_by_size', {})
    for bucket, target_band, note in [
        ('small',  (0, 50),  "J#3: call more vs block-bet turns"),
        ('medium', (45, 65), "merged middle"),
        ('large',  (55, 70), "J#3: fold more vs polarized turn"),
    ]:
        d = t_buckets.get(bucket, {})
        opps, folds, pct = d.get('opps', 0), d.get('folds', 0), d.get('pct', 0)
        if opps > 0:
            verdict = _verdict_ci(folds, opps, target_band[0], target_band[1], n_min=10)
            doc.w(f"| Turn | {verdict} | {bucket} | {pct:.1f}% | "
                  f"{target_band[0]}-{target_band[1]}% | {folds}/{opps} | {note} |")
    doc.w("")
    doc.w("*Tentative targets — leak deriver does NOT yet promote Jasper-5 metrics to "
          "Section III leaks. Tracking-mode only until calibrated against ≥5K hands "
          "of pool data.*")
    doc.w("")
