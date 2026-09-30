"""Tarama klasorunun izlenmesi: tarayicinin kaydettigi dosyalar otomatik olarak
alinir, siniflandirilir ve arsivlenir (normal yuklemeyle ayni kuyruk, isleme.py).

Ayarlar (.env):
    TARAMA_KLASORU               izlenecek klasor (or. C:\\ArcBase\\Tarama); bossa kapali
    TARAMA_VARSAYILAN_KULLANICI  koke dusen dosyalarin sahibi; bossa yoneticinin
                                 "Gelen belgeler" kutusuna gider

Klasor yapisi:
    Tarama\\                    kok: sahibi belli olmayan dosyalar
    Tarama\\<kullanici_adi>\\    o kullanicinin dosyalari (kayitta olusturulur)
    <klasor>\\islendi\\YYYY-AA-GG\\  alinan dosyalar buraya tasinir
    <klasor>\\hata\\             alinamayanlar; yaninda nedenini yazan .hata.txt
Hicbir dosya silinmez. "islendi" ve "hata" adli alt klasorler kullanici sayilmaz.

Yarim yazilmis dosya alinmaz: boyutu ve degisiklik zamani KARARLILIK_SN boyunca
sabit kalmalidir. Klasor watchdog ile izlenir; ag paylasiminda olaylar
kacabildigi icin ayrica birkac saniyede bir yoklanir (watchdog yoksa yalnizca
yoklama). Dosya once islendi\\ altina tasinir, sonra kuyruga eklenir: ayni
dosyayi iki surec (gunicorn worker) alamaz, tasima basarisizsa hicbir sey
eklenmez. Kuyruga ekleme basarisiz olursa dosya yerine geri konur.

Desteklenen turler: JPG, PNG, PDF ve TIFF. Tek sayfali TIFF kayipsiz PNG'ye,
cok sayfali TIFF tek belge olarak PDF'e cevrilir.

Windows'un varsayilan tarama klasorleri (VarsayilanKlasorIzleyici): Windows
Faks ve Tarama'nin ve yaygin tarayici yazilimlarinin kayit klasorleri
(Belgeler\\Scanned Documents, Resimler\\Scans ...) ayar gerekmeden izlenir
(Windows'ta varsayilan acik; kapatmak icin VARSAYILAN_TARAMA_KLASORLERI=0).
Klasor sonradan olusursa kendiliginden izlenmeye baslar. Dosyalar, ArcBase'te
tek kullanici varsa onun arsivine, birden fazla varsa yoneticinin "Gelen
belgeler" kutusuna gider (TARAMA_VARSAYILAN_KULLANICI tanimliysa ona). Alinan
dosya silinmez, "ArcBase'e aktarıldı" alt klasorune tasinir; alinamayan
"ArcBase'e aktarılamadı" klasorune. Desteklenmeyen turdeki dosyalara
(kullanicinin kendi belgeleri olabilir) hic dokunulmaz.
"""

import io
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageSequence

import database
import isleme
import izlenen_klasorler as izlenen_klasorler_deposu
import tarama_gunlugu

log = logging.getLogger("dijital_arsiv.klasor")

TURLER = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
ISLENDI, HATA = "islendi", "hata"
AKTARILDI, AKTARILAMADI = "ArcBase'e aktarıldı", "ArcBase'e aktarılamadı"
AYRILMIS_KLASORLER = {ISLENDI, HATA, AKTARILDI.lower(), AKTARILAMADI.lower()}
# Tarayici/Windows'un gecici ve yardimci dosyalari: hic dokunulmaz.
YOKSAYILAN_UZANTILAR = {".tmp", ".part", ".partial", ".crdownload", ".download", ".lock"}
YOKSAYILAN_ADLAR = {"thumbs.db", "desktop.ini", ".ds_store"}

KARARLILIK_SN = 3.0  # dosya bu kadar degismeden durmali
YOKLAMA_SN = 5.0  # watchdog olayi gelmese de klasor bu aralikla taranir
BEKLEYEN_YOKLAMA_SN = 1.0  # kararlilik beklenen dosya varken
OLAY_BEKLEMESI_SN = 0.5  # klasor olayindan sonra taramadan once kisa bekleme
MAKS_GORSEL_BOYUTU = 10 * 1024 * 1024  # tarayicidan yuklemeyle ayni sinirlar (app.py)
MAKS_PDF_BOYUTU = 5 * 1024 * 1024
TIFF_PDF_UZUN_KENAR = 2480  # cok sayfali TIFF -> PDF: A4 ~300 DPI
TIFF_PDF_KALITESI = 85


class DosyaHatasi(Exception):
    """Dosya alinamaz; mesaj hata\\ klasorundeki .hata.txt'ye yazilir."""


def etkin():
    """TARAMA_KLASORU tanimli ve arka plan iscisi acik (testlerde kapali)."""
    return bool(klasor_ayari()) and isleme.etkin()


def klasor_ayari():
    return (os.getenv("TARAMA_KLASORU") or "").strip() or None


def yoksayilir_mi(yol):
    ad = yol.name.lower()
    return ad.startswith((".", "~$")) or ad in YOKSAYILAN_ADLAR or yol.suffix.lower() in YOKSAYILAN_UZANTILAR


def kullanici_klasoru_olustur(kullanici_adi, kok=None):
    """Kullanicinin tarama alt klasorunu olusturur (kayitta). Klasor ayari
    yoksa ya da ad ayrilmis bir adsa bir sey yapmaz."""
    kok = kok or klasor_ayari()
    if not kok or kullanici_adi.lower() in AYRILMIS_KLASORLER:
        return None
    yol = Path(kok) / kullanici_adi
    try:
        yol.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.exception("Tarama klasoru olusturulamadi: %s", yol)
        return None
    return yol


# ---------------------------------------------------------------- dosya hazirlama

def _tiff_donustur(veri):
    """(veri, mime, uzanti): tek sayfa -> PNG, cok sayfa -> tek PDF."""
    try:
        goruntu = Image.open(io.BytesIO(veri))
        sayfalar = [sayfa.copy() for sayfa in ImageSequence.Iterator(goruntu)]
    except Exception as hata:
        raise DosyaHatasi(f"TIFF dosyası açılamadı: {hata}") from hata
    if not sayfalar:
        raise DosyaHatasi("TIFF dosyasında sayfa yok.")
    return sayfalari_birlestir(sayfalar)


def sayfalari_birlestir(sayfalar, dpi=None, uzun_kenar=TIFF_PDF_UZUN_KENAR, kalite=TIFF_PDF_KALITESI):
    """Taranmis sayfalar (PIL) -> (veri, mime, uzanti): tek sayfa kayipsiz PNG,
    cok sayfa tek PDF (sayfalar A4 ~300 DPI'ye kucultulup JPEG sikistirilir).
    Cok sayfali TIFF ve WIA taramasi (tarayici_wia.py) kullanir."""
    tampon = io.BytesIO()
    if len(sayfalar) == 1:
        sayfa = sayfalar[0]
        if sayfa.mode not in ("1", "L", "RGB", "RGBA"):
            sayfa = sayfa.convert("RGB")
        sayfa.save(tampon, "PNG", optimize=True)
        return tampon.getvalue(), "image/png", ".png"
    hazir = []
    for sayfa in sayfalar:
        sayfa = sayfa.convert("L" if sayfa.mode in ("1", "L", "I;16", "I") else "RGB")
        sayfa.thumbnail((uzun_kenar, uzun_kenar))
        hazir.append(sayfa)
    dpi = dpi or (sayfalar[0].info.get("dpi") or (300, 300))[0] or 300
    hazir[0].save(tampon, "PDF", save_all=True, append_images=hazir[1:], quality=kalite,
                  resolution=float(dpi))
    return tampon.getvalue(), "application/pdf", ".pdf"


def dosyayi_hazirla(yol, veri):
    """Dogrulanmis (veri, mime, dosya_adi); alinamazsa DosyaHatasi."""
    mime = TURLER.get(yol.suffix.lower())
    if mime is None:
        raise DosyaHatasi(
            f"Desteklenmeyen dosya türü ({yol.suffix or 'uzantısız'}). JPG, PNG, PDF ve TIFF dosyaları alınır."
        )
    if not veri:
        raise DosyaHatasi("Dosya boş.")
    ad = yol.name
    if mime == "image/tiff":
        veri, mime, uzanti = _tiff_donustur(veri)
        ad = yol.with_suffix(uzanti).name
    if mime == "application/pdf" and len(veri) > MAKS_PDF_BOYUTU:
        raise DosyaHatasi(f"PDF çok büyük ({len(veri) / 1024 / 1024:.1f} MB); en fazla 5 MB olabilir.")
    if mime != "application/pdf" and len(veri) > MAKS_GORSEL_BOYUTU:
        raise DosyaHatasi(f"Görsel çok büyük ({len(veri) / 1024 / 1024:.1f} MB); en fazla 10 MB olabilir.")
    return veri, mime, ad


# ---------------------------------------------------------------- tasima

def _bos_hedef(klasor, ad):
    """klasor/ad zaten varsa ad_1, ad_2 ... (hicbir dosyanin uzerine yazilmaz)."""
    hedef = klasor / ad
    sayac = 1
    while hedef.exists():
        hedef = klasor / f"{Path(ad).stem}_{sayac}{Path(ad).suffix}"
        sayac += 1
    return hedef


def _tasi(yol, klasor):
    klasor.mkdir(parents=True, exist_ok=True)
    hedef = _bos_hedef(klasor, yol.name)
    os.replace(yol, hedef)  # ayni birimde atomik; kilitli dosyada OSError
    return hedef


def hataya_tasi(yol, neden, klasor=None):
    """Dosyayi <klasor>/hata/ (ya da verilen klasore) tasir ve nedenini yanina yazar."""
    hedef = _tasi(yol, klasor or yol.parent / HATA)
    zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hedef.with_name(hedef.name + ".hata.txt").write_text(
        f"{zaman}\n{yol.name} alınamadı.\nNeden: {neden}\n", encoding="utf-8"
    )
    log.warning("Tarama dosyasi alinamadi (%s): %s", yol.name, neden)
    return hedef


# ---------------------------------------------------------------- izleyici

class Izleyici:
    """TARAMA_KLASORU izleyicisi. Tek tarama gecisi tara(); arka planda baslat()/durdur().

    saat: test icin zaman kaynagi (varsayilan time.monotonic)."""

    ad = "tarama-klasoru"
    kaynak_adi = "Tarama klasörü"

    def __init__(self, kok, varsayilan_kullanici=None, belge_limiti=None, kararlilik_sn=KARARLILIK_SN,
                 saat=time.monotonic):
        self.kok = Path(kok) if kok is not None else None
        self.varsayilan_kullanici = (varsayilan_kullanici or "").strip() or None
        self.belge_limiti = belge_limiti
        self.kararlilik_sn = kararlilik_sn
        self.saat = saat
        self._durumlar = {}  # yol -> ((boyut, mtime_ns), ilk gorulme)
        self._uyandir = threading.Event()
        self._dur = threading.Event()
        self._is_parcacigi = None
        self._gozlemci = None
        self._uyarilan = set()

    def izlenen_klasorler(self):
        return [self.kok]

    # -- aday dosyalar

    def _adaylar(self):
        """(yol, klasor_sahibi_adi | None). Kok ve bir seviye kullanici klasorleri."""
        if not self.kok.is_dir():
            return
        for oge in self.kok.iterdir():
            if oge.is_file():
                if not yoksayilir_mi(oge):
                    yield oge, None
            elif oge.is_dir() and oge.name.lower() not in AYRILMIS_KLASORLER and not yoksayilir_mi(oge):
                for dosya in oge.iterdir():
                    if dosya.is_file() and not yoksayilir_mi(dosya):
                        yield dosya, oge.name

    def _kararli_mi(self, yol):
        try:
            bilgi = yol.stat()
        except OSError:
            self._durumlar.pop(yol, None)
            return False
        imza = (bilgi.st_size, bilgi.st_mtime_ns)
        onceki = self._durumlar.get(yol)
        simdi = self.saat()
        if onceki is None or onceki[0] != imza:
            self._durumlar[yol] = (imza, simdi)
            return False
        return bilgi.st_size > 0 and simdi - onceki[1] >= self.kararlilik_sn

    # -- sahiplik

    def _sahip(self, klasor_adi):
        """(kullanici_id, gelen_kutusu, kullanici_adi) ya da DosyaHatasi.
        Sahip henuz belirlenemiyorsa (hic kullanici yok) None."""
        if klasor_adi is not None:
            kullanici = database.kullanici_adi_ile_getir(klasor_adi)
            if kullanici is None:
                raise DosyaHatasi(f"'{klasor_adi}' adlı bir kullanıcı yok; klasör adı kullanıcı adıyla aynı olmalı.")
            return kullanici["id"], False, kullanici["kullanici_adi"]
        if self.varsayilan_kullanici:
            kullanici = database.kullanici_adi_ile_getir(self.varsayilan_kullanici)
            if kullanici is not None:
                return kullanici["id"], False, kullanici["kullanici_adi"]
            self._bir_kez_uyar("varsayilan", "TARAMA_VARSAYILAN_KULLANICI (%s) bulunamadi; belgeler Gelen belgeler "
                               "kutusuna gidiyor.", self.varsayilan_kullanici)
        yonetici = database.yonetici_getir()
        if yonetici is None:
            self._bir_kez_uyar("yonetici", "Henuz kullanici yok; tarama klasorundeki dosyalar ilk kullanici "
                               "kaydolunca alinacak.")
            return None
        return yonetici["id"], True, yonetici["kullanici_adi"]

    def _bir_kez_uyar(self, anahtar, mesaj, *arg):
        if anahtar not in self._uyarilan:
            self._uyarilan.add(anahtar)
            log.warning(mesaj, *arg)

    # -- tek dosya

    def _isle(self, yol, klasor_adi):
        """Donus: ("alindi", belge_id) | ("hata", neden) | ("bekliyor", None)."""
        try:
            veri = yol.read_bytes()
        except OSError:
            return "bekliyor", None  # baska program hala tutuyor olabilir
        try:
            sahip = self._sahip(klasor_adi)
            if sahip is None:
                return "bekliyor", None
            kullanici_id, gelen, kullanici_adi = sahip
            veri, mime, ad = dosyayi_hazirla(yol, veri)
            if not gelen and self.belge_limiti is not None and database.belge_sayisi(kullanici_id) >= self.belge_limiti:
                raise DosyaHatasi(f"Kota dolu: {kullanici_adi} kullanıcısının arşivinde en fazla "
                                  f"{self.belge_limiti} belge olabilir.")
        except DosyaHatasi as hata:
            try:
                hataya_tasi(yol, str(hata), self._hata_klasoru(yol, klasor_adi))
            except OSError:
                return "bekliyor", None
            tarama_gunlugu.hata(self.kaynak_adi, f"{yol.name}: {hata}")
            return "hata", str(hata)

        try:
            tasinan = _tasi(yol, self._islendi_klasoru(yol, klasor_adi))
        except OSError:
            return "bekliyor", None  # dosya kilitli ya da baska surec aldi
        try:
            belge_id = isleme.kuyruga_ekle(kullanici_id, veri, mime, ad, gelen_kutusu=gelen, kaynak="klasor")
        except Exception:
            log.exception("Tarama dosyasi kuyruga eklenemedi, yerine geri konuyor: %s", yol.name)
            try:
                os.replace(tasinan, _bos_hedef(yol.parent, yol.name))
            except OSError:
                log.exception("Dosya geri tasinamadi: %s", tasinan)
            return "bekliyor", None
        log.info("Tarama dosyasi alindi: %s -> belge %s (%s%s)", yol.name, belge_id, kullanici_adi,
                 ", gelen kutusu" if gelen else "")
        tarama_gunlugu.aktarildi(yol.name, kullanici_adi, gelen, self.kaynak_adi)
        return "alindi", belge_id

    def _islendi_klasoru(self, yol, klasor_adi):
        return yol.parent / ISLENDI / datetime.now().strftime("%Y-%m-%d")

    def _hata_klasoru(self, yol, klasor_adi):
        return yol.parent / HATA

    # -- gecis

    def tara(self):
        """Klasoru bir kez tarar; kararli dosyalari isler. Donus: [(yol, sonuc, deger)]."""
        sonuclar = []
        gorulen = set()
        for yol, klasor_adi in list(self._adaylar()):
            gorulen.add(yol)
            if self._kararli_mi(yol):
                sonuc, deger = self._isle(yol, klasor_adi)
                if sonuc != "bekliyor":
                    self._durumlar.pop(yol, None)
                sonuclar.append((yol, sonuc, deger))
        for yol in set(self._durumlar) - gorulen:
            del self._durumlar[yol]
        return sonuclar

    # -- arka plan

    def baslat(self):
        if self._is_parcacigi is not None and self._is_parcacigi.is_alive():
            return
        if self.kok is not None:
            self.kok.mkdir(parents=True, exist_ok=True)
        self._dur.clear()
        self._gozlemciyi_baslat()
        self._is_parcacigi = threading.Thread(target=self._dongu, name=self.ad, daemon=True)
        self._is_parcacigi.start()
        for klasor in self.izlenen_klasorler():
            log.info("Tarama klasoru izleniyor: %s", klasor)

    def _gozlemciyi_baslat(self):
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            log.warning("watchdog kurulu degil; tarama klasoru yalnizca yoklamayla izleniyor.")
            return
        uyandir = self._uyandir

        class _Olay(FileSystemEventHandler):
            def on_any_event(self, olay):
                uyandir.set()

        try:
            self._gozlemci = Observer()
            for klasor in self.izlenen_klasorler():
                self._gozlemci.schedule(_Olay(), str(klasor), recursive=True)
            self._gozlemci.start()
        except Exception:
            log.warning("Klasor olaylari izlenemiyor (ag paylasimi olabilir); yoklamayla devam ediliyor.",
                        exc_info=True)
            self._gozlemci = None

    def durdur(self, bekle=5):
        self._dur.set()
        self._uyandir.set()
        if self._gozlemci is not None:
            self._gozlemci.stop()
            self._gozlemci.join(bekle)
            self._gozlemci = None
        if self._is_parcacigi is not None:
            self._is_parcacigi.join(bekle)
            self._is_parcacigi = None

    def _dongu(self):
        while not self._dur.is_set():
            self._uyandir.clear()
            try:
                self.tara()
            except Exception:
                log.exception("Tarama klasoru taranamadi")
            if self._uyandir.wait(BEKLEYEN_YOKLAMA_SN if self._durumlar else YOKLAMA_SN):
                # Yazim suren dosya art arda olay uretir; her olayda taranmasin.
                self._dur.wait(OLAY_BEKLEMESI_SN)


# ---------------------------------------------------------------- surec basina tek izleyici

_izleyici = None
_kilit = threading.Lock()


def baslat(belge_limiti=None):
    """TARAMA_KLASORU tanimliysa bu surecin izleyicisini baslatir; mevcut
    kullanicilarin alt klasorlerini olusturur."""
    global _izleyici
    if not etkin():
        return None
    with _kilit:
        if _izleyici is None:
            _izleyici = Izleyici(klasor_ayari(), os.getenv("TARAMA_VARSAYILAN_KULLANICI"), belge_limiti)
            try:
                for kullanici in database.kullanicilari_listele():
                    kullanici_klasoru_olustur(kullanici["kullanici_adi"], _izleyici.kok)
            except Exception:
                log.exception("Kullanici tarama klasorleri olusturulamadi")
        _izleyici.baslat()
    return _izleyici


# ---------------------------------------------------------------- bilgisayardaki tarama klasorleri
# Windows varsayilan tarama klasorleri ve sonradan eklenen klasorler
# (izlenen_klasorler.py) tek izleyiciyle izlenir.

# (bilinen klasor, alt yol): Windows Faks ve Tarama, Windows Tarayici uygulamasi
# ve yaygin tarayici yazilimlarinin varsayilan kayit yerleri. Yalnizca var olanlar
# izlenir; sonradan olusan klasor bir sonraki yoklamada eklenir.
VARSAYILAN_ALT_KLASORLER = (
    ("belgeler", "Scanned Documents"),  # Windows Faks ve Tarama ("Taranan Belgeler" diye gorunur)
    ("belgeler", "Taranan Belgeler"),
    ("resimler", "Scans"),  # Windows Tarayici uygulamasi
    ("resimler", "Taranan"),
    ("resimler", "Taranan Belgeler"),
    ("resimler", "Scanned Documents"),
    ("resimler", "ControlCenter4/Scan"),  # Brother
)
# Bilinen klasorlerin Windows kimlikleri (OneDrive'a tasinmis olabilirler) ve ev klasorundeki adlari.
BILINEN_KLASORLER = {
    "belgeler": ("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "Documents"),
    "resimler": ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", "Pictures"),
    "masaustu": ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "Desktop"),
    "indirilenler": ("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads"),
}
VARSAYILAN_TUR, EKLENEN_TUR = "Windows tarama klasörü", "Eklenen klasör"


def _bilinen_klasor(ad):
    """Kullanicinin Belgeler/Resimler/... klasorleri (Windows'un bildirdigi yer
    ve ev klasorundeki varsayilan yer; ayniysa bir kez)."""
    guid, yedek = BILINEN_KLASORLER[ad]
    yollar = []
    if sys.platform == "win32":
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            kimlik = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(guid).bytes_le)
            isaretci = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(kimlik), 0, None,
                                                          ctypes.byref(isaretci)) == 0:
                yollar.append(Path(isaretci.value))
            ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(isaretci, wintypes.LPVOID))
        except Exception:
            log.debug("Bilinen klasor okunamadi: %s", ad, exc_info=True)
    ev = Path.home() / yedek
    if ev not in yollar:
        yollar.append(ev)
    return yollar


def varsayilan_klasor_adaylari():
    """Izlenebilecek tum varsayilan tarama klasorleri (var olsun olmasin)."""
    adaylar = []
    for bilinen, alt in VARSAYILAN_ALT_KLASORLER:
        for taban in _bilinen_klasor(bilinen):
            yol = taban / Path(alt)
            if yol not in adaylar:
                adaylar.append(yol)
    return adaylar


def varsayilanlar_acik():
    """Windows varsayilan tarama klasorleri: Windows'ta acik, VARSAYILAN_TARAMA_KLASORLERI=0 kapatir."""
    return sys.platform == "win32" and os.getenv("VARSAYILAN_TARAMA_KLASORLERI", "").strip() != "0"


def bilgisayar_klasorleri():
    """[(yol, tur, baslangic)]: izlenecek eklenen ve varsayilan (kaldirilanlar
    haric) klasorler; var olup olmadiklarina bakilmaz. Ayni klasor bir kez."""
    liste, gorulen = [], set()
    kaldirilan = izlenen_klasorler_deposu.kaldirilan_varsayilanlar()
    for kayit in izlenen_klasorler_deposu.ekli_klasorler():
        anahtar = izlenen_klasorler_deposu.normal(kayit["yol"])
        if anahtar not in gorulen:
            gorulen.add(anahtar)
            liste.append((Path(kayit["yol"]), EKLENEN_TUR, kayit.get("baslangic")))
    if varsayilanlar_acik():
        for aday in varsayilan_klasor_adaylari():
            anahtar = izlenen_klasorler_deposu.normal(aday)
            if anahtar not in gorulen and anahtar not in kaldirilan:
                gorulen.add(anahtar)
                liste.append((aday, VARSAYILAN_TUR, None))
    return liste


def varsayilan_klasorler_etkin():
    """Bilgisayardaki tarama klasorlerinin izleyicisi calismali mi? Arka plan
    iscisi kapaliysa (testler) hayir."""
    return isleme.etkin() and (varsayilanlar_acik() or bool(izlenen_klasorler_deposu.ekli_klasorler()))


def _olusma_zamani(bilgi):
    """Dosyanin klasore dusme zamani: degisiklik ve (Windows'ta) olusturma
    zamaninin buyugu. Kopyalanan dosya eski degisiklik zamanini korusa da
    olusturma zamani yenidir."""
    return max(bilgi.st_mtime, getattr(bilgi, "st_birthtime", bilgi.st_ctime))


class VarsayilanKlasorIzleyici(Izleyici):
    """Bilgisayardaki tarama klasorlerini izler: Windows varsayilanlari ve
    sonradan eklenenler (modul aciklamasi).

    TARAMA_KLASORU'ndan farki: alt klasorler kullanici adi sayilmaz (tarayici
    yazilimlarinin tarih klasorleri olabilir; bir seviye inilir), yalnizca
    desteklenen turdeki dosyalar alinir, dosyalar "ArcBase'e aktarıldı"
    klasorune tasinir. Eklenen klasorde "yalnizca yeniler" secildiyse eklenme
    anindan once dusmus dosyalar alinmaz.

    adaylar: [(yol, tur, baslangic)] donduren fonksiyon (varsayilan bilgisayar_klasorleri)."""

    ad = "bilgisayar-tarama-klasorleri"
    kaynak_adi = "Bilgisayardaki tarama klasörü"

    def __init__(self, adaylar=None, haric=(), **ayar):
        super().__init__(None, **ayar)
        self._adaylar_fn = adaylar or bilgisayar_klasorleri
        self._haric = {izlenen_klasorler_deposu.normal(h) for h in haric if h}

    def _izlenenler(self):
        return [(yol, baslangic) for yol, _tur, baslangic in self._adaylar_fn()
                if yol.is_dir() and izlenen_klasorler_deposu.normal(yol) not in self._haric]

    def izlenen_klasorler(self):
        return [yol for yol, _ in self._izlenenler()]

    def _dosya_mi(self, yol, baslangic):
        if not (yol.is_file() and not yoksayilir_mi(yol) and yol.suffix.lower() in TURLER):
            return False
        if baslangic is None:
            return True
        try:
            return _olusma_zamani(yol.stat()) >= baslangic
        except OSError:
            return False

    def _adaylar(self):
        """(yol, izlenen kok klasor): kok ve bir seviye alt klasorler."""
        for kok, baslangic in self._izlenenler():
            try:
                ogeler = list(kok.iterdir())
            except OSError:
                continue
            for oge in ogeler:
                if oge.is_dir():
                    if oge.name.lower() in AYRILMIS_KLASORLER or yoksayilir_mi(oge):
                        continue
                    try:
                        for dosya in oge.iterdir():
                            if self._dosya_mi(dosya, baslangic):
                                yield dosya, kok
                    except OSError:
                        continue
                elif self._dosya_mi(oge, baslangic):
                    yield oge, kok

    def _sahip(self, kok):
        """Tanimliysa TARAMA_VARSAYILAN_KULLANICI; ArcBase'te tek kullanici
        varsa o; yoksa yoneticinin Gelen belgeler kutusu."""
        if self.varsayilan_kullanici and database.kullanici_adi_ile_getir(self.varsayilan_kullanici):
            return super()._sahip(None)
        kullanicilar = database.kullanicilari_listele()
        if len(kullanicilar) == 1:
            return kullanicilar[0]["id"], False, kullanicilar[0]["kullanici_adi"]
        return super()._sahip(None)

    def _islendi_klasoru(self, yol, kok):
        return kok / AKTARILDI

    def _hata_klasoru(self, yol, kok):
        return kok / AKTARILAMADI


def mevcut_dosya_sayisi(klasor):
    """Klasorde (ve bir seviye alt klasorlerinde) alinabilecek dosya sayisi."""
    izleyici = VarsayilanKlasorIzleyici(adaylar=lambda: [(Path(klasor), EKLENEN_TUR, None)])
    return sum(1 for _ in izleyici._adaylar())


_varsayilan_izleyici = None


def varsayilan_baslat(belge_limiti=None):
    """Bilgisayardaki tarama klasorlerinin izleyicisini baslatir (surec basina
    bir kez; klasor eklendiginde yeniden cagrilir, calisiyorsa bir sey yapmaz)."""
    global _varsayilan_izleyici
    if not varsayilan_klasorler_etkin():
        return None
    with _kilit:
        if _varsayilan_izleyici is None:
            _varsayilan_izleyici = VarsayilanKlasorIzleyici(
                haric=[klasor_ayari()], varsayilan_kullanici=os.getenv("TARAMA_VARSAYILAN_KULLANICI"),
                belge_limiti=belge_limiti,
            )
        _varsayilan_izleyici.baslat()
    return _varsayilan_izleyici


def izlenen_klasorler():
    """Durum ve klasor sayfalari icin: [{"yol", "tur", "izleniyor", "not", "kaldirilabilir"}]."""
    liste = []
    if klasor_ayari():
        kok = Path(klasor_ayari())
        liste.append({"yol": str(kok), "tur": "Tarama klasörü (TARAMA_KLASORU)",
                      "izleniyor": etkin() and kok.is_dir(), "kaldirilabilir": False,
                      "not": "Alt klasörler kullanıcı adıdır; .env'deki ayardan değiştirilir."})
    haric = izlenen_klasorler_deposu.normal(klasor_ayari()) if klasor_ayari() else None
    calisiyor = varsayilan_klasorler_etkin()
    for yol, tur, baslangic in bilgisayar_klasorleri():
        if izlenen_klasorler_deposu.normal(yol) == haric:
            continue
        var = yol.is_dir()
        if var:
            notu = "Yalnızca eklendikten sonra düşen dosyalar alınır." if baslangic else ""
        elif tur == VARSAYILAN_TUR:
            notu = "Henüz yok; oluşturulunca kendiliğinden izlenir."
        else:
            notu = "Klasör bulunamadı (silinmiş ya da taşınmış olabilir)."
        liste.append({"yol": str(yol), "tur": tur, "izleniyor": var and calisiyor, "not": notu,
                      "kaldirilabilir": True})
    return liste
