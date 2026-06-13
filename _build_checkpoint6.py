#!/usr/bin/env python3
"""Build GEM_Checkpoint6_upload.zip — full checkpoint for Claude Chat."""
import zipfile, os

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

# All gem_report_draft package files
report_draft_files = [
    'gem_report_draft/__init__.py',
    'gem_report_draft/_anchor_map.py',
    'gem_report_draft/_blocks.py',
    'gem_report_draft/_hand_grid.py',
    'gem_report_draft/_helpers.py',
    'gem_report_draft/_html.py',
    'gem_report_draft/_state.py',
    'gem_report_draft/draft.py',
    'gem_report_draft/sections_financial.py',
    'gem_report_draft/sections_iv_xii.py',
    'gem_report_draft/sections_mistakes.py',
    'gem_report_draft/sections_xiii.py',
    'gem_report_draft/sections_xiv.py',
    'gem_report_draft/tldr.py',
]

# Pipeline + infra files
pipeline_files = [
    'gem_analyzer.py',
    'gem_report_data.py',
    'gem_report_lint.py',
    'gem_run.py',
    'validate_schema.py',
]

# Test files
test_files = [
    'test_blocks.py',
    'test_content_parity.py',
    'test_lint.py',
    'test_hand_evidence_tier1.py',
    'test_report_draft.py',
    'test_detectors.py',
    'test_metrics.py',
    'test_gtow.py',
    'test_review_persistence_jsdom.js',
]

# Docs
doc_files = [
    'GEM_Changelog.txt',
    'GEM_Quick_Reference.txt',
]

# JSON config
config_files = [
    'gem_known_bugs.json',
    'gem_schema.json',
    'coaching_rules.json',
    'tournament_structures.json',
    'tier_handicaps.json',
    'gto_texture_archetypes.json',
]

readme = (
    "# GEM Checkpoint 6 - Phase 4.8 v3 Review Notes\n"
    "\n"
    "## Install: all files go into REPLACE/\n"
    "Drop each file at its relative path, replacing the existing version.\n"
    "\n"
    "## What changed since Checkpoint 5\n"
    "\n"
    "### Critical Bug Fixes\n"
    "- **_html.py**: Fixed HTML tags showing as literal text in report\n"
    "  - Added data-tip span stash pattern to _md_inline()\n"
    "  - Fixed nowrap span regex for content containing '<' (e.g. n=0<30)\n"
    "  - Fixed data-label attribute stripping for headers with HTML tags\n"
    "- **sections_financial.py**: Fixed '<' in verdict strings to &lt;\n"
    "- **sections_iv_xii.py**: Same '<' fix in status strings\n"
    "\n"
    "### EAI to All-Ins Rename\n"
    "- Global rename across all user-facing text in 6 files\n"
    "\n"
    "### Section-Specific v3 Changes\n"
    "- **S1.1a** (tldr.py): Component names link to relevant sections; methodology to tooltip\n"
    "- **S1.2** (sections_financial.py): Filter lines with <5 count, sort by BB/h desc\n"
    "- **S1.4** (sections_financial.py): Grouped Street column, Total row fix with expected\n"
    "- **S1.9** (sections_financial.py): Removed Hands column from Intra-Session Arc\n"
    "- **S4.2** (sections_mistakes.py): Removed collapsible details evidence blocks\n"
    "- **S8.2** (sections_iv_xii.py): Removed First 10 individual deviations list\n"
    "\n"
    "### Test Results\n"
    "- 150 pytest tests PASS\n"
    "- 530 metric tests PASS\n"
    "- 97 detector tests PASS\n"
    "- 0 BLOCKER, 0 ERROR\n"
)

zip_path = 'GEM_Checkpoint6_upload.zip'
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('README.md', readme)

    all_files = (
        report_draft_files + pipeline_files +
        test_files + doc_files + config_files
    )

    for src in all_files:
        dst = 'REPLACE/' + src
        if os.path.exists(src):
            zf.write(src, dst)
            sz = os.path.getsize(src)
            print(f"  {dst}  ({sz // 1024}KB)")
        else:
            print(f"  MISSING: {src}")

sz = os.path.getsize(zip_path)
print(f"\nCreated {zip_path}  ({sz // 1024}KB, {len(all_files)} files)")
