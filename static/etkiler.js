/* ArcBase — gorsel etkiler (yalnizca gorunum; is mantigi app.js'te kalir).
   Etkiler tek yerde kullanilir: karsilama (Panel vitrini) · tarama isigi bitisi (belge onizlemesi)
   metin cikarma (belge metni) · morph (kart -> onizleme) · yukleme ucusu (-> Belgeler hapi).
   Panel gostergeleri (kadran, cubuklar, yay, radar) yalniz CSS'tir (etkiler.css).
   app.js iki yerde buradaki islevleri cagirir: window.ArcEtki.taramaBitir / yukleUcusu.
   prefers-reduced-motion acikken hicbir etki calismaz; sayfa gorunumu ve islevler ayni kalir. */
(function () {
  'use strict';

  const $ = (secici, kap = document) => kap.querySelector(secici);
  const $$ = (secici, kap = document) => Array.from(kap.querySelectorAll(secici));
  const azHareket = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const EGRI_IO = 'cubic-bezier(0.65, 0, 0.35, 1)';

  /* ---------------------------------------------------------------- karsilama
     Selamlama saate gore; tarih ve ad duzeltilir. Sunucu "Merhaba" yazar (JS kapaliyken de dogru). */
  (function karsilama() {
    const kutu = $('[data-karsilama]');
    if (!kutu) return;
    const saat = new Date().getHours();
    const selam = saat < 6 ? 'İyi geceler' : saat < 12 ? 'Günaydın' : saat < 18 ? 'İyi günler' : saat < 22 ? 'İyi akşamlar' : 'İyi geceler';
    const selamEl = $('[data-selam]', kutu);
    if (selamEl) selamEl.textContent = selam + ',';
    const tarih = $('[data-karsilama-tarih]', kutu);
    if (tarih) tarih.textContent = new Date().toLocaleDateString('tr-TR', { weekday: 'long', day: 'numeric', month: 'long' });
    const ad = $('[data-karsilama-ad]', kutu);
    if (ad && ad.textContent) ad.textContent = ad.textContent.trim().replace(/^./, (h) => h.toLocaleUpperCase('tr'));
  })();

  /* ---------------------------------------------------------------- metin cikarma (belge metni)
     Satirlar <span> ile sarilir (bosluklar ve satir sonlari aynen kalir; kopyalama ve
     erisilebilirlik icin textContent degismez). Metin gorunce bir kez netlesir. */
  (function metinCikarma() {
    if (azHareket) return;
    $$('[data-ocr] .ocr-kutu').forEach((kutu) => {
      const pre = $('pre', kutu);
      if (!pre || pre.children.length) return;
      const parcalar = document.createDocumentFragment();
      let n = 0;
      pre.textContent.split('\n').forEach((satir, i) => {
        if (i) parcalar.append('\n');
        if (satir.trim() && n < 60) {
          const el = document.createElement('span');
          el.className = 'ocr-satir';
          el.style.setProperty('--i', String(n++));
          el.textContent = satir;
          parcalar.append(el);
        } else {
          parcalar.append(satir);
        }
      });
      pre.replaceChildren(parcalar);
      kutu.classList.add('ocr-hazir');
      const oynat = () => kutu.classList.add('ocr-oynat');
      if ('IntersectionObserver' in window) {
        const gozcu = new IntersectionObserver((kayitlar) => {
          if (kayitlar.some((k) => k.isIntersecting)) { oynat(); gozcu.disconnect(); }
        }, { threshold: 0.2 });
        gozcu.observe(kutu);
        setTimeout(oynat, 4000); // gozcu hic tetiklenmezse metin gizli kalmasin
      } else {
        oynat();
      }
    });
  })();

  /* ---------------------------------------------------------------- morph (kart -> belge onizlemesi)
     Belge kartina tiklayinca kartin kucuk resmi, sayfalar arasi gecis (View Transitions)
     sirasinda belge sayfasindaki buyuk onizlemeye donusur. Ad yalniz tiklanan kartta durur. */
  (function morph() {
    if (azHareket) return;
    const temizle = () => $$('[data-vt-belge]').forEach((el) => { el.style.viewTransitionName = ''; el.removeAttribute('data-vt-belge'); });
    document.addEventListener('click', (e) => {
      const kart = e.target.closest && e.target.closest('a.belge-karti');
      if (!kart || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.defaultPrevented) return;
      if (kart.closest('.secim-modu')) return; // secim modunda tiklama gitmez, secer
      const kucuk = $('.iskelet', kart);
      if (!kucuk) return;
      temizle();
      kucuk.style.viewTransitionName = 'belge-gorsel';
      kucuk.setAttribute('data-vt-belge', '');
    });
    window.addEventListener('pageshow', temizle); // geri gelinen sayfada ad kalmasin
  })();

  /* ---------------------------------------------------------------- tarama isigi: bitis (belge sayfasi)
     Belge islemesi bitince onizlemenin uzerinden son bir isik iner; isik indikce belge netlesir.
     Sayfa bu bittikten sonra yenilenir (app.js). Kartlarda bitis .netlesiyor sinifiyla (app.js). */
  function taramaBitir() {
    const cerceve = $('.onizleme-cercevesi[data-isleniyor]');
    const img = cerceve && $('img', cerceve);
    if (!cerceve || !img || azHareket || !img.complete || !img.naturalWidth) return Promise.resolve();
    const yuk = cerceve.getBoundingClientRect().height;
    const f = cerceve.getBoundingClientRect();
    const i = img.getBoundingClientRect();
    img.style.filter = getComputedStyle(img).filter; // bulanik hali sabit kalsin, net kopya uzerini acacak
    cerceve.removeAttribute('data-isleniyor');

    const acilim = document.createElement('div');
    acilim.className = 'tarama-acilim';
    const kopya = document.createElement('img');
    kopya.src = img.currentSrc || img.src;
    kopya.alt = '';
    kopya.style.cssText = 'left:' + (i.left - f.left) + 'px;top:' + (i.top - f.top) + 'px;width:' + i.width + 'px;height:' + i.height + 'px;object-fit:contain;';
    acilim.append(kopya);
    const cizgi = document.createElement('div');
    cizgi.className = 'tarama-cizgisi';
    cerceve.append(acilim, cizgi);

    const sure = 800;
    const secenek = { duration: sure, easing: EGRI_IO, fill: 'forwards' };
    acilim.animate([{ transform: 'translateY(' + -yuk + 'px)' }, { transform: 'translateY(0)' }], secenek);
    kopya.animate([{ transform: 'translateY(' + yuk + 'px)' }, { transform: 'translateY(0)' }], secenek);
    const inis = cizgi.animate([
      { transform: 'translateY(0)', opacity: 1 },
      { transform: 'translateY(' + (yuk - 2) + 'px)', opacity: 1, offset: 0.9 },
      { transform: 'translateY(' + (yuk - 2) + 'px)', opacity: 0 },
    ], secenek);
    return inis.finished.then(() => undefined, () => undefined);
  }

  /* ---------------------------------------------------------------- yukleme ucusu
     Yuklenen belgenin satiri kucuk bir hapa donusup ust menudeki "Belgeler" hapina dogru ucar;
     hap hafifce isildar. Hap menusu gorunmuyorsa (mobil) ucus olmaz. */
  function yukleUcusu(satir) {
    if (azHareket || !satir || !satir.isConnected) return;
    const karo = $('#ana-menu [data-belgeler-dugmesi]');
    if (!karo) return;
    const h = karo.getBoundingClientRect();
    const k = satir.getBoundingClientRect();
    if (!h.width || !k.width || h.right < 0 || h.left > innerWidth || k.bottom < 0 || k.top > innerHeight) return;

    const kap = document.createElement('div');
    kap.className = 'ucus-karti';
    const ic = document.createElement('div');
    ic.className = 'ucus-ic';
    const ad = document.createElement('span');
    ad.textContent = ($('[data-ad]', satir) || {}).textContent || 'Belge';
    ic.append(ad);
    kap.append(ic);
    document.body.append(kap);
    const w = ic.offsetWidth;
    const yy = ic.offsetHeight;
    const bx = k.left + k.width / 2 - w / 2;
    const by = k.top + k.height / 2 - yy / 2;
    const tx = h.left + h.width / 2 - w / 2;
    const ty = h.top + h.height / 2 - yy / 2;
    const sure = 700;
    // Yatay ve dikey farkli egrilerle: kart hafif kavisli bir yol izler.
    kap.animate([{ transform: 'translate3d(' + bx + 'px,0,0)' }, { transform: 'translate3d(' + tx + 'px,0,0)' }],
      { duration: sure, easing: EGRI_IO, fill: 'forwards' });
    ic.animate([
      { transform: 'translate3d(0,' + by + 'px,0) scale(1)', opacity: 1 },
      { transform: 'translate3d(0,' + ty + 'px,0) scale(0.18)', opacity: 0 },
    ], { duration: sure, easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)', fill: 'forwards' }).finished.then(() => {
      kap.remove();
      karo.classList.remove('karo-vurgu');
      karo.getBoundingClientRect();
      karo.classList.add('karo-vurgu');
      setTimeout(() => karo.classList.remove('karo-vurgu'), 800);
    }, () => kap.remove());
  }

  window.ArcEtki = { taramaBitir, yukleUcusu };
})();
