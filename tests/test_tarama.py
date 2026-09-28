"""Tarama filtreleri (tarama.py): golge ve sari isik temizligi, renk korunumu,
gri/siyah-beyaz modlar, gurultu temizligi, hiz ve /tarama/<id> onizleme route'u."""

import io
import re
import time

import cv2
import numpy as np
import pytest
from PIL import Image

import crypto
import database
import tarama
from ornek_gorseller import isik_bozulmasi, jpeg_bayt, renkli_belge, sayfa


def _bgr(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


@pytest.fixture(scope="module")
def ornek():
    """2000 px'lik, sari isikli ve golgeli, imzali/muhurlu renkli belge."""
    rgb, maskeler = renkli_belge((1414, 2000))
    bozuk = _bgr(isik_bozulmasi(rgb))
    yazi = (rgb.max(axis=2) < 100) & ~(maskeler["mavi"] | maskeler["kirmizi"] | maskeler["turuncu"])
    return bozuk, dict(maskeler, yazi=yazi)


def _kirp(maske, cikti, girdi):
    """Kenar kirpmadan sonra maskeyi cikti koordinatlarina tasir."""
    pay = (girdi.shape[0] - cikti.shape[0]) // 2
    return maske[pay:pay + cikti.shape[0], pay:pay + cikti.shape[1]]


@pytest.mark.parametrize("mod", tarama.MODLAR)
def test_golge_ve_sari_isik_temizlenir(ornek, mod):
    girdi, m = ornek
    assert girdi[m["kagit"]].std() > 20  # girdide kagit belirgin sekilde lekeli
    cikti = tarama.tara(girdi, mod)
    kagit = cikti[_kirp(m["kagit"], cikti, girdi)]
    parlaklik = kagit.min(axis=-1) if kagit.ndim == 2 else kagit
    assert (parlaklik >= 245).mean() > 0.98, mod


@pytest.mark.parametrize("mod", tarama.MODLAR)
def test_siyah_yazi_korunur(ornek, mod):
    girdi, m = ornek
    cikti = tarama.tara(girdi, mod)
    yazi = cikti[_kirp(m["yazi"], cikti, girdi)]
    koyu = yazi.max(axis=-1) if yazi.ndim == 2 else yazi
    assert (koyu < 110).mean() > 0.85, mod


def test_renkli_modda_murekkep_muhur_ve_logo_renkleri_korunur(ornek):
    girdi, m = ornek
    cikti = tarama.tara(girdi, "renkli")
    mavi_b, mavi_g, mavi_r = cikti[_kirp(m["mavi"], cikti, girdi)].mean(axis=0)
    assert mavi_b > mavi_r + 120 and mavi_b > mavi_g + 100  # mavi murekkep hala mavi
    kir_b, kir_g, kir_r = cikti[_kirp(m["kirmizi"], cikti, girdi)].mean(axis=0)
    assert kir_r > kir_g + 120 and kir_r > kir_b + 120  # kirmizi muhur hala kirmizi
    tur_b, tur_g, tur_r = cikti[_kirp(m["turuncu"], cikti, girdi)].mean(axis=0)
    assert tur_r > 220 and 90 < tur_g < 200 and tur_b < 60  # turuncu logo solmadi


def test_gri_ve_sb_tek_kanal_sb_ikili(ornek):
    girdi, _ = ornek
    assert tarama.tara(girdi, "gri").ndim == 2
    sb = tarama.tara(girdi, "sb")
    assert sb.ndim == 2 and set(np.unique(sb)) <= {0, 255}


def test_siyah_beyazda_kucuk_gurultu_silinir():
    rgb, m = renkli_belge((1414, 2000))
    rng = np.random.default_rng(7)
    noktali = rgb.copy()
    kagit_y, kagit_x = np.nonzero(m["kagit"])
    secim = rng.choice(len(kagit_y), 400, replace=False)
    for y, x in zip(kagit_y[secim], kagit_x[secim]):
        cv2.circle(noktali, (int(x), int(y)), 1, (60, 60, 60), -1)  # toz / kagit dokusu
    sb = tarama.tara(_bgr(noktali), "sb")
    kagit = _kirp(m["kagit"], sb, noktali)
    assert (sb[kagit] == 0).sum() < 40  # 400 noktanin neredeyse hepsi silindi


def test_temiz_belge_bozulmaz():
    rgb, m = renkli_belge()
    cikti = tarama.tara(_bgr(rgb), "renkli")
    kagit = cikti[_kirp(m["kagit"], cikti, rgb)]
    assert (kagit.min(axis=1) >= 250).mean() > 0.99


def test_buyuk_koyu_logo_solmaz_ve_cevresinde_hale_olmaz():
    """QR kod / logo gibi yazidan cok buyuk koyu alan: ince isik haritasi onu
    kagit sanip soldurmaz, cevresinde gri ya da parlak hale kalmaz."""
    rgb = sayfa((1414, 2000)).copy()
    x0, y0, x1, y1 = 900, 1300, 1250, 1650
    rgb[y0:y1, x0:x1] = 20
    cikti = tarama.tara(_bgr(isik_bozulmasi(rgb)), "renkli").min(axis=2)
    p = (2000 - cikti.shape[0]) // 2  # kenar kirpma
    assert cikti[y0 - p + 20:y1 - p - 20, x0 - p + 20:x1 - p - 20].mean() < 40
    halka = np.zeros(cikti.shape, bool)
    halka[y0 - p - 40:y1 - p + 40, x0 - p - 40:x1 - p + 40] = True
    halka[y0 - p - 5:y1 - p + 5, x0 - p - 5:x1 - p + 5] = False
    assert (cikti[halka] >= 245).mean() > 0.995


def test_vinyetli_kenarlar_tam_beyaz():
    """Fotograf koselerindeki isik azalmasi taramada gri kenar birakmaz."""
    yy, xx = np.mgrid[0:2000, 0:1414]
    r2 = (((xx - 707) / 707) ** 2 + ((yy - 1000) / 1000) ** 2) / 2
    vinyetli = (sayfa((1414, 2000)).astype(np.float32) * (1 - 0.45 * r2)[..., None]).astype(np.uint8)
    cikti = tarama.tara(_bgr(vinyetli), "renkli").min(axis=2)
    for serit in (cikti[:40], cikti[-40:], cikti[:, :40], cikti[:, -40:]):
        assert (serit >= 250).mean() > 0.99


def test_kenar_kirpilir_ve_gecersiz_mod():
    girdi = np.full((2000, 1414, 3), 255, np.uint8)
    cikti = tarama.tara(girdi, "renkli")
    assert cikti.shape[0] == 2000 - 2 * 8 and cikti.shape[1] == 1414 - 2 * 8
    with pytest.raises(ValueError):
        tarama.tara(girdi, "sepya")


@pytest.mark.parametrize("mod", tarama.MODLAR)
def test_2000_px_bir_saniyenin_altinda(ornek, mod):
    girdi, _ = ornek
    tarama.tara(girdi, mod)  # isinma
    bas = time.perf_counter()
    tarama.tara(girdi, mod)
    assert time.perf_counter() - bas < 1.0


def test_jpeg_cikti():
    veri = tarama.jpeg(np.full((50, 40), 255, np.uint8))
    assert veri[:2] == b"\xff\xd8"


# ---------------------------------------------------------------- /tarama/<id> onizleme route'u


def _belge(kullanici_id, veri, mime="image/jpeg", **ek):
    return database.belge_ekle(
        kullanici_id=kullanici_id, dosya_adi="b.jpg", mime_type=mime,
        sifreli_icerik=crypto.sifrele(veri), sifreli_onizleme=None,
        ocr_metni="", tur="fatura", guven=0.9, aciklama="", **ek,
    )


def test_tarama_onizleme_modlari(girisli):
    c, k = girisli
    rgb, _ = renkli_belge((700, 990))
    belge_id = _belge(k["id"], jpeg_bayt(isik_bozulmasi(rgb)), orijinal_saklandi=True)
    boyutlar = {}
    for mod in ("renkli", "gri", "sb", "orijinal"):
        r = c.get(f"/tarama/{belge_id}?mod={mod}")
        assert r.status_code == 200 and r.mimetype == "image/jpeg"
        g = Image.open(io.BytesIO(r.data))
        boyutlar[mod] = g.size
        if mod == "renkli":
            assert np.asarray(g)[40:80, 40:80].min() > 240  # sari/golgeli kose beyazladi
        if mod == "orijinal":
            assert np.asarray(g)[40:80, 40:80, 2].mean() < 200  # filtresiz: sari kalir (mavi kanal dusuk)
    assert len(set(boyutlar.values())) == 1  # karsilastirma icin ayni boyut
    varsayilan = c.get(f"/tarama/{belge_id}").data
    assert varsayilan == c.get(f"/tarama/{belge_id}?mod=renkli").data == c.get(f"/tarama/{belge_id}?mod=sepya").data


def test_tarama_koseleri_uygular(girisli):
    c, k = girisli
    veri = jpeg_bayt(np.full((400, 600, 3), 255, np.uint8))
    belge_id = _belge(k["id"], veri, orijinal_saklandi=True,
                      koseler=[[100, 50], [400, 50], [400, 350], [100, 350]])
    g = Image.open(io.BytesIO(c.get(f"/tarama/{belge_id}?mod=orijinal").data))
    assert abs(g.width - 300) <= 10 and abs(g.height - 300) <= 10


def test_detay_sayfasi_mod_secici(girisli):
    c, k = girisli
    belge_id = _belge(k["id"], jpeg_bayt(np.full((100, 80, 3), 255, np.uint8)))
    sayfa = c.get(f"/belge/{belge_id}").get_data(as_text=True)
    # adres icerik surumunu tasir (?v=), mod en sonda
    assert re.search(rf'src="/tarama/{belge_id}\?v=\d+&amp;mod=renkli"', sayfa)
    assert re.search(r'data-mod="renkli"\s+aria-checked="true"', sayfa)
    gri = c.get(f"/belge/{belge_id}?mod=gri").get_data(as_text=True)
    assert re.search(rf'src="/tarama/{belge_id}\?v=\d+&amp;mod=gri"', gri)
    for ad in ("Renkli tarama", "Gri", "Siyah-beyaz", "Orijinal fotoğraf", "Önce | sonra"):
        assert ad in sayfa


def test_pdf_icin_mod_secici_yok_ve_ilk_sayfa(girisli):
    import pymupdf

    c, k = girisli
    pdf = pymupdf.open()
    pdf.new_page()
    belge_id = _belge(k["id"], pdf.tobytes(), mime="application/pdf")
    assert "segment-dugmesi" not in c.get(f"/belge/{belge_id}").get_data(as_text=True)
    assert c.get(f"/tarama/{belge_id}?mod=sb").mimetype == "image/png"


def test_baskasinin_taramasi_404(girisli, kullanici):
    c, _ = girisli
    diger = kullanici()
    belge_id = _belge(diger["id"], jpeg_bayt(np.full((100, 80, 3), 255, np.uint8)))
    assert c.get(f"/tarama/{belge_id}?mod=renkli").status_code == 404
