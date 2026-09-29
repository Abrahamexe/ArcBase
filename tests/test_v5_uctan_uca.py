"""v5 uctan uca: zor bir telefon fotografi yukleme akisindan gecer (gercek
OCR), aranabilir PDF / Word / tarama onizlemesi uretilir; eski v3/v4
belgeleri tum yeni yollarda acilir; v5 uc noktalarinda veri ayrimi."""

import io
import json

import cv2
import numpy as np
import pymupdf
import pytest
from docx import Document
from PIL import Image

import crypto
import database
import ocr
from conftest import belge_ekle, isleme_durumu, jpeg, ocr_gerekli, yukle
from ornek_gorseller import (
    COK_EGIK,
    isik_bozulmasi,
    jpeg_bayt,
    masada_egik_cekim,
    renkli_belge,
    sayfa,
)


@pytest.mark.slow
@ocr_gerekli
def test_zor_fotograf_yuklemeden_aranabilir_pdfe(girisli):
    """Sari isikli, golgeli, ~30 derece yamuk, acik renkli masada cekilmis,
    muhurlu ve imzali renkli belge."""
    c, k = girisli
    rgb, _ = renkli_belge()
    foto = isik_bozulmasi(masada_egik_cekim(koseler=COK_EGIK, kagit=rgb, zemin_tonu=200, tohum=5))
    r = yukle(c, jpeg_bayt(foto), "zor_fatura.jpg", headers={"Accept": "application/json"})
    veri = r.get_json()
    assert veri["basarili"]
    belge_id = veri["belge_id"]
    assert isleme_durumu(c, belge_id)["kirpma_kontrol"] is False

    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["koseler"] and kayit["orijinal_saklandi"] and kayit["otomatik_duzeltildi"]
    assert "ABC2026000000123" in kayit["ocr_metni"]  # OCR duzeltilmis goruntude

    # Renkli tarama: kagit beyaz, kirmizi muhur hala kirmizi
    tarama = cv2.imdecode(np.frombuffer(c.get(f"/tarama/{belge_id}?mod=renkli").data, np.uint8), cv2.IMREAD_COLOR)
    y, g = tarama.shape[:2]
    assert y > g  # dik sayfa
    assert (tarama[int(y * 0.3):int(y * 0.6), int(g * 0.6):int(g * 0.95)].min(axis=2) > 235).mean() > 0.9
    muhur = tarama[int(y * 0.70):int(y * 0.90), int(g * 0.15):int(g * 0.40)].reshape(-1, 3).astype(int)
    kirmizi = muhur[(muhur[:, 2] > 150) & (muhur[:, 1] < 90) & (muhur[:, 0] < 90)]
    assert len(kirmizi) > 500

    # Aranabilir A4 PDF
    pdf = pymupdf.open("pdf", c.get(f"/belge/{belge_id}/pdf?mod=renkli").data)
    s = pdf[0]
    assert (round(s.rect.width), round(s.rect.height)) == (595, 842)
    assert s.search_for("ABC2026000000123") and s.search_for("Genel Toplam")

    # Word
    doc = Document(io.BytesIO(c.get(f"/belge/{belge_id}/word").data))
    assert any("ABC2026000000123" in p.text for p in doc.paragraphs)


def _eski(kullanici_id, surum):
    veri = jpeg_bayt(sayfa())
    ek = {"otomatik_duzeltildi": True} if surum == "v4-duzeltilmis" else {}
    return database.belge_ekle(
        kullanici_id=kullanici_id, dosya_adi=f"{surum}.jpg", mime_type="image/jpeg",
        sifreli_icerik=crypto.sifrele(veri), sifreli_onizleme=crypto.sifrele(veri),
        ocr_metni="FATURA metni", tur="fatura", guven=0.9, aciklama="eski", **ek,
    ), veri


@pytest.mark.slow
@ocr_gerekli
@pytest.mark.parametrize("surum", ["v3", "v4-duzeltilmis"])
def test_eski_belgeler_tum_yeni_yollarda_acilir(girisli, surum):
    c, k = girisli
    belge_id, veri = _eski(k["id"], surum)
    assert c.get(f"/belge/{belge_id}").status_code == 200
    assert c.get(f"/belge/{belge_id}/indir").data == veri
    assert c.get(f"/gorsel/{belge_id}").data == veri
    for mod in ("renkli", "gri", "sb", "orijinal"):
        assert c.get(f"/tarama/{belge_id}?mod={mod}").status_code == 200
    assert "Genel Toplam" in pymupdf.open("pdf", c.get(f"/belge/{belge_id}/pdf").data)[0].get_text()
    assert c.get(f"/belge/{belge_id}/word").status_code == 200
    birlesik = c.post("/pdf-birlestir", data={"belge": [str(belge_id)], "mod": "gri"})
    assert pymupdf.open("pdf", birlesik.data).page_count == 1


def test_v5_uc_noktalarinda_veri_ayrimi(girisli, kullanici, monkeypatch):
    """B kullanicisi A'nin belgesine v5'in hicbir yolundan erisemez ve
    degistiremez; yanitlar 404'tur (belgenin varligi belli edilmez)."""
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "DEGISTI")
    c, _ = girisli
    a = kullanici()
    veri = jpeg_bayt(np.full((300, 400, 3), 255, np.uint8))
    yabanci = database.belge_ekle(
        kullanici_id=a["id"], dosya_adi="a_gizli.jpg", mime_type="image/jpeg",
        sifreli_icerik=crypto.sifrele(veri), sifreli_onizleme=None,
        ocr_metni="GIZLI", tur="fatura", guven=0.9, aciklama="", orijinal_saklandi=True,
        koseler=[[10, 10], [390, 10], [390, 290], [10, 290]],
    )
    for adres in (
        f"/tarama/{yabanci}?mod=renkli", f"/gorsel/{yabanci}?ham=1", f"/belge/{yabanci}/koseler/otomatik",
        f"/belge/{yabanci}/pdf", f"/belge/{yabanci}/word",
    ):
        r = c.get(adres)
        assert r.status_code == 404 and b"a_gizli" not in r.data, adres
    kose = json.dumps([[0, 0], [400, 0], [400, 300], [0, 300]])
    assert c.post(f"/belge/{yabanci}/koseler", data={"koseler": kose}).status_code == 404
    assert c.post(f"/belge/{yabanci}/yeniden-analiz").status_code == 404
    assert c.post("/pdf-birlestir", data={"belge": [str(yabanci)]}).status_code == 404

    kayit = database.belge_getir(a["id"], yabanci)
    assert kayit["ocr_metni"] == "GIZLI" and kayit["koseler"] == [[10, 10], [390, 10], [390, 290], [10, 290]]
    assert database.koseleri_guncelle(girisli[1]["id"], yabanci, None, None, "x") is False


def test_koseler_yeni_yuklemede_saklanan_gorsele_olceklenir(girisli, monkeypatch):
    """4000 px fotograf 2000 px saklanir; koseler saklanan koordinatlarda."""
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    c, k = girisli
    koseler = ((0.28, 0.10), (0.72, 0.04), (0.78, 0.92), (0.30, 0.97))
    foto = masada_egik_cekim(tuval=(4000, 3000), koseler=koseler)
    belge_id = int(yukle(c, jpeg_bayt(foto), "buyuk.jpg").headers["Location"].rsplit("/", 1)[1])
    icerik = database.belge_icerigi(k["id"], belge_id)
    assert Image.open(io.BytesIO(crypto.coz(icerik["veri"]))).size == (2000, 1500)
    beklenen = np.float32([[2000 * x, 1500 * y] for x, y in koseler])
    assert np.abs(np.float32(icerik["koseler"]) - beklenen).max() < 0.01 * 2500


def test_kucuk_gorsel_yuklenir(girisli, monkeypatch):
    """Algilama yapilamayacak kadar kucuk gorsel sorunsuz kaydedilir."""
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    c, k = girisli
    r = yukle(c, jpeg(), "kucuk.jpg")
    assert r.status_code == 302
    icerik = database.belge_icerigi(k["id"], int(r.headers["Location"].rsplit("/", 1)[1]))
    assert icerik["koseler"] is None and icerik["orijinal_saklandi"]
    assert belge_ekle  # conftest yardimcisi (kullanilmayan import uyarisi olmasin)
