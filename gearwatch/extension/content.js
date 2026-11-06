// gearwatch – działa tylko na stronach, które sam otworzysz w skalnik.pl / 8a.pl.
// Zbiera HTML strony (bez skryptów i stylów) + bloki JSON-LD i przekazuje je
// do background.js, który zapisuje plik w Pobranych. Nic nie jest wysyłane do sieci.
(function () {
  const DELAY_MS = 4000;          // czas na doładowanie listy produktów
  const SKIP_PATH = /\/(checkout|customer|cart|koszyk|wishlist|sales|newsletter|blog)(\/|$)/i;

  function looksLikeShopPage(d) {
    if (/just a moment|attention required/i.test(d.title)) return false;   // ekran Cloudflare
    if (SKIP_PATH.test(location.pathname)) return false;
    return !!d.querySelector(
      'script[type="application/ld+json"], .product-item, [data-price-amount], ' +
      'meta[property="og:type"][content="product"], #product_addtocart_form');
  }

  function capture(reason) {
    const d = document;
    const ld = Array.from(d.querySelectorAll('script[type="application/ld+json"]'), s => s.textContent);
    const c = d.documentElement.cloneNode(true);
    c.querySelectorAll('script,style,noscript,svg,iframe,video,link[rel=stylesheet]').forEach(e => e.remove());
    const now = new Date().toISOString();
    const payload = { v: 1, url: location.href, title: d.title, captured_at: now, jsonld: ld,
                      html: '<!doctype html>' + c.outerHTML, via: 'extension:' + reason };
    const filename = 'gearwatch-' + location.hostname.replace(/^www\./, '') + '-' +
                     now.replace(/[:.]/g, '-') + '.json';
    chrome.runtime.sendMessage({ type: 'gearwatch-save', filename, json: JSON.stringify(payload),
                                 url: location.href, force: reason === 'manual' });
  }

  chrome.runtime.onMessage.addListener(msg => {
    if (msg && msg.type === 'gearwatch-capture-now') capture('manual');
  });

  setTimeout(() => { if (looksLikeShopPage(document)) capture('auto'); }, DELAY_MS);
})();
