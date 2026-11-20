/**
 * UK Sponsor Register – daily check (Google Apps Script, runs inside Google; no PC needed).
 *
 * Install (once, about 5 minutes):
 *   1. Open the Google Sheet "UK Sponsor Register – Job Search".
 *   2. Extensions → Apps Script. Delete any code in Code.gs and paste this whole file. Save.
 *   3. In the function dropdown pick `setup` and click Run. Approve the permissions
 *      (it asks for: this spreadsheet, Google Drive (to keep its state file next to the sheet),
 *      fetching gov.uk, and sending you email if a run fails).
 *   4. If asked about the runtime: this script needs the default V8 runtime.
 *   5. Done. `setup` runs the first check immediately and schedules a daily run at ~6am UK time.
 *
 * What it does every day
 *   - Finds today's register CSV via the GOV.UK Content API (link is never hard-coded).
 *   - Validates it (exact header, ≥50k rows, ≥30k Skilled Worker rows, no >5% drop).
 *     A bad file is rejected and yesterday's data is kept.
 *   - Writes tab "A-rated Skilled Worker" (normalised_name, organisation, town, county, rating).
 *   - Diffs against the previous run (Skilled Worker route only) using a state file
 *     "sponsor-register-state.json.gz" (compressed) kept next to this spreadsheet in Drive.
 *   - Writes tabs "Latest changes", "Change history" (all changes, appended) and "Change log"
 *     (one summary row per run), and updates "Status".
 *   - Emails you if the check fails.
 *
 * The pure functions (normaliseName, ratingOf, isARating, parseRegister, buildIndex, diffIndex)
 * match sponsors/sponsor_check.py so matching behaves the same everywhere.
 */

var CONFIG = {
  CONTENT_API: 'https://www.gov.uk/api/content/government/publications/register-of-licensed-sponsors-workers',
  ASSET_HOST: 'assets.publishing.service.gov.uk',
  HEADER: ['Organisation Name', 'Town/City', 'County', 'Type & Rating', 'Route'],
  MIN_ROWS: 50000,
  MIN_SKILLED_ROWS: 30000,
  MAX_SKILLED_DROP: 0.05,
  STATE_FILE: 'sponsor-register-state.json.gz',
  TABS: {
    status: 'Status',
    latest: 'Latest changes',
    history: 'Change history',
    log: 'Change log',
    aRated: 'A-rated Skilled Worker'
  },
  WRITE_CHUNK: 20000,
  RUN_HOUR: 6
};

var SUFFIXES = new Set(['ltd', 'limited', 'plc', 'llp', 'uk', 'group', 'holdings', 'the']);

// ----------------------------------------------------------------------------- pure helpers

function clean_(v) {
  return String(v == null ? '' : v).replace(/\s+/g, ' ').trim();
}

function normaliseName(name) {
  var s = String(name).normalize('NFKD').replace(/[^\x00-\x7F]/g, '');
  s = s.toLowerCase().replace(/&/g, ' and ');
  s = s.replace(/\(.*?\)/g, ' ');
  s = s.replace(/[^a-z0-9 ]+/g, ' ');
  return s.split(' ').filter(function (w) { return w && !SUFFIXES.has(w); }).join(' ');
}

function diffName_(name) {
  return clean_(name).toLowerCase();
}

function ratingOf(typeAndRating) {
  var m = /\((.*)\)/.exec(typeAndRating);
  return clean_(m ? m[1] : typeAndRating);
}

function isARating(rating) {
  return /^A\b/i.test(clean_(rating));
}

/** rows: array of arrays (first row = header). Returns array of row objects. Throws on bad data. */
function parseRegister(rows, strict) {
  if (!rows || !rows.length) throw new Error('Empty file');
  var header = rows[0].map(clean_);
  if (header.join('|') !== CONFIG.HEADER.join('|')) {
    throw new Error('Unexpected header ' + JSON.stringify(header));
  }
  var out = [];
  for (var i = 1; i < rows.length; i++) {
    var r = rows[i];
    if (!r || !r.some(function (c) { return clean_(c) !== ''; })) continue;
    out.push({
      name: clean_(r[0]), town: clean_(r[1]), county: clean_(r[2]),
      type: clean_(r[3]), route: clean_(r[4])
    });
  }
  if (strict) {
    if (out.length < CONFIG.MIN_ROWS) throw new Error('Only ' + out.length + ' rows; file looks partial');
    var sw = out.filter(function (r) { return r.route === 'Skilled Worker'; }).length;
    if (sw < CONFIG.MIN_SKILLED_ROWS) throw new Error('Only ' + sw + ' Skilled Worker rows');
  }
  return out;
}

/** Skilled Worker index: key "name|town" -> {n: name, t: town, c: county, r: "rating; rating"} */
function buildIndex(rows) {
  var tmp = Object.create(null);
  rows.forEach(function (r) {
    if (r.route !== 'Skilled Worker') return;
    var k = diffName_(r.name) + '|' + r.town.toLowerCase();
    if (!tmp[k]) tmp[k] = { n: r.name, t: r.town, c: r.county, rs: {} };
    tmp[k].rs[ratingOf(r.type)] = 1;
  });
  var idx = Object.create(null);
  Object.keys(tmp).forEach(function (k) {
    var e = tmp[k];
    idx[k] = { n: e.n, t: e.t, c: e.c, r: Object.keys(e.rs).sort().join('; ') };
  });
  return idx;
}

/** Compact form for the state file: [[name, town, county, ratings], ...] */
function indexToList(idx) {
  return Object.keys(idx).map(function (k) { var e = idx[k]; return [e.n, e.t, e.c, e.r]; });
}

function indexFromList(list) {
  var idx = Object.create(null);
  list.forEach(function (e) {
    idx[diffName_(e[0]) + '|' + String(e[1]).toLowerCase()] = { n: e[0], t: e[1], c: e[2], r: e[3] };
  });
  return idx;
}

function diffIndex(oldIdx, newIdx) {
  var out = [];
  Object.keys(newIdx).sort().forEach(function (k) {
    var n = newIdx[k], o = oldIdx[k];
    if (!o) out.push(['added', n.n, n.t, n.c, '', n.r]);
    else if (o.r !== n.r) out.push(['rating_changed', n.n, n.t, n.c, o.r, n.r]);
  });
  Object.keys(oldIdx).sort().forEach(function (k) {
    if (!newIdx[k]) { var o = oldIdx[k]; out.push(['removed', o.n, o.t, o.c, o.r, '']); }
  });
  var order = { added: 0, removed: 1, rating_changed: 2 };
  out.sort(function (a, b) { return order[a[0]] - order[b[0]]; });
  return out;
}

function aRatedRows(rows) {
  var seen = Object.create(null), out = [];
  rows.forEach(function (r) {
    if (r.route !== 'Skilled Worker' || !/^worker/i.test(r.type) || !isARating(ratingOf(r.type))) return;
    var k = diffName_(r.name) + '|' + r.town.toLowerCase();
    if (seen[k]) return;
    seen[k] = 1;
    out.push([normaliseName(r.name), r.name, r.town, r.county, ratingOf(r.type)]);
  });
  return out;
}

// ----------------------------------------------------------------------------- Google side

function fetch_(url) {
  var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
  if (res.getResponseCode() !== 200) throw new Error('HTTP ' + res.getResponseCode() + ' for ' + url);
  return res;
}

function findCsvUrl_() {
  var data = JSON.parse(fetch_(CONFIG.CONTENT_API).getContentText());
  var atts = (data.details && data.details.attachments) || [];
  var csvs = atts.filter(function (a) {
    return a.content_type === 'text/csv' || /\.csv$/i.test(String(a.url || '').split('?')[0]);
  });
  if (!csvs.length) throw new Error('No CSV attachment on the GOV.UK publication');
  var worker = csvs.filter(function (a) { return /worker/i.test((a.title || '') + (a.url || '')); });
  if (worker.length > 1) throw new Error(worker.length + ' candidate CSVs; refusing to guess');
  var pick = (worker.length ? worker : csvs)[0];
  var url = /^https?:/.test(pick.url) ? pick.url : 'https://www.gov.uk' + pick.url;
  if (url.indexOf('https://' + CONFIG.ASSET_HOST + '/') !== 0) throw new Error('Unexpected CSV host: ' + url);
  return { url: url, updated: data.public_updated_at || '' };
}

function sheet_(ss, name, header) {
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (header && sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight('bold');
    sh.setFrozenRows(1);
    if (sh.getMaxColumns() > header.length) sh.deleteColumns(header.length + 1, sh.getMaxColumns() - header.length);
  }
  return sh;
}

function stateFile_(ss) {
  var folder = DriveApp.getFileById(ss.getId()).getParents().next();
  // getFilesByName also returns trashed files, so search explicitly and take the newest.
  var it = folder.searchFiles('title = "' + CONFIG.STATE_FILE + '" and trashed = false'), f = null;
  while (it.hasNext()) { var x = it.next(); if (!f || x.getLastUpdated() > f.getLastUpdated()) f = x; }
  return { folder: folder, file: f };
}

/** State is gzipped JSON (~1-2 MB) so it stays well inside Drive/Apps Script size limits. */
function loadState_(file) {
  var blob = file.getBlob().setContentType('application/x-gzip');
  var st = JSON.parse(Utilities.ungzip(blob).getDataAsString('UTF-8'));
  st.index = indexFromList(st.list);
  delete st.list;
  return st;
}

function saveState_(st, obj) {
  obj.list = indexToList(obj.index);
  delete obj.index;
  var blob = Utilities.gzip(Utilities.newBlob(JSON.stringify(obj), 'application/json'), CONFIG.STATE_FILE);
  var created = st.folder.createFile(blob).setName(CONFIG.STATE_FILE);
  if (st.file) st.file.setTrashed(true);  // replace the old state only after the new one is saved
  return created;
}

function writeStatus_(ss, pairs) {
  var sh = sheet_(ss, CONFIG.TABS.status, ['Field', 'Value']);
  sh.getRange(2, 1, Math.max(sh.getLastRow() - 1, 1), 2).clearContent();
  sh.getRange(2, 1, pairs.length, 2).setValues(pairs);
}

function writeRows_(sh, header, rows) {
  sh.clear();
  sh.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight('bold');
  sh.setFrozenRows(1);
  var needed = rows.length + 1;
  if (sh.getMaxRows() < needed) sh.insertRowsAfter(sh.getMaxRows(), needed - sh.getMaxRows());
  for (var i = 0; i < rows.length; i += CONFIG.WRITE_CHUNK) {
    var part = rows.slice(i, i + CONFIG.WRITE_CHUNK);
    sh.getRange(i + 2, 1, part.length, header.length).setValues(part);
  }
  trim_(sh, needed, header.length);
}

/** Keep the grid exactly as big as the data so the 10M-cell limit is never approached. */
function trim_(sh, rows, cols) {
  var mr = sh.getMaxRows(), mc = sh.getMaxColumns();
  if (mr > rows) sh.deleteRows(rows + 1, mr - rows);
  if (mc > cols) sh.deleteColumns(cols + 1, mc - cols);
}

/** Write into a temporary tab, then swap it in, so a failed run never leaves a half-written tab. */
function replaceTab_(ss, name, header, rows) {
  var tmpName = name + ' (updating)';
  var old = ss.getSheetByName(tmpName);
  if (old) ss.deleteSheet(old);
  var tmp = ss.insertSheet(tmpName);
  writeRows_(tmp, header, rows);
  SpreadsheetApp.flush();
  var cur = ss.getSheetByName(name);
  var pos = cur ? cur.getIndex() : ss.getNumSheets();
  if (cur) ss.deleteSheet(cur);
  tmp.setName(name);
  ss.setActiveSheet(tmp);
  ss.moveActiveSheet(pos);
  return tmp;
}

function today_() {
  return Utilities.formatDate(new Date(), 'Europe/London', 'yyyy-MM-dd');
}

/** Main entry point (scheduled daily). */
function runDailyCheck() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    // Something else (e.g. the careers finder) is running: try again in 10 minutes instead of skipping the day.
    ScriptApp.newTrigger('runDailyCheckRetry').timeBased().after(10 * 60 * 1000).create();
    return;
  }
  try { runDailyCheck_(); } finally { lock.releaseLock(); }
}

function runDailyCheckRetry() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runDailyCheckRetry') ScriptApp.deleteTrigger(t);
  });
  runDailyCheck();
}

function runDailyCheck_() {
  var ss = SpreadsheetApp.getActive();
  var date = today_();
  try {
    var src = findCsvUrl_();
    var st = stateFile_(ss);
    var state = st.file ? loadState_(st.file) : null;

    var fileDate = (/(\d{4}-\d{2}-\d{2})/.exec(src.url.split('/').pop()) || [, ''])[1];
    if (state && state.url === src.url) {
      writeStatus_(ss, statusPairs_(date, src, 'ok – no new register file since ' + state.date +
        ' ("Latest changes" still shows that run)', state.summary));
      sheet_(ss, CONFIG.TABS.log, LOG_HEADER).appendRow([date, 'no new file', fileDate, '', '', 0, 0, 0]);
      return;
    }

    var res = fetch_(src.url);
    var text = res.getContentText('UTF-8');
    if (!/\n$/.test(text)) throw new Error('File does not end with a newline; looks truncated');
    var rows = parseRegister(Utilities.parseCsv(text), true);
    text = null;  // free memory
    var idx = buildIndex(rows);
    var swCount = rows.filter(function (r) { return r.route === 'Skilled Worker'; }).length;

    var changes = [];
    if (state) {
      var props = PropertiesService.getScriptProperties();
      var accept = props.getProperty('ACCEPT_DROP') === 'yes';
      if (!accept && state.swCount && (state.swCount - swCount) / state.swCount > CONFIG.MAX_SKILLED_DROP) {
        throw new Error('Skilled Worker rows fell from ' + state.swCount + ' to ' + swCount + ' (>5%); file rejected. ' +
          'If this drop is real, set Script property ACCEPT_DROP = yes and run runDailyCheck once.');
      }
      if (accept) props.deleteProperty('ACCEPT_DROP');
      changes = diffIndex(state.index, idx);
    }

    var aRated = aRatedRows(rows);
    // Add careers links found by CareersFinder.gs (Employer directory tab), if installed.
    var dir = (typeof readDirectory_ === 'function') ? readDirectory_(ss) : Object.create(null);
    aRated = aRated.map(function (r) {
      var d = dir[r[0] + '|' + String(r[2]).toLowerCase()];
      return r.concat(d ? [d.values[4], d.values[5], d.values[7], d.values[11]] : ['', '', '', '']);
    });
    replaceTab_(ss, CONFIG.TABS.aRated, ['normalised_name', 'organisation', 'town', 'county', 'rating',
      'careers_url', 'ats', 'job_feed_url', 'link_confidence'], aRated);

    var latestRows = changes.map(function (c) { return [date].concat(c); });
    replaceTab_(ss, CONFIG.TABS.latest, CHANGE_HEADER,
      latestRows.length ? latestRows : [[date, state ? 'no changes' : 'baseline (first run)', '', '', '', '', '']]);

    var counts = { added: 0, removed: 0, rating_changed: 0 };
    changes.forEach(function (c) { counts[c[0]]++; });
    var summary = {
      rows: rows.length, aRated: aRated.length,
      added: counts.added, removed: counts.removed, rating_changed: counts.rating_changed
    };
    // Save state BEFORE appending history/log, so an interrupted run can't append the same changes twice.
    saveState_(st, { date: date, url: src.url, swCount: swCount, summary: summary, index: idx });

    if (latestRows.length) {
      var hist = sheet_(ss, CONFIG.TABS.history, CHANGE_HEADER);
      var need = hist.getLastRow() + latestRows.length;
      if (hist.getMaxRows() < need) hist.insertRowsAfter(hist.getMaxRows(), need - hist.getMaxRows());
      hist.getRange(hist.getLastRow() + 1, 1, latestRows.length, CHANGE_HEADER.length).setValues(latestRows);
    }
    sheet_(ss, CONFIG.TABS.log, LOG_HEADER).appendRow([date, state ? 'ok' : 'ok (baseline)', fileDate,
      rows.length, aRated.length, counts.added, counts.removed, counts.rating_changed]);
    writeStatus_(ss, statusPairs_(date, src, state ? 'ok' : 'ok (baseline)', summary));
  } catch (e) {
    try {
      writeStatus_(ss, [['Last run date', date], ['Run status', 'REGISTER CHECK FAILED: ' + e.message],
        ['Note', 'Tabs are replaced only after a complete write, so the previous data is still in place.']]);
    } catch (_) {}
    try { sheet_(ss, CONFIG.TABS.log, LOG_HEADER).appendRow([date, 'FAILED: ' + e.message, '', '', '', '', '', '']); } catch (_) {}
    try {
      MailApp.sendEmail(Session.getEffectiveUser().getEmail(), 'Sponsor register check FAILED',
        'The daily sponsor register check failed on ' + date + ':\n\n' + e.message +
        '\n\nPrevious data has been kept. Sheet: ' + ss.getUrl());
    } catch (_) {}
    throw e;  // Google also sends its own trigger-failure email as a backup
  }
}

var CHANGE_HEADER = ['date', 'change', 'organisation', 'town', 'county', 'old_rating', 'new_rating'];
var LOG_HEADER = ['date', 'status', 'register_file_date', 'total_rows', 'a_rated', 'added', 'removed', 'rating_changed'];

function statusPairs_(date, src, statusText, s) {
  s = s || {};
  return [
    ['Last run date', date],
    ['Run status', statusText],
    ['Current register CSV', src.url],
    ['GOV.UK last updated', src.updated],
    ['Total rows', s.rows || ''],
    ['Skilled Worker A-rated entries', s.aRated || ''],
    ['Added / removed / rating changed',
      s.rows ? (s.added + ' / ' + s.removed + ' / ' + s.rating_changed) : '']
  ];
}

/** Run once by hand: sets timezone, creates the daily trigger, runs the first check. */
function setup() {
  var ss = SpreadsheetApp.getActive();
  ss.setSpreadsheetTimeZone('Europe/London');
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runDailyCheck') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('runDailyCheck').timeBased().atHour(CONFIG.RUN_HOUR).everyDays(1)
    .inTimezone('Europe/London').create();
  runDailyCheck();
}

// Node test hook (ignored by Apps Script).
if (typeof module !== 'undefined') {
  module.exports = { normaliseName: normaliseName, ratingOf: ratingOf, isARating: isARating,
    parseRegister: parseRegister, buildIndex: buildIndex, indexToList: indexToList, indexFromList: indexFromList, diffIndex: diffIndex, aRatedRows: aRatedRows, CONFIG: CONFIG };
}
