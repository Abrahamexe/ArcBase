"""PDF/goruntu isleme, OCR oncesi on isleme ve Tesseract ile metin cikarma.

Belgeler diske yazilmadigi icin fonksiyonlar dosya yolu yerine ham baytlarla
(ya da bellekteki goruntu dizileriyle) calisir.
"""

import io
import os
import shutil
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageOps

# PDF destegi opsiyonel: pymupdf kurulu degilse resim yukleme calismaya devam eder.
try:
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None

DIL = "tur"
PDF_SAYFA_SINIRI = 3  # cok sayfali PDF'lerde ilk N sayfa okunur
PDF_DPI = 200  # OCR icin yeterli cozunurluk
PDF_ONIZLEME_DPI = 72  # onizleme 600 px'e kucultulecegi icin dusuk cozunurluk yeter
# Sayfanin metin katmaninda (e-fatura, Word'den PDF) bu kadar harf/rakam varsa
# o sayfa icin OCR yapilmaz; metin katmani OCR'dan hem hizli hem hatasizdir.
PDF_METIN_KATMANI_EN_AZ = 20
ONIZLEME_BOYUTU = (600, 600)
ONIZLEME_KALITESI = 80
SAKLAMA_UZUN_KENAR = 2000  # saklanan gorselin uzun kenari en fazla bu kadar px
SAKLAMA_KALITESI = 85  # JPEG kalitesi
PDF_MIME = "application/pdf"
# --oem 1: yalnizca LSTM motoru; tessedit_do_invert=0: her satiri bir de ters
# renkte (koyu zemin, acik yazi) okumayi denemez. Belgelerde dogruluk ayni,
# OCR biraz daha hizli (README "Performans").
TESSERACT_AYARI = "--oem 1 -c tessedit_do_invert=0"

# Cok sayfali PDF'te sayfalar paralel okunur; her Tesseract sureci tek is
# parcacigi kullanir (OpenMP'li Linux derlemesinde cekirdekler asiri paylasilmasin).
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

# Windows'ta Tesseract genelde PATH'te olmadigi icin bilinen kurulum yollarina bakilir.
_OLASI_YOLLAR = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


class PdfDesteklenmiyor(RuntimeError):
    """pymupdf kurulu degil."""


def _tesseract_yolunu_ayarla():
    """Tesseract calistirilabilir dosyasinin yolunu pytesseract'a bildirir."""
    ortamdan = os.getenv("TESSERACT_CMD")
    if ortamdan:
        pytesseract.pytesseract.tesseract_cmd = ortamdan
        return
    if shutil.which("tesseract"):
        return  # PATH'te var, varsayilan ayar yeterli
    for yol in _OLASI_YOLLAR:
        if os.path.exists(yol):
            pytesseract.pytesseract.tesseract_cmd = yol
            return


_tesseract_yolunu_ayarla()


def on_isle(goruntu):
    """Gri tonlama + otomatik kontrast.

    Telefonla cekilen belge fotograflari taranmis belgelere gore daha dusuk
    kontrastli ve golgeli olabiliyor; bu iki adim OCR dogrulugunu belirgin
    sekilde artiriyor.
    """
    gri = ImageOps.grayscale(goruntu)
    return ImageOps.autocontrast(gri)


def _tesseract(goruntu):
    return pytesseract.image_to_string(on_isle(goruntu), lang=DIL, config=TESSERACT_AYARI)


def _pdf_ac(veri):
    if pymupdf is None:
        raise PdfDesteklenmiyor(
            "PDF okumak için 'pymupdf' paketi gerekli: pip install pymupdf"
        )
    return pymupdf.open(stream=veri, filetype="pdf")


def _sayfa_goruntusu(sayfa, dpi=PDF_DPI, gri=False):
    """PDF sayfasini Pillow goruntusune cevirir (PNG'ye kodlamadan, dogrudan pikseller)."""
    renk_uzayi = pymupdf.csGRAY if gri else pymupdf.csRGB
    pixmap = sayfa.get_pixmap(dpi=dpi, colorspace=renk_uzayi, alpha=False)
    return Image.frombytes("L" if gri else "RGB", (pixmap.width, pixmap.height), pixmap.samples)


def goruntu_al(veri, mime_type, dpi=PDF_DPI):
    """Belgenin ilk sayfasini/karesini Pillow goruntusu olarak dondurur."""
    if mime_type == PDF_MIME:
        with _pdf_ac(veri) as belge:
            if not len(belge):
                raise ValueError("PDF dosyası boş.")
            return _sayfa_goruntusu(belge[0], dpi)
    return Image.open(io.BytesIO(veri))


def _pdf_metni(veri):
    """Ilk PDF_SAYFA_SINIRI sayfanin metni. Metin katmani olan sayfa OCR'siz
    okunur; taranmis sayfalar ayni anda (paralel Tesseract surecleri) okunur.
    pymupdf is parcacigi guvenli olmadigi icin sayfalar once sirayla cizilir."""
    metinler, taranacak = [], []
    with _pdf_ac(veri) as belge:
        for no, sayfa in enumerate(belge[:PDF_SAYFA_SINIRI]):
            katman = sayfa.get_text().strip()
            if sum(k.isalnum() for k in katman) >= PDF_METIN_KATMANI_EN_AZ:
                metinler.append(katman)
            else:
                metinler.append(None)
                taranacak.append((no, _sayfa_goruntusu(sayfa, gri=True)))
    if taranacak:
        with ThreadPoolExecutor(max_workers=min(len(taranacak), os.cpu_count() or 1)) as havuz:
            for (no, _), metin in zip(taranacak, havuz.map(lambda s: _tesseract(s[1]), taranacak)):
                metinler[no] = metin
    return "\n".join(metinler)


def metin_cikar(veri, mime_type):
    """OCR ile metni cikarir.

    veri: dosya baytlari ya da hazirlanmis goruntu dizisi (numpy; arka plan
    iscisi duzeltilmis gri taramayi dogrudan verir, JPEG'e kodlanip yeniden
    acilmaz)."""
    if isinstance(veri, np.ndarray):
        metin = _tesseract(Image.fromarray(veri))
    elif mime_type == PDF_MIME:
        metin = _pdf_metni(veri)
    else:
        with Image.open(io.BytesIO(veri)) as goruntu:
            # Telefon fotograflari yan kaydedilip yonu EXIF'te tutulabiliyor;
            # OCR duz cevrilmis goruntude yapilir.
            metin = _tesseract(ImageOps.exif_transpose(goruntu))
    return metin.strip()


def _jpeg(bgr, kalite):
    tamam, veri = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, kalite, cv2.IMWRITE_JPEG_OPTIMIZE, 1])
    if not tamam:
        raise ValueError("Görüntü JPEG'e çevrilemedi.")
    return veri.tobytes()


def _hedef_boyut(bgr, uzun_kenar):
    y, g = bgr.shape[:2]
    oran = min(1.0, uzun_kenar / max(y, g))
    return max(1, round(g * oran)), max(1, round(y * oran))


def _uzun_kenara(bgr, uzun_kenar):
    boyut = _hedef_boyut(bgr, uzun_kenar)
    if boyut == (bgr.shape[1], bgr.shape[0]):
        return bgr
    return cv2.resize(bgr, boyut, interpolation=cv2.INTER_AREA)


def saklama_boyutu(bgr):
    """gorsel_sikistir_bgr'nin uretecegi (genislik, yukseklik)."""
    return _hedef_boyut(bgr, SAKLAMA_UZUN_KENAR)


def gorsel_sikistir_bgr(bgr):
    """Acilmis (EXIF yonu uygulanmis) gorseli saklamak icin kucultup JPEG'e
    cevirir. Donus: (baytlar, (genislik, yukseklik)). Yeniden kodlama EXIF
    bilgilerini (konum vb.) de temizler."""
    kucuk = _uzun_kenara(bgr, SAKLAMA_UZUN_KENAR)
    return _jpeg(kucuk, SAKLAMA_KALITESI), (kucuk.shape[1], kucuk.shape[0])


def onizleme_bgr(bgr):
    """Grid'lerde gosterilecek kucuk JPEG onizlemesi (acilmis gorselden)."""
    return _jpeg(_uzun_kenara(bgr, max(ONIZLEME_BOYUTU)), ONIZLEME_KALITESI)


def gorsel_sikistir(veri):
    """JPG/PNG gorseli saklamadan once kucultur ve JPEG olarak yeniden kodlar.

    Uzun kenar en fazla SAKLAMA_UZUN_KENAR px olur, EXIF yonu uygulanir.
    Yeniden kodlama EXIF bilgilerini (konum vb.) de temizler.
    """
    with Image.open(io.BytesIO(veri)) as goruntu:
        duz = ImageOps.exif_transpose(goruntu)
        if duz.mode in ("RGBA", "LA", "P"):
            # Saydam PNG'lerde saydam alanlar beyaz olur (JPEG saydamlik desteklemez).
            rgba = duz.convert("RGBA")
            duz = Image.new("RGB", rgba.size, "white")
            duz.paste(rgba, mask=rgba.getchannel("A"))
        else:
            duz = duz.convert("RGB")
        duz.thumbnail((SAKLAMA_UZUN_KENAR, SAKLAMA_UZUN_KENAR), Image.LANCZOS)
        tampon = io.BytesIO()
        duz.save(tampon, format="JPEG", quality=SAKLAMA_KALITESI, optimize=True)
        return tampon.getvalue()


def onizleme_uret(veri, mime_type):
    """Grid'lerde gosterilecek kucuk JPEG onizlemesi uretir.

    Onizleme uretilemezse None doner; belge yine de kaydedilir ve arayuz
    onizleme yerine ikon gosterir.
    """
    try:
        goruntu = goruntu_al(veri, mime_type, dpi=PDF_ONIZLEME_DPI)
        with goruntu:
            if mime_type != PDF_MIME:
                # JPEG'i kucuk olcekte coz (12 MP fotografta ~10 kat hizli).
                goruntu.draft("RGB", ONIZLEME_BOYUTU)
            kucuk = ImageOps.exif_transpose(goruntu).convert("RGB")
            kucuk.thumbnail(ONIZLEME_BOYUTU)
            tampon = io.BytesIO()
            kucuk.save(tampon, format="JPEG", quality=ONIZLEME_KALITESI)
            return tampon.getvalue()
    except Exception:  # bozuk dosya, desteklenmeyen format...
        return None


def goruntu_baytlari(veri, mime_type):
    """Tarayicida gosterilecek goruntuyu dondurur; PDF ise ilk sayfa PNG olur."""
    if mime_type != PDF_MIME:
        return veri, mime_type
    with goruntu_al(veri, mime_type) as goruntu:
        tampon = io.BytesIO()
        goruntu.convert("RGB").save(tampon, format="PNG")
        return tampon.getvalue(), "image/png"
