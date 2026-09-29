"""Testlerin ve olcum betiklerinin canli veritabanina baglanmasini engeller.

Yalnizca .env'deki TEST_DATABASE_URL kullanilir; DATABASE_URL (canli
veritabani) hicbir kosulda kullanilmaz. veritabanini_ayarla() .env
yuklendikten sonra, uygulama modulleri ice aktarilmadan once cagrilir:
DATABASE_URL'i test adresiyle degistirir, test adresi yoksa bos birakir.
Uygulama modulleri ice aktarilirken load_dotenv() cagirir ama var olan
degiskeni ezmez; bos DATABASE_URL ile database modulu hic baglanti acmaz.

Adresler yazdirilmaz.
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

ENV_DOSYASI = Path(__file__).resolve().parent.parent / ".env"
# Ayarlandiktan sonra ortamdaki DATABASE_URL artik canli adres degildir; alt
# surecler (pytest-xdist isciler) bu isareti devralir.
AYARLANDI = "ARCBASE_TEST_DB_AYARLANDI"


class CanliVeritabaniHatasi(RuntimeError):
    """TEST_DATABASE_URL canli veritabanini gosteriyor."""


def _kimlik(adres):
    """(sunucu, port, veritabani). Neon'un havuzlayici adresi (ep-...-pooler)
    dogrudan adresle ayni veritabanidir."""
    parca = urlsplit(adres.strip())
    sunucu = (parca.hostname or "").lower()
    ilk, nokta, geri = sunucu.partition(".")
    if ilk.endswith("-pooler"):
        ilk = ilk[: -len("-pooler")]
    return ilk + nokta + geri, parca.port or 5432, unquote(parca.path.lstrip("/"))


def ayni_veritabani(a, b):
    if not a or not b:
        return False
    if a.strip() == b.strip():
        return True
    try:
        return _kimlik(a) == _kimlik(b)
    except ValueError:
        return False


def _canli_adresler():
    adresler = [dotenv_values(ENV_DOSYASI).get("DATABASE_URL") if ENV_DOSYASI.exists() else None]
    if os.environ.get(AYARLANDI) != "1":
        adresler.append(os.environ.get("DATABASE_URL"))
    return [a.strip() for a in adresler if a and a.strip()]


def veritabanini_ayarla():
    """TEST_DATABASE_URL'i DATABASE_URL olarak ayarlar ve dondurur; tanimli
    degilse DATABASE_URL'i bosaltip None dondurur. TEST_DATABASE_URL canli
    veritabaniyla ayniysa CanliVeritabaniHatasi firlatir (DATABASE_URL yine
    bosaltilir, hicbir baglanti acilamaz)."""
    test = (os.environ.get("TEST_DATABASE_URL") or "").strip()
    canli = _canli_adresler()
    os.environ["DATABASE_URL"] = ""
    os.environ[AYARLANDI] = "1"
    if test and any(ayni_veritabani(test, a) for a in canli):
        raise CanliVeritabaniHatasi(
            "TEST_DATABASE_URL, DATABASE_URL (canlı veritabanı) ile aynı veritabanını gösteriyor. "
            "Testler ve ölçümler canlı veritabanında çalıştırılmaz; .env'de ayrı bir test veritabanı tanımlayın."
        )
    os.environ["DATABASE_URL"] = test
    return test or None
