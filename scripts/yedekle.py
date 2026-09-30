"""Veritabaninin tarihli yedegini alir (pg_dump) ve en son N yedegi tutar.

Yerel modda yedekleme kurumun sorumlulugundadir; bu betik Windows Gorev
Zamanlayici ile her gun calistirilir (docs/KURULUM_KURUM.md). Yedek
DATABASE_URL'deki veritabanindan pg_dump'in "custom" bicimiyle alinir
(sikistirilmis; pg_restore ile geri yuklenir). Belgeler yedekte de sifrelidir:
ENCRYPTION_KEY olmadan yedek acilamaz, anahtar ayrica saklanmalidir.

Ayarlar (.env):
    YEDEK_KLASORU  yedeklerin yazilacagi klasor (varsayilan: proje/yedekler)
    YEDEK_SAYISI   tutulacak en son yedek sayisi (varsayilan: 14)
    PG_DUMP        pg_dump PATH'te degilse tam yolu
                   (or. C:\\Program Files\\PostgreSQL\\17\\bin\\pg_dump.exe)

Yalnizca bu betigin urettigi adlardaki (arcbase_YYYY-AA-GG_SSDDss.dump)
dosyalar silinir; klasordeki baska dosyalara dokunulmaz. Yarim kalan yedek
.tmp uzantisiyla yazilir ve basarisizlikta silinir. Adres yazdirilmaz.

Kullanim (proje kokunden):
    python scripts/yedekle.py
Geri yukleme (bos bir veritabanina):
    pg_restore --no-owner -d <veritabani_adresi> yedekler\\arcbase_....dump
"""

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJE = Path(__file__).resolve().parent.parent
ONEK = "arcbase_"
UZANTI = ".dump"
AD_KALIBI = re.compile(r"^arcbase_\d{4}-\d{2}-\d{2}_\d{6}\.dump$")
VARSAYILAN_SAYI = 14


class YedekHatasi(RuntimeError):
    """Yedek alinamadi; mesaj kullaniciya gosterilir (adres icermez)."""


def pg_dump_yolu():
    yol = (os.getenv("PG_DUMP") or "").strip() or shutil.which("pg_dump")
    if not yol or not Path(yol).exists():
        raise YedekHatasi(
            "pg_dump bulunamadı. PostgreSQL'in bin klasörünü PATH'e ekleyin ya da "
            ".env'de PG_DUMP ile tam yolunu verin."
        )
    return yol


def yedek_adi(zaman=None):
    return f"{ONEK}{(zaman or datetime.now()).strftime('%Y-%m-%d_%H%M%S')}{UZANTI}"


def eski_yedekleri_sil(klasor, tutulacak):
    """En yeni `tutulacak` yedek disindakileri siler; silinenleri dondurur.
    Ad tarih icerdigi icin alfabetik sira kronolojik siradir."""
    yedekler = sorted(p for p in Path(klasor).iterdir() if p.is_file() and AD_KALIBI.match(p.name))
    silinecek = yedekler[: max(len(yedekler) - tutulacak, 0)]
    for yol in silinecek:
        yol.unlink()
    return silinecek


def yedekle(adres, klasor, tutulacak=VARSAYILAN_SAYI, pg_dump=None, zaman=None):
    """Yedegi alir, eskileri temizler; (yedek_yolu, silinenler) dondurur."""
    if not adres:
        raise YedekHatasi("DATABASE_URL tanımlı değil.")
    if tutulacak < 1:
        raise YedekHatasi("YEDEK_SAYISI en az 1 olmalı.")
    klasor = Path(klasor)
    klasor.mkdir(parents=True, exist_ok=True)
    hedef = klasor / yedek_adi(zaman)
    gecici = hedef.with_name(hedef.name + ".tmp")
    komut = [pg_dump or pg_dump_yolu(), "--format=custom", "--no-owner", f"--file={gecici}", f"--dbname={adres}"]
    try:
        sonuc = subprocess.run(komut, capture_output=True, text=True)
    except OSError as hata:
        raise YedekHatasi(f"pg_dump çalıştırılamadı: {hata}") from hata
    if sonuc.returncode != 0 or not gecici.exists() or gecici.stat().st_size == 0:
        gecici.unlink(missing_ok=True)
        # pg_dump'in mesajinda adres (sifre) gecebilir; yazdirilmadan once gizlenir.
        mesaj = (sonuc.stderr or "").replace(adres, "<DATABASE_URL>").strip()
        raise YedekHatasi(f"pg_dump başarısız oldu (çıkış kodu {sonuc.returncode}). {mesaj}")
    gecici.replace(hedef)
    return hedef, eski_yedekleri_sil(klasor, tutulacak)


def main():
    load_dotenv(PROJE / ".env")
    klasor = (os.getenv("YEDEK_KLASORU") or "").strip() or PROJE / "yedekler"
    try:
        sayi = int(os.getenv("YEDEK_SAYISI") or VARSAYILAN_SAYI)
        yol, silinen = yedekle(os.getenv("DATABASE_URL"), klasor, sayi)
    except (YedekHatasi, ValueError) as hata:
        print(f"HATA: {hata}", file=sys.stderr, flush=True)
        return 1
    print(f"Yedek alındı: {yol} ({yol.stat().st_size / 1024 / 1024:.1f} MB)")
    if silinen:
        print(f"{len(silinen)} eski yedek silindi (en son {sayi} yedek tutulur).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
