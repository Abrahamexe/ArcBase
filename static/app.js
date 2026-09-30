/* Dijital Arsiv — arayuz davranislari.
   Sayfaya ozel parcalar (grafik, isik kutusu, silme onayi...) ilgili eleman
   sayfada varsa calisir; her sayfa ayni dosyayi yukler. */
(function () {
  'use strict';

  const kok = document.documentElement;
  const $ = (secici, kap = document) => kap.querySelector(secici);
  const $$ = (secici, kap = document) => Array.from(kap.querySelectorAll(secici));
  const azHareket = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const IZINLI_UZANTILAR = ['jpg', 'jpeg', 'png', 'pdf'];
  const MAKS_BOYUT = 10 * 1024 * 1024; // app.py'deki MAKS_DOSYA_BOYUTU ile ayni
  const MAKS_PDF_BOYUTU = 5 * 1024 * 1024; // app.py'deki MAKS_PDF_BOYUTU ile ayni

  function kaydet(anahtar, deger) {
    try { localStorage.setItem(anahtar, deger); } catch (e) { /* gizli pencere vb. */ }
  }

  function boyutYaz(bayt) {
    if (bayt < 1024) return bayt + ' B';
    if (bayt < 1024 * 1024) return (bayt / 1024).toFixed(0) + ' KB';
    return (bayt / 1024 / 1024).toFixed(1).replace('.', ',') + ' MB';
  }

  // "Bilgi cikar": Groq hiz sinirina takilmamak icin ardisik istekler arasi bekleme; 429'da daha uzun.
  const ISTEK_ARALIGI_MS = 1000;
  const GROQ_BEKLEME_MS = 5000;
  const bekle = (ms) => new Promise((coz) => setTimeout(coz, ms));
  // base.html bu betige isleme durumu adresini verir (yukleme sonrasi yoklama).
  const DURUM_ADRESI = document.currentScript?.dataset.durumAdresi || '/isleme-durumu';
  // Dogrudan tarama acikken (Windows) bagli tarayicilarin durum adresi; kapaliyken yok.
  const TARAYICI_ADRESI = document.currentScript?.dataset.tarayiciAdresi;

  // fetch cevabini JSON olarak okur. Oturum dustuyse sunucu giris sayfasina
  // yonlendirir ve HTML doner; bu durum anlasilir bir hataya cevrilir.
  async function jsonOku(yanit) {
    if (!(yanit.headers.get('content-type') || '').includes('application/json')) {
      throw new Error(yanit.redirected ? 'Oturumunuz kapanmış, lütfen yeniden giriş yapın.'
                                       : 'Sunucu beklenmeyen bir cevap verdi (' + yanit.status + ').');
    }
    return yanit.json();
  }

  const DONEN_HALKA = '<span class="donen-halka" aria-hidden="true"></span>';

  function butonuMesgulYap(buton, metin) {
    buton.disabled = true;
    buton.dataset.eskiIcerik = buton.innerHTML;
    buton.innerHTML = DONEN_HALKA + '<span>' + metin + '</span>';
  }

  function butonuSerbestBirak(buton) {
    if (buton.dataset.eskiIcerik) {
      buton.innerHTML = buton.dataset.eskiIcerik;
      delete buton.dataset.eskiIcerik;
    }
    buton.disabled = false;
  }

  /* ---------------------------------------------------------------- tema */
  $$('[data-tema-degistir]').forEach((dugme) => {
    dugme.addEventListener('click', () => {
      const koyu = !kok.classList.contains('dark');
      const uygula = () => kok.classList.toggle('dark', koyu);
      // Destekleyen tarayicida tum sayfa tek seferde yumusakca gecis yapar;
      // aksi halde renkler aninda degisir.
      if (document.startViewTransition && !azHareket) {
        kok.classList.add('tema-gecisi');
        document.startViewTransition(uygula).finished.finally(() => kok.classList.remove('tema-gecisi'));
      } else {
        uygula();
      }
      kaydet('tema', koyu ? 'koyu' : 'acik');
    });
  });

  /* ---------------------------------------------------------------- kenar menu */
  const kenarNav = $('#kenar-menu nav');
  const gosterge = $('[data-aktif-gosterge]');

  // Kayan aktif gosterge: aktif sayfanin ogesinin arkasinda durur. Sayfa
  // degisince onceki sayfadaki konumundan yenisine kayar (konum sessionStorage'da).
  function gostergeKonumu() {
    const aktif = kenarNav && $('.menu-ogesi[aria-current="page"]', kenarNav);
    if (!aktif || !aktif.offsetParent || aktif.closest('.grup-icerik[data-kapali]')) return null;
    const n = kenarNav.getBoundingClientRect();
    const a = aktif.getBoundingClientRect();
    return { ust: a.top - n.top + kenarNav.scrollTop, yukseklik: a.height };
  }
  function gostergeyiKonumla(anlik) {
    if (!gosterge) return;
    const konum = gostergeKonumu();
    gosterge.classList.toggle('anlik', !!anlik);
    gosterge.classList.toggle('gorunur', !!konum);
    if (!konum) return;
    gosterge.style.height = konum.yukseklik + 'px';
    gosterge.style.transform = 'translateY(' + konum.ust + 'px)';
  }
  // Grup acilip kapanirken ya da menu daralirken gosterge her karede izler.
  function gostergeyiIzle(ms = 400) {
    const bitis = performance.now() + ms;
    (function kare() {
      gostergeyiKonumla(true);
      if (performance.now() < bitis) requestAnimationFrame(kare);
    })();
  }
  if (gosterge) {
    let onceki = null;
    try { onceki = JSON.parse(sessionStorage.getItem('menuGostergesi') || 'null'); } catch (e) { /* yok */ }
    sessionStorage.removeItem('menuGostergesi');
    const simdi = gostergeKonumu();
    if (onceki && simdi && !azHareket && Math.abs(onceki.ust - simdi.ust) > 1) {
      gosterge.classList.add('anlik', 'gorunur');
      gosterge.style.height = onceki.yukseklik + 'px';
      gosterge.style.transform = 'translateY(' + onceki.ust + 'px)';
      gosterge.getBoundingClientRect(); // baslangic konumu cizilsin
      requestAnimationFrame(() => requestAnimationFrame(() => gostergeyiKonumla(false)));
    } else {
      gostergeyiKonumla(true);
    }
    $$('a.menu-ogesi', kenarNav).forEach((a) => a.addEventListener('click', () => {
      const konum = gostergeKonumu();
      try { if (konum) sessionStorage.setItem('menuGostergesi', JSON.stringify(konum)); } catch (e) { /* gizli mod */ }
    }));
    window.addEventListener('resize', () => gostergeyiKonumla(true), { passive: true });
    document.fonts?.ready.then(() => gostergeyiKonumla(true));
  }

  const daraltDugmesi = $('[data-kenar-daralt]');
  function daraltEtiketiniGuncelle() {
    if (!daraltDugmesi) return;
    const dar = kok.classList.contains('kenar-dar');
    daraltDugmesi.setAttribute('aria-label', dar ? 'Menüyü genişlet' : 'Menüyü daralt');
    daraltDugmesi.setAttribute('aria-expanded', String(!dar));
  }
  function menuyuDaralt(dar) {
    kok.classList.toggle('kenar-dar', dar);
    kaydet('kenar', dar ? 'dar' : 'genis');
    ipucuGizle();
    daraltEtiketiniGuncelle();
    gostergeyiIzle(400);
  }
  daraltEtiketiniGuncelle();
  daraltDugmesi?.addEventListener('click', () => menuyuDaralt(!kok.classList.contains('kenar-dar')));

  const menuAcDugmesi = $('[data-menu-ac]');
  function mobilMenu(acik) {
    kok.classList.toggle('menu-acik', acik);
    menuAcDugmesi?.setAttribute('aria-expanded', String(acik));
    if (acik) {
      $('#kenar-menu a[aria-current], #kenar-menu a')?.focus({ preventScroll: true });
      gostergeyiIzle(400);
    }
  }
  menuAcDugmesi?.addEventListener('click', () => mobilMenu(true));
  $$('[data-menu-kapat]').forEach((el) => el.addEventListener('click', () => mobilMenu(false)));
  $$('#kenar-menu a').forEach((a) => a.addEventListener('click', () => mobilMenu(false)));

  // Menu gruplari (Ana isler, Arsiv, Yonetim) ve Kategoriler alt listesi
  // yuksekligi animasyonla acilir-kapanir; durum tarayicida hatirlanir. Ilk durum
  // base.html'deki satir ici betikle boyamadan once uygulanir.
  $$('[data-grup-dugmesi]').forEach((dugme) => {
    dugme.addEventListener('click', () => {
      // Dar menude "Kategoriler"e basmak menuyu genisletip listeyi acar.
      if (kok.classList.contains('kenar-dar') && window.innerWidth >= 1024) {
        if (!('altListe' in dugme.dataset)) return;
        menuyuDaralt(false);
        dugme.setAttribute('aria-expanded', 'true');
      } else {
        dugme.setAttribute('aria-expanded', String(dugme.getAttribute('aria-expanded') !== 'true'));
      }
      const acik = dugme.getAttribute('aria-expanded') === 'true';
      document.getElementById(dugme.getAttribute('aria-controls')).toggleAttribute('data-kapali', !acik);
      gostergeyiIzle(400);
      let durum = {};
      try { durum = JSON.parse(localStorage.getItem('menuGruplari') || '{}'); } catch (e) { /* bozuk kayit */ }
      durum[dugme.dataset.grupDugmesi] = acik;
      kaydet('menuGruplari', JSON.stringify(durum));
    });
  });

  // Kullanici karti: Hesabim, tema ve Cikis iceren menu; yukari dogru olcek ve
  // opaklikla acilir, kapanis animasyonu bitince gizlenir.
  const kullaniciKarti = $('[data-kullanici-karti]');
  const kullaniciMenusu = $('[data-kullanici-menusu]');
  let kullaniciMenusuZamani = null;
  const kullaniciMenusuAcik = () => kullaniciMenusu && kullaniciMenusu.classList.contains('acik');
  function kullaniciMenusuAc(acik) {
    if (!kullaniciMenusu) return;
    clearTimeout(kullaniciMenusuZamani);
    kullaniciKarti.setAttribute('aria-expanded', String(acik));
    if (acik) {
      kullaniciMenusu.hidden = false;
      kullaniciMenusu.getBoundingClientRect();
      kullaniciMenusu.classList.add('acik');
      ipucuGizle();
      $('a, button', kullaniciMenusu)?.focus({ preventScroll: true });
    } else {
      kullaniciMenusu.classList.remove('acik');
      kullaniciMenusuZamani = setTimeout(() => { kullaniciMenusu.hidden = true; }, azHareket ? 0 : 300);
    }
  }
  kullaniciKarti?.addEventListener('click', () => kullaniciMenusuAc(!kullaniciMenusuAcik()));
  document.addEventListener('click', (olay) => {
    if (kullaniciMenusuAcik() && !olay.target.closest('[data-kullanici-alani]')) kullaniciMenusuAc(false);
  });
  document.addEventListener('keydown', (olay) => {
    if (olay.key === 'Escape' && kullaniciMenusuAcik()) {
      kullaniciMenusuAc(false);
      kullaniciKarti.focus();
    }
  });

  // Daraltilmis menude oge adlari (ve sayilari) ipucu olarak gosterilir. Menu
  // kaydirilabilir oldugu icin ipucu sabit konumlu ayri bir katmanda cizilir.
  const ipucu = document.createElement('div');
  ipucu.className = 'ipucu';
  ipucu.setAttribute('role', 'tooltip');
  document.body.appendChild(ipucu);
  function ipucuGizle() { ipucu.classList.remove('gorunur'); }
  $$('#kenar-menu [data-ipucu]').forEach((el) => {
    const goster = () => {
      if (!kok.classList.contains('kenar-dar') || window.innerWidth < 1024 || kullaniciMenusuAcik()) return;
      const r = el.getBoundingClientRect();
      ipucu.textContent = el.dataset.ipucu;
      if (el.dataset.ipucuEk) {
        const ek = document.createElement('b');
        ek.textContent = el.dataset.ipucuEk;
        ipucu.append(ek);
      }
      ipucu.style.top = r.top + r.height / 2 + 'px';
      ipucu.style.left = r.right + 12 + 'px';
      ipucu.classList.add('gorunur');
    };
    el.addEventListener('mouseenter', goster);
    el.addEventListener('focus', goster);
    el.addEventListener('mouseleave', ipucuGizle);
    el.addEventListener('blur', ipucuGizle);
  });
  kenarNav?.addEventListener('scroll', ipucuGizle, { passive: true });

  /* ---------------------------------------------------------------- pencereler */
  function pencereAc(pencere) {
    if (!pencere || pencere.open) return;
    pencere.classList.remove('kapaniyor');
    pencere.showModal();
  }

  function pencereKapat(pencere, animasyonsuz) {
    // Icinde yukleme suren pencere (data-mesgul) kapatilmaz.
    if (!pencere || !pencere.open || pencere.classList.contains('kapaniyor') || 'mesgul' in pencere.dataset) return;
    if (animasyonsuz || azHareket) { pencere.close(); return; }
    pencere.classList.add('kapaniyor');
    setTimeout(() => {
      pencere.classList.remove('kapaniyor');
      pencere.close();
    }, 180);
  }

  $$('dialog').forEach((pencere) => {
    // Esc ile kapanirken de cikis animasyonu oynasin.
    pencere.addEventListener('cancel', (olay) => {
      olay.preventDefault();
      pencereKapat(pencere);
    });
    // Karartilmis arka plana tiklayinca kapat (pencere icerigi ayri bir cocuk eleman).
    pencere.addEventListener('click', (olay) => {
      if (olay.target === pencere) pencereKapat(pencere);
    });
    $$('[data-pencere-kapat]', pencere).forEach((d) =>
      d.addEventListener('click', () => pencereKapat(pencere)));
  });

  const yuklemePenceresi = $('#yukleme-penceresi');
  $$('[data-yukleme-ac]').forEach((d) => d.addEventListener('click', () => {
    mobilMenu(false);
    pencereAc(yuklemePenceresi);
  }));

  /* ---------------------------------------------------------------- komut paleti (Ctrl+K)
   Ortada acilan arama/komut penceresi: hizli eylemler, sayfalara gitme ve
   belge arama. Sayfalar menudeki baglantilardan toplanir (kullanicinin
   gormedigi sayfa cikmaz). Belgeler mevcut /ara sayfasindan okunur. */
  const palet = $('#komut-paleti');
  if (palet) {
    const girdi = $('#komut-girdi', palet);
    const liste = $('#komut-listesi', palet);
    const ikonKopyala = (secici) => $(secici)?.cloneNode(true) || null;
    const sade = (s) => s.toLocaleLowerCase('tr').replace(/[çğıöşü]/g, (h) => ({ ç: 'c', ğ: 'g', ı: 'i', ö: 'o', ş: 's', ü: 'u' })[h]);
    let secili = 0;
    let ogeler = [];
    let aramaIstegi = null;
    let aramaZamani = null;
    let belgeSonuclari = null; // null: aranmadi · 'yukleniyor' · []

    function eylemler() {
      const e = [];
      e.push({ grup: 'Hızlı eylemler', ad: 'Yeni belge', alt: 'Fotoğraf veya PDF yükle', ikon: '[data-yukleme-ac] svg', kisayol: '',
               calistir: () => $('[data-yukleme-ac]')?.click() });
      const tara = $('[data-tara-menu]:not([hidden]), [data-tara-dugmesi]:not([hidden])');
      if (tara) e.push({ grup: 'Hızlı eylemler', ad: 'Tara', alt: 'Bağlı tarayıcıdan belge tara', ikon: '[data-tara-menu] svg', href: tara.href });
      e.push({ grup: 'Hızlı eylemler', ad: kok.classList.contains('dark') ? 'Açık temaya geç' : 'Koyu temaya geç', alt: 'Tema değiştir',
               ikon: kok.classList.contains('dark') ? '.ikon-ay svg' : '.ikon-gunes svg', calistir: () => $('[data-tema-degistir]')?.click() });
      if (window.innerWidth >= 1024 && daraltDugmesi) {
        e.push({ grup: 'Hızlı eylemler', ad: kok.classList.contains('kenar-dar') ? 'Menüyü genişlet' : 'Menüyü daralt', alt: 'Kenar menü',
                 ikon: '[data-kenar-daralt] svg', calistir: () => daraltDugmesi.click() });
      }
      return e;
    }
    function sayfalar() {
      const goruldu = new Set();
      return $$('#kenar-menu a.menu-ogesi[href]').filter((a) => !a.hidden && !goruldu.has(a.href) && goruldu.add(a.href)).map((a) => {
        const kategori = a.closest('.alt-liste');
        const ad = ($('.kenar-etiket', a) || a).textContent.trim();
        return {
          grup: 'Sayfalar', ad, alt: kategori ? 'Kategori · ' + ($('.menu-sayac', a)?.textContent.trim() || '0') + ' belge' : '',
          ikon: a, href: a.href,
        };
      });
    }

    function vurgula(metin, sorgu) {
      const kap = document.createElement('span');
      const yer = sorgu ? sade(metin).indexOf(sade(sorgu)) : -1;
      if (yer < 0 || sade(metin).length !== metin.length) { kap.textContent = metin; return kap; }
      const isaret = document.createElement('mark');
      isaret.textContent = metin.slice(yer, yer + sorgu.length);
      kap.append(metin.slice(0, yer), isaret, metin.slice(yer + sorgu.length));
      return kap;
    }

    function ikonuAl(kaynak) {
      if (!kaynak) return null;
      if (kaynak instanceof SVGElement) return document.importNode(kaynak, true);
      if (typeof kaynak !== 'string') return $('.menu-ikon svg, .menu-ikon .kategori-nokta', kaynak)?.cloneNode(true) || null;
      return ikonKopyala(kaynak);
    }

    function ciz() {
      const sorgu = girdi.value.trim();
      const s = sade(sorgu);
      const uygun = (o) => !s || sade(o.ad + ' ' + (o.alt || '')).includes(s);
      ogeler = [...eylemler().filter(uygun), ...sayfalar().filter(uygun)];
      if (Array.isArray(belgeSonuclari)) ogeler.push(...belgeSonuclari);
      if (sorgu) {
        ogeler.push({ grup: 'Belgeler', ad: '“' + sorgu + '” için tüm sonuçlar', alt: 'Arama sayfasında aç',
                      ikon: '#komut-paleti .komut-girdi-alani svg', href: palet.dataset.aramaAdresi + '?q=' + encodeURIComponent(sorgu) });
      }
      secili = Math.min(secili, Math.max(ogeler.length - 1, 0));

      const parca = document.createDocumentFragment();
      let grup = null;
      ogeler.forEach((o, i) => {
        if (o.grup !== grup) {
          grup = o.grup;
          const baslik = document.createElement('div');
          baslik.className = 'komut-baslik';
          baslik.textContent = grup;
          parca.append(baslik);
          if (grup === 'Belgeler' && belgeSonuclari === 'yukleniyor') parca.append(...iskeletler());
        }
        const el = document.createElement(o.href ? 'a' : 'button');
        if (o.href) el.href = o.href; else el.type = 'button';
        el.className = 'komut-ogesi';
        el.id = 'komut-' + i;
        el.setAttribute('role', 'option');
        el.setAttribute('aria-selected', String(i === secili));
        el.tabIndex = -1;
        const ikon = document.createElement('span');
        ikon.className = 'komut-ikon';
        const svg = ikonuAl(o.ikon);
        if (svg) ikon.append(svg);
        const metin = document.createElement('span');
        metin.className = 'komut-metin';
        const b = document.createElement('b');
        b.append(vurgula(o.ad, sorgu));
        metin.append(b);
        if (o.alt) { const k = document.createElement('small'); k.textContent = o.alt; metin.append(k); }
        const ek = document.createElement('span');
        ek.className = 'komut-ek';
        ek.append(ikonKopyala('#komut-enter-ikonu svg') || '↵');
        el.append(ikon, metin, ek);
        el.addEventListener('mousemove', () => { if (secili !== i) sec(i, false); });
        el.addEventListener('click', (olay) => { olay.preventDefault(); calistir(i); });
        parca.append(el);
      });
      if (belgeSonuclari === 'yukleniyor' && !ogeler.some((o) => o.grup === 'Belgeler')) {
        const baslik = document.createElement('div');
        baslik.className = 'komut-baslik';
        baslik.textContent = 'Belgeler';
        parca.append(baslik, ...iskeletler());
      }
      if (!ogeler.length && belgeSonuclari !== 'yukleniyor') {
        const bos = document.createElement('p');
        bos.className = 'komut-bos';
        bos.textContent = 'Sonuç bulunamadı.';
        parca.append(bos);
      }
      liste.replaceChildren(parca);
      girdi.setAttribute('aria-activedescendant', ogeler.length ? 'komut-' + secili : '');
    }

    function iskeletler() {
      return [0, 1, 2].map(() => {
        const s = document.createElement('div');
        s.className = 'komut-iskelet';
        s.innerHTML = '<i></i><span><i></i><i></i></span>';
        return s;
      });
    }

    function sec(i, kaydir = true) {
      if (!ogeler.length) return;
      secili = (i + ogeler.length) % ogeler.length;
      $$('.komut-ogesi', liste).forEach((el, j) => el.setAttribute('aria-selected', String(j === secili)));
      girdi.setAttribute('aria-activedescendant', 'komut-' + secili);
      if (kaydir) $('#komut-' + secili, liste)?.scrollIntoView({ block: 'nearest' });
    }

    function calistir(i) {
      const o = ogeler[i];
      if (!o) return;
      pencereKapat(palet, true);
      if (o.href) location.href = o.href;
      else o.calistir?.();
    }

    // Belge arama: /ara sayfasinin sonuc kartlari okunur (en fazla 6).
    async function belgeAra(sorgu) {
      aramaIstegi?.abort();
      if (sorgu.length < 2) { belgeSonuclari = null; ciz(); return; }
      belgeSonuclari = 'yukleniyor';
      ciz();
      const istek = new AbortController();
      aramaIstegi = istek;
      try {
        const yanit = await fetch(palet.dataset.aramaAdresi + '?q=' + encodeURIComponent(sorgu),
                                  { credentials: 'same-origin', signal: istek.signal });
        const belge = new DOMParser().parseFromString(await yanit.text(), 'text/html');
        belgeSonuclari = $$('.belge-karti', belge).slice(0, 6).map((kart) => {
          const tur = $('.p-4 > div:last-child > span:first-child', kart);
          const tarih = $('time', kart);
          return {
            grup: 'Belgeler',
            ad: $('p[title]', kart)?.getAttribute('title') || 'Belge',
            alt: [tur?.textContent.trim(), tarih?.textContent.trim()].filter(Boolean).join(' · '),
            ikon: tur?.querySelector('svg') || '#kenar-menu [data-alt-liste] svg',
            href: new URL(kart.getAttribute('href'), location.href).href,
          };
        });
      } catch (hata) {
        if (hata.name === 'AbortError') return;
        belgeSonuclari = [];
      }
      if (aramaIstegi === istek) ciz();
    }

    girdi.addEventListener('input', () => {
      secili = 0;
      clearTimeout(aramaZamani);
      const sorgu = girdi.value.trim();
      aramaZamani = setTimeout(() => belgeAra(sorgu), 220);
      ciz();
    });
    girdi.addEventListener('keydown', (olay) => {
      if (olay.key === 'ArrowDown') { olay.preventDefault(); sec(secili + 1); }
      else if (olay.key === 'ArrowUp') { olay.preventDefault(); sec(secili - 1); }
      else if (olay.key === 'Home' && olay.ctrlKey) { olay.preventDefault(); sec(0); }
      else if (olay.key === 'End' && olay.ctrlKey) { olay.preventDefault(); sec(ogeler.length - 1); }
      else if (olay.key === 'Enter') { olay.preventDefault(); calistir(secili); }
    });

    function paletiAc() {
      if (palet.open) { girdi.select(); return; }
      mobilMenu(false);
      kullaniciMenusuAc(false);
      girdi.value = '';
      belgeSonuclari = null;
      secili = 0;
      ciz();
      pencereAc(palet);
      girdi.focus();
    }
    $$('[data-komut-ac]').forEach((d) => d.addEventListener('click', paletiAc));
    document.addEventListener('keydown', (olay) => {
      if ((olay.ctrlKey || olay.metaKey) && !olay.altKey && olay.key.toLowerCase() === 'k') {
        olay.preventDefault();
        paletiAc();
      }
    });
  }

  /* ---------------------------------------------------------------- bildirimler */
  function bildirimKapat(bildirim) {
    if (bildirim.classList.contains('kapaniyor')) return;
    bildirim.classList.add('kapaniyor');
    bildirim.addEventListener('animationend', () => bildirim.remove(), { once: true });
    if (azHareket) bildirim.remove();
  }
  $$('[data-bildirim]').forEach((bildirim) => {
    $('[data-bildirim-kapat]', bildirim)?.addEventListener('click', () => bildirimKapat(bildirim));
    // Sure cubugu bitince (fareyle ustune gelindiginde duraklar) bildirim kapanir.
    $('.bildirim-sure', bildirim)?.addEventListener('animationend', () => bildirimKapat(bildirim));
  });

  /* ---------------------------------------------------------------- tarihler
   Sunucu UTC yazar; burada tarayicinin saat dilimine cevrilir. */
  const goreliBicim = new Intl.RelativeTimeFormat('tr', { numeric: 'auto' });
  const kisaTarih = new Intl.DateTimeFormat('tr', { day: 'numeric', month: 'short', year: 'numeric' });
  const tamTarih = new Intl.DateTimeFormat('tr', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' });

  function goreliYaz(tarih) {
    const saniye = (Date.now() - tarih.getTime()) / 1000;
    if (saniye < 45) return 'az önce';
    if (saniye < 45 * 60) return goreliBicim.format(-Math.round(saniye / 60), 'minute');
    if (saniye < 22 * 3600) return goreliBicim.format(-Math.round(saniye / 3600), 'hour');
    if (saniye < 6.5 * 86400) return goreliBicim.format(-Math.round(saniye / 86400), 'day');
    return kisaTarih.format(tarih);
  }

  $$('time[data-zaman]').forEach((el) => {
    const tarih = new Date(el.getAttribute('datetime'));
    if (isNaN(tarih)) return;
    el.title = tamTarih.format(tarih);
    el.textContent = el.dataset.zaman === 'tam' ? tamTarih.format(tarih) : goreliYaz(tarih);
  });

  /* ---------------------------------------------------------------- gorseller */
  function gorselHazir(img) { img.dataset.yuklendi = '1'; }
  function gorselleriHazirla(kap = document) {
    $$('img.gorsel-yavas', kap).forEach((img) => {
      if (img.complete && img.naturalWidth) gorselHazir(img);
      else {
        img.addEventListener('load', () => gorselHazir(img), { once: true });
        // Onizleme alinamazsa bos kalmasin: kutu iskelet animasyonunu birakir.
        img.addEventListener('error', () => { gorselHazir(img); img.style.visibility = 'hidden'; }, { once: true });
      }
    });
  }
  gorselleriHazirla();

  /* ---------------------------------------------------------------- isleme durumu
   Yuklenen belge arka planda islenir (duzeltme, OCR, siniflandirma). Islenmekte
   olan belgeler (kartlar, detay sayfasi, yukleme listesi) /isleme-durumu ile
   kisa araliklarla yoklanir; sekme gizliyken yoklama durur, 10 dakika sonra biter. */
  const ISLENIYOR = ['bekliyor', 'isleniyor'];
  const islenmekte = (durum) => ISLENIYOR.includes(durum);

  function yoklayici(kimlikleriAl, sonucaBak) {
    const bas = Date.now();
    let zamanlayici = null;
    let calisiyor = false;
    const planla = () => {
      if (zamanlayici || calisiyor || document.hidden) return;
      zamanlayici = setTimeout(tur, Date.now() - bas < 30000 ? 1500 : 3000);
    };
    async function tur() {
      zamanlayici = null;
      const kimlikler = kimlikleriAl();
      if (!kimlikler.length || Date.now() - bas > 10 * 60 * 1000) return;
      calisiyor = true;
      try {
        const adres = DURUM_ADRESI + '?' + kimlikler.map((k) => 'id=' + encodeURIComponent(k)).join('&');
        const yanit = await fetch(adres, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        await sonucaBak(await jsonOku(yanit));
      } catch (hata) { /* ag hatasi: bir sonraki turda yeniden denenir */ }
      calisiyor = false;
      planla();
    }
    document.addEventListener('visibilitychange', planla);
    return planla;
  }

  // Menu sayaclari ve paneldeki "N belge isleniyor" notu (belge turu belli olunca degisir).
  function sayaclariGuncelle(veri) {
    Object.entries(veri.sayaclar || {}).forEach(([kod, adet]) => {
      const el = $('[data-tur-sayaci="' + kod + '"]');
      if (el) {
        el.textContent = adet;
        el.closest('[data-ipucu]')?.setAttribute('data-ipucu-ek', adet);
      }
    });
    if (typeof veri.isleniyor === 'number') {
      const rozet = $('[data-isleniyor-rozeti]');
      if (rozet) {
        rozet.textContent = veri.isleniyor;
        rozet.hidden = !veri.isleniyor;
        const oge = rozet.closest('[data-ipucu]');
        if (veri.isleniyor) oge?.setAttribute('data-ipucu-ek', veri.isleniyor + ' işleniyor');
        else oge?.removeAttribute('data-ipucu-ek');
      }
      const nokta = $('[data-isleniyor-nokta]');
      if (nokta) nokta.hidden = !veri.isleniyor;
    }
    const not = $('[data-isleniyor-bilgisi]');
    if (not) {
      not.hidden = !veri.isleniyor;
      $('[data-isleniyor-sayisi]', not).textContent = veri.isleniyor;
    }
  }

  // "Isleniyor" rozeti yumusakca "Tamamlandi"ya doner; kart az sonra yenilenir.
  function rozetiTamamla(rozet) {
    if (azHareket) return Promise.resolve();
    return new Promise((bitti) => {
      rozet.classList.add('degisiyor');
      setTimeout(() => {
        $('[data-rozet-metni]', rozet).textContent = 'Tamamlandı';
        rozet.setAttribute('data-tamam', '');
        rozet.classList.remove('degisiyor');
        setTimeout(bitti, 900);
      }, 200);
    });
  }

  // Listelerdeki islenmekte olan kartlar: biten kart, sayfanin guncel halinden
  // alinan yenisiyle degistirilir (kaydirma, acik pencere ve formlar korunur).
  const bekleyenKartlar = () => $$('.belge-karti[data-isleniyor]').map((k) => k.dataset.belgeId);
  if (bekleyenKartlar().length) {
    yoklayici(bekleyenKartlar, async (veri) => {
      sayaclariGuncelle(veri);
      const biten = Object.entries(veri.belgeler || {}).filter(([, d]) => !islenmekte(d.durum)).map(([id]) => id);
      if (!biten.length) return;
      const donusum = Promise.all(biten.map((id) => {
        const rozet = $('.belge-karti[data-belge-id="' + id + '"] [data-isleme-rozeti]');
        return rozet && veri.belgeler[id].durum !== 'hata' ? rozetiTamamla(rozet) : null;
      }));
      const yanit = await fetch(location.href, { credentials: 'same-origin' });
      await donusum;
      const yeni = new DOMParser().parseFromString(await yanit.text(), 'text/html');
      biten.forEach((id) => {
        const eski = $('.belge-karti[data-belge-id="' + id + '"]');
        const guncel = $('.belge-karti[data-belge-id="' + id + '"]', yeni);
        if (!eski) return;
        if (!guncel) { eski.removeAttribute('data-isleniyor'); return; }
        guncel.classList.remove('kart-giris');
        guncel.classList.add('netlesiyor'); // kucuk resim netlesir, tur rozeti yerine oturur (etkiler.css)
        const kart = document.adoptNode(guncel);
        eski.replaceWith(kart);
        gorselleriHazirla(kart);
      });
    })();
  }

  // Detay sayfasi: islem bitince sayfa yenilenir (tur, bilgiler, OCR metni, kirpilmis gorsel).
  const isleyenBelge = $('[data-belge-isleniyor]');
  if (isleyenBelge) {
    const kimlik = isleyenBelge.dataset.belgeIsleniyor;
    yoklayici(() => [kimlik], (veri) => {
      sayaclariGuncelle(veri);
      const d = veri.belgeler?.[kimlik];
      // Bitince onizlemenin uzerinden son bir tarama isigi iner (etkiler.js), sonra sayfa yenilenir.
      if (d && !islenmekte(d.durum)) {
        const bitis = window.ArcEtki?.taramaBitir?.() || Promise.resolve();
        bitis.then(() => location.reload(), () => location.reload());
      }
    })();
  }

  /* ---------------------------------------------------------------- arama vurgusu
   Arama sonuclarinda kart basligindaki eslesen kismi isaretler. */
  $$('[data-vurgula]').forEach((kap) => {
    const sorgu = kap.dataset.vurgula.trim().toLocaleLowerCase('tr');
    if (!sorgu) return;
    $$('.belge-karti p[title]', kap).forEach((baslik) => {
      const metin = baslik.textContent;
      const yer = metin.toLocaleLowerCase('tr').indexOf(sorgu);
      if (yer < 0 || metin.toLocaleLowerCase('tr').length !== metin.length) return;
      const isaret = document.createElement('mark');
      isaret.className = 'arama-vurgusu';
      isaret.textContent = metin.slice(yer, yer + sorgu.length);
      baslik.replaceChildren(metin.slice(0, yer), isaret, metin.slice(yer + sorgu.length));
    });
  });

  /* ---------------------------------------------------------------- yukleme
   Secilen dosyalar (en fazla 10) sirayla, her biri ayri bir fetch istegiyle
   /yukle'ye gonderilir; sunucu dosyayi kaydedip hemen doner. OCR ve analiz
   arka planda yapilir: satirlar "isleniyor" durumuna gecer ve durum yoklanir.
   Tek dosyada dogrudan belge sayfasina gidilir (sayfa kendini gunceller).
   Bir dosyadaki hata digerlerini durdurmaz. */
  const TOPLU_SINIR = 10; // app.py'deki TOPLU_YUKLEME_SINIRI ile ayni
  const satirSablonu = $('#kuyruk-satiri-sablonu');
  let yuklemeSuruyor = false;

  function dosyaHatasi(dosya) {
    const uzanti = (dosya.name.split('.').pop() || '').toLowerCase();
    if (!IZINLI_UZANTILAR.includes(uzanti)) return 'Sadece JPG, PNG ve PDF dosyaları yüklenebilir.';
    if (dosya.size === 0) return 'Dosya boş görünüyor.';
    if (dosya.size > MAKS_BOYUT) return 'Dosya çok büyük (' + boyutYaz(dosya.size) + '). En fazla 10 MB yükleyebilirsiniz.';
    if (uzanti === 'pdf' && dosya.size > MAKS_PDF_BOYUTU) return 'PDF çok büyük (' + boyutYaz(dosya.size) + '). PDF dosyaları en fazla 5 MB olabilir.';
    return null;
  }

  function ayrilmaUyarisi(olay) {
    olay.preventDefault();
    olay.returnValue = '';
  }

  function yuklemeFormunuHazirla(form) {
    const girdi = $('[data-dosya-girisi]', form);
    const alan = $('[data-birakma]', form);
    const alanBasligi = $('[data-birakma-baslik]', form);
    const kuyruk = $('[data-kuyruk]', form);
    const hataKutusu = $('[data-form-hata]', form);
    const kontroller = $('[data-kontroller]', form);
    const ozet = $('[data-ozet]', form);
    const gonder = $('[data-gonder]', form);
    const gonderEtiketi = $('[data-gonder-etiket]', form);
    const islemeNotu = $('[data-isleme-notu]', form);
    const anahtar = $('[data-duzelt-anahtari]', form);
    const pencere = form.closest('dialog');
    let kalanKota = Number(form.dataset.kalanKota);
    let ogeler = []; // {dosya, satir, hata}

    const hataGoster = (mesaj) => {
      hataKutusu.textContent = mesaj;
      hataKutusu.hidden = !mesaj;
      if (mesaj && !azHareket) {
        alan.classList.remove('titret');
        void alan.offsetWidth; // animasyonu yeniden baslatmak icin
        alan.classList.add('titret');
      }
    };

    const satirDurumu = (oge, durum, bilgi) => {
      oge.satir.dataset.durum = durum;
      $('[data-bilgi]', oge.satir).textContent = bilgi;
    };

    const gecerliler = () => ogeler.filter((o) => !o.hata);

    const guncelle = () => {
      const adet = gecerliler().length;
      kuyruk.hidden = !ogeler.length;
      gonder.disabled = !adet;
      gonderEtiketi.textContent = adet > 1 ? adet + ' belgeyi yükle ve analiz et' : 'Yükle ve analiz et';
      alanBasligi.textContent = ogeler.length ? 'Başka dosya eklemek için bırakın ya da tıklayın' : 'Belgenin fotoğrafını yükleyin, gerisini biz halledelim';
    };

    const ekle = (dosyalar) => {
      hataGoster('');
      let fazla = 0;
      for (const dosya of dosyalar) {
        const ayni = ogeler.some((o) => o.dosya.name === dosya.name && o.dosya.size === dosya.size &&
                                        o.dosya.lastModified === dosya.lastModified);
        if (ayni) continue;
        if (ogeler.length >= TOPLU_SINIR) { fazla++; continue; }
        const satir = satirSablonu.content.firstElementChild.cloneNode(true);
        const oge = { dosya, satir, hata: dosyaHatasi(dosya) };
        $('[data-ad]', satir).textContent = dosya.name;
        satirDurumu(oge, oge.hata ? 'hata' : 'secildi',
                    oge.hata || (/\.pdf$/i.test(dosya.name) ? 'PDF' : 'Görsel') + ' · ' + boyutYaz(dosya.size));
        $('[data-kaldir]', satir).addEventListener('click', () => {
          ogeler = ogeler.filter((o) => o !== oge);
          satir.remove();
          hataGoster('');
          guncelle();
        });
        ogeler.push(oge);
        kuyruk.appendChild(satir);
      }
      if (fazla) hataGoster('Tek seferde en fazla ' + TOPLU_SINIR + ' dosya yüklenebilir; ' + fazla + ' dosya eklenmedi.');
      guncelle();
    };

    const sifirla = () => {
      ogeler = [];
      kuyruk.replaceChildren();
      delete form.dataset.bitti;
      ozet.hidden = true;
      islemeNotu.hidden = true;
      kontroller.hidden = false;
      alan.hidden = false;
      butonuSerbestBirak(gonder);
      hataGoster('');
      guncelle();
    };

    const kilitle = (acik) => {
      yuklemeSuruyor = acik;
      for (const el of [form, pencere]) {
        if (!el) continue;
        if (acik) el.dataset.mesgul = ''; else delete el.dataset.mesgul;
      }
      anahtar.disabled = acik;
      if (acik) {
        butonuMesgulYap(gonder, 'Yükleniyor…');
        window.addEventListener('beforeunload', ayrilmaUyarisi);
      } else {
        butonuSerbestBirak(gonder);
        window.removeEventListener('beforeunload', ayrilmaUyarisi);
      }
    };

    // Tek dosyayi gonderir; {basarili, kotaDoldu, adres} dondurur. Basarili
    // dosyanin satiri "isleniyor"a gecer; sonucu durum yoklamasi getirir.
    const dosyaYukle = async (oge) => {
      satirDurumu(oge, 'okunuyor', 'Yükleniyor…');
      const govde = new FormData();
      govde.append('csrf_token', form.elements.csrf_token.value);
      govde.append('belge', oge.dosya, oge.dosya.name);
      govde.append('otomatik_duzelt', anahtar.checked ? '1' : '0');
      let durum = 0;
      let veri;
      try {
        const yanit = await fetch(form.action, {
          method: 'POST', body: govde, credentials: 'same-origin', headers: { Accept: 'application/json' },
        });
        durum = yanit.status;
        veri = await jsonOku(yanit);
      } catch (hata) {
        veri = {
          basarili: false,
          hata: hata instanceof TypeError ? 'Bağlantı hatası, internet bağlantınızı kontrol edin.' : hata.message,
        };
      }
      if (!veri.basarili) {
        satirDurumu(oge, 'hata', veri.hata || 'Yüklenemedi.');
        return { basarili: false, kotaDoldu: durum === 403 };
      }
      oge.belgeId = String(veri.belge_id);
      oge.adres = veri.adres;
      satirDurumu(oge, 'analiz', 'Metin okunuyor ve belge sınıflandırılıyor…');
      return { basarili: true, adres: veri.adres };
    };

    // Islem bitince satira tur rozeti, uyarilar ve "Ac" baglantisi eklenir.
    const satirSonucu = (oge, d) => {
      if (d.durum === 'hata') {
        satirDurumu(oge, 'hata', d.hata);
        return;
      }
      const uyarilar = d.uyarilar || [];
      const notlar = d.kirpma_kontrol ? uyarilar.concat('Kırpma otomatik algılandı ama emin olunamadı.') : uyarilar;
      satirDurumu(oge, 'kaydedildi', notlar.length ? notlar.join(' ') : 'Kaydedildi');
      if (notlar.length) oge.satir.dataset.uyari = '';
      const sonuc = $('[data-sonuc]', oge.satir);
      const rozet = $('[data-rozet-sablonu="' + d.tur + '"]');
      if (rozet) sonuc.appendChild(rozet.content.cloneNode(true));
      window.ArcEtki?.yukleUcusu?.(oge.satir, d.tur); // satir ilgili kategori karosuna ucar (etkiler.js)
      if (d.kirpma_kontrol) {
        const kontrol = document.createElement('a');
        kontrol.href = oge.adres + '?koseler=1';
        kontrol.className = 'text-sm font-semibold text-orange-600 hover:underline dark:text-orange-300';
        kontrol.textContent = 'Kırpmayı kontrol et';
        sonuc.appendChild(kontrol);
      }
      const ac = document.createElement('a');
      ac.href = oge.adres;
      ac.className = 'text-sm font-semibold text-marka-600 hover:underline dark:text-marka-300';
      ac.textContent = 'Aç';
      ac.setAttribute('aria-label', oge.dosya.name + ' belgesini aç');
      sonuc.appendChild(ac);
    };

    const ozetGoster = () => {
      const kaydedilen = ogeler.filter((o) => o.satir.dataset.durum === 'kaydedildi').length;
      const hatali = ogeler.length - kaydedilen;
      islemeNotu.hidden = true;
      ozet.dataset.durum = hatali ? (kaydedilen ? 'kismi' : 'hata') : 'tam'; // renk ve kutlama animasyonu
      $('[data-ozet-metni]', form).textContent =
        kaydedilen + ' belge kaydedildi' + (hatali ? ', ' + hatali + ' hata' : '') + '.';
      ozet.hidden = false;
    };

    gonder.disabled = true;
    girdi.addEventListener('change', () => {
      ekle(girdi.files);
      girdi.value = ''; // ayni dosya kaldirilip yeniden secilebilsin
    });
    form.dosyaAta = (dosyalar) => { if (!yuklemeSuruyor && !('bitti' in form.dataset)) ekle(dosyalar); };
    form.sifirla = sifirla;
    $('[data-yeniden]', form).addEventListener('click', sifirla);

    let derinlik = 0;
    alan.addEventListener('dragenter', (olay) => {
      olay.preventDefault();
      derinlik++;
      alan.classList.add('uzerinde');
    });
    alan.addEventListener('dragover', (olay) => olay.preventDefault());
    alan.addEventListener('dragleave', () => {
      if (--derinlik <= 0) { derinlik = 0; alan.classList.remove('uzerinde'); }
    });
    alan.addEventListener('drop', (olay) => {
      olay.preventDefault();
      olay.stopPropagation();
      derinlik = 0;
      alan.classList.remove('uzerinde');
      suruklemeBitti();
      if (olay.dataTransfer.files.length) form.dosyaAta(olay.dataTransfer.files);
    });

    form.addEventListener('submit', async (olay) => {
      olay.preventDefault();
      if (yuklemeSuruyor) return;
      const liste = gecerliler();
      if (!liste.length) {
        hataGoster(ogeler.length ? 'Listede yüklenebilecek geçerli dosya yok.' : 'Lütfen bir dosya seçin.');
        return;
      }
      if (liste.length > kalanKota) {
        hataGoster(kalanKota > 0
          ? 'Kotanızda ' + kalanKota + ' belgelik yer kaldı ama ' + liste.length + ' dosya seçtiniz. Fazla dosyaları listeden çıkarın.'
          : 'Belge kotanız doldu. Yeni belge yüklemek için eski belgelerden bazılarını silin.');
        return;
      }
      hataGoster('');
      kilitle(true);
      liste.forEach((o) => satirDurumu(o, 'bekliyor', 'Sırada bekliyor'));

      const sonuclar = [];
      for (let i = 0; i < liste.length; i++) {
        liste[i].satir.scrollIntoView({ block: 'nearest', behavior: azHareket ? 'auto' : 'smooth' });
        const sonuc = await dosyaYukle(liste[i]);
        sonuclar.push(sonuc);
        if (sonuc.basarili) kalanKota--;
        if (sonuc.kotaDoldu) {
          liste.slice(i + 1).forEach((o) => satirDurumu(o, 'hata', 'Kota dolduğu için yüklenmedi.'));
          break;
        }
      }
      kilitle(false);

      // Tek dosya: dogrudan belge sayfasina gidilir; sayfa islem bitince kendini gunceller.
      const tek = sonuclar[0];
      if (ogeler.length === 1 && tek.basarili) {
        window.location.href = tek.adres;
        return;
      }
      form.dataset.bitti = '';
      kontroller.hidden = true;
      alan.hidden = true;
      const islenenler = () => ogeler.filter((o) => o.satir.dataset.durum === 'analiz');
      if (!islenenler().length) { ozetGoster(); return; }
      islemeNotu.hidden = false;
      yoklayici(() => islenenler().map((o) => o.belgeId), (veri) => {
        sayaclariGuncelle(veri);
        islenenler().forEach((o) => {
          const d = veri.belgeler?.[o.belgeId];
          if (d && !islenmekte(d.durum)) satirSonucu(o, d);
        });
        if (!islenenler().length) ozetGoster();
      })();
    });
  }

  const yuklemeFormlari = $$('[data-yukleme-formu]');
  yuklemeFormlari.forEach(yuklemeFormunuHazirla);

  // Sayfanin herhangi bir yerine dosya birakilirsa yukleme penceresi acilir.
  let suruklemeDerinligi = 0;
  const dosyaSurukleniyor = (olay) => Array.from(olay.dataTransfer?.types || []).includes('Files');
  function suruklemeBitti() {
    suruklemeDerinligi = 0;
    kok.classList.remove('surukleniyor');
  }
  window.addEventListener('dragenter', (olay) => {
    // Giris/kayit gibi yukleme penceresi olmayan sayfalarda perde gosterilmez.
    if (!yuklemePenceresi || !dosyaSurukleniyor(olay) || yuklemeSuruyor) return;
    suruklemeDerinligi++;
    // Dashboard'daki buyuk alan zaten kendi vurgusunu gosteriyor.
    if (!olay.target.closest?.('[data-birakma]')) kok.classList.add('surukleniyor');
    else kok.classList.remove('surukleniyor');
  });
  window.addEventListener('dragover', (olay) => {
    if (dosyaSurukleniyor(olay)) olay.preventDefault();
  });
  window.addEventListener('dragleave', () => {
    if (--suruklemeDerinligi <= 0) suruklemeBitti();
  });
  window.addEventListener('drop', (olay) => {
    if (!yuklemePenceresi || !dosyaSurukleniyor(olay)) return;
    olay.preventDefault();
    suruklemeBitti();
    const form = $('[data-yukleme-formu]', yuklemePenceresi);
    if (!form || !olay.dataTransfer.files.length || yuklemeSuruyor) return;
    pencereAc(yuklemePenceresi);
    form.dosyaAta(olay.dataTransfer.files);
  });

  // Geri tusuyla onbellekten donulurse formlar ve mesgul butonlar sifirlansin.
  window.addEventListener('pageshow', (olay) => {
    if (!olay.persisted) return;
    yuklemeFormlari.forEach((f) => f.sifirla?.());
    $$('[data-mesgul-sifirla]').forEach(butonuSerbestBirak);
  });

  /* ---------------------------------------------------------------- klavye */
  document.addEventListener('keydown', (olay) => {
    const yaziyor = olay.target.closest?.('input, textarea, select, [contenteditable="true"]');
    const arama = $('#ust-arama');
    if (!arama) return;
    if (olay.key === '/' && !yaziyor) {
      olay.preventDefault();
      arama.focus();
      arama.select();
    }
    if (olay.key === 'Escape' && kok.classList.contains('menu-acik')) mobilMenu(false);
  });

  /* ---------------------------------------------------------------- sayaclar
   Sayilar 0'dan hedef degere sayar (yavaslayarak, ~800 ms); yerel bicimle
   (1.234) yazilir. Hareket azaltildiysa dogrudan son deger. */
  $$('[data-sayac]').forEach((el) => {
    const hedef = Number(el.dataset.sayac) || 0;
    const yaz = (n) => { el.textContent = Math.round(n).toLocaleString('tr'); };
    if (azHareket || !hedef) { yaz(hedef); return; }
    const sure = 800;
    const gecikme = 120 + (Number(getComputedStyle(el.closest('.kart-giris, .bolum-giris') || el).getPropertyValue('--i')) || 0) * 90;
    let bas = null;
    yaz(0);
    const kare = (t) => {
      bas ??= t + gecikme;
      const ilerleme = Math.min(Math.max((t - bas) / sure, 0), 1);
      yaz(hedef * (1 - Math.pow(1 - ilerleme, 4)));
      if (ilerleme < 1) requestAnimationFrame(kare);
    };
    requestAnimationFrame(kare);
  });

  /* ---------------------------------------------------------------- isik kutusu (tam ekran onizleme) */
  const isikKutusu = $('#isik-kutusu');
  if (isikKutusu) {
    const gorsel = $('.isik-gorsel', isikKutusu);
    const yakinlasDugmesi = $('[data-yakinlas]', isikKutusu);

    const yakinlik = (acik, olay) => {
      if (acik && olay) {
        const r = gorsel.getBoundingClientRect();
        gorsel.style.transformOrigin =
          ((olay.clientX - r.left) / r.width) * 100 + '% ' + ((olay.clientY - r.top) / r.height) * 100 + '%';
      } else if (acik) {
        gorsel.style.transformOrigin = '50% 50%';
      }
      gorsel.classList.toggle('yakin', acik);
      yakinlasDugmesi?.setAttribute('aria-pressed', String(acik));
    };

    $$('[data-isik-kutusu-ac]').forEach((d) => d.addEventListener('click', () => {
      yakinlik(false);
      pencereAc(isikKutusu);
    }));
    gorsel.addEventListener('click', (olay) => {
      olay.stopPropagation();
      yakinlik(!gorsel.classList.contains('yakin'), olay);
    });
    // Yakinlastirilmisken fareyle gezinme: odak noktasi imleci takip eder.
    gorsel.addEventListener('mousemove', (olay) => {
      if (!gorsel.classList.contains('yakin')) return;
      const r = gorsel.getBoundingClientRect();
      // r yakinlastirilmis kutu; oranlar olcekten bagimsiz oldugu icin dogrudan kullanilabilir
      gorsel.style.transformOrigin =
        ((olay.clientX - r.left) / r.width) * 100 + '% ' + ((olay.clientY - r.top) / r.height) * 100 + '%';
    });
    yakinlasDugmesi?.addEventListener('click', () => yakinlik(!gorsel.classList.contains('yakin')));
    $('[data-isik-sahne]', isikKutusu).addEventListener('click', (olay) => {
      if (olay.target === olay.currentTarget) pencereKapat(isikKutusu);
    });
  }

  /* ---------------------------------------------------------------- tarama gorunumu
   Mod secildiginde gorsel /tarama/<id>?mod=... ile yenilenir (sayfa yenilenmez).
   Son secilen mod tarayicida hatirlanir. "Once | sonra" filtresiz fotografi
   secili modla ayirici surguyle karsilastirir. */
  const TARAMA_MODU_ANAHTARI = 'tarama_modu';
  $$('[data-tarama]').forEach((bolum) => {
    const segmentler = $$('[data-mod]', bolum);
    if (!segmentler.length) return; // PDF: mod secici yok
    // data-adres icerik surumunu (?v=) tasir; mod en sona eklenir.
    const adres = (mod) => {
      const url = new URL(bolum.dataset.adres, location.href);
      url.searchParams.set('mod', mod);
      return url.pathname + url.search;
    };
    const gorsel = $('[data-tarama-gorsel]', bolum);
    const isikGorsel = $('#isik-kutusu .isik-gorsel');
    const yukleniyor = $('[data-tarama-yukleniyor]', bolum);
    const karsilastirDugmesi = $('[data-karsilastir]', bolum);
    const katman = $('[data-karsilastirma]', bolum);
    const once = $('[data-once]', katman);
    const sonra = $('[data-sonra]', katman);
    const surgu = $('[data-ayirici]', katman);
    const cerceve = gorsel.closest('[data-isik-kutusu-ac]');
    let mod = segmentler.find((s) => s.getAttribute('aria-checked') === 'true')?.dataset.mod || 'renkli';
    let istekNo = 0;

    // Karsilastirmada "sonra" her zaman bir tarama modudur; orijinal seciliyse renkli.
    const sonraModu = () => (mod === 'orijinal' ? 'renkli' : mod);

    const yukle = (img, src) => new Promise((coz) => {
      if (img.src.endsWith(src)) { coz(); return; }
      const on = new Image();
      on.onload = on.onerror = () => { img.src = src; coz(); };
      on.src = src;
    });

    async function sec(yeni, hatirla) {
      mod = yeni;
      segmentler.forEach((s) => s.setAttribute('aria-checked', String(s.dataset.mod === yeni)));
      const no = ++istekNo;
      yukleniyor.hidden = false;
      gorsel.classList.add('degisiyor');
      const isler = [yukle(gorsel, adres(yeni))];
      if (!katman.hidden) isler.push(yukle(sonra, adres(sonraModu())));
      await Promise.all(isler);
      if (no !== istekNo) return; // bu arada baska mod secildi
      gorsel.classList.remove('degisiyor');
      yukleniyor.hidden = true;
      if (isikGorsel) isikGorsel.src = adres(yeni);
      // PDF indir butonu secili tarama moduyla uretir ("orijinal" PDF modu degildir).
      const pdfBagi = $('[data-pdf-indir]');
      if (pdfBagi && yeni !== 'orijinal') {
        const url = new URL(pdfBagi.href, location.href);
        url.searchParams.set('mod', yeni);
        pdfBagi.href = url.pathname + url.search;
        const modAdi = $('[data-pdf-mod-adi]', pdfBagi);
        if (modAdi) modAdi.textContent = '(' + segmentler.find((s) => s.dataset.mod === yeni).textContent.trim() + ')';
      }
      try { history.replaceState(null, '', location.pathname + '?mod=' + yeni + location.hash); } catch (e) { /* yok say */ }
      if (hatirla) kaydet(TARAMA_MODU_ANAHTARI, yeni);
    }

    segmentler.forEach((s) => s.addEventListener('click', (olay) => {
      olay.preventDefault();
      if (s.dataset.mod !== mod) sec(s.dataset.mod, true);
    }));
    // Klavye: ok tuslariyla modlar arasinda gezinme (radiogroup)
    segmentler.forEach((s, i) => s.addEventListener('keydown', (olay) => {
      const yon = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[olay.key];
      if (!yon) return;
      olay.preventDefault();
      const hedef = segmentler[(i + yon + segmentler.length) % segmentler.length];
      hedef.focus();
      sec(hedef.dataset.mod, true);
    }));

    // Adreste mod yoksa son secilen mod uygulanir.
    let kayitli = null;
    try { kayitli = localStorage.getItem(TARAMA_MODU_ANAHTARI); } catch (e) { /* gizli pencere */ }
    const adrestenMod = new URLSearchParams(location.search).get('mod');
    if (!adrestenMod && kayitli && kayitli !== mod && segmentler.some((s) => s.dataset.mod === kayitli)) {
      sec(kayitli, false);
    }

    const ayir = () => katman.style.setProperty('--ayir', surgu.value + '%');
    surgu.addEventListener('input', ayir);
    karsilastirDugmesi.hidden = false;
    karsilastirDugmesi.addEventListener('click', async () => {
      const ac = katman.hidden;
      karsilastirDugmesi.setAttribute('aria-pressed', String(ac));
      if (!ac) {
        katman.hidden = true;
        cerceve.hidden = false;
        return;
      }
      yukleniyor.hidden = false;
      await Promise.all([yukle(once, adres('orijinal')), yukle(sonra, adres(sonraModu()))]);
      yukleniyor.hidden = true;
      surgu.value = 50;
      ayir();
      cerceve.hidden = true;
      katman.hidden = false;
      surgu.focus({ preventScroll: true });
    });
  });

  /* ---------------------------------------------------------------- kose editoru
   Kirpilmamis orijinal fotograf uzerinde 4 surüklenebilir tutamac (fare ve
   dokunmatik: Pointer Events). Koseler gorselin piksel koordinatlarinda tutulur
   (sunucudaki belgeler.koseler ile ayni). Surüklerken buyutec kosenin yakin
   gorunumunu gosterir. Kaydedince sunucu OCR'i yeniden yapar, sayfa yenilenir. */
  const BUYUTEC_KATI = 3;
  $$('[data-kose-editoru]').forEach((editor) => {
    const bolum = editor.closest('[data-tarama]');
    const acDugmesi = $('[data-kose-ac]', bolum);
    const karsilastirDugmesi = $('[data-karsilastir]', bolum);
    const cerceve = $('[data-isik-kutusu-ac]', bolum);
    const katman = $('[data-karsilastirma]', bolum);
    const sahne = $('[data-kose-sahne]', editor);
    const gorsel = $('[data-kose-gorsel]', editor);
    const cizim = $('[data-kose-cizim]', editor);
    const dis = $('.kose-dis', cizim);
    const cizgi = $('.kose-cizgi', cizim);
    const tutamaclar = $$('[data-tutamac]', editor);
    const buyutec = $('[data-buyutec]', editor);
    const mesaj = $('[data-kose-mesaj]', editor);
    const kaydetDugmesi = $('[data-kose-kaydet]', editor);
    const kayitli = JSON.parse(editor.dataset.koseler || 'null');
    let g = 0;
    let y = 0;
    let koseler = [];

    const tumGorsel = () => [[0, 0], [g, 0], [g, y], [0, y]];
    const mesajYaz = (metin, hata) => {
      mesaj.textContent = metin;
      mesaj.classList.toggle('text-rose-600', !!hata);
    };

    function ciz() {
      koseler.forEach(([kx, ky], i) => {
        tutamaclar[i].style.left = (kx / g) * 100 + '%';
        tutamaclar[i].style.top = (ky / y) * 100 + '%';
      });
      cizgi.setAttribute('points', koseler.map((k) => k.join(',')).join(' '));
      // Disari: tum cerceve eksi dortgen (evenodd) yari saydam karartilir.
      dis.setAttribute('d', 'M0 0H' + g + 'V' + y + 'H0Z M' + koseler.map((k) => k.join(' ')).join(' L') + 'Z');
    }

    // Dortgen dis bukey mi? (kesisen / ters donmus koseler kaydedilmez)
    function disBukey() {
      let isaret = 0;
      for (let i = 0; i < 4; i++) {
        const [ax, ay] = koseler[i];
        const [bx, by] = koseler[(i + 1) % 4];
        const [cx, cy] = koseler[(i + 2) % 4];
        const carpim = (bx - ax) * (cy - by) - (by - ay) * (cx - bx);
        if (Math.abs(carpim) < 1e-6) return false;
        if (isaret && Math.sign(carpim) !== isaret) return false;
        isaret = Math.sign(carpim);
      }
      return true;
    }

    async function ac() {
      if (karsilastirDugmesi?.getAttribute('aria-pressed') === 'true') karsilastirDugmesi.click();
      cerceve.hidden = true;
      if (katman) katman.hidden = true;
      if (karsilastirDugmesi) karsilastirDugmesi.disabled = true;
      acDugmesi.setAttribute('aria-pressed', 'true');
      editor.hidden = false;
      if (!gorsel.getAttribute('src')) gorsel.src = editor.dataset.gorsel; // ham gorsel yalnizca gerekince iner
      if (!gorsel.complete || !gorsel.naturalWidth) {
        // Gorsel inene kadar alan cokmesin; tutamaclar gizli, yukleniyor gostergesi acik.
        sahne.classList.add('yukleniyor');
        const yukleniyor = $('[data-tarama-yukleniyor]', bolum);
        yukleniyor.hidden = false;
        const indi = await new Promise((coz) => {
          gorsel.addEventListener('load', () => coz(true), { once: true });
          gorsel.addEventListener('error', () => coz(false), { once: true });
        });
        yukleniyor.hidden = true;
        sahne.classList.remove('yukleniyor');
        if (!indi) {
          mesajYaz('Orijinal görsel yüklenemedi, sayfayı yenileyip tekrar deneyin.', true);
          return;
        }
      }
      g = gorsel.naturalWidth;
      y = gorsel.naturalHeight;
      cizim.setAttribute('viewBox', '0 0 ' + g + ' ' + y);
      sahne.style.aspectRatio = g + ' / ' + y;
      sahne.style.maxWidth = 'calc(70vh * ' + (g / y).toFixed(4) + ')';
      koseler = (kayitli || tumGorsel()).map((k) => [...k]);
      ciz();
      tutamaclar[0].focus({ preventScroll: true });
    }

    function kapat() {
      editor.hidden = true;
      cerceve.hidden = false;
      if (karsilastirDugmesi) karsilastirDugmesi.disabled = false;
      acDugmesi.setAttribute('aria-pressed', 'false');
      buyutec.hidden = true;
    }

    function buyutecGoster(i, dokunmatik) {
      const r = sahne.getBoundingClientRect();
      const [kx, ky] = koseler[i];
      const px = (kx / g) * r.width;
      const py = (ky / y) * r.height;
      const cap = buyutec.offsetWidth || 120;
      buyutec.style.backgroundImage = 'url("' + gorsel.src + '")';
      buyutec.style.backgroundSize = r.width * BUYUTEC_KATI + 'px ' + r.height * BUYUTEC_KATI + 'px';
      buyutec.style.backgroundPosition = cap / 2 - px * BUYUTEC_KATI + 'px ' + (cap / 2 - py * BUYUTEC_KATI) + 'px';
      // Parmagin altinda kalmasin diye dokunmatikte yukarida gosterilir.
      buyutec.style.left = px + 'px';
      buyutec.style.top = py - (dokunmatik ? cap * 0.9 : cap * 0.75) + 'px';
      buyutec.hidden = false;
    }

    tutamaclar.forEach((tutamac, i) => {
      const tasi = (olay) => {
        const r = sahne.getBoundingClientRect();
        const kx = Math.min(Math.max(((olay.clientX - r.left) / r.width) * g, -0.05 * g), 1.05 * g);
        const ky = Math.min(Math.max(((olay.clientY - r.top) / r.height) * y, -0.05 * y), 1.05 * y);
        koseler[i] = [Math.round(kx * 10) / 10, Math.round(ky * 10) / 10];
        ciz();
        buyutecGoster(i, olay.pointerType === 'touch');
      };
      tutamac.addEventListener('pointerdown', (olay) => {
        olay.preventDefault();
        tutamac.setPointerCapture(olay.pointerId);
        tutamac.classList.add('surukleniyor');
        tutamac.focus({ preventScroll: true });
        tasi(olay);
      });
      tutamac.addEventListener('pointermove', (olay) => {
        if (tutamac.hasPointerCapture(olay.pointerId)) tasi(olay);
      });
      const birak = () => {
        tutamac.classList.remove('surukleniyor');
        buyutec.hidden = true;
      };
      tutamac.addEventListener('pointerup', birak);
      tutamac.addEventListener('pointercancel', birak);
      tutamac.addEventListener('keydown', (olay) => {
        const yon = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[olay.key];
        if (!yon) return;
        olay.preventDefault();
        const adim = (olay.shiftKey ? 0.02 : 0.002) * Math.max(g, y);
        koseler[i] = [koseler[i][0] + yon[0] * adim, koseler[i][1] + yon[1] * adim];
        ciz();
      });
    });

    acDugmesi.hidden = false;
    acDugmesi.addEventListener('click', () => (editor.hidden ? ac() : kapat()));
    $('[data-kose-vazgec]', editor).addEventListener('click', kapat);
    $('[data-kose-tumu]', editor).addEventListener('click', () => {
      koseler = tumGorsel();
      ciz();
      mesajYaz('Kırpma kaldırılacak: görselin tamamı kullanılır.');
    });
    $('[data-kose-otomatik]', editor).addEventListener('click', async (olay) => {
      const dugme = olay.currentTarget;
      butonuMesgulYap(dugme, 'Algılanıyor…');
      try {
        const yanit = await fetch(editor.dataset.otomatikAdres, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        const veri = await jsonOku(yanit);
        koseler = veri.koseler || tumGorsel();
        ciz();
        mesajYaz(veri.koseler
          ? (veri.belge ? 'Belge algılandı (güven %' + Math.round(veri.puan * 100) + ').' : 'Belge bulunamadı; yalnızca eğiklik düzeltildi.')
          : 'Belge algılanamadı; görselin tamamı seçildi.');
      } catch (hata) {
        mesajYaz(hata.message, true);
      } finally {
        butonuSerbestBirak(dugme);
      }
    });
    kaydetDugmesi.addEventListener('click', async () => {
      if (!disBukey()) {
        mesajYaz('Köşeler kesişiyor; dört köşe kağıdın köşelerine sırayla (sol üst, sağ üst, sağ alt, sol alt) gelmeli.', true);
        return;
      }
      const tamami = koseler.every(([kx, ky], i) => Math.abs(kx - tumGorsel()[i][0]) < 1 && Math.abs(ky - tumGorsel()[i][1]) < 1);
      const govde = new FormData();
      govde.append('csrf_token', $('input[name="csrf_token"]').value);
      govde.append('koseler', tamami ? '' : JSON.stringify(koseler));
      butonuMesgulYap(kaydetDugmesi, 'Kaydediliyor, metin okunuyor…');
      mesajYaz('Kırpma kaydediliyor ve metin yeniden okunuyor…');
      try {
        const yanit = await fetch(editor.dataset.kaydetAdres, {
          method: 'POST', body: govde, credentials: 'same-origin', headers: { Accept: 'application/json' },
        });
        const veri = await jsonOku(yanit);
        if (!veri.basarili) throw new Error(veri.hata || 'Kaydedilemedi.');
        const parametreler = new URLSearchParams(location.search);
        parametreler.delete('koseler');
        location.replace(location.pathname + (parametreler.toString() ? '?' + parametreler : ''));
      } catch (hata) {
        mesajYaz(hata.message, true);
        butonuSerbestBirak(kaydetDugmesi);
      }
    });

    // Toplu yuklemedeki "Kirpmayi kontrol et" baglantisi editoru acik getirir.
    if (new URLSearchParams(location.search).get('koseler') === '1') ac();
  });

  /* ---------------------------------------------------------------- uretilen dosyalari indirme
   PDF / Word her istekte sunucuda uretildigi icin birkac saniye surebilir.
   JS varken dosya fetch ile alinir, bu sirada butonda bekleme gosterilir;
   JS yokken bag normal indirme bagidir. */
  function dosyaAdi(yanit, varsayilan) {
    const baslik = yanit.headers.get('content-disposition') || '';
    const utf8 = baslik.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8) return decodeURIComponent(utf8[1]);
    const duz = baslik.match(/filename="?([^";]+)"?/i);
    return duz ? duz[1] : varsayilan;
  }

  async function uretilenDosyayiIndir(adres, gosterge, beklemeMetni) {
    if (gosterge.getAttribute('aria-busy') === 'true') return;
    const eski = gosterge.innerHTML;
    gosterge.setAttribute('aria-busy', 'true');
    gosterge.classList.add('pointer-events-none', 'opacity-80');
    gosterge.innerHTML = DONEN_HALKA + '<span>' + beklemeMetni + '</span>';
    try {
      const yanit = await fetch(adres, { credentials: 'same-origin' });
      if (!yanit.ok) throw new Error(yanit.status);
      const blob = await yanit.blob();
      const url = URL.createObjectURL(blob);
      const bag = document.createElement('a');
      bag.href = url;
      bag.download = dosyaAdi(yanit, 'belge');
      document.body.appendChild(bag);
      bag.click();
      bag.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (hata) {
      location.href = adres; // fetch basarisizsa tarayicinin normal indirmesine birak
    } finally {
      gosterge.innerHTML = eski;
      gosterge.removeAttribute('aria-busy');
      gosterge.classList.remove('pointer-events-none', 'opacity-80');
    }
  }

  $$('[data-indir-bekle]').forEach((bag) => {
    bag.addEventListener('click', (olay) => {
      olay.preventDefault();
      const menu = bag.closest('details');
      if (menu) menu.open = false;
      // Menudeki secenek de ana PDF butonunda bekleme gosterir.
      const gosterge = menu ? $('[data-pdf-indir]') || bag : bag;
      uretilenDosyayiIndir(bag.href, gosterge, bag.dataset.bekleme || 'PDF hazırlanıyor…');
    });
  });

  // Acik PDF menusu disari tiklayinca ya da Esc ile kapanir.
  document.addEventListener('click', (olay) => {
    $$('details.pdf-menu[open]').forEach((menu) => { if (!menu.contains(olay.target)) menu.open = false; });
  });
  document.addEventListener('keydown', (olay) => {
    if (olay.key === 'Escape') $$('details.pdf-menu[open]').forEach((menu) => { menu.open = false; });
  });

  /* ---------------------------------------------------------------- coklu secim ve PDF birlestirme
   "Sec" modunda kart tiklamasi gezinmek yerine secer; secim sirasi kartta
   numara olarak gorunur ve PDF'teki sirayi belirler. */
  const secimCubugu = $('[data-secim-cubugu]');
  if (secimCubugu) {
    const acDugmesi = $('[data-secim-ac]');
    const sayac = $('[data-secim-sayisi]', secimCubugu);
    const birlestir = $('[data-birlestir]', secimCubugu);
    const hataKutusu = $('[data-secim-hata]', secimCubugu);
    const sinir = Number(secimCubugu.dataset.sinir); // app.py PDF_BIRLESTIRME_SINIRI
    let secilenler = [];
    const kartlar = () => $$('.belge-karti[data-belge-id]');

    const hata = (mesaj) => { hataKutusu.textContent = mesaj; hataKutusu.hidden = !mesaj; };

    function guncelle() {
      kartlar().forEach((kart) => {
        const sira = secilenler.indexOf(kart.dataset.belgeId);
        kart.toggleAttribute('data-secili', sira >= 0);
        kart.dataset.sira = sira >= 0 ? String(sira + 1) : '';
        kart.setAttribute('aria-pressed', String(sira >= 0));
      });
      sayac.textContent = secilenler.length;
      const fazla = secilenler.length > sinir;
      birlestir.disabled = !secilenler.length || fazla;
      hata(fazla ? 'Tek seferde en fazla ' + sinir + ' belge birleştirilebilir; ' + secilenler.length + ' belge seçtiniz.' : '');
    }

    function secimModu(acik) {
      kok.classList.toggle('secim-modu', acik);
      secimCubugu.hidden = !acik;
      acDugmesi.setAttribute('aria-pressed', String(acik));
      kartlar().forEach((kart) => {
        if (acik) kart.setAttribute('role', 'button'); else { kart.removeAttribute('role'); kart.removeAttribute('aria-pressed'); }
      });
      if (!acik) secilenler = [];
      guncelle();
    }

    acDugmesi.hidden = false;
    acDugmesi.addEventListener('click', () => secimModu(!kok.classList.contains('secim-modu')));
    $('[data-secim-kapat]', secimCubugu).addEventListener('click', () => secimModu(false));
    $('[data-secimi-temizle]', secimCubugu).addEventListener('click', () => { secilenler = []; guncelle(); });
    $('[data-tumunu-sec]', secimCubugu).addEventListener('click', () => {
      kartlar().forEach((kart) => { if (!secilenler.includes(kart.dataset.belgeId)) secilenler.push(kart.dataset.belgeId); });
      guncelle();
    });

    // Yakalama asamasinda: secim modunda karta tiklamak baglantiyi acmaz.
    document.addEventListener('click', (olay) => {
      if (!kok.classList.contains('secim-modu')) return;
      const kart = olay.target.closest?.('.belge-karti[data-belge-id]');
      if (!kart) return;
      olay.preventDefault();
      const id = kart.dataset.belgeId;
      secilenler = secilenler.includes(id) ? secilenler.filter((s) => s !== id) : secilenler.concat(id);
      guncelle();
    }, true);
    document.addEventListener('keydown', (olay) => {
      if (olay.key === 'Escape' && kok.classList.contains('secim-modu') && !document.querySelector('dialog[open]')) secimModu(false);
    });

    secimCubugu.addEventListener('submit', async (olay) => {
      olay.preventDefault();
      if (!secilenler.length || secilenler.length > sinir) return;
      const govde = new FormData(secimCubugu); // csrf_token + mod
      secilenler.forEach((id) => govde.append('belge', id));
      butonuMesgulYap(birlestir, 'PDF hazırlanıyor (' + secilenler.length + ' belge)…');
      hata('');
      try {
        const yanit = await fetch(secimCubugu.action, {
          method: 'POST', body: govde, credentials: 'same-origin',
          headers: { Accept: 'application/pdf, application/json' },
        });
        if ((yanit.headers.get('content-type') || '').includes('application/json')) {
          throw new Error((await yanit.json()).hata || 'PDF oluşturulamadı.');
        }
        if (!yanit.ok) throw new Error('PDF oluşturulamadı (' + yanit.status + ').');
        const url = URL.createObjectURL(await yanit.blob());
        const bag = document.createElement('a');
        bag.href = url;
        bag.download = dosyaAdi(yanit, 'arsiv_birlesik.pdf');
        document.body.appendChild(bag);
        bag.click();
        bag.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
      } catch (e) {
        hata(e.message);
      } finally {
        butonuSerbestBirak(birlestir);
        birlestir.disabled = !secilenler.length;
      }
    });
  }

  /* ---------------------------------------------------------------- silme onayi */
  const silPenceresi = $('#sil-penceresi');
  $$('form[data-onay]').forEach((form) => {
    form.addEventListener('submit', (olay) => {
      if (!silPenceresi) return;
      olay.preventDefault();
      pencereAc(silPenceresi);
      silPenceresi.hedefForm = form;
    });
  });
  $('[data-onayla]', silPenceresi || document.createElement('div'))?.addEventListener('click', (olay) => {
    const form = silPenceresi.hedefForm;
    if (!form) return;
    butonuMesgulYap(olay.currentTarget, 'Siliniyor…');
    form.submit();
  });

  /* ---------------------------------------------------------------- tur duzeltme */
  $$('[data-tur-formu]').forEach((form) => {
    const kaydetDugmesi = $('[data-kaydet]', form);
    const ilk = $('input[name="tur"]:checked', form)?.value;
    const guncelle = () => {
      kaydetDugmesi.disabled = $('input[name="tur"]:checked', form)?.value === ilk;
    };
    form.addEventListener('change', guncelle);
    guncelle();
    form.addEventListener('submit', () => butonuMesgulYap(kaydetDugmesi, 'Kaydediliyor…'));
  });

  /* ---------------------------------------------------------------- mevcut belgelerden bilgi cikarma
   Sunucu her istekte bir belge isler; tarayici sirayla ilerleyip durumu gosterir.
   son_id imleci basarisiz belgenin tekrar tekrar denenmesini onler. */
  $$('[data-bilgi-cikar]').forEach((form) => {
    const dugme = $('button[type="submit"]', form);
    const durum = $('[data-bilgi-durum]', form);
    const cubuk = $('[data-bilgi-cubuk]', form);
    const dolgu = $('[data-bilgi-dolgu]', form);
    const toplam = Number(form.dataset.toplam) || 0;

    const ilerleme = (bitti) => {
      const yuzde = toplam ? Math.round((bitti / toplam) * 100) : 100;
      dolgu.style.width = yuzde + '%';
      cubuk.setAttribute('aria-valuenow', String(yuzde));
    };

    form.addEventListener('submit', async (olay) => {
      olay.preventDefault();
      butonuMesgulYap(dugme, 'Çıkarılıyor…');
      cubuk.hidden = false;
      ilerleme(0);
      let sonId = 0, islenen = 0, hatali = 0, yogunDeneme = 0, kalan = toplam;
      try {
        while (kalan > 0) {
          durum.textContent = (toplam - kalan + 1) + ' / ' + toplam + ' belge işleniyor…';
          const govde = new FormData(form);
          govde.set('son_id', String(sonId));
          const yanit = await fetch(form.action, {
            method: 'POST', body: govde, credentials: 'same-origin',
            headers: { Accept: 'application/json' },
          });
          const veri = await jsonOku(yanit);
          if (veri.yogun) {
            // Groq hiz siniri: birkac saniye bekleyip ayni belgeyi bir kez daha dene.
            if (yogunDeneme++ >= 1) throw new Error('Şu an yoğunluk var, biraz sonra devam edin.');
            durum.textContent = 'Şu an yoğunluk var, birkaç saniye bekleniyor…';
            await bekle(GROQ_BEKLEME_MS);
            continue;
          }
          yogunDeneme = 0;
          sonId = veri.son_id;
          islenen += veri.islenen;
          hatali += veri.hatali;
          kalan = veri.kalan;
          ilerleme(toplam - kalan);
          if (kalan > 0) await bekle(ISTEK_ARALIGI_MS);
        }
        durum.textContent = islenen + ' belgeden bilgi çıkarıldı' + (hatali ? ', ' + hatali + ' belgede hata oluştu.' : '.');
        butonuSerbestBirak(dugme);
        dugme.disabled = true;
      } catch (hata) {
        durum.textContent = (islenen ? islenen + ' belge işlendi. ' : '') + hata.message;
        butonuSerbestBirak(dugme);
      }
    });
  });

  /* ---------------------------------------------------------------- giris / kayit / hesap formlari */
  $$('[data-sifre-goster]').forEach((dugme) => {
    const girdi = dugme.parentElement.querySelector('input');
    dugme.addEventListener('click', () => {
      const goster = girdi.type === 'password';
      girdi.type = goster ? 'text' : 'password';
      dugme.setAttribute('aria-pressed', String(goster));
      dugme.setAttribute('aria-label', goster ? 'Şifreyi gizle' : 'Şifreyi göster');
      dugme.classList.toggle('text-marka-600', goster);
    });
  });

  $$('[data-kimlik-formu]').forEach((form) => {
    form.addEventListener('submit', () => {
      const dugme = $('button[type="submit"]', form);
      if (dugme) butonuMesgulYap(dugme, 'Lütfen bekleyin…');
    });
  });

  /* ---------------------------------------------------------------- OCR metni */
  $$('[data-ocr]').forEach((kap) => {
    const kutu = $('.ocr-kutu', kap);
    const dugme = $('[data-ocr-ac]', kap);
    const kapaliYukseklik = 176;
    if (!kutu || !dugme) return;

    if (kutu.scrollHeight <= kapaliYukseklik + 24) {
      kutu.classList.add('acik');
      dugme.hidden = true;
    } else {
      kutu.style.maxHeight = kapaliYukseklik + 'px';
    }
    dugme.addEventListener('click', () => {
      const acik = !kutu.classList.contains('acik');
      kutu.classList.toggle('acik', acik);
      kutu.style.maxHeight = (acik ? kutu.scrollHeight : kapaliYukseklik) + 'px';
      dugme.setAttribute('aria-expanded', String(acik));
      $('[data-ocr-etiket]', dugme).textContent = acik ? 'Daralt' : 'Tamamını göster';
    });
  });

  $$('[data-kopyala]').forEach((dugme) => {
    dugme.addEventListener('click', async () => {
      const kaynak = document.getElementById(dugme.dataset.kopyala);
      const etiket = $('[data-kopyala-etiket]', dugme);
      try {
        await navigator.clipboard.writeText(kaynak.textContent);
        etiket.textContent = 'Kopyalandı';
      } catch (e) {
        etiket.textContent = 'Kopyalanamadı';
      }
      dugme.classList.add('text-turkuaz-600');
      setTimeout(() => {
        etiket.textContent = 'Kopyala';
        dugme.classList.remove('text-turkuaz-600');
      }, 1800);
    });
  });

  /* ---------------------------------------------------------------- tarayici algilama
   Bagli tarayicilar birkac saniyede bir sorulur (sekme gizliyken durur). Yeni
   tarayici takilinca bu sekmede "Tarayici bulundu" bildirimi cikar; "Tara"
   dugmeleri yalnizca tarayici bagliyken gorunur. Bildirilen tarayicilar
   sekmeye ozel (sessionStorage) tutulur: sayfa degisince yeniden bildirilmez,
   cikarilip yeniden takilinca bildirilir. */
  const tarayiciDinleyicileri = [];
  let taramaSuruyor = false;
  let tarayicilariHemenSor = () => {};
  if (TARAYICI_ADRESI) {
    const BILINEN_ANAHTARI = 'bilinenTarayicilar';
    let bilinen = [];
    try { bilinen = JSON.parse(sessionStorage.getItem(BILINEN_ANAHTARI) || '[]'); } catch (e) { /* yok */ }
    const taraSayfasindaMi = () => Boolean($('[data-tara-sayfasi]'));

    const tarayiciBildir = (ad) => {
      const sablon = $('#tarayici-bildirim-sablonu');
      const kap = $('[data-bildirimler]');
      if (!sablon || !kap) return;
      const bildirim = sablon.content.firstElementChild.cloneNode(true);
      $('[data-ad]', bildirim).textContent = ad;
      $('[data-bildirim-kapat]', bildirim).addEventListener('click', () => bildirimKapat(bildirim));
      $('.bildirim-sure', bildirim).addEventListener('animationend', () => bildirimKapat(bildirim));
      kap.append(bildirim);
    };

    const dugmeleriGuncelle = (bagli, liste = []) => {
      $$('[data-tara-menu], [data-tara-baglantisi]').forEach((el) => {
        if (el.getAttribute('aria-current') !== 'page') el.hidden = !bagli;
      });
      // Panel'deki tarayici bilgi kutusu: bagli mi, hangi tarayici.
      const kart = $('[data-tarayici-karti]');
      if (kart) {
        kart.dataset.durum = bagli ? 'bagli' : 'yok';
        $('[data-tarayici-ozet]', kart).textContent = liste.length > 1 ? liste.length + ' tarayıcı bağlı' : bagli ? 'Bağlı' : 'Bağlı değil';
        $('[data-tarayici-ad]', kart).textContent = bagli ? liste.map((t) => t.ad).join(', ') : 'Tarayıcıyı bilgisayara bağlayıp açın';
        const tara = $('[data-tarayici-tara]', kart);
        if (tara) tara.hidden = !bagli;
      }
      const dugme = $('[data-tara-dugmesi]');
      if (dugme && !taraSayfasindaMi()) dugme.hidden = !bagli;
      if (!bagli) $$('[data-tarayici-bildirimi]').forEach(bildirimKapat);
    };

    let zamanlayici = null;
    const planla = (ms) => {
      clearTimeout(zamanlayici);
      if (!document.hidden) zamanlayici = setTimeout(sor, ms ?? (taramaSuruyor ? 1000 : 3000));
    };
    async function sor() {
      try {
        const yanit = await fetch(TARAYICI_ADRESI, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        const veri = await jsonOku(yanit);
        const liste = veri.tarayicilar || [];
        if (!taraSayfasindaMi()) liste.filter((t) => !bilinen.includes(t.id)).forEach((t) => tarayiciBildir(t.ad));
        bilinen = liste.map((t) => t.id);
        try { sessionStorage.setItem(BILINEN_ANAHTARI, JSON.stringify(bilinen)); } catch (e) { /* gizli pencere */ }
        dugmeleriGuncelle(liste.length > 0, liste);
        tarayiciDinleyicileri.forEach((dinleyici) => dinleyici(veri));
      } catch (hata) { /* ag hatasi ya da oturum dustu: bir sonraki turda yeniden denenir */ }
      planla();
    }
    tarayicilariHemenSor = () => planla(0);
    document.addEventListener('visibilitychange', () => planla(0));
    planla(0);
  }

  /* ---------------------------------------------------------------- tarama (tara.html)
   "Tara" / "Sonraki sayfa" / "Bitir" / "Vazgec" istekleri fetch ile gider;
   tarama surerken form yerine buyuk bir ilerleme paneli gorunur. Besleyiciden
   gelen sayfa sayisi durum yoklamasindan okunur. Belge olusunca sayfasina gidilir. */
  const taraSayfasi = $('[data-tara-sayfasi]');
  const taraFormu = $('[data-tara-formu]');
  if (taraSayfasi) {
    const ilerlemePaneli = $('[data-tara-ilerleme]', taraSayfasi);
    const hataKutusu = $('[data-tara-hata]', taraSayfasi);
    let bekleyenSayfa = Number($('[data-tara-sayfa-sayisi]', taraSayfasi)?.textContent || 0);
    let bitiriliyor = false;

    const ilerlemeYaz = (baslik, metin) => {
      $('[data-tara-ilerleme-baslik]', ilerlemePaneli).textContent = baslik;
      $('[data-tara-ilerleme-metin]', ilerlemePaneli).textContent = metin;
    };
    const hataGoster = (mesaj) => {
      $('[data-tara-hata-metin]', hataKutusu).textContent = mesaj;
      hataKutusu.hidden = !mesaj;
    };
    const durumuGoster = (sayi) => {
      bekleyenSayfa = sayi;
      $('[data-tara-basla]', taraFormu).hidden = sayi > 0;
      $('[data-tara-sonraki]', taraFormu).hidden = sayi === 0;
      $('[data-tara-sayfa-sayisi]', taraFormu).textContent = sayi;
    };

    tarayiciDinleyicileri.push((veri) => {
      if (taramaSuruyor) {
        const alinan = veri.ilerleme?.sayfa || 0;
        if (!bitiriliyor && alinan > 0) ilerlemeYaz('Taranıyor…', alinan + '. sayfa alındı, devam ediyor…');
        return;
      }
      // Tarayici takildi ya da cikarildi: sayfa guncel haliyle yeniden acilir.
      if ((veri.tarayicilar || []).length !== Number(taraSayfasi.dataset.tarayiciSayisi)) location.reload();
    });

    taraFormu?.addEventListener('submit', async (olay) => {
      olay.preventDefault();
      if (taramaSuruyor) return;
      const dugme = olay.submitter;
      const adres = dugme?.getAttribute('formaction') || taraFormu.action;
      const iptal = dugme?.hasAttribute('data-tara-iptal');
      bitiriliyor = Boolean(dugme?.hasAttribute('data-tara-bitir'));
      hataGoster('');
      taramaSuruyor = true;
      if (!iptal) {
        if (bitiriliyor) ilerlemeYaz('Belge hazırlanıyor…', bekleyenSayfa + ' sayfa tek belge olarak kaydediliyor.');
        else ilerlemeYaz('Taranıyor…', bekleyenSayfa ? (bekleyenSayfa + 1) + '. sayfa taranıyor, lütfen bekleyin.'
                                                      : 'Tarayıcı çalışıyor, lütfen bekleyin.');
        taraFormu.hidden = true;
        ilerlemePaneli.hidden = false;
        tarayicilariHemenSor();
      }
      let gidiliyor = false;
      try {
        const yanit = await fetch(adres, {
          method: 'POST', body: new FormData(taraFormu), credentials: 'same-origin', headers: { Accept: 'application/json' },
        });
        const veri = await jsonOku(yanit);
        if (veri.adres) {
          gidiliyor = true;
          ilerlemeYaz('Tamamlandı', 'Belge açılıyor…');
          location.href = veri.adres;
          return;
        }
        if (veri.hata) hataGoster(veri.hata);
        durumuGoster(veri.sayfa_sayisi || 0);
      } catch (hata) {
        hataGoster(hata.message.startsWith('Oturumunuz') ? hata.message
                                                         : 'Bir sorun oluştu. Sayfayı yenileyip yeniden deneyin.');
      } finally {
        if (!gidiliyor) {
          taramaSuruyor = false;
          ilerlemePaneli.hidden = true;
          taraFormu.hidden = false;
        }
      }
    });
  }

  /* ---------------------------------------------------------------- tarama klasorleri (klasorler.html)
   "Taradigim belgeler gorunmuyor": kullanici bir sayfa tarar, son dakikalarda
   olusan dosyalar onizlemeleriyle gosterilir; "Evet, bu" o klasoru ekler.
   "Klasoru kendim secegim": sunucu bilgisayarinin klasorleri pencerede gezilir.
   Klasorde dosya varsa "hepsi mi, bundan sonrakiler mi?" sorulur. */
  const klasorBul = $('[data-klasor-bul]');
  if (klasorBul) {
    const csrf = $('[data-klasor-csrf]', klasorBul).value;
    const hataKutusu = $('[data-klasor-hata]', klasorBul);
    const getirJson = async (adres, govde) => {
      const yanit = await fetch(adres, {
        method: govde ? 'POST' : 'GET', body: govde, credentials: 'same-origin', headers: { Accept: 'application/json' },
      });
      const veri = await jsonOku(yanit);
      if (veri.hata) throw new Error(veri.hata);
      return veri;
    };
    const sadeHata = (hata) => (hata instanceof TypeError || hata.message.startsWith('Sunucu')
      ? 'Bir sorun oluştu. Sayfayı yenileyip yeniden deneyin.' : hata.message);
    const hataGoster = (mesaj) => {
      $('[data-klasor-hata-metin]', hataKutusu).textContent = mesaj || '';
      hataKutusu.hidden = !mesaj;
    };
    const adimaGec = (ad) => {
      $$('[data-adim]', klasorBul).forEach((el) => { el.hidden = el.dataset.adim !== ad; });
      hataGoster('');
    };

    // Klasoru ekler; dosya varsa once sorar. secim: {anahtar} ya da {yol}.
    let bekleyenSecim = null;
    async function ekle(secim, mevcutlar) {
      const govde = new FormData();
      govde.append('csrf_token', csrf);
      Object.entries(secim).forEach(([k, v]) => govde.append(k, v));
      if (mevcutlar) govde.append('mevcutlar', mevcutlar);
      try {
        const veri = await getirJson(klasorBul.dataset.ekleAdresi, govde);
        if (veri.soru) {
          bekleyenSecim = secim;
          $('[data-soru-sayi]', klasorBul).textContent = veri.sayi;
          $('[data-soru-yol]', klasorBul).textContent = veri.yol;
          adimaGec('soru');
          return;
        }
        location.href = veri.adres;
      } catch (hata) { hataGoster(sadeHata(hata)); }
    }
    $$('[data-mevcutlar]', klasorBul).forEach((dugme) => dugme.addEventListener('click', () => {
      if (bekleyenSecim) ekle(bekleyenSecim, dugme.dataset.mevcutlar);
    }));

    // -- son taranan belgeyi bulma
    async function ara() {
      adimaGec('araniyor');
      try {
        const veri = await getirJson(klasorBul.dataset.araAdresi);
        if (!veri.dosyalar.length) { adimaGec('yok'); return; }
        const liste = $('[data-sonuc-listesi]', klasorBul);
        const sablon = $('#bulunan-dosya');
        liste.replaceChildren(...veri.dosyalar.map((dosya) => {
          const oge = sablon.content.firstElementChild.cloneNode(true);
          $('[data-onizleme]', oge).src = dosya.onizleme;
          $('[data-onizleme]', oge).alt = dosya.ad;
          $('[data-ad]', oge).textContent = dosya.ad;
          $('[data-klasor]', oge).textContent = dosya.klasor;
          $('[data-bu]', oge).addEventListener('click', () => ekle({ anahtar: dosya.anahtar }));
          return oge;
        }));
        adimaGec('sonuc');
      } catch (hata) {
        adimaGec('tara');
        hataGoster(sadeHata(hata));
      }
    }
    $$('[data-bul-basla]', klasorBul).forEach((d) => d.addEventListener('click', () => adimaGec('tara')));
    $$('[data-bul-ara]', klasorBul).forEach((d) => d.addEventListener('click', ara));
    $$('[data-bul-vazgec]', klasorBul).forEach((d) => d.addEventListener('click', () => adimaGec('bas')));
    if (klasorBul.dataset.hemen) adimaGec('tara');

    // -- klasor gezgini
    const gezgin = $('[data-klasor-gezgini]');
    const gezginListe = $('[data-gezgin-liste]', gezgin);
    const gezginHata = $('[data-gezgin-hata]', gezgin);
    const secDugmesi = $('[data-gezgin-sec]', gezgin);
    let gezginDurum = { yol: null, ust: null };

    const satir = (ad, tiklaninca) => {
      const oge = $('#gezgin-satiri').content.firstElementChild.cloneNode(true);
      $('[data-ad]', oge).textContent = ad;
      $('[data-gezgin-oge]', oge).addEventListener('click', tiklaninca);
      return oge;
    };
    async function gez(yol) {
      gezginHata.hidden = true;
      try {
        const veri = await getirJson(klasorBul.dataset.gezAdresi + (yol ? '?yol=' + encodeURIComponent(yol) : ''));
        gezginDurum = veri;
        $('[data-gezgin-yol]', gezgin).textContent = veri.yol || 'Bu bilgisayar';
        $('[data-gezgin-geri]', gezgin).disabled = !veri.yol;
        secDugmesi.disabled = !veri.yol;
        const ogeler = [
          ...veri.kisayollar.map((k) => satir(k.ad, () => gez(k.yol))),
          ...veri.suruculer.map((s) => satir(s.ad + ' sürücüsü', () => gez(s.yol))),
          ...veri.klasorler.map((k) => satir(k.ad, () => gez(k.yol))),
        ];
        if (!ogeler.length) {
          const bos = document.createElement('li');
          bos.className = 'px-4 py-6 text-center text-sm text-metin-3';
          bos.textContent = 'Bu klasörün içinde başka klasör yok.';
          ogeler.push(bos);
        }
        gezginListe.replaceChildren(...ogeler);
        gezginListe.scrollTop = 0;
      } catch (hata) {
        gezginHata.textContent = sadeHata(hata);
        gezginHata.hidden = false;
      }
    }
    $('[data-gezgin-geri]', gezgin).addEventListener('click', () => {
      if (gezginDurum.yol) gez(gezginDurum.ust || null);
    });
    secDugmesi.addEventListener('click', () => {
      if (!gezginDurum.yol) return;
      pencereKapat(gezgin);
      ekle({ yol: gezginDurum.yol });
    });
    $$('[data-gezgin-ac]', klasorBul).forEach((d) => d.addEventListener('click', () => {
      pencereAc(gezgin);
      gez(null);
    }));
  }

  $$('[data-klasor-kaldir]').forEach((dugme) => dugme.form.addEventListener('submit', (olay) => {
    if (!confirm('Bu klasör artık izlenmesin mi? İçindeki dosyalar silinmez.')) olay.preventDefault();
  }));
})();
