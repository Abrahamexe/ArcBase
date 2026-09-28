"""v4 bilgi cikarma: Groq cevabinin dogrulanmasi, kimlik gizliligi, elle
duzenleme, filtreler/siralama, fatura ozeti ve yeni alanlarda arama."""

import json
import re
from datetime import date
from decimal import Decimal

import pytest

import alanlar
import classifier
import database
import ocr
from conftest import GERCEK_SINIFLANDIR, belge_ekle, jpeg, yukle


class SahteGroq:
    """Groq istemcisi yerine verilen sozlugu JSON olarak donduren sahte istemci."""

    def __init__(self, cevap):
        self.cevap = cevap
        self.istekler = []
        self.chat = self.completions = self

    def create(self, **istek):
        self.istekler.append(istek)
        mesaj = type("Mesaj", (), {"content": json.dumps(self.cevap)})
        return type("Yanit", (), {"choices": [type("Secim", (), {"message": mesaj})]})


@pytest.fixture
def groq_cevabi(monkeypatch):
    """Gercek classifier.siniflandir + sabit cevapli sahte Groq istemcisi."""
    monkeypatch.setattr(classifier, "siniflandir", GERCEK_SINIFLANDIR)

    def ayarla(cevap):
        istemci = SahteGroq(cevap)
        monkeypatch.setattr(classifier, "_istemci_olustur", lambda: istemci)
        return istemci

    return ayarla


# ---------------------------------------------------------------- Groq cevabi

def test_fatura_bilgileri_dogrulanir(groq_cevabi):
    istemci = groq_cevabi({
        "tur": "fatura", "guven": 0.97, "aciklama": "Elektrik faturası",
        "alanlar": {
            "kurum": "  Enerjisa   Başkent ", "tutar": "1.234,56", "para_birimi": "TL",
            "belge_tarihi": "2026-02-28", "fatura_no": "EBK2026000001", "iban": "TR00",
        },
    })
    sonuc = classifier.siniflandir("FATURA metni")
    assert sonuc["tur"] == "fatura"
    assert sonuc["alanlar"] == {
        "kurum": "Enerjisa Başkent", "tutar": Decimal("1234.56"), "para_birimi": "TRY",
        "belge_tarihi": date(2026, 2, 28), "fatura_no": "EBK2026000001",
    }
    # Tek istek: siniflandirma ve bilgi cikarma ayni cagrida
    assert len(istemci.istekler) == 1
    prompt = istemci.istekler[0]["messages"][0]["content"]
    assert "YYYY-MM-DD" in prompt and "null" in prompt and "TC kimlik" in prompt


def test_dilekce_bilgileri(groq_cevabi):
    groq_cevabi({
        "tur": "dilekce", "guven": 0.9, "aciklama": "Belediyeye dilekçe",
        "alanlar": {"kurum": "Kadıköy Belediyesi", "konu": "Sokak lambası arızası",
                    "belge_tarihi": "02.04.2026", "tutar": 50},
    })
    sonuc = classifier.siniflandir("dilekce metni")
    assert sonuc["alanlar"] == {
        "kurum": "Kadıköy Belediyesi", "konu": "Sokak lambası arızası",
        "belge_tarihi": date(2026, 4, 2),
    }


def test_kimlikte_tc_dogum_tarihi_ve_seri_no_saklanmaz(groq_cevabi, girisli, monkeypatch):
    tc, seri = "12345678950", "A12Z34567"
    groq_cevabi({
        "tur": "kimlik", "guven": 0.99,
        "aciklama": f"T.C. {tc} numaralı kimlik kartı",
        "alanlar": {
            "belge_turu": "Kimlik kartı", "gecerlilik_tarihi": "2031-08-20",
            "tc_kimlik_no": tc, "dogum_tarihi": "1990-05-12", "seri_no": seri,
            "konu": f"Seri {seri}",
        },
    })
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "KIMLIK KARTI metni")
    c, k = girisli
    yukle(c, jpeg(), "kimlik.jpg")
    kayit = database.belgeleri_suz(k["id"])[0]
    detay = database.belge_getir(k["id"], kayit["id"])
    assert detay["tur"] == "kimlik"
    assert detay["alanlar"] == {"belge_turu": "Kimlik kartı", "gecerlilik_tarihi": "2031-08-20"}
    kaydedilen = json.dumps(detay["alanlar"]) + (detay["aciklama"] or "") + str(detay["kurum"])
    for yasak in (tc, seri, "1990"):
        assert yasak not in kaydedilen
    sayfa = c.get(f"/belge/{kayit['id']}").get_data(as_text=True)
    assert "20.08.2031" in sayfa and "Gizlilik gereği" in sayfa


def test_kimlik_metin_alaninda_numara_reddedilir():
    temiz, hatalar = alanlar.dogrula("kimlik", {"belge_turu": "Ehliyet 12345678950"})
    assert temiz["belge_turu"] is None and hatalar == ["Belge türü"]


def test_gecersiz_degerler_null_olur(groq_cevabi):
    groq_cevabi({"tur": "fatura", "guven": 1, "alanlar": {
        "tutar": "bilinmiyor", "belge_tarihi": "2026-02-30", "para_birimi": "lira mı?",
        "kurum": "null", "fatura_no": None,
    }})
    assert set(classifier.siniflandir("x")["alanlar"].values()) == {None}


def test_groq_hatasinda_alanlar_cikarilmamis_sayilir(groq_cevabi):
    groq_cevabi("json nesnesi değil")
    sonuc = classifier.siniflandir("x")
    assert sonuc["alanlar"] is None and sonuc["tur"] == "diger"


def test_bilinen_tur_ile_sadece_alanlar_cikarilir(groq_cevabi):
    istemci = groq_cevabi({"tur": "fatura", "alanlar": {"konu": "Tapu", "tutar": 5}})
    sonuc = classifier.siniflandir("x", bilinen_tur="resmi_yazi")
    assert sonuc["tur"] == "resmi_yazi" and sonuc["alanlar"]["konu"] == "Tapu"
    assert "'resmi_yazi'" in istemci.istekler[0]["messages"][0]["content"]


def test_alan_tanimlari_prompt_ile_uyumlu():
    assert set(classifier.ALAN_ACIKLAMALARI) == set(alanlar.ALANLAR) == set(database.TURLER)
    for tur, tanimlar in alanlar.ALANLAR.items():
        for anahtar, _, _ in tanimlar:
            assert anahtar in classifier.ALAN_ACIKLAMALARI[tur], (tur, anahtar)


@pytest.mark.parametrize(
    "girdi, beklenen",
    [("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("720,00 TL", "720.00"),
     ("₺ 1.500", "1500.00"), (99.999, "100.00"), ("1e20", None), ("", None)],
)
def test_tutar_ayristirma(girdi, beklenen):
    assert alanlar.tutar_dogrula(girdi) == (Decimal(beklenen) if beklenen else None)


def test_bicimlendirme():
    assert alanlar.tutar_yaz(Decimal("1234567.5"), "TRY") == "1.234.567,50 TL"
    assert alanlar.tutar_yaz(Decimal("10"), "USD") == "10,00 $"
    assert alanlar.tarih_yaz("2026-03-15") == "15.03.2026"


# ---------------------------------------------------------------- yukleme + detay

def test_yuklemede_bilgiler_kaydedilir_ve_gosterilir(girisli, monkeypatch):
    monkeypatch.setattr(ocr, "metin_cikar", lambda *a: "FATURA metni")
    c, k = girisli
    r = yukle(c, jpeg(), "elektrik.jpg")
    belge_id = int(r.headers["Location"].rsplit("/", 1)[1])
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["kurum"] == "Test Elektrik A.Ş." and kayit["tutar"] == Decimal("720.00")
    assert kayit["belge_tarihi"] == date(2026, 1, 15) and kayit["para_birimi"] == "TRY"
    assert kayit["alanlar"] == {"fatura_no": "2026-000123"}
    sayfa = c.get(f"/belge/{belge_id}").get_data(as_text=True)
    for parca in ("Belge bilgileri", "Test Elektrik A.Ş.", "720,00 TL", "15.01.2026", "2026-000123"):
        assert parca in sayfa
    kart = c.get("/kategori/fatura").get_data(as_text=True)
    assert "720,00 TL" in kart and "15.01.2026" in kart


def test_v3_belgesi_bilgisiz_acilir(girisli):
    c, k = girisli
    belge_id = belge_ekle(k["id"], "eski.jpg", "fatura")
    sayfa = c.get(f"/belge/{belge_id}").get_data(as_text=True)
    assert "henüz bilgi çıkarılmadı" in sayfa
    assert c.get("/kategori/fatura").status_code == 200


# ---------------------------------------------------------------- elle duzenleme

def test_elle_duzenleme(girisli):
    c, k = girisli
    belge_id = belge_ekle(k["id"], tur="fatura", kurum="Yanlış Firma", tutar=10)
    r = c.post(f"/belge/{belge_id}/alanlar", data={
        "kurum": "Doğru Firma", "tutar": "2.450,75", "para_birimi": "EUR",
        "belge_tarihi": "2026-05-01", "fatura_no": "",
    }, follow_redirects=True)
    assert "Belge bilgileri güncellendi" in r.get_data(as_text=True)
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["kurum"] == "Doğru Firma" and kayit["tutar"] == Decimal("2450.75")
    assert kayit["para_birimi"] == "EUR" and kayit["belge_tarihi"] == date(2026, 5, 1)
    assert kayit["alanlar"] == {} and kayit["alanlar_elle_duzeltildi"]
    assert "2.450,75 €" in r.get_data(as_text=True)


def test_elle_duzenlemede_gecersiz_deger_kaydedilmez(girisli):
    c, k = girisli
    belge_id = belge_ekle(k["id"], tur="fatura", kurum="Firma", tutar=10)
    r = c.post(f"/belge/{belge_id}/alanlar",
               data={"kurum": "Başka", "tutar": "on lira", "belge_tarihi": "2026-02-31"},
               follow_redirects=True)
    assert "Tutar, Fatura tarihi" in r.get_data(as_text=True)
    kayit = database.belge_getir(k["id"], belge_id)
    assert kayit["kurum"] == "Firma" and not kayit["alanlar_elle_duzeltildi"]


def test_kimlikte_elle_tc_girilemez(girisli):
    c, k = girisli
    belge_id = belge_ekle(k["id"], tur="kimlik")
    r = c.post(f"/belge/{belge_id}/alanlar", data={"belge_turu": "TC 12345678950"},
               follow_redirects=True)
    assert "saklanmaz" in r.get_data(as_text=True)
    assert database.belge_getir(k["id"], belge_id)["alanlar"] is None


def test_baskasinin_alanlarini_duzenleyemez(girisli, kullanici):
    c, _ = girisli
    diger = kullanici()
    belge_id = belge_ekle(diger["id"], tur="fatura", kurum="Gizli Firma")
    assert c.post(f"/belge/{belge_id}/alanlar", data={"kurum": "X"}).status_code == 404
    assert database.belge_getir(diger["id"], belge_id)["kurum"] == "Gizli Firma"
    assert database.alanlari_guncelle(girisli[1]["id"], belge_id, {"kurum": "X"}) is False


# ---------------------------------------------------------------- filtreler, ozet, arama

@pytest.fixture
def faturalar(girisli):
    c, k = girisli
    ekle = lambda ad, **b: belge_ekle(k["id"], ad, "fatura", **b)  # noqa: E731
    ekle("ocak.jpg", kurum="Enerjisa", tutar=100, para_birimi="TRY", belge_tarihi="2026-01-10")
    ekle("subat.jpg", kurum="İGDAŞ", tutar=250.5, para_birimi="TRY", belge_tarihi="2026-02-10")
    ekle("mart.jpg", kurum="Enerjisa", tutar=900, para_birimi="TRY", belge_tarihi="2026-03-10")
    ekle("dolar.jpg", kurum="AWS", tutar=20, para_birimi="USD", belge_tarihi="2026-03-20")
    ekle("tarihsiz.jpg")
    belge_ekle(k["id"], "dilekce.jpg", "dilekce", kurum="Enerjisa", konu="Sayaç itirazı")
    return c, k


def _adlar(sayfa):
    return [ad for ad in ("ocak", "subat", "mart", "dolar", "tarihsiz", "dilekce") if f"{ad}.jpg" in sayfa]


def test_kategori_filtreleri(faturalar):
    c, _ = faturalar
    sayfa = lambda q: c.get(f"/kategori/fatura?{q}").get_data(as_text=True)  # noqa: E731
    assert _adlar(sayfa("")) == ["ocak", "subat", "mart", "dolar", "tarihsiz"]
    assert _adlar(sayfa("baslangic=2026-02-01&bitis=2026-03-15")) == ["subat", "mart"]
    assert _adlar(sayfa("kurum=enerji")) == ["ocak", "mart"]  # dilekce kategori disi
    assert _adlar(sayfa("min_tutar=200&maks_tutar=500")) == ["subat"]
    assert _adlar(sayfa("min_tutar=1.000")) == []
    assert "Filtreye uyan belge yok" in sayfa("min_tutar=1.000")
    # gecersiz degerler yok sayilir
    assert len(_adlar(sayfa("baslangic=dun&siralama=DROP"))) == 5


def test_siralama(faturalar):
    c, k = faturalar
    sira = lambda s: [b["dosya_adi"] for b in database.belgeleri_suz(k["id"], tur="fatura", siralama=s)]  # noqa: E731
    assert sira("tarih") == ["dolar.jpg", "mart.jpg", "subat.jpg", "ocak.jpg", "tarihsiz.jpg"]
    assert sira("tutar") == ["mart.jpg", "subat.jpg", "ocak.jpg", "dolar.jpg", "tarihsiz.jpg"]
    sayfa = c.get("/kategori/fatura?siralama=tutar").get_data(as_text=True)
    assert sayfa.index("mart.jpg") < sayfa.index("subat.jpg") < sayfa.index("ocak.jpg")


def test_fatura_ozeti(faturalar):
    c, _ = faturalar
    sayfa = c.get("/kategori/fatura").get_data(as_text=True)
    assert "1.250,50 TL" in sayfa and "20,00 $" in sayfa
    assert "1 faturada tutar okunamadı" in sayfa
    suzgecli = c.get("/kategori/fatura?kurum=Enerjisa").get_data(as_text=True)
    assert "1.000,00 TL" in suzgecli and "Seçili filtreye göre" in suzgecli
    assert "data-fatura-ozeti" not in c.get("/kategori/dilekce").get_data(as_text=True)


def test_sayfalama_suzgeci_korur(girisli):
    c, k = girisli
    for i in range(14):
        belge_ekle(k["id"], f"f{i:02}.jpg", "fatura", kurum="Enerjisa", tutar=i)
    sayfa = c.get("/kategori/fatura?kurum=Enerjisa&siralama=tutar").get_data(as_text=True)
    baglantilar = re.findall(r'href="([^"]*sayfa=2[^"]*)"', sayfa)
    assert baglantilar and all("kurum=Enerjisa" in b and "siralama=tutar" in b for b in baglantilar)


def test_arama_kurum_ve_alanlarda(faturalar):
    c, k = faturalar
    assert _adlar(c.get("/ara?q=GDA").get_data(as_text=True)) == ["subat"]
    assert _adlar(c.get("/ara?q=itiraz").get_data(as_text=True)) == ["dilekce"]  # alanlar.konu
    assert [b["dosya_adi"] for b in database.belgeleri_suz(k["id"], sorgu="konu")] == []  # anahtar adi eslesmez
    sayfa = c.get("/ara?q=enerjisa&baslangic=2026-03-01").get_data(as_text=True)
    assert _adlar(sayfa) == ["mart"]


# ---------------------------------------------------------------- mevcut belgelerden bilgi cikarma

def _cikar(c, son_id=0):
    r = c.post("/hesap/bilgi-cikar", data={"son_id": son_id}, headers={"Accept": "application/json"})
    assert r.status_code == 200 and r.is_json
    return r.get_json()


def test_mevcut_belgelerden_bilgi_cikarma(girisli, kullanici):
    c, k = girisli
    eski = belge_ekle(k["id"], "eski_fatura.jpg", "fatura", "FATURA metni")
    elle = belge_ekle(k["id"], "elle.jpg", "fatura", "FATURA metni")
    database.alanlari_guncelle(k["id"], elle, alanlar.dogrula("fatura", {"kurum": "Elle Girilen"})[0])
    database._sorgula("UPDATE belgeler SET alanlar = NULL WHERE id = %s", (elle,))  # v3'ten kalmis gibi
    metinsiz = belge_ekle(k["id"], "okunmaz.jpg", "fatura", "")
    diger_tur = belge_ekle(k["id"], "yazi.jpg", "resmi_yazi", "FATURA gibi görünen resmi yazı")
    baskasi = kullanici()
    yabanci = belge_ekle(baskasi["id"], "yabanci.jpg", "fatura", "FATURA metni")

    assert "2</span> belgenin bilgileri henüz çıkarılmadı" in c.get("/hesap").get_data(as_text=True)
    ilk = _cikar(c)
    assert ilk == {"islenen": 1, "hatali": 0, "yogun": False, "son_id": eski, "kalan": 1}
    ikinci = _cikar(c, ilk["son_id"])
    assert ikinci["son_id"] == diger_tur and ikinci["kalan"] == 0
    assert _cikar(c, ikinci["son_id"])["islenen"] == 0

    kayit = database.belge_getir(k["id"], eski)
    assert kayit["kurum"] == "Test Elektrik A.Ş." and kayit["tutar"] == Decimal("720.00")
    assert not kayit["alanlar_elle_duzeltildi"]
    # tur degismez; fatura gibi gorunse de resmi yazi olarak kalir, alanlar o ture gore
    yazi = database.belge_getir(k["id"], diger_tur)
    assert yazi["tur"] == "resmi_yazi" and yazi["alanlar"] == {} and yazi["tutar"] is None
    # elle duzeltilmis, metinsiz ve baska kullanicinin belgesine dokunulmaz
    assert database.belge_getir(k["id"], elle)["kurum"] == "Elle Girilen"
    assert database.belge_getir(k["id"], metinsiz)["alanlar"] is None
    assert database.belge_getir(baskasi["id"], yabanci)["alanlar"] is None
    assert "Tüm belgelerin bilgileri çıkarılmış" in c.get("/hesap").get_data(as_text=True)


def test_bilgi_cikarmada_hata_ve_yogunluk(girisli, monkeypatch):
    c, k = girisli
    ilk = belge_ekle(k["id"], "bir.jpg", "fatura", "FATURA")
    ikinci = belge_ekle(k["id"], "iki.jpg", "fatura", "FATURA")
    cevaplar = iter([
        {"yogun": True, "alanlar": None},  # 429: ayni belge tekrar denenmeli
        {"yogun": False, "alanlar": None},  # hata: atlanip siradakine gecilmeli
        {"yogun": False, "alanlar": alanlar.dogrula("fatura", {"kurum": "Firma"})[0]},
    ])
    monkeypatch.setattr(classifier, "siniflandir", lambda metin, bilinen_tur=None: next(cevaplar))

    r = _cikar(c)
    assert r["yogun"] and r["son_id"] == 0 and r["kalan"] == 2
    r = _cikar(c, r["son_id"])
    assert r == {"islenen": 0, "hatali": 1, "yogun": False, "son_id": ilk, "kalan": 1}
    r = _cikar(c, r["son_id"])
    assert r["islenen"] == 1 and r["kalan"] == 0
    assert database.belge_getir(k["id"], ikinci)["kurum"] == "Firma"
    assert database.belge_getir(k["id"], ilk)["alanlar"] is None  # sonra yeniden denenebilir


def test_bilgi_cikarma_js_kapaliyken(girisli):
    c, k = girisli
    for i in range(7):
        belge_ekle(k["id"], f"f{i}.jpg", "fatura", "FATURA")
    r = c.post("/hesap/bilgi-cikar", follow_redirects=True)
    assert "5 belgeden bilgi çıkarıldı. 2 belge kaldı" in r.get_data(as_text=True)
    assert database.bilgisi_eksik_sayisi(k["id"]) == 2
