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

  // Compose the result HTML
  const listItems = rows.map(item => `
        <li>
          Í máli <strong>${item.supreme}</strong> &nbsp;–&nbsp;
          <a href="${item.url}" target="_blank" rel="noopener">Skoða ${item.type}</a>
        </li>`).join('');

  result.innerHTML = `
      <p>Landsréttarmál <strong>${key}</strong> hefur verið til umfjöllunar í Hæstarétti:</p>
      <ul>${listItems}</ul>`;
});

// ---------- 3. Helper ---------------------------------------------------
function showError(msg) {
  result.innerHTML = `<p class="error">${msg}</p>`;
}
