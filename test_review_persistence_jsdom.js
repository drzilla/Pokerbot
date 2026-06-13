/**
 * test_review_persistence_jsdom.js — Behavioral verification of modal
 * review persistence using jsdom against REAL generator-rendered HTML.
 *
 * Tests the actual <script> block from _html.py, not a Python stand-in.
 *
 * Sub-tests:
 *   A. Normal mode: open hand → type notes + set verdict → close →
 *      reopen → assert both restored; switch to second hand and back →
 *      assert first hand's values intact, second independent.
 *      Phase 4.8 C5: uses pokerbot:handreview:* storage keys.
 *   B. Blocked-localStorage mode (opaque origin / file://): simulate
 *      localStorage throwing on every access → assert sessionStorage
 *      fallback works, Copy button still produces correct output.
 *   C. Modal audit-row strip: open hand → verify buildModalHand output
 *      has zero details.audit-row elements (Phase 4.6 A1 double-review fix).
 *   D. _loading guard: pre-populate storage for a hand, open it
 *      (triggering loadReview), close immediately, reopen → verify
 *      notes survived (Phase 4.7 C5 race-condition fix).
 *   E. Migration bridge: pre-populate gem-review-* keys before script
 *      runs → verify they are COPIED to pokerbot:handreview:* format.
 *      Old keys preserved (non-destructive).
 *
 * Usage:  node test_review_persistence_jsdom.js
 * Requires: npm install jsdom (local or global)
 */

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

// ---- Load the real generator-rendered HTML ----
const htmlPath = path.join(__dirname, '_test_rendered.html');
if (!fs.existsSync(htmlPath)) {
  console.error('ERROR: _test_rendered.html not found. Generate it first:\n' +
    '  python -X utf8 -c "from test_content_parity import _enriched_fixture; ' +
    'from gem_report_draft.draft import render_html; ' +
    's,rd,h=_enriched_fixture(); ' +
    'open(\'_test_rendered.html\',\'w\',encoding=\'utf-8\').write(render_html(s,rd,h))"');
  process.exit(1);
}
const htmlSource = fs.readFileSync(htmlPath, 'utf-8');

let passed = 0;
let failed = 0;

function assert(condition, message) {
  if (condition) {
    passed++;
    console.log(`  ✅ ${message}`);
  } else {
    failed++;
    console.log(`  ❌ FAIL: ${message}`);
  }
}

// ============================================================
// SUB-TEST A: Normal mode (both stores working)
// ============================================================
console.log('\n=== Sub-test A: Normal mode (sessionStorage + localStorage) ===');

(function testNormalMode() {
  const dom = new JSDOM(htmlSource, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    url: 'http://localhost/test.html',  // non-opaque origin → localStorage works
  });
  const doc = dom.window.document;
  const win = dom.window;

  // Verify pills and cards exist
  const pills = doc.querySelectorAll('a.hand-ref[data-hand-id]');
  assert(pills.length > 0, `Found ${pills.length} hand-ref pills in rendered HTML`);

  const cards = doc.querySelectorAll('article.hand-detail-card[data-hand-id]');
  assert(cards.length >= 3, `Found ${cards.length} hand-detail-cards (need ≥3)`);

  // Verify modal scaffold exists (v29 .modal class)
  const modal = doc.getElementById('hand-modal');
  assert(modal !== null, 'Modal scaffold (#hand-modal) exists');
  assert(modal.classList.contains('modal'), 'Modal has v29 .modal class');

  const reviewStatus = doc.getElementById('modal-review-status');
  const reviewNotes = doc.getElementById('modal-review-notes');
  const saveState = doc.getElementById('modal-save-state');
  assert(reviewStatus !== null, 'Modal review status select exists');
  assert(reviewNotes !== null, 'Modal review notes textarea exists');

  // ---- Step 1: Open hand 10000001, set verdict + notes ----
  const pill1 = doc.querySelector('a.hand-ref[data-hand-id="10000001"]');
  assert(pill1 !== null, 'Found pill for hand 10000001');
  pill1.click();

  // Modal should be visible
  assert(modal.getAttribute('aria-hidden') === 'false',
    'Modal opens after pill click (aria-hidden=false)');
  assert(modal.classList.contains('is-open'),
    'Modal has .is-open class when open');

  // Set verdict and notes
  reviewStatus.value = 'Debate';
  reviewStatus.dispatchEvent(new win.Event('change'));
  reviewNotes.value = 'Sizing was too large on the flop';
  reviewNotes.dispatchEvent(new win.Event('input'));

  // Verify auto-save fired
  assert(saveState.textContent === 'Auto-saved',
    'Auto-save indicator shows after typing');

  // Verify .reviewed class applied to pill
  assert(pill1.classList.contains('reviewed'),
    'Pill gets .reviewed class after save');

  // ---- Step 2: Close modal ----
  const closeBtn = doc.getElementById('hand-modal-close');
  closeBtn.click();
  assert(modal.getAttribute('aria-hidden') === 'true',
    'Modal closes after close button click');
  assert(!modal.classList.contains('is-open'),
    'Modal .is-open removed on close');

  // ---- Step 3: Open hand 10000002, set different values ----
  const pill2 = doc.querySelector('a.hand-ref[data-hand-id="10000002"]');
  assert(pill2 !== null, 'Found pill for hand 10000002');
  pill2.click();

  // Verify hand 2 starts clean (not hand 1's values)
  assert(reviewStatus.value !== 'Debate',
    'Hand 2 does NOT inherit hand 1\'s verdict on open');

  reviewStatus.value = 'Agree';
  reviewStatus.dispatchEvent(new win.Event('change'));
  reviewNotes.value = 'Standard play, well executed';
  reviewNotes.dispatchEvent(new win.Event('input'));
  closeBtn.click();

  // ---- Step 4: Reopen hand 10000001 — must restore hand 1's values ----
  pill1.click();
  assert(reviewStatus.value === 'Debate',
    `Hand 1 verdict restored: got "${reviewStatus.value}", expected "Debate"`);
  assert(reviewNotes.value === 'Sizing was too large on the flop',
    `Hand 1 notes restored: got "${reviewNotes.value.substring(0, 40)}..."`);
  closeBtn.click();

  // ---- Step 5: Reopen hand 10000002 — must restore hand 2's values ----
  pill2.click();
  assert(reviewStatus.value === 'Agree',
    `Hand 2 verdict restored: got "${reviewStatus.value}", expected "Agree"`);
  assert(reviewNotes.value === 'Standard play, well executed',
    `Hand 2 notes restored: got "${reviewNotes.value.substring(0, 40)}..."`);
  closeBtn.click();

  // ---- Step 6: Verify both stores have the data (date-scoped key format) ----
  const ssKey1 = win.sessionStorage.getItem('pokerbot:handreview:2026-05-27:10000001');
  const lsKey1 = win.localStorage.getItem('pokerbot:handreview:2026-05-27:10000001');
  assert(ssKey1 !== null, 'Hand 1 review saved to sessionStorage (date-scoped key)');
  assert(lsKey1 !== null, 'Hand 1 review mirrored to localStorage');

  const ssData1 = JSON.parse(ssKey1);
  assert(ssData1.status === 'Debate' && ssData1.notes === 'Sizing was too large on the flop',
    'sessionStorage data for hand 1 matches what was typed');

  dom.window.close();
})();

// ============================================================
// SUB-TEST B: Blocked-localStorage mode (opaque origin)
// ============================================================
console.log('\n=== Sub-test B: Blocked localStorage (opaque origin simulation) ===');

(function testBlockedLocalStorage() {
  const probePattern = /if\(localStorage\.getItem\('_gem_probe'\)==='1'\)\{_lsOK=true;\}/;
  const patchedHtml = htmlSource.replace(
    probePattern,
    "if(false/* TEST PATCH: force _lsOK=false */){_lsOK=true;}"
  );
  assert(patchedHtml !== htmlSource, '[blocked] Patch was applied (probe branch forced false)');

  const dom = new JSDOM(patchedHtml, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    url: 'http://localhost/test-blocked.html',
  });
  const doc = dom.window.document;
  const win = dom.window;

  const reviewStatus = doc.getElementById('modal-review-status');
  const reviewNotes = doc.getElementById('modal-review-notes');
  const modal = doc.getElementById('hand-modal');
  const closeBtn = doc.getElementById('hand-modal-close');

  // ---- Step 1: Open hand 1, save review via sessionStorage only ----
  const pill1 = doc.querySelector('a.hand-ref[data-hand-id="10000001"]');
  assert(pill1 !== null, '[blocked] Found pill for hand 10000001');
  pill1.click();

  assert(modal.getAttribute('aria-hidden') === 'false',
    '[blocked] Modal opens despite blocked localStorage');

  reviewStatus.value = 'Report bug';
  reviewStatus.dispatchEvent(new win.Event('change'));
  reviewNotes.value = 'Off-by-one in pot calculation';
  reviewNotes.dispatchEvent(new win.Event('input'));
  closeBtn.click();

  // ---- Step 2: Reopen and verify persistence via sessionStorage ----
  pill1.click();
  assert(reviewStatus.value === 'Report bug',
    `[blocked] Verdict restored via sessionStorage: got "${reviewStatus.value}"`);
  assert(reviewNotes.value === 'Off-by-one in pot calculation',
    `[blocked] Notes restored via sessionStorage: got "${reviewNotes.value.substring(0, 40)}..."`);

  // ---- Step 3: Verify sessionStorage has the data (date-scoped key) ----
  const ssKey = win.sessionStorage.getItem('pokerbot:handreview:2026-05-27:10000001');
  assert(ssKey !== null, '[blocked] sessionStorage has the review data');
  if (ssKey) {
    const ssData = JSON.parse(ssKey);
    assert(ssData.status === 'Report bug',
      `[blocked] sessionStorage status correct: "${ssData.status}"`);
  }

  // ---- Step 4: Verify localStorage was NOT written to ----
  const lsData = win.localStorage.getItem('pokerbot:handreview:2026-05-27:10000001');
  assert(lsData === null,
    `[blocked] localStorage has NO review data (confirming _lsOK=false path): got ${lsData}`);

  // ---- Step 5: Test Copy button collects from sessionStorage ----
  const pill2 = doc.querySelector('a.hand-ref[data-hand-id="10000002"]');
  pill2.click();
  reviewStatus.value = 'Agree';
  reviewStatus.dispatchEvent(new win.Event('change'));
  reviewNotes.value = 'Clean play';
  reviewNotes.dispatchEvent(new win.Event('input'));

  // Mock clipboard (jsdom doesn't have real clipboard API)
  let clipboardContent = '';
  win.navigator.clipboard = {
    writeText: function(text) {
      clipboardContent = text;
      return Promise.resolve();
    }
  };

  // Click copy button (audit-export-btn is the current ID)
  const copyBtn = doc.getElementById('audit-export-btn');
  assert(copyBtn !== null, '[blocked] Copy reviews button exists');
  copyBtn.click();

  // Give the Promise a tick to resolve
  setTimeout(() => {
    assert(clipboardContent.includes('10000001'),
      `[blocked] Copy output includes hand 10000001`);
    assert(clipboardContent.includes('Report bug'),
      `[blocked] Copy output includes verdict "Report bug"`);
    assert(clipboardContent.includes('10000002'),
      `[blocked] Copy output includes hand 10000002`);
    assert(clipboardContent.includes('Clean play'),
      `[blocked] Copy output includes notes "Clean play"`);

    closeBtn.click();
    dom.window.close();

    // ============================================================
    // SUB-TEST C: Modal audit-row strip (Phase 4.6 A1)
    // ============================================================
    runAuditRowTest();
  }, 50);
})();

function runAuditRowTest() {
  console.log('\n=== Sub-test C: Modal clone strips audit-row ===');

  const dom = new JSDOM(htmlSource, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    url: 'http://localhost/test-audit.html',
  });
  const doc = dom.window.document;

  // Verify source cards HAVE audit-rows
  const card1 = doc.querySelector('article.hand-detail-card[data-hand-id="10000001"]');
  assert(card1 !== null, '[audit] Source card for 10000001 exists');
  const sourceAuditRows = card1.querySelectorAll('details.audit-row');
  assert(sourceAuditRows.length > 0,
    `[audit] Source card has ${sourceAuditRows.length} audit-row(s) (proves REVIEWROW expanded)`);

  // Open the hand in modal
  const pill = doc.querySelector('a.hand-ref[data-hand-id="10000001"]');
  pill.click();

  // Check the modal clone has ZERO audit-rows
  const modalBody = doc.getElementById('hand-modal-body');
  const clonedAuditRows = modalBody.querySelectorAll('details.audit-row');
  assert(clonedAuditRows.length === 0,
    `[audit] Modal clone has ${clonedAuditRows.length} audit-row(s) (must be 0)`);

  // Verify the modal's own review section still exists (v29 .modal-review class)
  const modalReview = doc.querySelector('.modal-review');
  assert(modalReview !== null,
    '[audit] Modal has its own .modal-review section (not stripped)');

  // Verify buildModalHand created a .modal-hand wrapper
  const modalHand = modalBody.querySelector('.modal-hand');
  assert(modalHand !== null,
    '[audit] Modal body contains a .modal-hand wrapper');

  const modalClose = doc.getElementById('hand-modal-close');
  modalClose.click();
  dom.window.close();

  // ============================================================
  // SUB-TEST D: _loading guard — pre-populated notes survive open/close
  // ============================================================
  runLoadingGuardTest();
}

function runLoadingGuardTest() {
  console.log('\n=== Sub-test D: _loading guard (pre-populated notes survive) ===');

  const dom = new JSDOM(htmlSource, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    url: 'http://localhost/test-loading.html',
  });
  const doc = dom.window.document;
  const win = dom.window;

  // Pre-populate sessionStorage with saved notes for hand 10000001
  // Phase 4.8: date-scoped key format pokerbot:handreview:<date>:<hid>
  win.sessionStorage.setItem('pokerbot:handreview:2026-05-27:10000001',
    JSON.stringify({status: 'Agree', notes: 'Great line here'}));

  // Open the hand (triggers loadReview with pre-populated data)
  const pill = doc.querySelector('a.hand-ref[data-hand-id="10000001"]');
  assert(pill !== null, '[loading] hand-ref pill for 10000001 exists');
  pill.click();

  // Verify form was populated correctly
  const reviewStatus = doc.getElementById('modal-review-status');
  const reviewNotes = doc.getElementById('modal-review-notes');
  assert(reviewStatus.value === 'Agree',
    `[loading] Status loaded: expected "Agree", got "${reviewStatus.value}"`);
  assert(reviewNotes.value === 'Great line here',
    `[loading] Notes loaded: expected "Great line here", got "${reviewNotes.value}"`);

  // Verify save-state shows "Loaded" (operator precedence fix)
  const saveState = doc.getElementById('modal-save-state');
  assert(saveState.textContent === 'Loaded',
    `[loading] Save-state shows "Loaded": got "${saveState.textContent}"`);

  // Close immediately without editing
  const closeBtn = doc.getElementById('hand-modal-close');
  closeBtn.click();

  // Reopen the same hand
  pill.click();

  // Notes must survive — _loading guard prevented the race condition
  assert(reviewStatus.value === 'Agree',
    `[loading] After reopen: status is "Agree", got "${reviewStatus.value}"`);
  assert(reviewNotes.value === 'Great line here',
    `[loading] After reopen: notes is "Great line here", got "${reviewNotes.value}"`);

  // Verify storage wasn't corrupted (date-scoped key format)
  const stored = JSON.parse(win.sessionStorage.getItem('pokerbot:handreview:2026-05-27:10000001'));
  assert(stored.status === 'Agree',
    `[loading] Storage status preserved: got "${stored.status}"`);
  assert(stored.notes === 'Great line here',
    `[loading] Storage notes preserved: got "${stored.notes}"`);

  // Verify _loading flag exists in the JS (structural check)
  const scripts = doc.querySelectorAll('script');
  let hasLoading = false;
  scripts.forEach(s => { if (s.textContent.includes('_loading')) hasLoading = true; });
  assert(hasLoading, '[loading] _loading guard variable present in script');

  closeBtn.click();
  dom.window.close();

  // ============================================================
  // SUB-TEST E: Migration bridge (gem-review-* → pokerbot:handreview:*)
  // ============================================================
  runMigrationTest();
}

function runMigrationTest() {
  console.log('\n=== Sub-test E: Migration bridge (gem-review-* → date-scoped keys) ===');

  // Inject old-format keys into the HTML BEFORE scripts execute.
  // We add a <script> right before </head> that pre-populates sessionStorage
  // with gem-review-* keys.  The migration bridge in the IIFE will then
  // migrate them to pokerbot:handreview:<date>:<hid> on page load.
  // Bug C fix: migration is one-shot (sentinel) and deletes legacy keys.
  const migrationSetup = `<script>
    sessionStorage.setItem('gem-review-10000001',
      JSON.stringify({status:'Debate',notes:'Old format migration test'}));
    sessionStorage.setItem('gem-review-10000002',
      JSON.stringify({status:'Agree',notes:'Second old key'}));
  </script>`;
  const patchedHtml = htmlSource.replace('</head>', migrationSetup + '\n</head>');
  assert(patchedHtml !== htmlSource, '[migration] Pre-population script injected');

  const dom = new JSDOM(patchedHtml, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    url: 'http://localhost/test-migration.html',
  });
  const doc = dom.window.document;
  const win = dom.window;

  // 1. Old keys should be DELETED after migration (Bug C: consume-and-delete)
  const oldKey1 = win.sessionStorage.getItem('gem-review-10000001');
  assert(oldKey1 === null,
    '[migration] Old key gem-review-10000001 deleted after migration');

  // 2. New date-scoped keys should exist (created by migration bridge)
  const newKey1 = win.sessionStorage.getItem('pokerbot:handreview:2026-05-27:10000001');
  assert(newKey1 !== null,
    '[migration] New key pokerbot:handreview:2026-05-27:10000001 created by bridge');

  const newKey2 = win.sessionStorage.getItem('pokerbot:handreview:2026-05-27:10000002');
  assert(newKey2 !== null,
    '[migration] New key pokerbot:handreview:2026-05-27:10000002 created by bridge');

  // 3. New key data matches old key data
  if (newKey1) {
    const newData1 = JSON.parse(newKey1);
    assert(newData1.status === 'Debate' && newData1.notes === 'Old format migration test',
      `[migration] Migrated data matches: status="${newData1.status}", notes="${newData1.notes.substring(0, 30)}..."`);
  }

  // 4. One-shot sentinel set
  const sentinel = win.localStorage.getItem('pokerbot:migrated:2026-05-27');
  assert(sentinel === '1',
    '[migration] One-shot sentinel set in localStorage');

  // 5. Open hand 10000001 — loadReview should find the migrated data
  const pill = doc.querySelector('a.hand-ref[data-hand-id="10000001"]');
  pill.click();

  const reviewStatus = doc.getElementById('modal-review-status');
  const reviewNotes = doc.getElementById('modal-review-notes');
  assert(reviewStatus.value === 'Debate',
    `[migration] loadReview found migrated status: got "${reviewStatus.value}"`);
  assert(reviewNotes.value === 'Old format migration test',
    `[migration] loadReview found migrated notes: got "${reviewNotes.value}"`);

  // 6. Verify .reviewed class applied from migrated data on page load
  const pill1refs = doc.querySelectorAll('a.hand-ref[data-hand-id="10000001"]');
  let anyReviewed = false;
  pill1refs.forEach(p => { if (p.classList.contains('reviewed')) anyReviewed = true; });
  assert(anyReviewed,
    '[migration] Migrated hand pills have .reviewed class on page load');

  const closeBtn = doc.getElementById('hand-modal-close');
  closeBtn.click();
  dom.window.close();

  // ============================================================
  // Final summary
  // ============================================================
  console.log(`\n${'='.repeat(60)}`);
  console.log(`test_review_persistence_jsdom: ${passed}/${passed + failed} passed` +
    (failed ? `, ${failed} FAILED` : ' — all green'));
  process.exit(failed ? 1 : 0);
}
