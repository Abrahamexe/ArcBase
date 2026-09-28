"""Istek surelerini parcalara ayirarak olcer (hizlandirma calismasi icin).

Gecici bir kullanici ve belgeler olusturur; panel, kategori, belge detayi,
arama ve tek belge yuklemeyi Flask test istemcisiyle tekrar tekrar ister ve
her istegin suresini parcalara ayirir: veritabani baglantisi, sorgu (sayi ve
sure), sifre cozme, gorsel duzeltme, tarama filtresi, OCR, Groq, sablon.
Istenirse sayfalari gercek bir tarayicida (Playwright) da acip ilk cizim ve
yuklenme surelerini olcer. Sonunda kullanici ve belgeleri silinir.

Kullanim (proje kokunden):
    python docs/hiz_olcumu.py [--tekrar 7] [--sahte-groq] [--tarayici] [--json sonuc.json]
    python docs/hiz_olcumu.py --kok ESKI_KOD_DIZINI --json once.json   # onceki surum
    python docs/hiz_olcumu.py --karsilastir once.json sonra.json        # tablo

--kok: olculecek kod dizini (varsayilan: bu proje). .env her durumda bu
projeden okunur; anahtarlar yazdirilmaz. Gercek Groq cagrisi yapilir
(GROQ_API_KEY varsa); --sahte-groq ile Groq aninda cevap veren taklitle
degistirilir.
"""

import argparse
import functools
import io
import json
import os
import statistics
import sys
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

PROJE = Path(__file__).resolve().parent.parent

KATEGORILER = (
    "DB bağlantısı",
    "Sorgu",
    "Şifre çözme",
    "Şifreleme",
    "Görsel düzeltme",
    "Tarama filtresi",
    "OCR",
    "Groq",
    "Görsel kodlama",
    "Şablon",
)

# (modul, nitelik, kategori). Ic ice cagrilarda yalnizca en distaki sayilir;
# boylece ayni sure iki kategoriye yazilmaz. Olmayan nitelikler atlanir
# (eski ve yeni surum ayni betikle olculur).
SARMALAR = (
    ("psycopg2", "connect", "DB bağlantısı"),
    ("psycopg2.extras.RealDictCursor", "execute", "Sorgu"),
    ("crypto", "coz", "Şifre çözme"),
    ("crypto", "sifrele", "Şifreleme"),
    ("goruntu_duzelt", "analiz", "Görsel düzeltme"),
    ("goruntu_duzelt", "uygula", "Görsel düzeltme"),
    ("tarama", "tara", "Tarama filtresi"),
    ("tarama", "kenar_kirp", "Tarama filtresi"),
    ("ocr", "metin_cikar", "OCR"),
    ("ocr", "gorselden_metin", "OCR"),
    ("pytesseract", "image_to_string", "OCR"),
    ("classifier", "siniflandir", "Groq"),
    ("goruntu_duzelt", "goruntu_ac", "Görsel kodlama"),
    ("goruntu_duzelt", "jpeg", "Görsel kodlama"),
    ("tarama", "jpeg", "Görsel kodlama"),
    ("ocr", "gorsel_sikistir", "Görsel kodlama"),
    ("ocr", "onizleme_uret", "Görsel kodlama"),
    ("ocr", "goruntu_baytlari", "Görsel kodlama"),
    ("ocr", "gorsel_sikistir_bgr", "Görsel kodlama"),
    ("ocr", "onizleme_bgr", "Görsel kodlama"),
    # Flask'in _render'i baglam islemcilerini de calistirir (menu sayaclari
    # sorgusu); o sure "Sorgu"ya yazilsin diye yalnizca Jinja'nin cizimi sarilir.
    ("jinja2.environment.Template", "render", "Şablon"),
)

# Belge detayindaki (sentetik) fotografin metni; OCR dogrulugu icin de kullanilir.
SENTETIK_METIN = [
    "E-ARŞİV FATURA",
    "Örnek Elektrik Perakende Satış A.Ş.",
    "Vergi Dairesi: Kadıköy  Vergi No: 1234567890",
    "Fatura No: OEP2026000004512",
    "Fatura Tarihi: 14.03.2026   Son Ödeme Tarihi: 28.03.2026",
    "Tesisat No: 4001234567   Sözleşme Hesap No: 3009876543",
    "Dönem: 01.02.2026 - 28.02.2026",
    "Aktif enerji tüketimi 312 kWh x 2,4580 TL = 766,90 TL",
    "Dağıtım bedeli 312 kWh x 0,9870 TL = 307,94 TL",
    "Enerji fonu %1: 7,67 TL",
    "TRT payı %2: 15,34 TL",
    "Elektrik tüketim vergisi %5: 38,35 TL",
    "Ara toplam: 1.136,20 TL",
    "KDV %20: 227,24 TL",
    "Ödenecek tutar: 1.363,44 TL",
    "Faturanızı son ödeme tarihine kadar bankalar, PTT şubeleri",
    "veya internet şubesi üzerinden ödeyebilirsiniz.",
    "Gecikme durumunda yasal gecikme zammı uygulanır.",
    "Arıza ve şikayetleriniz için çağrı merkezimizi arayabilirsiniz.",
    "Bu belge elektronik ortamda oluşturulmuştur.",
]


# ---------------------------------------------------------------- olcer

class Olcer:
    """Ana is parcacigindaki sarili cagrilarin surelerini kategorilere yazar."""

    def __init__(self):
        self.ana = threading.get_ident()
        self.kova = None
        self.adet = None
        self.derinlik = 0

    def basla(self):
        self.kova, self.adet, self.derinlik = defaultdict(float), defaultdict(int), 0

    def bitir(self):
        kova, adet = dict(self.kova), dict(self.adet)
        self.kova = self.adet = None
        return kova, adet

    def sar(self, nesne, ad, kategori):
        asil = getattr(nesne, ad)
        if getattr(asil, "_olcum_sarmali", False):
            return

        @functools.wraps(asil)
        def sarmal(*a, **k):
            if self.kova is None or self.derinlik or threading.get_ident() != self.ana:
                return asil(*a, **k)
            self.derinlik += 1
            bas = time.perf_counter()
            try:
                return asil(*a, **k)
            finally:
                self.derinlik -= 1
                if self.kova is not None:
                    self.kova[kategori] += time.perf_counter() - bas
                    self.adet[kategori] += 1

        sarmal._olcum_sarmali = True
        setattr(nesne, ad, sarmal)


def _nesne(yol):
    import importlib

    parcalar = yol.split(".")
    for i in range(len(parcalar), 0, -1):
        try:
            nesne = importlib.import_module(".".join(parcalar[:i]))
        except ImportError:
            continue
        for parca in parcalar[i:]:
            nesne = getattr(nesne, parca)
        return nesne
    raise ImportError(yol)


# ---------------------------------------------------------------- ornek veriler

def sentetik_fotograf():
    """12 MP (3024x4032) telefon fotografi: yogun metinli A4 sayfa masada egik."""
    sys.path.insert(0, str(PROJE / "tests"))
    from ornek_gorseller import _yazi_tipi, jpeg_bayt, masada_egik_cekim
    from PIL import Image, ImageDraw
    import numpy as np

    sayfa = Image.new("RGB", (2480, 3508), "white")
    cizim = ImageDraw.Draw(sayfa)
    yazi = _yazi_tipi(46)  # 11 pt @ 300 DPI
    for i, satir in enumerate(SENTETIK_METIN):
        cizim.text((220, 260 + i * 120), satir, fill="black", font=yazi)
    koseler = ((0.12, 0.10), (0.88, 0.12), (0.90, 0.90), (0.08, 0.88))
    foto = masada_egik_cekim(tuval=(3024, 4032), koseler=koseler, kagit=np.asarray(sayfa))
    return jpeg_bayt(foto, 90)


def ornek_belgeler(kullanici_id, adet, foto):
    """Arayuz olcumu icin veritabanina dogrudan belge ekler (yukleme olcumunden bagimsiz)."""
    import alanlar
    import crypto
    import database
    import goruntu_duzelt
    import ocr

    tam = goruntu_duzelt.goruntu_ac(foto)
    koseler = goruntu_duzelt.analiz(tam)["koseler"]
    saklanan = ocr.gorsel_sikistir(foto)
    kucuk = goruntu_duzelt.goruntu_ac(saklanan)
    koseler = goruntu_duzelt.koseleri_olcekle(koseler, kucuk.shape[1] / tam.shape[1])
    onizleme = ocr.onizleme_uret(goruntu_duzelt.jpeg(goruntu_duzelt.uygula(kucuk, koseler)), "image/jpeg")
    sifreli, sifreli_onizleme = crypto.sifrele(saklanan), crypto.sifrele(onizleme)
    metin = "\n".join(SENTETIK_METIN)
    kimlikler = []
    for i in range(adet):
        tur = "fatura" if i % 3 else "dilekce"
        bilgi = {"kurum": "Örnek Elektrik", "tutar": 1363.44, "para_birimi": "TRY", "belge_tarihi": "2026-03-14"}
        kimlikler.append(database.belge_ekle(
            kullanici_id=kullanici_id, dosya_adi=f"belge_{i:02}.jpg", mime_type="image/jpeg",
            sifreli_icerik=sifreli, sifreli_onizleme=sifreli_onizleme, ocr_metni=metin, tur=tur,
            guven=0.93, aciklama="Ölçüm belgesi", alanlar=alanlar.dogrula(tur, bilgi)[0],
            otomatik_duzeltildi=True, koseler=koseler, orijinal_saklandi=True,
        ))
    return kimlikler


# ---------------------------------------------------------------- olcum

def _ozet(ornekler):
    """En yavas tekrar (Neon'un anlik gecikmesi vb.) atilir, kalanlarin ortalamasi."""
    ornekler = sorted(ornekler, key=lambda o: o["toplam"])
    if len(ornekler) > 2:
        ornekler = ornekler[:-1]
    n = len(ornekler)
    ozet = {"toplam": sum(o["toplam"] for o in ornekler) / n, "parcalar": {}, "adetler": {}}
    for kat in KATEGORILER:
        ozet["parcalar"][kat] = sum(o["kova"].get(kat, 0) for o in ornekler) / n
        ozet["adetler"][kat] = sum(o["adet"].get(kat, 0) for o in ornekler) / n
    ozet["parcalar"]["Diğer"] = max(ozet["toplam"] - sum(ozet["parcalar"].values()), 0)
    ozet["min"] = ornekler[0]["toplam"]
    ozet["maks"] = ornekler[-1]["toplam"]
    return ozet


def istek_olc(olcer, istemci, adres, tekrar, hazirla=None, yontem="GET", beklenen=(200,), **k):
    ornekler = []
    for i in range(tekrar + 1):  # ilk istek isinma, sayilmaz
        ek = hazirla(i) if hazirla else {}
        olcer.basla()
        bas = time.perf_counter()
        yanit = istemci.open(adres, method=yontem, **k, **ek)
        yanit.get_data()
        toplam = time.perf_counter() - bas
        kova, adet = olcer.bitir()
        assert yanit.status_code in beklenen, (adres, yanit.status_code, yanit.get_data(as_text=True)[:300])
        if i:
            ornekler.append({"toplam": toplam, "kova": kova, "adet": adet})
    return _ozet(ornekler), yanit


def yukleme_olc(olcer, istemci, veri, ad, tekrar):
    """Tek belge yukleme: kullanicinin bekledigi istek + (varsa) arka plan isi."""
    try:
        import isleme
    except ImportError:
        isleme = None
    istek, is_, uctan = [], [], []
    for _ in range(tekrar):
        olcer.basla()
        bas = time.perf_counter()
        yanit = istemci.post("/yukle", data={"belge": (io.BytesIO(veri), ad)},
                             content_type="multipart/form-data", headers={"Accept": "application/json"})
        sure = time.perf_counter() - bas
        kova, adet = olcer.bitir()
        assert yanit.status_code == 200, yanit.get_data(as_text=True)[:300]
        istek.append({"toplam": sure, "kova": kova, "adet": adet})
        is_sure = 0.0
        if isleme is not None:
            # Yalnizca bu olcumun yukledigi belge islenir (ayni veritabanindaki
            # baska belgelere dokunulmaz).
            belge_id = yanit.get_json()["belge_id"]
            olcer.basla()
            bas = time.perf_counter()
            while isleme.bir_is_isle(belge_id=belge_id, gecikmeyi_yoksay=True):
                pass
            is_sure = time.perf_counter() - bas
            kova, adet = olcer.bitir()
            is_.append({"toplam": is_sure, "kova": kova, "adet": adet})
        uctan.append(sure + is_sure)
    sonuc = {"istek": _ozet(istek)}
    if is_:
        sonuc["arka_plan"] = _ozet(is_)
    sonuc["uctan_uca"] = statistics.mean(sorted(uctan)[:-1] if len(uctan) > 2 else uctan)
    return sonuc


def sunucu_olc(tekrar, sahte_groq, gercek_foto):
    import app as uygulama_modulu
    import classifier
    import database
    import kimlik

    olcer = Olcer()
    for yol, ad, kat in SARMALAR:
        try:
            nesne = _nesne(yol)
        except (ImportError, AttributeError):
            continue
        if hasattr(nesne, ad):
            olcer.sar(nesne, ad, kat)

    if sahte_groq or not os.getenv("GROQ_API_KEY"):
        def sahte(metin, bilinen_tur=None):
            return {"tur": bilinen_tur or "fatura", "guven": 0.9, "aciklama": "sahte", "yogun": False,
                    "hata_turu": None, "alanlar": {}}
        classifier.siniflandir = sahte
        olcer.sar(classifier, "siniflandir", "Groq")

    app = uygulama_modulu.app
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    uygulama_modulu.limiter.enabled = False
    uygulama_modulu.KULLANICI_BELGE_LIMITI = 1000
    database.veritabanini_hazirla()

    ad = "olcum_" + uuid.uuid4().hex[:10]
    kullanici_id = database.kullanici_ekle(ad, kimlik.sifre_hashle("olcum_sifre_123"))
    sonuclar = {}
    try:
        foto = sentetik_fotograf()
        kimlikler = ornek_belgeler(kullanici_id, 30, foto)
        belge_id = kimlikler[-1]
        istemci = app.test_client()
        assert istemci.post("/giris", data={"kullanici_adi": ad, "sifre": "olcum_sifre_123"}).status_code == 302

        onbellek_temizle = getattr(uygulama_modulu, "gorsel_onbellegini_temizle", lambda: None)

        def soguk(_):
            onbellek_temizle()
            return {}

        sayfalar = [
            ("Panel (dashboard)", "/", None),
            ("Kategori (fatura, 12 kart)", "/kategori/fatura", None),
            ("Belge detayı (HTML)", f"/belge/{belge_id}", None),
            ("Belge görseli /tarama (ilk açılış)", f"/tarama/{belge_id}?mod=renkli", soguk),
            ("Önizleme (grid küçük resmi)", f"/onizleme/{belge_id}", soguk),
            ("Arama (?q=elektrik)", "/ara?q=elektrik", None),
        ]
        for etiket, adres, hazirla in sayfalar:
            sonuclar[etiket], yanit = istek_olc(olcer, istemci, adres, tekrar, hazirla)
            if "tarama" in adres or "onizleme" in adres:
                etag = yanit.headers.get("ETag")
                tekrar_etiket = etiket.split(" (")[0] + " (tekrar ziyaret)"
                if etag:
                    sonuclar[tekrar_etiket], _ = istek_olc(
                        olcer, istemci, adres, tekrar, beklenen=(304,), headers={"If-None-Match": etag})
                else:
                    sonuclar[tekrar_etiket], _ = istek_olc(olcer, istemci, adres, tekrar)

        yuklemeler = [("12 MP fotoğraf (sentetik)", foto, "fatura.jpg")]
        if gercek_foto and Path(gercek_foto).exists():
            yuklemeler.insert(0, ("Gerçek fotoğraf (tests/ozel/bu.png)", Path(gercek_foto).read_bytes(), "bu.png"))
        for etiket, veri, dosya_adi in yuklemeler:
            sonuclar["Yükleme: " + etiket] = yukleme_olc(olcer, istemci, veri, dosya_adi, max(3, tekrar // 2))
    finally:
        database.kullanici_sil(kullanici_id)
    return sonuclar


def tarayici_olc(tekrar):
    """Sayfalari Chromium'da acar: ilk cizim (FCP), DOMContentLoaded, load (ms)."""
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server

    import app as uygulama_modulu
    import database
    import kimlik

    app = uygulama_modulu.app
    app.config.update(WTF_CSRF_ENABLED=False)
    uygulama_modulu.limiter.enabled = False
    ad = "olcum_" + uuid.uuid4().hex[:10]
    kullanici_id = database.kullanici_ekle(ad, kimlik.sifre_hashle("olcum_sifre_123"))
    sunucu = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    taban = f"http://127.0.0.1:{sunucu.server_port}"
    sonuclar = {}
    try:
        kimlikler = ornek_belgeler(kullanici_id, 30, sentetik_fotograf())
        with sync_playwright() as p:
            tarayici = p.chromium.launch()
            s = tarayici.new_page()
            s.goto(taban + "/giris")
            s.fill("input[name=kullanici_adi]", ad)
            s.fill("input[name=sifre]", "olcum_sifre_123")
            s.click("button[type=submit]")
            s.wait_for_url(taban + "/")
            for etiket, adres in [("Panel", "/"), ("Kategori", "/kategori/fatura"),
                                  ("Belge detayı", f"/belge/{kimlikler[-1]}"), ("Arama", "/ara?q=elektrik")]:
                olcumler = []
                for i in range(tekrar + 1):
                    s.goto(taban + adres, wait_until="load")
                    s.wait_for_load_state("networkidle")
                    deger = s.evaluate("""() => {
                        const n = performance.getEntriesByType('navigation')[0];
                        const fcp = performance.getEntriesByName('first-contentful-paint')[0];
                        return {fcp: fcp ? fcp.startTime : null, dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd,
                                ttfb: n.responseStart};
                    }""")
                    if i:
                        olcumler.append(deger)
                sonuclar[etiket] = {k: statistics.median(o[k] for o in olcumler if o[k] is not None)
                                    for k in ("ttfb", "fcp", "dcl", "load")}
            tarayici.close()
    finally:
        sunucu.shutdown()
        database.kullanici_sil(kullanici_id)
    return sonuclar


# ---------------------------------------------------------------- rapor

def _ms(saniye):
    return f"{saniye * 1000:,.0f}".replace(",", ".")


def tablo_yaz(sonuclar):
    satirlar = []
    basliklar = ["İstek", "Toplam (ms)"] + list(KATEGORILER) + ["Diğer", "Sorgu adedi", "Bağlantı adedi"]
    satirlar.append("| " + " | ".join(basliklar) + " |")
    satirlar.append("|" + "---|" * len(basliklar))

    def satir(etiket, oz):
        parca = [_ms(oz["parcalar"][k]) if oz["parcalar"][k] >= 0.0005 else "·" for k in list(KATEGORILER) + ["Diğer"]]
        satirlar.append(f"| {etiket} | **{_ms(oz['toplam'])}** | " + " | ".join(parca)
                        + f" | {oz['adetler']['Sorgu']:.0f} | {oz['adetler']['DB bağlantısı']:.0f} |")

    for etiket, oz in sonuclar.get("sunucu", {}).items():
        if "istek" in oz:
            satir(etiket + " — istek", oz["istek"])
            if "arka_plan" in oz:
                satir(etiket + " — arka plan işi", oz["arka_plan"])
            satirlar.append(f"| {etiket} — belge hazır (uçtan uca) | **{_ms(oz['uctan_uca'])}** |"
                            + " |" * (len(basliklar) - 2))
        else:
            satir(etiket, oz)
    if sonuclar.get("tarayici"):
        satirlar += ["", "| Sayfa (Chromium) | TTFB | İlk çizim (FCP) | DOMContentLoaded | load |", "|---|---|---|---|---|"]
        for etiket, d in sonuclar["tarayici"].items():
            satirlar.append(f"| {etiket} | {d['ttfb']:.0f} | {d['fcp']:.0f} | {d['dcl']:.0f} | {d['load']:.0f} |")
    return "\n".join(satirlar)


def karsilastir(once_yolu, sonra_yolu):
    once = json.loads(Path(once_yolu).read_text(encoding="utf-8"))
    sonra = json.loads(Path(sonra_yolu).read_text(encoding="utf-8"))
    satirlar = ["| İstek | Önce (ms) | Sonra (ms) | Fark |", "|---|---|---|---|"]

    def ekle(etiket, a, b):
        if not a or not b:
            fark = ""
        elif b <= a:
            fark = f"{a / b:.1f}× hızlı (−%{(1 - b / a) * 100:.0f})".replace(".", ",")
        else:
            fark = f"{b / a:.1f}× yavaş (+%{(b / a - 1) * 100:.0f})".replace(".", ",")
        satirlar.append(f"| {etiket} | {_ms(a)} | {_ms(b)} | {fark} |")

    for etiket, oz in once.get("sunucu", {}).items():
        yeni = sonra.get("sunucu", {}).get(etiket)
        if yeni is None:
            continue
        if "istek" in oz:
            ekle(etiket + " — kullanıcının beklediği", oz["istek"]["toplam"], yeni["istek"]["toplam"])
            ekle(etiket + " — belge hazır (uçtan uca)", oz["uctan_uca"], yeni["uctan_uca"])
        else:
            ekle(etiket, oz["toplam"], yeni["toplam"])
    if once.get("tarayici") and sonra.get("tarayici"):
        satirlar += ["", "| Sayfa (Chromium, ms) | FCP önce | FCP sonra | load önce | load sonra |", "|---|---|---|---|---|"]
        for etiket, d in once["tarayici"].items():
            y = sonra["tarayici"].get(etiket)
            if y:
                satirlar.append(f"| {etiket} | {d['fcp']:.0f} | {y['fcp']:.0f} | {d['load']:.0f} | {y['load']:.0f} |")
    return "\n".join(satirlar)


def main():
    ayr = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ayr.add_argument("--kok", default=str(PROJE), help="olculecek kod dizini")
    ayr.add_argument("--tekrar", type=int, default=7)
    ayr.add_argument("--sahte-groq", action="store_true")
    ayr.add_argument("--tarayici", action="store_true", help="Playwright ile tarayici olcumu de yap")
    ayr.add_argument("--gercek-foto", default=str(PROJE / "tests" / "ozel" / "bu.png"))
    ayr.add_argument("--json", help="ham sonuclari bu dosyaya yaz")
    ayr.add_argument("--karsilastir", nargs=2, metavar=("ONCE", "SONRA"))
    arg = ayr.parse_args()

    if arg.karsilastir:
        print(karsilastir(*arg.karsilastir))
        return

    from dotenv import load_dotenv

    load_dotenv(PROJE / ".env")
    os.environ.setdefault("ARKA_PLAN_ISCISI", "0")  # yeni surumde isler olcum icin elle calistirilir
    kok = Path(arg.kok).resolve()
    sys.path.insert(0, str(kok))
    os.chdir(kok)

    sonuclar = {"sunucu": sunucu_olc(arg.tekrar, arg.sahte_groq, arg.gercek_foto)}
    if arg.tarayici:
        sonuclar["tarayici"] = tarayici_olc(max(3, arg.tekrar // 2))
    print(tablo_yaz(sonuclar))
    if arg.json:
        Path(arg.json).write_text(json.dumps(sonuclar, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
