"""Otomatik kirpma ve duzeltme (OpenCV): perspektif, egiklik, dokunulmayan
goruntuler ve yukleme akisina entegrasyon."""

import io
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

import crypto
import database
import goruntu_duzelt
import ocr
from conftest import bayt, gorsel_boyutu, isleme_durumu, jpeg, ocr_gerekli, yazili_gorsel, yukle
from ornek_gorseller import (
    COK_EGIK,
    HAFIF_EGIK,
    egik_tarama,
    isik_bozulmasi,
    jpeg_bayt,
    masada_egik_cekim,
    renkli_belge,
    sayfa,
)


def _bgr(veri):
    return np.asarray(Image.open(io.BytesIO(veri)).convert("RGB"))[..., ::-1].copy()


def test_masadaki_belge_kirpilip_duzeltilir():
    veri = jpeg_bayt(masada_egik_cekim())
    yeni, uygulandi = goruntu_duzelt.duzelt(veri)
    assert uygulandi
    sonuc = np.asarray(Image.open(io.BytesIO(yeni)).convert("L"))
    # Koyu masa kirpildi: kenar seritleri de kagit kadar acik renkli
    for serit in (sonuc[:15], sonuc[-15:], sonuc[:, :15], sonuc[:, -15:]):
        assert serit.mean() > 180
    y, g = sonuc.shape
    assert 0.6 < g / y < 0.95  # dikey sayfa


@pytest.mark.parametrize("aci", [-9, -4, 3, 7, 12])
def test_egik_tarama_duzeltilir(aci):
    veri = jpeg_bayt(egik_tarama(aci))
    yeni, uygulandi = goruntu_duzelt.duzelt(veri)
    assert uygulandi
    assert abs(goruntu_duzelt.egiklik_acisi(_bgr(yeni))) < abs(aci) / 2


@pytest.mark.parametrize(
    "veri",
    [
        jpeg_bayt(sayfa()),  # duz taranmis belge
        jpeg_bayt(egik_tarama(25)),  # +-15 derece sinirinin disi
        jpeg(),  # bos beyaz gorsel
        b"gorsel degil",
    ],
    ids=["duz", "cok-egik", "bos", "bozuk"],
)
def test_uygun_degilse_orijinal_aynen_doner(veri):
    assert goruntu_duzelt.duzelt(veri) == (veri, False)


def test_exif_yonu_uygulanir():
    """EXIF'te 'saat yonunde 90 derece dondur' yazan fotograf, dondurulmus
    halinin aynisi gibi duzeltilir."""
    exif = Image.Exif()
    exif[0x0112] = 6
    g = Image.fromarray(masada_egik_cekim())
    exifli, _ = goruntu_duzelt.duzelt(bayt(g, "JPEG", exif=exif.tobytes()))
    beklenen, _ = goruntu_duzelt.duzelt(bayt(g.transpose(Image.Transpose.ROTATE_270), "JPEG"))
    a, b = Image.open(io.BytesIO(exifli)).size, Image.open(io.BytesIO(beklenen)).size
    assert a[0] > a[1] and abs(a[0] - b[0]) < 10 and abs(a[1] - b[1]) < 10


# ---------------------------------------------------------------- yukleme akisi

def test_yuklemede_duzeltme_uygulanir_ve_rozet_gosterilir(girisli, monkeypatch):
    c, k = girisli
    okunan = {}

    def sahte_ocr(veri, mime):
        okunan["boyut"] = gorsel_boyutu(veri)
        return "FATURA"

    monkeypatch.setattr(ocr, "metin_cikar", sahte_ocr)
    r = yukle(c, jpeg_bayt(masada_egik_cekim()), "masa.jpg")
    belge_id = int(r.headers["Location"].rsplit("/", 1)[1])
    assert okunan["boyut"] != (3000, 2250)  # OCR kirpilmis goruntuyu okudu
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["otomatik_duzeltildi"]
    assert "Otomatik düzeltildi" in c.get(f"/belge/{belge_id}").get_data(as_text=True)


def test_anahtar_kapaliyken_duzeltme_yapilmaz(girisli, monkeypatch):
    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    r = yukle(c, jpeg_bayt(masada_egik_cekim()), "masa.jpg", data_ek={"otomatik_duzelt": "0"})
    kayit = database.belge_getir(k["id"], int(r.headers["Location"].rsplit("/", 1)[1]))
    assert not kayit["otomatik_duzeltildi"]
    assert "Otomatik düzeltildi" not in c.get(f"/belge/{kayit['id']}").get_data(as_text=True)


def test_anahtar_acik_formu_gizli_alanla_birlikte(girisli, monkeypatch):
    """Formda gizli '0' + isaretli kutu '1' birlikte gelir; son deger gecerlidir."""
    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    r = yukle(c, jpeg_bayt(masada_egik_cekim()), "masa.jpg", data_ek={"otomatik_duzelt": ["0", "1"]})
    assert database.belge_getir(k["id"], int(r.headers["Location"].rsplit("/", 1)[1]))["otomatik_duzeltildi"]


def test_pdf_duzeltilmez(girisli, monkeypatch):
    import pymupdf

    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    monkeypatch.setattr(goruntu_duzelt, "duzelt", lambda veri: pytest.fail("PDF'e duzeltme uygulandi"))
    belge = pymupdf.open()
    belge.new_page()
    r = yukle(c, belge.tobytes(), "belge.pdf")
    assert r.status_code == 302
    assert "Otomatik düzeltildi" not in c.get(r.headers["Location"]).get_data(as_text=True)


@ocr_gerekli
def test_duzeltme_ocr_sonucunu_bozmaz():
    """Duz, metinli gorselde duzeltme devreye girmez; OCR ayni kalir."""
    veri = bayt(yazili_gorsel(), "PNG")
    yeni, uygulandi = goruntu_duzelt.duzelt(veri)
    assert not uygulandi and yeni == veri


@ocr_gerekli
def test_duzeltme_oncesi_sonrasi_ocr_karsilastirmasi():
    """~30 derece donuk, masada cekilmis fotograf: duzeltmeden once Tesseract
    anahtar satirlari okuyamaz, sonra okur (README'deki tablo)."""
    from ornek_gorseller import COK_EGIK

    veri = jpeg_bayt(masada_egik_cekim(koseler=COK_EGIK, tohum=2))
    yeni, uygulandi = goruntu_duzelt.duzelt(veri)
    assert uygulandi
    once, sonra = ocr.metin_cikar(veri, "image/jpeg"), ocr.metin_cikar(yeni, "image/jpeg")
    anahtarlar = ["ABC2026000000123", "15.03.2026", "1.200,00"]
    assert sum(a in sonra for a in anahtarlar) == 3
    assert sum(a in once for a in anahtarlar) < 3 and len(sonra) > len(once)


# ---------------------------------------------------------------- v5: coklu aday algilama, puan, ince egiklik

TUVAL = (3000, 2250)
DIK_15 = ((0.28, 0.10), (0.72, 0.04), (0.78, 0.92), (0.30, 0.97))  # ~15 derece yamuk


def _kose_hatasi(bulunan, oransal):
    gercek = np.float32([[TUVAL[0] * x, TUVAL[1] * y] for x, y in oransal])
    return np.abs(bulunan - gercek).max() / np.hypot(*TUVAL)


@pytest.mark.parametrize(
    "ayar",
    [
        dict(koseler=DIK_15),
        dict(koseler=COK_EGIK, tohum=2),  # ~30 derece
        dict(koseler=HAFIF_EGIK, zemin_tonu=240),  # beyaz masada beyaz kagit
        dict(koseler=COK_EGIK, zemin_tonu=245),
    ],
    ids=["15-derece", "30-derece", "beyaz-masa", "beyaz-masa-30-derece"],
)
def test_zor_cekimlerde_koseler_bulunur(ayar):
    a = goruntu_duzelt.analiz(_bgr(jpeg_bayt(masada_egik_cekim(**ayar))))
    assert a["belge"] and a["puan"] >= goruntu_duzelt.EMIN_PUANI
    assert _kose_hatasi(a["koseler"], ayar["koseler"]) < 0.01  # kosegenin %1'i


def test_sari_isikli_golgeli_muhurlu_belge():
    rgb, _ = renkli_belge()
    foto = isik_bozulmasi(masada_egik_cekim(koseler=DIK_15, kagit=rgb, zemin_tonu=220))
    a = goruntu_duzelt.analiz(_bgr(jpeg_bayt(foto)))
    assert a["belge"] and _kose_hatasi(a["koseler"], DIK_15) < 0.01


def test_ince_egiklik_koselere_katlanir():
    """Kagit dogru kirpilsa da yazi kagida 3 derece yamuk basilmis: satirlar
    yatay olacak sekilde koseler dondurulur."""
    foto = masada_egik_cekim(koseler=HAFIF_EGIK, kagit=egik_tarama(3.0))
    bgr = _bgr(jpeg_bayt(foto))
    a = goruntu_duzelt.analiz(bgr)
    duz = goruntu_duzelt.uygula(bgr, a["koseler"])
    assert abs(goruntu_duzelt.egiklik_acisi(duz, 5)) < 0.5


def test_kadrajdan_tasan_kagit_emin_degil():
    tasan = ((0.35, 0.10), (1.08, 0.12), (1.05, 0.92), (0.30, 0.90))
    a = goruntu_duzelt.analiz(_bgr(jpeg_bayt(masada_egik_cekim(koseler=tasan))))
    assert a["belge"] and a["puan"] < goruntu_duzelt.EMIN_PUANI


def test_uygula_ve_kose_dogrulama():
    bgr = np.zeros((100, 200, 3), np.uint8)
    assert goruntu_duzelt.uygula(bgr, None) is bgr
    duz = goruntu_duzelt.uygula(bgr, [[10, 10], [110, 10], [110, 60], [10, 60]])
    assert duz.shape[:2] == (50, 100)
    assert goruntu_duzelt.koseler_gecerli([[0, 0], [200, 0], [200, 100], [0, 100]], (200, 100))
    assert not goruntu_duzelt.koseler_gecerli([[0, 0], [200, 100], [200, 0], [0, 100]], (200, 100))  # kesisen
    assert not goruntu_duzelt.koseler_gecerli([[0, 0], [5, 0], [5, 5], [0, 5]], (200, 100))  # cok kucuk
    assert not goruntu_duzelt.koseler_gecerli([[0, 0], [900, 0], [900, 100], [0, 100]], (200, 100))  # disarida
    assert not goruntu_duzelt.koseler_gecerli("bozuk", (200, 100))


# ---------------------------------------------------------------- v6: kenar cizgisi algilama, kontrast puani, A4

def _duvarli_yansimali_cekim():
    """Koyu masada kagit; sagda kagida degen ve kadraj kenarina uzanan beyaz
    duvar, solda kagidin ustune tasan parlak masa yansimasi. Parlaklik maskesi
    duvari ve yansimayi kagitla birlestirir."""
    foto = masada_egik_cekim(koseler=DIK_15, zemin_tonu=90, tohum=4).astype(np.float32)
    y, g = foto.shape[:2]
    duvar = np.zeros((y, g), np.uint8)
    cv2.fillConvexPoly(duvar, np.int32([[0.80 * g, 0.3 * y], [g, 0.25 * y], [g, 0.95 * y], [0.79 * g, 0.95 * y]]), 255)
    foto[duvar > 0] = 240
    yansima = np.zeros((y, g), np.float32)
    cv2.ellipse(yansima, (int(0.2 * g), int(0.6 * y)), (int(0.12 * g), int(0.08 * y)), 0, 0, 360, 1.0, -1)
    yansima = cv2.GaussianBlur(yansima, (0, 0), 40)[..., None]
    return (foto * (1 - yansima) + 250 * yansima).clip(0, 255).astype(np.uint8)


def test_beyaz_duvar_ve_yansima_kagit_sanilmaz():
    a = goruntu_duzelt.analiz(_bgr(jpeg_bayt(_duvarli_yansimali_cekim())))
    assert a["belge"] and a["puan"] >= goruntu_duzelt.EMIN_PUANI
    assert _kose_hatasi(a["koseler"], DIK_15) < 0.01


def test_kadrajdan_tasan_koseler_kenar_cizgilerinden_bulunur():
    """Alt iki kose kadraj disinda ama dort kenar da kismen gorunuyor: koseler
    kenar cizgilerinin kesisiminden (goruntu disinda) bulunur."""
    tasan_alt = ((0.22, 0.08), (0.74, 0.06), (1.03, 0.97), (-0.04, 0.95))
    a = goruntu_duzelt.analiz(_bgr(jpeg_bayt(masada_egik_cekim(koseler=tasan_alt))))
    assert a["belge"] and a["puan"] >= goruntu_duzelt.EMIN_PUANI
    assert _kose_hatasi(a["koseler"], tasan_alt) < 0.01
    assert a["koseler"][2][0] > TUVAL[0] and a["koseler"][3][0] < 0


def test_kadraj_disi_bolge_kenar_seridini_tekrarlamaz():
    """Fotografin kenarindaki ince koyu serit (laptop, vinyet) kadraj disina
    tasan kagit bolgesine uzatilmaz."""
    bgr = np.full((400, 300, 3), 230, np.uint8)
    bgr[:, :2] = (80, 20, 20)
    duz = goruntu_duzelt.uygula(bgr, [[30, 20], [280, 20], [280, 380], [-30, 380]])
    assert duz.min() > 200


def _kamera_goruntusu(egim, yan=0.0, odak=1600, tuval=(2000, 1500), uzaklik=0.42):
    """A4 kagidin (210x297 mm) ust kenari kameradan uzaklasacak sekilde 'egim',
    dikey eksen etrafinda 'yan' derece dondurulup igne delikli kamerayla
    (odak px) cekilmis koseleri (piksel)."""
    g, y = tuval
    a, b = np.radians(egim), np.radians(yan)
    koseler = []
    for kx, ky in ((-0.105, -0.1485), (0.105, -0.1485), (0.105, 0.1485), (-0.105, 0.1485)):
        px, py, pz = kx, ky * np.cos(a), -ky * np.sin(a)
        px, pz = px * np.cos(b) + pz * np.sin(b), -px * np.sin(b) + pz * np.cos(b) + uzaklik
        koseler.append((odak * px / pz + g / 2, odak * py / pz + y / 2))
    return np.float32(koseler)


@pytest.mark.parametrize(
    "egim, yan, odak",
    [(0, 0, 1600), (40, 15, 1300), (25, 20, 1000), (35, 0, 1300), (35, 0, 2200)],
    ids=["duz", "egik-yan", "genis-aci", "simetrik-kisa-odak", "simetrik-uzun-odak"],
)
def test_perspektifli_a4_dik_a4_olur(egim, yan, odak):
    """Kameraya egik tutulmus A4: fotografta basik gorunur ama cikti tam A4.
    Simetrik yamukta odak hesaplanamaz; makul odak araligi A4'le uyusur."""
    kaynak = _kamera_goruntusu(egim, yan, odak)
    su, sa_ust, sa_alt, so = kaynak
    gorunen = max(np.linalg.norm(so - su), np.linalg.norm(sa_alt - sa_ust)) / np.linalg.norm(sa_alt - so)
    if egim >= 35:
        assert gorunen < 1.3  # fotografta A4'ten (1.414) belirgin sekilde basik
    y, g = goruntu_duzelt.uygula(np.full((1500, 2000, 3), 255, np.uint8), kaynak).shape[:2]
    assert abs(y / g - 2 ** 0.5) < 0.005


def test_a4_cozunurluk_yetiyorsa_300_dpi():
    bgr = np.full((4000, 3000, 3), 255, np.uint8)
    a4 = [[200, 100], [2800, 100], [2800, 3777], [200, 3777]]  # 2600 x 3677, A4 orani
    assert goruntu_duzelt.uygula(bgr, a4).shape[:2] == (3508, 2480)
    kucuk = [[10, 10], [310, 10], [310, 434], [10, 434]]  # 300 px: en az 150 DPI
    assert goruntu_duzelt.uygula(bgr, kucuk).shape[:2] == (1754, 1240)
    # A4 olmayan oranlar (4:3, fis) oldugu gibi kalir
    assert goruntu_duzelt.uygula(bgr, [[0, 0], [400, 0], [400, 300], [0, 300]]).shape[:2] == (300, 400)
    assert goruntu_duzelt.uygula(bgr, [[0, 0], [300, 0], [300, 900], [0, 900]]).shape[:2] == (900, 300)


OZEL_FOTO = Path(__file__).parent / "ozel" / "bu.png"


@pytest.mark.skipif(not OZEL_FOTO.exists(), reason="kisisel test fotografi yok (tests/ozel, git disi)")
def test_gercek_fotograf_elle_kose_vermeden_kirpilir():
    """Sagda beyaz zemin, solda laptop, alt iki kose kadraj disinda. Koseler
    fotograf uzerinde elle olculdu."""
    bgr = cv2.imread(str(OZEL_FOTO))
    a = goruntu_duzelt.analiz(bgr)
    assert a["belge"] and a["puan"] >= goruntu_duzelt.EMIN_PUANI
    elle = np.float32([[76, 84], [475, 75], [579, 726], [-17, 726]])
    assert np.abs(a["koseler"] - elle).max() < 0.02 * np.hypot(*bgr.shape[:2])
    y, g = goruntu_duzelt.uygula(bgr, a["koseler"]).shape[:2]
    assert (g, y) == goruntu_duzelt.A4_150DPI


# ---------------------------------------------------------------- v5: orijinal + kose saklama

def _yuklenen(c, veri, ad="masa.jpg", **form):
    r = yukle(c, veri, ad, data_ek=form)
    return int(r.headers["Location"].rsplit("/", 1)[1])


def test_orijinal_ve_koseler_saklanir_gosterimde_duzeltilir(girisli, monkeypatch):
    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    foto = jpeg_bayt(masada_egik_cekim(koseler=DIK_15))  # 3000x2250 yatay fotograf
    belge_id = _yuklenen(c, foto)

    kayit = database.belge_icerigi(k["id"], belge_id)
    assert kayit["orijinal_saklandi"] and len(kayit["koseler"]) == 4
    saklanan = crypto.coz(kayit["veri"])
    assert Image.open(io.BytesIO(saklanan)).size == (2000, 1500)  # duzeltilmemis, kucultulmus orijinal
    # koseler saklanan gorselin koordinatlarinda (3000 -> 2000 olcek)
    gercek = np.float32([[2000 * x, 1500 * y] for x, y in DIK_15])
    assert np.abs(np.float32(kayit["koseler"]) - gercek).max() < 0.02 * 2500

    gosterilen = Image.open(io.BytesIO(c.get(f"/gorsel/{belge_id}").data))
    assert gosterilen.height > gosterilen.width  # kagit dik: kirpilip duzeltilmis
    onizleme = Image.open(io.BytesIO(c.get(f"/onizleme/{belge_id}").data))
    assert onizleme.height > onizleme.width
    assert c.get(f"/belge/{belge_id}/indir").data == saklanan  # "orijinali indir"
    assert database.belge_getir(k["id"], belge_id)["otomatik_duzeltildi"]


def test_duzeltme_kapaliyken_kose_yok_orijinal_saklandi(girisli, monkeypatch):
    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    belge_id = _yuklenen(c, jpeg_bayt(masada_egik_cekim()), otomatik_duzelt="0")
    kayit = database.belge_icerigi(k["id"], belge_id)
    assert kayit["koseler"] is None and kayit["orijinal_saklandi"]
    assert c.get(f"/gorsel/{belge_id}").data == crypto.coz(kayit["veri"])


def _eski_belge(kullanici_id, gorsel, **ek):
    veri = jpeg_bayt(gorsel)
    return database.belge_ekle(
        kullanici_id=kullanici_id, dosya_adi="eski.jpg", mime_type="image/jpeg",
        sifreli_icerik=crypto.sifrele(veri), sifreli_onizleme=crypto.sifrele(veri),
        ocr_metni="FATURA", tur="fatura", guven=0.9, aciklama="eski", **ek,
    ), veri


@pytest.mark.parametrize("surum", ["v3", "v4-duzeltilmis"])
def test_eski_belgeler_aynen_acilir_ve_indirilir(girisli, surum):
    """v4'te duzeltilip oyle saklanmis ya da hic duzeltilmemis belgeler, v5 kodu
    yuzunden yeniden kirpilmaz."""
    c, k = girisli
    ek = {"otomatik_duzeltildi": True} if surum == "v4-duzeltilmis" else {}
    belge_id, veri = _eski_belge(k["id"], sayfa(), **ek)
    assert c.get(f"/belge/{belge_id}").status_code == 200
    assert c.get(f"/gorsel/{belge_id}").data == veri
    assert c.get(f"/onizleme/{belge_id}").status_code == 200
    assert c.get(f"/belge/{belge_id}/indir").data == veri


def test_pdf_orijinal_saklandi_isaretlenmez(girisli, monkeypatch):
    import pymupdf

    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    belge = pymupdf.open()
    belge.new_page()
    belge_id = _yuklenen(c, belge.tobytes(), "belge.pdf")
    kayit = database.belge_icerigi(k["id"], belge_id)
    assert not kayit["orijinal_saklandi"] and kayit["koseler"] is None


def test_emin_olunmayan_kirpma_isleme_durumunda_isaretlenir(girisli, monkeypatch):
    c, _ = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    tasan = ((0.35, 0.10), (1.08, 0.12), (1.05, 0.92), (0.30, 0.90))
    baslik = {"Accept": "application/json"}
    supheli = yukle(c, jpeg_bayt(masada_egik_cekim(koseler=tasan)), "a.jpg", headers=baslik).get_json()["belge_id"]
    net = yukle(c, jpeg_bayt(masada_egik_cekim(koseler=DIK_15)), "b.jpg", headers=baslik).get_json()["belge_id"]
    assert isleme_durumu(c, supheli)["kirpma_kontrol"] is True
    assert isleme_durumu(c, net)["kirpma_kontrol"] is False
    # Detay sayfasi kose editorunu onerir; kirpma elle kaydedilince oneri kalkar.
    sayfa = c.get(f"/belge/{supheli}").get_data(as_text=True)
    assert "data-kirpma-kontrol" in sayfa and f"/belge/{supheli}?koseler=1" in sayfa
    assert "data-kirpma-kontrol" not in c.get(f"/belge/{net}").get_data(as_text=True)
    koseler = database.belge_icerigi(girisli[1]["id"], supheli)["koseler"]
    c.post(f"/belge/{supheli}/koseler", data={"koseler": json.dumps(koseler)})
    assert "data-kirpma-kontrol" not in c.get(f"/belge/{supheli}").get_data(as_text=True)
