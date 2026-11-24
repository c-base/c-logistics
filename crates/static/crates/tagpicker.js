// Tag-Auswahl: Aus einer Reihe von Haken (ein <div> je Tag) wird eine Auswahl, die nur
// die gewählten zeigt. Weitere kommen über ein Feld dazu, das die übrigen zum Anklicken
// aufklappt und beim Tippen eingrenzt. Ohne Skript stehen einfach alle als Haken da.
//
//   initTagPicker(element, { placeholder: '…', onChange: function () {} })
function initTagPicker(list, options) {
  if (!list || !list.children.length) return;
  options = options || {};
  var rows = Array.prototype.slice.call(list.children).map(function (row) {
    return { row: row, box: row.querySelector('input'), name: row.textContent.trim() };
  });
  var add = document.createElement('div'), input = document.createElement('input'), results = document.createElement('ul');
  add.className = 'member-add';
  input.type = 'search';
  input.className = 'form-control';
  input.placeholder = options.placeholder || 'Tag hinzufügen …';
  input.autocomplete = 'off';
  input.spellcheck = false;
  input.setAttribute('autocapitalize', 'none');
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-controls', list.id + '-results');
  input.setAttribute('aria-label', input.placeholder);
  results.className = 'member-results';
  results.id = list.id + '-results';
  results.setAttribute('role', 'listbox');
  add.appendChild(input);
  add.appendChild(results);
  list.parentNode.insertBefore(add, list.nextSibling);
  var found = [], active = -1;

  function sync() {
    rows.forEach(function (tag) { tag.row.hidden = !tag.box.checked; });
    list.hidden = !rows.some(function (tag) { return tag.box.checked; });
  }
  function mark() {
    Array.prototype.forEach.call(results.querySelectorAll('[role=option]'), function (item, index) {
      item.classList.toggle('active', index === active);
      item.setAttribute('aria-selected', index === active ? 'true' : 'false');
    });
  }
  function close() {
    found = [];
    active = -1;
    results.textContent = '';
    results.hidden = true;
    input.setAttribute('aria-expanded', 'false');
  }
  function open() {
    var query = input.value.trim().toLowerCase();
    found = rows.filter(function (tag) { return !tag.box.checked && tag.name.indexOf(query) !== -1; });
    active = found.length ? 0 : -1;
    results.textContent = '';
    found.forEach(function (tag) {
      var item = document.createElement('li');
      item.setAttribute('role', 'option');
      item.textContent = tag.name;
      item.addEventListener('click', function () { pick(tag); });
      results.appendChild(item);
    });
    if (!found.length) {
      var none = document.createElement('li');
      none.className = 'none';
      none.textContent = query ? 'Kein Tag gefunden.' : 'Alle Tags sind schon gewählt.';
      results.appendChild(none);
    }
    mark();
    results.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }
  function changed() {
    sync();
    if (options.onChange) options.onChange();
  }
  function pick(tag) {
    tag.box.checked = true;
    input.value = '';
    close();
    input.focus();
    changed();
  }
  // ein Haken, der herausgenommen wird, wandert zurück in die Auswahl
  list.addEventListener('change', changed);
  input.addEventListener('input', open);
  input.addEventListener('click', open);
  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      // Enter wählt das Tag und schickt nicht das ganze Formular ab
      event.preventDefault();
      if (found[active]) pick(found[active]);
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (results.hidden) return open();
      if (!found.length) return;
      active = (active + (event.key === 'ArrowDown' ? 1 : -1) + found.length) % found.length;
      mark();
    } else if (event.key === 'Escape') {
      close();
    }
  });
  document.addEventListener('click', function (event) { if (!add.contains(event.target)) close(); });
  close();
  sync();
}
