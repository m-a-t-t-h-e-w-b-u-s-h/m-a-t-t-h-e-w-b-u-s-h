Pliki w tym katalogu są **syntetyczne** – napisane ręcznie na wzór typowego
markupu Magento i schema.org, nie skopiowane ze sklepów (sklepy blokują
automatyczny dostęp). Służą do testowania logiki, nie potwierdzają, że
selektory pasują do prawdziwych stron. Po pierwszych prawdziwych zrzutach
z bookmarkletu warto dodać je tutaj jako fixtury regresyjne.

`badge_listing.html` odtwarza problem zaobserwowany na prawdziwym zrzucie
Skalnika: link ze zdjęcia z plakietką rabatową (`-27%`, `BLACK MONTH -48%`)
był brany jako nazwa produktu, a menu sklepu jako breadcrumbs. Markup jest
nadal syntetyczny.

`omnibus.html` – kafelki z informacją „najniższa cena z 30 dni przed obniżką”
(dyrektywa Omnibus), którą ekstraktor brał wcześniej za cenę aktualną
(Rab Microlight Alpine: 538,99 zł zamiast 716,99 zł). Markup syntetyczny.
