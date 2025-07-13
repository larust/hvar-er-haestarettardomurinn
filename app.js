/*  ------------------------------------------------------------------
    Loads mapping.json, handles look-up, supports 1-to-many results.
    ------------------------------------------------------------------ */

let mapping = {};                           // filled on load

const form   = document.getElementById('lookupForm');
const input  = document.getElementById('appealInput');
const result = document.getElementById('result');

// ---------- 1. Fetch mapping.json --------------------------------------
fetch('mapping.json')
  .then(r => r.json())
  .then(data => { mapping = data; })
  .catch(() => showError('Tókst ekki að hlaða gögnunum :('));

// ---------- 2. Lookup on form submit -----------------------------------
form.addEventListener('submit', evt => {
  evt.preventDefault();

  const key = input.value.trim();
  let rows  = mapping[key];

  if (!rows) {
    showError(`Ekkert mál hjá Hæstarétti fannst fyrir <b>${key}</b>.`);
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
    ? `<a href="${firstAppealUrl}" target="_blank" rel="noopener"><strong>${key}</strong></a>`
    : `<strong>${key}</strong>`;

  // Always include this paragraph
  const firstAppealHtml = `
    <p>
      Landsréttarmál ${keyHtml} hefur verið til umfjöllunar í Hæstarétti:
    </p>
  `;

  // Compose the result HTML
  const listItems = rows.map(item => `
        <li>
          Í máli <strong>${item.supreme_case_number}</strong> &nbsp;–&nbsp;
          <a href="${item.supreme_case_link}" target="_blank" rel="noopener">Skoða ${item.source_type}</a>
        </li>`).join('');

  result.innerHTML = `
      ${firstAppealHtml}
      <ul>${listItems}</ul>`;
});

// ---------- 3. Helper ---------------------------------------------------
function showError(msg) {
  result.innerHTML = `<p class="error">${msg}</p>`;
}
