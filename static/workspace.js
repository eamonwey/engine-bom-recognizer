/* Presentation enhancements; recognition and review APIs remain in app.js. */
"use strict";
(() => {
  const nav = document.querySelector('#nav');
  function syncNavigation() {
    nav.querySelectorAll('[data-view]').forEach(link => {
      if (link.classList.contains('active')) {
        link.setAttribute('aria-current', 'page');
        document.querySelector('#page-location').textContent = link.textContent.trim();
      } else link.removeAttribute('aria-current');
    });
  }
  function route() {
    const view = location.hash.slice(1);
    const link = [...nav.querySelectorAll('[data-view]')].find(a => a.dataset.view === view);
    if (link && !link.classList.contains('active')) link.click();
  }
  nav.addEventListener('click', e => {
    if (!e.target.closest('[data-view]')) return;
    syncNavigation();
  });
  window.addEventListener('hashchange', route);
  document.addEventListener('click', e => {
    const button = e.target.closest('[data-go]');
    if (button) nav.querySelector('[data-view="' + button.dataset.go + '"]').click();
  });
  route();
  syncNavigation();

  const help = document.querySelector('#help-dialog');
  document.querySelector('#help-open').addEventListener('click', () => help.showModal());
  document.querySelector('#help-close').addEventListener('click', () => help.close());
  const settings = document.querySelector('#view-settings');
  settings.insertBefore(document.querySelector('#cfg-provider').closest('.card'), document.querySelector('#enterprise-panel'));

  function filterRows() {
    const query = document.querySelector('#bom-search').value.trim().toLowerCase();
    const rows = [...document.querySelectorAll('#bom-table tr')].filter(row => row.querySelector('td'));
    let visible = 0;
    const editingRow = document.activeElement?.closest('#bom-table tr');
    rows.forEach(row => {
      row.hidden = row !== editingRow && !row.textContent.toLowerCase().includes(query);
      if (!row.hidden) visible++;
    });
    document.querySelector('#bom-row-count').textContent = '显示 ' + visible + ' / ' + rows.length + ' 项';
  }
  document.querySelector('#bom-search').addEventListener('input', filterRows);
  document.querySelector('#bom-table').addEventListener('focusout', () => setTimeout(filterRows, 0));
  new MutationObserver(filterRows).observe(document.querySelector('#bom-table'), {childList:true, subtree:true, characterData:true});
  filterRows();
  document.querySelector('#bom-table').addEventListener('input', () => {
    const badge = document.querySelector('#bom-edit-state');
    badge.textContent = '有未保存的修改';
    badge.classList.remove('hidden');
    document.querySelector('#bom-save-msg').classList.add('hidden');
  });
  new MutationObserver(() => {
    if (!document.querySelector('#bom-save-msg').classList.contains('hidden')) document.querySelector('#bom-edit-state').classList.add('hidden');
  }).observe(document.querySelector('#bom-save-msg'), {attributes:true, attributeFilter:['class']});

  [['bom','bom'], ['doc','doc'], ['compare','cmp']].forEach(([view, prefix]) => {
    const progress = document.querySelector('#' + prefix + '-progress');
    const result = document.querySelector('#' + prefix + '-result');
    const empty = document.querySelector('#' + view + '-empty');
    progress.setAttribute('role', 'status');
    progress.setAttribute('aria-live', 'polite');
    document.querySelector('#' + prefix + '-error').setAttribute('role', 'alert');
    function syncTask() {
      const busy = !progress.classList.contains('hidden');
      const ready = !result.classList.contains('hidden');
      document.querySelector('#' + prefix + '-start').disabled = busy;
      if (view === 'bom') document.querySelector('#ins-correct').disabled = busy;
      document.querySelectorAll('#view-' + view + ' .drop input').forEach(input => input.disabled = busy);
      document.querySelectorAll('#view-' + view + ' .drop').forEach(drop => drop.setAttribute('aria-disabled', String(busy)));
      empty.classList.toggle('hidden', busy || ready);
      if (view === 'bom') {
        document.querySelectorAll('#view-bom > .workflow-steps li').forEach((step, i) => step.classList.toggle('current', i === (busy ? 1 : ready ? 2 : 0)));
      }
    }
    new MutationObserver(syncTask).observe(progress, {attributes:true, attributeFilter:['class']});
    new MutationObserver(syncTask).observe(result, {attributes:true, attributeFilter:['class']});
    syncTask();
  });
})();
