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
  const daraltDugmesi = $('[data-kenar-daralt]');
  function daraltEtiketiniGuncelle() {
    if (!daraltDugmesi) return;
    const dar = kok.classList.contains('kenar-dar');
    daraltDugmesi.setAttribute('aria-label', dar ? 'Menüyü genişlet' : 'Menüyü daralt');
    daraltDugmesi.setAttribute('aria-expanded', String(!dar));
  }
  daraltEtiketiniGuncelle();
  daraltDugmesi?.addEventListener('click', () => {
    const dar = kok.classList.toggle('kenar-dar');
    kaydet('kenar', dar ? 'dar' : 'genis');
    ipucuGizle();
    daraltEtiketiniGuncelle();
  });

  const menuAcDugmesi = $('[data-menu-ac]');
  function mobilMenu(acik) {
    kok.classList.toggle('menu-acik', acik);
    menuAcDugmesi?.setAttribute('aria-expanded', String(acik));
    if (acik) $('#kenar-menu a[aria-current], #kenar-menu a')?.focus({ preventScroll: true });
  }
  menuAcDugmesi?.addEventListener('click', () => mobilMenu(true));
  $$('[data-menu-kapat]').forEach((el) => el.addEventListener('click', () => mobilMenu(false)));
  $$('#kenar-menu a').forEach((a) => a.addEventListener('click', () => mobilMenu(false)));

  // Daraltilmis menude oge adlari ipucu olarak gosterilir. Menu kaydirilabilir
  // oldugu icin ipucu menunun icinde degil, sabit konumlu ayri bir katmanda cizilir.
  const ipucu = document.createElement('div');
  ipucu.className = 'ipucu';
  ipucu.setAttribute('role', 'tooltip');
  document.body.appendChild(ipucu);
  function ipucuGizle() { ipucu.classList.remove('gorunur'); }
  $$('#kenar-menu [data-ipucu]').forEach((el) => {
    const goster = () => {
      if (!kok.classList.contains('kenar-dar') || window.innerWidth < 1024) return;
      const r = el.getBoundingClientRect();
      ipucu.textContent = el.dataset.ipucu;
      ipucu.style.top = r.top + r.height / 2 + 'px';
      ipucu.style.left = r.right + 12 + 'px';
      ipucu.classList.add('gorunur');
    };
    el.addEventListener('mouseenter', goster);
    el.addEventListener('focus', goster);
    el.addEventListener('mouseleave', ipucuGizle);
    el.addEventListener('blur', ipucuGizle);
  });
  $('#kenar-menu nav')?.addEventListener('scroll', ipucuGizle, { passive: true });

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
      if (el) el.textContent = adet;
    });
    const not = $('[data-isleniyor-bilgisi]');
    if (not) {
      not.hidden = !veri.isleniyor;
      $('[data-isleniyor-sayisi]', not).textContent = veri.isleniyor;
    }
  }

  // Listelerdeki islenmekte olan kartlar: biten kart, sayfanin guncel halinden
  // alinan yenisiyle degistirilir (kaydirma, acik pencere ve formlar korunur).
  const bekleyenKartlar = () => $$('.belge-karti[data-isleniyor]').map((k) => k.dataset.belgeId);
  if (bekleyenKartlar().length) {
    yoklayici(bekleyenKartlar, async (veri) => {
      sayaclariGuncelle(veri);
      const biten = Object.entries(veri.belgeler || {}).filter(([, d]) => !islenmekte(d.durum)).map(([id]) => id);
      if (!biten.length) return;
      const yanit = await fetch(location.href, { credentials: 'same-origin' });
      const yeni = new DOMParser().parseFromString(await yanit.text(), 'text/html');
      biten.forEach((id) => {
        const eski = $('.belge-karti[data-belge-id="' + id + '"]');
        const guncel = $('.belge-karti[data-belge-id="' + id + '"]', yeni);
        if (!eski) return;
        if (!guncel) { eski.removeAttribute('data-isleniyor'); return; }
        guncel.classList.remove('kart-giris');
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
      if (d && !islenmekte(d.durum)) location.reload();
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
    if ((olay.key === '/' && !yaziyor) || ((olay.ctrlKey || olay.metaKey) && olay.key.toLowerCase() === 'k')) {
      olay.preventDefault();
      arama.focus();
      arama.select();
    }
    if (olay.key === 'Escape' && kok.classList.contains('menu-acik')) mobilMenu(false);
  });

  /* ---------------------------------------------------------------- sayaclar */
  function sayacCalistir(el, hedef) {
    if (azHareket || hedef === 0) { el.textContent = hedef.toLocaleString('tr'); return; }
    const sure = Math.min(200, 120 + hedef * 4); // sayfa acilisini bekletmesin
    const bas = performance.now();
    const adim = (simdi) => {
      const t = Math.min((simdi - bas) / sure, 1);
      const yumusak = 1 - Math.pow(1 - t, 3);
      el.textContent = Math.round(hedef * yumusak).toLocaleString('tr');
      if (t < 1) requestAnimationFrame(adim);
    };
    requestAnimationFrame(adim);
  }
  $$('[data-sayac]').forEach((el) => sayacCalistir(el, Number(el.dataset.sayac) || 0));

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
})();
