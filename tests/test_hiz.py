"""Hizlandirma: baglanti havuzu, sayfa basina sorgu sayisi, gorsel onbellegi ve
tarayici onbellek basliklari (ETag, Cache-Control), tek seferlik ve kucultulmus
OCR, paralel PDF OCR, derlenmis Tailwind ve kisa sayfa gecis animasyonlari."""

import io
import re
import threading
from pathlib import Path

import pymupdf
import psycopg2
import psycopg2.extras
import pytesseract
import pytest
from PIL import Image

import app as uygulama_modulu
import crypto
import database
import isleme
import ocr
from conftest import belge_ekle, isleme_durumu, yukle
from ornek_gorseller import jpeg_bayt, masada_egik_cekim, sayfa

DIK_15 = ((0.28, 0.10), (0.72, 0.04), (0.78, 0.92), (0.30, 0.97))  # ~15 derece yamuk cekim (test_duzelt ile ayni)

KOK = Path(__file__).resolve().parent.parent


@pytest.fixture
def sayac(monkeypatch):
    """Veritabani sorgu ve yeni baglanti sayaci."""
    adet = {"sorgu": 0, "baglanti": 0}
    execute, connect = psycopg2.extras.RealDictCursor.execute, psycopg2.connect

    def say_sorgu(self, *a, **k):
        adet["sorgu"] += 1
        return execute(self, *a, **k)

    def say_baglanti(*a, **k):
        adet["baglanti"] += 1
        return connect(*a, **k)

    monkeypatch.setattr(psycopg2.extras.RealDictCursor, "execute", say_sorgu)
    monkeypatch.setattr(psycopg2, "connect", say_baglanti)

    def sifirla():
        adet.update(sorgu=0, baglanti=0)
        return adet

    return sifirla


def _kose_belgesi(kullanici_id):
    """Koseleri olan (v5) gorsel belge; tarama goruntusu aninda uretilir."""
    import goruntu_duzelt

    foto = jpeg_bayt(masada_egik_cekim(koseler=DIK_15))
    tam = goruntu_duzelt.goruntu_ac(foto)
    saklanan, (genislik, _) = ocr.gorsel_sikistir_bgr(tam)
    koseler = goruntu_duzelt.koseleri_olcekle(goruntu_duzelt.analiz(tam)["koseler"], genislik / tam.shape[1])
    return database.belge_ekle(
        kullanici_id=kullanici_id, dosya_adi="kose.jpg", mime_type="image/jpeg",
        sifreli_icerik=crypto.sifrele(saklanan), sifreli_onizleme=crypto.sifrele(ocr.onizleme_bgr(tam)),
        ocr_metni="FATURA", tur="fatura", guven=0.9, aciklama="", koseler=koseler, orijinal_saklandi=True,
    )


# ---------------------------------------------------------------- veritabani

@pytest.mark.parametrize("adres", ["/", "/kategori/fatura", "/ara?q=fatura", "/hesap", "BELGE"])
def test_sayfa_basina_iki_sorgu_yeni_baglanti_yok(girisli, sayac, adres):
    """Kullanici + menu sayaclari tek sorgu, sayfanin verisi tek sorgu; baglanti havuzdan."""
    c, k = girisli
    belge_id = belge_ekle(k["id"], ocr_metni="FATURA")
    adres = f"/belge/{belge_id}" if adres == "BELGE" else adres
    assert c.get(adres).status_code == 200  # isinma: havuzda baglanti olsun
    adet = sayac()
    assert c.get(adres).status_code == 200
    beklenen = 1 if adres == "/hesap" else 2  # hesap sayfasinin tum sayilari kullanici sorgusunda
    assert adet["sorgu"] == beklenen and adet["baglanti"] == 0


def test_havuzdaki_kopmus_baglanti_yenisiyle_degistirilir(girisli):
    _, k = girisli
    baglanti, _ = database._havuz.al()
    pid = baglanti.get_backend_pid()
    database._havuz.birak(baglanti)
    olduren = database.baglanti_ac()  # Neon'un uykuya gecip baglantiyi kesmesi gibi
    try:
        with olduren, olduren.cursor() as imlec:
            imlec.execute("SELECT pg_terminate_backend(%s)", (pid,))
    finally:
        olduren.close()
    assert database.kullanici_getir(k["id"])["id"] == k["id"]


def test_menu_sayaclari_ve_bu_hafta_kullanici_sorgusundan(girisli):
    c, k = girisli
    for _ in range(3):
        belge_ekle(k["id"], tur="fatura")
    belge_ekle(k["id"], tur="dilekce")
    panel = c.get("/").get_data(as_text=True)
    assert 'data-tur-sayaci="fatura">3<' in panel and 'data-tur-sayaci="dilekce">1<' in panel
    assert 'data-sayac="4"' in panel  # toplam ve bu hafta yuklenen
    assert panel.count('data-sayac="4"') == 2
    assert "kategori-son-tarihleri" not in panel  # tarayici kategori sayfalarini cekmez


# ---------------------------------------------------------------- gorsel onbellegi

def test_gorsel_etag_304_ve_bellek_onbellegi(girisli, monkeypatch):
    c, k = girisli
    belge_id = _kose_belgesi(k["id"])
    uygulama_modulu.gorsel_onbellegini_temizle()
    cozulen = []
    asil = crypto.coz
    monkeypatch.setattr(crypto, "coz", lambda v: cozulen.append(1) or asil(v))

    ilk = c.get(f"/tarama/{belge_id}?mod=renkli")
    assert ilk.status_code == 200 and ilk.mimetype == "image/jpeg" and ilk.headers["ETag"]
    assert ilk.headers["Cache-Control"] == "private, no-cache"
    assert len(cozulen) == 1

    tekrar = c.get(f"/tarama/{belge_id}?mod=renkli", headers={"If-None-Match": ilk.headers["ETag"]})
    assert tekrar.status_code == 304 and not tekrar.data and tekrar.headers["ETag"] == ilk.headers["ETag"]
    baska_tarayici = c.get(f"/tarama/{belge_id}?mod=renkli")  # tarayici onbellegi yok, surec onbellegi var
    assert baska_tarayici.status_code == 200 and baska_tarayici.data == ilk.data
    assert len(cozulen) == 1  # ikisinde de sifre cozulmedi, filtre calismadi

    gri = c.get(f"/tarama/{belge_id}?mod=gri", headers={"If-None-Match": ilk.headers["ETag"]})
    assert gri.status_code == 200 and gri.headers["ETag"] != ilk.headers["ETag"]  # mod degisince


def test_kose_degisince_onbellek_gecersizlesir(girisli, monkeypatch):
    import json

    c, k = girisli
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA")
    belge_id = _kose_belgesi(k["id"])
    ilk = c.get(f"/tarama/{belge_id}?mod=renkli")
    onizleme = c.get(f"/onizleme/{belge_id}")
    koseler = database.belge_icerigi(k["id"], belge_id)["koseler"]
    koseler[0] = [koseler[0][0] + 40, koseler[0][1] + 40]
    assert c.post(f"/belge/{belge_id}/koseler", data={"koseler": json.dumps(koseler)}).status_code == 302

    sonra = c.get(f"/tarama/{belge_id}?mod=renkli", headers={"If-None-Match": ilk.headers["ETag"]})
    assert sonra.status_code == 200 and sonra.headers["ETag"] != ilk.headers["ETag"] and sonra.data != ilk.data
    yeni_onizleme = c.get(f"/onizleme/{belge_id}", headers={"If-None-Match": onizleme.headers["ETag"]})
    assert yeni_onizleme.status_code == 200 and yeni_onizleme.data != onizleme.data


def test_surumlu_adres_uzun_sure_onbellekte_kalir(girisli):
    c, k = girisli
    belge_id = belge_ekle(k["id"])
    surum = database.belge_getir(k["id"], belge_id)["icerik_surumu"]
    kalici = c.get(f"/onizleme/{belge_id}?v={surum}")
    assert kalici.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    eski = c.get(f"/onizleme/{belge_id}?v={surum + 5}")
    assert eski.headers["Cache-Control"] == "private, no-cache"


def test_gorsel_onbellegi_baskasinin_belgesini_vermez(girisli, kullanici, uygulama):
    from conftest import giris_yap

    c, k = girisli
    belge_id = _kose_belgesi(k["id"])
    ilk = c.get(f"/tarama/{belge_id}?mod=renkli")
    assert ilk.status_code == 200  # artik surec onbelleginde
    baska = uygulama.test_client()
    giris_yap(baska, kullanici()["ad"])
    assert baska.get(f"/tarama/{belge_id}?mod=renkli").status_code == 404
    assert baska.get(f"/tarama/{belge_id}?mod=renkli", headers={"If-None-Match": ilk.headers["ETag"]}).status_code == 404
    assert baska.get(f"/onizleme/{belge_id}").status_code == 404


def test_gridlerde_surumlu_lazy_onizleme(girisli):
    c, k = girisli
    for _ in range(3):
        belge_ekle(k["id"])
    for adres in ("/", "/kategori/fatura"):
        html = c.get(adres).get_data(as_text=True)
        kartlar = re.findall(r'<img src="(/[^"]+)"[^>]*loading="lazy"', html)
        assert len(kartlar) == 3 and all(re.fullmatch(r"/onizleme/\d+\?v=\d+", a) for a in kartlar)
        assert "/tarama/" not in html and "/gorsel/" not in html


def test_cikista_tarayici_onbellegi_temizlenir(girisli):
    c, _ = girisli
    assert c.post("/cikis").headers["Clear-Site-Data"] == '"cache"'


# ---------------------------------------------------------------- OCR

def test_yuklemede_tek_ocr_ve_kucultulmus_girdi(girisli, monkeypatch):
    c, _ = girisli
    boyutlar = []

    def sahte(goruntu, **k):
        boyutlar.append(goruntu.size)
        assert "tessedit_do_invert=0" in k["config"]
        return "FATURA"

    monkeypatch.setattr(pytesseract, "image_to_string", sahte)
    foto = masada_egik_cekim(tuval=(4032, 3024), koseler=((0.25, 0.02), (0.75, 0.02), (0.78, 0.98), (0.22, 0.98)))
    belge_id = yukle(c, jpeg_bayt(foto), "buyuk.jpg", headers={"Accept": "application/json"}).get_json()["belge_id"]
    assert isleme_durumu(c, belge_id)["tur"] == "fatura"
    assert len(boyutlar) == 1  # ayni goruntu bir kez okunur
    assert max(boyutlar[0]) <= isleme.OCR_UZUN_KENAR


def test_pdf_metin_katmani_okunur_taranmis_sayfalar_paralel(monkeypatch):
    is_parcaciklari = []

    def sahte(goruntu, **k):
        is_parcaciklari.append(threading.get_ident())
        return "taranmis sayfa"

    monkeypatch.setattr(pytesseract, "image_to_string", sahte)
    belge = pymupdf.open()
    belge.new_page().insert_text((72, 100), "E-FATURA Fatura No: ABC2026000000777 Genel Toplam", fontsize=14)
    for _ in range(2):  # metin katmani olmayan (taranmis) sayfalar
        tampon = io.BytesIO()
        Image.fromarray(sayfa()).save(tampon, "JPEG")
        belge.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=tampon.getvalue())
    metin = ocr.metin_cikar(belge.tobytes(), "application/pdf")
    assert "ABC2026000000777" in metin and metin.count("taranmis sayfa") == 2
    assert len(is_parcaciklari) == 2 and threading.get_ident() not in is_parcaciklari


def test_pdf_onizleme_dusuk_cozunurlukte_uretilir():
    belge = pymupdf.open()
    belge.new_page().insert_text((72, 100), "Merhaba", fontsize=20)
    onizleme = Image.open(io.BytesIO(ocr.onizleme_uret(belge.tobytes(), "application/pdf")))
    assert max(onizleme.size) == 600


# ---------------------------------------------------------------- statik dosyalar ve animasyonlar

def test_derlenmis_tailwind_ve_uzun_statik_onbellek(girisli):
    c, _ = girisli
    html = c.get("/").get_data(as_text=True)
    assert "cdn.tailwindcss.com" not in html and "tailwind.config" not in html
    adres = re.search(r'href="(/static/tailwind\.css\?v=\d+)"', html).group(1)
    css = c.get(adres)
    assert css.status_code == 200 and b".bg-marka-600" in css.data
    assert css.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    css.close()
    assert re.search(r'src="/static/app\.js\?v=\d+"', html)


def test_arayuz_animasyonlari_300_800ms():
    """Tasarim kurali: ana animasyon ve gecisler 300-800 ms (gecikmeler dahil her deger en
    fazla 800 ms); yumusak cikis egrisi; kartlar ve bolumler sirayla gelir. Mikro gecisler
    (hover rengi, acilir panel) 300 ms'nin altinda kalabilir. Surekli ve cok yavas hareketler
    (belge yigini, radar, tarama isigi) ve donen gostergeler (iskelet, nabiz) haric tutulur;
    onlar ambiyanstir ve prefers-reduced-motion'da kapatilir."""
    css = (KOK / "static" / "style.css").read_text(encoding="utf-8") + "\n" + (KOK / "static" / "etkiler.css").read_text(encoding="utf-8")

    def sureler(secici):
        kural = css[css.index(secici):]
        kural = kural[:kural.index("}")]
        return [float(s) * (1000 if b == "s" else 1) for s, b in re.findall(r"(\d+(?:\.\d+)?)(ms|s)\b", kural)]

    # Her deger en fazla 800 ms.
    for secici in ("::view-transition-old(icerik)", ".sayfa-icerik { animation", ".kart-giris {", ".guven-dolgu", ".kota-dolgu",
                   ".bildirim {", "dialog.pencere[open] > *", ".kullanici-menusu {\n", ".nav-gosterge {", ".acilir-panel {",
                   ".mobil-menu {", ".bolum-giris {", ".kadran-deger {\n", ".kadran-ibre {", ".cubuk-iz i {\n", ".yay-deger { stroke",
                   ".ocr-kutu.ocr-oynat .ocr-satir", ".tarama-netles", "::view-transition-group(belge-gorsel)", ".karo-vurgu",
                   "html.tema-gecisi::view-transition-new(root) {\n  animation: tema-sil"):
        assert sureler(secici) and max(sureler(secici)) <= 800, secici
    # Ana animasyonlar 300 ms'den kisa olmaz.
    for secici in (".sayfa-icerik { animation", ".kart-giris {", ".nav-gosterge {", ".bolum-giris {", ".kadran-deger {\n",
                   ".cubuk-iz i {\n", ".yay-deger { stroke", ".ocr-kutu.ocr-oynat .ocr-satir", "::view-transition-group(belge-gorsel)",
                   "html.tema-gecisi::view-transition-new(root) {\n  animation: tema-sil"):
        assert max(sureler(secici)) >= 300, secici
    kart = css[css.index(".kart-giris {"):]
    assert "animation: icerik-gir" in kart[:kart.index("}")] and "var(--i" in kart[:kart.index("}")]
    bolum = css[css.index(".bolum-giris {"):]
    assert "animation: bolum-gir" in bolum[:bolum.index("}")] and "var(--i" in bolum[:bolum.index("}")]
    assert "--yumusak: cubic-bezier(0.23, 1, 0.32, 1)" in css
    # Surekli hareketler (yigin, radar) ve panel girisleri hareket azaltmada durur.
    azalt = css[css.rindex("prefers-reduced-motion: reduce"):]
    assert ".yaprak" in azalt and ".radar-isin" in azalt and ".kadran-deger" in azalt and ".cubuk-iz i" in azalt


def test_etkiler_yalnizca_gorunum_ve_dis_adres_yok():
    """Gorsel etkiler yalnizca gorunumdur: dis adres yuklemez (yerel mod) ve anahtar kareler
    yerlesimi degistiren ozellikleri (width/height/top/left/margin) animasyonla oynatmaz."""
    css = (KOK / "static" / "etkiler.css").read_text(encoding="utf-8")
    js = (KOK / "static" / "etkiler.js").read_text(encoding="utf-8")
    for metin in (css, js):
        assert "https://" not in metin and "http://" not in metin.replace("http://www.w3.org/2000/svg", "")

    def govde(ad):
        bas = css.index("@keyframes " + ad)
        i = css.index("{", bas)
        derinlik = 0
        for j in range(i, len(css)):
            derinlik += css[j] == "{"
            derinlik -= css[j] == "}"
            if derinlik == 0:
                return css[i:j + 1]

    for ad in ("bolum-gir", "kadran-ciz", "ibre-don", "yaprak-suzul", "yay-ciz", "radar-don", "tarama-gecis", "netles",
               "rozet-otur", "ocr-belir", "cubuk-buyu"):
        assert not re.search(r"(?<![-\w])(width|height|top|left|margin)\s*:", govde(ad)), ad
