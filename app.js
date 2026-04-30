/*  ------------------------------------------------------------------
    Loads mapping.json, handles lookup, supports 1-to-many results.
    ------------------------------------------------------------------ */

let mapping = {};
let mappingKeys = [];
let mappingLoaded = false;
let loadFailed = false;

const MAX_SUGGESTIONS = 3;
const MAX_SUGGESTION_DISTANCE = 3;
const ICELANDIC_MONTHS = {
  janúar: 0,
  febrúar: 1,
  mars: 2,
  apríl: 3,
  maí: 4,
  júní: 5,
  júlí: 6,
  ágúst: 7,
  september: 8,
  október: 9,
  nóvember: 10,
  desember: 11,
};

const form = document.getElementById('lookupForm');
const input = document.getElementById('appealInput');
const result = document.getElementById('result');
const updatedEl = document.getElementById('updated');
const submitBtn = form.querySelector('button[type="submit"]') || form.querySelector('button');
const defaultBtnLabel = submitBtn ? submitBtn.textContent : '';

function setLoading(isLoading) {
  if (!submitBtn) return;
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? 'Hleður...' : defaultBtnLabel;
}

function setInputEnabled(enabled) {
  input.disabled = !enabled;
}

function createElement(tagName, className = '', text = '') {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function replaceResult(...nodes) {
  result.replaceChildren(...nodes);
}

function showStatus(message) {
  replaceResult(createElement('div', 'status', message));
}

function showError(message) {
  replaceResult(createElement('div', 'error', message));
}

function toText(value) {
  return value == null ? '' : String(value);
}

function getSafeHttpUrl(value) {
  const raw = toText(value).trim();
  if (!raw) return '';

  try {
    const url = new URL(raw, window.location.href);
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      return url.href;
    }
  } catch (err) {
    return '';
  }

  return '';
}

function normalizeCaseInput(value) {
  const raw = toText(value).trim();
  if (!raw) return '';

  const compact = raw
    .replace(/^(?:landsréttarmál(?:ið)?|m[áa]l)\s*nr\.?\s*/i, '')
    .replace(/\s+/g, '')
    .replace(/[–—]/g, '-');

  const slashMatch = compact.match(/^(\d{1,4})\/(\d{4})$/);
  if (slashMatch) return `${slashMatch[1]}/${slashMatch[2]}`;

  const hyphenMatch = compact.match(/^(\d{1,4})-(\d{4})$/);
  if (hyphenMatch) return `${hyphenMatch[1]}/${hyphenMatch[2]}`;

  return '';
}

setLoading(true);
setInputEnabled(false);
showStatus('Sæki gögn...');

// ---------- 1. Fetch mapping.json --------------------------------------
fetch('mapping.json')
  .then(response => response.json())
  .then(data => {
    mapping = data || {};
    mappingKeys = Object.keys(mapping);
    mappingLoaded = true;
    setLoading(false);
    setInputEnabled(true);

    if (mappingKeys.length > 0) {
      const randomKey = mappingKeys[Math.floor(Math.random() * mappingKeys.length)];
      input.placeholder = `t.d. ${randomKey}`;
    }

    if (mappingKeys.length === 0) {
      showStatus('Engin gögn fundust.');
      return;
    }

    replaceResult();

    const params = new URLSearchParams(window.location.search);
    const caseParam = params.get('case');
    if (caseParam) {
      performLookup(caseParam);
    }
  })
  .catch(() => {
    loadFailed = true;
    setLoading(false);
    setInputEnabled(false);
    if (submitBtn) submitBtn.disabled = true;
    showError('Tókst ekki að hlaða gögnunum.');
  });

// ---------- 1b. Fetch last-updated timestamp ---------------------------
fetch('last_updated.txt')
  .then(response => response.text())
  .then(text => { updatedEl.textContent = text; })
  .catch(() => { updatedEl.textContent = 'Ekki vitað hvenær dómasafnið var síðast uppfært.'; });

// ---------- 2. Lookup on form submit -----------------------------------
form.addEventListener('submit', event => {
  event.preventDefault();
  performLookup(input.value);
});

result.addEventListener('click', event => {
  const target = event.target instanceof Element ? event.target : event.target.parentElement;
  const button = target ? target.closest('.suggestion-button') : null;
  if (!button) return;
  const suggestedKey = button.dataset.case;
  if (!suggestedKey) return;
  performLookup(suggestedKey);
});

function performLookup(rawKey) {
  if (!mappingLoaded) {
    if (loadFailed) {
      showError('Ekki er hægt að leita þar sem gögnin náðust ekki.');
    } else {
      showStatus('Bíð eftir að gögnin hlaðist...');
    }
    return;
  }

  const key = normalizeCaseInput(rawKey);
  if (!key) {
    showError('Sláðu inn málsnúmer Landsréttar á forminu 123/2024.');
    trackSearch(toText(rawKey), false, 0);
    return;
  }

  input.value = key;

  const newUrl = `${window.location.pathname}?case=${encodeURIComponent(key)}`;
  window.history.pushState({ path: newUrl }, '', newUrl);

  let rows = mapping[key];

  if (!rows) {
    const suggestions = getSuggestions(key);
    renderNoMatch(key, suggestions);
    trackSearch(key, false, 0);
    return;
  }

  if (!Array.isArray(rows)) rows = [rows];

  renderMatches(key, rows);
  trackSearch(key, true, rows.length);
}

function renderNoMatch(key, suggestions) {
  const error = createElement('div', 'error');
  error.append('Ekkert mál hjá Hæstarétti fannst fyrir ');
  error.append(createElement('strong', '', key), '.');

  if (!suggestions.length) {
    replaceResult(error);
    return;
  }

  const hint = createElement('span', 'suggestion-hint', 'Svipuð Landsréttarmál:');
  error.append(document.createElement('br'), hint);

  const list = createElement('ul', 'suggestion-list');
  suggestions.forEach(suggestion => {
    const item = document.createElement('li');
    const button = createElement('button', 'suggestion-button', suggestion);
    button.type = 'button';
    button.dataset.case = suggestion;
    item.append(button);
    list.append(item);
  });

  replaceResult(error, list);
}

function renderMatches(key, rows) {
  const sortedRows = sortResultRows(rows);
  const firstAppealItem = rows.find(item => toText(item.appeals_case_link).trim() !== '');
  const firstAppealUrl = firstAppealItem ? getSafeHttpUrl(firstAppealItem.appeals_case_link) : '';

  const summary = createElement('div', 'result-summary');
  const summaryText = createElement('div', 'result-summary-text');
  const intro = createElement('div', 'intro-text');
  intro.append('Landsréttarmál nr. ');

  const strong = createElement('strong', '', key);
  if (firstAppealUrl) {
    const appealLink = document.createElement('a');
    appealLink.href = firstAppealUrl;
    appealLink.target = '_blank';
    appealLink.rel = 'noopener';
    appealLink.append(strong);
    intro.append(appealLink);
  } else {
    intro.append(strong);
  }

  intro.append(' hefur verið til umfjöllunar í Hæstarétti:');
  summaryText.append(intro);
  summary.append(summaryText);

  const list = createElement('ul', 'result-list');
  sortedRows.forEach(row => {
    list.append(createVerdictItem(row));
  });

  replaceResult(summary, list);
  input.focus();
}

function createVerdictItem(row) {
  const item = createElement('li', 'result-item');
  const header = createElement('div', 'result-main');
  const typeChip = createElement('span', 'case-chip', getSourceTypeLabel(row.source_type));
  const sourceType = toText(row.source_type) || 'mál';
  const supremeCaseNumber = toText(row.supreme_case_number);
  const linkText = `Mál nr. ${supremeCaseNumber}`;
  const supremeUrl = getSafeHttpUrl(row.supreme_case_link);

  header.append(typeChip);

  if (supremeUrl) {
    const link = createElement('a', '', linkText);
    link.href = supremeUrl;
    link.target = '_blank';
    link.rel = 'noopener';
    header.append(link);
  } else {
    header.append(createElement('span', 'result-link-fallback', linkText));
  }

  const meta = createElement('div', 'verdict-meta');
  const verdictDate = toText(row.verdict_date).trim();
  const decisionStatus = toText(row.decision_status).trim();

  if (verdictDate) meta.append(verdictDate);

  if (sourceType.includes('ákvörðun') && decisionStatus) {
    const statusClass = getDecisionStatusClass(decisionStatus);
    meta.append(createElement('span', statusClass, decisionStatus));
  }

  item.append(header, meta);
  return item;
}

function getDecisionStatusClass(status) {
  if (status.includes('Samþykkt')) return 'status-chip status-chip-approved';
  if (status.includes('Hafnað')) return 'status-chip status-chip-rejected';
  return 'status-chip status-muted';
}

function getSourceTypeLabel(sourceType) {
  return toText(sourceType).includes('ákvörðun') ? 'Ákvörðun' : 'Dómur';
}

function parseIcelandicDate(value) {
  const match = toText(value).trim().match(/^(\d{1,2})\.\s+([a-záðéíóúýþæö]+)\s+(\d{4})$/i);
  if (!match) return null;

  const day = Number(match[1]);
  const month = ICELANDIC_MONTHS[match[2].toLocaleLowerCase('is-IS')];
  const year = Number(match[3]);
  if (!Number.isInteger(day) || month == null || !Number.isInteger(year)) return null;

  return new Date(year, month, day).getTime();
}

function sortResultRows(rows) {
  return rows
    .map((row, index) => ({
      row,
      index,
      parsedDate: parseIcelandicDate(row.verdict_date),
    }))
    .sort((a, b) => {
      if (a.parsedDate != null && b.parsedDate != null) return a.parsedDate - b.parsedDate;
      if (a.parsedDate != null) return -1;
      if (b.parsedDate != null) return 1;
      return a.index - b.index;
    })
    .map(item => item.row);
}

// ---------- 3. Helper ---------------------------------------------------
function levenshtein(a, b) {
  if (a === b) return 0;
  const lenA = a.length;
  const lenB = b.length;
  if (lenA === 0) return lenB;
  if (lenB === 0) return lenA;

  const prev = new Array(lenB + 1);
  const curr = new Array(lenB + 1);

  for (let j = 0; j <= lenB; j += 1) prev[j] = j;

  for (let i = 1; i <= lenA; i += 1) {
    curr[0] = i;
    const charA = a.charAt(i - 1);

    for (let j = 1; j <= lenB; j += 1) {
      const charB = b.charAt(j - 1);
      const cost = charA === charB ? 0 : 1;
      curr[j] = Math.min(
        curr[j - 1] + 1,
        prev[j] + 1,
        prev[j - 1] + cost,
      );
    }

    for (let j = 0; j <= lenB; j += 1) {
      prev[j] = curr[j];
    }
  }

  return prev[lenB];
}

function parseCaseNumberParts(value) {
  const [sequenceText = '', yearText = ''] = toText(value).split('/');
  const sequence = Number(sequenceText);
  const year = Number(yearText);

  return {
    sequenceText,
    yearText,
    sequence: Number.isInteger(sequence) ? sequence : null,
    year: Number.isInteger(year) ? year : null,
  };
}

function getNumericGap(first, second) {
  if (first == null || second == null) return Number.POSITIVE_INFINITY;
  return Math.abs(first - second);
}

function getSequencePenalty(inputParts, candidateParts, sequenceDistance) {
  const gap = getNumericGap(inputParts.sequence, candidateParts.sequence);
  if (!Number.isFinite(gap) || gap === 0) return 0;
  if (gap <= 100) return gap / 100;
  if (sequenceDistance <= 1 && inputParts.sequenceText.length !== candidateParts.sequenceText.length) return 1;
  return 2.5;
}

function getYearPenalty(inputParts, candidateParts, sequenceDistance) {
  const gap = getNumericGap(inputParts.year, candidateParts.year);
  if (!Number.isFinite(gap) || gap <= 1) return 0;
  if (sequenceDistance === 0) return Math.min(gap / 10, 1);
  return Math.min((gap - 1) * 0.5, 2);
}

function rankSuggestion(inputParts, key) {
  const candidateParts = parseCaseNumberParts(key);
  const sequenceDistance = levenshtein(inputParts.sequenceText, candidateParts.sequenceText);
  const yearDistance = levenshtein(inputParts.yearText, candidateParts.yearText);
  const sequenceGap = getNumericGap(inputParts.sequence, candidateParts.sequence);
  const yearGap = getNumericGap(inputParts.year, candidateParts.year);
  const score = sequenceDistance
    + yearDistance * 1.5
    + getSequencePenalty(inputParts, candidateParts, sequenceDistance)
    + getYearPenalty(inputParts, candidateParts, sequenceDistance);

  return {
    key,
    score,
    sequenceDistance,
    yearDistance,
    sequenceGap,
    yearGap,
  };
}

function compareSuggestionRanks(a, b) {
  if (a.score !== b.score) return a.score - b.score;
  if (a.yearGap !== b.yearGap) return a.yearGap - b.yearGap;
  if (a.sequenceGap !== b.sequenceGap) return a.sequenceGap - b.sequenceGap;
  if (a.sequenceDistance !== b.sequenceDistance) return a.sequenceDistance - b.sequenceDistance;
  if (a.yearDistance !== b.yearDistance) return a.yearDistance - b.yearDistance;
  return a.key.localeCompare(b.key, 'is', { numeric: true });
}

function getSuggestions(term) {
  if (!term || !mappingKeys.length) return [];

  const inputParts = parseCaseNumberParts(term);
  return mappingKeys
    .map(key => rankSuggestion(inputParts, key))
    .filter(item => item.score <= MAX_SUGGESTION_DISTANCE)
    .sort(compareSuggestionRanks)
    .slice(0, MAX_SUGGESTIONS)
    .map(item => item.key);
}

function trackSearch(term, hasMatch, matchesCount) {
  if (typeof window.gtag !== 'function') return;
  try {
    window.gtag('event', 'appeal_search', {
      search_term: term,
      has_match: hasMatch,
      matches_count: matchesCount,
    });
  } catch (err) {
    console.warn('gtag tracking failed', err);
  }
}
