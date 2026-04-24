/*  ------------------------------------------------------------------
    Loads mapping.json, handles lookup, supports 1-to-many results.
    ------------------------------------------------------------------ */

let mapping = {};
let mappingKeys = [];
let mappingLoaded = false;
let loadFailed = false;

const MAX_SUGGESTIONS = 3;
const MAX_SUGGESTION_DISTANCE = 3;

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
  error.append('Mál nr. ');
  error.append(createElement('strong', '', key), ' fannst ekki.');

  if (!suggestions.length) {
    replaceResult(error);
    return;
  }

  const hint = createElement('span', 'suggestion-hint', 'Getur verið að þú hafir verið að leita að:');
  error.append(document.createElement('br'), hint);

  const list = document.createElement('ul');
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
  const firstAppealItem = rows.find(item => toText(item.appeals_case_link).trim() !== '');
  const firstAppealUrl = firstAppealItem ? getSafeHttpUrl(firstAppealItem.appeals_case_link) : '';

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

  const list = document.createElement('ul');
  rows.forEach(row => {
    list.append(createVerdictItem(row));
  });

  replaceResult(intro, list);
}

function createVerdictItem(row) {
  const item = document.createElement('li');
  const header = createElement('div', 'verdict-header');
  const sourceType = toText(row.source_type) || 'mál';
  const supremeCaseNumber = toText(row.supreme_case_number);
  const linkText = `Skoða ${sourceType} í máli nr. ${supremeCaseNumber}`;
  const supremeUrl = getSafeHttpUrl(row.supreme_case_link);

  if (supremeUrl) {
    const link = createElement('a', '', linkText);
    link.href = supremeUrl;
    link.target = '_blank';
    link.rel = 'noopener';
    header.append(link);
  } else {
    header.textContent = linkText;
  }

  const meta = createElement('div', 'verdict-meta');
  const verdictDate = toText(row.verdict_date).trim();
  const decisionStatus = toText(row.decision_status).trim();

  if (verdictDate) meta.append(verdictDate);

  if (sourceType.includes('ákvörðun') && decisionStatus) {
    if (verdictDate) meta.append(' - ');
    const statusClass = getDecisionStatusClass(decisionStatus);
    meta.append(createElement('span', statusClass, decisionStatus));
  }

  item.append(header, meta);
  return item;
}

function getDecisionStatusClass(status) {
  if (status.includes('Samþykkt')) return 'status-approved';
  if (status.includes('Hafnað')) return 'status-rejected';
  return 'status-muted';
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

function weightedDistance(inputCase, inputYear, candidate) {
  const [candCase = '', candYear = ''] = candidate.split('/');
  const caseDistance = levenshtein(inputCase, candCase);
  const yearDistance = levenshtein(inputYear, candYear);
  return caseDistance + yearDistance * 1.5;
}

function getSuggestions(term) {
  if (!term || !mappingKeys.length) return [];
  const [inputCase = '', inputYear = ''] = term.split('/');
  const sameCase = inputCase
    ? mappingKeys.filter(key => key.split('/')[0] === inputCase)
    : [];
  const sameYear = inputYear
    ? mappingKeys.filter(key => key.endsWith(`/${inputYear}`))
    : [];

  const candidateSet = new Set();
  sameCase.forEach(key => candidateSet.add(key));
  sameYear.forEach(key => candidateSet.add(key));

  if (!candidateSet.size) {
    mappingKeys.forEach(key => candidateSet.add(key));
  } else if (candidateSet.size < MAX_SUGGESTIONS) {
    mappingKeys.forEach(key => candidateSet.add(key));
  }

  const ranked = Array.from(candidateSet)
    .map(key => ({
      key,
      score: weightedDistance(inputCase, inputYear, key),
    }))
    .sort((a, b) => a.score - b.score);

  if (!ranked.length || ranked[0].score > MAX_SUGGESTION_DISTANCE) return [];

  return ranked
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
