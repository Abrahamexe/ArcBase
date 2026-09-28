"""Arka planda isleme: yukleme hemen doner, belge "isleniyor" olarak gorunur;
OCR ve siniflandirmayi isci yapar. Durum veritabaninda tutulur; yarim kalan is
(sureci durmus isci) ve kaldigi asama yeniden baslatmada devam eder."""

import time

import classifier
import database
import isleme
import ocr
from conftest import isleme_durumu, jpeg, yukle

JSON = {"Accept": "application/json"}


def _yukle_islemeden(c, ad="fatura.jpg"):
    r = yukle(c, jpeg(), ad, headers=JSON, isle=False)
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return r.get_json()["belge_id"]


def _eskit(belge_id, dakika=10):
    """Isin kalp atisini geriye alir (iscinin sureci dakikalar once durmus gibi)."""
    database._sorgula(
        "UPDATE belgeler SET isleme_zamani = isleme_zamani - %s * INTERVAL '1 minute' WHERE id = %s",
        (dakika, belge_id),
    )


def test_yukleme_hemen_doner_belge_isleniyor_rozetiyle_gorunur(girisli, monkeypatch):
    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA metni")
    belge_id = _yukle_islemeden(c)
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["isleme_durumu"] == "bekliyor" and kayit["ocr_metni"] is None
    assert kayit["onizleme_var"]  # islenene kadar hizli onizleme gosterilir

    panel = c.get("/").get_data(as_text=True)
    assert f'data-belge-id="{belge_id}" data-isleniyor' in panel and "İşleniyor" in panel
    assert "1</span> belge işleniyor" in panel
    detay = c.get(f"/belge/{belge_id}").get_data(as_text=True)
    assert f'data-belge-isleniyor="{belge_id}"' in detay
    assert '<noscript><meta http-equiv="refresh"' in detay  # JS yokken sayfa kendini yeniler
    assert "data-bilgi-karti" not in detay and "Köşeleri ayarla" not in detay
    assert isleme_durumu(c, belge_id) == {"durum": "bekliyor", "asama": "goruntu", "adres": f"/belge/{belge_id}"}

    assert isleme.bekleyenleri_isle(belge_id=belge_id) == 1
    durum = isleme_durumu(c, belge_id)
    assert durum["durum"] == "tamamlandi" and durum["tur"] == "fatura"
    panel = c.get("/").get_data(as_text=True)
    assert f'data-belge-id="{belge_id}" data-isleniyor' not in panel
    detay = c.get(f"/belge/{belge_id}").get_data(as_text=True)
    assert "data-belge-isleniyor" not in detay and "data-bilgi-karti" in detay and "noscript><meta" not in detay


def test_js_kapaliyken_yukleme_belge_sayfasina_gider(girisli, monkeypatch):
    c, _ = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA metni")
    r = yukle(c, jpeg(), "a.jpg", isle=False)
    assert r.status_code == 302 and "/belge/" in r.headers["Location"]
    sayfa = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "Metni okunup türü belirleniyor" in sayfa and "data-belge-isleniyor" in sayfa


def test_yarim_kalan_is_sahipsiz_kalinca_yeniden_alinir(girisli, monkeypatch):
    """Isci is ortasinda durdu (uygulama yeniden basladi): "isleniyor" is,
    kalp atisi zaman asimini gecince baska bir isci tarafindan alinir."""
    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA metni")
    belge_id = _yukle_islemeden(c)
    assert database.is_al(belge_id=belge_id)["id"] == belge_id  # isci isi aldi ve "oldu"
    assert database.belge_getir(k["id"], belge_id)["isleme_durumu"] == "isleniyor"
    assert not isleme.bir_is_isle(belge_id=belge_id)  # kalp atisi taze: baskasinin isi

    _eskit(belge_id)
    assert isleme.bir_is_isle(belge_id=belge_id)
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["isleme_durumu"] == "tamamlandi" and kayit["tur"] == "fatura"


def test_is_kaldigi_asamadan_devam_eder_ocr_tekrarlanmaz(girisli, monkeypatch):
    c, k = girisli
    ocr_cagrisi = []
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: ocr_cagrisi.append(1) or "FATURA metni")
    gercek = classifier.siniflandir

    def coken(metin):
        raise RuntimeError("surec durdu")

    monkeypatch.setattr(classifier, "siniflandir", coken)
    belge_id = _yukle_islemeden(c)
    assert isleme.bir_is_isle(belge_id=belge_id)
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["isleme_durumu"] == "bekliyor" and kayit["isleme_bilgi"]["asama"] == "siniflandirma"
    assert kayit["ocr_metni"] == "FATURA metni" and kayit["mime_type"] == "image/jpeg"

    monkeypatch.setattr(classifier, "siniflandir", gercek)
    isleme.bekleyenleri_isle(belge_id=belge_id)
    assert ocr_cagrisi == [1]  # goruntu asamasi tekrarlanmadi
    assert database.belge_getir(k["id"], belge_id)["tur"] == "fatura"


def test_bellek_bosalinca_ocr_saklanan_gorselden_yapilir(girisli, monkeypatch):
    """Yuklemede tam cozunurluklu dosya isciye bellekte birakilir; uygulama
    yeniden baslayip bellek bosalmissa is saklanan (2000 px) gorselden devam eder."""
    from conftest import bayt, gorsel_boyutu, yazili_gorsel

    c, k = girisli
    okunan = []
    monkeypatch.setattr(ocr, "metin_cikar", lambda veri, mime: okunan.append(gorsel_boyutu(veri)) or "FATURA")
    r = yukle(c, bayt(yazili_gorsel((3000, 4000))), "buyuk.png", headers=JSON, isle=False)
    belge_id = r.get_json()["belge_id"]
    isleme.ham_bellegini_bosalt()
    isleme.bekleyenleri_isle(belge_id=belge_id)
    assert max(okunan[0]) <= 2000
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["isleme_durumu"] == "tamamlandi" and kayit["tur"] == "fatura" and kayit["orijinal_saklandi"]


def test_surekli_coken_is_hata_olur_ve_yeniden_islenebilir(girisli, monkeypatch):
    c, k = girisli

    def coken(*a):
        raise MemoryError("cok buyuk")

    asil = isleme._goruntu_asamasi
    monkeypatch.setattr(isleme, "_goruntu_asamasi", coken)
    belge_id = _yukle_islemeden(c)
    isleme.bekleyenleri_isle(belge_id=belge_id)
    kayit = database.belge_getir(k["id"], belge_id)
    deneme = database._sorgula("SELECT isleme_deneme FROM belgeler WHERE id = %s", (belge_id,), tek=True)
    assert kayit["isleme_durumu"] == "hata" and deneme["isleme_deneme"] == isleme.MAKS_DENEME
    assert isleme_durumu(c, belge_id)["hata"] == isleme.ISLEME_HATASI
    sayfa = c.get(f"/belge/{belge_id}").get_data(as_text=True)
    assert "Belge işlenemedi" in sayfa and "İşlenemedi" in c.get("/").get_data(as_text=True)

    monkeypatch.setattr(isleme, "_goruntu_asamasi", asil)
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA metni")
    r = c.post(f"/belge/{belge_id}/yeniden-isle", follow_redirects=True)
    assert "yeniden işleniyor" in r.get_data(as_text=True)
    isleme.bekleyenleri_isle(belge_id=belge_id)
    assert database.belge_getir(k["id"], belge_id)["isleme_durumu"] == "tamamlandi"


def test_islenirken_elle_secilen_tur_korunur(girisli, monkeypatch):
    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA metni")
    istenen = []
    monkeypatch.setattr(classifier, "siniflandir", lambda metin, bilinen_tur=None: istenen.append(bilinen_tur) or {
        "tur": bilinen_tur or "fatura", "guven": 0.9, "aciklama": "", "yogun": False, "alanlar": {}})
    belge_id = _yukle_islemeden(c)
    c.post(f"/belge/{belge_id}/tur", data={"tur": "kimlik"})
    isleme.bekleyenleri_isle(belge_id=belge_id)
    assert istenen == ["kimlik"] and database.belge_getir(k["id"], belge_id)["tur"] == "kimlik"


def test_islenirken_kose_ve_yeniden_analiz_yapilmaz(girisli, monkeypatch):
    c, k = girisli
    belge_id = _yukle_islemeden(c)
    assert c.post(f"/belge/{belge_id}/koseler", data={"koseler": ""}).status_code == 404
    r = c.post(f"/belge/{belge_id}/yeniden-analiz", follow_redirects=True)
    assert "henüz işleniyor" in r.get_data(as_text=True)
    # "Bilgi cikar" islenen belgeyi saymaz (isci zaten isleyecek)
    assert database.bilgisi_eksik_sayisi(k["id"]) == 0


def test_durum_yalnizca_kendi_belgelerini_gosterir(girisli, kullanici, uygulama):
    from conftest import giris_yap

    c, _ = girisli
    belge_id = _yukle_islemeden(c)
    baska = uygulama.test_client()
    giris_yap(baska, kullanici()["ad"])
    veri = baska.get(f"/isleme-durumu?id={belge_id}").get_json()
    assert veri["belgeler"] == {} and veri["isleniyor"] == 0
    assert baska.get("/isleme-durumu?id=abc").status_code == 200


def test_arka_plan_iscisi_is_parcaciginda_isler(girisli, monkeypatch):
    """Gercek isci: yeni yukleme onu uyandirir, is kendi is parcaciginda biter."""
    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA metni")
    isleme.baslat(kullanici_id=k["id"])
    try:
        belge_id = _yukle_islemeden(c)
        son = time.monotonic() + 60
        while isleme_durumu(c, belge_id)["durum"] != "tamamlandi":
            assert time.monotonic() < son, "isci belgeyi islemedi"
            time.sleep(0.3)
    finally:
        isleme.durdur()
    assert database.belge_getir(k["id"], belge_id)["tur"] == "fatura"
