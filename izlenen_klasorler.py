"""Sonradan eklenen / kaldirilan izlenen klasorler (bu bilgisayara ozel ayar).

"Taradigim belgeler gorunmuyor" ya da "Klasoru kendim secegim" ile eklenen
klasorler ve listeden kaldirilan Windows varsayilan tarama klasorleri, sunucu
bilgisayarinda kucuk bir JSON dosyasinda tutulur (klasor yollari o bilgisayara
ozeldir; veritabanina yazilmaz). Dosya: IZLENEN_KLASORLER_DOSYASI, bossa
<proje>/veri/izlenen_klasorler.json (git'e gitmez).

Her eklenen klasorde "baslangic" (Unix zamani) varsa, klasore o andan once
dusmus dosyalar alinmaz ("sadece bundan sonrakiler"); None ise hepsi alinir.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("dijital_arsiv.klasor")

VARSAYILAN_DOSYA = Path(__file__).resolve().parent / "veri" / "izlenen_klasorler.json"

_kilit = threading.Lock()


def _dosya():
    return Path(os.getenv("IZLENEN_KLASORLER_DOSYASI") or VARSAYILAN_DOSYA)


def normal(yol):
    """Karsilastirma icin yol (mutlak, Windows'ta buyuk/kucuk harf duyarsiz)."""
    return os.path.normcase(os.path.abspath(str(yol)))


def _bos():
    return {"klasorler": [], "kaldirilan_varsayilanlar": []}


def oku():
    try:
        veri = json.loads(_dosya().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _bos()
    except (OSError, ValueError):
        log.exception("Izlenen klasorler dosyasi okunamadi: %s", _dosya())
        return _bos()
    return {**_bos(), **veri}


def _yaz(veri):
    dosya = _dosya()
    dosya.parent.mkdir(parents=True, exist_ok=True)
    gecici = dosya.with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(gecici, dosya)


def ekli_klasorler():
    """[{"yol", "baslangic", "ekleyen", "eklenme"}]"""
    return oku()["klasorler"]


def kaldirilan_varsayilanlar():
    return {normal(y) for y in oku()["kaldirilan_varsayilanlar"]}


def ekle(yol, ekleyen, yalnizca_yeniler):
    """Klasoru ekler (zaten ekliyse gunceller). yalnizca_yeniler: mevcut dosyalar alinmaz."""
    yol = os.path.abspath(str(yol))
    with _kilit:
        veri = oku()
        veri["klasorler"] = [k for k in veri["klasorler"] if normal(k["yol"]) != normal(yol)]
        veri["klasorler"].append({
            "yol": yol,
            "baslangic": time.time() if yalnizca_yeniler else None,
            "ekleyen": ekleyen,
            "eklenme": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        # Daha once kaldirilmis bir varsayilan klasorse yeniden izlenir.
        veri["kaldirilan_varsayilanlar"] = [y for y in veri["kaldirilan_varsayilanlar"] if normal(y) != normal(yol)]
        _yaz(veri)
    log.info("Izlenen klasor eklendi: %s (%s, %s)", yol, ekleyen, "yalnizca yeniler" if yalnizca_yeniler else "hepsi")


def kaldir(yol, varsayilan_mi, kaldiran):
    """Eklenen klasoru siler; varsayilan klasoru kaldirilanlar listesine yazar."""
    with _kilit:
        veri = oku()
        veri["klasorler"] = [k for k in veri["klasorler"] if normal(k["yol"]) != normal(yol)]
        if varsayilan_mi and normal(yol) not in {normal(y) for y in veri["kaldirilan_varsayilanlar"]}:
            veri["kaldirilan_varsayilanlar"].append(os.path.abspath(str(yol)))
        _yaz(veri)
    log.info("Izlenen klasor kaldirildi: %s (%s)", yol, kaldiran)
