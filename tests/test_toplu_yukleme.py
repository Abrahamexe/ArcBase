"""Toplu yukleme: tarayici dosyalari sirayla /yukle'ye gonderir ve JSON cevap
alir; OCR ve siniflandirma arka planda yapilir, sonuc /isleme-durumu ile
yoklanir. Hata, kota, Groq yogunlugu ve JS kapaliyken coklu secim."""

import io

import pytest

import app as uygulama_modulu
import classifier
import database
import isleme
import ocr
from conftest import isleme_durumu, jpeg, yukle

JSON = {"Accept": "application/json"}


@pytest.fixture(autouse=True)
def _hizli_ocr(monkeypatch):
    monkeypatch.setattr(ocr, "metin_cikar", lambda veri, mime: "FATURA metni")


def json_yukle(c, veri, ad, isle=True, **form):
    return yukle(c, veri, ad, data_ek=form, headers=JSON, isle=isle)


def test_json_basarili_cevap(girisli):
    c, k = girisli
    r = json_yukle(c, jpeg(), "fatura.jpg")
    assert r.status_code == 200 and r.is_json
    veri = r.get_json()
    # Yukleme cevabi OCR'i beklemez; tur ve uyarilar durum yoklamasindan gelir.
    assert veri["basarili"] and veri["durum"] == "bekliyor"
    assert veri["adres"] == f"/belge/{veri['belge_id']}"
    durum = isleme_durumu(c, veri["belge_id"])
    assert durum["durum"] == "tamamlandi" and durum["tur"] == "fatura" and durum["tur_ad"] == "Fatura"
    assert durum["uyarilar"] == [] and durum["kirpma_kontrol"] is False
    assert database.belge_getir(k["id"], veri["belge_id"])["kurum"] == "Test Elektrik A.Ş."
    # JSON isteginde flash birakilmaz; sonraki sayfada eski mesaj cikmaz
    assert "başarıyla arşivlendi" not in c.get("/").get_data(as_text=True)


def test_bes_dosyalik_toplu_yukleme_biri_hatali(girisli, kullanici):
    """Tarayicinin yaptigi gibi 5 dosya sirayla gonderilir; hatali olan
    digerlerini durdurmaz."""
    c, k = girisli
    dosyalar = [
        (jpeg(), "bir.jpg"),
        (jpeg(), "iki.png"),
        (b"duz metin", "notlar.txt"),  # hatali
        (jpeg(), "dort.jpg"),
        (jpeg(), "bes.jpeg"),
    ]
    sonuclar = [json_yukle(c, veri, ad) for veri, ad in dosyalar]
    assert [r.status_code for r in sonuclar] == [200, 200, 400, 200, 200]
    assert sonuclar[2].get_json() == {
        "basarili": False, "hata": "Sadece JPG, PNG ve PDF dosyaları yüklenebilir.", "yogun": False,
    }
    assert database.belge_sayisi(k["id"]) == 4
    adlar = {b["dosya_adi"] for b in database.belgeleri_listele(k["id"])}
    assert adlar == {"bir.jpg", "iki.jpg", "dort.jpg", "bes.jpg"}
    assert database.belge_sayisi(kullanici()["id"]) == 0  # baska kullaniciya gecmez


@pytest.mark.parametrize(
    "boyut, ad, durum, mesaj",
    [
        (0, "bos.jpg", 400, "Lütfen bir dosya seçin"),  # tarayici bos dosya adini gondermez
        (5 * 1024 * 1024 + 4, "buyuk.pdf", 400, "PDF dosyaları en fazla 5 MB"),
        (10 * 1024 * 1024 + 1, "dev.jpg", 413, "En fazla 10 MB"),
    ],
    ids=["dosya-yok", "buyuk-pdf", "10mb-ustu"],
)
def test_json_hatalari(girisli, boyut, ad, durum, mesaj):
    c, k = girisli
    if not boyut:
        r = c.post("/yukle", data={}, headers=JSON)
    else:
        r = json_yukle(c, b"%PDF" + b"0" * (boyut - 4), ad)
    assert r.status_code == durum and r.is_json
    assert mesaj in r.get_json()["hata"] and not r.get_json()["basarili"]
    assert database.belge_sayisi(k["id"]) == 0


def test_json_kota_asimi(girisli, monkeypatch):
    c, k = girisli
    monkeypatch.setattr(uygulama_modulu, "KULLANICI_BELGE_LIMITI", 2)
    assert [json_yukle(c, jpeg(), f"{i}.jpg").status_code for i in range(3)] == [200, 200, 403]
    assert database.belge_sayisi(k["id"]) == 2
    assert "Belge kotanız doldu" in json_yukle(c, jpeg(), "x.jpg").get_json()["hata"]
    assert "data-kota-doldu" in c.get("/").get_data(as_text=True)


def test_kalan_kota_formda(girisli, monkeypatch):
    c, k = girisli
    monkeypatch.setattr(uygulama_modulu, "KULLANICI_BELGE_LIMITI", 5)
    json_yukle(c, jpeg(), "a.jpg")
    sayfa = c.get("/").get_data(as_text=True)
    assert 'data-kalan-kota="4"' in sayfa and "en fazla 10 dosya" in sayfa and "multiple" in sayfa


def test_groq_yogunsa_belge_kaydedilir_is_ertelenip_yeniden_denenir(girisli, monkeypatch):
    """Eskiden tarayici 429'da belgeyi kaydetmeden bekleyip yeniden gonderiyordu;
    artik belge hemen kaydedilir, siniflandirmayi isci birkac saniye sonra yeniden
    dener. Denemeler biterse belge "diger" olarak uyariyla tamamlanir."""
    c, k = girisli
    cagrilar = []

    def yogun(metin):
        cagrilar.append(metin)
        return {"tur": "diger", "guven": 0.0, "aciklama": classifier.YOGUN_MESAJI,
                "yogun": True, "hata_turu": "yogun", "alanlar": None}

    monkeypatch.setattr(classifier, "siniflandir", yogun)
    r = json_yukle(c, jpeg(), "yogun.jpg", isle=False)
    assert r.status_code == 200 and database.belge_sayisi(k["id"]) == 1
    belge_id = r.get_json()["belge_id"]

    assert isleme.bir_is_isle(belge_id=belge_id)  # goruntu + 1. Groq denemesi
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["isleme_durumu"] == "bekliyor" and kayit["isleme_bilgi"]["groq_deneme"] == 1
    assert kayit["ocr_metni"] == "FATURA metni"  # OCR sonucu kaydedildi, tekrarlanmaz
    assert not isleme.bir_is_isle(belge_id=belge_id)  # erteleme suresi dolmadan alinmaz
    assert isleme_durumu(c, belge_id)["durum"] == "bekliyor"

    isleme.bekleyenleri_isle(belge_id=belge_id)  # kalan denemeler, beklemeden
    assert len(cagrilar) == 1 + len(isleme.GROQ_BEKLEMELERI)
    durum = isleme_durumu(c, belge_id)
    assert durum["durum"] == "tamamlandi" and durum["tur"] == "diger"
    assert durum["uyarilar"] == [classifier.YOGUN_MESAJI]


def test_groq_duzelince_ertelenen_is_siniflandirilir(girisli, monkeypatch):
    c, k = girisli
    cevaplar = [
        {"tur": "diger", "guven": 0.0, "aciklama": "", "yogun": True, "hata_turu": "yogun", "alanlar": None},
        {"tur": "fatura", "guven": 0.9, "aciklama": "Fatura", "yogun": False, "alanlar": {}},
    ]
    monkeypatch.setattr(classifier, "siniflandir", lambda metin: cevaplar.pop(0))
    belge_id = json_yukle(c, jpeg(), "a.jpg").get_json()["belge_id"]
    durum = isleme_durumu(c, belge_id)
    assert durum["durum"] == "tamamlandi" and durum["tur"] == "fatura" and durum["uyarilar"] == []


def test_js_kapaliyken_coklu_secimde_ilk_dosya_yuklenir(girisli):
    c, k = girisli
    r = c.post(
        "/yukle",
        data={"belge": [(io.BytesIO(jpeg()), "ilk.jpg"), (io.BytesIO(jpeg()), "ikinci.jpg")]},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "yalnızca ilk dosya yüklendi" in r.get_data(as_text=True)
    assert [b["dosya_adi"] for b in database.belgeleri_listele(k["id"])] == ["ilk.jpg"]


def test_json_csrf_hatasi(uygulama, girisli):
    c, k = girisli
    uygulama.config["WTF_CSRF_ENABLED"] = True
    r = json_yukle(c, jpeg(), "a.jpg")
    assert r.status_code == 400 and r.is_json and "Form süresi doldu" in r.get_json()["hata"]
    assert database.belge_sayisi(k["id"]) == 0


def test_oturumsuz_json_istegi_girise_yonlenir(istemci):
    r = json_yukle(istemci, jpeg(), "a.jpg")
    assert r.status_code == 302 and "/giris" in r.headers["Location"]
