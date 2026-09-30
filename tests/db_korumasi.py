"""Testlerin ve olcum betiklerinin canli veritabanina baglanmasini engeller.

Yalnizca .env'deki TEST_DATABASE_URL kullanilir; DATABASE_URL (canli
veritabani) ve YEREL_DATABASE_URL hicbir kosulda kullanilmaz. veritabanini_ayarla() .env
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


YEREL_SUNUCULAR = ("", "localhost", "127.0.0.1", "::1")


class CanliVeritabaniHatasi(RuntimeError):
    """TEST_DATABASE_URL canli veritabanini gosteriyor."""


def _kimlik(adres):
    """(sunucu, port, veritabani). Neon'un havuzlayici adresi (ep-...-pooler)
    dogrudan adresle ayni veritabanidir; yerel sunucunun adlari da birdir."""
    parca = urlsplit(adres.strip())
    sunucu = (parca.hostname or "").lower()
    ilk, nokta, geri = sunucu.partition(".")
    if ilk.endswith("-pooler"):
        ilk = ilk[: -len("-pooler")]
    sunucu = ilk + nokta + geri
    if sunucu in YEREL_SUNUCULAR:  # localhost ile 127.0.0.1 ayni sunucudur
        sunucu = "localhost"
    return sunucu, parca.port or 5432, unquote(parca.path.lstrip("/"))


def ayni_veritabani(a, b):
    if not a or not b:
        return False
    if a.strip() == b.strip():
        return True
    try:
        return _kimlik(a) == _kimlik(b)
    except ValueError:
        return False


# Canli sayilan adresler: DATABASE_URL ve yerel moda geciste asil veritabani
# olacak YEREL_DATABASE_URL (scripts/veri_tasi.py'nin hedefi).
CANLI_DEGISKENLER = ("DATABASE_URL", "YEREL_DATABASE_URL")


def _canli_adresler():
    env = dotenv_values(ENV_DOSYASI) if ENV_DOSYASI.exists() else {}
    adresler = [env.get(ad) for ad in CANLI_DEGISKENLER]
    adresler.append(os.environ.get("YEREL_DATABASE_URL"))
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
            "TEST_DATABASE_URL, canlı veritabanıyla (DATABASE_URL / YEREL_DATABASE_URL) aynı veritabanını gösteriyor. "
            "Testler ve ölçümler canlı veritabanında çalıştırılmaz; .env'de ayrı bir test veritabanı tanımlayın."
        )
    os.environ["DATABASE_URL"] = test
    return test or None
