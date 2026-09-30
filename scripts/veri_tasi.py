"""Kullanicilari ve belgeleri bir PostgreSQL veritabanindan digerine kopyalar
(bulut modundan yerel moda gecis: Neon -> kurumun yerel PostgreSQL'i).

Kaynak varsayilan olarak DATABASE_URL, hedef YEREL_DATABASE_URL'dir (.env).
Sifreli icerik oldugu gibi tasinir, cozulmez: hedefte calisacak uygulamanin
AYNI ENCRYPTION_KEY'i kullanmasi gerekir. Betik anahtarin kaynaktaki bir
belgeyi cozebildigini denetler.

Adimlar:
1. Hedefte sema yoksa olusturulur (uygulamanin kendi semasi, database.sema_sql).
2. Iki taraftaki kullanici/belge sayilari gosterilir. Hedef bos degilse
   betik durur (var olan kayitlarin uzerine yazilmaz, hicbir sey silinmez).
3. Onay istenir ("evet").
4. Kayitlar id'leriyle birlikte tek islemde (transaction) kopyalanir, id
   sayaclari ilerletilir.
5. Dogrulama: satir sayilari ve her kaydin icerik ozeti (md5) iki tarafta
   karsilastirilir. Uyusmazsa islem geri alinir, hedef bos kalir.

Tasima sirasinda eski uygulamaya yeni belge yuklenmemelidir; tasimadan
sonra yuklenenler hedefe gecmez. Adresler ve anahtarlar yazdirilmaz.

Kullanim (proje kokunden):
    python scripts/veri_tasi.py
    python scripts/veri_tasi.py --kaynak DATABASE_URL --hedef YEREL_DATABASE_URL
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

PROJE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJE))

import crypto  # noqa: E402
import database  # noqa: E402

# Kopyalama sirasi yabanci anahtarlara uyar: once kullanicilar.
TABLOLAR = ("kullanicilar", "belgeler")
PARTI = 50  # belgeler bu kadarlik partilerle okunur (bellekte az icerik tutulur)

# Dogrulamada karsilastirilan ozet: her satirin tum sutunlari (bytea dahil)
# metne cevrilip md5'lenir, id sirasiyla birlestirilir.
_OZET_SQL = "SELECT COUNT(*) AS adet, md5(string_agg(md5(t::text), ',' ORDER BY t.id)) AS ozet FROM (SELECT {sutunlar} FROM {tablo}) AS t"


class TasimaHatasi(RuntimeError):
    """Tasima baslamadi ya da geri alindi; mesaj kullaniciya gosterilir."""


def _kimlik(adres):
    """(sunucu, port, veritabani, options). options (or. search_path) farkli
    semalari ayirir; testler ayni veritabaninda iki sema kullanir."""
    parca = urlsplit(adres.strip())
    sunucu = (parca.hostname or "").lower()
    if sunucu in ("", "127.0.0.1", "::1"):
        sunucu = "localhost"
    secenek = parse_qs(parca.query).get("options", [""])[0]
    return sunucu, parca.port or 5432, unquote(parca.path.lstrip("/")), secenek


def ayni_veritabani(a, b):
    return a.strip() == b.strip() or _kimlik(a) == _kimlik(b)


def _baglan(adres, ad):
    try:
        baglanti = psycopg2.connect(adres, cursor_factory=psycopg2.extras.RealDictCursor)
    except psycopg2.OperationalError as hata:
        raise TasimaHatasi(f"{ad} veritabanına bağlanılamadı: {hata}") from hata
    # Dogrulama ozeti satirlarin metin halinden cikar; iki sunucunun ayarlari
    # (tarih bicimi vb.) farkli olsa da ayni veri ayni metni versin.
    # JSON(B) degerleri cozumlenmeden metin olarak okunur; hedefe aynen yazilir.
    psycopg2.extras.register_default_json(baglanti, loads=lambda metin: metin)
    psycopg2.extras.register_default_jsonb(baglanti, loads=lambda metin: metin)
    baglanti.autocommit = True
    with baglanti.cursor() as imlec:
        imlec.execute("SET DateStyle = 'ISO, YMD'; SET bytea_output = 'hex'; SET extra_float_digits = 1")
    baglanti.autocommit = False
    return baglanti


def _tablo_var(baglanti, tablo):
    with baglanti.cursor() as imlec:
        imlec.execute("SELECT to_regclass(%s) IS NOT NULL AS var", (tablo,))
        return imlec.fetchone()["var"]


def _sutunlar(baglanti, tablo):
    with baglanti.cursor() as imlec:
        imlec.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
            (tablo,),
        )
        return [s["column_name"] for s in imlec.fetchall()]


def _sayilar(baglanti):
    sonuc = {}
    with baglanti.cursor() as imlec:
        for tablo in TABLOLAR:
            if _tablo_var(baglanti, tablo):
                imlec.execute(f"SELECT COUNT(*) AS adet FROM {tablo}")
                sonuc[tablo] = imlec.fetchone()["adet"]
            else:
                sonuc[tablo] = 0
        if _tablo_var(baglanti, "belgeler"):
            imlec.execute(
                "SELECT COALESCE(SUM(octet_length(sifreli_icerik) + "
                "COALESCE(octet_length(sifreli_onizleme), 0)), 0) AS bayt FROM belgeler"
            )
            sonuc["bayt"] = int(imlec.fetchone()["bayt"])
        else:
            sonuc["bayt"] = 0
    return sonuc


def _anahtar_denetimi(kaynak):
    """ENCRYPTION_KEY kaynaktaki bir belgeyi cozebiliyor mu? Belge yoksa None."""
    if not _tablo_var(kaynak, "belgeler"):
        return None
    with kaynak.cursor() as imlec:
        imlec.execute("SELECT sifreli_icerik FROM belgeler ORDER BY id LIMIT 1")
        satir = imlec.fetchone()
    if satir is None:
        return None
    try:
        crypto.coz(satir["sifreli_icerik"])
    except crypto.SifrelemeHatasi:
        return False
    return True


def _kopyala(kaynak, hedef, tablo, sutunlar):
    liste = ", ".join(sutunlar)
    adet = 0
    with kaynak.cursor(name=f"tasi_{tablo}") as okuyucu, hedef.cursor() as yazici:
        okuyucu.itersize = PARTI
        okuyucu.execute(f"SELECT {liste} FROM {tablo} ORDER BY id")
        while satirlar := okuyucu.fetchmany(PARTI):
            psycopg2.extras.execute_values(
                yazici,
                f"INSERT INTO {tablo} ({liste}) VALUES %s",
                [tuple(s[sutun] for sutun in sutunlar) for s in satirlar],
            )
            adet += len(satirlar)
    # Yeni kayitlar tasinan id'lerin ustunden devam etsin.
    with hedef.cursor() as yazici:
        yazici.execute(
            f"SELECT setval(pg_get_serial_sequence('{tablo}', 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {tablo}"
        )
    return adet


def _ozet(baglanti, tablo, sutunlar):
    with baglanti.cursor() as imlec:
        imlec.execute(_OZET_SQL.format(sutunlar=", ".join(sutunlar), tablo=tablo))
        satir = imlec.fetchone()
        return satir["adet"], satir["ozet"]


def _yaz(mesaj=""):
    print(mesaj, flush=True)


def _mb(bayt):
    return f"{bayt / 1024 / 1024:.1f} MB"


def tasi(kaynak_adres, hedef_adres, onayla=None, yaz=_yaz):
    """Tasimayi yapar; tasinan {tablo: adet} dondurur. onayla(ozet_metni) ->
    bool; False donerse hicbir sey kopyalanmaz ve None doner."""
    if not kaynak_adres or not hedef_adres:
        raise TasimaHatasi("Kaynak ve hedef veritabanı adresleri tanımlı olmalı.")
    if ayni_veritabani(kaynak_adres, hedef_adres):
        raise TasimaHatasi("Kaynak ve hedef aynı veritabanını gösteriyor.")

    kaynak = _baglan(kaynak_adres, "Kaynak")
    hedef = _baglan(hedef_adres, "Hedef")
    try:
        # Kaynak tek bir anlik goruntuden okunur; tasima sirasinda degisse bile
        # kopya ve dogrulama ayni veriyi gorur. Kaynaga hicbir sey yazilmaz.
        kaynak.set_session(isolation_level="REPEATABLE READ", readonly=True)
        if not _tablo_var(kaynak, "kullanicilar"):
            raise TasimaHatasi("Kaynak veritabanında ArcBase tabloları yok.")

        with hedef.cursor() as imlec:
            imlec.execute(database.sema_sql())
        hedef.commit()

        kaynak_sayi, hedef_sayi = _sayilar(kaynak), _sayilar(hedef)
        yaz("Kaynak: {kullanicilar} kullanıcı, {belgeler} belge".format(**kaynak_sayi) + f" ({_mb(kaynak_sayi['bayt'])})")
        yaz("Hedef:  {kullanicilar} kullanıcı, {belgeler} belge".format(**hedef_sayi))
        if hedef_sayi["kullanicilar"] or hedef_sayi["belgeler"]:
            raise TasimaHatasi(
                "Hedef veritabanı boş değil; var olan kayıtların üzerine yazılmaz. "
                "Taşıma yalnızca boş bir veritabanına yapılır."
            )

        anahtar = _anahtar_denetimi(kaynak)
        if anahtar is False:
            raise TasimaHatasi(
                "ENCRYPTION_KEY kaynaktaki belgeleri çözemiyor. Taşınan belgeleri açabilmek için "
                ".env'deki anahtar kaynak uygulamanınkiyle aynı olmalı."
            )
        if anahtar:
            yaz("ENCRYPTION_KEY kaynaktaki belgeleri çözebiliyor (aynı anahtar hedefte de kullanılmalı).")

        if onayla is not None and not onayla(
            f"{kaynak_sayi['kullanicilar']} kullanıcı ve {kaynak_sayi['belgeler']} belge hedefe kopyalanacak."
        ):
            yaz("Vazgeçildi, hiçbir şey kopyalanmadı.")
            return None

        tasinan = {}
        for tablo in TABLOLAR:
            if not _tablo_var(kaynak, tablo):
                continue
            hedef_sutunlar = set(_sutunlar(hedef, tablo))
            sutunlar = [s for s in _sutunlar(kaynak, tablo) if s in hedef_sutunlar]
            tasinan[tablo] = _kopyala(kaynak, hedef, tablo, sutunlar)
            yaz(f"{tablo}: {tasinan[tablo]} kayıt kopyalandı, doğrulanıyor...")
            if _ozet(kaynak, tablo, sutunlar) != _ozet(hedef, tablo, sutunlar):
                raise TasimaHatasi(f"Doğrulama başarısız ({tablo}): kaynak ile hedef farklı. İşlem geri alındı.")
        hedef.commit()
        yaz("Doğrulama başarılı: tüm kayıtlar birebir aynı. Taşıma tamamlandı.")
        return tasinan
    except BaseException:
        hedef.rollback()
        raise
    finally:
        kaynak.close()
        hedef.close()


def _konsol_onayi(ozet):
    _yaz(ozet)
    cevap = input('Devam etmek için "evet" yazın: ').strip().lower()
    return cevap == "evet"


def main(argv=None):
    ayar = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ayar.add_argument("--kaynak", default="DATABASE_URL", help="kaynak adresin .env'deki adı (varsayılan: DATABASE_URL)")
    ayar.add_argument("--hedef", default="YEREL_DATABASE_URL", help="hedef adresin .env'deki adı (varsayılan: YEREL_DATABASE_URL)")
    secim = ayar.parse_args(argv)

    load_dotenv(PROJE / ".env")
    kaynak, hedef = os.getenv(secim.kaynak), os.getenv(secim.hedef)
    for ad, deger in ((secim.kaynak, kaynak), (secim.hedef, hedef)):
        if not deger:
            _yaz(f"HATA: {ad} .env'de tanımlı değil.")
            return 2
    _yaz(f"Kaynak: {secim.kaynak}  ->  Hedef: {secim.hedef}")
    try:
        sonuc = tasi(kaynak, hedef, onayla=_konsol_onayi)
    except (TasimaHatasi, crypto.SifrelemeHatasi) as hata:
        _yaz(f"HATA: {hata}")
        return 1
    return 0 if sonuc is not None else 3


if __name__ == "__main__":
    sys.exit(main())
