// download mapping once, keep in memory
let mapping = {};
fetch('mapping.json')
  .then(r => r.json())
  .then(m => mapping = m)
  .catch(() => showError('Tókst ekki að hlaða gögnum :('));

const form   = document.getElementById('lookupForm');
const input  = document.getElementById('appealInput');
const result = document.getElementById('result');

form.addEventListener('submit', e => {
  e.preventDefault();
  const key = input.value.trim();
  const row = mapping[key];
  if (!row) { showError(`Enginn hæstaréttardómur fannst fyrir ${key}`); return; }

  result.innerHTML = `
    <p><strong>${key}</strong> varð að mál <strong>${row.supreme}</strong> í Hæstarétti.</p>
    <p><a href="${row.url}" target="_blank" rel="noopener">Skoða dóm Hæstaréttar</a></p>`;
});

function showError(msg){
  result.innerHTML = `<p class="error">${msg}</p>`;
}
