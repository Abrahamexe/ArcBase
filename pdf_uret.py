"""Aranabilir A4 PDF uretimi (Tesseract metin katmani + PyMuPDF yerlesim).

Her sayfa: tarama filtresi uygulanmis goruntu A4'e sigdirilir (en-boy orani
korunur, ortalanir, esit beyaz kenar; yatay belgede yatay A4). Tesseract'tan
yalnizca gorunmez metin katmani alinir (textonly_pdf) ve goruntunun tam
uzerine yerlestirilir; boylece metin secilebilir ve Ctrl+F ile aranabilir.
Goruntu Tesseract'a birakilmaz, kendimiz sikistiririz: renkli/gri JPEG,
siyah-beyaz 1-bit PNG. PDF saklanmaz, her istekte uretilir.
"""

import io
from datetime import datetime

import cv2
import pymupdf
import pytesseract
from PIL import Image

import ocr

A4 = pymupdf.paper_rect("a4")  # 595 x 842 pt
KENAR_BOSLUGU = 28  # pt (~1 cm), dort kenarda esit
JPEG_KALITESI = 80  # renkli/gri sayfa ~1 MB'in altinda kalsin
URETICI = "ArcBase"


def yeni_belge():
    return pymupdf.open()


def _gomulecek(goruntu, mod):
    """Goruntuyu PDF'e gomulecek sikistirilmis baytlara ve PIL goruntusune cevirir."""
    if goruntu.ndim == 3:
        pil = Image.fromarray(cv2.cvtColor(goruntu, cv2.COLOR_BGR2RGB))
    else:
        pil = Image.fromarray(goruntu)
    tampon = io.BytesIO()
    if mod == "sb":
        pil.convert("1").save(tampon, format="PNG", optimize=True)
    else:
        pil.save(tampon, format="JPEG", quality=JPEG_KALITESI, optimize=True)
    return tampon.getvalue(), pil


def _yerlesim(genislik, yukseklik):
    """A4 sayfa (yatay goruntude yatay) ve goruntunun ortalanmis dikdortgeni."""
    sayfa = A4 if yukseklik >= genislik else pymupdf.Rect(0, 0, A4.height, A4.width)
    olcek = min((sayfa.width - 2 * KENAR_BOSLUGU) / genislik, (sayfa.height - 2 * KENAR_BOSLUGU) / yukseklik)
    g, y = genislik * olcek, yukseklik * olcek
    x0, y0 = (sayfa.width - g) / 2, (sayfa.height - y) / 2
    return sayfa, pymupdf.Rect(x0, y0, x0 + g, y0 + y)


def goruntu_sayfasi_ekle(belge, goruntu, mod):
    """Filtrelenmis goruntuyu (BGR veya gri numpy) metin katmanli A4 sayfa olarak
    ekler; eklenen sayfanin numarasini dondurur."""
    gomulecek, pil = _gomulecek(goruntu, mod)
    sayfa_boyutu, alan = _yerlesim(pil.width, pil.height)
    sayfa = belge.new_page(width=sayfa_boyutu.width, height=sayfa_boyutu.height)
    sayfa.insert_image(alan, stream=gomulecek)
    try:
        metin_pdf = pytesseract.image_to_pdf_or_hocr(
            pil if mod != "sb" else pil.convert("L"),
            lang=ocr.DIL,
            extension="pdf",
            config="-c textonly_pdf=1",
        )
        with pymupdf.open("pdf", metin_pdf) as metin:
            # keep_proportion=False: metin katmani goruntuyle birebir ayni alana oturur.
            sayfa.show_pdf_page(alan, metin, 0, keep_proportion=False)
    except Exception:
        pass  # OCR yapilamazsa sayfa yine goruntu olarak eklenir (aranamaz)
    return sayfa.number


def pdf_sayfalari_ekle(belge, pdf_bayti):
    """Yuklenmis PDF'in sayfalarini oldugu gibi ekler; ilk eklenen sayfanin numarasi."""
    ilk = belge.page_count
    with pymupdf.open("pdf", pdf_bayti) as kaynak:
        belge.insert_pdf(kaynak)
    return ilk


def bitir(belge, baslik, yer_imleri=None):
    """Meta veri ve yer imlerini yazip PDF baytlarini dondurur.

    yer_imleri: [(baslik, sayfa_no), ...] (0 tabanli sayfa numarasi)."""
    simdi = datetime.now().strftime("D:%Y%m%d%H%M%S")
    belge.set_metadata({
        "title": baslik,
        "author": URETICI,
        "creator": URETICI,
        "producer": URETICI,
        "creationDate": simdi,
        "modDate": simdi,
    })
    if yer_imleri:
        belge.set_toc([[1, ad, no + 1] for ad, no in yer_imleri])
    return belge.tobytes(garbage=3, deflate=True)
