"""Otomatik duzeltme ve tarama testleri icin sentetik belge fotograflari.

Gercek telefon fotografi yerine: metin iceren beyaz bir sayfa, koyu ve
dokulu bir masa zemini uzerine perspektifle yerlestirilir (eğik cekim),
ya da beyaz zeminde birkac derece dondurulur (eğik tarama). Tarama
filtreleri icin sayfaya mavi imza, kirmizi muhur ve renkli logo eklenip
sari isik ve golge uygulanabilir."""

import io

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SATIRLAR = [
    "E-ARSIV FATURA",
    "ABC Elektronik Ticaret Ltd. Sti.",
    "Fatura No: ABC2026000000123",
    "Fatura Tarihi: 15.03.2026",
    "Kablosuz kulaklik 1 adet 1.000,00 TL",
    "KDV %20: 200,00 TL",
    "Genel Toplam: 1.200,00 TL",
]


def _yazi_tipi(boyut):
    for ad in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(ad, boyut)
        except OSError:
            pass
    return ImageFont.load_default()


def sayfa(boyut=(1240, 1754), satirlar=SATIRLAR):
    """A4 oraninda, uzerinde metin olan beyaz sayfa (RGB numpy)."""
    g = Image.new("RGB", boyut, "white")
    d = ImageDraw.Draw(g)
    yazi = _yazi_tipi(boyut[0] // 24)
    for i, satir in enumerate(satirlar):
        d.text((boyut[0] // 10, boyut[1] // 10 + i * boyut[0] // 12), satir, fill="black", font=yazi)
    return np.asarray(g)


# Sayfanin koselerinin tuvaldeki yeri (oransal): sol ust, sag ust, sag alt, sol alt
HAFIF_EGIK = ((0.30, 0.08), (0.74, 0.14), (0.70, 0.93), (0.22, 0.86))
COK_EGIK = ((0.38, 0.03), (0.86, 0.30), (0.62, 0.98), (0.12, 0.70))  # ~30 derece donuk
UZAKTAN = ((0.40, 0.30), (0.62, 0.33), (0.60, 0.72), (0.37, 0.69))  # kagit kucuk, masa buyuk


def masada_egik_cekim(tuval=(3000, 2250), tohum=1, koseler=HAFIF_EGIK, kagit=None, zemin_tonu=70):
    """Sayfayi dokulu bir masa uzerine perspektifle yerlestirir (telefon cekimi).

    zemin_tonu: masanin parlakligi; ~215 "beyaz masada beyaz kagit" gibi dusuk
    kontrastli durum uretir."""
    rng = np.random.default_rng(tohum)
    g, y = tuval
    zemin = rng.normal(zemin_tonu, 12 if zemin_tonu > 150 else 18, (y, g, 3)).clip(0, 255).astype(np.uint8)
    zemin = cv2.GaussianBlur(zemin, (0, 0), 3)
    zemin[..., 0] = (zemin[..., 0] * (0.93 if zemin_tonu > 150 else 0.7)).astype(np.uint8)  # sicak ton
    kagit = sayfa() if kagit is None else kagit
    kh, kg = kagit.shape[:2]
    kaynak = np.float32([[0, 0], [kg, 0], [kg, kh], [0, kh]])
    hedef = np.float32([[g * kx, y * ky] for kx, ky in koseler])
    matris = cv2.getPerspectiveTransform(kaynak, hedef)
    cizilen = cv2.warpPerspective(kagit, matris, (g, y))
    maske = cv2.warpPerspective(np.full((kh, kg), 255, np.uint8), matris, (g, y))
    sonuc = np.where(maske[..., None] > 0, cizilen, zemin)
    # hafif golge/isik farki ve sensor gurultusu
    isik = np.linspace(0.85, 1.05, g)[None, :, None]
    sonuc = (sonuc * isik + rng.normal(0, 4, sonuc.shape)).clip(0, 255).astype(np.uint8)
    return sonuc


def egik_tarama(aci=7.0):
    """Beyaz zeminde birkac derece donmus taranmis sayfa."""
    kagit = sayfa()
    h, g = kagit.shape[:2]
    matris = cv2.getRotationMatrix2D((g / 2, h / 2), aci, 1.0)
    return cv2.warpAffine(kagit, matris, (g, h), borderValue=(255, 255, 255))


def jpeg_bayt(rgb, kalite=92):
    tampon = io.BytesIO()
    Image.fromarray(rgb).save(tampon, "JPEG", quality=kalite)
    return tampon.getvalue()


def renkli_belge(boyut=(1240, 1754)):
    """Siyah yazi, mavi murekkep imza, kirmizi muhur ve turuncu logolu sayfa.

    Donus: (rgb, maskeler). maskeler: 'mavi', 'kirmizi', 'turuncu', 'kagit'
    — sayfa koordinatlarinda bool diziler (renk korunumu testleri icin)."""
    g, y = boyut
    rgb = sayfa(boyut).copy()
    mavi = np.zeros((y, g), np.uint8)
    kirmizi = np.zeros((y, g), np.uint8)
    turuncu = np.zeros((y, g), np.uint8)

    # Mavi imza: el yazisi benzeri kalin egri
    xs = np.linspace(g * 0.55, g * 0.85, 60)
    ys = y * 0.80 + np.sin(np.linspace(0, 5 * np.pi, 60)) * y * 0.02
    imza = np.stack([xs, ys], axis=1).astype(np.int32)
    cv2.polylines(mavi, [imza], False, 255, thickness=max(4, g // 250))
    # Kirmizi muhur: halka + ic halka + yazi benzeri cizgiler
    merkez = (int(g * 0.28), int(y * 0.80))
    r = int(g * 0.09)
    cv2.circle(kirmizi, merkez, r, 255, thickness=max(5, g // 200))
    cv2.circle(kirmizi, merkez, int(r * 0.75), 255, thickness=max(3, g // 400))
    for i in range(3):
        cv2.line(kirmizi, (merkez[0] - r // 2, merkez[1] - r // 4 + i * r // 4),
                 (merkez[0] + r // 2, merkez[1] - r // 4 + i * r // 4), 255, max(3, g // 400))
    # Turuncu logo: kose
    cv2.rectangle(turuncu, (int(g * 0.78), int(y * 0.04)), (int(g * 0.92), int(y * 0.07)), 255, -1)

    rgb[mavi > 0] = (30, 60, 200)
    rgb[kirmizi > 0] = (200, 30, 40)
    rgb[turuncu > 0] = (245, 140, 20)
    koyu = rgb.min(axis=2) < 200
    kagit_maskesi = ~cv2.dilate(koyu.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    return rgb, {"mavi": mavi > 0, "kirmizi": kirmizi > 0, "turuncu": turuncu > 0, "kagit": kagit_maskesi}


def isik_bozulmasi(rgb, sari=True, golge=True, tohum=3):
    """Telefon cekimindeki sari ampul isigi, capraz isik azalmasi ve el/telefon
    golgesi (yumusak kenarli koyu leke) ekler."""
    rng = np.random.default_rng(tohum)
    y, g = rgb.shape[:2]
    carpan = np.ones((y, g, 3), np.float32)
    if sari:
        carpan *= np.array([1.0, 0.90, 0.68], np.float32)  # R, G, B
    if golge:
        yy, xx = np.mgrid[0:y, 0:g].astype(np.float32)
        carpan *= (1.0 - 0.35 * (xx / g + yy / y) / 2)[..., None]  # capraz isik azalmasi
        leke = np.zeros((y, g), np.float32)
        cv2.ellipse(leke, (int(g * 0.8), int(y * 0.35)), (int(g * 0.35), int(y * 0.2)), 30, 0, 360, 1.0, -1)
        leke = cv2.GaussianBlur(leke, (0, 0), g * 0.06)
        carpan *= (1.0 - 0.45 * leke)[..., None]
    sonuc = rgb.astype(np.float32) * carpan + rng.normal(0, 3, rgb.shape)
    return sonuc.clip(0, 255).astype(np.uint8)
