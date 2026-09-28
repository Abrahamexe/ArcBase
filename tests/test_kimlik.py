"""Kayit, giris, cikis, CSRF, hiz siniri ve sayfa korumasi."""

import re

import pytest

import database
from conftest import SIFRE, giris_yap


def kayit_ol(istemci, ad, sifre=SIFRE, tekrar=None):
    return istemci.post(
        "/kayit",
        data={"kullanici_adi": ad, "sifre": sifre, "sifre_tekrar": tekrar or sifre},
    )


# ---------------------------------------------------------------- kayit

def test_kayit_basarili_ve_sifre_hashli(istemci, yeni_ad):
    ad = yeni_ad()
    r = kayit_ol(istemci, ad)
    assert r.status_code == 302 and r.headers["Location"] == "/"
    satir = database.kullanici_adi_ile_getir(ad)
    assert satir["sifre_hash"] != SIFRE
    assert satir["sifre_hash"].startswith(("scrypt:", "pbkdf2:"))
    # Kayittan sonra oturum acik: panel gorunur
    assert "Çıkış yap" in istemci.get("/").get_data(as_text=True)


@pytest.mark.parametrize(
    "ad, sifre, tekrar, mesaj",
    [
        ("ab", SIFRE, SIFRE, "3-30 karakter"),
        ("a" * 31, SIFRE, SIFRE, "3-30 karakter"),
        ("bosluk var", SIFRE, SIFRE, "3-30 karakter"),
        ("türkçe_ğ", SIFRE, SIFRE, "3-30 karakter"),
        ("gecerli_ad", "kisa", "kisa", "en az 8"),
        ("gecerli_ad", SIFRE, SIFRE + "x", "eşleşmiyor"),
    ],
)
def test_kayit_kurallari(istemci, ad, sifre, tekrar, mesaj):
    r = kayit_ol(istemci, ad, sifre, tekrar)
    assert r.status_code == 400
    assert mesaj in r.get_data(as_text=True)
    assert database.kullanici_adi_ile_getir("gecerli_ad") is None


def test_kullanici_adi_buyuk_kucuk_harf_duyarsiz_benzersiz(uygulama, yeni_ad):
    ad = yeni_ad()
    assert kayit_ol(uygulama.test_client(), ad).status_code == 302
    r = kayit_ol(uygulama.test_client(), ad.upper())
    assert r.status_code == 400
    assert "alınmış" in r.get_data(as_text=True)


# ---------------------------------------------------------------- giris / cikis

def test_giris_buyuk_kucuk_harf_duyarsiz(istemci, kullanici):
    k = kullanici()
    r = giris_yap(istemci, k["ad"].upper())
    assert r.status_code == 302 and r.headers["Location"] == "/"


def test_hatali_giris_ayni_mesaj(istemci, kullanici):
    k = kullanici()
    yanlis_sifre = giris_yap(istemci, k["ad"], "yanlis_sifre")
    olmayan = giris_yap(istemci, "hic_olmayan_kullanici", "yanlis_sifre")
    for r in (yanlis_sifre, olmayan):
        assert r.status_code == 401
        assert "Kullanıcı adı veya şifre hatalı." in r.get_data(as_text=True)
    assert istemci.get("/hesap").status_code == 302  # oturum acilmadi


def test_giris_sonrasi_next_ve_acik_yonlendirme(istemci, kullanici):
    k = kullanici()
    r = istemci.post(
        "/giris?next=/ara", data={"kullanici_adi": k["ad"], "sifre": SIFRE}
    )
    assert r.headers["Location"] == "/ara"
    istemci.post("/cikis")
    for kotu in ("//evil.com", "https://evil.com/x", "/\\evil.com"):
        r = istemci.post(
            f"/giris?next={kotu}", data={"kullanici_adi": k["ad"], "sifre": SIFRE}
        )
        assert r.headers["Location"] == "/", kotu
        istemci.post("/cikis")


def test_beni_hatirla_cerezi(istemci, kullanici):
    k = kullanici()
    r = giris_yap(istemci, k["ad"], beni_hatirla="1")
    cerezler = " ".join(r.headers.getlist("Set-Cookie"))
    assert "remember_token=" in cerezler


def test_cikis(girisli):
    c, _ = girisli
    assert c.get("/cikis").status_code == 405  # sadece POST
    r = c.post("/cikis")
    assert r.status_code == 302 and r.headers["Location"] == "/giris"
    assert c.get("/hesap").status_code == 302


def test_girisliyken_giris_ve_kayit_panele_yonlenir(girisli):
    c, _ = girisli
    assert c.get("/giris").headers["Location"] == "/"
    assert c.get("/kayit").headers["Location"] == "/"


# ---------------------------------------------------------------- CSRF

def test_csrf_tokensiz_post_reddedilir(uygulama, kullanici):
    k = kullanici()
    uygulama.config["WTF_CSRF_ENABLED"] = True
    c = uygulama.test_client()
    r = c.post(
        "/giris", data={"kullanici_adi": k["ad"], "sifre": SIFRE}, follow_redirects=True
    )
    assert "Form süresi doldu veya geçersiz" in r.get_data(as_text=True)
    assert c.get("/hesap").status_code == 302  # oturum acilmadi

    html = c.get("/giris").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    r = giris_yap(c, k["ad"], csrf_token=token)
    assert r.headers["Location"] == "/"
    # Giris sonrasi tum formlarda token var
    for yol in ("/", "/hesap"):
        assert 'name="csrf_token"' in c.get(yol).get_data(as_text=True)


# ---------------------------------------------------------------- hiz siniri

def test_giris_hiz_siniri_dakikada_5(istemci, kullanici):
    import app as uygulama_modulu

    uygulama_modulu.limiter.enabled = True
    k = kullanici()
    kodlar = [giris_yap(istemci, k["ad"], "yanlis").status_code for _ in range(6)]
    assert kodlar == [401] * 5 + [429]
    # Dogru sifre de artik engelli (kaba kuvvet denemesi durur)
    r = giris_yap(istemci, k["ad"])
    assert r.status_code == 429
    assert "Çok fazla deneme" in r.get_data(as_text=True)


def test_kayit_hiz_siniri_saatte_5(uygulama, yeni_ad):
    import app as uygulama_modulu

    uygulama_modulu.limiter.enabled = True
    # Hatali formlar sayilmaz
    for _ in range(3):
        assert kayit_ol(uygulama.test_client(), "x").status_code == 400
    kodlar = [kayit_ol(uygulama.test_client(), yeni_ad()).status_code for _ in range(6)]
    assert kodlar == [302] * 5 + [429]


# ---------------------------------------------------------------- sayfa korumasi

KORUNAN_GET = ["/hesap", "/ara?q=x", "/kategori/fatura", "/belge/1", "/gorsel/1",
               "/onizleme/1", "/belge/1/indir"]
KORUNAN_POST = ["/yukle", "/belge/1/tur", "/belge/1/sil", "/hesap/sifre", "/hesap/sil"]


@pytest.mark.parametrize("yol", KORUNAN_GET)
def test_girissiz_get_giris_sayfasina_yonlenir(istemci, yol):
    r = istemci.get(yol)
    assert r.status_code == 302
    assert r.headers["Location"].startswith("/giris?next=")


@pytest.mark.parametrize("yol", KORUNAN_POST)
def test_girissiz_post_engellenir(istemci, yol):
    r = istemci.post(yol)
    assert r.status_code == 302
    assert r.headers["Location"].startswith("/giris")


def test_acilis_sayfasi(istemci):
    r = istemci.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Ücretsiz hesap oluştur" in html and "/kayit" in html and "/giris" in html
    assert "kenar-menu" not in html  # uygulama menusu gosterilmez
