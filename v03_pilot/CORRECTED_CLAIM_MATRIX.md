# CORRECTED_CLAIM_MATRIX — first V03 completion (`63b00e7`)

Every claim from the first completion report re-classified against the deep audit and the real-session
measurement. Classes: **PROVEN**, **PROVEN ONLY ON FIXTURE**, **STRONG INFERENCE**, **UNVERIFIED**, **INCORRECT**.

| # | First-run claim | Class | Correction |
|---|---|---|---|
| 1 | Detector consumes canonical owners; no parallel calc | **PROVEN** | Holds. |
| 2 | Atomic record, zero analyst calculation, no leakage | **PROVEN** | Holds (semantic audit clean on real records). |
| 3 | Fails closed on unknown archetype / incomplete chart / within tolerance / missing operand | **PROVEN** | Holds; widened (SRP/HU/all-in/within-spread now also fail closed). |
| 4 | Dual-strategy bands never auto-confirmed | **PROVEN** | Holds. |
| 5 | "1 genuine new confirmed mistake found (TM91000015)" | **INCORRECT** | TM91000015 is a **fixture**, a **3-bet pot**, and an **all-in** c-bet. The SRP range-c-bet chart did not apply, and a jam is not a free sizing choice. **Retracted.** It was a chart-misapplication, not a mistake. |
| 6 | Detector maps gross deviation → CONFIRMED_MISTAKE (required) | **INCORRECT** (design defect) | The detector must not own the terminal verdict for a sizing deviation. Now nominates → READ_DEPENDENT; analyst owns the verdict. |
| 7 | "Precision (confirmed/resolved) 0.50" on fixtures | **PROVEN ONLY ON FIXTURE** (and now moot) | Fixture-only; cannot count for product value. Real-data precision is **0.0** (0 confirmed / 29 resolved). |
| 8 | "Confirmed mistakes / 100 hands = 1.72" | **PROVEN ONLY ON FIXTURE** → **INCORRECT as product value** | Fixture artifact. Real-data rate is **0.0 / 100 hands**. |
| 9 | "0 detector-bug false positives" (on fixtures) | **PROVEN ONLY ON FIXTURE** | True on fixtures, but the fixtures were all 3BP (the detector should not have evaluated them at all). On real data, post-correction detector-bug rate is 0/29. |
| 10 | One-pass / no-calculation contract preserved | **PROVEN** | Holds across corrections (re-verified on real records). |
| 11 | "No suite regression; detectors 88/5 pre-existing" | **PROVEN** | Holds. |
| 12 | Incremental runtime negligible; ~5KB/record packet cost | **PROVEN** (refined) | Real corpus: +9.8ms (+10.9% of discovery) over 3609 hands; ~5.3KB/record. |
| 13 | Recommendation "EXPAND cautiously" | **INCORRECT / UNVERIFIED at the time** | Was provisional on unproven product value. Real data shows 0 confirmed mistakes → corrected to **RECALIBRATE** (see package). |
| 14 | "844-hand June-16 raw inputs absent; measurement pending" | **PROVEN** | Holds; this run obtained a different legitimate real corpus (3 approved sessions, 3609 hands). |

## Net

The **implementation seam** claims (1–4, 10–12) are PROVEN and survive. The **product-value** claims (5–9, 13)
are INCORRECT or fixture-only and are **retracted/corrected**: the prior "genuine mistake found" was a
fixture chart-misapplication, and the real-data confirmed-mistake yield is **zero**.
