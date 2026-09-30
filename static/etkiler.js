/* ArcBase — gorsel etkiler (yalnizca gorunum; is mantigi app.js'te kalir).
   Etkiler tek yerde kullanilir (docs/vitrin numaralariyla):
     3 menu gostergesinin rengi · 6 spotlight (Kategoriler) · 8 tarama isigi bitisi (belge onizlemesi)
     9 metin cikarma (belge metni) · 10 morph (kart -> onizleme) · 13 karsilama · 14 yukleme ucusu
     15 miknatisli dugme (yalniz Panel'deki "Yukle ve analiz et")
   app.js iki yerde buradaki islevleri cagirir: window.ArcEtki.taramaBitir / yukleUcusu.
   prefers-reduced-motion acikken hicbir etki calismaz; sayfa gorunumu ve islevler ayni kalir. */
(function () {
  'use strict';

  const $ = (secici, kap = document) => kap.querySelector(secici);
  const $$ = (secici, kap = document) => Array.from(kap.querySelectorAll(secici));
  const azHareket = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fareVar = matchMedia('(hover: hover)').matches;
  const EGRI_YUMUSAK = 'cubic-bezier(0.22, 1, 0.36, 1)';
  const EGRI_IO = 'cubic-bezier(0.65, 0, 0.35, 1)';

  /* ---------------------------------------------------------------- 3 menu gostergesinin rengi
     app.js gostergeyi konumlar; burada aktif ogenin tonu (--h) yazilir. Sayfa degisince
     onceki sayfadaki ton hatirlanir, gosterge hem kayar hem renk degistirir. */
  (function gostergeRengi() {
    const gosterge = $('[data-aktif-gosterge]');
    if (!gosterge) return;
    const aktif = $('#kenar-menu .menu-ogesi[aria-current="page"]');
    const ton = aktif && aktif.style.getPropertyValue('--h').trim();
    let onceki = null;
    try { onceki = sessionStorage.getItem('menuTonu'); sessionStorage.removeItem('menuTonu'); } catch (e) { /* gizli mod */ }
    if (ton) {
      if (onceki && onceki !== ton && !azHareket) {
        gosterge.style.transition = 'none';
        gosterge.style.setProperty('--h', onceki);
        gosterge.getBoundingClientRect();
        gosterge.style.transition = '';
        requestAnimationFrame(() => requestAnimationFrame(() => gosterge.style.setProperty('--h', ton)));
      } else {
        gosterge.style.setProperty('--h', ton);
      }
    }
    $$('#kenar-menu a.menu-ogesi').forEach((a) => a.addEventListener('click', () => {
      const guncel = $('#kenar-menu .menu-ogesi[aria-current="page"]');
      const t = guncel && guncel.style.getPropertyValue('--h').trim();
      try { if (t) sessionStorage.setItem('menuTonu', t); } catch (e) { /* gizli mod */ }
    }));
  })();

  /* ---------------------------------------------------------------- 13 karsilama
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

  /* ---------------------------------------------------------------- 6 spotlight (Kategoriler)
     Imlec kartlarda gezerken isik dairesi imleci izler; her kart icin imlec konumuna gore
     hesaplanir, boylece komsu kartlarin kenari da yakinliga gore parlar. Yalniz transform. */
  (function spotlight() {
    const alan = $('[data-spot-alani]');
    if (!alan || azHareket || !fareVar) return;
    const kartlar = $$('[data-spot-kart]', alan);
    let kare = 0;
    let olay = null;
    const ciz = () => {
      kare = 0;
      if (!olay) return;
      kartlar.forEach((k) => {
        const r = k.getBoundingClientRect();
        const t = 'translate3d(' + (olay.clientX - r.left) + 'px,' + (olay.clientY - r.top) + 'px,0)';
        $$('.spot-isik i, .spot-halka i', k).forEach((i) => { i.style.transform = t; });
      });
    };
    alan.addEventListener('pointermove', (e) => {
      olay = e;
      alan.classList.add('spot-acik');
      if (!kare) kare = requestAnimationFrame(ciz);
    });
    alan.addEventListener('pointerleave', () => alan.classList.remove('spot-acik'));
  })();

  /* ---------------------------------------------------------------- 15 miknatisli dugme
     Yalniz Panel'in ana eylem dugmesi ("Yukle ve analiz et", Hizli yukleme kartinda): fare
     yaklasinca dugme imlece dogru cok hafif cekilir; uzaklasinca yavasca yerine doner.
     Dugme kilitliyken (dosya secilmemis) cekilmez. */
  (function miknatis() {
    const dugme = $('[data-karsilama]') && $('main [data-yukleme-formu] [data-gonder]');
    if (!dugme || azHareket || !fareVar) return;
    const YARICAP = 150;
    let hx = 0, hy = 0, x = 0, y = 0, kare = 0;
    dugme.style.transitionProperty = 'background-color, color, border-color, box-shadow, opacity, filter'; // transform'u biz suruyoruz
    dugme.style.willChange = 'transform';
    const yaz = () => {
      x += (hx - x) * 0.16;
      y += (hy - y) * 0.16;
      dugme.style.transform = 'translate3d(' + x.toFixed(2) + 'px,' + y.toFixed(2) + 'px,0)';
      kare = (Math.abs(hx - x) > 0.05 || Math.abs(hy - y) > 0.05) ? requestAnimationFrame(yaz) : 0;
    };
    document.addEventListener('pointermove', (e) => {
      const r = dugme.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2 - x);
      const dy = e.clientY - (r.top + r.height / 2 - y);
      const pay = dugme.disabled ? 0 : Math.max(0, 1 - Math.hypot(dx, dy) / YARICAP);
      hx = Math.max(-14, Math.min(14, dx * 0.48 * pay));
      hy = Math.max(-10, Math.min(10, dy * 0.48 * pay));
      if (!kare) kare = requestAnimationFrame(yaz);
    }, { passive: true });
    document.addEventListener('pointerleave', () => { hx = hy = 0; if (!kare) kare = requestAnimationFrame(yaz); });
  })();

  /* ---------------------------------------------------------------- 9 metin cikarma (belge metni)
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

  /* ---------------------------------------------------------------- 10 morph (kart -> belge onizlemesi)
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

  /* ---------------------------------------------------------------- 8 tarama isigi: bitis (belge sayfasi)
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

  /* ---------------------------------------------------------------- 14 yukleme ucusu
     Yuklenen belgenin satiri kucuk bir karta donusup ilgili kategori karosuna dogru ucar; karo
     isildar. Kategori listesi kapaliysa Kategoriler karosuna ucar. Menu gorunmuyorsa (mobil) yok. */
  function yukleUcusu(satir, tur) {
    if (azHareket || !satir || !satir.isConnected) return;
    const liste = $('#kategori-listesi');
    const oge = $('#kenar-menu a[data-tur="' + tur + '"]');
    const acik = liste && !liste.hasAttribute('data-kapali') && oge;
    const karo = acik ? $('.menu-ikon', oge) : $('#kenar-menu [data-alt-liste] .menu-ikon');
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
