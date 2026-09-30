"""Yerel mod: bulut veritabani adresinin reddi, yerel/ozel ag adresinin kabulu
ve arayuzun hicbir dis adrese (CDN, Google Fonts) istek atmamasi."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import yerel_mod
from conftest import belge_ekle

PROJE = Path(__file__).resolve().parent.parent

NEON = "postgresql://kullanici:sifre@ep-sessiz-orman-123456-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require"


@pytest.mark.parametrize(
    "adres",
    [
        "postgresql://arcbase:s@localhost:5432/arcbase",
        "postgresql://arcbase:s@127.0.0.1/arcbase",
        "postgresql://arcbase:s@[::1]:5432/arcbase",
        "postgresql:///arcbase",  # Unix soketi
        "postgresql://arcbase:s@10.0.0.5/arcbase",
        "postgresql://arcbase:s@172.16.0.1/arcbase",
        "postgresql://arcbase:s@172.31.255.254/arcbase",
        "postgresql://arcbase:s@192.168.1.50:5432/arcbase",
        "host=192.168.1.50 dbname=arcbase user=arcbase",
        "postgresql://arcbase:s@localhost,192.168.1.51/arcbase",
    ],
)
def test_yerel_ve_ozel_ag_adresleri_kabul_edilir(adres):
    assert yerel_mod.adres_yerel_mi(adres)


@pytest.mark.parametrize(
    "adres",
    [
        NEON,
        "postgresql://u:s@db.example.com/arcbase",
        "postgresql://u:s@8.8.8.8/arcbase",
        "postgresql://u:s@172.32.0.1/arcbase",  # 172.16-31 disi
        "postgresql://u:s@192.169.1.1/arcbase",
        "postgresql://u:s@11.0.0.1/arcbase",
        "postgresql://u:s@sunucu.kurum.local/arcbase",  # ad: nereye cozuldugu bilinmez
        "postgresql://u:s@localhost,ep-x.neon.tech/arcbase",  # sunuculardan biri bulutta
        "postgresql://u:s@/arcbase?host=ep-x.neon.tech",
        "bozuk adres ===",
    ],
)
def test_bulut_ve_disaridaki_adresler_reddedilir(adres):
    assert not yerel_mod.adres_yerel_mi(adres)


def test_denetim_yalnizca_yerel_modda_uygulanir(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", NEON)
    monkeypatch.delenv("YEREL_MOD", raising=False)
    yerel_mod.denetle()  # bulut modu: Neon serbest
    monkeypatch.setenv("YEREL_MOD", "1")
    with pytest.raises(yerel_mod.YerelModHatasi) as hata:
        yerel_mod.denetle()
    assert "sifre" not in str(hata.value) and "neon.tech" not in str(hata.value)
    monkeypatch.setenv("DATABASE_URL", "postgresql://arcbase:s@localhost/arcbase")
    yerel_mod.denetle()


def _uygulamayi_baslat(**ortam):
    """app modulunu ayri bir surecte ice aktarir (veritabanina baglanmaz:
    baglanti ilk istekte acilir)."""
    env = {**os.environ, "ARKA_PLAN_ISCISI": "0", **ortam}
    return subprocess.run(
        [sys.executable, "-c", "import app"], cwd=PROJE, env=env, capture_output=True, text=True, timeout=120
    )


def test_uygulama_yerel_modda_bulut_veritabaniyla_baslamaz():
    sonuc = _uygulamayi_baslat(YEREL_MOD="1", DATABASE_URL=NEON)
    assert sonuc.returncode != 0
    assert "ArcBase başlatılamadı" in sonuc.stderr and "YEREL_MOD" in sonuc.stderr
    assert "sifre" not in sonuc.stderr


def test_uygulama_yerel_modda_yerel_veritabaniyla_baslar():
    sonuc = _uygulamayi_baslat(YEREL_MOD="1", DATABASE_URL="postgresql://u:s@127.0.0.1:1/yok")
    assert sonuc.returncode == 0, sonuc.stderr


# ---------------------------------------------------------------- dis kaynak yok

# Tarayicinin kendiliginden yukledigi kaynaklar (baglanti <a href> degil).
_DIS_ETIKET = re.compile(
    r"<(?:link|script|img|iframe|source|video|audio|embed|object)\b[^>]*?\s(?:href|src|data)\s*=\s*[\"']?\s*(?:https?:)?//",
    re.IGNORECASE,
)
_DIS_CSS = re.compile(r"(?:url\(\s*[\"']?\s*(?:https?:)?//|@import\s+(?:url\()?\s*[\"']?\s*(?:https?:)?//)", re.IGNORECASE)
_DIS_JS = re.compile(r"(?:fetch|import|importScripts)\s*\(\s*[\"'`](?:https?:)?//|[\"'`]https?://(?!www\.w3\.org/)", re.IGNORECASE)


def _dis_kaynaklar(html):
    return _DIS_ETIKET.findall(html) + _DIS_CSS.findall(html)


def test_dis_kaynak_denetimi_ornekleri_yakalar():
    assert _dis_kaynaklar('<link href="https://fonts.googleapis.com/css2" rel="stylesheet">')
    assert _dis_kaynaklar("<script src='//cdn.example.com/x.js'></script>")
    assert _dis_kaynaklar("<style>@import url(https://x.y/z.css);</style>")
    assert _dis_kaynaklar('<div style="background:url(http://x.y/a.png)">')
    assert not _dis_kaynaklar('<a href="https://github.com/">kaynak kod</a>')
    assert not _dis_kaynaklar('<svg xmlns="http://www.w3.org/2000/svg"></svg>')


def test_statik_dosyalarda_dis_kaynak_yok():
    statik = PROJE / "static"
    dosyalar = [p for p in statik.rglob("*") if p.suffix in (".css", ".js")]
    assert dosyalar
    for yol in dosyalar:
        metin = yol.read_text(encoding="utf-8")
        bulunan = _DIS_CSS.findall(metin) + (_DIS_JS.findall(metin) if yol.suffix == ".js" else [])
        assert not bulunan, f"{yol.relative_to(PROJE)}: {bulunan}"


def test_sablonlarda_dis_kaynak_yok():
    for yol in (PROJE / "templates").glob("*.html"):
        assert not _dis_kaynaklar(yol.read_text(encoding="utf-8")), yol.name


def test_yazi_tipi_yerelden_sunulur(istemci):
    for dosya in ("fonts.css", "fonts/plus-jakarta-sans-latin.woff2", "fonts/plus-jakarta-sans-latin-ext.woff2"):
        yanit = istemci.get(f"/static/{dosya}")
        assert yanit.status_code == 200, dosya
        yanit.close()


def test_sayfalarda_dis_kaynak_yok(istemci, girisli):
    c, k = girisli
    belge_id = belge_ekle(k["id"], ocr_metni="FATURA")
    girissiz = [(adres, istemci) for adres in ("/", "/giris", "/kayit", "/olmayan-sayfa")]
    girisli_sayfalar = [
        (adres, c) for adres in ("/", "/hesap", "/kategori/fatura", "/ara?q=fatura", f"/belge/{belge_id}")
    ]
    for adres, i in girissiz + girisli_sayfalar:
        html = i.get(adres).get_data(as_text=True)
        assert "<html" in html.lower(), adres
        assert not _dis_kaynaklar(html), f"{adres}: {_dis_kaynaklar(html)}"
        assert "fonts.css" in html, adres


# ---------------------------------------------------------------- waitress ve cerez ayari


@pytest.mark.parametrize(
    "ortam, guvenli",
    [
        ({}, False),  # gelistirme: python app.py
        ({"URETIM": "1"}, True),  # Render: her zaman HTTPS
        ({"YEREL_MOD": "1"}, False),  # kurum, yerel agda HTTP: giris calismali
        ({"YEREL_MOD": "1", "URETIM": "1"}, False),  # kurumda Docker imaji
        ({"YEREL_MOD": "1", "HTTPS": "1"}, True),  # kurum, onde TLS var
    ],
)
def test_guvenli_cerez_ayari(ortam, guvenli):
    temel = {"URETIM": "", "YEREL_MOD": "", "HTTPS": "", "SECRET_KEY": "test-anahtari",
             "DATABASE_URL": "postgresql://u:s@127.0.0.1:1/yok"}
    env = {**os.environ, "ARKA_PLAN_ISCISI": "0", **temel, **ortam}
    kod = "import app; c = app.app.config; print(c['SESSION_COOKIE_SECURE'], c['REMEMBER_COOKIE_SECURE'])"
    sonuc = subprocess.run([sys.executable, "-c", kod], cwd=PROJE, env=env, capture_output=True, text=True, timeout=120)
    assert sonuc.returncode == 0, sonuc.stderr
    assert sonuc.stdout.split() == [str(guvenli)] * 2


def test_yerel_modda_secret_key_zorunlu():
    env = {**os.environ, "ARKA_PLAN_ISCISI": "0", "YEREL_MOD": "1", "SECRET_KEY": "",
           "DATABASE_URL": "postgresql://u:s@127.0.0.1:1/yok"}
    sonuc = subprocess.run([sys.executable, "-c", "import app"], cwd=PROJE, env=env, capture_output=True, text=True,
                           timeout=120)
    assert sonuc.returncode != 0 and "SECRET_KEY" in sonuc.stderr


def test_sunucu_waitress_ile_baslar(monkeypatch, capsys):
    import isleme
    import sunucu
    import waitress

    cagri = {}
    monkeypatch.setattr(waitress, "serve", lambda uygulama, **ayar: cagri.update(uygulama=uygulama, **ayar))
    monkeypatch.setattr(isleme, "etkin", lambda: True)
    monkeypatch.setattr(isleme, "baslat", lambda: cagri.setdefault("isci", True))
    monkeypatch.setattr(sunucu, "yerel_ag_adresleri", lambda: ["192.168.1.50"])
    monkeypatch.setenv("PORT", "5099")
    monkeypatch.delenv("SUNUCU_ADRESI", raising=False)

    sunucu.main()

    import app

    assert cagri["uygulama"] is app.app and cagri["isci"]
    assert (cagri["host"], cagri["port"], cagri["url_scheme"]) == ("0.0.0.0", 5099, "http")
    assert "http://192.168.1.50:5099" in capsys.readouterr().out


def test_yerel_ag_adresleri_yalnizca_ozel_ag(monkeypatch):
    import sunucu

    bilgiler = [(2, 1, 6, "", (a, 0)) for a in ("192.168.1.50", "127.0.0.1", "8.8.8.8", "10.0.0.2", "192.168.1.50")]
    monkeypatch.setattr(sunucu.socket, "getaddrinfo", lambda *a, **k: bilgiler)
    assert sunucu.yerel_ag_adresleri() == ["192.168.1.50", "10.0.0.2"]
