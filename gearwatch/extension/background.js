// Zapisuje zrzuty do Pobranych. Ta sama strona zapisywana jest automatycznie
// najwyżej raz dziennie; kliknięcie ikony rozszerzenia wymusza zapis.
function toast(tabId, text, color) {
  chrome.action.setBadgeBackgroundColor({ tabId, color });
  chrome.action.setBadgeText({ tabId, text });
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || msg.type !== 'gearwatch-save') return;
  const tabId = sender.tab && sender.tab.id;
  const u = new URL(msg.url);
  const key = 'seen:' + u.origin + u.pathname + u.search + ':' + new Date().toISOString().slice(0, 10);
  chrome.storage.local.get(key).then(found => {
    if (found[key] && !msg.force) { toast(tabId, '=', '#777'); return; }
    const url = 'data:application/json;charset=utf-8,' + encodeURIComponent(msg.json);
    chrome.downloads.download({ url, filename: msg.filename, conflictAction: 'uniquify', saveAs: false })
      .then(() => { chrome.storage.local.set({ [key]: Date.now() }); toast(tabId, '✓', '#1b5e20'); })
      .catch(err => { console.error('gearwatch', err); toast(tabId, '!', '#b71c1c'); });
  });
});

chrome.action.onClicked.addListener(tab => {
  chrome.tabs.sendMessage(tab.id, { type: 'gearwatch-capture-now' }).catch(() => toast(tab.id, '?', '#b71c1c'));
});

// sprzątanie starych wpisów "już zapisane dziś"
chrome.runtime.onStartup.addListener(() => {
  const today = new Date().toISOString().slice(0, 10);
  chrome.storage.local.get(null).then(all => {
    const old = Object.keys(all).filter(k => k.startsWith('seen:') && !k.endsWith(today));
    if (old.length) chrome.storage.local.remove(old);
  });
});
