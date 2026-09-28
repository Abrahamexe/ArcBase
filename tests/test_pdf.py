"""Aranabilir A4 PDF indirme: metin katmani (arama/secim), A4 yerlesimi
(dikey/yatay, ortalanmis, esit kenar), boyut, meta veri, veri ayrimi."""

import cv2
import numpy as np
import pymupdf
import pytest

import alanlar
import crypto
import database
from conftest import ocr_gerekli
from ornek_gorseller import SATIRLAR, isik_bozulmasi, jpeg_bayt, masada_egik_cekim, renkli_belge, sayfa

pytestmark = ocr_gerekli


def _gorsel_belge(kullanici_id, gorsel, **ek):
    veri = jpeg_bayt(gorsel)
    return database.belge_ekle(
        kullanici_id=kullanici_id, dosya_adi="foto.jpg", mime_type="image/jpeg",
        sifreli_icerik=crypto.sifrele(veri), sifreli_onizleme=None,
        ocr_metni="\n".join(SATIRLAR), tur="fatura", guven=0.9, aciklama="", orijinal_saklandi=True, **ek,
    )


def _pdf(c, belge_id, mod="renkli"):
    r = c.get(f"/belge/{belge_id}/pdf?mod={mod}")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    return r, pymupdf.open("pdf", r.data)


def test_aranabilir_a4_pdf(girisli):
    c, k = girisli
    rgb, _ = renkli_belge()
    belge_id = _gorsel_belge(
        k["id"], isik_bozulmasi(rgb),
        alanlar=alanlar.dogrula("fatura", {"belge_tarihi": "2026-03-15"})[0],
    )
    r, pdf = _pdf(c, belge_id)
    assert r.headers["Content-Disposition"] == "attachment; filename=fatura_2026-03-15.pdf"
    assert pdf.page_count == 1
    s = pdf[0]
    assert (round(s.rect.width), round(s.rect.height)) == (595, 842)  # A4 dikey

    # Metin katmani: secilebilir ve aranabilir
    metin = s.get_text()
    assert "Fatura No" in metin and "ABC2026000000123" in metin
    bulunan = s.search_for("ABC2026000000123")
    assert bulunan

    # Goruntu ortalanmis, esit kenar bosluklu; metin goruntunun ustunde dogru yerde
    goruntu = pymupdf.Rect(s.get_image_info()[0]["bbox"])
    assert abs(goruntu.x0 - (s.rect.width - goruntu.x1)) < 1 and abs(goruntu.y0 - (s.rect.height - goruntu.y1)) < 1
    assert min(goruntu.x0, goruntu.y0) >= 27
    assert goruntu.contains(bulunan[0])
    # "Fatura No" satiri sayfanin ustunde (orijinalde ~%15 yukseklikte)
    assert (bulunan[0].y0 - goruntu.y0) / goruntu.height < 0.3

    assert pdf.metadata["title"] == "Fatura 15.03.2026" and pdf.metadata["creator"] == "ArcBase"
    assert len(r.data) < 1024 * 1024


def test_yatay_belge_yatay_a4(girisli):
    c, k = girisli
    yatay = np.ascontiguousarray(np.rot90(sayfa()))  # 1754x1240 -> yatay
    belge_id = _gorsel_belge(k["id"], yatay)
    r, pdf = _pdf(c, belge_id)
    s = pdf[0]
    assert (round(s.rect.width), round(s.rect.height)) == (842, 595)
    # yukleme tarihi kullanilir (belge tarihi yok)
    assert r.headers["Content-Disposition"].startswith("attachment; filename=fatura_20")


def test_siyah_beyaz_kucuk_ve_1_bit(girisli):
    c, k = girisli
    rgb, _ = renkli_belge()
    belge_id = _gorsel_belge(k["id"], isik_bozulmasi(rgb))
    renkli, _ = _pdf(c, belge_id, "renkli")
    sb, pdf = _pdf(c, belge_id, "sb")
    assert len(sb.data) < len(renkli.data) / 2
    assert pdf[0].get_images(full=True)[0][4] == 1  # bit derinligi
    assert "Genel Toplam" in pdf[0].get_text()
    gri, pdf_gri = _pdf(c, belge_id, "gri")
    assert len(gri.data) < 1024 * 1024 and "Fatura" in pdf_gri[0].get_text()


def test_koseler_uygulanir(girisli):
    """Masada cekilmis fotograf: PDF'e kirpilmis/duzeltilmis hali girer."""
    c, k = girisli
    koseler = ((0.28, 0.10), (0.72, 0.04), (0.78, 0.92), (0.30, 0.97))
    foto = masada_egik_cekim(koseler=koseler)
    belge_id = _gorsel_belge(k["id"], foto, koseler=[[3000 * x, 2250 * y] for x, y in koseler])
    _, pdf = _pdf(c, belge_id)
    s = pdf[0]
    assert s.rect.height > s.rect.width  # yatay fotograf dik sayfaya duzeldi
    assert "ABC2026000000123" in s.get_text()


def test_pdf_belgenin_orijinali_verilir(girisli):
    c, k = girisli
    kaynak = pymupdf.open()
    kaynak.new_page().insert_text((72, 100), "Orijinal PDF metni", fontsize=14)
    veri = kaynak.tobytes()
    belge_id = database.belge_ekle(
        kullanici_id=k["id"], dosya_adi="a.pdf", mime_type="application/pdf",
        sifreli_icerik=crypto.sifrele(veri), sifreli_onizleme=None,
        ocr_metni="", tur="sozlesme", guven=0.9, aciklama="",
    )
    r = c.get(f"/belge/{belge_id}/pdf?mod=sb")
    assert r.data == veri and "sozlesme_" in r.headers["Content-Disposition"]


def test_eski_v4_belgesinden_pdf(girisli):
    """orijinal_saklandi olmayan (v3/v4) gorsellerden de PDF uretilir."""
    c, k = girisli
    veri = jpeg_bayt(sayfa())
    belge_id = database.belge_ekle(
        kullanici_id=k["id"], dosya_adi="eski.jpg", mime_type="image/jpeg",
        sifreli_icerik=crypto.sifrele(veri), sifreli_onizleme=None,
        ocr_metni="", tur="fatura", guven=0.9, aciklama="", otomatik_duzeltildi=True,
    )
    _, pdf = _pdf(c, belge_id)
    assert "Genel Toplam" in pdf[0].get_text()


def test_pdf_veri_ayrimi_ve_giris(girisli, kullanici, istemci):
    c, _ = girisli
    diger = kullanici()
    yabanci = _gorsel_belge(diger["id"], sayfa())
    assert c.get(f"/belge/{yabanci}/pdf").status_code == 404
    r = istemci.get(f"/belge/{yabanci}/pdf")
    assert r.status_code == 302 and "/giris" in r.headers["Location"]


def test_detay_sayfasinda_pdf_butonlari(girisli):
    c, k = girisli
    belge_id = _gorsel_belge(k["id"], cv2.resize(sayfa(), (300, 424)))
    html = c.get(f"/belge/{belge_id}?mod=gri").get_data(as_text=True)
    assert f'href="/belge/{belge_id}/pdf?mod=gri"' in html  # secili modla
    for mod in ("renkli", "gri", "sb"):
        assert f"/belge/{belge_id}/pdf?mod={mod}" in html
    assert "Orijinali indir" in html
    # orijinal gorunumdeyken PDF renkli uretilir
    assert f'href="/belge/{belge_id}/pdf?mod=renkli" download data-pdf-indir' in c.get(
        f"/belge/{belge_id}?mod=orijinal").get_data(as_text=True)


# ---------------------------------------------------------------- coklu belge birlestirme

def _pdf_belge(kullanici_id, sayfa_metinleri):
    kaynak = pymupdf.open()
    for metin in sayfa_metinleri:
        kaynak.new_page().insert_text((72, 100), metin, fontsize=14)
    return database.belge_ekle(
        kullanici_id=kullanici_id, dosya_adi="sozlesme.pdf", mime_type="application/pdf",
        sifreli_icerik=crypto.sifrele(kaynak.tobytes()), sifreli_onizleme=None,
        ocr_metni="", tur="sozlesme", guven=0.9, aciklama="",
    )


def _birlestir(c, kimlikler, mod="renkli", **ek):
    return c.post("/pdf-birlestir", data={"belge": [str(i) for i in kimlikler], "mod": mod}, **ek)


def test_secim_sirasiyla_birlestirilir_yer_imleri(girisli):
    c, k = girisli
    birinci = _gorsel_belge(k["id"], sayfa(satirlar=["BIRINCI BELGE", "Fatura No: 111"]),
                            alanlar=alanlar.dogrula("fatura", {"belge_tarihi": "2026-01-05"})[0])
    ikinci = _gorsel_belge(k["id"], sayfa(satirlar=["IKINCI BELGE", "Fatura No: 222"]))
    pdf_id = _pdf_belge(k["id"], ["Sozlesme sayfa bir", "Sozlesme sayfa iki"])

    r = _birlestir(c, [ikinci, pdf_id, birinci, ikinci])  # tekrar eden id bir kez
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    assert r.headers["Content-Disposition"].startswith("attachment; filename=arsiv_birlesik_20")
    pdf = pymupdf.open("pdf", r.data)
    assert pdf.page_count == 4
    assert "IKINCI BELGE" in pdf[0].get_text()
    assert "Sozlesme sayfa bir" in pdf[1].get_text() and "Sozlesme sayfa iki" in pdf[2].get_text()
    assert "BIRINCI BELGE" in pdf[3].get_text()
    for s in (pdf[0], pdf[3]):
        assert (round(s.rect.width), round(s.rect.height)) == (595, 842)
    yer_imleri = pdf.get_toc()
    assert [sayfa_no for _, _, sayfa_no in yer_imleri] == [1, 2, 4]
    assert yer_imleri[0][1].startswith("Fatura · ") and yer_imleri[0][1].endswith("· foto.jpg")
    assert yer_imleri[1][1].startswith("Sözleşme · ") and yer_imleri[1][1].endswith("sozlesme.pdf")
    assert "05.01.2026" in yer_imleri[2][1]


def test_yirmi_belge_siniri(girisli):
    c, k = girisli
    kimlikler = list(range(1, 22))  # 21 belge: sahiplik kontrolunden once reddedilir
    r = _birlestir(c, kimlikler, headers={"Accept": "application/json"})
    assert r.status_code == 400 and "en fazla 20 belge" in r.get_json()["hata"]
    r = _birlestir(c, kimlikler, headers={"Referer": "http://localhost/kategori/fatura"}, follow_redirects=True)
    assert "en fazla 20 belge" in r.get_data(as_text=True)
    assert _birlestir(c, [], headers={"Accept": "application/json"}).status_code == 400


def test_birlestirmede_baskasinin_belgesi_404(girisli, kullanici):
    c, k = girisli
    benim = _gorsel_belge(k["id"], sayfa())
    diger = kullanici()
    yabanci = _gorsel_belge(diger["id"], sayfa())
    assert _birlestir(c, [benim, yabanci]).status_code == 404


def test_secim_arayuzu_sayfalarda(girisli):
    c, k = girisli
    belge_id = _gorsel_belge(k["id"], sayfa())
    for adres in ("/kategori/fatura", "/ara?q=foto"):
        html = c.get(adres).get_data(as_text=True)
        assert "data-secim-ac" in html and "data-secim-cubugu" in html and 'data-sinir="20"' in html
        assert f'data-belge-id="{belge_id}"' in html
