"""Belge ozellikleri: yukleme (OCR), sikistirma, PDF, kota, Groq 429,
tur duzeltme, silme, indirme, kategori, arama."""

import io

import pytest
from PIL import Image

import app as uygulama_modulu
import classifier
import crypto
import database
import isleme
import ocr
from conftest import (
    GERCEK_SINIFLANDIR,
    bayt,
    belge_ekle,
    gorsel_boyutu,
    jpeg,
    ocr_gerekli,
    yazili_gorsel,
    yukle,
)


def belge_id(yanit):
    assert yanit.status_code == 302, yanit.get_data(as_text=True)[:300]
    return int(yanit.headers["Location"].rsplit("/", 1)[1])


# ---------------------------------------------------------------- yukleme + OCR

@pytest.mark.slow
@ocr_gerekli
def test_gorsel_yukleme_ocr_ve_siniflandirma(girisli):
    c, k = girisli
    r = yukle(c, bayt(yazili_gorsel()), "fatura.png")
    kayit = database.belge_getir(k["id"], belge_id(r))
    assert "FATURA" in kayit["ocr_metni"].upper()
    assert kayit["tur"] == "fatura"
    assert kayit["onizleme_var"]
    sayfa = c.get(f"/belge/{kayit['id']}").get_data(as_text=True)
    assert "fatura.jpg" in sayfa and "Fatura No" in sayfa


@pytest.mark.slow
@ocr_gerekli
def test_pdf_yukleme_oldugu_gibi_saklanir(girisli):
    import pymupdf

    c, k = girisli
    belge = pymupdf.open()
    sayfa = belge.new_page()
    sayfa.insert_text((72, 100), "FATURA  Fatura No: 2026-000999", fontsize=20)
    pdf = belge.tobytes()
    kayit_id = belge_id(yukle(c, pdf, "fatura.pdf"))
    kayit = database.belge_getir(k["id"], kayit_id)
    assert kayit["mime_type"] == "application/pdf" and kayit["dosya_adi"] == "fatura.pdf"
    assert "2026-000999" in kayit["ocr_metni"]
    assert crypto.coz(database.belge_icerigi(k["id"], kayit_id)["veri"]) == pdf
    gorsel = c.get(f"/gorsel/{kayit_id}")
    assert gorsel.mimetype == "image/png"  # PDF'in ilk sayfasi
    indir = c.get(f"/belge/{kayit_id}/indir")
    assert indir.mimetype == "application/pdf" and indir.data == pdf


def test_ocr_basarisiz_olsa_da_belge_kaydedilir(girisli, monkeypatch):
    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: (_ for _ in ()).throw(RuntimeError("tesseract yok")))
    r = yukle(c, jpeg(), "okunmaz.jpg", follow_redirects=True)
    assert "Metin çıkarılamadı" in r.get_data(as_text=True)
    assert database.belgeleri_listele(k["id"])[0]["tur"] == "diger"


@pytest.mark.parametrize(
    "veri, ad, mesaj",
    [
        (b"", "bos.jpg", "Lütfen bir dosya seçin"),
        (b"abc", "belge.txt", "Sadece JPG, PNG ve PDF"),
    ],
)
def test_gecersiz_yuklemeler(girisli, veri, ad, mesaj):
    c, k = girisli
    if not veri:
        r = c.post("/yukle", data={}, follow_redirects=True)
    else:
        r = yukle(c, veri, ad, follow_redirects=True)
    assert mesaj in r.get_data(as_text=True)
    assert database.belge_sayisi(k["id"]) == 0


def test_cok_buyuk_dosya_413(girisli):
    c, k = girisli
    r = yukle(c, b"0" * (10 * 1024 * 1024 + 1), "dev.jpg", follow_redirects=True)
    assert "En fazla 10 MB" in r.get_data(as_text=True)
    assert database.belge_sayisi(k["id"]) == 0


def test_pdf_5mb_siniri(girisli):
    c, k = girisli
    r = yukle(c, b"%PDF-1.4" + b"0" * (5 * 1024 * 1024), "buyuk.pdf", follow_redirects=True)
    assert "en fazla 5 MB" in r.get_data(as_text=True)
    assert database.belge_sayisi(k["id"]) == 0


# ---------------------------------------------------------------- sikistirma

def test_buyuk_png_kucultulup_jpeg_saklanir(girisli, monkeypatch):
    c, k = girisli
    okunan = {}

    def sahte_ocr(veri, mime):
        okunan["boyut"] = gorsel_boyutu(veri)
        return "FATURA"

    monkeypatch.setattr(ocr, "metin_cikar", sahte_ocr)
    orijinal = bayt(yazili_gorsel((3000, 4000)), "PNG")
    kayit_id = belge_id(yukle(c, orijinal, "Buyuk Fatura.png"))

    # OCR saklanan (2000 px) gorselde degil, OCR cozunurlugune indirilmis
    # goruntude yapildi (gri tarama kenardan birkac px kirpar)
    assert 2000 < max(okunan["boyut"]) <= isleme.OCR_UZUN_KENAR
    assert okunan["boyut"][1] > isleme.OCR_UZUN_KENAR - 30
    kayit = database.belge_getir(k["id"], kayit_id)
    assert kayit["mime_type"] == "image/jpeg" and kayit["dosya_adi"] == "Buyuk_Fatura.jpg"
    saklanan = crypto.coz(database.belge_icerigi(k["id"], kayit_id)["veri"])
    g = Image.open(io.BytesIO(saklanan))
    assert g.format == "JPEG" and max(g.size) == 2000 and g.size == (1500, 2000)
    assert len(saklanan) < len(orijinal)

    indir = c.get(f"/belge/{kayit_id}/indir")
    assert indir.mimetype == "image/jpeg" and indir.data == saklanan
    sayfa = c.get(f"/belge/{kayit_id}").get_data(as_text=True)
    assert "Orijinali indir" in sayfa and "küçültülüp sıkıştırılmış" in sayfa


def test_sikistirma_exif_yonu_ve_temizligi():
    exif = Image.Exif()
    exif[0x0112] = 6  # 90 derece dondurulmus olarak gosterilmeli
    veri = bayt(Image.new("RGB", (1600, 1200), "white"), "JPEG", exif=exif.tobytes())
    g = Image.open(io.BytesIO(ocr.gorsel_sikistir(veri)))
    assert g.size == (1200, 1600)
    assert len(g.getexif()) == 0


def test_sikistirma_kucuk_gorseli_buyutmez_ve_saydamligi_beyaz_yapar():
    saydam = bayt(Image.new("RGBA", (300, 200), (0, 0, 0, 0)), "PNG")
    g = Image.open(io.BytesIO(ocr.gorsel_sikistir(saydam)))
    assert g.size == (300, 200) and g.mode == "RGB" and g.getpixel((5, 5)) == (255, 255, 255)


# ---------------------------------------------------------------- kota

def test_kota_dolunca_yukleme_engellenir(girisli, monkeypatch):
    c, k = girisli
    monkeypatch.setattr(uygulama_modulu, "KULLANICI_BELGE_LIMITI", 2)
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    belge_ekle(k["id"])
    assert yukle(c, jpeg(), "ikinci.jpg").status_code == 302
    assert database.belge_sayisi(k["id"]) == 2

    r = yukle(c, jpeg(), "ucuncu.jpg", follow_redirects=True)
    assert "Belge kotanız doldu" in r.get_data(as_text=True)
    assert database.belge_sayisi(k["id"]) == 2

    panel = c.get("/").get_data(as_text=True)
    assert "data-kota-doldu" in panel and "data-yukleme-formu" not in panel
    assert "/ 2 belge" in c.get("/hesap").get_data(as_text=True)


# ---------------------------------------------------------------- Groq

def test_groq_429_diger_olarak_kaydedilir(girisli, monkeypatch):
    import openai

    try:
        import httpx2 as httpx
    except ImportError:  # openai'nin eski surumleri
        import httpx

    class SahteIstemci:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    yanit = httpx.Response(429, request=httpx.Request("POST", "https://groq"))
                    raise openai.RateLimitError("rate limit", response=yanit, body=None)

    # conftest'teki sahte siniflandirma yerine gercek fonksiyon + sahte istemci
    monkeypatch.setattr(classifier, "siniflandir", GERCEK_SINIFLANDIR)
    monkeypatch.setattr(classifier, "_istemci_olustur", lambda: SahteIstemci)
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA metni")

    r = yukle(girisli[0], jpeg(), "yogun.jpg", follow_redirects=True)
    assert "Yapay zeka şu an yoğun" in r.get_data(as_text=True)
    kayit = database.belgeleri_listele(girisli[1]["id"])[0]
    assert kayit["tur"] == "diger" and kayit["guven"] == 0


def test_groq_yanit_duzeltme():
    assert classifier._turu_duzelt(" Resmi yazi ") == "resmi_yazi"
    assert classifier._turu_duzelt("FATURA") == "fatura"
    assert classifier._turu_duzelt("makbuz") == "diger"
    assert classifier._turu_duzelt(None) == "diger"
    assert classifier._guveni_duzelt(87) == pytest.approx(0.87)
    assert classifier._guveni_duzelt("abc") == 0.0
    assert classifier._guveni_duzelt(-3) == 0.0


# ---------------------------------------------------------------- mevcut ozellikler

def test_tur_duzeltme(girisli):
    c, k = girisli
    kayit_id = belge_ekle(k["id"], tur="fatura")
    assert c.post(f"/belge/{kayit_id}/tur", data={"tur": "gecersiz"}).status_code == 302
    assert database.belge_getir(k["id"], kayit_id)["tur"] == "fatura"
    r = c.post(f"/belge/{kayit_id}/tur", data={"tur": "kimlik"}, follow_redirects=True)
    assert "Kimlik" in r.get_data(as_text=True)
    kayit = database.belge_getir(k["id"], kayit_id)
    assert kayit["tur"] == "kimlik" and kayit["elle_duzeltildi"]


def test_silme(girisli):
    c, k = girisli
    kayit_id = belge_ekle(k["id"])
    r = c.post(f"/belge/{kayit_id}/sil", follow_redirects=True)
    assert "Belge silindi" in r.get_data(as_text=True)
    assert database.belge_getir(k["id"], kayit_id) is None
    assert c.get(f"/belge/{kayit_id}").status_code == 404


def test_indirme_onizleme_gorsel(girisli):
    c, k = girisli
    kayit_id = belge_ekle(k["id"], "ornek.jpg")
    indir = c.get(f"/belge/{kayit_id}/indir")
    assert indir.status_code == 200 and "attachment" in indir.headers["Content-Disposition"]
    assert "ornek.jpg" in indir.headers["Content-Disposition"]
    assert c.get(f"/onizleme/{kayit_id}").mimetype == "image/jpeg"
    assert c.get(f"/gorsel/{kayit_id}").mimetype == "image/jpeg"


def test_kategori_arama_ve_sayfalama(girisli):
    c, k = girisli
    for i in range(14):
        belge_ekle(k["id"], f"fatura_{i:02}.jpg", "fatura", f"Ortak kelime ZETA{i}")
    belge_ekle(k["id"], "dilekce.jpg", "dilekce", "baska metin")

    ilk = c.get("/kategori/fatura").get_data(as_text=True)
    assert ilk.count('class="belge-karti') == 12 and "dilekce.jpg" not in ilk
    ikinci = c.get("/kategori/fatura?sayfa=2").get_data(as_text=True)
    assert ikinci.count('class="belge-karti') == 2
    assert c.get("/kategori/olmayan").status_code == 404

    arama = c.get("/ara?q=zeta").get_data(as_text=True)  # buyuk/kucuk harf duyarsiz
    assert "14</span> sonuç" in arama
    assert "dilekce.jpg" in c.get("/ara?q=dilekce").get_data(as_text=True)
    suzgec = c.get("/ara?q=metin&tur=dilekce").get_data(as_text=True)
    assert "dilekce.jpg" in suzgec and "fatura_00" not in suzgec

    panel = c.get("/").get_data(as_text=True)
    assert panel.count('class="belge-karti') == 6  # son 6 belge
    assert 'data-sayac="15"' in panel
