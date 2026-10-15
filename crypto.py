"""Belge iceriklerinin Fernet ile sifrelenmesi ve cozulmesi.

Sifreleme anahtari .env icindeki ENCRYPTION_KEY'den okunur. Anahtar bir kez
uretilir ve ASLA degistirilmez; degisirse veritabanindaki tum belgeler
cozulemez hale gelir.
"""

import os

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

load_dotenv()

_fernet = None


class SifrelemeHatasi(RuntimeError):
    """Anahtar eksik/bozuk ya da veri cozulemedi."""


def _fernet_al():
    """Fernet nesnesini bir kez olusturup tekrar kullanir."""
    global _fernet
    if _fernet is not None:
        return _fernet

    anahtar = os.getenv("ENCRYPTION_KEY")
    if not anahtar:
        raise SifrelemeHatasi(
            "ENCRYPTION_KEY tanımlı değil. .env dosyasına ekleyin "
            "(python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())")'
        )
    try:
        _fernet = Fernet(anahtar.strip().encode())
    except (ValueError, TypeError) as hata:
        raise SifrelemeHatasi(f"ENCRYPTION_KEY geçersiz: {hata}") from hata
    return _fernet


def sifrele(veri):
    """Ham baytlari sifreleyip sifreli baytlari dondurur."""
    if veri is None:
        return None
    return _fernet_al().encrypt(veri)


def coz(sifreli_veri):
    """Sifreli baytlari cozup orijinal baytlari dondurur."""
    if sifreli_veri is None:
        return None
    try:
        return _fernet_al().decrypt(bytes(sifreli_veri))
    except InvalidToken as hata:
        raise SifrelemeHatasi(
            "Belge çözülemedi. ENCRYPTION_KEY değişmiş olabilir."
        ) from hata
