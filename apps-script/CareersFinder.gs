/**
 * Careers finder: adds careers / job-portal links for sponsors, automatically and for free.
 * Lives in the same Apps Script project as SponsorRegister.gs (add it as a second file).
 *
 * How it works
 *   - Every 15 minutes it takes the next batch of not-yet-checked sponsors from the
 *     "A-rated Skilled Worker" tab, highest priority first (see priorityScore).
 *   - For each one it tests whether the employer uses Greenhouse, Lever or Ashby. These
 *     hiring systems publish free public job feeds, so a match gives both a careers link
 *     and a feed the daily job search can read without scraping.
 *   - Results go to the "Employer directory" tab (one row per sponsor checked).
 *     Rows with source = "manual" or "agent" are never overwritten by this script, so you
 *     (or Claude's daily agent) can add or correct links by hand.
 *   - SponsorRegister.gs copies careers_url / ats / job_feed_url into the
 *     "A-rated Skilled Worker" tab on each daily run.
 *
 * Install: add this file (+ → Script, name it CareersFinder), save, then run `setupCareers` once.
 * Rows with ats = 'retry' hit a temporary error (rate limit etc.) and are retried the next day.
 *
 * Limits: Google allows ~20,000 web requests a day on a personal account. This uses up to
 * DAILY_FETCH_BUDGET of them (the sponsor check needs only 2), which covers roughly
 * 3,000-4,000 sponsors a day, best-first.
 */

var CAREERS = {
  DIR_TAB: 'Employer directory',
  TODO_TAB: 'Careers to find',      // short worklist for Claude's daily agent (web search)
  TODO_SIZE: 30,
  DIR_HEADER: ['normalised_name', 'organisation', 'town', 'priority', 'careers_url', 'ats', 'ats_slug',
    'job_feed_url', 'open_jobs', 'uk_jobs', 'data_jobs', 'confidence', 'source', 'last_checked', 'notes'],
  BATCH_COMPANIES: 200,       // per 15-minute run
  DAILY_FETCH_BUDGET: 16000,
  PARALLEL: 30,               // requests per UrlFetchApp.fetchAll call
  MAX_RUN_MS: 3.5 * 60 * 1000
};

var UK_RE = /\b(united kingdom|uk|u\.k\.|england|scotland|wales|northern ireland|london|glasgow|edinburgh|manchester|birmingham|leeds|bristol|cambridge|oxford|belfast|cardiff|aberdeen|dundee|newcastle|liverpool|sheffield|nottingham|reading|remote)\b/i;
var DATA_RE = /\b(data|analytics?|analyst|scientist|machine learning|\bml\b|\bbi\b|business intelligence|insight|statistic|quantitative|looker|dbt)\b/i;

// ----------------------------------------------------------------------------- pure helpers

/** Interim priority (until Companies House ranking is added): higher = check first. */
function priorityScore(name, town, county) {
  var n = ' ' + normaliseName(name) + ' ';
  var s = 0;
  var strong = /\b(data|analytics|software|technolog\w*|tech|digital|ai|cloud|cyber|fintech|bank|banking|capital|financial|finance|insurance|investment\w*|asset|payments?|consult\w*|advisory|health\w*|medical|pharma\w*|therapeutics|bio\w*|diagnostics|university|research|energy|telecom\w*|media|games?|labs?|platforms?|systems|solutions|analytics|intelligence|engineering|retail|commerce|logistics)\b/;
  var weak = /\b(care|homes?|nursing|residential|restaurant|takeaway|cafe|kebab|pizza|curry|grill|bakery|salon|barber|beauty|nails|construction|builders?|roofing|plumbing|cleaning|taxi|cars?|garage|motors|food|foods|catering|hotel|travel|church|mosque|temple|gurdwara|ministries|fellowship|farm|farms|stores?|supermarket|mini market|off licence|butchers?|newsagent|domiciliary|recruitment)\b/;
  if (strong.test(n)) s += 3;
  if (weak.test(n)) s -= 4;
  var t = (String(town) + ' ' + String(county)).toLowerCase();
  if (/glasgow|edinburgh/.test(t)) s += 3;
  else if (/scotland|aberdeen|dundee|stirling|livingston|paisley|lanarkshire|lothian|fife/.test(t)) s += 2;
  else if (/london/.test(t)) s += 1.5;
  else if (/manchester|leeds|bristol|cambridge|oxford|birmingham|reading|belfast|cardiff|newcastle/.test(t)) s += 1;
  return s;
}

/** Candidate board slugs from a sponsor name, e.g. "Monzo Bank Ltd" -> ["monzobank","monzo-bank","monzo"]. */
function slugCandidates(name) {
  var words = normaliseName(name).replace(/\band\b/g, ' ').split(' ').filter(Boolean);
  if (!words.length) return [];
  var out = [words.join(''), words.join('-')];
  var generic = /^(bank|technologies|technology|tech|software|services|solutions|systems|international|global|digital|labs|health|healthcare|consulting|partners|capital|financial|europe|holdings)$/;
  if (words.length > 1 && generic.test(words[words.length - 1])) {
    var core = words.slice(0, -1);
    out.push(core.join(''), core.join('-'));
  }
  var seen = {};
  return out.filter(function (s) { return s.length >= 3 && !seen[s] && (seen[s] = 1); }).slice(0, 3);
}

function tokenOverlap(a, b) {
  var A = normaliseName(a).split(' ').filter(Boolean), B = normaliseName(b).split(' ').filter(Boolean);
  if (!A.length || !B.length) return 0;
  var setB = new Set(B), hit = A.filter(function (w) { return setB.has(w); }).length;
  return hit / Math.min(A.length, B.length);
}

/** Interprets one probe response. Returns null (no board) or a result object. */
function interpretProbe(ats, slug, code, body, sponsorName) {
  if (code !== 200 || !body) return null;
  var data;
  try { data = JSON.parse(body); } catch (e) { return null; }
  var jobs = [], locs = [], titles = [], boardName = '';
  if (ats === 'greenhouse') {
    if (!data || data.status === 404) return null;
    boardName = data.name || '';
    return { ats: ats, slug: slug, boardName: boardName, needsJobs: true };
  }
  if (ats === 'greenhouse_jobs') {
    jobs = data.jobs || [];
    jobs.forEach(function (j) { locs.push((j.location && j.location.name) || ''); titles.push(j.title || ''); });
  } else if (ats === 'lever') {
    if (!Array.isArray(data)) return null;
    jobs = data;
    jobs.forEach(function (j) {
      var c = j.categories || {};
      locs.push([c.location, (c.allLocations || []).join(' '), j.country, j.workplaceType].join(' '));
      titles.push(j.text || '');
    });
  } else if (ats === 'ashby') {
    if (!data || !Array.isArray(data.jobs)) return null;
    jobs = data.jobs;
    jobs.forEach(function (j) {
      locs.push([j.location, (j.secondaryLocations || []).map(function (l) { return l.location; }).join(' '),
        j.address && j.address.postalAddress && j.address.postalAddress.addressCountry, j.isRemote ? 'remote' : ''].join(' '));
      titles.push(j.title || '');
    });
  }
  var uk = 0, dataJobs = 0;
  for (var i = 0; i < jobs.length; i++) {
    var isUk = UK_RE.test(locs[i] || '');
    if (isUk) uk++;
    if (isUk && DATA_RE.test(titles[i] || '')) dataJobs++;
  }
  return { ats: ats, slug: slug, open: jobs.length, uk: uk, dataJobs: dataJobs };
}

function probeUrls(ats, slug) {
  if (ats === 'greenhouse') return 'https://boards-api.greenhouse.io/v1/boards/' + slug;
  if (ats === 'greenhouse_jobs') return 'https://boards-api.greenhouse.io/v1/boards/' + slug + '/jobs';
  if (ats === 'lever') return 'https://api.lever.co/v0/postings/' + slug + '?mode=json';
  if (ats === 'ashby') return 'https://api.ashbyhq.com/posting-api/job-board/' + slug;
}

function careersUrl(ats, slug) {
  return { greenhouse: 'https://boards.greenhouse.io/' + slug, lever: 'https://jobs.lever.co/' + slug,
    ashby: 'https://jobs.ashbyhq.com/' + slug }[ats];
}

/**
 * Decide the best match for one sponsor from its probe results.
 * Confidence: high = Greenhouse board name matches the sponsor, or Lever/Ashby board on the full
 * name with UK jobs; medium = Lever/Ashby on a shortened name with UK jobs, or Greenhouse partial
 * name match; low = board exists but has no UK jobs to confirm it (kept for review, not used by
 * the job search until confirmed).
 */
function chooseMatch(sponsorName, results, fullSlug) {
  var best = null;
  results.forEach(function (r) {
    if (!r) return;
    var conf;
    if (r.ats === 'greenhouse') {
      var ov = tokenOverlap(sponsorName, r.boardName);
      if (ov >= 0.99) conf = 'high'; else if (ov >= 0.5) conf = 'medium'; else return;
      if (r.open != null && r.uk === 0 && r.open > 0) conf = conf === 'high' ? 'medium' : 'low';
    } else {
      if (r.uk > 0) conf = r.slug === fullSlug ? 'high' : 'medium';
      else conf = 'low';
    }
    // Short one-word names (e.g. "ALT", "Wise") collide with other companies' boards: never trust them fully.
    var shortName = normaliseName(sponsorName).replace(/ /g, '').length < 5;
    if (shortName) conf = (r.ats === 'greenhouse' && conf === 'high') ? 'medium' : 'low';
    var rank = { high: 3, medium: 2, low: 1 }[conf];
    if (!best || rank > best.rank || (rank === best.rank && (r.uk || 0) > (best.r.uk || 0))) best = { r: r, conf: conf, rank: rank };
  });
  return best;
}

// ----------------------------------------------------------------------------- Google side

function dirSheet_(ss) {
  var sh = ss.getSheetByName(CAREERS.DIR_TAB);
  if (!sh) {
    sh = ss.insertSheet(CAREERS.DIR_TAB);
    sh.getRange(1, 1, 1, CAREERS.DIR_HEADER.length).setValues([CAREERS.DIR_HEADER]).setFontWeight('bold');
    sh.setFrozenRows(1);
    if (sh.getMaxColumns() > CAREERS.DIR_HEADER.length) {
      sh.deleteColumns(CAREERS.DIR_HEADER.length + 1, sh.getMaxColumns() - CAREERS.DIR_HEADER.length);
    }
  }
  return sh;
}

/** Map normalised_name|town -> directory row (array). Used by SponsorRegister.gs too. */
function readDirectory_(ss) {
  var sh = ss.getSheetByName(CAREERS.DIR_TAB);
  var map = Object.create(null);
  if (!sh || sh.getLastRow() < 2) return map;
  sh.getRange(2, 1, sh.getLastRow() - 1, CAREERS.DIR_HEADER.length).getValues().forEach(function (r, i) {
    map[r[0] + '|' + String(r[2]).toLowerCase()] = { row: i + 2, values: r };
  });
  return map;
}

function fetchBudgetLeft_() {
  var props = PropertiesService.getScriptProperties();
  var today = today_();
  if (props.getProperty('CAREERS_DAY') !== today) {
    props.setProperties({ CAREERS_DAY: today, CAREERS_FETCHES: '0' });
  }
  return CAREERS.DAILY_FETCH_BUDGET - Number(props.getProperty('CAREERS_FETCHES') || 0);
}

function spendBudget_(n) {
  var props = PropertiesService.getScriptProperties();
  props.setProperty('CAREERS_FETCHES', String(Number(props.getProperty('CAREERS_FETCHES') || 0) + n));
}

function appendDir_(sh, rows) {
  var need = sh.getLastRow() + rows.length;
  if (sh.getMaxRows() < need) sh.insertRowsAfter(sh.getMaxRows(), need - sh.getMaxRows());
  sh.getRange(sh.getLastRow() + 1, 1, rows.length, CAREERS.DIR_HEADER.length).setValues(rows);
}

/** Scheduled every 15 minutes. */
function runCareersBatch() {
  // Stay out of the way of the daily register check (its trigger fires between 6 and 7am).
  var hm = Utilities.formatDate(new Date(), 'Europe/London', 'HHmm');
  if (hm >= '0550' && hm < '0710') return;
  if (fetchBudgetLeft_() < 200) return;          // cheap exit once today's budget is used
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  var started = Date.now();
  try {
    var ss = SpreadsheetApp.getActive();
    var aSheet = ss.getSheetByName(CONFIG.TABS.aRated);
    if (!aSheet || aSheet.getLastRow() < 2) return;
    var sh = dirSheet_(ss);
    var today = today_();

    // Directory state: key -> {row, ats, checked}; name -> resolved values (to reuse across towns).
    var known = Object.create(null), byName = Object.create(null);
    var nDir = sh.getLastRow() - 1;
    if (nDir > 0) {
      var vals = sh.getRange(2, 1, nDir, CAREERS.DIR_HEADER.length).getValues();
      vals.forEach(function (r, i) {
        known[r[0] + '|' + String(r[2]).toLowerCase()] = { row: i + 2, ats: r[5], checked: String(r[13]) };
        if (r[5] && r[5] !== 'retry' && !byName[r[0]]) byName[r[0]] = r;
      });
    }

    // Queue: unchecked sponsors, plus 'retry' rows not already retried today. Highest priority first.
    var rows = aSheet.getRange(2, 1, aSheet.getLastRow() - 1, 4).getValues(); // norm, org, town, county
    var queue = [];
    rows.forEach(function (r) {
      var k = r[0] + '|' + String(r[2]).toLowerCase();
      var d = known[k];
      if (d && !(d.ats === 'retry' && d.checked !== today)) return;
      queue.push({ key: k, norm: String(r[0]), org: r[1], town: r[2], county: r[3],
        score: priorityScore(r[1], r[2], r[3]), retryRow: d ? d.row : 0 });
    });
    if (!queue.length) return;
    queue.sort(function (a, b) { return b.score - a.score; });

    var batch = [], inBatch = Object.create(null);
    for (var q = 0; q < queue.length && batch.length < CAREERS.BATCH_COMPANIES; q++) {
      if (inBatch[queue[q].key]) continue;
      inBatch[queue[q].key] = 1;
      batch.push(queue[q]);
    }

    var cache = Object.create(null), seenOrg = Object.create(null);
    function rowFor(c, src, now) {
      if (byName[c.norm]) {                       // same company already resolved in another town
        var r = byName[c.norm].slice();
        r[1] = c.org; r[2] = c.town; r[3] = c.score; r[12] = 'auto-probe (same company)'; r[13] = now;
        return r;
      }
      if (src.transient) {
        return [c.norm, c.org, c.town, c.score, '', 'retry', '', '', '', '', '', '', 'auto-probe', now,
          'Temporary HTTP error or rate limit; will retry tomorrow'];
      }
      var results = [];
      (src.slugs || []).forEach(function (s) {
        ['greenhouse', 'lever', 'ashby'].forEach(function (ats) { results.push(cache[ats + ':' + s] || null); });
      });
      var m = chooseMatch(src.org, results, (src.slugs || [])[0]);
      if (m) {
        var x = m.r;
        return [c.norm, c.org, c.town, c.score, careersUrl(x.ats, x.slug), x.ats, x.slug, probeUrls(x.ats, x.slug),
          x.open || 0, x.uk || 0, x.dataJobs || 0, m.conf, 'auto-probe', now, ''];
      }
      return [c.norm, c.org, c.town, c.score, '', 'not detected', '', '', '', '', '', '', 'auto-probe', now,
        'No Greenhouse/Lever/Ashby board found; careers page to be found by search'];
    }

    for (var b = 0; b < batch.length; b += 10) {
      if (Date.now() - started > CAREERS.MAX_RUN_MS || fetchBudgetLeft_() < 100) break;
      var group = batch.slice(b, b + 10);
      var probes = [];
      group.forEach(function (c) {
        if (byName[c.norm]) return;
        if (seenOrg[c.norm]) { c.copyOf = seenOrg[c.norm]; return; }
        seenOrg[c.norm] = c;
        c.slugs = slugCandidates(c.org);
        c.slugs.forEach(function (sl) {
          ['greenhouse', 'lever', 'ashby'].forEach(function (ats) {
            if (cache[ats + ':' + sl] === undefined) probes.push({ c: c, ats: ats, slug: sl });
          });
        });
      });
      var resp;
      try { resp = fetchAllStrict_(probes.map(function (p) { return probeUrls(p.ats, p.slug); })); }
      catch (e) { console.log('fetchAll failed, stopping this run: ' + e); break; }
      var ghFollow = [];
      probes.forEach(function (p, i) {
        var code = resp[i].code;
        if (code !== 200 && code !== 404) { p.c.transient = true; return; }
        var r = interpretProbe(p.ats, p.slug, code, resp[i].body, p.c.org);
        cache[p.ats + ':' + p.slug] = r;
        if (r && r.needsJobs) ghFollow.push({ c: p.c, r: r });
      });
      if (ghFollow.length) {
        var jr;
        try { jr = fetchAllStrict_(ghFollow.map(function (g) { return probeUrls('greenhouse_jobs', g.r.slug); })); }
        catch (e) { console.log('fetchAll failed, stopping this run: ' + e); break; }
        ghFollow.forEach(function (g, i) {
          var j = interpretProbe('greenhouse_jobs', g.r.slug, jr[i].code, jr[i].body, g.c.org);
          if (j) { g.r.open = j.open; g.r.uk = j.uk; g.r.dataJobs = j.dataJobs; }
        });
      }
      var now = today_(), appendRows = [];
      group.forEach(function (c) {
        var row = rowFor(c, c.copyOf || c, now);
        if (row[5] && row[5] !== 'retry' && !byName[c.norm]) byName[c.norm] = row;
        if (c.retryRow) sh.getRange(c.retryRow, 1, 1, row.length).setValues([row]);
        else appendRows.push(row);
      });
      if (appendRows.length) appendDir_(sh, appendRows);   // save after every group of 10
    }
    refreshTodo_(ss, sh);
  } finally {
    lock.releaseLock();
  }
}

/**
 * "Careers to find": the highest-priority sponsors where no Greenhouse/Lever/Ashby board was found.
 * Claude's daily cloud task works through this list with web search and writes the careers URL
 * straight into the Employer directory row (source = "agent"), so it drops off this list.
 */
function refreshTodo_(ss, dirSh) {
  var n = dirSh.getLastRow() - 1;
  if (n < 1) return;
  var vals = dirSh.getRange(2, 1, n, CAREERS.DIR_HEADER.length).getValues();
  var todo = [];
  vals.forEach(function (r, i) {
    if (r[5] === 'not detected' && !r[4] && String(r[12]).indexOf('auto-probe') === 0 && Number(r[3]) > 0) {
      todo.push([i + 2, r[1], r[2], r[3]]);
    }
  });
  todo.sort(function (a, b) { return b[3] - a[3]; });
  todo = todo.slice(0, CAREERS.TODO_SIZE);
  var sh = ss.getSheetByName(CAREERS.TODO_TAB) || ss.insertSheet(CAREERS.TODO_TAB);
  sh.clearContents();
  var header = ['directory_row', 'organisation', 'town', 'priority'];
  sh.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight('bold');
  if (todo.length) sh.getRange(2, 1, todo.length, header.length).setValues(todo);
}

/** fetchAll in chunks; budget is counted before fetching; throws if Google refuses (e.g. quota). */
function fetchAllStrict_(urls) {
  var out = [];
  for (var i = 0; i < urls.length; i += CAREERS.PARALLEL) {
    var reqs = urls.slice(i, i + CAREERS.PARALLEL).map(function (u) {
      return { url: u, muteHttpExceptions: true, followRedirects: true };
    });
    spendBudget_(reqs.length);
    UrlFetchApp.fetchAll(reqs).forEach(function (r) {
      var code = r.getResponseCode();
      out.push({ code: code, body: code === 200 ? r.getContentText() : '' });
    });
  }
  return out;
}

/** Run once: creates the 10-minute trigger and runs the first batch. */
function setupCareers() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runCareersBatch') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('runCareersBatch').timeBased().everyMinutes(15).create();
  var sh = dirSheet_(SpreadsheetApp.getActive());
  sh.getRange('A:A').setNumberFormat('@'); sh.getRange('C:C').setNumberFormat('@');
  runCareersBatch();
}

if (typeof module !== 'undefined') {
  module.exports = { priorityScore: priorityScore, slugCandidates: slugCandidates, tokenOverlap: tokenOverlap,
    interpretProbe: interpretProbe, chooseMatch: chooseMatch, probeUrls: probeUrls, careersUrl: careersUrl };
}
