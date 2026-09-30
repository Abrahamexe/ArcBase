"""Yerel mod (kurum kurulumu) korumasi.

YEREL_MOD=1 iken belgeler ve veritabani kurumun kendi aginda kalmalidir:
DATABASE_URL yalnizca bu bilgisayari (localhost, 127.x, ::1, Unix soketi) ya
da ozel ag adresini (10.x, 172.16-31.x, 192.168.x, IPv6 fc00::/7) gosterebilir.
Neon gibi bulut veritabani adresiyle uygulama BASLAMAZ ve nedenini yazar.

Sunucu adi (or. "sunucu.kurum.local") kabul edilmez: adin nereye cozuldugu
degisebilir; yerel agdaki veritabani IP adresiyle yazilir.

Uygulamanin disariya yaptigi tek baglanti Groq API cagrisidir (classifier.py);
Groq'a yalnizca OCR metni gider. Gorsel, dosya ve veritabani icerigi gitmez.
"""

import ipaddress
import os

import psycopg2.extensions

YEREL_ADLAR = {"localhost"}
OZEL_AGLAR = tuple(
    ipaddress.ip_network(ag)
    for ag in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
)


class YerelModHatasi(RuntimeError):
    """Yerel mod acikken kurala uymayan ayar; mesaj kullaniciya gosterilir."""


def acik():
    return os.getenv("YEREL_MOD", "").strip() == "1"


def sunucu_yerel_mi(sunucu):
    """Tek bir sunucu adi/adresi bu bilgisayar ya da ozel ag mi?"""
    sunucu = (sunucu or "").strip().strip("[]").lower()
    if not sunucu or sunucu.startswith("/") or sunucu in YEREL_ADLAR:
        return True  # bos ya da "/" ile baslayan: Unix soketi (ayni bilgisayar)
    try:
        adres = ipaddress.ip_address(sunucu.split("%")[0])
    except ValueError:
        return False
    return any(adres in ag for ag in OZEL_AGLAR)


def adres_yerel_mi(adres):
    """Veritabani adresinin tum sunuculari yerel/ozel ag mi? (postgresql://...
    ve "host=... dbname=..." bicimleri; ?host= ve virgulle ayrilmis coklu
    sunucu dahil). Cozumlenemeyen adres yerel sayilmaz."""
    try:
        ayrinti = psycopg2.extensions.parse_dsn(adres)
    except psycopg2.ProgrammingError:
        return False
    sunucular = (ayrinti.get("host") or "").split(",") + [
        a for a in (ayrinti.get("hostaddr") or "").split(",") if a
    ]
    return all(sunucu_yerel_mi(s) for s in sunucular)


def denetle():
    """YEREL_MOD=1 iken ayarlari denetler; uymuyorsa YerelModHatasi firlatir.
    Mesaj adresin kendisini (kullanici adi, sifre) icermez."""
    if not acik():
        return
    adres = (os.getenv("DATABASE_URL") or "").strip()
    if adres and not adres_yerel_mi(adres):
        raise YerelModHatasi(
            "YEREL_MOD=1 açık, ancak DATABASE_URL bu bilgisayardaki ya da yerel ağdaki bir veritabanını "
            "göstermiyor (bulut veritabanı, ör. Neon, yerel modda kullanılamaz). DATABASE_URL'deki sunucu "
            "localhost, 127.0.0.1 ya da özel ağ IP adresi (10.x.x.x, 172.16-31.x.x, 192.168.x.x) olmalı."
        )
