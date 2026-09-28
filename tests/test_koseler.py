"""Elle kose ayarlama, yeniden OCR, otomatik yeniden algilama ve yapay zeka
ile yeniden analiz; eski belgelerde kose ayarlamanin kapali olmasi."""

import io

import numpy as np
import pytest
from PIL import Image

import classifier
import crypto
import database
import ocr
from conftest import belge_ekle, gorsel_boyutu, jpeg
from ornek_gorseller import jpeg_bayt, masada_egik_cekim

JSON = {"Accept": "application/json"}
DIK = ((0.28, 0.10), (0.72, 0.04), (0.78, 0.92), (0.30, 0.97))


def _gorsel_belge(kullanici_id, gorsel_bayti, **ek):
    return database.belge_ekle(
        kullanici_id=kullanici_id, dosya_adi="foto.jpg", mime_type="image/jpeg",
        sifreli_icerik=crypto.sifrele(gorsel_bayti), sifreli_onizleme=crypto.sifrele(gorsel_bayti),
        ocr_metni="eski metin", tur="fatura", guven=0.9, aciklama="eski", **ek,
    )


def _yaklasik(boyut, beklenen, pay=8):
    """OCR girdisi gri taramadir; tarama kenardan birkac px kirpar."""
    return all(0 <= b - a <= pay for a, b in zip(boyut, beklenen))


@pytest.fixture
def okunan(monkeypatch):
    """OCR'a giden goruntunun boyutunu kaydeden sahte OCR."""
    kayit = {}

    def sahte(veri, mime):
        kayit["boyut"] = gorsel_boyutu(veri)
        return "YENI OKUNAN METIN FATURA"

    monkeypatch.setattr(ocr, "metin_cikar", sahte)
    return kayit


def _kaydet(c, belge_id, koseler, **ek):
    import json

    deger = "" if koseler is None else json.dumps(koseler)
    return c.post(f"/belge/{belge_id}/koseler", data={"koseler": deger}, headers=JSON, **ek)


def test_elle_koseler_kaydedilir_ocr_yenilenir(girisli, okunan):
    c, k = girisli
    veri = jpeg_bayt(np.full((600, 800, 3), 255, np.uint8))
    belge_id = _gorsel_belge(k["id"], veri, orijinal_saklandi=True, otomatik_duzeltildi=True,
                             koseler=[[0, 0], [800, 0], [800, 600], [0, 600]])
    r = _kaydet(c, belge_id, [[100, 100], [500, 100], [500, 400], [100, 400]])
    assert r.status_code == 200 and r.get_json()["basarili"]
    assert "yeniden okundu" in r.get_json()["mesaj"]
    assert _yaklasik(okunan["boyut"], (400, 300))  # OCR duzeltilmis goruntude

    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["koseler"] == [[100, 100], [500, 100], [500, 400], [100, 400]]
    assert kayit["ocr_metni"] == "YENI OKUNAN METIN FATURA"
    assert kayit["orijinal_saklandi"] and not kayit["otomatik_duzeltildi"]
    assert Image.open(io.BytesIO(c.get(f"/gorsel/{belge_id}").data)).size == (400, 300)
    assert Image.open(io.BytesIO(c.get(f"/gorsel/{belge_id}?ham=1").data)).size == (800, 600)
    onizleme = Image.open(io.BytesIO(c.get(f"/onizleme/{belge_id}").data))
    assert abs(onizleme.width / onizleme.height - 4 / 3) < 0.05

    sayfa = c.get(f"/belge/{belge_id}").get_data(as_text=True)
    assert "Kırpma elle ayarlandı" in sayfa and "data-yeniden-analiz-onerisi" in sayfa
    # oneri bir kez gosterilir
    assert "data-yeniden-analiz-onerisi" not in c.get(f"/belge/{belge_id}").get_data(as_text=True)


def test_tum_gorsel_duzeltmeyi_kaldirir(girisli, okunan):
    c, k = girisli
    veri = jpeg_bayt(np.full((300, 400, 3), 255, np.uint8))
    belge_id = _gorsel_belge(k["id"], veri, orijinal_saklandi=True, koseler=[[10, 10], [300, 10], [300, 200], [10, 200]])
    assert _kaydet(c, belge_id, None).get_json()["basarili"]
    assert database.belge_getir(k["id"], belge_id)["koseler"] is None
    assert c.get(f"/gorsel/{belge_id}").data == veri
    assert _yaklasik(okunan["boyut"], (400, 300))


@pytest.mark.parametrize(
    "koseler",
    [
        [[0, 0], [400, 300], [400, 0], [0, 300]],  # kesisen
        [[0, 0], [10, 0], [10, 10], [0, 10]],  # cok kucuk
        [[0, 0], [4000, 0], [4000, 300], [0, 300]],  # gorselin disinda
        "bozuk",
    ],
    ids=["kesisen", "kucuk", "disarida", "bozuk"],
)
def test_gecersiz_koseler_reddedilir(girisli, okunan, koseler):
    c, k = girisli
    belge_id = _gorsel_belge(k["id"], jpeg_bayt(np.full((300, 400, 3), 255, np.uint8)), orijinal_saklandi=True)
    if koseler == "bozuk":
        r = c.post(f"/belge/{belge_id}/koseler", data={"koseler": "[[1,2"}, headers=JSON)
    else:
        r = _kaydet(c, belge_id, koseler)
    assert r.status_code == 400 and not r.get_json()["basarili"]
    assert database.belge_getir(k["id"], belge_id)["ocr_metni"] == "eski metin"


def test_v4_duzeltilmis_belgede_kose_ayari_kapali(girisli, okunan):
    """v4'te duzeltilip oyle saklanan belgenin orijinali yok: koseler degismez."""
    c, k = girisli
    belge_id = _gorsel_belge(k["id"], jpeg(), otomatik_duzeltildi=True)
    assert _kaydet(c, belge_id, [[0, 0], [60, 0], [60, 40], [0, 40]]).status_code == 404
    assert c.get(f"/belge/{belge_id}/koseler/otomatik").status_code == 404
    sayfa = c.get(f"/belge/{belge_id}").get_data(as_text=True)
    assert "data-kose-ac" not in sayfa and "eski sürümle yüklendi" in sayfa


def test_duzeltilmemis_eski_belgede_kose_ayari_acik(girisli, okunan):
    c, k = girisli
    veri = jpeg_bayt(np.full((300, 400, 3), 255, np.uint8))
    belge_id = _gorsel_belge(k["id"], veri)  # v3: orijinal_saklandi FALSE, duzeltme yok
    assert "data-kose-ac" in c.get(f"/belge/{belge_id}").get_data(as_text=True)
    assert _kaydet(c, belge_id, [[50, 50], [350, 50], [350, 250], [50, 250]]).get_json()["basarili"]
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["orijinal_saklandi"] and kayit["koseler"]
    assert Image.open(io.BytesIO(c.get(f"/gorsel/{belge_id}").data)).size == (300, 200)


def test_pdf_ve_baskasinin_belgesi_404(girisli, kullanici, okunan):
    import pymupdf

    c, k = girisli
    pdf = pymupdf.open()
    pdf.new_page()
    pdf_id = database.belge_ekle(
        kullanici_id=k["id"], dosya_adi="a.pdf", mime_type="application/pdf",
        sifreli_icerik=crypto.sifrele(pdf.tobytes()), sifreli_onizleme=None,
        ocr_metni="", tur="diger", guven=0.5, aciklama="",
    )
    assert _kaydet(c, pdf_id, None).status_code == 404
    diger = kullanici()
    yabanci = _gorsel_belge(diger["id"], jpeg(), orijinal_saklandi=True)
    assert _kaydet(c, yabanci, None).status_code == 404
    assert c.get(f"/belge/{yabanci}/koseler/otomatik").status_code == 404
    assert c.post(f"/belge/{yabanci}/yeniden-analiz").status_code == 404
    assert c.get(f"/gorsel/{yabanci}?ham=1").status_code == 404
    assert database.belge_getir(diger["id"], yabanci)["ocr_metni"] == "eski metin"


def test_otomatik_algila(girisli):
    c, k = girisli
    foto = jpeg_bayt(masada_egik_cekim(koseler=DIK))  # 3000x2250
    belge_id = _gorsel_belge(k["id"], foto, orijinal_saklandi=True)
    veri = c.get(f"/belge/{belge_id}/koseler/otomatik").get_json()
    assert veri["belge"] and veri["puan"] >= 0.8
    gercek = np.float32([[3000 * x, 2250 * y] for x, y in DIK])
    assert np.abs(np.float32(veri["koseler"]) - gercek).max() < 0.01 * 3750


# ---------------------------------------------------------------- yeniden analiz

def test_yeniden_analiz_tur_ve_bilgileri_gunceller(girisli):
    c, k = girisli
    belge_id = belge_ekle(k["id"], "a.jpg", "diger", "FATURA metni", 0.4)
    r = c.post(f"/belge/{belge_id}/yeniden-analiz", follow_redirects=True)
    assert "Belge yeniden analiz edildi." in r.get_data(as_text=True)
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["tur"] == "fatura" and kayit["guven"] == pytest.approx(0.95)
    assert kayit["kurum"] == "Test Elektrik A.Ş."


def test_yeniden_analiz_elle_duzeltilenlere_dokunmaz(girisli, monkeypatch):
    c, k = girisli
    belge_id = belge_ekle(k["id"], "a.jpg", "fatura", "FATURA metni", kurum="Elle Firma")
    database.turu_guncelle(k["id"], belge_id, "resmi_yazi")  # tur elle secildi
    database.alanlari_guncelle(k["id"], belge_id, {"kurum": "Elle Kurum"})  # alanlar elle
    cagrilar = []
    gercek = classifier.siniflandir

    def izle(metin, bilinen_tur=None):
        cagrilar.append(bilinen_tur)
        return gercek(metin, bilinen_tur=bilinen_tur)

    monkeypatch.setattr(classifier, "siniflandir", izle)
    r = c.post(f"/belge/{belge_id}/yeniden-analiz", follow_redirects=True)
    metin = r.get_data(as_text=True)
    assert "elle seçilen tür korundu" in metin and "elle düzeltilen bilgiler korundu" in metin
    assert cagrilar == ["resmi_yazi"]  # tur yeniden belirlenmedi
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["tur"] == "resmi_yazi" and kayit["kurum"] == "Elle Kurum"


def test_yeniden_analiz_yogunken(girisli, monkeypatch):
    c, k = girisli
    belge_id = belge_ekle(k["id"], "a.jpg", "diger", "FATURA metni", 0.4)
    monkeypatch.setattr(classifier, "siniflandir", lambda metin, bilinen_tur=None: {
        "tur": "diger", "guven": 0, "aciklama": "", "yogun": True, "alanlar": None})
    r = c.post(f"/belge/{belge_id}/yeniden-analiz", follow_redirects=True)
    assert "Yapay zeka şu an yoğun" in r.get_data(as_text=True)
    assert database.belge_getir(k["id"], belge_id)["guven"] == pytest.approx(0.4)
