/*  ----------------------------------------------------------------------
    Loads mapping.json, wires up the lookup form,
    and populates the <datalist> for autocomplete.
    ---------------------------------------------------------------------- */

let mapping = {};                   // { "266/2022": {appeal, supreme, url}, … }

const form   = document.getElementById('lookupForm');
const input  = document.getElementById('appealInput');
const result = document.getElementById('result');
const dlist  = document.getElementById('appealList');

// --- 1.  Fetch mapping.json once and set up the page --------------------
fetch('mapping.json')
  .then(r => r.json())
  .then(data => {
    mapping = data;

    // Populate datalist for autocomplete
    Object.keys(mapping)
      .sort((a, b) => a.localeCompare(b, 'is', { numeric: true }))
      .forEach(key => {
        const opt = document.createElement('option');
        opt.value = key;
        dlist.appendChild(opt);
      });
  })
  .catch(() => showError('Tókst ekki að hlaða gögnunum :('));

// --- 2.  Handle the form submit ----------------------------------------
form.addEventListener('submit', ev => {
  ev.preventDefault();                            // stay on the page

  const key = input.value.trim();
  const row = mapping[key];

  if (!row) {
    showError(`Enginn hæstaréttardómur fannst fyrir <b>${key}</b>.`);
    return;
  }

  // Success – show the result
  result.innerHTML = `
    <p><strong>${row.appeal}</strong> varð að
       máli <strong>${row.supreme}</strong> í Hæstarétti.</p>
    <p><a href="${row.url}" target="_blank" rel="noopener">
       Skoða dóm Hæstaréttar
    </a></p>`;
});

// --- 3.  Helper to show error messages ---------------------------------
function showError(msg) {
  result.innerHTML = `<p class="error">${msg}</p>`;
}
