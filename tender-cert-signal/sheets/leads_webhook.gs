/**
 * Receives leads from the tendersignal tool and keeps one row per lead in this sheet.
 *
 * - New leads are appended; leads already in the sheet get their tool-filled columns refreshed.
 * - The team's own columns (Status / Owner / Notes) are NEVER overwritten.
 * - Leads are matched on the "Lead ID" column, so you can sort, filter or reorder rows freely.
 *
 * Setup: see SETUP.md in this folder. Change TOKEN below to your own long random string.
 */
const TOKEN = 'change-me-to-a-long-random-string';
const SHEET_NAME = 'Leads';

// Order = column order in the sheet. The first field is the row key.
const TOOL_COLUMNS = [
  ['global_id', 'Lead ID'],
  ['supplier_name', 'Company'],
  ['supplier_canonical_name', 'Legal name (ABN)'],
  ['supplier_abn', 'ABN'],
  ['supplier_locality', 'City'],
  ['supplier_region', 'State'],
  ['supplier_entity_type_name', 'Entity type'],
  ['relevant_standards', 'Suggested ISO standards'],
  ['source', 'Source'],
  ['agency_name', 'Agency / list'],
  ['value_amount', 'Contract value (AUD)'],
  ['description', 'Description'],
  ['date_signed', 'Date signed'],
  ['period_end_date', 'Contract end'],
  ['match_score', 'Best registry match score'],
  ['first_seen', 'First seen'],
  ['tender_url', 'Link'],
];
const MANUAL_COLUMNS = ['Status', 'Owner', 'Notes'];

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.token !== TOKEN) return json_({ ok: false, error: 'bad token' });

    const lock = LockService.getScriptLock();
    lock.waitLock(30000);
    try {
      return json_(upsert_(body.leads || []));
    } finally {
      lock.releaseLock();
    }
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function upsert_(leads) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
  const headers = TOOL_COLUMNS.map(c => c[1]).concat(MANUAL_COLUMNS);

  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
    sheet.setFrozenRows(1);
  }

  // Index existing rows by Lead ID (column A).
  const lastRow = sheet.getLastRow();
  const existing = {};
  if (lastRow > 1) {
    sheet.getRange(2, 1, lastRow - 1, 1).getValues().forEach((r, i) => {
      if (r[0]) existing[r[0]] = i + 2;
    });
  }

  const toolWidth = TOOL_COLUMNS.length;
  let added = 0, updated = 0;
  const appendRows = [];
  leads.forEach(lead => {
    const values = TOOL_COLUMNS.map(c => lead[c[0]] === undefined ? '' : lead[c[0]]);
    const row = existing[lead.global_id];
    if (row) {
      sheet.getRange(row, 1, 1, toolWidth).setValues([values]);
      updated++;
    } else {
      appendRows.push(values.concat(MANUAL_COLUMNS.map((c, i) => (i === 0 ? 'New' : ''))));
      added++;
    }
  });
  if (appendRows.length) {
    sheet.getRange(sheet.getLastRow() + 1, 1, appendRows.length, headers.length).setValues(appendRows);
  }
  return { ok: true, added: added, updated: updated, total: leads.length };
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
