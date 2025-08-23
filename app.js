/*  ------------------------------------------------------------------
    Loads mapping.json, handles look-up, supports 1-to-many results.
    ------------------------------------------------------------------ */


let mapping = {};                           // filled on load

const form   = document.getElementById('lookupForm');
const input  = document.getElementById('appealInput');
const result = document.getElementById('result');
const updatedEl = document.getElementById('updated');

// ---------- 1. Fetch mapping.json --------------------------------------
fetch('mapping.json')
  .then(r => r.json())
  .then(data => { mapping = data; })
  .catch(() => showError('Tókst ekki að hlaða gögnunum :('));

// ---------- 1b. Fetch last-updated timestamp ---------------------------
fetch('last_updated.txt')
  .then(r => r.text())
  .then(text => { updatedEl.innerHTML = text; })
  .catch(() => { updatedEl.textContent = 'Síðast uppfært óþekkt.'; });

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

// ---------- 1. Fetch mapping.json --------------------------------------
fetch('mapping.json')
  .then(r => r.json())
  .then(data => { mapping = data; })
  .catch(() => showError('Tókst ekki að hlaða gögnunum :('));

// ---------- 2. Lookup on form submit -----------------------------------
form.addEventListener('submit', evt => {
  evt.preventDefault();

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
