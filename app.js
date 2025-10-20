/*  ------------------------------------------------------------------
    Loads mapping.json, handles look-up, supports 1-to-many results.
    ------------------------------------------------------------------ */


let mapping = {};                           // filled on load
let mappingLoaded = false;                  // flipped once data arrives
let loadFailed = false;                     // prevents submitting on fatal error

const form   = document.getElementById('lookupForm');
const input  = document.getElementById('appealInput');
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
  result.innerHTML = `<p class="status">${msg}</p>`;
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

  if (!mappingLoaded) {
    if (loadFailed) {
      showError('Ekki er hægt að leita þar sem gögnin náðust ekki.');
    } else {
      showStatus('Bíð eftir að gögnin hlaðist…');
    }
    return;
  }

  const key = input.value.trim();
  const safeKey = escapeHtml(key);
  let rows  = mapping[key];

  if (!rows) {
    showError(`Ekkert mál hjá Hæstarétti fannst fyrir <b>${safeKey}</b>.`);
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
    <p>
      Landsréttarmál ${keyHtml} hefur verið til umfjöllunar í Hæstarétti:
    </p>
  `;

  // Compose the result HTML
  const listItems = rows.map(item => {
    const datePart = item.verdict_date ? `${item.verdict_date}` : '';
    const decisionPart =
      item.source_type.includes('ákvörðun') && item.decision_status
        ? ` &nbsp;–&nbsp; ${item.decision_status}`
        : '';
    return `
        <li>
          <strong>${datePart}</strong> í máli nr. <strong>${item.supreme_case_number}</strong> &nbsp;–&nbsp;
          <a href="${item.supreme_case_link}" target="_blank" rel="noopener">Skoða ${item.source_type}</a>${decisionPart}
        </li>`;
  }).join('');

  result.innerHTML = `
      ${firstAppealHtml}
      <ul>${listItems}</ul>`;
});

// ---------- 3. Helper ---------------------------------------------------
function showError(msg) {
  result.innerHTML = `<p class="error">${msg}</p>`;
}
