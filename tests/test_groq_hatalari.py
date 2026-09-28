"""Groq hatalari: gecici (baglanti, zaman asimi, 5xx, 429) ve kalici (anahtar,
model, bozuk cevap) ayrimi; basarisiz siniflandirmanin kullaniciya bildirilmesi,
toplu yuklemede yeniden deneme ve detay sayfasindan "Yeniden dene".

Gercek bir olay uzerine eklendi: yukleme aninda Groq'a ulasilamadi
("Connection error"), belge sessizce "diger" olarak kaydedildi ve ekranda
"basariyla arsivlendi" yazdi."""

import json
import logging

import openai
import pytest

import classifier
import database
import isleme
import ocr
from conftest import GERCEK_SINIFLANDIR, belge_ekle, isleme_durumu, jpeg, yukle

try:
    import httpx2 as httpx
except ImportError:  # openai'nin eski surumleri
    import httpx

ISTEK = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _yanit(kod):
    return httpx.Response(kod, request=ISTEK)


HATALAR = {
    "baglanti": lambda: openai.APIConnectionError(request=ISTEK),
    "zaman_asimi": lambda: openai.APITimeoutError(request=ISTEK),
    "sunucu_500": lambda: openai.InternalServerError("sunucu", response=_yanit(500), body=None),
    "kota_429": lambda: openai.RateLimitError("kota", response=_yanit(429), body=None),
    "anahtar_401": lambda: openai.AuthenticationError("gecersiz anahtar", response=_yanit(401), body=None),
    "model_404": lambda: openai.NotFoundError("model yok", response=_yanit(404), body=None),
    "istek_400": lambda: openai.BadRequestError("bozuk istek", response=_yanit(400), body=None),
}


class HataVerenIstemci:
    def __init__(self, hata):
        self.hata = hata
        self.chat = self.completions = self

    def create(self, **_):
        raise self.hata()


class CevapVerenIstemci:
    def __init__(self, icerik):
        self.icerik = icerik
        self.chat = self.completions = self

    def create(self, **_):
        mesaj = type("Mesaj", (), {"content": self.icerik})
        return type("Yanit", (), {"choices": [type("Secim", (), {"message": mesaj})]})


@pytest.fixture
def gercek_siniflandir(monkeypatch):
    """conftest'teki sahte siniflandirma yerine gercek fonksiyon; istemci test icinde verilir."""
    monkeypatch.setattr(classifier, "siniflandir", GERCEK_SINIFLANDIR)
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA Genel Toplam: 100,00 TL")

    def istemci(nesne):
        monkeypatch.setattr(classifier, "_istemci_olustur", lambda: nesne)

    return istemci


@pytest.mark.parametrize(
    "ad, hata_turu",
    [("baglanti", "baglanti"), ("zaman_asimi", "baglanti"), ("sunucu_500", "baglanti"),
     ("kota_429", "yogun"), ("anahtar_401", "kalici"), ("model_404", "kalici"), ("istek_400", "kalici")],
)
def test_hata_siniflari(gercek_siniflandir, caplog, ad, hata_turu):
    gercek_siniflandir(HataVerenIstemci(HATALAR[ad]))
    with caplog.at_level(logging.WARNING, logger="dijital_arsiv.groq"):
        sonuc = classifier.siniflandir("FATURA metni")
    assert sonuc["hata_turu"] == hata_turu and sonuc["alanlar"] is None and sonuc["guven"] == 0
    assert sonuc["yogun"] is (hata_turu in ("yogun", "baglanti"))
    # Kullanici mesaji sade; teknik neden loga yazilir
    assert "Connection" not in sonuc["aciklama"] and "HTTP" not in sonuc["aciklama"]
    assert caplog.records, "teknik neden loga yazilmali"


def test_bozuk_cevap_ve_anahtar_yok(gercek_siniflandir, monkeypatch):
    gercek_siniflandir(CevapVerenIstemci("json degil"))
    assert classifier.siniflandir("x")["hata_turu"] == "kalici"
    gercek_siniflandir(CevapVerenIstemci(json.dumps(["liste"])))
    assert classifier.siniflandir("x")["hata_turu"] == "kalici"
    gercek_siniflandir(None)  # GROQ_API_KEY tanimsiz
    sonuc = classifier.siniflandir("x")
    assert sonuc["hata_turu"] == "kalici" and "GROQ_API_KEY" not in sonuc["aciklama"]


def test_basarili_cevapta_hata_yok(gercek_siniflandir):
    gercek_siniflandir(CevapVerenIstemci(json.dumps({"tur": "fatura", "guven": 0.9, "aciklama": "a", "alanlar": {}})))
    sonuc = classifier.siniflandir("x")
    assert sonuc["hata_turu"] is None and not sonuc["yogun"] and sonuc["tur"] == "fatura"


def test_baglanti_hatasi_yuklemede_sessiz_kalmaz(girisli, gercek_siniflandir):
    """Eski davranis: belge "diger" kaydedilip "basariyla arsivlendi" yaziyordu."""
    c, k = girisli
    gercek_siniflandir(HataVerenIstemci(HATALAR["baglanti"]))
    r = yukle(c, jpeg(), "fatura.jpg", follow_redirects=True)
    sayfa = r.get_data(as_text=True)
    assert "servise ulaşılamadı" in sayfa and "başarıyla arşivlendi" not in sayfa
    kayit = database.belgeleri_listele(k["id"])[0]
    assert kayit["tur"] == "diger" and kayit["guven"] == 0
    assert "Belgenin türü belirlenemedi" in sayfa and "data-yeniden-dene" in sayfa


class SayanIstemci(HataVerenIstemci):
    def __init__(self, hata):
        super().__init__(hata)
        self.adet = 0

    def create(self, **k):
        self.adet += 1
        return super().create(**k)


def test_baglanti_hatasinda_is_ertelenip_yeniden_denenir(girisli, gercek_siniflandir):
    """Gecici hata (baglanti): belge kaydedilir, isci siniflandirmayi birkac kez
    yeniden dener; olmazsa uyariyla tamamlar."""
    c, k = girisli
    istemci = SayanIstemci(HATALAR["baglanti"])
    gercek_siniflandir(istemci)
    r = yukle(c, jpeg(), "a.jpg", headers={"Accept": "application/json"})
    assert r.status_code == 200 and database.belge_sayisi(k["id"]) == 1
    assert istemci.adet == 1 + len(isleme.GROQ_BEKLEMELERI)
    durum = isleme_durumu(c, r.get_json()["belge_id"])
    assert durum["durum"] == "tamamlandi" and durum["uyarilar"] == [classifier.BAGLANTI_MESAJI]


def test_kalici_hata_tekrar_denenmez(girisli, gercek_siniflandir):
    c, k = girisli
    istemci = SayanIstemci(HATALAR["anahtar_401"])
    gercek_siniflandir(istemci)
    r = yukle(c, jpeg(), "a.jpg", headers={"Accept": "application/json"})
    assert istemci.adet == 1
    durum = isleme_durumu(c, r.get_json()["belge_id"])
    assert durum["durum"] == "tamamlandi" and durum["uyarilar"] == [classifier.KALICI_HATA_MESAJI]


def test_yeniden_dene_duzelir(girisli, gercek_siniflandir):
    c, k = girisli
    belge_id = belge_ekle(k["id"], "a.jpg", "diger", "FATURA Genel Toplam: 100,00 TL", 0.0)
    assert "data-yeniden-dene" in c.get(f"/belge/{belge_id}").get_data(as_text=True)

    gercek_siniflandir(HataVerenIstemci(HATALAR["baglanti"]))
    r = c.post(f"/belge/{belge_id}/yeniden-analiz", follow_redirects=True)
    assert "Servise şu an ulaşılamadı" in r.get_data(as_text=True)
    assert database.belge_getir(k["id"], belge_id)["tur"] == "diger"

    gercek_siniflandir(CevapVerenIstemci(json.dumps(
        {"tur": "fatura", "guven": 0.93, "aciklama": "Fatura", "alanlar": {"tutar": "100.00", "para_birimi": "TRY"}})))
    r = c.post(f"/belge/{belge_id}/yeniden-analiz", follow_redirects=True)
    assert "Belge yeniden analiz edildi" in r.get_data(as_text=True)
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["tur"] == "fatura" and kayit["guven"] > 0.9 and str(kayit["tutar"]) == "100.00"
    assert "data-yeniden-dene" not in c.get(f"/belge/{belge_id}").get_data(as_text=True)


def test_basarili_ve_elle_duzeltilmis_belgede_kart_yok(girisli):
    c, k = girisli
    iyi = belge_ekle(k["id"], "a.jpg", "fatura", "FATURA", 0.9)
    metinsiz = belge_ekle(k["id"], "b.jpg", "diger", "", 0.0)
    elle = belge_ekle(k["id"], "c.jpg", "diger", "FATURA", 0.0)
    database.turu_guncelle(k["id"], elle, "dilekce")
    for belge_id in (iyi, metinsiz, elle):
        assert "data-yeniden-dene" not in c.get(f"/belge/{belge_id}").get_data(as_text=True)
