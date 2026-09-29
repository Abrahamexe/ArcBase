"""Gercek Groq API ile entegrasyon testleri (istege bagli).

Diger testler Groq'u taklit eder; bu yuzden anahtarin gecersizlesmesi, modelin
kaldirilmasi, cevap bicimi degisikligi ya da baglanti sorunlari yakalanmaz.
Bu dosya gercek istek atar (~7 istek, kota harcar):

    GROQ_ENTEGRASYON=1 pytest -m slow tests/test_groq_entegrasyon.py

.env'deki GROQ_API_KEY (ve varsa GROQ_MODEL) kullanilir; anahtar yazdirilmaz.
"""

import os

import pytest

import classifier
import database
from conftest import GERCEK_SINIFLANDIR, ocr_gerekli, yukle
from ornek_gorseller import jpeg_bayt, sayfa

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("GROQ_ENTEGRASYON") != "1" or not os.getenv("GROQ_API_KEY"),
        reason="Gercek Groq testleri icin GROQ_ENTEGRASYON=1 ve GROQ_API_KEY gerekli",
    ),
]

FATURA = """E-ARŞİV FATURA
ABC Elektronik Tic. Ltd. Şti.
Fatura No: ABC2026000000123
Fatura Tarihi: 15.03.2026
Kablosuz kulaklık 1 adet 1.000,00 TL
KDV %20: 200,00 TL
Genel Toplam: 1.200,00 TL"""

DILEKCE = """KADIKÖY BELEDİYE BAŞKANLIĞINA
Mahallemizdeki sokak lambalarının iki haftadır yanmadığını bildirir,
gerekli onarımın yapılmasını arz ederim.
02.04.2026
Ayşe Yılmaz"""

KIMLIK = """TÜRKİYE CUMHURİYETİ KİMLİK KARTI
T.C. Kimlik No 12345678950
Soyadı YILMAZ  Adı AYŞE
Doğum Tarihi 12.05.1990
Seri No A12Z34567
Son Geçerlilik 20.08.2031"""


@pytest.fixture(autouse=True)
def gercek_groq(monkeypatch):
    """conftest'in sahte siniflandirmasini geri alir."""
    monkeypatch.setattr(classifier, "siniflandir", GERCEK_SINIFLANDIR)


def _basarili(sonuc):
    assert sonuc["hata_turu"] is None, f"Groq hatasi: {sonuc['hata_turu']} — {sonuc['aciklama']}"
    return sonuc


def test_model_mevcut():
    """GROQ_MODEL (ya da varsayilan) Groq'ta hala var mi? Kaldirilirsa 404 alinir."""
    model = os.getenv("GROQ_MODEL", classifier.VARSAYILAN_MODEL)
    modeller = {m.id for m in classifier._istemci_olustur().models.list().data}
    assert model in modeller, f"{model} Groq'ta yok; mevcut modellerden birini GROQ_MODEL olarak ayarlayin"


def test_fatura_siniflandirma_ve_bilgiler():
    sonuc = _basarili(classifier.siniflandir(FATURA))
    assert sonuc["tur"] == "fatura" and sonuc["guven"] >= 0.6
    a = sonuc["alanlar"]
    assert str(a["tutar"]) == "1200.00" and a["para_birimi"] == "TRY"
    assert a["fatura_no"] == "ABC2026000000123" and a["belge_tarihi"].isoformat() == "2026-03-15"


def test_dilekce_siniflandirma():
    sonuc = _basarili(classifier.siniflandir(DILEKCE))
    assert sonuc["tur"] == "dilekce"
    assert sonuc["alanlar"]["belge_tarihi"].isoformat() == "2026-04-02"


def test_kimlikte_hassas_bilgi_saklanmaz():
    sonuc = _basarili(classifier.siniflandir(KIMLIK))
    assert sonuc["tur"] == "kimlik"
    duz = str(sonuc)
    for yasak in ("12345678950", "A12Z34567", "1990"):
        assert yasak not in duz


def test_gecersiz_anahtar_kalici_hata(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_gecersiz_test_anahtari")
    sonuc = classifier.siniflandir(FATURA)
    assert sonuc["hata_turu"] == "kalici" and not sonuc["yogun"]


@ocr_gerekli
def test_uctan_uca_yukleme(girisli):
    """Gercek OCR + gercek Groq: faturanin fotografi yukleme akisindan gecer."""
    c, k = girisli
    r = yukle(c, jpeg_bayt(sayfa()), "fatura.jpg", headers={"Accept": "application/json"})
    veri = r.get_json()
    assert r.status_code == 200 and veri["uyarilar"] == [], veri
    kayit = database.belge_getir(k["id"], veri["belge_id"])
    assert kayit["tur"] == "fatura" and kayit["guven"] >= 0.6
    assert str(kayit["tutar"]) == "1200.00"
