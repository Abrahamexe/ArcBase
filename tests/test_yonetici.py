"""Yonetici rolu ve Gelen belgeler kutusu: yoneticinin belirlenmesi, atama,
atama kaydi, kota ve veri ayriminin korunmasi (yonetici baska kullanicilarin
arsivini goremez)."""

import uuid
from urllib.parse import quote

import psycopg2
import pytest

import app as uygulama_modulu
import conftest
import database
import kimlik
from conftest import SIFRE, belge_ekle, giris_yap, jpeg


def _yonetici_yap(kullanici_id, deger=True):
    database._sorgula("UPDATE kullanicilar SET yonetici = %s WHERE id = %s", (deger, kullanici_id))


def _gelen_belge(yonetici_id, dosya_adi="tarama_001.jpg"):
    import crypto

    veri = jpeg()
    return database.belge_ekle(
        kullanici_id=yonetici_id, dosya_adi=dosya_adi, mime_type="image/jpeg",
        sifreli_icerik=crypto.sifrele(veri), sifreli_onizleme=crypto.sifrele(veri),
        ocr_metni="FATURA", tur="fatura", guven=0.9, aciklama="test", gelen_kutusu=True,
    )


@pytest.fixture
def yonetici(uygulama, kullanici):
    """Giris yapmis yonetici istemcisi ve kullanicisi."""
    k = kullanici()
    _yonetici_yap(k["id"])
    c = uygulama.test_client()
    assert giris_yap(c, k["ad"]).status_code == 302
    return c, k


def _istemci(uygulama, k):
    c = uygulama.test_client()
    assert giris_yap(c, k["ad"]).status_code == 302
    return c


# ---------------------------------------------------------------- yoneticinin belirlenmesi


@pytest.fixture
def ayri_sema(veritabani, monkeypatch):
    """database modulunu bu teste ozel bos bir semaya yonlendirir (kullanici
    tablosu bos baslar; ortak test verisi etkilenmez)."""
    sema = f"yonetici_{uuid.uuid4().hex[:8]}"
    yonetim = psycopg2.connect(conftest.TEST_VERITABANI)
    yonetim.autocommit = True
    with yonetim.cursor() as imlec:
        imlec.execute(f"CREATE SCHEMA {sema}")
    ayrac = "&" if "?" in conftest.TEST_VERITABANI else "?"
    monkeypatch.setenv("DATABASE_URL", f"{conftest.TEST_VERITABANI}{ayrac}options={quote(f'-csearch_path={sema}')}")
    monkeypatch.setattr(database, "_havuz", database._Havuz())
    database.veritabanini_hazirla()
    try:
        yield
    finally:
        database._havuz.bosalt()
        with yonetim.cursor() as imlec:
            imlec.execute(f"DROP SCHEMA IF EXISTS {sema} CASCADE")
        yonetim.close()


def _yoneticiler():
    return [s["kullanici_adi"] for s in database._sorgula(
        "SELECT kullanici_adi FROM kullanicilar WHERE yonetici ORDER BY id", hepsi=True)]


def test_ilk_kullanici_yonetici_olur_ayar_verilirse_o(ayri_sema):
    database.yoneticiyi_belirle(None)  # kullanici yok: hata vermez
    ilk = database.kullanici_ekle("ilk", "h")
    database.kullanici_ekle("ikinci", "h")
    database.yoneticiyi_belirle(None)
    assert _yoneticiler() == ["ilk"]
    assert database.yonetici_getir()["id"] == ilk

    database.kullanici_ekle("Sef", "h")
    database.yoneticiyi_belirle("sef")  # buyuk/kucuk harf duyarsiz
    assert _yoneticiler() == ["Sef"]
    database.yoneticiyi_belirle("olmayan")  # ayardaki kullanici yok: mevcut yonetici kalir
    assert _yoneticiler() == ["Sef"]
    database.yoneticiyi_belirle(None)
    assert _yoneticiler() == ["Sef"]


def test_yonetici_degisince_gelen_kutusu_yenisine_gecer(ayri_sema):
    eski = database.kullanici_ekle("eski", "h")
    yeni = database.kullanici_ekle("yeni", "h")
    database.yoneticiyi_belirle(None)
    belge_id = _gelen_belge(eski)
    arsiv_id = belge_ekle(eski)
    database.yoneticiyi_belirle("yeni")
    assert [b["id"] for b in database.belgeleri_suz(yeni, gelen=True)] == [belge_id]
    assert database.belge_getir(eski, arsiv_id) is not None  # arsiv belgesi yerinde


def test_kayitta_ilk_kullanici_yonetici_olur(ayri_sema, monkeypatch):
    monkeypatch.setattr(uygulama_modulu, "YONETICI_KULLANICI", None)
    uygulama_modulu.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    c = uygulama_modulu.app.test_client()
    yanit = c.post("/kayit", data={"kullanici_adi": "kurucu", "sifre": SIFRE, "sifre_tekrar": SIFRE})
    assert yanit.status_code == 302
    assert _yoneticiler() == ["kurucu"]
    assert "Gelen belgeler" in c.get("/").get_data(as_text=True)


# ---------------------------------------------------------------- gelen kutusu


def test_gelen_belge_arsivde_ve_sayaclarda_gorunmez(yonetici):
    c, k = yonetici
    gelen_id = _gelen_belge(k["id"])
    arsiv_id = belge_ekle(k["id"], ocr_metni="FATURA")

    ozet = database.kullanici_ozeti(k["id"])["sayaclar"]
    assert (ozet["toplam"], ozet["gelen"]) == (1, 1)
    assert [b["id"] for b in database.belgeleri_listele(k["id"])] == [arsiv_id]
    assert database.belge_sayisi(k["id"]) == 1
    assert [b["id"] for b in database.belgeleri_suz(k["id"], sorgu="FATURA")] == [arsiv_id]

    panel = c.get("/").get_data(as_text=True)
    assert f'data-belge-id="{gelen_id}"' not in panel and f'data-belge-id="{arsiv_id}"' in panel
    assert "data-gelen-menu" in panel
    sayfa = c.get("/gelen").get_data(as_text=True)
    assert f'data-gelen-belge="{gelen_id}"' in sayfa and f'data-belge-id="{arsiv_id}"' not in sayfa
    # Yonetici gelen belgeyi acabilir (gorsel, tur) ve atama formunu gorur.
    belge_sayfasi = c.get(f"/belge/{gelen_id}")
    assert belge_sayfasi.status_code == 200 and "data-gelen-belge" in belge_sayfasi.get_data(as_text=True)
    assert c.get(f"/onizleme/{gelen_id}").status_code == 200


def test_yonetici_olmayan_gelen_kutusunu_goremez_ve_atayamaz(uygulama, yonetici, kullanici):
    _, y = yonetici
    gelen_id = _gelen_belge(y["id"])
    u = kullanici()
    _yonetici_yap(u["id"], False)
    c = _istemci(uygulama, u)
    assert c.get("/gelen").status_code == 404
    assert "data-gelen-menu" not in c.get("/").get_data(as_text=True)
    assert c.post(f"/gelen/{gelen_id}/ata", data={"kullanici": u["id"]}).status_code == 404
    assert c.get(f"/belge/{gelen_id}").status_code == 404
    assert database.belge_getir(y["id"], gelen_id)["gelen_kutusu"]


def test_atama_kullaniciya_gecer_ve_kaydedilir(uygulama, yonetici, kullanici):
    c, y = yonetici
    gelen_id = _gelen_belge(y["id"])
    u = kullanici()

    yanit = c.post(f"/gelen/{gelen_id}/ata", data={"kullanici": u["id"]}, follow_redirects=True)
    assert "kullanıcısına atandı" in yanit.get_data(as_text=True)

    kayit = database.belge_getir(u["id"], gelen_id)
    assert kayit is not None and not kayit["gelen_kutusu"]
    atama = kayit["atama_gecmisi"][-1]
    assert (atama["yapan_id"], atama["yapan"], atama["kime_id"], atama["kime"]) == (y["id"], y["ad"], u["id"], u["ad"])
    assert atama["zaman"]
    # Veri ayrimi: atandiktan sonra yonetici belgeyi goremez; kullanici gorur.
    assert c.get(f"/belge/{gelen_id}").status_code == 404
    assert f'data-gelen-belge="{gelen_id}"' not in c.get("/gelen").get_data(as_text=True)
    k_istemci = _istemci(uygulama, u)
    sayfa = k_istemci.get(f"/belge/{gelen_id}").get_data(as_text=True)
    assert "data-atama-bilgisi" in sayfa and y["ad"] in sayfa
    assert gelen_id in [b["id"] for b in database.belgeleri_listele(u["id"])]
    # Ayni belge ikinci kez atanamaz.
    assert c.post(f"/gelen/{gelen_id}/ata", data={"kullanici": y["id"]}).status_code == 404


def test_yonetici_kendi_arsivine_alabilir(yonetici):
    c, y = yonetici
    gelen_id = _gelen_belge(y["id"])
    yanit = c.post(f"/gelen/{gelen_id}/ata", data={"kullanici": y["id"]}, follow_redirects=True)
    assert "arşivinize alındı" in yanit.get_data(as_text=True)
    assert [b["id"] for b in database.belgeleri_listele(y["id"])] == [gelen_id]
    assert database.kullanici_ozeti(y["id"])["sayaclar"]["gelen"] == 0


def test_hedefin_kotasi_doluysa_atanmaz(yonetici, kullanici, monkeypatch):
    c, y = yonetici
    monkeypatch.setattr(uygulama_modulu, "KULLANICI_BELGE_LIMITI", 1)
    gelen_id = _gelen_belge(y["id"])
    u = kullanici()
    belge_ekle(u["id"])
    yanit = c.post(f"/gelen/{gelen_id}/ata", data={"kullanici": u["id"]}, follow_redirects=True)
    assert "kotası dolu" in yanit.get_data(as_text=True)
    assert database.belge_getir(y["id"], gelen_id)["gelen_kutusu"]


def test_gecersiz_hedef_kullanici(yonetici):
    c, y = yonetici
    gelen_id = _gelen_belge(y["id"])
    for veri in ({}, {"kullanici": "abc"}, {"kullanici": 0}, {"kullanici": 2_000_000_000}):
        yanit = c.post(f"/gelen/{gelen_id}/ata", data=veri, follow_redirects=True)
        assert "kullanıcıyı seçin" in yanit.get_data(as_text=True)
    assert database.belge_getir(y["id"], gelen_id)["gelen_kutusu"]


def test_yonetici_bilgisi_oturum_nesnesinde(yonetici, kullanici):
    _, y = yonetici
    assert kimlik.Kullanici(database.kullanici_ozeti(y["id"])).yonetici
    assert not kimlik.Kullanici(database.kullanici_getir(kullanici()["id"])).yonetici


def test_yonetici_baska_kullanicinin_arsivini_goremez(yonetici, kullanici):
    c, _ = yonetici
    u = kullanici()
    belge_id = belge_ekle(u["id"], dosya_adi="gizli.jpg", ocr_metni="GIZLI SOZLESME")
    for adres in (f"/belge/{belge_id}", f"/onizleme/{belge_id}", f"/belge/{belge_id}/indir"):
        assert c.get(adres).status_code == 404, adres
    assert "gizli.jpg" not in c.get("/ara?q=GIZLI").get_data(as_text=True)
    assert "gizli.jpg" not in c.get("/gelen").get_data(as_text=True)
    # Kendi gelen kutusunda olmayan belgeyi atayamaz.
    assert c.post(f"/gelen/{belge_id}/ata", data={"kullanici": u["id"]}).status_code == 404
    assert database.belge_getir(u["id"], belge_id) is not None
