"""Tarayicinin kaydettigi klasoru bulma/secme (klasor_secimi.py, izlenen_klasorler.py
ve app.py /klasorler): erisim (yonetici ya da sunucu bilgisayarinin kendisi),
sistem klasorlerinin gizlenmesi, son taranan dosyanin bulunmasi ve onizlemesi,
klasor ekleme ("hepsi" / "bundan sonrakiler") ve kaldirma."""

import os
import sys
import time
from pathlib import Path

import pymupdf
import pytest

import app as uygulama_modulu
import database
import izlenen_klasorler
import klasor_izleme
import klasor_secimi
from conftest import bayt, giris_yap, yazili_gorsel

JSON = {"Accept": "application/json"}
AGDAKI = {"REMOTE_ADDR": "192.168.1.20"}


def _png():
    return bayt(yazili_gorsel((600, 800)))


def _pdf():
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "FATURA")
        return pdf.tobytes()


def _yonetici_yap(kullanici_id):
    database._sorgula("UPDATE kullanicilar SET yonetici = TRUE WHERE id = %s", (kullanici_id,))


@pytest.fixture(autouse=True)
def _gecici_klasor_sistem_sayilmasin(monkeypatch, tmp_path_factory):
    """pytest'in gecici klasoru AppData altindadir ve (dogru olarak) sistem
    klasoru sayilir. Testlerde gecici klasor, surucu kokunde siradan bir
    klasormus gibi denetlenir; gecici klasorun icindeki AppData vb. yine yasaktir."""
    taban = tmp_path_factory.getbasetemp()
    asil = klasor_secimi.yasak_mi

    def yasak_mi(yol):
        yol = Path(os.path.abspath(str(yol)))
        try:
            return asil(Path(taban.anchor) / "Deneme" / yol.relative_to(taban))
        except ValueError:
            return asil(yol)

    monkeypatch.setattr(klasor_secimi, "yasak_mi", yasak_mi)
    return asil


@pytest.fixture
def kokler(tmp_path, monkeypatch):
    """Gecici Belgeler ve Resimler; arama bunlarda yapilir, varsayilan klasorler kapali."""
    belgeler, resimler = tmp_path / "Belgeler", tmp_path / "Resimler"
    belgeler.mkdir()
    resimler.mkdir()
    monkeypatch.setattr(klasor_secimi, "arama_kokleri", lambda: [belgeler, resimler])
    monkeypatch.setattr(klasor_izleme, "varsayilanlar_acik", lambda: False)
    monkeypatch.delenv("TARAMA_KLASORU", raising=False)
    return belgeler, resimler


# ---------------------------------------------------------------- erisim


ADRESLER = ["/klasorler", "/klasorler/son-dosyalar", "/klasorler/gez", "/klasorler/onizleme/x"]


def test_sunucu_bilgisayarindan_kullanici_gorur(girisli, kokler):
    c, _ = girisli  # test istemcisi 127.0.0.1'den gelir
    assert c.get("/klasorler").status_code == 200
    assert "data-klasorler-menu" in c.get("/").get_data(as_text=True)


def test_agdaki_kullanici_goremez(girisli, kokler):
    c, _ = girisli
    for adres in ADRESLER:
        assert c.get(adres, environ_base=AGDAKI).status_code == 404, adres
    for adres in ("/klasorler/ekle", "/klasorler/kaldir"):
        assert c.post(adres, data={"yol": str(kokler[0])}, environ_base=AGDAKI).status_code == 404
    assert "data-klasorler-menu" not in c.get("/", environ_base=AGDAKI).get_data(as_text=True)
    assert izlenen_klasorler.ekli_klasorler() == []


def test_yonetici_agdan_da_gorur(uygulama, kullanici, kokler):
    y = kullanici()
    _yonetici_yap(y["id"])
    c = uygulama.test_client()
    giris_yap(c, y["ad"])
    assert c.get("/klasorler", environ_base=AGDAKI).status_code == 200
    assert c.get("/klasorler/gez", environ_base=AGDAKI).status_code == 200


def test_vekil_arkasinda_yerel_sayilmaz(girisli, kokler, monkeypatch):
    c, _ = girisli
    monkeypatch.setattr(uygulama_modulu, "URETIM", True)
    monkeypatch.setattr(uygulama_modulu, "YEREL_MOD", False)
    assert c.get("/klasorler").status_code == 404


def test_giris_yapmadan_erisilemez(istemci, kokler):
    assert istemci.get("/klasorler/gez").status_code == 302


# ---------------------------------------------------------------- sistem klasorleri


@pytest.mark.skipif(sys.platform != "win32", reason="Windows yollari")
@pytest.mark.parametrize("yol, yasak", [
    (r"C:\Windows", True),
    (r"C:\Windows\System32\drivers", True),
    (r"C:\Program Files\Canon", True),
    (r"C:\Program Files (x86)", True),
    (r"D:\ProgramData\x", True),
    (r"C:\Users\ali\AppData\Local\Temp", True),
    (r"C:\$Recycle.Bin", True),
    (r"E:\System Volume Information", True),
    (r"C:\Users\ali\Documents", False),
    (r"C:\Users\ali\Documents\Windows notları", False),
    (r"D:\Tarama", False),
])
def test_windows_sistem_klasorleri(yol, yasak):
    assert klasor_secimi.yasak_mi(yol) is yasak


@pytest.mark.skipif(sys.platform != "win32", reason="Windows yollari")
def test_ortamdaki_sistem_klasoru_yasak(monkeypatch, _gecici_klasor_sistem_sayilmasin):
    yasak_mi = _gecici_klasor_sistem_sayilmasin  # asil denetim
    monkeypatch.setenv("ProgramFiles", r"D:\Uygulamalar")
    assert yasak_mi(r"D:\Uygulamalar\Tarayici") and yasak_mi(r"D:\Uygulamalar")
    assert not yasak_mi(r"D:\Uygulamalar2") and not yasak_mi(r"D:\Belgeler")
    # pytest'in gecici klasoru gibi AppData altindaki her sey yasak.
    assert yasak_mi(r"C:\Users\ali\AppData\Local\Temp\x")


def test_gezgin_klasorleri_listeler_sistem_ve_gizlileri_gostermez(girisli, tmp_path):
    c, _ = girisli
    for ad in ("Faturalar", "arsiv", ".gizli", "AppData", "node_modules", "$Recycle.Bin"):
        (tmp_path / ad).mkdir()
    (tmp_path / "dosya.txt").write_text("x")
    if sys.platform == "win32":
        import ctypes

        (tmp_path / "GizliNitelik").mkdir()
        ctypes.windll.kernel32.SetFileAttributesW(str(tmp_path / "GizliNitelik"), 2)
    veri = c.get("/klasorler/gez", query_string={"yol": str(tmp_path)}).get_json()
    assert [k["ad"] for k in veri["klasorler"]] == ["arsiv", "Faturalar"]
    assert veri["yol"] == str(tmp_path) and veri["ust"] == str(tmp_path.parent)
    alt = c.get("/klasorler/gez", query_string={"yol": str(tmp_path / "arsiv")}).get_json()
    assert alt["klasorler"] == [] and alt["ust"] == str(tmp_path)


def test_gezgin_baslangicta_suruculer(girisli):
    c, _ = girisli
    veri = c.get("/klasorler/gez").get_json()
    assert veri["yol"] is None and veri["suruculer"]
    assert all(set(k) == {"ad", "yol"} for k in veri["kisayollar"])


@pytest.mark.parametrize("yol, mesaj", [("goreli/yol", "Geçerli"), ("__yok__", "bulunamadı")])
def test_gezgin_gecersiz_yol(girisli, tmp_path, yol, mesaj):
    c, _ = girisli
    if yol == "__yok__":
        yol = str(tmp_path / "yok")
    yanit = c.get("/klasorler/gez", query_string={"yol": yol})
    assert yanit.status_code == 400 and mesaj in yanit.get_json()["hata"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows yollari")
def test_gezgin_sistem_klasorunu_acmaz(girisli):
    c, _ = girisli
    yanit = c.get("/klasorler/gez", query_string={"yol": os.environ.get("SystemRoot", r"C:\Windows")})
    assert yanit.status_code == 400 and "sistem klasörü" in yanit.get_json()["hata"]
    kok = c.get("/klasorler/gez", query_string={"yol": "C:\\"}).get_json()
    adlar = {k["ad"].lower() for k in kok["klasorler"]}
    assert not adlar & {"windows", "program files", "program files (x86)", "programdata"}


# ---------------------------------------------------------------- son taranan dosya


def test_son_dosyalar_bulunur(kokler):
    belgeler, resimler = kokler
    derin = belgeler / "Canon" / "2026" / "09"
    derin.mkdir(parents=True)
    (derin / "IMG_0001.jpg").write_bytes(b"x")
    (resimler / "tarama.pdf").write_bytes(b"x")
    (belgeler / "notlar.txt").write_text("x")
    (belgeler / "ArcBase'e aktarıldı").mkdir()
    (belgeler / "ArcBase'e aktarıldı" / "eski.png").write_bytes(b"x")
    (belgeler / "AppData").mkdir()
    (belgeler / "AppData" / "onbellek.png").write_bytes(b"x")

    bulunan = klasor_secimi.son_dosyalari_bul()
    assert sorted(d["ad"] for d in bulunan) == ["IMG_0001.jpg", "tarama.pdf"]
    assert {d["klasor"] for d in bulunan} == {str(derin), str(resimler)}
    # Iki dakikadan eski dosyalar gosterilmez.
    assert klasor_secimi.son_dosyalari_bul(simdi=time.time() + klasor_secimi.SON_DOSYA_SN + 10) == []


def test_bulunan_dosya_onizlemesi_yalnizca_anahtarla(uygulama, girisli, kokler, kullanici):
    c, _ = girisli
    belgeler, resimler = kokler
    (belgeler / "tarama.png").write_bytes(_png())
    (resimler / "tarama.pdf").write_bytes(_pdf())
    dosyalar = c.get("/klasorler/son-dosyalar").get_json()["dosyalar"]
    assert {d["ad"] for d in dosyalar} == {"tarama.png", "tarama.pdf"}
    assert all("yol" not in d for d in dosyalar)  # istemciye dosya yolu anahtar olarak gitmez
    for dosya in dosyalar:
        yanit = c.get(dosya["onizleme"])
        assert yanit.status_code == 200 and yanit.mimetype == "image/jpeg" and yanit.data[:2] == b"\xff\xd8"
    # Baska kullanici ayni anahtarla goremez; uydurma anahtar da calismaz.
    diger = uygulama.test_client()
    giris_yap(diger, kullanici()["ad"])
    assert diger.get(dosyalar[0]["onizleme"]).status_code == 404
    assert c.get("/klasorler/onizleme/uydurma").status_code == 404


def test_onizleme_anahtarinin_suresi_dolar():
    saat = [0.0]
    anahtarlar = klasor_secimi.OnizlemeAnahtarlari(omur_sn=60, saat=lambda: saat[0])
    anahtar = anahtarlar.ver(1, "C:/x.png")
    assert anahtarlar.yol(1, anahtar) == Path("C:/x.png")
    assert anahtarlar.yol(2, anahtar) is None
    saat[0] = 61
    assert anahtarlar.yol(1, anahtar) is None


# ---------------------------------------------------------------- ekleme


def _izleyici_ile_isle(saat_kaymasi=10):
    """Eklenen klasorleri izleyen bir gecis (sahte saatle kararlilik beklenmez)."""
    an = [0.0]
    izleyici = klasor_izleme.VarsayilanKlasorIzleyici(saat=lambda: an[0])
    izleyici.tara()
    an[0] += saat_kaymasi
    return izleyici.tara()


def _tek_kullanici(monkeypatch, k):
    monkeypatch.setattr(database, "kullanicilari_listele", lambda: [{"id": k["id"], "kullanici_adi": k["ad"]}])


def test_bulunan_belgenin_klasoru_eklenir_yalnizca_yeniler(girisli, kokler, monkeypatch):
    c, k = girisli
    _tek_kullanici(monkeypatch, k)
    klasor = kokler[0] / "HP Scans"
    klasor.mkdir()
    (klasor / "eski.png").write_bytes(_png())
    (klasor / "tarama.png").write_bytes(_png())
    [anahtar] = [d["anahtar"] for d in c.get("/klasorler/son-dosyalar").get_json()["dosyalar"] if d["ad"] == "tarama.png"]
    time.sleep(0.05)

    # Klasorde dosya var: once sorulur, hicbir sey eklenmez.
    soru = c.post("/klasorler/ekle", data={"anahtar": anahtar}, headers=JSON).get_json()
    assert soru == {"soru": True, "sayi": 2, "yol": str(klasor)}
    assert izlenen_klasorler.ekli_klasorler() == []

    yanit = c.post("/klasorler/ekle", data={"anahtar": anahtar, "mevcutlar": "sonrakiler"}, headers=JSON).get_json()
    assert yanit["eklendi"] and yanit["adres"] == "/klasorler"
    [kayit] = izlenen_klasorler.ekli_klasorler()
    assert kayit["yol"] == str(klasor) and kayit["baslangic"] and kayit["ekleyen"] == k["ad"]
    sayfa = c.get("/klasorler").get_data(as_text=True)
    assert str(klasor) in sayfa and "eklendikten sonra düşen dosyalar" in sayfa

    time.sleep(0.05)
    (klasor / "yeni.png").write_bytes(_png())
    sonuclar = _izleyici_ile_isle()
    assert [(y.name, s) for y, s, _ in sonuclar] == [("yeni.png", "alindi")]
    assert (klasor / "eski.png").exists() and (klasor / "ArcBase'e aktarıldı" / "yeni.png").exists()


def test_hepsi_secilirse_mevcut_dosyalar_da_alinir(girisli, kokler, monkeypatch):
    c, k = girisli
    _tek_kullanici(monkeypatch, k)
    klasor = kokler[1] / "Taramalar"
    klasor.mkdir()
    (klasor / "a.png").write_bytes(_png())
    (klasor / "b.pdf").write_bytes(_pdf())
    yanit = c.post("/klasorler/ekle", data={"yol": str(klasor), "mevcutlar": "hepsi"}, headers=JSON)
    assert yanit.get_json()["eklendi"]
    assert izlenen_klasorler.ekli_klasorler()[0]["baslangic"] is None
    assert sorted(s for _, s, _ in _izleyici_ile_isle()) == ["alindi", "alindi"]
    assert database.belge_sayisi(k["id"]) == 2


def test_bos_klasor_sormadan_eklenir(girisli, kokler):
    c, _ = girisli
    klasor = kokler[0] / "Bos"
    klasor.mkdir()
    assert c.post("/klasorler/ekle", data={"yol": str(klasor)}, headers=JSON).get_json()["eklendi"]
    assert [k["yol"] for k in izlenen_klasorler.ekli_klasorler()] == [str(klasor)]
    # Ikinci kez eklemek kopya olusturmaz.
    c.post("/klasorler/ekle", data={"yol": str(klasor)}, headers=JSON)
    assert len(izlenen_klasorler.ekli_klasorler()) == 1


def test_ekleme_hatalari(girisli, kokler, tmp_path, monkeypatch):
    c, _ = girisli
    yanit = c.post("/klasorler/ekle", data={"anahtar": "uydurma"}, headers=JSON)
    assert yanit.status_code == 400 and "yeniden arayın" in yanit.get_json()["hata"]
    yanit = c.post("/klasorler/ekle", data={"yol": str(tmp_path / "yok")}, headers=JSON)
    assert yanit.status_code == 400
    monkeypatch.setenv("TARAMA_KLASORU", str(kokler[0]))
    yanit = c.post("/klasorler/ekle", data={"yol": str(kokler[0])}, headers=JSON)
    assert yanit.status_code == 400 and "zaten izleniyor" in yanit.get_json()["hata"]
    if sys.platform == "win32":
        yanit = c.post("/klasorler/ekle", data={"yol": os.environ.get("SystemRoot", r"C:\Windows")}, headers=JSON)
        assert yanit.status_code == 400 and "sistem klasörü" in yanit.get_json()["hata"]
    assert izlenen_klasorler.ekli_klasorler() == []


def test_js_kapaliyken_ekleme_yonlendirir(girisli, kokler):
    c, _ = girisli
    klasor = kokler[0] / "Form"
    klasor.mkdir()
    (klasor / "a.png").write_bytes(_png())
    yanit = c.post("/klasorler/ekle", data={"yol": str(klasor)})
    assert yanit.status_code == 302 and yanit.headers["Location"].endswith("/klasorler")
    assert izlenen_klasorler.ekli_klasorler()[0]["baslangic"]  # sorulamadi: yalnizca yeniler


# ---------------------------------------------------------------- listeleme ve kaldirma


def test_eklenen_klasor_kaldirilir_dosyalara_dokunulmaz(girisli, kokler):
    c, _ = girisli
    klasor = kokler[0] / "Kaldirilacak"
    klasor.mkdir()
    (klasor / "a.png").write_bytes(_png())
    izlenen_klasorler.ekle(klasor, "test", yalnizca_yeniler=True)
    assert "data-klasor-kaldir" in c.get("/klasorler").get_data(as_text=True)
    yanit = c.post("/klasorler/kaldir", data={"yol": str(klasor)})
    assert yanit.status_code == 302
    assert izlenen_klasorler.ekli_klasorler() == [] and (klasor / "a.png").exists()


def test_varsayilan_klasor_kaldirilir_ve_yeniden_eklenebilir(girisli, kokler, tmp_path, monkeypatch):
    c, _ = girisli
    tarama = tmp_path / "Resimler" / "Scans"
    tarama.mkdir()
    monkeypatch.setattr(klasor_izleme, "varsayilanlar_acik", lambda: True)
    monkeypatch.setattr(klasor_izleme, "varsayilan_klasor_adaylari", lambda: [tarama])
    assert [y for y, _, _ in klasor_izleme.bilgisayar_klasorleri()] == [tarama]
    c.post("/klasorler/kaldir", data={"yol": str(tarama)})
    assert klasor_izleme.bilgisayar_klasorleri() == []
    assert str(tarama) not in c.get("/klasorler").get_data(as_text=True)
    c.post("/klasorler/ekle", data={"yol": str(tarama)}, headers=JSON)
    assert [y for y, _, _ in klasor_izleme.bilgisayar_klasorleri()] == [tarama]


def test_tarama_klasoru_ayari_kaldirilamaz(girisli, kokler, monkeypatch, tmp_path):
    c, _ = girisli
    monkeypatch.setenv("TARAMA_KLASORU", str(tmp_path / "Tarama"))
    sayfa = c.get("/klasorler").get_data(as_text=True)
    assert str(tmp_path / "Tarama") in sayfa
    yanit = c.post("/klasorler/kaldir", data={"yol": str(tmp_path / "Tarama")}, headers=JSON)
    assert yanit.status_code == 400
