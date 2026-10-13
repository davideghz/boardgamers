/* User picker: drives the .js-user-picker blocks rendered by forms.UserPickerWidget.
   One search modal is shared by every picker on the page; texts and the search URL
   come from the data-* attributes of the picker that opened it. */
(function () {
  if (window.UserPicker) return;  // the script can be included once per form
  window.UserPicker = true;

  var SPINNER = '<svg class="animate-spin w-7 h-7 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">'
    + '<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>'
    + '<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg>';

  var modal, input, title, hint, body;
  var picker = null;       // picker currently being filled
  var results = [];        // last results, indexed by the rendered rows
  var debounceTimer = null;
  var searchToken = 0;     // discards stale responses

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function buildModal() {
    modal = document.createElement('div');
    modal.className = 'fixed inset-0 z-50 items-center justify-center p-4';
    modal.style.display = 'none';
    modal.innerHTML =
      '<div class="absolute inset-0 bg-black/60" data-close></div>'
      + '<div class="relative bg-surface rounded-2xl w-full max-w-lg mx-auto shadow-2xl flex flex-col" style="max-height:88vh">'
      + '  <div class="px-6 pt-6 pb-5 flex items-start justify-between gap-4">'
      + '    <h2 data-title class="text-xl font-extrabold text-content leading-tight"></h2>'
      + '    <button type="button" data-close class="flex-shrink-0 text-content-muted hover:text-content transition-colors bg-transparent border-0 p-0 cursor-pointer mt-0.5">'
      + '      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" /></svg>'
      + '    </button>'
      + '  </div>'
      + '  <div class="border-t border-divider"></div>'
      + '  <div class="px-4 py-4">'
      + '    <div class="relative">'
      + '      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-content-muted pointer-events-none"><path stroke-linecap="round" stroke-linejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" /></svg>'
      + '      <input data-input type="text" autocomplete="off" class="w-full pl-10 pr-4 py-3 rounded-2xl border border-divider bg-surface text-sm text-content placeholder:text-content-muted focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-colors">'
      + '    </div>'
      + '    <p data-hint class="mt-2 px-1 text-xs text-content-muted"></p>'
      + '  </div>'
      + '  <div class="border-t border-divider"></div>'
      + '  <div data-body class="flex-1 overflow-y-auto px-4 py-4 min-h-[200px]"></div>'
      + '</div>';
    document.body.appendChild(modal);

    input = modal.querySelector('[data-input]');
    title = modal.querySelector('[data-title]');
    hint = modal.querySelector('[data-hint]');
    body = modal.querySelector('[data-body]');

    modal.addEventListener('click', function (e) {
      if (e.target.closest('[data-close]')) { close(); return; }
      var row = e.target.closest('button[data-index]');
      if (row) select(results[+row.dataset.index]);
    });
    input.addEventListener('input', search);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();  // never submit the page form from here
        if (results.length) select(results[0]);
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal.style.display !== 'none') close();
    });
  }

  function message(text) {
    body.innerHTML = '<div class="flex flex-col items-center justify-center py-12 gap-3 text-center">'
      + '<p class="text-sm text-content-muted">' + esc(text) + '</p></div>';
  }

  function open(target) {
    if (!modal) buildModal();
    picker = target;
    title.textContent = picker.dataset.title;
    input.placeholder = picker.dataset.placeholder;
    hint.textContent = picker.dataset.hint;
    input.value = '';
    results = [];
    message(picker.dataset.minLengthText);
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    setTimeout(function () { input.focus(); }, 50);
  }

  function close() {
    modal.style.display = 'none';
    document.body.style.overflow = '';
    clearTimeout(debounceTimer);
    searchToken++;
    picker = null;
  }

  function render(data) {
    results = data;
    if (!data.length) { message(picker.dataset.noResultsText); return; }
    body.innerHTML = '<div class="space-y-2">' + data.map(function (u, i) {
      return '<button type="button" data-index="' + i + '" class="w-full flex items-center gap-3 p-2.5 rounded-xl border border-divider bg-surface hover:bg-surface-alt text-left transition-colors cursor-pointer">'
        + '<img src="' + esc(u.avatar_url) + '" alt="" class="w-10 h-10 rounded-full object-cover flex-shrink-0">'
        + '<div class="min-w-0 flex-1"><p class="text-sm font-semibold text-content truncate">' + esc(u.nickname) + '</p>'
        + (u.full_name ? '<p class="text-xs text-content-muted truncate">' + esc(u.full_name) + '</p>' : '')
        + '</div>'
        + (u.email_match ? '<span class="flex-shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">' + esc(picker.dataset.emailMatchText) + '</span>' : '')
        + '</button>';
    }).join('') + '</div>';
  }

  function search() {
    clearTimeout(debounceTimer);
    var q = input.value.trim();
    if (q.length < +picker.dataset.minLength) {
      searchToken++;
      results = [];
      message(picker.dataset.minLengthText);
      return;
    }
    body.innerHTML = '<div class="flex flex-col items-center justify-center py-12 gap-3">' + SPINNER
      + '<p class="text-sm text-content-muted">' + esc(picker.dataset.searchingText) + '</p></div>';
    debounceTimer = setTimeout(function () {
      var token = ++searchToken;
      fetch(picker.dataset.searchUrl + '?q=' + encodeURIComponent(q), {credentials: 'same-origin'})
        .then(function (r) { return r.json(); })
        .then(function (data) { if (token === searchToken) render(data.results); })
        .catch(function () { if (token === searchToken) message(picker.dataset.noResultsText); });
    }, 300);
  }

  function setValue(target, user) {
    target.querySelector('input[type=hidden]').value = user ? user.id : '';
    target.querySelector('[data-picker-selected]').style.display = user ? '' : 'none';
    target.querySelector('[data-picker-open]').style.display = user ? 'none' : '';
    if (!user) return;
    target.querySelector('[data-picker-avatar]').src = user.avatar_url;
    target.querySelector('[data-picker-nickname]').textContent = user.nickname;
    var fullName = target.querySelector('[data-picker-fullname]');
    fullName.textContent = user.full_name;
    fullName.style.display = user.full_name ? '' : 'none';
  }

  function select(user) {
    if (!user || !picker) return;
    setValue(picker, user);
    close();
  }

  document.addEventListener('click', function (e) {
    var target = e.target.closest('.js-user-picker');
    if (!target) return;
    if (e.target.closest('[data-picker-open]')) open(target);
    else if (e.target.closest('[data-picker-clear]')) setValue(target, null);
  });

  // A hidden input is skipped by browser validation: open the search instead of
  // submitting a required picker left empty.
  document.addEventListener('submit', function (e) {
    var pickers = e.target.querySelectorAll('.js-user-picker[data-required="1"]');
    for (var i = 0; i < pickers.length; i++) {
      if (!pickers[i].querySelector('input[type=hidden]').value) {
        e.preventDefault();
        open(pickers[i]);
        return;
      }
    }
  }, true);
})();
