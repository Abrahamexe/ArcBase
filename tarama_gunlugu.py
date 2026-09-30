"""Tarama olaylarinin kisa gecmisi (yoneticinin "Tarama durumu" sayfasi icin).

Klasorlerden aktarilan son dosyalar, son hatalar ve tarayicinin takilip
cikarilmasi bellekte tutulur (surec basina; uygulama yeniden baslayinca
bosalir). Buraya kullaniciya gosterilecek sade metin yazilir; teknik ayrinti
(hata kodu, yigin izi) yalnizca uygulama gunlugune gider.
"""

import threading
from collections import deque
from datetime import datetime, timezone

KAYIT_SAYISI = 20

_kilit = threading.Lock()
_aktarilanlar = deque(maxlen=KAYIT_SAYISI)
_hatalar = deque(maxlen=KAYIT_SAYISI)


def _simdi():
    return datetime.now(timezone.utc)


def aktarildi(dosya, kime, gelen_kutusu=False, kaynak=""):
    with _kilit:
        _aktarilanlar.appendleft(
            {"zaman": _simdi(), "dosya": dosya, "kime": kime, "gelen_kutusu": gelen_kutusu, "kaynak": kaynak}
        )


def hata(kaynak, mesaj):
    with _kilit:
        _hatalar.appendleft({"zaman": _simdi(), "kaynak": kaynak, "mesaj": mesaj})


def son_aktarilanlar():
    with _kilit:
        return list(_aktarilanlar)


def son_hatalar():
    with _kilit:
        return list(_hatalar)


def temizle():
    """Testler icin."""
    with _kilit:
        _aktarilanlar.clear()
        _hatalar.clear()
