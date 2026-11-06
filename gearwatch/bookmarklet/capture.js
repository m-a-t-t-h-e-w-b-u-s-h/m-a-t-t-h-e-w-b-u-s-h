/* gearwatch – zrzut bieżącej strony sklepu do pliku JSON.
   Działa w Twojej przeglądarce, na stronie, którą sam otworzyłeś: nie wysyła
   nic do sieci, tylko zapisuje plik gearwatch-<sklep>-<czas>.json w Pobranych. */
(function () {
  var d = document;
  var ld = Array.prototype.map.call(
    d.querySelectorAll('script[type="application/ld+json"]'),
    function (s) { return s.textContent; });
  var c = d.documentElement.cloneNode(true);
  c.querySelectorAll('script,style,noscript,svg,iframe,video,link[rel=stylesheet]')
    .forEach(function (e) { e.remove(); });
  var now = new Date().toISOString();
  var payload = { v: 1, url: location.href, title: d.title, captured_at: now,
                  jsonld: ld, html: '<!doctype html>' + c.outerHTML };
  var blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
  var a = d.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'gearwatch-' + location.hostname.replace(/^www\./, '') + '-' +
               now.replace(/[:.]/g, '-') + '.json';
  d.body.appendChild(a);
  a.click();
  var t = d.createElement('div');
  t.textContent = 'gearwatch: zapisano zrzut (' + Math.round(blob.size / 1024) + ' kB)';
  t.style.cssText = 'position:fixed;z-index:2147483647;bottom:16px;right:16px;padding:10px 14px;' +
                    'background:#1b5e20;color:#fff;font:14px sans-serif;border-radius:6px';
  d.body.appendChild(t);
  setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); t.remove(); }, 2500);
})();
