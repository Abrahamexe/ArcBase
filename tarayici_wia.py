"""Bilgisayara bagli tarayicidan dogrudan tarama (WIA, yalnizca Windows).

Windows'ta varsayilan olarak aciktir (kapatmak icin TARAYICI_WIA=0). Modul
yalnizca gerektiginde ice aktarilir; Linux'ta (Render) hic yuklenmez.
Uygulama, tarayicinin bagli oldugu (USB) ya da ag tarayicisini (WSD) Windows'a
eklemis bilgisayarda calismalidir: WIA ikisini de ayni listede gosterir.

Tarayici algilama: arka planda YOKLAMA_SN'de bir tarayici listesi yenilenir
(izlemeyi_baslat). Sayfalar /tarayici/durum ile bu onbellegi sorar; tarayici
takilinca "Tarayici bulundu" bildirimi ve "Tara" dugmesi cikar, cikarilinca
kaybolur. Arka plan is parcacigi yoksa (testler) liste istek aninda yenilenir.

Tarama: kaynak "otomatik" iken besleyicide (ADF) kagit varsa tum sayfalar tek
seferde alinir; yoksa camli yuzeyden tek sayfa alinir ve kullanici "Sonraki
sayfa" / "Bitir" ile devam eder. Bitmemis cok sayfali taramanin sayfalari
bellekte kullanici basina tutulur (BekleyenTaramalar). Ayni anda tek tarama
yapilir; her tarama kendi COM oturumunu acar (CoInitialize).

Hatalar TarayiciHatasi olarak sade bir mesajla doner (hata kodu ve teknik
terim yok); teknik ayrinti yalnizca uygulama gunlugune yazilir.

Gercek tarayiciyla otomatik test yapilamaz; bu katman sahte COM nesneleriyle
test edilir (tests/test_tarayici_wia.py). Elle kontrol listesi:
docs/KURULUM_KURUM.md, "Gerçek tarayıcıyla kontrol listesi".
"""

import logging
import threading
import time

import tarama_gunlugu

log = logging.getLogger("dijital_arsiv.tarayici")

# WIA sabitleri (wiadef.h)
TARAYICI_TURU = 1  # WiaDeviceType.ScannerDeviceType
PNG_BICIMI = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"  # wiaFormatPNG
BELGE_YETENEKLERI = 3086  # WIA_DPS_DOCUMENT_HANDLING_CAPABILITIES
BELGE_DURUMU = 3087  # WIA_DPS_DOCUMENT_HANDLING_STATUS
BELGE_KAYNAGI = 3088  # WIA_DPS_DOCUMENT_HANDLING_SELECT
SAYFA_SAYISI = 3096  # WIA_DPS_PAGES (0 = besleyicideki tum sayfalar)
BESLEYICI, CAMLI = 1, 2  # FEEDER, FLATBED (yetenek ve secim bitleri)
BESLEYICI_HAZIR = 1  # FEED_READY: besleyicide kagit var
RENK_NIYETI = 6146  # WIA_IPS_CUR_INTENT
YATAY_COZUNURLUK, DIKEY_COZUNURLUK = 6147, 6148  # WIA_IPS_XRES / YRES
RENKLER = {"renkli": 1, "gri": 2, "sb": 4}  # WIA_INTENT_IMAGE_TYPE_COLOR / GRAYSCALE / TEXT
COZUNURLUKLER = (200, 300)
KAYNAKLAR = ("otomatik", "besleyici", "cam")
VARSAYILAN_DPI, VARSAYILAN_RENK = 300, "renkli"
MAKS_SAYFA = 50  # tek belgede en fazla sayfa
YOKLAMA_SN = 3.0  # tarayici listesi bu aralikla yenilenir
BEKLEYEN_OMRU_SN = 30 * 60  # bitirilmemis cok sayfali tarama bu kadar sonra atilir

# Kullaniciya gosterilen mesajlar
BULUNAMADI = "Tarayıcı bulunamadı. Kablonun takılı ve tarayıcının açık olduğundan emin olun."
GENEL_HATA = "Tarama yapılamadı. Tarayıcıyı kapatıp açın ve yeniden deneyin."
MESGUL = "Tarayıcı şu an başka bir tarama yapıyor. Bitince yeniden deneyin."
BESLEYICI_YOK = "Bu tarayıcıda kâğıt besleyici yok. Kâğıdı camın üzerine koyup yeniden deneyin."

# HRESULT -> kullaniciya mesaj (wia.h WIA_ERROR_* / WIA_S_*)
KAGIT_BITTI = 0x80210003
HATA_MESAJLARI = {
    0x80210001: GENEL_HATA,
    0x80210002: "Kâğıt sıkıştı. Tarayıcının kapağını açıp sıkışan kâğıdı yavaşça çekin, sonra yeniden deneyin.",
    KAGIT_BITTI: "Besleyicide kâğıt yok. Kâğıtları besleyiciye yerleştirip yeniden deneyin.",
    0x80210004: "Kâğıt düzgün alınamadı. Kâğıtları düzeltip yeniden yerleştirin.",
    0x80210005: BULUNAMADI,
    0x80210006: "Tarayıcı şu an meşgul. Biraz bekleyip yeniden deneyin.",
    0x80210007: "Tarayıcı ısınıyor. Birkaç saniye bekleyip yeniden deneyin.",
    0x80210008: "Tarayıcının ekranında bir uyarı var. Tarayıcıyı kontrol edip yeniden deneyin.",
    0x80210009: BULUNAMADI,
    0x8021000A: "Tarayıcıyla bağlantı kurulamadı. Kabloyu çıkarıp yeniden takın.",
    0x8021000C: GENEL_HATA,
    0x8021000D: "Tarayıcı kilitli. Tarayıcının üzerindeki kilidi açıp yeniden deneyin.",
    0x8021000E: "Tarayıcının yazılımında bir sorun oluştu. Tarayıcıyı kapatıp açın; düzelmezse sürücüsünü yeniden kurun.",
    0x8021000F: "Tarayıcının yazılımında bir sorun oluştu. Tarayıcıyı kapatıp açın; düzelmezse sürücüsünü yeniden kurun.",
    0x80210015: BULUNAMADI,
    0x80210016: "Tarayıcının kapağı açık. Kapağı kapatıp yeniden deneyin.",
    0x80210017: "Tarayıcının ışığı yanmıyor. Tarayıcıyı kapatıp açın.",
    0x80210019: "Tarayıcı başka bir bilgisayar tarafından kullanılıyor. Biraz bekleyip yeniden deneyin.",
    0x80210020: "Besleyici aynı anda birden fazla kâğıt çekti. Kâğıtları havalandırıp yeniden yerleştirin.",
    0x80210064: "Tarama iptal edildi.",
    0x80070005: "Tarayıcıya erişilemedi. Bilgisayarı yeniden başlatıp tekrar deneyin.",
}

_tarama_kilidi = threading.Lock()


class TarayiciHatasi(RuntimeError):
    """Kullaniciya gosterilecek tarama hatasi (sade metin)."""


def _com():
    """(pythoncom, win32com.client). Testlerde sahtesiyle degistirilir."""
    import pythoncom
    import win32com.client

    return pythoncom, win32com.client


def _hresult(hata):
    """COM hatasindaki WIA kodu (isaretsiz 32 bit); yoksa None.
    pywintypes.com_error: args = (hresult, metin, excepinfo, arg); asil WIA
    kodu cogunlukla excepinfo[5]'tedir."""
    adaylar = []
    arg = getattr(hata, "args", ())
    if len(arg) > 2 and isinstance(arg[2], tuple) and len(arg[2]) > 5:
        adaylar.append(arg[2][5])
    if arg:
        adaylar.append(arg[0])
    adaylar.append(getattr(hata, "hresult", None))
    for kod in adaylar:
        if isinstance(kod, int) and kod:
            return kod & 0xFFFFFFFF
    return None


def _mesaj(hata):
    return HATA_MESAJLARI.get(_hresult(hata), GENEL_HATA)


def _kod_yaz(hata):
    kod = _hresult(hata)
    return f"0x{kod:08X}" if kod is not None else "-"


class _ComOturumu:
    """Is parcacigi icin COM'u acar/kapatir."""

    def __enter__(self):
        self.pythoncom, self.istemci = _com()
        self.pythoncom.CoInitialize()
        return self.istemci

    def __exit__(self, *_):
        self.pythoncom.CoUninitialize()


def _ozellik_yaz(ozellikler, kimlik, deger, zorunlu=False):
    """WIA ozelligini yazar; cihaz desteklemiyorsa (zorunlu degilse) atlar."""
    try:
        for ozellik in ozellikler:
            if ozellik.PropertyID == kimlik:
                ozellik.Value = deger
                return True
    except Exception:
        if zorunlu:
            raise
        return False
    return False


def _ozellik_oku(ozellikler, kimlik):
    """WIA ozelliginin tamsayi degeri; cihazda yoksa None."""
    try:
        for ozellik in ozellikler:
            if ozellik.PropertyID == kimlik:
                return int(ozellik.Value)
    except Exception:
        return None
    return None


def _tarayici_bilgileri(istemci):
    yonetici = istemci.Dispatch("WIA.DeviceManager")
    for bilgi in yonetici.DeviceInfos:
        if bilgi.Type == TARAYICI_TURU:
            yield bilgi


def _ad(bilgi):
    try:
        return str(bilgi.Properties("Name").Value)
    except Exception:
        return str(bilgi.DeviceID)


def tarayicilari_listele():
    """[{"id", "ad"}]; tarayici yoksa bos liste. WIA kullanilamiyorsa TarayiciHatasi."""
    try:
        with _ComOturumu() as istemci:
            return [{"id": str(b.DeviceID), "ad": _ad(b)} for b in _tarayici_bilgileri(istemci)]
    except Exception as hata:
        raise TarayiciHatasi(BULUNAMADI) from hata


# ---------------------------------------------------------------- tarayici algilama

class _Durum:
    def __init__(self):
        self.kilit = threading.Lock()
        self.tarayicilar = []
        self.son_kontrol = None  # time.monotonic; None: hic bakilmadi
        self.son_teknik_hata = None  # ayni hata her yoklamada gunluge yazilmasin
        self.ilerleme = {"taraniyor": False, "sayfa": 0}
        self.is_parcacigi = None


_durum = _Durum()


def yenile():
    """Tarayici listesini simdi yeniler; takilan/cikarilan tarayiciyi gunluge
    yazar. Tarama surerken liste degistirilmez (ayni cihaza ikinci COM erisimi)."""
    if _tarama_kilidi.locked():
        return list(_durum.tarayicilar)
    with _durum.kilit:
        try:
            yeni = tarayicilari_listele()
            _durum.son_teknik_hata = None
        except TarayiciHatasi as hata:
            teknik = repr(hata.__cause__)
            if teknik != _durum.son_teknik_hata:
                log.warning("Tarayici listesi alinamadi (WIA): %s", teknik)
                _durum.son_teknik_hata = teknik
            yeni = []
        onceki = {t["id"]: t["ad"] for t in _durum.tarayicilar}
        simdiki = {t["id"]: t["ad"] for t in yeni}
        if _durum.son_kontrol is not None or yeni:
            for kimlik in simdiki.keys() - onceki.keys():
                log.info("Tarayici bulundu: %s (%s)", simdiki[kimlik], kimlik)
            for kimlik in onceki.keys() - simdiki.keys():
                log.info("Tarayici cikarildi: %s (%s)", onceki[kimlik], kimlik)
        _durum.tarayicilar = yeni
        _durum.son_kontrol = time.monotonic()
        return list(yeni)


def bagli_tarayicilar(yenile_gerekirse=True):
    """Bilinen tarayicilar. Liste YOKLAMA_SN'den eskiyse (arka plan is parcacigi
    calismiyorsa) once yenilenir; yenile_gerekirse=False iken yalnizca onbellek."""
    son = _durum.son_kontrol
    if yenile_gerekirse and (son is None or time.monotonic() - son >= YOKLAMA_SN):
        return yenile()
    return list(_durum.tarayicilar)


def ilerleme():
    """{"taraniyor": bool, "sayfa": o ana kadar alinan sayfa sayisi}."""
    return dict(_durum.ilerleme)


def izlemeyi_baslat():
    """Tarayici listesini arka planda YOKLAMA_SN'de bir yeniler (surec basina bir kez)."""
    if _durum.is_parcacigi is not None and _durum.is_parcacigi.is_alive():
        return

    def dongu():
        while True:
            try:
                yenile()
            except Exception:
                log.exception("Tarayici listesi yenilenemedi")
            time.sleep(YOKLAMA_SN)

    _durum.is_parcacigi = threading.Thread(target=dongu, name="tarayici-algilama", daemon=True)
    _durum.is_parcacigi.start()


def sifirla():
    """Testler icin: onbellek ve ilerleme bosaltilir."""
    with _durum.kilit:
        _durum.tarayicilar = []
        _durum.son_kontrol = None
        _durum.son_teknik_hata = None
        _durum.ilerleme = {"taraniyor": False, "sayfa": 0}
    bekleyenler.temizle()


# ---------------------------------------------------------------- tarama

def _kaynak_sec(cihaz, kaynak):
    """True: besleyici (ADF), False: camli yuzey.

    otomatik: yalnizca besleyicisi olan tarayici besleyiciden; hem besleyici
    hem cami olanda besleyicide kagit varsa besleyiciden, yoksa camdan. Cihaz
    yeteneklerini bildirmiyorsa camdan."""
    if kaynak != "otomatik":
        return kaynak == "besleyici"
    yetenek = _ozellik_oku(cihaz.Properties, BELGE_YETENEKLERI)
    if yetenek is None or not yetenek & BESLEYICI:
        return False
    if not yetenek & CAMLI:
        return True
    durum = _ozellik_oku(cihaz.Properties, BELGE_DURUMU)
    return bool(durum is not None and durum & BESLEYICI_HAZIR)


def tara(cihaz_id, dpi=VARSAYILAN_DPI, renk=VARSAYILAN_RENK, kaynak="otomatik"):
    """Secilen tarayicidan tarar. Donus: (sayfalarin PNG baytlari, besleyici_mi).

    Besleyiciden kagit bitene kadar tum sayfalar, camli yuzeyden tek sayfa alinir."""
    if dpi not in COZUNURLUKLER or renk not in RENKLER or kaynak not in KAYNAKLAR:
        raise TarayiciHatasi("Tarama ayarları geçersiz. Sayfayı yenileyip yeniden deneyin.")
    if not _tarama_kilidi.acquire(blocking=False):
        raise TarayiciHatasi(MESGUL)
    _durum.ilerleme = {"taraniyor": True, "sayfa": 0}
    try:
        with _ComOturumu() as istemci:
            return _oturumda_tara(istemci, cihaz_id, dpi, renk, kaynak)
    except TarayiciHatasi as hata:
        tarama_gunlugu.hata("Tarayıcı", str(hata))
        raise
    except Exception as hata:
        log.warning("Tarama hatasi (cihaz=%s, kod=%s): %r", cihaz_id, _kod_yaz(hata), hata)
        mesaj = _mesaj(hata)
        tarama_gunlugu.hata("Tarayıcı", mesaj)
        raise TarayiciHatasi(mesaj) from hata
    finally:
        _durum.ilerleme = {"taraniyor": False, "sayfa": 0}
        _tarama_kilidi.release()


def _oturumda_tara(istemci, cihaz_id, dpi, renk, kaynak):
    """tara()'nin COM oturumu icindeki isi. Ayri fonksiyondur: COM nesneleri
    (bilgi, cihaz, oge) bu cerceveyle birlikte CoUninitialize'dan once birakilir;
    sonra birakilirsa pywin32 "releasing IUnknown" hatasi verir."""
    bilgi = next((b for b in _tarayici_bilgileri(istemci) if str(b.DeviceID) == cihaz_id), None)
    if bilgi is None:
        log.warning("Tarama: cihaz bulunamadi (%s)", cihaz_id)
        raise TarayiciHatasi(BULUNAMADI)
    cihaz = bilgi.Connect()
    besleyici = _kaynak_sec(cihaz, kaynak)
    if besleyici:
        if not _ozellik_yaz(cihaz.Properties, BELGE_KAYNAGI, BESLEYICI):
            raise TarayiciHatasi(BESLEYICI_YOK)
        _ozellik_yaz(cihaz.Properties, SAYFA_SAYISI, 0)
    else:
        _ozellik_yaz(cihaz.Properties, BELGE_KAYNAGI, CAMLI)
        _ozellik_yaz(cihaz.Properties, SAYFA_SAYISI, 1)
    oge = cihaz.Items(1)
    _ozellik_yaz(oge.Properties, RENK_NIYETI, RENKLER[renk])
    _ozellik_yaz(oge.Properties, YATAY_COZUNURLUK, dpi)
    _ozellik_yaz(oge.Properties, DIKEY_COZUNURLUK, dpi)
    sayfalar = _sayfalari_al(oge, besleyici)
    log.info("Tarama tamam: %s, %d sayfa (%s, %d dpi, %s)", _ad(bilgi), len(sayfalar),
             "besleyici" if besleyici else "cam", dpi, renk)
    return sayfalar, besleyici


def _sayfalari_al(oge, besleyici):
    sayfalar = []
    while len(sayfalar) < (MAKS_SAYFA if besleyici else 1):
        try:
            goruntu = oge.Transfer(PNG_BICIMI)
        except Exception as hata:
            if besleyici and sayfalar and _hresult(hata) == KAGIT_BITTI:
                break  # besleyicideki sayfalar bitti
            raise
        sayfalar.append(bytes(goruntu.FileData.BinaryData))
        _durum.ilerleme = {"taraniyor": True, "sayfa": len(sayfalar)}
    return sayfalar


# ---------------------------------------------------------------- cok sayfali tarama

class BekleyenTaramalar:
    """Camli yuzeyden sayfa sayfa taranan, henuz belgeye donusmemis sayfalar
    (kullanici basina). Bellektedir: tarama yalnizca tarayicinin bagli oldugu
    bilgisayarda, tek surecte (waitress) yapilir."""

    def __init__(self, omur_sn=BEKLEYEN_OMRU_SN, saat=time.monotonic):
        self.omur_sn = omur_sn
        self.saat = saat
        self._kilit = threading.Lock()
        self._kayitlar = {}  # kullanici_id -> {"sayfalar", "dpi", "zaman"}

    def _eskileri_at(self):
        sinir = self.saat() - self.omur_sn
        for anahtar in [a for a, k in self._kayitlar.items() if k["zaman"] < sinir]:
            del self._kayitlar[anahtar]

    def ekle(self, kullanici_id, sayfalar, dpi):
        """Sayfalari ekler; toplam sayfa sayisini dondurur."""
        with self._kilit:
            self._eskileri_at()
            kayit = self._kayitlar.setdefault(kullanici_id, {"sayfalar": [], "dpi": dpi, "zaman": 0})
            kayit["sayfalar"].extend(sayfalar)
            kayit["zaman"] = self.saat()
            return len(kayit["sayfalar"])

    def sayi(self, kullanici_id):
        with self._kilit:
            self._eskileri_at()
            kayit = self._kayitlar.get(kullanici_id)
            return len(kayit["sayfalar"]) if kayit else 0

    def al(self, kullanici_id):
        """(sayfalar, dpi) ve kaydi siler; yoksa ([], None)."""
        with self._kilit:
            self._eskileri_at()
            kayit = self._kayitlar.pop(kullanici_id, None)
        return (kayit["sayfalar"], kayit["dpi"]) if kayit else ([], None)

    def temizle(self):
        with self._kilit:
            self._kayitlar.clear()


bekleyenler = BekleyenTaramalar()
