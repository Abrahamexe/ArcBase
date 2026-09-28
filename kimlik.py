"""Kullanici oturumu (Flask-Login), sifre hash'leme ve kayit/giris kurallari."""

import hashlib
import re
from urllib.parse import urlsplit

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

import database

KULLANICI_ADI_KALIBI = re.compile(r"^[A-Za-z0-9_]{3,30}$")
SIFRE_EN_AZ = 8
SIFRE_EN_FAZLA = 128  # cok uzun girdilerle hash'leme yavaslatilmasin

HATALI_GIRIS_MESAJI = "Kullanıcı adı veya şifre hatalı."

# Olmayan kullanici adinda da ayni sure harcansin diye karsilastirilan sahte
# hash; boylece yanit suresinden adin kayitli olup olmadigi anlasilmaz.
_SAHTE_HASH = generate_password_hash("zamanlama-esitleme")


class Kullanici(UserMixin):
    def __init__(self, satir):
        self.id = satir["id"]
        self.kullanici_adi = satir["kullanici_adi"]
        self.sifre_hash = satir["sifre_hash"]
        self.olusturma_tarihi = satir["olusturma_tarihi"]
        # Istek basinda kullaniciyla ayni sorguda gelen sayaclar (menu, kota,
        # "bu hafta"); giris/kayit aninda olusturulan nesnede yoktur (None).
        self.sayaclar = satir.get("sayaclar")

    def get_id(self):
        """Oturum kimligine sifrenin parmak izi de eklenir: sifre degisince
        diger cihazlardaki oturumlar ve "beni hatirla" cerezleri gecersizlesir."""
        return f"{self.id}-{sifre_parmak_izi(self.sifre_hash)}"


def sifre_parmak_izi(sifre_hash):
    return hashlib.sha256(sifre_hash.encode()).hexdigest()[:16]


def oturumdan_yukle(oturum_kimligi):
    """Flask-Login user_loader'i: "id-parmakizi" degerinden kullaniciyi bulur.

    Her istekte calistigi icin sayfalarin ortak sayaclari da ayni sorguda alinir."""
    kullanici_id, _, parmak_izi = (oturum_kimligi or "").partition("-")
    if not kullanici_id.isdigit():
        return None
    satir = database.kullanici_ozeti(int(kullanici_id))
    if satir is None or sifre_parmak_izi(satir["sifre_hash"]) != parmak_izi:
        return None
    return Kullanici(satir)


def sifre_hashle(sifre):
    return generate_password_hash(sifre)


def kullanici_adi_hatasi(kullanici_adi):
    if not KULLANICI_ADI_KALIBI.match(kullanici_adi or ""):
        return (
            "Kullanıcı adı 3-30 karakter olmalı; sadece İngilizce harf, "
            "rakam ve alt çizgi (_) içerebilir."
        )
    return None


def sifre_hatasi(sifre, tekrar=None):
    if len(sifre or "") < SIFRE_EN_AZ:
        return f"Şifre en az {SIFRE_EN_AZ} karakter olmalı."
    if len(sifre) > SIFRE_EN_FAZLA:
        return f"Şifre en fazla {SIFRE_EN_FAZLA} karakter olabilir."
    if tekrar is not None and sifre != tekrar:
        return "Şifreler birbiriyle eşleşmiyor."
    return None


def dogrula(kullanici_adi, sifre):
    """Ad ve sifre dogruysa Kullanici, degilse None dondurur."""
    satir = database.kullanici_adi_ile_getir(kullanici_adi) if kullanici_adi else None
    if satir is None:
        check_password_hash(_SAHTE_HASH, sifre or "")
        return None
    if not check_password_hash(satir["sifre_hash"], sifre or ""):
        return None
    return Kullanici(satir)


def sifre_dogru_mu(kullanici, sifre):
    return check_password_hash(kullanici.sifre_hash, sifre or "")


def guvenli_yonlendirme(adres):
    """Giris sonrasi "next" adresi sadece site ici bir yol olabilir
    (acik yonlendirme / open redirect engellenir)."""
    if not adres or not adres.startswith("/") or adres.startswith("//"):
        return None
    parca = urlsplit(adres)
    if parca.scheme or parca.netloc or "\\" in adres:
        return None
    return adres
