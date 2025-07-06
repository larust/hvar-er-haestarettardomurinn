/*  ------------------------------------------------------------------
    Loads mapping.json, handles look-up, supports 1-to-many results.
    mapping.json structure accepted:

      "37/2022": {appeal:"37/2022", supreme:"34/2023", url:"…"}
        – or –
      "37/2022": [
          {appeal:"37/2022", supreme:"34/2023", url:"…"},
          {appeal:"37/2022", supreme:"60/2023", url:"…"}
        ]
    ------------------------------------------------------------------ */

let mapping = {};                           // filled on load

const form   = document.getElementById('lookupForm');
const input  = document.getElementById('appealInput');
const result = document.getElementById('result');
const dlist  = document.getElementById('appealList');

// ---------- 1. Fetch mapping.json & build datalist --------------------
fetch('mapping_d_og_a.json')
  .then(r => r.json())
  .then(data => {
    mapping = data;

    Object.keys(mapping)
      .sort((a, b) => a.localeCompare(b, 'is', { numeric: true }))
      .forEach(key => {
        const opt = document.createElement('option');
        opt.value = key;
        dlist.appendChild(opt);
      });
  })
  .catch(() => showError('Tókst ekki að hlaða gögnunum :('));

// ---------- 2. Lookup on form submit ----------------------------------
form.addEventListener('submit', evt => {
  evt.preventDefault();

  const key = input.value.trim();
  let rows  = mapping[key];

  if (!rows) {
    showError(`Enginn hæstaréttardómur fannst fyrir <b>${key}</b>.`);
    return;
  }

  // Normalise: ensure rows is an array
  if (!Array.isArray(rows)) rows = [rows];

  // Compose the result HTML
  const listItems = rows.map(item => `
        <li>
          Mál <strong>${item.supreme}</strong> &nbsp;–&nbsp;
          <a href="${item.url}" target="_blank" rel="noopener">Skoða dóm</a>
        </li>`).join('');

  result.innerHTML = `
      <p>Landsréttarmál <strong>${key}</strong> er dómur Hæstaréttar:</p>
      <ul>${listItems}</ul>`;
});

// ---------- 3. Helper --------------------------------------------------
function showError(msg) {
  result.innerHTML = `<p class="error">${msg}</p>`;
}
