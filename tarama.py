"""Belge fotografini tarayicidan cikmis gibi gosteren filtreler (OpenCV).

Uc mod:
- renkli (varsayilan): golge ve sari isik temizlenir, kagit beyazlasir; mavi
  murekkep, kirmizi/mor muhur ve renkli logolar korunur
- gri: ayni normalizasyon gri tonda + CLAHE ile yerel kontrast
- sb (siyah-beyaz): uyarlamali esikleme; muhur ve imzalar silik cikabilir

Hepsinin cekirdegi "arka plana bolme": yazisiz kagit isigi haritasi tahmin
edilir ve her piksel bu haritaya bolunur. Boylece isik/golge farki kaybolur,
kagidin uzerindeki murekkep (arka plandan koyu olan her sey) korunur.
PDF olarak yuklenen belgelere uygulanmaz.
"""

import cv2
import numpy as np

MODLAR = ("renkli", "gri", "sb")
VARSAYILAN_MOD = "renkli"

ARKA_PLAN_UZUN_KENAR = 500  # isik haritasi bu boyuta kucultulmus kopyada tahmin edilir (hiz)
ARKA_PLAN_DILATE = 7  # yazi cizgilerini silecek kadar genis (kucuk kopyada px)
ARKA_PLAN_MEDYAN = 21  # kalan dokuyu yumusatir; tek sayi
KABA_KARO = 25  # kaba kagit tahmininin karo boyu (kucuk kopyada px, ~%5)
KABA_YUZDELIK = 90  # karodaki en parlak %10: logo/QR/muhur karonun cogunu kaplamadikca kagittir
SIYAH_NOKTASI = 25  # bunun altı tam siyah (yazi koyulasir)
BEYAZ_NOKTASI = 225  # bunun ustu tam beyaz (kagit dokusu ve kalan golge kaybolur)
MUREKKEP_GAMMA = 1.4  # >1: ara tonlar (bulanik yazi govdesi) koyulasir, beyaz ve siyah yerinde kalir
KESKINLIK = 0.6  # yazi kenari keskinlestirme miktari (unsharp mask)
KESKINLIK_SIGMA = 0.0015  # keskinlestirme bulaniklik yaricapi, uzun kenara oranla
KESKINLIK_ESIGI = 12  # bundan kucuk yerel farklar (doku, gurultu) keskinlestirilmez
KENAR_KIRPMA_ORANI = 0.004  # her kenardan ~%0.4 (2000 px'te 8 px) masa/golge seridi kirpilir
SB_BLOK_ORANI = 0.02  # uyarlamali esik blok boyu, uzun kenara oranla
SB_SABIT = 12  # esik sabiti; buyudukce arka plan daha temiz, ince yazi daha zayif
SB_MIN_LEKE = 12  # bundan kucuk (px) siyah lekeler gurultu sayilip silinir


def tara(bgr, mod=VARSAYILAN_MOD):
    """BGR goruntuye filtre uygular. renkli: BGR, gri/sb: tek kanalli dizi doner."""
    if mod not in MODLAR:
        raise ValueError(f"Bilinmeyen tarama modu: {mod}")
    bgr = kenar_kirp(bgr)
    if mod == "renkli":
        return _seviye(_normalize(bgr))
    gri = _normalize(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    if mod == "gri":
        # Once kagit tam beyaza cekilir; CLAHE sonra yalnizca yazinin cevresindeki
        # yerel kontrasti arttirir (tersi sirada kalan golge sinirlarini buyutur).
        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        return clahe.apply(_seviye(gri))
    return _siyah_beyaz(gri)


def kenar_kirp(goruntu):
    y, g = goruntu.shape[:2]
    pay = max(2, int(max(y, g) * KENAR_KIRPMA_ORANI))
    if y <= 4 * pay or g <= 4 * pay:
        return goruntu
    return goruntu[pay:y - pay, pay:g - pay]


def arka_plan(kanal):
    """Tek kanalin yazisiz 'kagit isigi' haritasi (ayni boyutta, uint8).

    Kucuk kopyada dilate yazilari (koyu, ince) kagit rengiyle doldurur, medyan
    kalan kucuk lekeleri siler. Logo, QR kod ya da muhur gibi dilate'in
    silemeyecegi kadar buyuk koyu alanlar bu ince tahmini asagi ceker; bolme
    sonrasi bunlarin cevresinde parlak hale, iclerinde solma olur. Bunu
    onlemek icin kaba bir tahmin (karolarin parlak yuzdeligi) alt sinir olarak
    kullanilir. Sonuc tam boyuta yumusakca buyutulur."""
    y, g = kanal.shape[:2]
    oran = min(1.0, ARKA_PLAN_UZUN_KENAR / max(y, g))
    kucuk = cv2.resize(kanal, None, fx=oran, fy=oran, interpolation=cv2.INTER_AREA) if oran < 1 else kanal
    ince = cv2.dilate(kucuk, np.ones((ARKA_PLAN_DILATE, ARKA_PLAN_DILATE), np.uint8))
    ince = cv2.medianBlur(ince, ARKA_PLAN_MEDYAN)
    tahmin = np.maximum(ince, _kaba_arka_plan(kucuk))
    return cv2.resize(tahmin, (g, y), interpolation=cv2.INTER_LINEAR)


def _kaba_arka_plan(kucuk):
    """Karo basina parlak yuzdelik; yumusatilip kucuk kopya boyutuna buyutulur.
    Isik degisimini izler ama tek bir karodan buyuk olmayan koyu nesneleri
    gormez."""
    y, g = kucuk.shape[:2]
    satir, sutun = max(1, round(y / KABA_KARO)), max(1, round(g / KABA_KARO))
    karolar = np.empty((satir, sutun), np.uint8)
    ys = np.linspace(0, y, satir + 1).astype(int)
    xs = np.linspace(0, g, sutun + 1).astype(int)
    for i in range(satir):
        for j in range(sutun):
            karolar[i, j] = np.percentile(kucuk[ys[i]:ys[i + 1], xs[j]:xs[j + 1]], KABA_YUZDELIK)
    if min(satir, sutun) >= 3:
        karolar = cv2.medianBlur(karolar, 3)
    # Karo merkezleri arasinda dogrusal gecis. Goruntu kenarinda son karo
    # merkezinden disari duz uzatmak vinyetli/golgeli kenarda kagidi oldugundan
    # parlak gosterir (kenar kararmasi); bu yuzden izgara bir karo disari
    # dogrusal olarak uzatilir. Sonuc biraz karartilir ki ince tahmin dogru
    # oldugu yerde (golge siniri) baskin kalsin.
    uzatilmis = np.pad(karolar.astype(np.float32), 1, mode="reflect", reflect_type="odd")
    karo_y, karo_x = y / satir, g / sutun
    buyuk = cv2.resize(uzatilmis, (round(g + 2 * karo_x), round(y + 2 * karo_y)), interpolation=cv2.INTER_LINEAR)
    oy, ox = round(karo_y), round(karo_x)
    kaba = buyuk[oy:oy + y, ox:ox + g]
    kaba = cv2.GaussianBlur(kaba, (0, 0), KABA_KARO / 2) * 0.96
    return np.clip(kaba, 0, 255).astype(np.uint8)


def _normalize(goruntu):
    """Her kanali kendi arka planina boler: kagit ~255, murekkep rengini korur."""
    if goruntu.ndim == 2:
        return cv2.divide(goruntu, np.maximum(arka_plan(goruntu), 1), scale=255)
    kanallar = [cv2.divide(k, np.maximum(arka_plan(k), 1), scale=255) for k in cv2.split(goruntu)]
    return cv2.merge(kanallar)


def _keskinlestir(goruntu):
    """Esikli unsharp mask: yazi kenarlari netlesir. Esigin altindaki kucuk
    farklar (kagit dokusu, sensor gurultusu, golgedeki gren) buyutulmez, yoksa
    beyaz zeminde gri noktalar kalir. Kagit zaten beyaza yakin oldugundan
    acik taraftaki asim beyazda kirpilir; hale olusmaz."""
    sigma = max(0.8, KESKINLIK_SIGMA * max(goruntu.shape[:2]))
    ayrinti = goruntu.astype(np.int16) - cv2.GaussianBlur(goruntu, (0, 0), sigma).astype(np.int16)
    ayrinti = np.sign(ayrinti) * np.maximum(np.abs(ayrinti) - KESKINLIK_ESIGI, 0)
    return np.clip(goruntu + KESKINLIK * ayrinti, 0, 255).astype(np.uint8)


def _seviye(goruntu):
    """Siyah/beyaz noktalarini ayarlar ve ara tonlari koyulastirir: neredeyse
    beyaz pikseller tam beyaz olur, bulanik yazi govdesi koyulasir. Tum
    kanallara ayni egri uygulandigi icin renk tonu korunur (muhur, logo)."""
    dogrusal = np.clip(
        (np.arange(256, dtype=np.float32) - SIYAH_NOKTASI) / (BEYAZ_NOKTASI - SIYAH_NOKTASI), 0, 1
    )
    tablo = (255.0 * dogrusal ** MUREKKEP_GAMMA).round().astype(np.uint8)
    return cv2.LUT(_keskinlestir(goruntu), tablo)


def _siyah_beyaz(gri):
    uzun = max(gri.shape[:2])
    blok = max(15, int(uzun * SB_BLOK_ORANI)) | 1  # tek sayi olmali
    ikili = cv2.adaptiveThreshold(
        gri, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blok, SB_SABIT
    )
    # Kucuk siyah noktalar (kagit dokusu, toz) silinir; yazi harfleri kalir.
    adet, etiketler, istatistik, _ = cv2.connectedComponentsWithStats(255 - ikili, connectivity=8)
    silinecek = istatistik[:, cv2.CC_STAT_AREA] < SB_MIN_LEKE
    silinecek[0] = False  # 0: arka plan (kagit)
    if silinecek.any():
        ikili[silinecek[etiketler]] = 255
    return ikili


def jpeg(goruntu, kalite=88):
    """Filtre ciktisini JPEG baytlarina cevirir (onizleme ve PDF gomme icin)."""
    tamam, veri = cv2.imencode(".jpg", goruntu, [cv2.IMWRITE_JPEG_QUALITY, kalite])
    if not tamam:
        raise ValueError("Görüntü JPEG'e çevrilemedi.")
    return veri.tobytes()
