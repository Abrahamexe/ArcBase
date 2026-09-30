"""Bagli tarayicidan dogrudan tarama (tarayici_wia.py). Gercek tarayici
olmadan, WIA Otomasyon nesnelerini taklit eden sahte COM katmaniyla test
edilir; gercek tarayiciyla kontrol listesi docs/KURULUM_KURUM.md'dedir.

Kapsam: tarayici algilama (takilma/cikarilma, onbellek), otomatik kaynak
secimi (besleyici/cam), tek tusla ve sayfa sayfa tarama, sade hata mesajlari
(teknik ayrinti yalnizca gunlukte) ve yoneticinin durum sayfasi."""

import io
import logging
import os
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

import app as uygulama_modulu
import crypto
import database
import tarama_gunlugu
import tarayici_wia as wia
from conftest import belge_ekle, giris_yap, yazili_gorsel

PROJE = Path(__file__).resolve().parent.parent
JSON = {"Accept": "application/json"}


def _imzali(kod):
    """pywin32 HRESULT'u isaretli 32 bit tamsayi olarak verir."""
    return kod - (1 << 32) if kod & 0x80000000 else kod


class SahteComHatasi(Exception):
    """pywintypes.com_error benzeri: (hresult, metin, excepinfo, arg)."""

    def __init__(self, kod):
        super().__init__(_imzali(0x80020009), "Exception occurred.", (0, "WIA", "", None, 0, _imzali(kod)), None)


class Ozellik:
    def __init__(self, kimlik, deger=0, salt_okunur=False):
        self.PropertyID = kimlik
        self._deger = deger
        self.salt_okunur = salt_okunur

    @property
    def Value(self):
        return self._deger

    @Value.setter
    def Value(self, deger):
        if self.salt_okunur:
            raise SahteComHatasi(0x80070057)
        self._deger = deger


def _png(renk="white"):
    tampon = io.BytesIO()
    yazili_gorsel((850, 1100)).convert("RGB" if renk == "white" else "L").save(tampon, "PNG")
    return tampon.getvalue()


class Oge:
    def __init__(self, sayfalar, bitis_hatasi=wia.KAGIT_BITTI):
        self.Properties = [Ozellik(wia.RENK_NIYETI), Ozellik(wia.YATAY_COZUNURLUK), Ozellik(wia.DIKEY_COZUNURLUK)]
        self.sayfalar = list(sayfalar)
        self.bitis_hatasi = bitis_hatasi
        self.bicimler = []

    def ozellik(self, kimlik):
        return next(o.Value for o in self.Properties if o.PropertyID == kimlik)

    def Transfer(self, bicim):
        self.bicimler.append(bicim)
        if not self.sayfalar:
            raise SahteComHatasi(self.bitis_hatasi)
        veri = self.sayfalar.pop(0)
        return type("Goruntu", (), {"FileData": type("Veri", (), {"BinaryData": memoryview(veri)})()})()


class Cihaz:
    """besleyici: kaynak secimi yazilabilir mi. yetenek/durum: WIA belge
    isleme yetenekleri ve besleyici durumu (None: cihaz bildirmiyor)."""

    def __init__(self, oge, besleyici=True, yetenek=None, durum=None):
        self.oge = oge
        self.Properties = [Ozellik(wia.BELGE_KAYNAGI, salt_okunur=not besleyici), Ozellik(wia.SAYFA_SAYISI)]
        if yetenek is not None:
            self.Properties.append(Ozellik(wia.BELGE_YETENEKLERI, yetenek, salt_okunur=True))
        if durum is not None:
            self.Properties.append(Ozellik(wia.BELGE_DURUMU, durum, salt_okunur=True))

    def ozellik(self, kimlik):
        return next(o.Value for o in self.Properties if o.PropertyID == kimlik)

    def Items(self, sira):
        assert sira == 1
        return self.oge


def _adf_dolu(oge):
    """Hem besleyicisi hem cami olan, besleyicisinde kagit bulunan tarayici."""
    return Cihaz(oge, yetenek=wia.BESLEYICI | wia.CAMLI, durum=wia.BESLEYICI_HAZIR)


class Bilgi:
    def __init__(self, kimlik, ad, tur=wia.TARAYICI_TURU, cihaz=None, baglanti_hatasi=None):
        self.DeviceID, self.Type, self.ad = kimlik, tur, ad
        self.cihaz, self.baglanti_hatasi = cihaz, baglanti_hatasi

    def Properties(self, ad):
        assert ad == "Name"
        return type("Ozellik", (), {"Value": self.ad})()

    def Connect(self):
        if self.baglanti_hatasi:
            raise SahteComHatasi(self.baglanti_hatasi)
        return self.cihaz


class SahteCom:
    """(pythoncom, win32com.client) yerine gecer; COM oturumlarini sayar.
    bilgiler listesi test sirasinda degistirilebilir (tarayici takma/cikarma)."""

    def __init__(self, bilgiler=(), dispatch_hatasi=False):
        self.bilgiler = list(bilgiler)
        self.dispatch_hatasi = dispatch_hatasi
        self.acik = 0
        self.acilan = 0

    def CoInitialize(self):
        self.acik += 1
        self.acilan += 1

    def CoUninitialize(self):
        self.acik -= 1

    def Dispatch(self, ad):
        assert ad == "WIA.DeviceManager"
        if self.dispatch_hatasi:
            raise SahteComHatasi(0x80040154)  # sinif kayitli degil
        return type("Yonetici", (), {"DeviceInfos": list(self.bilgiler)})()


@pytest.fixture
def com(monkeypatch):
    """Sahte COM kurar; tarayici onbellegi, bekleyen taramalar ve gunluk sifirlanir."""
    tarama_gunlugu.temizle()

    def kur(*bilgiler, **ayar):
        sahte = SahteCom(bilgiler, **ayar)
        monkeypatch.setattr(wia, "_com", lambda: (sahte, sahte))
        wia.sifirla()
        return sahte

    yield kur
    wia.sifirla()


# ---------------------------------------------------------------- WIA katmani


def test_yalnizca_tarayicilar_listelenir(com):
    sahte = com(Bilgi("{A}\\0001", "Canon LiDE 300"), Bilgi("{K}\\0002", "Kamera", tur=2), Bilgi("{B}\\0003", "HP ADF"))
    assert wia.tarayicilari_listele() == [{"id": "{A}\\0001", "ad": "Canon LiDE 300"}, {"id": "{B}\\0003", "ad": "HP ADF"}]
    assert sahte.acilan == 1 and sahte.acik == 0  # COM oturumu kapatildi


def test_wia_kullanilamiyorsa_sade_mesaj(com):
    sahte = com(dispatch_hatasi=True)
    with pytest.raises(wia.TarayiciHatasi) as hata:
        wia.tarayicilari_listele()
    assert str(hata.value) == wia.BULUNAMADI
    assert sahte.acik == 0


def test_camli_yuzeyden_tek_sayfa(com):
    oge = Oge([_png(), _png()])
    cihaz = Cihaz(oge)
    com(Bilgi("t1", "Tarayici", cihaz=cihaz))
    sayfalar, besleyici = wia.tara("t1", dpi=200, renk="gri")
    assert len(sayfalar) == 1 and sayfalar[0][:4] == b"\x89PNG" and not besleyici
    assert (cihaz.ozellik(wia.BELGE_KAYNAGI), cihaz.ozellik(wia.SAYFA_SAYISI)) == (wia.CAMLI, 1)
    assert (oge.ozellik(wia.RENK_NIYETI), oge.ozellik(wia.YATAY_COZUNURLUK), oge.ozellik(wia.DIKEY_COZUNURLUK)) == (2, 200, 200)
    assert oge.bicimler == [wia.PNG_BICIMI]


def test_varsayilan_ayarlar_300_dpi_renkli(com):
    oge = Oge([_png()])
    com(Bilgi("t1", "T", cihaz=Cihaz(oge)))
    wia.tara("t1")
    assert (oge.ozellik(wia.RENK_NIYETI), oge.ozellik(wia.YATAY_COZUNURLUK)) == (wia.RENKLER["renkli"], 300)


def test_besleyiciden_kagit_bitene_kadar(com):
    oge = Oge([_png() for _ in range(3)])
    cihaz = Cihaz(oge)
    com(Bilgi("t1", "ADF", cihaz=cihaz))
    sayfalar, besleyici = wia.tara("t1", renk="sb", kaynak="besleyici")
    assert len(sayfalar) == 3 and besleyici
    assert (cihaz.ozellik(wia.BELGE_KAYNAGI), cihaz.ozellik(wia.SAYFA_SAYISI)) == (wia.BESLEYICI, 0)
    assert oge.ozellik(wia.RENK_NIYETI) == 4


@pytest.mark.parametrize(
    "yetenek, durum, besleyici_beklenir",
    [
        (wia.BESLEYICI | wia.CAMLI, wia.BESLEYICI_HAZIR, True),  # besleyicide kagit var
        (wia.BESLEYICI | wia.CAMLI, 0, False),  # besleyici bos: cam
        (wia.BESLEYICI | wia.CAMLI, None, False),  # durum bilinmiyor: cam
        (wia.BESLEYICI, None, True),  # yalnizca besleyici
        (wia.CAMLI, None, False),  # yalnizca cam
        (None, None, False),  # cihaz bildirmiyor: cam
    ],
)
def test_otomatik_kaynak_secimi(com, yetenek, durum, besleyici_beklenir):
    oge = Oge([_png(), _png()])
    cihaz = Cihaz(oge, yetenek=yetenek, durum=durum)
    com(Bilgi("t1", "T", cihaz=cihaz))
    sayfalar, besleyici = wia.tara("t1")
    assert besleyici is besleyici_beklenir
    assert len(sayfalar) == (2 if besleyici_beklenir else 1)
    assert cihaz.ozellik(wia.BELGE_KAYNAGI) == (wia.BESLEYICI if besleyici_beklenir else wia.CAMLI)


@pytest.mark.parametrize(
    "durum, mesaj",
    [
        ("bos_besleyici", "Besleyicide kâğıt yok"),
        ("mesgul", "meşgul"),
        ("sikisma", "Kâğıt sıkıştı"),
        ("kapak", "kapağı açık"),
        ("bilinmeyen", "Tarama yapılamadı"),
        ("yok", "Tarayıcı bulunamadı. Kablonun takılı"),
        ("kopuk", "Tarayıcı bulunamadı. Kablonun takılı"),
        ("adf_yok", "kâğıt besleyici yok"),
    ],
)
def test_tarayici_hatalari_sade_mesaj_verir(com, durum, mesaj, caplog):
    kodlar = {"mesgul": 0x80210006, "kapak": 0x80210016, "bilinmeyen": 0x81234567, "kopuk": 0x80210005}
    oge = Oge([], bitis_hatasi={"sikisma": 0x80210002}.get(durum, wia.KAGIT_BITTI))
    bilgi = Bilgi("t1", "T", cihaz=Cihaz(oge, besleyici=durum != "adf_yok"), baglanti_hatasi=kodlar.get(durum))
    sahte = com(bilgi)
    with caplog.at_level(logging.WARNING, logger="dijital_arsiv.tarayici"):
        with pytest.raises(wia.TarayiciHatasi, match=mesaj) as hata:
            wia.tara("yok" if durum == "yok" else "t1",
                     kaynak="besleyici" if durum in ("bos_besleyici", "adf_yok") else "otomatik")
    # Kullaniciya hata kodu ve teknik terim gosterilmez; kod gunluge yazilir.
    for teknik in ("0x", "WIA", "ADF", "HRESULT"):
        assert teknik not in str(hata.value)
    if durum in kodlar:
        assert f"0x{kodlar[durum]:08X}" in caplog.text
    assert sahte.acik == 0
    assert not wia._tarama_kilidi.locked()
    assert tarama_gunlugu.son_hatalar()[0]["mesaj"] == str(hata.value)


def test_tum_mesajlar_sade(com):
    for mesaj in [*wia.HATA_MESAJLARI.values(), wia.BULUNAMADI, wia.GENEL_HATA, wia.MESGUL, wia.BESLEYICI_YOK]:
        assert "0x" not in mesaj and "WIA" not in mesaj and "ADF" not in mesaj


def test_ayni_anda_tek_tarama(com):
    com(Bilgi("t1", "T", cihaz=Cihaz(Oge([_png()]))))
    with wia._tarama_kilidi:
        with pytest.raises(wia.TarayiciHatasi, match="başka bir tarama"):
            wia.tara("t1")
    assert len(wia.tara("t1")[0]) == 1


@pytest.mark.parametrize("ayar", [{"dpi": 600}, {"renk": "mor"}, {"kaynak": "uzay"}])
def test_gecersiz_ayar(com, ayar):
    com(Bilgi("t1", "T", cihaz=Cihaz(Oge([_png()]))))
    with pytest.raises(wia.TarayiciHatasi, match="geçersiz"):
        wia.tara("t1", **ayar)


def test_hresult_cozumleme():
    assert wia._hresult(SahteComHatasi(0x80210006)) == 0x80210006
    assert wia._hresult(Exception(_imzali(0x80210005))) == 0x80210005
    assert wia._hresult(Exception("metin")) is None


def test_ilerleme_sayfa_sayisini_bildirir(com):
    gorulen = []

    class IzlenenOge(Oge):
        def Transfer(self, bicim):
            gorulen.append(wia.ilerleme())
            return super().Transfer(bicim)

    com(Bilgi("t1", "T", cihaz=Cihaz(IzlenenOge([_png(), _png()]))))
    wia.tara("t1", kaynak="besleyici")
    assert [g["sayfa"] for g in gorulen] == [0, 1, 2] and all(g["taraniyor"] for g in gorulen)
    assert wia.ilerleme() == {"taraniyor": False, "sayfa": 0}


# ---------------------------------------------------------------- tarayici algilama


def test_takilan_ve_cikarilan_tarayici_algilanir(com, caplog):
    sahte = com()
    with caplog.at_level(logging.INFO, logger="dijital_arsiv.tarayici"):
        assert wia.yenile() == []
        sahte.bilgiler.append(Bilgi("t1", "Canon LiDE 300"))
        assert wia.yenile() == [{"id": "t1", "ad": "Canon LiDE 300"}]
        assert "Tarayici bulundu: Canon LiDE 300" in caplog.text
        sahte.bilgiler.clear()
        assert wia.yenile() == []
        assert "Tarayici cikarildi: Canon LiDE 300" in caplog.text


def test_liste_onbellekten_verilir_sure_dolunca_yenilenir(com, monkeypatch):
    sahte = com(Bilgi("t1", "T"))
    saat = [100.0]
    monkeypatch.setattr(wia.time, "monotonic", lambda: saat[0])
    assert wia.bagli_tarayicilar() == [{"id": "t1", "ad": "T"}]
    sahte.bilgiler.clear()
    assert wia.bagli_tarayicilar() == [{"id": "t1", "ad": "T"}] and sahte.acilan == 1
    assert wia.bagli_tarayicilar(False) == [{"id": "t1", "ad": "T"}]
    saat[0] += wia.YOKLAMA_SN
    assert wia.bagli_tarayicilar() == [] and sahte.acilan == 2


def test_wia_hatasi_gunluge_bir_kez_yazilir(com, caplog):
    com(dispatch_hatasi=True)
    with caplog.at_level(logging.WARNING, logger="dijital_arsiv.tarayici"):
        for _ in range(3):
            assert wia.yenile() == []
    assert caplog.text.count("Tarayici listesi alinamadi") == 1


def test_tarama_surerken_liste_yenilenmez(com):
    sahte = com(Bilgi("t1", "T"))
    wia.yenile()
    with wia._tarama_kilidi:
        sahte.bilgiler.clear()
        assert wia.yenile() == [{"id": "t1", "ad": "T"}]
    assert sahte.acilan == 1


def test_bekleyen_taramalar_suresi_dolunca_atilir():
    saat = [0.0]
    bekleyen = wia.BekleyenTaramalar(omur_sn=60, saat=lambda: saat[0])
    assert bekleyen.ekle(1, [b"a"], 300) == 1
    assert bekleyen.ekle(1, [b"b", b"c"], 300) == 3
    assert bekleyen.sayi(2) == 0
    saat[0] = 61
    assert bekleyen.sayi(1) == 0 and bekleyen.al(1) == ([], None)
    bekleyen.ekle(1, [b"d"], 200)
    assert bekleyen.al(1) == ([b"d"], 200) and bekleyen.sayi(1) == 0


# ---------------------------------------------------------------- uygulama


def _uygulamayi_ice_aktar(tarayici_wia_ayari):
    env = {**os.environ, "ARKA_PLAN_ISCISI": "0", "TARAYICI_WIA": tarayici_wia_ayari}
    sonuc = subprocess.run(
        [sys.executable, "-c", "import sys, app; print(app.TARAYICI_WIA, 'tarayici_wia' in sys.modules)"],
        cwd=PROJE, env=env, capture_output=True, text=True, timeout=120,
    )
    return sonuc.stdout.strip(), sonuc.stderr[-500:]


def test_windowsta_varsayilan_acik_ayar_gerekmez():
    cikti, hata = _uygulamayi_ice_aktar("")
    # Acik olsa da modul ilk kullanima kadar yuklenmez.
    assert cikti == f"{sys.platform == 'win32'} False", hata


def test_kapaliyken_buton_yok_modul_yuklenmez(girisli, monkeypatch):
    c, _ = girisli
    monkeypatch.setattr(uygulama_modulu, "TARAYICI_WIA", False)
    assert c.get("/tara").status_code == 404
    assert c.post("/tara", data={"cihaz": "t1"}).status_code == 404
    assert c.get("/tarayici/durum").status_code == 404
    sayfa = c.get("/").get_data(as_text=True)
    assert "data-tara-menu" not in sayfa and "data-tara-dugmesi" not in sayfa and "tarayici-bildirim-sablonu" not in sayfa
    cikti, hata = _uygulamayi_ice_aktar("0")
    assert cikti == "False False", hata


@pytest.fixture
def wia_acik(monkeypatch):
    monkeypatch.setattr(uygulama_modulu, "TARAYICI_WIA", True)


def _gizli_mi(sayfa, isaret):
    """isaret'i tasiyan etiket hidden ozniteligiyle mi yazilmis?"""
    bas = sayfa.index(isaret)
    return "hidden" in sayfa[sayfa.rfind("<", 0, bas):sayfa.index(">", bas)]


def test_tara_dugmesi_yalnizca_tarayici_bagliyken(girisli, wia_acik, com):
    c, _ = girisli
    sahte = com()
    sayfa = c.get("/").get_data(as_text=True)
    assert _gizli_mi(sayfa, "data-tara-dugmesi") and _gizli_mi(sayfa, "data-tara-menu")
    assert "tarayici-bildirim-sablonu" in sayfa and "data-tarayici-adresi" in sayfa

    sahte.bilgiler.append(Bilgi("t1", "Canon LiDE 300"))
    wia.yenile()  # arka plan is parcacigi yerine
    durum = c.get("/tarayici/durum").get_json()
    assert durum["tarayicilar"] == [{"id": "t1", "ad": "Canon LiDE 300"}]
    assert durum["ilerleme"] == {"taraniyor": False, "sayfa": 0} and durum["bekleyen_sayfa"] == 0
    sayfa = c.get("/").get_data(as_text=True)
    assert not _gizli_mi(sayfa, "data-tara-dugmesi") and not _gizli_mi(sayfa, "data-tara-menu")


def test_tek_tarayicida_secim_sorulmaz(girisli, wia_acik, com):
    c, _ = girisli
    com(Bilgi("t1", "Canon LiDE 300"))
    sayfa = c.get("/tara").get_data(as_text=True)
    assert "data-tara-formu" in sayfa and "data-tek-tarayici" in sayfa and "Canon LiDE 300" in sayfa
    assert 'type="radio"' not in sayfa
    assert _gizli_mi(sayfa, "data-tarayici-yok")
    # Gelismis ayarlar kapali bir "Ayarlar" bolumunde; varsayilan 300 dpi.
    assert "<details" in sayfa and "data-tara-ayarlari" in sayfa and 'value="300" selected' in sayfa


def test_birden_fazla_tarayicida_secim(girisli, wia_acik, com):
    c, _ = girisli
    com(Bilgi("t1", "Canon"), Bilgi("t2", "HP"))
    sayfa = c.get("/tara").get_data(as_text=True)
    assert sayfa.count('type="radio"') == 2
    yanit = c.post("/tara", data={}, headers=JSON)
    assert yanit.status_code == 400 and "hangisiyle" in yanit.get_json()["hata"]


def test_tarayici_yoksa_sade_mesaj_ve_yardim(girisli, wia_acik, com):
    c, _ = girisli
    com()
    sayfa = c.get("/tara").get_data(as_text=True)
    assert not _gizli_mi(sayfa, "data-tarayici-yok") and "data-tara-formu" not in sayfa
    assert "Tarayıcı bulunamadı. Kablonun takılı ve tarayıcının açık olduğundan emin olun." in sayfa
    assert "Windows Faks ve Tarama" in sayfa and "sürücü" in sayfa
    yanit = c.post("/tara", data={}, headers=JSON)
    assert yanit.status_code == 400 and yanit.get_json()["hata"] == wia.BULUNAMADI
    # WIA hic kullanilamiyorsa da ayni sade sayfa (teknik hata yok).
    com(dispatch_hatasi=True)
    sayfa = c.get("/tara").get_data(as_text=True)
    assert not _gizli_mi(sayfa, "data-tarayici-yok") and "WIA" not in sayfa.split("<main", 1)[1].split("</main>")[0]


def test_camli_yuzeyden_sayfa_sayfa_tek_belge(girisli, wia_acik, com):
    c, k = girisli
    com(Bilgi("t1", "T", cihaz=Cihaz(Oge([_png(), _png("gri")]))))
    assert c.post("/tara", data={}, headers=JSON).get_json() == {"bitti": False, "adres": None, "sayfa_sayisi": 1}
    assert c.get("/tarayici/durum").get_json()["bekleyen_sayfa"] == 1
    sayfa = c.get("/tara").get_data(as_text=True)
    assert not _gizli_mi(sayfa, "data-tara-sonraki") and _gizli_mi(sayfa, "data-tara-basla")
    assert database.belge_sayisi(k["id"]) == 0  # "Bitir"e kadar belge olusmaz

    assert c.post("/tara", data={}, headers=JSON).get_json()["sayfa_sayisi"] == 2  # "Sonraki sayfa"
    yanit = c.post("/tara/bitir", headers=JSON).get_json()
    assert yanit["bitti"] and yanit["sayfa_sayisi"] == 2
    belge_id = int(yanit["adres"].rsplit("/", 1)[1])
    kayit = database.belge_icerigi(k["id"], belge_id)
    assert kayit["mime_type"] == "application/pdf"
    with pymupdf.open(stream=crypto.coz(kayit["veri"]), filetype="pdf") as pdf:
        assert pdf.page_count == 2
    assert c.get("/tarayici/durum").get_json()["bekleyen_sayfa"] == 0


def test_js_kapaliyken_form_ile_tek_sayfa(girisli, wia_acik, com):
    c, k = girisli
    com(Bilgi("t1", "T", cihaz=Cihaz(Oge([_png()]))))
    yanit = c.post("/tara", data={"cihaz": "t1", "dpi": "300", "renk": "renkli"})
    assert yanit.status_code == 302 and yanit.headers["Location"].endswith("/tara")
    yanit = c.post("/tara/bitir")
    assert yanit.status_code == 302 and "/belge/" in yanit.headers["Location"]
    belge_id = int(yanit.headers["Location"].rsplit("/", 1)[1])
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["dosya_adi"].startswith("tarama_") and kayit["mime_type"] == "image/jpeg"
    assert kayit["isleme_bilgi"]["kaynak"] == "tarayici" and not kayit["gelen_kutusu"]


def test_besleyicideki_tum_sayfalar_tek_seferde(girisli, wia_acik, com):
    c, k = girisli
    com(Bilgi("t1", "T", cihaz=_adf_dolu(Oge([_png() for _ in range(3)]))))
    yanit = c.post("/tara", data={}, headers=JSON).get_json()
    assert yanit["bitti"] and yanit["sayfa_sayisi"] == 3
    kayit = database.belge_icerigi(k["id"], int(yanit["adres"].rsplit("/", 1)[1]))
    with pymupdf.open(stream=crypto.coz(kayit["veri"]), filetype="pdf") as pdf:
        assert pdf.page_count == 3


def test_vazgec_sayfalari_atar(girisli, wia_acik, com):
    c, k = girisli
    com(Bilgi("t1", "T", cihaz=Cihaz(Oge([_png()]))))
    c.post("/tara", data={}, headers=JSON)
    assert c.post("/tara/iptal", headers=JSON).get_json()["sayfa_sayisi"] == 0
    yanit = c.post("/tara/bitir", headers=JSON)
    assert yanit.status_code == 400 and database.belge_sayisi(k["id"]) == 0


def test_bekleyen_sayfalar_kullaniciya_ozel(uygulama, girisli, wia_acik, com, kullanici):
    c, _ = girisli
    com(Bilgi("t1", "T", cihaz=Cihaz(Oge([_png()]))))
    c.post("/tara", data={}, headers=JSON)
    diger = uygulama.test_client()
    giris_yap(diger, kullanici()["ad"])
    assert diger.get("/tarayici/durum").get_json()["bekleyen_sayfa"] == 0
    assert diger.post("/tara/bitir", headers=JSON).status_code == 400


def test_tarama_hatasi_belge_olusturmaz(girisli, wia_acik, com):
    c, k = girisli
    com(Bilgi("t1", "T", cihaz=Cihaz(Oge([])), baglanti_hatasi=0x80210006))
    yanit = c.post("/tara", data={"cihaz": "t1"}, follow_redirects=True)
    assert "meşgul" in yanit.get_data(as_text=True)
    yanit = c.post("/tara", data={}, headers=JSON)
    assert yanit.status_code == 400 and "meşgul" in yanit.get_json()["hata"]
    assert database.belge_sayisi(k["id"]) == 0


def test_kota_doluysa_taranmaz(girisli, wia_acik, com, monkeypatch):
    c, k = girisli
    monkeypatch.setattr(uygulama_modulu, "KULLANICI_BELGE_LIMITI", 1)
    belge_ekle(k["id"])
    oge = Oge([_png()])
    com(Bilgi("t1", "T", cihaz=Cihaz(oge)))
    yanit = c.post("/tara", data={"cihaz": "t1"}, follow_redirects=True)
    assert "kotanız doldu" in yanit.get_data(as_text=True)
    assert oge.bicimler == [] and database.belge_sayisi(k["id"]) == 1


# ---------------------------------------------------------------- yonetici durum sayfasi


def test_durum_sayfasi_yalnizca_yoneticiye(uygulama, girisli, wia_acik, com, kullanici, monkeypatch):
    c, _ = girisli
    assert c.get("/tarama-durumu").status_code == 404
    assert "data-tarama-durumu-menu" not in c.get("/").get_data(as_text=True)

    y = kullanici()
    database._sorgula("UPDATE kullanicilar SET yonetici = TRUE WHERE id = %s", (y["id"],))
    yc = uygulama.test_client()
    giris_yap(yc, y["ad"])
    com(Bilgi("t1", "Canon LiDE 300"))
    tarama_gunlugu.aktarildi("tarama_001.jpg", y["ad"], kaynak="Windows tarama klasörü")
    tarama_gunlugu.hata("Tarayıcı", "Kâğıt sıkıştı.")
    monkeypatch.setattr(uygulama_modulu.klasor_izleme, "izlenen_klasorler", lambda: [
        {"yol": r"C:\Users\x\Documents\Scanned Documents", "tur": "Windows tarama klasörü", "izleniyor": True, "not": ""},
    ])
    sayfa = yc.get("/tarama-durumu").get_data(as_text=True)
    assert "data-tarama-durumu-menu" in sayfa
    for beklenen in ("Canon LiDE 300", "Scanned Documents", "tarama_001.jpg", "Kâğıt sıkıştı."):
        assert beklenen in sayfa
    assert "<form" not in sayfa.split("<main", 1)[1].split("</main>")[0]  # yalnizca bilgi
