/*  ------------------------------------------------------------------
    Loads mapping.json, handles look-up, supports 1-to-many results.
    ------------------------------------------------------------------ */


let mapping = {};                           // filled on load
let mappingLoaded = false;                  // flipped once data arrives
let loadFailed = false;                     // prevents submitting on fatal error
const MAX_SUGGESTIONS = 3;                  // how many near matches to show
const MAX_SUGGESTION_DISTANCE = 3;          // skip if best match is farther away

const form = document.getElementById('lookupForm');
const input = document.getElementById('appealInput');
const result = document.getElementById('result');
const updatedEl = document.getElementById('updated');
const submitBtn = form.querySelector('button[type="submit"]') || form.querySelector('button');
const defaultBtnLabel = submitBtn ? submitBtn.textContent : '';

function setLoading(isLoading) {
  if (!submitBtn) return;
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? 'Hleður…' : defaultBtnLabel;
}

function setInputEnabled(enabled) {
  input.disabled = !enabled;
}

function showStatus(msg) {
  result.innerHTML = `<div class="status">${msg}</div>`;
}

setLoading(true);
setInputEnabled(false);
showStatus('Sæki gögn...');

// ---------- 1. Fetch mapping.json --------------------------------------
fetch('mapping.json')
  .then(r => r.json())
  .then(data => {
    mapping = data || {};
    mappingLoaded = true;
    setLoading(false);
    setInputEnabled(true);
    if (Object.keys(mapping).length === 0) {
      showStatus('Engin gögn fundust.');
    } else {
      result.innerHTML = '';
    }
  })
  .catch(() => {
    loadFailed = true;
    setLoading(false);
    setInputEnabled(false);
    if (submitBtn) submitBtn.disabled = true;
    showError('Tókst ekki að hlaða gögnunum :(');
  });

// ---------- 1b. Fetch last-updated timestamp ---------------------------
fetch('last_updated.txt')
  .then(r => r.text())
  .then(text => { updatedEl.innerHTML = text; })
  .catch(() => { updatedEl.textContent = 'Ekki vitað hvenær dómasafnið var síðast uppfært.'; });

// Escape basic HTML entities to avoid injection when inserting user data
function escapeHtml(str) {
  return str.replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

// ---------- 2. Lookup on form submit -----------------------------------
form.addEventListener('submit', evt => {
  evt.preventDefault();
  const key = input.value.trim();
  performLookup(key);
});

result.addEventListener('click', evt => {
  const button = evt.target.closest('.suggestion-button');
  if (!button) return;
  const suggestedKey = button.dataset.case;
  if (!suggestedKey) return;
  input.value = suggestedKey;
  performLookup(suggestedKey);
});

function performLookup(key) {
  if (!mappingLoaded) {
    if (loadFailed) {
      showError('Ekki er hægt að leita þar sem gögnin náðust ekki.');
    } else {
      showStatus('Bíð eftir að gögnin hlaðist…');
    }
    return;
  }

  const safeKey = escapeHtml(key);
  let rows = mapping[key];

  if (!rows) {
    const suggestions = getSuggestions(key);
    if (suggestions.length) {
      const suggestionList = suggestions
        .map(item => `
          <li>
            <button type="button" class="suggestion-button" data-case="${item}">
              ${escapeHtml(item)}
            </button>
          </li>`)
        .join('');
      result.innerHTML = `
        <div class="error">
          Mál nr. <b>${safeKey}</b> fannst ekki.<br>
          <span style="font-size: 0.9em; margin-top:0.5em; display:block;">Getur verið að þú hafir verið að leita að:</span>
        </div>
        <ul>${suggestionList}</ul>
      `;
    } else {
      showError(`Ekkert mál hjá Hæstarétti fannst fyrir <b>${safeKey}</b>.`);
    }
    trackSearch(key, false, 0);
    return;
  }

  // Normalise: ensure rows is an array
  if (!Array.isArray(rows)) rows = [rows];

  // Find the first non-empty appeals link
  const firstAppealItem = rows.find(item =>
    item.appeals_case_link &&
    item.appeals_case_link.trim() !== ''
  );
  const firstAppealUrl = firstAppealItem
    ? firstAppealItem.appeals_case_link
    : '';

  // Build the in-block label: link if we have one, else just bold text
  const keyHtml = firstAppealUrl
    ? `<a href="${firstAppealUrl}" target="_blank" rel="noopener"><strong>${safeKey}</strong></a>`
    : `<strong>${safeKey}</strong>`;

  // Always include this paragraph
  const firstAppealHtml = `
    <div class="intro-text">
       Landsréttarmál ${keyHtml} hefur verið til umfjöllunar í Hæstarétti:
    </div>
  `;

  // Compose the result HTML
  const listItems = rows.map(item => {
    const datePart = item.verdict_date ? `${item.verdict_date}` : '';
    const decisionPart =
      item.source_type.includes('ákvörðun') && item.decision_status
        ? `<span style="opacity:0.8"> – ${item.decision_status}</span>`
        : '';

    return `
        <li>
          <div class="verdict-header">
             <a href="${item.supreme_case_link}" target="_blank" rel="noopener">
               Skoða ${item.source_type} (Mál nr. ${item.supreme_case_number})
             </a>
          </div>
          <div class="verdict-meta">
            ${datePart}${decisionPart}
          </div>
        </li>`;
  }).join('');

  result.innerHTML = `
      ${firstAppealHtml}
      <ul>${listItems}</ul>`;

  trackSearch(key, true, rows.length);
}

// ---------- 3. Helper ---------------------------------------------------
function showError(msg) {
  result.innerHTML = `<div class="error">${msg}</div>`;
}

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
        curr[j - 1] + 1,        // insertion
        prev[j] + 1,            // deletion
        prev[j - 1] + cost,     // substitution
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
  if (!term || !mapping || !Object.keys(mapping).length) return [];
  const [inputCase = '', inputYear = ''] = term.split('/');
  const keys = Object.keys(mapping);
  const sameCase = inputCase
    ? keys.filter(key => key.split('/')[0] === inputCase)
    : [];
  const sameYear = inputYear
    ? keys.filter(key => key.endsWith(`/${inputYear}`))
    : [];

  const candidateSet = new Set();
  sameCase.forEach(key => candidateSet.add(key));
  sameYear.forEach(key => candidateSet.add(key));

  if (!candidateSet.size) {
    keys.forEach(key => candidateSet.add(key));
  } else if (candidateSet.size < MAX_SUGGESTIONS) {
    keys.forEach(key => candidateSet.add(key));
  }

  const candidates = Array.from(candidateSet);

  const ranked = candidates
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
