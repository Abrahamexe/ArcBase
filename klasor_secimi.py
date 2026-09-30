"""Tarayicinin kaydettigi klasoru bulma ve secme (sunucu bilgisayarinda).

"Taradigim belgeler gorunmuyor": kullanici tarayicisiyla bir sayfa tarar;
Belgeler, Resimler, Masaustu ve Indirilenler (alt klasorleriyle) icinde son
SON_DOSYA_SN'de olusan gorsel/PDF dosyalari bulunur (son_dosyalari_bul) ve
onizlemeleriyle gosterilir. Onaylanan dosyanin klasoru izlenen klasorlere
eklenir (izlenen_klasorler.py).

"Klasoru kendim secegim": sunucu bilgisayarinin suruculeri ve klasorleri
gezilir (klasoru_listele).

Guvenlik: bu ozellikler yalnizca yoneticiye ya da ArcBase'in calistigi
bilgisayarin kendisinden (127.0.0.1 / ::1) gelen istege aciktir (app.py:
_klasor_yonetimi_izinli). Windows sistem klasorleri (Windows, Program Files,
ProgramData, AppData, Geri Donusum Kutusu ...) ve gizli/sistem klasorleri
listelenmez, aranmaz ve eklenemez. Onizleme yalnizca aramada bulunan dosyalar
icin, kullaniciya verilen gecici bir anahtarla yapilir (istemci yol gondermez).
"""

import io
import os
import secrets
import stat
import string
import sys
import threading
import time
from pathlib import Path

import klasor_izleme

SON_DOSYA_SN = 120  # "son 2 dakikada olusan"
ARAMA_DERINLIGI = 5  # bilinen klasorlerin altinda en fazla bu kadar seviye
ARAMA_KLASOR_SINIRI = 5000  # aramada en fazla bu kadar klasor gezilir
SONUC_SINIRI = 12
ONIZLEME_OMRU_SN = 15 * 60
ONIZLEME_BOYUTU = (360, 480)

ARAMA_KLASORLERI = (("belgeler", "Belgeler"), ("resimler", "Resimler"), ("masaustu", "Masaüstü"),
                    ("indirilenler", "İndirilenler"))

# Surucu kokundeki sistem klasorleri ve her yerde gizlenen klasorler (kucuk harf).
KOKTE_YASAK = {
    "windows", "program files", "program files (x86)", "programdata", "$recycle.bin",
    "system volume information", "recovery", "perflogs", "config.msi", "$winreagent", "boot",
    "msocache", "documents and settings", "$windows.~bt", "$windows.~ws", "intel", "drivers",
}
HER_YERDE_YASAK = {"appdata", "$recycle.bin", "system volume information", "windowsapps", "node_modules", ".git"}
# Unix'te (gelistirme) kokteki sistem klasorleri
UNIX_KOKTE_YASAK = {"proc", "sys", "dev", "etc", "usr", "bin", "sbin", "lib", "lib64", "boot", "var", "run", "snap"}


class KlasorHatasi(Exception):
    """Kullaniciya gosterilecek sade mesaj."""


# ---------------------------------------------------------------- sistem klasorleri

def _sistem_yollari():
    """Ortam degiskenlerinden bilinen sistem klasorleri (surucu farketmeksizin)."""
    adlar = ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData",
             "LOCALAPPDATA", "APPDATA")
    return {os.path.normcase(os.path.abspath(os.environ[a])) for a in adlar if os.environ.get(a)}


def yasak_mi(yol):
    """Sistem klasoru mu (ya da altinda mi)? Bu klasorler listelenmez ve eklenemez."""
    yol = Path(os.path.abspath(str(yol)))
    parcalar = [p.lower() for p in yol.parts]
    if any(p in HER_YERDE_YASAK for p in parcalar[1:]):
        return True
    if len(parcalar) > 1 and parcalar[1] in (KOKTE_YASAK if sys.platform == "win32" else UNIX_KOKTE_YASAK):
        return True
    normal = os.path.normcase(str(yol))
    return any(normal == s or normal.startswith(s.rstrip("\\/") + os.sep) for s in _sistem_yollari())


def _gizli_mi(girdi):
    """os.DirEntry gizli ya da sistem klasoru mu?"""
    if girdi.name.startswith((".", "$", "~")):
        return True
    try:
        nitelik = getattr(girdi.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(nitelik & (getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2) | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 4)))


def _gezilebilir(girdi):
    try:
        return girdi.is_dir(follow_symlinks=False) and not _gizli_mi(girdi) and not yasak_mi(girdi.path)
    except OSError:
        return False


# ---------------------------------------------------------------- gezinme

def suruculer():
    """Bu bilgisayarin suruculeri: [{"ad", "yol"}]."""
    if sys.platform != "win32":
        return [{"ad": "/", "yol": "/"}]
    try:
        import ctypes

        maske = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        maske = (1 << 26) - 1
    liste = []
    for sira, harf in enumerate(string.ascii_uppercase):
        yol = f"{harf}:\\"
        if maske & (1 << sira) and harf not in "AB" and os.path.isdir(yol):
            liste.append({"ad": f"{harf}:", "yol": yol})
    return liste


def kisayollar():
    """Kullanicinin Belgeler, Resimler, Masaustu, Indirilenler klasorleri (var olanlar)."""
    liste = []
    for anahtar, ad in ARAMA_KLASORLERI:
        for yol in klasor_izleme._bilinen_klasor(anahtar):
            if yol.is_dir():
                liste.append({"ad": ad, "yol": str(yol)})
                break
    return liste


def klasoru_dogrula(yol):
    """Kullanicinin gonderdigi yolu dogrular; mutlak Path ya da KlasorHatasi."""
    if not yol or not os.path.isabs(yol):
        raise KlasorHatasi("Geçerli bir klasör seçin.")
    yol = Path(os.path.abspath(yol))
    if yasak_mi(yol):
        raise KlasorHatasi("Bu bir sistem klasörü; seçilemez.")
    if not yol.is_dir():
        raise KlasorHatasi("Klasör bulunamadı. Silinmiş ya da taşınmış olabilir.")
    return yol


def klasoru_listele(yol=None):
    """{"yol", "ust", "klasorler": [{"ad", "yol"}], "suruculer", "kisayollar"}.
    yol bossa suruculer ve kisayollar listelenir (baslangic ekrani)."""
    if not yol:
        return {"yol": None, "ust": None, "klasorler": [], "suruculer": suruculer(), "kisayollar": kisayollar()}
    klasor = klasoru_dogrula(yol)
    try:
        girdiler = [g for g in os.scandir(klasor) if _gezilebilir(g)]
    except PermissionError as hata:
        raise KlasorHatasi("Bu klasörü açma izni yok.") from hata
    except OSError as hata:
        raise KlasorHatasi("Klasör açılamadı.") from hata
    ust = klasor.parent if klasor.parent != klasor else None
    return {
        "yol": str(klasor),
        "ust": str(ust) if ust is not None and not yasak_mi(ust) else "",  # "": suruculere don
        "klasorler": [{"ad": g.name, "yol": g.path} for g in sorted(girdiler, key=lambda g: g.name.lower())],
        "suruculer": [],
        "kisayollar": [],
    }


# ---------------------------------------------------------------- son taranan dosyayi bulma

def arama_kokleri():
    kokler = []
    for anahtar, _ad in ARAMA_KLASORLERI:
        for yol in klasor_izleme._bilinen_klasor(anahtar):
            if yol.is_dir() and yol not in kokler:
                kokler.append(yol)
    return kokler


def son_dosyalari_bul(kokler=None, sure_sn=SON_DOSYA_SN, simdi=None):
    """Koklerin altinda son sure_sn'de olusan gorsel/PDF dosyalari, en yenisi
    once: [{"yol", "ad", "klasor", "zaman"}]. ArcBase'in kendi aktarim
    klasorleri, gizli ve sistem klasorleri atlanir; gezinti sinirlidir."""
    simdi = time.time() if simdi is None else simdi
    sinir = simdi - sure_sn
    bulunan, gezilen = [], 0
    yigin = [(Path(k), 0) for k in (kokler if kokler is not None else arama_kokleri())]
    while yigin and gezilen < ARAMA_KLASOR_SINIRI:
        klasor, derinlik = yigin.pop()
        gezilen += 1
        try:
            girdiler = list(os.scandir(klasor))
        except OSError:
            continue
        for girdi in girdiler:
            try:
                if girdi.is_dir(follow_symlinks=False):
                    if (derinlik < ARAMA_DERINLIGI and girdi.name.lower() not in klasor_izleme.AYRILMIS_KLASORLER
                            and _gezilebilir(girdi)):
                        yigin.append((Path(girdi.path), derinlik + 1))
                elif (Path(girdi.name).suffix.lower() in klasor_izleme.TURLER
                      and not klasor_izleme.yoksayilir_mi(Path(girdi.name))):
                    zaman = klasor_izleme._olusma_zamani(girdi.stat())
                    if sinir <= zaman <= simdi + 5:
                        bulunan.append({"yol": girdi.path, "ad": girdi.name, "klasor": str(klasor), "zaman": zaman})
            except OSError:
                continue
    bulunan.sort(key=lambda d: d["zaman"], reverse=True)
    return bulunan[:SONUC_SINIRI]


# ---------------------------------------------------------------- onizleme anahtarlari

class OnizlemeAnahtarlari:
    """Aramada bulunan dosyalar icin kullaniciya ozel gecici anahtarlar:
    istemci dosya yolu gondermez, yalnizca bu anahtari."""

    def __init__(self, omur_sn=ONIZLEME_OMRU_SN, saat=time.monotonic):
        self.omur_sn = omur_sn
        self.saat = saat
        self._kilit = threading.Lock()
        self._kayitlar = {}  # anahtar -> (kullanici_id, yol, zaman)

    def ver(self, kullanici_id, yol):
        anahtar = secrets.token_urlsafe(16)
        with self._kilit:
            sinir = self.saat() - self.omur_sn
            self._kayitlar = {a: k for a, k in self._kayitlar.items() if k[2] >= sinir}
            self._kayitlar[anahtar] = (kullanici_id, str(yol), self.saat())
        return anahtar

    def yol(self, kullanici_id, anahtar):
        """Anahtarin dosya yolu; yoksa, suresi dolduysa ya da baska kullanicininsa None."""
        with self._kilit:
            kayit = self._kayitlar.get(anahtar or "")
        if not kayit or kayit[0] != kullanici_id or kayit[2] < self.saat() - self.omur_sn:
            return None
        return Path(kayit[1])


anahtarlar = OnizlemeAnahtarlari()


def onizleme_uret(yol):
    """Dosyanin kucuk JPEG onizlemesi (PDF'in ilk sayfasi); uretilemezse KlasorHatasi."""
    from PIL import Image

    try:
        if yol.suffix.lower() == ".pdf":
            import pymupdf

            with pymupdf.open(str(yol)) as pdf:
                pix = pdf[0].get_pixmap(dpi=50)
                gorsel = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        else:
            gorsel = Image.open(yol)
            gorsel.draft("RGB", ONIZLEME_BOYUTU)
            gorsel = gorsel.convert("RGB")
        gorsel.thumbnail(ONIZLEME_BOYUTU)
        tampon = io.BytesIO()
        gorsel.save(tampon, "JPEG", quality=80)
        return tampon.getvalue()
    except Exception as hata:
        raise KlasorHatasi("Önizleme gösterilemiyor.") from hata
