"""Tarama klasoru (klasor_izleme.py): kullanici alt klasoru, kok klasor
(varsayilan kullanici / yoneticinin gelen kutusu), yarim yazilmis dosya, TIFF,
hatali dosya, kota, dosyalarin tasinmasi. Her test gecici bir klasor kullanir;
zaman sahte saatle ilerletilir (test beklemez)."""

import io
import time
from datetime import datetime

import pymupdf
import pytest

import database
import isleme
import klasor_izleme
from conftest import SIFRE, bayt, belge_ekle, yazili_gorsel


class Saat:
    def __init__(self):
        self.an = 1000.0

    def __call__(self):
        return self.an

    def ilerlet(self, sn=klasor_izleme.KARARLILIK_SN + 0.5):
        self.an += sn


@pytest.fixture
def saat():
    return Saat()


@pytest.fixture
def izleyici_uret(tmp_path, saat):
    def uret(**ayar):
        return klasor_izleme.Izleyici(tmp_path / "Tarama", saat=saat, **ayar)

    (tmp_path / "Tarama").mkdir()
    return uret


def _isle_ve_al(izleyici, saat):
    """Ilk gecis dosyayi gorur, saat ilerleyince ikinci gecis isler."""
    assert izleyici.tara() == []
    saat.ilerlet()
    return izleyici.tara()


def _png():
    return bayt(yazili_gorsel((800, 600)))


def _tiff(sayfa_sayisi):
    sayfalar = [yazili_gorsel((800, 600)).convert("L") for _ in range(sayfa_sayisi)]
    tampon = io.BytesIO()
    sayfalar[0].save(tampon, "TIFF", save_all=True, append_images=sayfalar[1:], compression="tiff_deflate")
    return tampon.getvalue()


def _bugun():
    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------- sahiplik


def test_kullanici_alt_klasoru_o_kullaniciya_ait_olur(izleyici_uret, saat, kullanici):
    k = kullanici()
    izleyici = izleyici_uret()
    klasor = izleyici.kok / k["ad"]
    klasor.mkdir()
    (klasor / "fatura.png").write_bytes(_png())

    [(yol, sonuc, belge_id)] = _isle_ve_al(izleyici, saat)

    assert sonuc == "alindi"
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["dosya_adi"] == "fatura.jpg" and not kayit["gelen_kutusu"]
    assert kayit["isleme_durumu"] == database.BEKLIYOR and kayit["isleme_bilgi"]["kaynak"] == "klasor"
    # Dosya silinmez, islendi\YYYY-AA-GG altina tasinir.
    assert not yol.exists()
    assert (klasor / "islendi" / _bugun() / "fatura.png").read_bytes() == _png()
    # Normal yuklemeyle ayni kuyruk: isci isler, belge siniflandirilir.
    isleme.bekleyenleri_isle(belge_id=belge_id)
    kayit = database.belge_getir(k["id"], belge_id)
    assert (kayit["isleme_durumu"], kayit["tur"]) == (database.TAMAMLANDI, "fatura")


def test_kok_klasor_varsayilan_kullaniciya_gider(izleyici_uret, saat, kullanici):
    k = kullanici()
    izleyici = izleyici_uret(varsayilan_kullanici=k["ad"].upper())
    (izleyici.kok / "tarama.png").write_bytes(_png())
    [(_, sonuc, belge_id)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "alindi"
    assert not database.belge_getir(k["id"], belge_id)["gelen_kutusu"]
    assert (izleyici.kok / "islendi" / _bugun() / "tarama.png").exists()


@pytest.mark.parametrize("varsayilan", [None, "olmayan_kullanici"])
def test_kok_klasor_yoneticinin_gelen_kutusuna_gider(izleyici_uret, saat, kullanici, monkeypatch, varsayilan):
    y = kullanici()
    monkeypatch.setattr(database, "yonetici_getir", lambda: {"id": y["id"], "kullanici_adi": y["ad"]})
    izleyici = izleyici_uret(varsayilan_kullanici=varsayilan)
    (izleyici.kok / "sahipsiz.png").write_bytes(_png())
    [(_, sonuc, belge_id)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "alindi"
    assert database.belge_getir(y["id"], belge_id)["gelen_kutusu"]
    assert belge_id not in [b["id"] for b in database.belgeleri_listele(y["id"])]


def test_hic_kullanici_yoksa_dosya_bekler(izleyici_uret, saat, monkeypatch):
    monkeypatch.setattr(database, "yonetici_getir", lambda: None)
    izleyici = izleyici_uret()
    dosya = izleyici.kok / "erken.png"
    dosya.write_bytes(_png())
    [(_, sonuc, _)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "bekliyor" and dosya.exists()


def test_olmayan_kullanici_klasoru_hataya_gider(izleyici_uret, saat, veritabani):
    izleyici = izleyici_uret()
    klasor = izleyici.kok / "boyle_biri_yok_123"
    klasor.mkdir()
    (klasor / "a.png").write_bytes(_png())
    [(_, sonuc, neden)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "hata" and "kullanıcı yok" in neden
    assert (klasor / "hata" / "a.png").exists()
    assert "kullanıcı yok" in (klasor / "hata" / "a.png.hata.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------- yazim, tur, hata


def test_yarim_yazilmis_dosya_alinmaz(izleyici_uret, saat, kullanici):
    k = kullanici()
    izleyici = izleyici_uret(varsayilan_kullanici=k["ad"])
    veri = _png()
    dosya = izleyici.kok / "yaziliyor.png"
    dosya.write_bytes(veri[:1000])
    assert izleyici.tara() == []
    saat.ilerlet(2)
    with dosya.open("ab") as f:  # tarayici yazmaya devam ediyor
        f.write(veri[1000:])
    assert izleyici.tara() == []  # boyut degisti: sayac yeniden baslar
    saat.ilerlet(klasor_izleme.KARARLILIK_SN - 1)
    assert izleyici.tara() == []
    saat.ilerlet(2)
    [(_, sonuc, belge_id)] = izleyici.tara()
    assert sonuc == "alindi"
    assert database.belge_getir(k["id"], belge_id) is not None


def test_bos_dosya_beklenir(izleyici_uret, saat, kullanici):
    izleyici = izleyici_uret(varsayilan_kullanici=kullanici()["ad"])
    (izleyici.kok / "bos.pdf").write_bytes(b"")
    assert izleyici.tara() == []
    saat.ilerlet(60)
    assert izleyici.tara() == []  # 0 bayt: tarayici henuz yazmadi


def test_tek_sayfali_tiff_gorsel_olur(izleyici_uret, saat, kullanici):
    k = kullanici()
    izleyici = izleyici_uret(varsayilan_kullanici=k["ad"])
    (izleyici.kok / "tek.tif").write_bytes(_tiff(1))
    [(_, sonuc, belge_id)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "alindi"
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["mime_type"] == "image/jpeg" and kayit["dosya_adi"] == "tek.jpg"


def test_cok_sayfali_tiff_tek_pdf_belge_olur(izleyici_uret, saat, kullanici):
    k = kullanici()
    izleyici = izleyici_uret(varsayilan_kullanici=k["ad"])
    (izleyici.kok / "cok.tiff").write_bytes(_tiff(3))
    [(_, sonuc, belge_id)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "alindi"
    kayit = database.belge_icerigi(k["id"], belge_id)
    assert kayit["mime_type"] == "application/pdf" and kayit["dosya_adi"] == "cok.pdf"
    import crypto

    with pymupdf.open(stream=crypto.coz(kayit["veri"]), filetype="pdf") as pdf:
        assert pdf.page_count == 3
    assert (izleyici.kok / "islendi" / _bugun() / "cok.tiff").exists()


@pytest.mark.parametrize(
    "ad, veri, neden",
    [
        ("notlar.txt", b"merhaba", "Desteklenmeyen"),
        ("bozuk.tif", b"II*\x00bozuk", "TIFF"),
        ("buyuk.pdf", None, "PDF çok büyük"),
    ],
    ids=["desteklenmeyen", "bozuk-tiff", "buyuk-pdf"],
)
def test_hatali_dosya_nedeniyle_hataya_tasinir(izleyici_uret, saat, kullanici, ad, veri, neden):
    veri = veri or b"%PDF" + b"0" * (klasor_izleme.MAKS_PDF_BOYUTU + 1)
    izleyici = izleyici_uret(varsayilan_kullanici=kullanici()["ad"])
    (izleyici.kok / ad).write_bytes(veri)
    [(_, sonuc, mesaj)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "hata" and neden in mesaj
    assert (izleyici.kok / "hata" / ad).read_bytes() == veri
    assert neden in (izleyici.kok / "hata" / f"{ad}.hata.txt").read_text(encoding="utf-8")
    assert izleyici.tara() == []  # hata klasoru yeniden islenmez


def test_kota_doluysa_hataya_tasinir(izleyici_uret, saat, kullanici):
    k = kullanici()
    belge_ekle(k["id"])
    izleyici = izleyici_uret(varsayilan_kullanici=k["ad"], belge_limiti=1)
    (izleyici.kok / "fazla.png").write_bytes(_png())
    [(_, sonuc, mesaj)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "hata" and "Kota dolu" in mesaj
    assert "Kota dolu" in (izleyici.kok / "hata" / "fazla.png.hata.txt").read_text(encoding="utf-8")
    assert database.belge_sayisi(k["id"]) == 1


def test_gecici_dosyalar_ve_ayrilmis_klasorler_yoksayilir(izleyici_uret, saat, kullanici):
    izleyici = izleyici_uret(varsayilan_kullanici=kullanici()["ad"])
    for ad in ("tarama.tmp", "desktop.ini", "Thumbs.db", "~$gecici.pdf", ".gizli.png"):
        (izleyici.kok / ad).write_bytes(b"x")
    (izleyici.kok / "islendi").mkdir()
    (izleyici.kok / "islendi" / "eski.png").write_bytes(_png())
    assert _isle_ve_al(izleyici, saat) == []
    assert izleyici.tara() == []


def test_ayni_adli_dosya_uzerine_yazilmaz(izleyici_uret, saat, kullanici):
    izleyici = izleyici_uret(varsayilan_kullanici=kullanici()["ad"])
    for _ in range(2):
        (izleyici.kok / "ayni.png").write_bytes(_png())
        [(_, sonuc, _)] = _isle_ve_al(izleyici, saat)
        assert sonuc == "alindi"
    gun = izleyici.kok / "islendi" / _bugun()
    assert sorted(p.name for p in gun.iterdir()) == ["ayni.png", "ayni_1.png"]


def test_kuyruga_eklenemezse_dosya_yerine_doner(izleyici_uret, saat, kullanici, monkeypatch):
    izleyici = izleyici_uret(varsayilan_kullanici=kullanici()["ad"])
    dosya = izleyici.kok / "geri.png"
    dosya.write_bytes(_png())

    def bozuk(*a, **k):
        raise database.VeritabaniHatasi("baglanti yok")

    monkeypatch.setattr(isleme, "kuyruga_ekle", bozuk)
    [(_, sonuc, _)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "bekliyor" and dosya.exists()
    assert not any((izleyici.kok / "islendi" / _bugun()).iterdir())


# ---------------------------------------------------------------- kayit ve arka plan


def test_kayitta_kullanici_klasoru_olusur(istemci, yeni_ad, tmp_path, monkeypatch):
    monkeypatch.setenv("TARAMA_KLASORU", str(tmp_path / "Tarama"))
    ad = yeni_ad()
    yanit = istemci.post("/kayit", data={"kullanici_adi": ad, "sifre": SIFRE, "sifre_tekrar": SIFRE})
    assert yanit.status_code == 302
    assert (tmp_path / "Tarama" / ad).is_dir()


def test_ayrilmis_ad_kullanici_klasoru_olmaz(tmp_path):
    assert klasor_izleme.kullanici_klasoru_olustur("islendi", tmp_path) is None
    assert klasor_izleme.kullanici_klasoru_olustur("Hata", tmp_path) is None
    assert klasor_izleme.kullanici_klasoru_olustur("ali", tmp_path) == tmp_path / "ali"


@pytest.mark.slow
def test_arka_planda_izleyici_dosyayi_alir(tmp_path, kullanici, monkeypatch):
    """Gercek is parcacigi ve watchdog ile: dosya birakilir, birkac saniyede alinir."""
    k = kullanici()
    monkeypatch.setattr(klasor_izleme, "YOKLAMA_SN", 0.5)
    izleyici = klasor_izleme.Izleyici(tmp_path / "Tarama", varsayilan_kullanici=k["ad"], kararlilik_sn=0.5)
    izleyici.baslat()
    try:
        (izleyici.kok / "canli.png").write_bytes(_png())
        for _ in range(100):
            if (izleyici.kok / "islendi" / _bugun() / "canli.png").exists():
                break
            time.sleep(0.1)
        else:
            pytest.fail("Dosya 10 saniyede alinmadi")
    finally:
        izleyici.durdur()
    assert database.belge_sayisi(k["id"]) == 1


# ---------------------------------------------------------------- Windows varsayilan tarama klasorleri


@pytest.fixture
def varsayilan(tmp_path, saat):
    """Gecici "Belgeler/Scanned Documents" (var) ve "Resimler/Scans" (henuz yok)
    klasorlerini izleyen VarsayilanKlasorIzleyici uretir."""
    import tarama_gunlugu

    tarama_gunlugu.temizle()
    belgeler = tmp_path / "Belgeler" / "Scanned Documents"
    belgeler.mkdir(parents=True)
    resimler = tmp_path / "Resimler" / "Scans"

    def uret(**ayar):
        return klasor_izleme.VarsayilanKlasorIzleyici(
            adaylar=lambda: [(belgeler, klasor_izleme.VARSAYILAN_TUR, None), (resimler, klasor_izleme.VARSAYILAN_TUR, None)],
            saat=saat, **ayar)

    uret.belgeler, uret.resimler = belgeler, resimler
    return uret


def _tek_kullanici(monkeypatch, k):
    monkeypatch.setattr(database, "kullanicilari_listele", lambda: [{"id": k["id"], "kullanici_adi": k["ad"]}])


def test_varsayilan_klasor_tek_kullanicinin_arsivine_gider(varsayilan, saat, kullanici, monkeypatch):
    import tarama_gunlugu

    k = kullanici()
    _tek_kullanici(monkeypatch, k)
    izleyici = varsayilan()
    (varsayilan.belgeler / "Resim 001.jpg").write_bytes(bayt(yazili_gorsel((800, 600)), "JPEG"))

    [(yol, sonuc, belge_id)] = _isle_ve_al(izleyici, saat)

    assert sonuc == "alindi"
    assert not database.belge_getir(k["id"], belge_id)["gelen_kutusu"]
    # Silinmez: "ArcBase'e aktarıldı" alt klasorune tasinir.
    assert not yol.exists() and (varsayilan.belgeler / "ArcBase'e aktarıldı" / "Resim 001.jpg").exists()
    [kayit] = tarama_gunlugu.son_aktarilanlar()
    assert (kayit["dosya"], kayit["kime"], kayit["gelen_kutusu"]) == ("Resim 001.jpg", k["ad"], False)
    # Aktarilan dosya bir daha alinmaz.
    saat.ilerlet()
    assert izleyici.tara() == []


def test_varsayilan_klasor_cok_kullanicida_gelen_kutusuna(varsayilan, saat, kullanici, monkeypatch):
    y, diger = kullanici(), kullanici()
    monkeypatch.setattr(database, "kullanicilari_listele", lambda: [
        {"id": y["id"], "kullanici_adi": y["ad"]}, {"id": diger["id"], "kullanici_adi": diger["ad"]}])
    monkeypatch.setattr(database, "yonetici_getir", lambda: {"id": y["id"], "kullanici_adi": y["ad"]})
    izleyici = varsayilan()
    (varsayilan.belgeler / "tarama.png").write_bytes(_png())
    [(_, sonuc, belge_id)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "alindi" and database.belge_getir(y["id"], belge_id)["gelen_kutusu"]


def test_varsayilan_klasor_ayarli_varsayilan_kullaniciya_gider(varsayilan, saat, kullanici, monkeypatch):
    k, diger = kullanici(), kullanici()
    monkeypatch.setattr(database, "kullanicilari_listele", lambda: [{"id": 1}, {"id": 2}])
    izleyici = varsayilan(varsayilan_kullanici=k["ad"])
    (varsayilan.belgeler / "tarama.png").write_bytes(_png())
    [(_, sonuc, belge_id)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "alindi" and not database.belge_getir(k["id"], belge_id)["gelen_kutusu"]


def test_varsayilan_klasorde_baska_dosyalara_dokunulmaz(varsayilan, saat, kullanici, monkeypatch):
    _tek_kullanici(monkeypatch, kullanici())
    izleyici = varsayilan()
    for ad in ("rapor.docx", "notlar.txt", "desktop.ini", "~$gecici.pdf"):
        (varsayilan.belgeler / ad).write_bytes(b"x")
    aktarildi = varsayilan.belgeler / "ArcBase'e aktarıldı"
    aktarildi.mkdir()
    (aktarildi / "eski.png").write_bytes(_png())
    assert _isle_ve_al(izleyici, saat) == []
    assert (varsayilan.belgeler / "rapor.docx").exists() and (aktarildi / "eski.png").exists()


def test_varsayilan_klasorde_tarih_alt_klasoru(varsayilan, saat, kullanici, monkeypatch):
    k = kullanici()
    _tek_kullanici(monkeypatch, k)
    izleyici = varsayilan()
    alt = varsayilan.belgeler / "2026_09_29"
    alt.mkdir()
    (alt / "IMG_0001.png").write_bytes(_png())
    [(_, sonuc, _)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "alindi"
    assert (varsayilan.belgeler / "ArcBase'e aktarıldı" / "IMG_0001.png").exists()


def test_varsayilan_klasorde_hatali_dosya_ayri_klasore(varsayilan, saat, kullanici, monkeypatch):
    import tarama_gunlugu

    _tek_kullanici(monkeypatch, kullanici())
    izleyici = varsayilan()
    (varsayilan.belgeler / "bozuk.tif").write_bytes(b"TIFF degil")
    [(_, sonuc, neden)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "hata" and "TIFF" in neden
    hata_klasoru = varsayilan.belgeler / "ArcBase'e aktarılamadı"
    assert (hata_klasoru / "bozuk.tif").exists() and (hata_klasoru / "bozuk.tif.hata.txt").exists()
    assert "bozuk.tif" in tarama_gunlugu.son_hatalar()[0]["mesaj"]


def test_sonradan_olusan_varsayilan_klasor_izlenir(varsayilan, saat, kullanici, monkeypatch):
    _tek_kullanici(monkeypatch, kullanici())
    izleyici = varsayilan()
    assert izleyici.izlenen_klasorler() == [varsayilan.belgeler]
    varsayilan.resimler.mkdir(parents=True)
    (varsayilan.resimler / "tarama.png").write_bytes(_png())
    assert varsayilan.resimler in izleyici.izlenen_klasorler()
    [(_, sonuc, _)] = _isle_ve_al(izleyici, saat)
    assert sonuc == "alindi" and (varsayilan.resimler / "ArcBase'e aktarıldı" / "tarama.png").exists()


def test_tarama_klasoru_varsayilanlarla_cakismaz(varsayilan):
    """TARAMA_KLASORU varsayilan klasorlerden biriyse onu yalnizca kendi izleyicisi izler."""
    izleyici = varsayilan(haric=[str(varsayilan.belgeler)])
    assert izleyici.izlenen_klasorler() == []


def test_tarama_klasorunde_aktarildi_klasoru_kullanici_sayilmaz(izleyici_uret, saat, veritabani):
    izleyici = izleyici_uret()
    klasor = izleyici.kok / "ArcBase'e aktarıldı"
    klasor.mkdir()
    (klasor / "a.png").write_bytes(_png())
    assert _isle_ve_al(izleyici, saat) == []


def test_varsayilan_klasor_adaylari_belgeler_ve_resimler(monkeypatch, tmp_path):
    monkeypatch.setattr(klasor_izleme, "_bilinen_klasor",
                        lambda ad: [tmp_path / ("Documents" if ad == "belgeler" else "Pictures")])
    adaylar = klasor_izleme.varsayilan_klasor_adaylari()
    assert tmp_path / "Documents" / "Scanned Documents" in adaylar
    assert tmp_path / "Documents" / "Taranan Belgeler" in adaylar
    assert tmp_path / "Pictures" / "Taranan" in adaylar
    assert all(a.parent != tmp_path for a in adaylar)  # Belgeler/Resimler'in kendisi izlenmez


def test_izlenen_klasorler_durum_listesi(monkeypatch, tmp_path):
    import sys

    var, yok = tmp_path / "Scanned Documents", tmp_path / "Scans"
    var.mkdir()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("VARSAYILAN_TARAMA_KLASORLERI", raising=False)
    monkeypatch.setenv("TARAMA_KLASORU", str(tmp_path / "Tarama"))
    monkeypatch.setattr(klasor_izleme, "varsayilan_klasor_adaylari", lambda: [var, yok])
    liste = {k["yol"]: k for k in klasor_izleme.izlenen_klasorler()}
    assert str(tmp_path / "Tarama") in liste
    assert liste[str(yok)]["not"].startswith("Henüz yok")
    assert not liste[str(var)]["not"]
