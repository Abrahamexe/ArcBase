"""Test ortak parcalari.

Testler yalnizca .env'deki TEST_DATABASE_URL'i kullanir; DATABASE_URL'e (canli
veritabani) hicbir kosulda baglanmaz (db_korumasi.py). TEST_DATABASE_URL
tanimli degilse veritabani gerektiren testler uyariyla atlanir; canli
veritabaniyla ayniysa test oturumu hatayla durur.
Her test benzersiz adli gecici kullanicilar olusturur ve sonunda siler;
belgeleri ON DELETE CASCADE ile birlikte silinir. Groq cagrilari varsayilan
olarak taklit edilir (kota harcanmaz, sonuc tekrarlanabilir olur).

Arka plan iscisi testlerde kendiliginden baslamaz (ARKA_PLAN_ISCISI=0);
yukle() yardimcisi yuklenen belgenin isini ayni is parcaciginda hemen calistirir.
Is her zaman belge id'siyle alinir: ayni veritabanindaki baska belgelere dokunulmaz.
"""

import io
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from db_korumasi import CanliVeritabaniHatasi, veritabanini_ayarla  # noqa: E402

load_dotenv()
os.environ["ARKA_PLAN_ISCISI"] = "0"
# Uygulama modullerinden ONCE: DATABASE_URL test adresi olur ya da bos kalir.
try:
    TEST_VERITABANI = veritabanini_ayarla()
    VERITABANI_HATASI = None
except CanliVeritabaniHatasi as hata:
    TEST_VERITABANI, VERITABANI_HATASI = None, str(hata)

VERITABANI_YOK = (
    "TEST_DATABASE_URL tanımlı değil: veritabanı gerektiren testler atlandı "
    "(.env'e ayrı bir test veritabanı adresi ekleyin; DATABASE_URL testlerde kullanılmaz)."
)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import alanlar  # noqa: E402
import app as uygulama_modulu  # noqa: E402
import classifier  # noqa: E402
import crypto  # noqa: E402
import database  # noqa: E402
import isleme  # noqa: E402
import kimlik  # noqa: E402

SIFRE = "test_sifre_123"
# sahte_groq fixture'i bunu degistirir; gercek davranisi deneyen testler icin saklanir.
GERCEK_SINIFLANDIR = classifier.siniflandir


def tesseract_var():
    import pytesseract

    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return bool(shutil.which("tesseract"))


ocr_gerekli = pytest.mark.skipif(not tesseract_var(), reason="Tesseract kurulu değil")


def pytest_configure(config):
    if VERITABANI_HATASI:
        raise pytest.UsageError(VERITABANI_HATASI)


def pytest_report_header(config):
    return None if TEST_VERITABANI else "UYARI: " + VERITABANI_YOK


def pytest_terminal_summary(terminalreporter):
    if not TEST_VERITABANI:
        terminalreporter.write_line("UYARI: " + VERITABANI_YOK, yellow=True, bold=True)


@pytest.fixture(scope="session")
def veritabani():
    """Veritabani gerektiren her sey buna baglidir: TEST_DATABASE_URL yoksa atlanir."""
    if not TEST_VERITABANI:
        pytest.skip(VERITABANI_YOK)
    database.veritabanini_hazirla()


@pytest.fixture(scope="session")
def uygulama(veritabani):
    app = uygulama_modulu.app
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app


@pytest.fixture(autouse=True)
def _temiz_durum(monkeypatch, tmp_path_factory):
    """Her testte hiz siniri kapali ve sifirlanmis, CSRF kapali baslar; eklenen
    izlenen klasorler gecici bir dosyaya yazilir (izlenen_klasorler.py).
    Veritabanina baglanmaz: saf goruntu testleri veritabanisiz da calisir."""
    monkeypatch.setenv("IZLENEN_KLASORLER_DOSYASI", str(tmp_path_factory.mktemp("ayar") / "izlenen_klasorler.json"))
    limiter = uygulama_modulu.limiter
    limiter.reset()
    limiter.enabled = False
    uygulama_modulu.app.config["WTF_CSRF_ENABLED"] = False
    yield
    limiter.enabled = True
    limiter.reset()


@pytest.fixture
def istemci(uygulama):
    return uygulama.test_client()


@pytest.fixture
def yeni_ad(veritabani):
    """Benzersiz, kurallara uygun bir kullanici adi uretir ve test sonunda
    bu adla olusturulan kullaniciyi (varsa) siler."""
    adlar = []

    def uret():
        ad = "t_" + uuid.uuid4().hex[:12]
        adlar.append(ad)
        return ad

    yield uret
    for ad in adlar:
        satir = database.kullanici_adi_ile_getir(ad)
        if satir:
            database.kullanici_sil(satir["id"])


@pytest.fixture
def kullanici(yeni_ad):
    """Veritabanina dogrudan eklenen kullanici fabrikasi: {'id', 'ad'} dondurur."""

    def olustur():
        ad = yeni_ad()
        kullanici_id = database.kullanici_ekle(ad, kimlik.sifre_hashle(SIFRE))
        return {"id": kullanici_id, "ad": ad}

    return olustur


def giris_yap(istemci, ad, sifre=SIFRE, **ek):
    return istemci.post("/giris", data={"kullanici_adi": ad, "sifre": sifre, **ek})


@pytest.fixture
def girisli(uygulama, kullanici):
    """Giris yapmis bir istemci ve kullanicisi."""
    k = kullanici()
    c = uygulama.test_client()
    assert giris_yap(c, k["ad"]).status_code == 302
    return c, k


def jpeg(boyut=(64, 48), renk="white"):
    tampon = io.BytesIO()
    Image.new("RGB", boyut, renk).save(tampon, "JPEG")
    return tampon.getvalue()


def belge_ekle(kullanici_id, dosya_adi="deneme.jpg", tur="fatura", ocr_metni="", guven=0.9, **bilgi):
    """OCR/Groq'u atlayip belgeyi dogrudan veritabanina ekler.

    bilgi verilirse (kurum=..., tutar=...) alanlar dogrulanip kaydedilir;
    verilmezse v3'teki gibi bilgi alanlari NULL kalir."""
    veri = jpeg()
    ek = {"alanlar": alanlar.dogrula(tur, bilgi)[0]} if bilgi else {}
    return database.belge_ekle(
        kullanici_id=kullanici_id,
        dosya_adi=dosya_adi,
        mime_type="image/jpeg",
        sifreli_icerik=crypto.sifrele(veri),
        sifreli_onizleme=crypto.sifrele(veri),
        ocr_metni=ocr_metni,
        tur=tur,
        guven=guven,
        aciklama="test",
        **ek,
    )


def yazili_gorsel(boyut=(1600, 1200), satirlar=None):
    """OCR'in okuyabilecegi, uzerinde metin olan beyaz bir gorsel."""
    satirlar = satirlar or [
        "FATURA",
        "Fatura No: 2026-000123",
        "Genel Toplam: 720,00 TL",
        "Vergi Dairesi: Kadikoy",
    ]
    g = Image.new("RGB", boyut, "white")
    d = ImageDraw.Draw(g)
    try:
        yazi = ImageFont.truetype("arial.ttf", max(24, boyut[0] // 25))
    except OSError:
        try:
            yazi = ImageFont.truetype("DejaVuSans.ttf", max(24, boyut[0] // 25))
        except OSError:
            yazi = ImageFont.load_default()
    adim = boyut[1] // (len(satirlar) + 2)
    for i, satir in enumerate(satirlar):
        d.text((boyut[0] // 12, adim * (i + 1)), satir, fill="black", font=yazi)
    return g


def bayt(gorsel, bicim="PNG", **ayar):
    tampon = io.BytesIO()
    gorsel.save(tampon, bicim, **ayar)
    return tampon.getvalue()


def yuklenen_belge_id(yanit):
    """/yukle cevabindan (JSON ya da belge sayfasina yonlendirme) belge id'si."""
    if yanit.is_json:
        return (yanit.get_json() or {}).get("belge_id")
    eslesme = re.search(r"/belge/(\d+)$", yanit.headers.get("Location", ""))
    return int(eslesme.group(1)) if eslesme else None


def yukle(istemci, veri, ad, data_ek=None, isle=True, **ek):
    """data_ek: dosyayla birlikte gonderilecek diger form alanlari.

    isle=True: yukleme istegi dondukten sonra belgenin arka plan isi (duzeltme,
    OCR, siniflandirma; Groq denemeleri beklemeden) hemen calistirilir; boylece
    test sonucu dogrudan denetleyebilir. follow_redirects bundan sonra izlenir."""
    takip = ek.pop("follow_redirects", False)
    yanit = istemci.post(
        "/yukle",
        data={"belge": (io.BytesIO(veri), ad), **(data_ek or {})},
        content_type="multipart/form-data",
        **ek,
    )
    belge_id = yuklenen_belge_id(yanit)
    if isle and belge_id:
        isleme.bekleyenleri_isle(belge_id=belge_id)
    if takip and yanit.status_code in (301, 302, 303):
        yanit = istemci.get(yanit.headers["Location"])
    return yanit


def isleme_durumu(istemci, belge_id):
    """Tarayicinin yokladigi /isleme-durumu cevabindaki bu belgenin durumu."""
    return istemci.get(f"/isleme-durumu?id={belge_id}").get_json()["belgeler"][str(belge_id)]


def gorsel_boyutu(veri):
    """OCR'a verilen girdinin (bayt ya da numpy dizisi) (genislik, yukseklik) degeri."""
    if hasattr(veri, "shape"):
        return veri.shape[1], veri.shape[0]
    return Image.open(io.BytesIO(veri)).size


@pytest.fixture(autouse=True)
def sahte_groq(monkeypatch):
    """Groq yerine sabit bir sonuc dondurur. Gercek API'yi denemek icin
    GERCEK_GROQ=1 ortam degiskeniyle calistirin."""
    if os.getenv("GERCEK_GROQ") == "1":
        return

    def sahte(metin, bilinen_tur=None):
        tur = bilinen_tur or ("fatura" if "FATURA" in (metin or "").upper() else "diger")
        ham = SAHTE_FATURA_ALANLARI if tur == "fatura" else {}
        return {
            "tur": tur,
            "guven": 0.95,
            "aciklama": "Test sınıflandırması",
            "yogun": False,
            "alanlar": alanlar.dogrula(tur, ham)[0],
        }

    monkeypatch.setattr(classifier, "siniflandir", sahte)


SAHTE_FATURA_ALANLARI = {
    "kurum": "Test Elektrik A.Ş.",
    "tutar": 720.0,
    "para_birimi": "TRY",
    "belge_tarihi": "2026-01-15",
    "fatura_no": "2026-000123",
}
