"""Yuklenen belgelerin arka planda islenmesi: duzeltme, OCR, siniflandirma.

Yukleme istegi gorseli saklanacak haline (en fazla 2000 px JPEG) getirip
sifreler, "bekliyor" durumunda kaydeder ve hemen doner; kullanici OCR'i ve
Groq'u beklemez. Tam cozunurluklu dosya isciye bellekte birakilir (ham_birak);
boylece buyuk dosya veritabanina gidip geri gelmez. Bu moduldeki isci is
parcacigi isleri veritabanindan sirayla alir. Is iki asamalidir ve her
asamanin sonucu veritabanina yazilir; uygulama yeniden baslarsa is kaldigi
asamadan devam eder (bellek bosaldiysa OCR saklanan 2000 px gorselden yapilir):

1. goruntu: kose algilama, OCR (duzeltilmis ve OCR cozunurlugune indirilmis
   gri tarama uzerinde, tek sefer), duzeltilmis onizleme
2. siniflandirma: Groq ile tur ve bilgi alanlari. Gecici hatada (429,
   baglanti) is birkac saniye sonra yeniden denenmek uzere ertelenir; denemeler
   biterse belge "diger" olarak uyariyla tamamlanir (eskisi gibi).

Harici kuyruk servisi yoktur: durum belgeler.isleme_* sutunlarindadir. Her
surecte (gunicorn worker) bir isci calisir; ayni isi iki surecin almasini
veritabani kilidi (FOR UPDATE SKIP LOCKED) onler. Isci bosta iken veritabanini
yoklamaz (Neon uyuyabilsin): yeni yukleme isciyi uyandirir; ertelenmis ya da
baska bir surecte yarim kalmis is varsa yalnizca onun zamanina kadar bekler.
"""

import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path

import classifier
import crypto
import database
import goruntu_duzelt
import ocr
import tarama
from database import VARSAYILAN_TUR

log = logging.getLogger("dijital_arsiv.isleme")

PDF_MIME = "application/pdf"
# OCR'a giden duzeltilmis sayfanin uzun kenari (px). A4'te ~200 DPI: gercek
# fotograf ve sentetik 12 MP fotografta 300 DPI (3508 px) ile ayni dogruluk,
# yarisindan az piksel (bkz. README "Performans").
OCR_UZUN_KENAR = 2400
GROQ_BEKLEMELERI = (5, 20)  # gecici Groq hatasinda yeniden deneme aralari (sn)
MAKS_DENEME = 6  # is bu kadar kez alinip bitirilemediyse (cokme dongusu) hata sayilir
HATA_ERTELEME_SN = 30  # beklenmeyen hatadan sonra yeniden deneme
# Yuklenen tam cozunurluklu dosyalarin isciye bellekte aktarimi icin ust sinir;
# asilirsa en eski birakilir ve o belgenin OCR'i saklanan gorselden yapilir.
HAM_BELLEK_MB = int(os.getenv("HAM_BELLEK_MB") or 64)
METIN_OKUNAMADI = "Metin okunamadı, daha net bir fotoğraf deneyin."
ISLEME_HATASI = "Belge işlenemedi. Yeniden deneyebilir ya da silip tekrar yükleyebilirsiniz."


# ---------------------------------------------------------------- yukleme -> isci aktarimi

_hamlar = OrderedDict()  # belge_id -> tam cozunurluklu dosya baytlari
_ham_boyut = 0
_ham_kilit = threading.Lock()


def saklanacak_hal(veri, mime_type, dosya_adi):
    """Yukleme aninda veritabanina yazilacak hal: (icerik, mime, dosya_adi,
    onizleme, orijinal_saklandi).

    Gorsel EXIF yonu uygulanip en fazla 2000 px JPEG'e kucultulur (EXIF,
    konum vb. temizlenir) ve kirpilmamis hizli onizleme uretilir; isci bitince
    duzeltilmis onizleme gelir. PDF ve acilamayan gorsel oldugu gibi kalir."""
    if mime_type != PDF_MIME:
        try:
            tam = goruntu_duzelt.goruntu_ac(veri)
        except Exception:
            tam = None
        if tam is not None:
            saklanan, _ = ocr.gorsel_sikistir_bgr(tam)
            return saklanan, "image/jpeg", Path(dosya_adi).with_suffix(".jpg").name, ocr.onizleme_bgr(tam), True
    return veri, mime_type, dosya_adi, ocr.onizleme_uret(veri, mime_type), False


def ham_birak(belge_id, veri):
    """Tam cozunurluklu dosyayi isciye bellekte birakir (ayni surecte islenirse
    OCR bundan yapilir)."""
    global _ham_boyut
    with _ham_kilit:
        _hamlar[belge_id] = veri
        _ham_boyut += len(veri)
        while _ham_boyut > HAM_BELLEK_MB * 1024 * 1024 and _hamlar:
            _, eski = _hamlar.popitem(last=False)
            _ham_boyut -= len(eski)


def _ham_al(belge_id):
    global _ham_boyut
    with _ham_kilit:
        veri = _hamlar.pop(belge_id, None)
        if veri is not None:
            _ham_boyut -= len(veri)
        return veri


def ham_bellegini_bosalt():
    """Yeniden baslatmanin benzetimi (testler): bellekteki dosyalar kaybolur."""
    global _ham_boyut
    with _ham_kilit:
        _hamlar.clear()
        _ham_boyut = 0


# ---------------------------------------------------------------- goruntu -> metin

def ocr_girdisi(bgr, koseler):
    """(duzeltilmis renkli goruntu, OCR'a gidecek gri tarama).

    Perspektif duzeltme dogrudan OCR cozunurlugunde yapilir; tam boyutlu ara
    goruntu uretilmez. Golge ve sari isik gri tarama filtresiyle temizlenir;
    zor fotograflarda okuma belirgin sekilde iyilesir."""
    if koseler is not None:
        duz = goruntu_duzelt.uygula(bgr, koseler, uzun_kenar=OCR_UZUN_KENAR)
    else:
        duz = goruntu_duzelt.kucult(bgr, OCR_UZUN_KENAR)
    return duz, tarama.tara(duz, "gri")


def ocr_metni(bgr, koseler):
    """Gorselin (koselerle duzeltilmis) OCR metni; kose editoru de kullanir."""
    return ocr.metin_cikar(ocr_girdisi(bgr, koseler)[1], "image/jpeg")


def _metin_oku(veri, mime_type, uyarilar):
    """OCR hatasi yuklemeyi durdurmaz; uyari olarak kullaniciya gosterilir."""
    try:
        return ocr.metin_cikar(veri, mime_type)
    except Exception as hata:
        uyarilar.append(f"Metin çıkarılamadı: {hata}")
        return ""


def _goruntu_asamasi(is_, bilgi):
    """Donus: (ocr_metni, guncel bilgi). Sonuc veritabanina yazilir.

    Kaynak yuklemede bellege birakilan tam cozunurluklu dosyadir; yoksa
    (surec yeniden basladi, is baska surece dustu) saklanan gorsel kullanilir."""
    veri = _ham_al(is_["id"])
    if veri is None:
        veri = crypto.coz(database.is_icerigi(is_["id"]))
    mime_type = is_["mime_type"]
    uyarilar = []
    bilgi = {**bilgi, "asama": "siniflandirma", "uyarilar": uyarilar}

    tam = None
    if mime_type != PDF_MIME:
        try:
            tam = goruntu_duzelt.goruntu_ac(veri)
        except Exception:
            tam = None  # acilamayan gorsel: oldugu gibi saklanir, OCR uyarisi doner
    if tam is None:
        metin = _metin_oku(veri, mime_type, uyarilar)
        database.goruntu_asamasini_kaydet(is_["id"], bilgi, metin, None)  # onizleme yuklemede uretildi
        return metin, bilgi

    # Telefon fotografinda belgenin koseleri bulunur. Saklanan, duzeltilmemis
    # (kucultulmus) orijinal + koselerdir; duzeltilmis hal gosterimde aninda
    # uretilir. Kose puani emin esiginin altindaysa arayuz kirpmayi kontrol ettirir.
    koseler = None
    if bilgi.get("duzelt", True):
        analiz = goruntu_duzelt.analiz(tam)
        koseler = analiz["koseler"]
        if koseler is not None and analiz["belge"]:
            bilgi["kirpma_kontrol"] = analiz["puan"] < goruntu_duzelt.EMIN_PUANI
    duz, gri = ocr_girdisi(tam, koseler)
    metin = _metin_oku(gri, "image/jpeg", uyarilar)

    # Saklanan gorsel yuklemede kucultuldu; koseler onun koordinatlarina tasinir.
    genislik, _ = ocr.saklama_boyutu(tam)
    koseler = goruntu_duzelt.koseleri_olcekle(koseler, genislik / tam.shape[1])
    database.goruntu_asamasini_kaydet(
        is_["id"],
        bilgi,
        metin,
        crypto.sifrele(ocr.onizleme_bgr(duz)),
        koseler=koseler,
        otomatik_duzeltildi=koseler is not None,
    )
    return metin, bilgi


# ---------------------------------------------------------------- siniflandirma

def _siniflandirma_asamasi(is_, bilgi, metin):
    uyarilar = list(bilgi.get("uyarilar") or [])
    if metin:
        if is_["elle_duzeltildi"]:  # islenirken kullanici turu elle secti
            sonuc = classifier.siniflandir(metin, bilinen_tur=is_["tur"])
        else:
            sonuc = classifier.siniflandir(metin)
    else:
        sonuc = {"tur": VARSAYILAN_TUR, "guven": 0.0, "aciklama": METIN_OKUNAMADI, "alanlar": None}
        if not uyarilar:
            uyarilar.append(METIN_OKUNAMADI)

    hata_turu = sonuc.get("hata_turu") or ("yogun" if sonuc.get("yogun") else None)
    if hata_turu in ("yogun", "baglanti"):
        deneme = bilgi.get("groq_deneme", 0)
        if deneme < len(GROQ_BEKLEMELERI):
            database.is_ertele(is_["id"], GROQ_BEKLEMELERI[deneme], {**bilgi, "groq_deneme": deneme + 1})
            return
    if hata_turu:
        # Siniflandirma yapilamadi: belge "diger" olarak kaydedilir ve kullanici
        # uyarilir; detay sayfasindan yeniden denenebilir.
        uyarilar.append(classifier.YOGUN_MESAJI if hata_turu == "yogun" else sonuc["aciklama"])
    database.isi_tamamla(
        is_["id"], sonuc["tur"], sonuc["guven"], sonuc["aciklama"], sonuc.get("alanlar"),
        {**bilgi, "uyarilar": uyarilar},
    )


# ---------------------------------------------------------------- is dongusu

def bir_is_isle(kullanici_id=None, belge_id=None, gecikmeyi_yoksay=False):
    """Hazir bir isi alip isler; is yoksa False doner."""
    is_ = database.is_al(kullanici_id, belge_id, gecikmeyi_yoksay)
    if is_ is None:
        return False
    bilgi = dict(is_["isleme_bilgi"] or {})
    try:
        if is_["isleme_deneme"] > MAKS_DENEME:
            database.is_hatasi(is_["id"], {**bilgi, "hata": ISLEME_HATASI})
            return True
        metin = is_["ocr_metni"] or ""
        if bilgi.get("asama", "goruntu") == "goruntu":
            metin, bilgi = _goruntu_asamasi(is_, bilgi)
        _siniflandirma_asamasi(is_, bilgi, metin)
    except Exception:
        log.exception("Belge %s islenemedi (deneme %s)", is_["id"], is_["isleme_deneme"])
        try:
            if is_["isleme_deneme"] >= MAKS_DENEME:
                database.is_hatasi(is_["id"], {**bilgi, "hata": ISLEME_HATASI})
            else:
                database.is_ertele(is_["id"], HATA_ERTELEME_SN, bilgi)
        except Exception:
            log.exception("Belge %s icin hata durumu yazilamadi", is_["id"])
    return True


def bekleyenleri_isle(kullanici_id=None, belge_id=None, en_fazla=50):
    """Bekleyen isleri erteleme surelerini beklemeden hemen isler (testler,
    komut satiri). Islenen is sayisini dondurur."""
    adet = 0
    while adet < en_fazla and bir_is_isle(kullanici_id, belge_id, gecikmeyi_yoksay=True):
        adet += 1
    return adet


# ---------------------------------------------------------------- isci is parcacigi

_uyandir = threading.Event()
_dur = threading.Event()
_kilit = threading.Lock()
_is_parcacigi = None
_pid = None
_kullanici_filtresi = None


def etkin():
    """ARKA_PLAN_ISCISI=0 ile kapatilir (testler isleri kendisi calistirir)."""
    return os.getenv("ARKA_PLAN_ISCISI", "1") != "0"


def baslat(kullanici_id=None):
    """Bu surecin iscisini baslatir (zaten calisiyorsa bir sey yapmaz).
    kullanici_id: yalnizca bu kullanicinin isleri (tarayici testleri)."""
    global _is_parcacigi, _pid, _kullanici_filtresi
    with _kilit:
        if _is_parcacigi is not None and _is_parcacigi.is_alive() and _pid == os.getpid():
            return
        _kullanici_filtresi = kullanici_id
        _dur.clear()
        _uyandir.set()  # acilista yarim kalmis isler hemen alinsin
        _pid = os.getpid()
        _is_parcacigi = threading.Thread(target=_dongu, name="belge-iscisi", daemon=True)
        _is_parcacigi.start()


def durdur(bekle=10):
    global _is_parcacigi
    _dur.set()
    _uyandir.set()
    if _is_parcacigi is not None:
        _is_parcacigi.join(bekle)
    _is_parcacigi = None


def uyandir():
    """Yeni is eklendi: bosta bekleyen isci hemen baslasin."""
    _uyandir.set()


def _dongu():
    while not _dur.is_set():
        _uyandir.clear()  # bundan sonraki uyandirma kaybolmaz: is her donguda yeniden sorgulanir
        try:
            if bir_is_isle(kullanici_id=_kullanici_filtresi):
                continue
            kalan = database.sonraki_is_suresi(_kullanici_filtresi)
        except Exception:
            log.exception("Arka plan iscisi hata verdi")
            kalan = HATA_ERTELEME_SN
        # Is yoksa suresiz bekle (yalnizca yeni yukleme uyandirir).
        _uyandir.wait(None if kalan is None else max(kalan, 1.0))
