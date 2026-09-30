"""Gercek WIA ile tarayici entegrasyon testi (yalnizca Windows, bagli tarayici).

Sahte COM katmani (test_tarayici_wia.py) WIA'nin gercek davranisini
yakalayamaz; bu testler uygulamanin kullandigi yolu (arka plan is parcacigi,
kendi COM oturumu) gercek WIA.DeviceManager ile karsilastirir. WIA'da tarayici
yoksa atlanir. Gercek tarama kagit gerektirir; ayrica acilir:

    pytest -m slow tests/test_tarayici_wia_gercek.py
    TARAYICI_GERCEK_TARA=1 pytest -m slow tests/test_tarayici_wia_gercek.py   # camdaki kagidi tarar
"""

import os
import sys
import threading

import pytest

import tarayici_wia as wia

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(sys.platform != "win32", reason="WIA yalnizca Windows'ta var"),
]


def _is_parcaciginda(islev):
    """islev'i ayri is parcaciginda calistirir (uygulamanin yoklama is parcacigi gibi)."""
    sonuc = {}

    def calistir():
        try:
            sonuc["deger"] = islev()
        except BaseException as hata:  # noqa: BLE001 - ana is parcacigina tasinir
            sonuc["hata"] = hata

    is_parcacigi = threading.Thread(target=calistir)
    is_parcacigi.start()
    is_parcacigi.join(60)
    assert not is_parcacigi.is_alive(), "WIA 60 sn icinde yanit vermedi"
    if "hata" in sonuc:
        raise sonuc["hata"]
    return sonuc["deger"]


def _ham_cihazlar():
    """WIA'nin gordugu tum cihazlar, uygulamanin koduna dokunmadan: [(id, tur, ad)]."""
    pythoncom = pytest.importorskip("pythoncom")
    istemci = pytest.importorskip("win32com.client")
    pythoncom.CoInitialize()
    try:
        cihazlar = []
        for bilgi in istemci.Dispatch("WIA.DeviceManager").DeviceInfos:
            cihazlar.append((str(bilgi.DeviceID), int(bilgi.Type), wia._ad(bilgi)))
            del bilgi
        return cihazlar
    finally:
        pythoncom.CoUninitialize()


@pytest.fixture(scope="module")
def tarayici():
    cihazlar = _is_parcaciginda(_ham_cihazlar)
    tarayicilar = [c for c in cihazlar if c[1] == wia.TARAYICI_TURU]
    if not tarayicilar:
        pytest.skip(f"WIA'da tarayici yok (WIA'daki tum cihazlar: {cihazlar or 'hic'})")
    return tarayicilar[0]


@pytest.fixture(autouse=True)
def _temiz_durum():
    wia.sifirla()
    yield
    wia.sifirla()


def test_ana_ve_arka_plan_is_parcacigi_ayni_tarayicilari_gorur(tarayici):
    ham = {c[0] for c in _is_parcaciginda(_ham_cihazlar) if c[1] == wia.TARAYICI_TURU}
    ana = {t["id"] for t in wia.tarayicilari_listele()}
    arka = {t["id"] for t in _is_parcaciginda(wia.tarayicilari_listele)}
    assert ana == ham
    assert arka == ham


def test_yoklama_tarayiciyi_bulur(tarayici):
    kimlik, _, ad = tarayici
    bulunan = _is_parcaciginda(wia.yenile)
    assert {"id": kimlik, "ad": ad} in bulunan
    assert wia.bagli_tarayicilar(yenile_gerekirse=False) == bulunan


def test_tarayiciya_baglanilir(tarayici):
    """Listelemenin otesinde surucu gercekten yuklenir: cihaz acilir, tarama ogesi vardir."""

    def baglan():
        with wia._ComOturumu() as istemci:
            bilgi = next(b for b in wia._tarayici_bilgileri(istemci) if str(b.DeviceID) == tarayici[0])
            cihaz = bilgi.Connect()
            sayi = int(cihaz.Items.Count)
            del bilgi, cihaz
            return sayi

    assert _is_parcaciginda(baglan) >= 1


@pytest.mark.skipif(os.environ.get("TARAYICI_GERCEK_TARA") != "1",
                    reason="camda kagit gerekir; TARAYICI_GERCEK_TARA=1 ile acilir")
def test_camdan_gercek_tarama(tarayici):
    sayfalar, besleyici = _is_parcaciginda(lambda: wia.tara(tarayici[0], dpi=200, renk="gri", kaynak="cam"))
    assert besleyici is False
    assert len(sayfalar) == 1
    assert sayfalar[0][:8] == b"\x89PNG\r\n\x1a\n"
