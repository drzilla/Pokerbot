"""Emit FINAL_TRUTH_RECONCILIATION.json from a run's gem_report_data_<player>.json (v8.20 W1A.2A).

Reproducible: the canonical final-truth owner (gem_final_truth) stamps rd['final_truth'] during report
generation, so this tool simply lifts that record set out of the run's own emitted report-data and
annotates it with the surfaces that consume it + the cross-surface reconciliation. No re-derivation.

Usage:
    python tools/emit_final_truth_reconciliation.py <gem_report_data_*.json> <out.json>
"""
import io
import json
import sys

# The primary coaching surfaces that consume the canonical final-truth owner (gem_final_truth). The
# COUNT surfaces read it transitively through discipline_tier['canonical_*_count'] (both discipline
# builders delegate to the owner); the SET/eligibility surfaces read populations / records directly.
CONSUMING_SURFACES = [
    {'surface': 'KPI / stat cards (TL;DR)', 'via': "discipline_tier['canonical_mistakes_count','canonical_punts_count']"},
    {'surface': 'Summary / TL;DR discipline counter', 'via': "discipline_tier (owner-delegated)"},
    {'surface': 'Section III strategic-evaluation header', 'via': "discipline_tier (owner-delegated)"},
    {'surface': 'S2.2 Confirmed Mistakes header (confirmed + punts = errors)', 'via': "discipline_tier (owner-delegated)"},
    {'surface': 'XIII.4 All Mistakes header', 'via': "discipline_tier (owner-delegated)"},
    {'surface': 'Pokerbot Picks eligibility', 'via': "gem_final_truth.pick_eligible (positive-class gate)"},
    {'surface': 'Hand-detail / appendix verdict class', 'via': "gem_final_truth.class_from_verdict / record_for"},
]


def build(report_data_path):
    rd = json.load(io.open(report_data_path, encoding='utf-8'))
    ft = rd.get('final_truth')
    if not ft:
        raise SystemExit('ERROR: report-data has no final_truth (owner did not run / stale runtime).')
    dt = rd.get('discipline_tier', {}) or {}
    counts = ft['counts']
    recon = ft['reconciliation']
    # cross-surface check: the count every KPI/header/TL;DR surface reads (discipline_tier) MUST equal
    # the owner's population counts -- one source, no drift.
    cross_surface_ok = (
        dt.get('canonical_mistakes_count') == counts.get('CONFIRMED_MISTAKE')
        and dt.get('canonical_punts_count') == counts.get('PUNT'))
    out = {
        'artifact': 'FINAL_TRUTH_RECONCILIATION',
        'owner': 'gem_final_truth.build_final_truth',
        'source_report_data': report_data_path.replace('\\', '/').split('/')[-1],
        'reviewed_hands': recon.get('reviewed_hands'),
        'records': ft['records'],
        'populations': ft['populations'],
        'counts_by_class': counts,
        'reconciliation': {
            'contradictions': recon.get('contradictions'),
            'orphans': recon.get('orphans'),
            'duplicate_final_owners': recon.get('duplicates'),
            'error_total': recon.get('error_total'),
            'confirmed_mistakes': recon.get('confirmed_mistakes'),
            'punts': recon.get('punts'),
            'coolers': recon.get('coolers'),
        },
        'cross_surface': {
            'discipline_tier_canonical_mistakes_count': dt.get('canonical_mistakes_count'),
            'discipline_tier_canonical_punts_count': dt.get('canonical_punts_count'),
            'owner_confirmed_mistakes': counts.get('CONFIRMED_MISTAKE'),
            'owner_punts': counts.get('PUNT'),
            'counts_reconcile': cross_surface_ok,
        },
        'consuming_surfaces': CONSUMING_SURFACES,
        'invariants_pass': bool(
            recon.get('contradictions') == 0
            and recon.get('orphans') == 0
            and recon.get('duplicates') == 0
            and cross_surface_ok),
    }
    return out


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    out = build(sys.argv[1])
    with io.open(sys.argv[2], 'w', encoding='utf-8', newline='\n') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    r = out['reconciliation']
    print('FINAL_TRUTH_RECONCILIATION written: %s' % sys.argv[2])
    print('  reviewed=%s  contradictions=%s  orphans=%s  duplicates=%s  invariants_pass=%s'
          % (out['reviewed_hands'], r['contradictions'], r['orphans'],
             r['duplicate_final_owners'], out['invariants_pass']))


if __name__ == '__main__':
    main()
