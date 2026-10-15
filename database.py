"""PostgreSQL baglantisi (Neon ya da yerel sunucu) ve belge kayitlari icin sorgular.

Baglanti adresi .env icindeki DATABASE_URL'den okunur ve psycopg2'ye oldugu
gibi verilir: SSL zorunlu tutulmaz, yalnizca adreste (?sslmode=require, Neon)
belirtilirse uygulanir; yerel PostgreSQL SSL'siz calisir. Baglantilar surec
basina bir havuzda tutulur ve istekler arasinda yeniden kullanilir: Neon'a
yeni baglanti (TLS + kimlik dogrulama) bir sorgudan kat kat pahalidir. Bir
sure bosta kalan baglanti kullanilmadan once yoklanir; Neon uykuya gecip
baglantiyi kestiyse atilir ve yenisi acilir. Neon uyanirken ilk baglanti
zaman asimina ugrayabildigi icin baglanti bir kez yeniden denenir.
"""

import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import psycopg2
import psycopg2.errors
import psycopg2.extensions
import psycopg2.extras
from dotenv import load_dotenv

from alanlar import SUTUN_ALANLARI

load_dotenv()

# Havuzda bekletilen en fazla bosta baglanti; fazlasi is bitince kapatilir.
# Ust sinir yoktur: yogunlukta gecici ek baglanti acilir, istek beklemez.
HAVUZ_BOSTA_EN_FAZLA = int(os.getenv("DB_HAVUZ_BOYUTU") or 8)
BOSTA_YOKLAMA_SN = 120  # bu kadar kullanilmamis baglanti once SELECT 1 ile yoklanir

# Arka plan isleme durumlari (belgeler.isleme_durumu).
BEKLIYOR, ISLENIYOR, TAMAMLANDI, HATA = "bekliyor", "isleniyor", "tamamlandi", "hata"
ISLEME_ZAMAN_ASIMI_SN = 180  # "isleniyor" isin kalp atisi bu kadar gecikirse is sahipsiz sayilir

# Tur kodu -> (gorunen ad, ikon, renk sinifi) ; arayuzun tamami bu listeden beslenir.
TURLER = {
    "fatura": {"ad": "Fatura", "ikon": "🧾", "renk": "amber"},
    "sozlesme": {"ad": "Sözleşme", "ikon": "📜", "renk": "indigo"},
    "kimlik": {"ad": "Kimlik", "ikon": "🪪", "renk": "emerald"},
    "dilekce": {"ad": "Dilekçe", "ikon": "✍️", "renk": "sky"},
    "resmi_yazi": {"ad": "Resmi Yazı", "ikon": "🏛️", "renk": "rose"},
    "diger": {"ad": "Diğer", "ikon": "📄", "renk": "slate"},
}

VARSAYILAN_TUR = "diger"
DUSUK_GUVEN_SINIRI = 0.6


class VeritabaniHatasi(RuntimeError):
    """Baglanti kurulamadi ya da sorgu calistirilamadi."""


def _baglanti_adresi():
    adres = os.getenv("DATABASE_URL")
    if not adres:
        raise VeritabaniHatasi(
            "DATABASE_URL tanımlı değil. Veritabanı bağlantı adresini .env dosyasına ekleyin."
        )
    return adres


def baglanti_ac():
    """Sozluk benzeri satirlar donduren yeni bir PostgreSQL baglantisi acar.

    Neon uykudan uyanirken ilk deneme zaman asimina ugrayabiliyor; bu yuzden
    basarisiz olan ilk denemeden sonra kisa bir bekleyip bir kez daha denenir.
    """
    adres = _baglanti_adresi()
    son_hata = None
    for deneme in range(2):
        try:
            baglanti = psycopg2.connect(
                adres, cursor_factory=psycopg2.extras.RealDictCursor
            )
            # Her sorgu tek komuttur ve kendi basina atomiktir; ayri BEGIN/COMMIT
            # gidis-donusleri (uzak veritabaninda her biri yuzlerce ms) gerekmez.
            baglanti.autocommit = True
            return baglanti
        except psycopg2.OperationalError as hata:
            son_hata = hata
            if deneme == 0:
                time.sleep(2)  # Neon'un uyanmasi icin kisa bekleme
    raise VeritabaniHatasi(f"Veritabanına bağlanılamadı: {son_hata}") from son_hata


class _Havuz:
    """Is parcacigi guvenli, basit baglanti havuzu.

    psycopg2'nin ThreadedConnectionPool'u dolunca hata firlatir ve bayat
    baglantiyi ayirt etmez; burada bosta baglanti yoksa yenisi acilir, uzun
    sure bosta kalan baglanti verilmeden once yoklanir."""

    def __init__(self):
        self._bosta = []  # (baglanti, son kullanim zamani)
        self._kilit = threading.Lock()
        self._pid = os.getpid()

    def al(self):
        """(baglanti, yeni_mi) dondurur."""
        while True:
            with self._kilit:
                if self._pid != os.getpid():
                    # fork edilmis surec: ust surecin baglantilari paylasilamaz
                    self._bosta, self._pid = [], os.getpid()
                oge = self._bosta.pop() if self._bosta else None
            if oge is None:
                return baglanti_ac(), True
            baglanti, zaman = oge
            if baglanti.closed:
                continue
            if time.monotonic() - zaman > BOSTA_YOKLAMA_SN:
                try:
                    with baglanti.cursor() as imlec:
                        imlec.execute("SELECT 1")
                except psycopg2.Error:
                    _kapat(baglanti)
                    continue
            return baglanti, False

    def birak(self, baglanti, bozuk=False):
        temiz = (
            not bozuk
            and not baglanti.closed
            and baglanti.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_IDLE
        )
        if temiz:
            with self._kilit:
                if self._pid == os.getpid() and len(self._bosta) < HAVUZ_BOSTA_EN_FAZLA:
                    self._bosta.append((baglanti, time.monotonic()))
                    return
        _kapat(baglanti)

    def bosalt(self):
        with self._kilit:
            bosta, self._bosta = self._bosta, []
        for baglanti, _ in bosta:
            _kapat(baglanti)


def _kapat(baglanti):
    try:
        baglanti.close()
    except psycopg2.Error:
        pass


_havuz = _Havuz()


def _sorgula(sql, parametreler=(), tek=False, hepsi=False):
    """Tek noktadan sorgu calistirir. Baglanti autocommit'tir: her cagri tek
    bir SQL komutudur (birden fazla komut iceren metin sunucuda tek islem
    olarak calisir), ek BEGIN/COMMIT gidis-donusu olmaz.

    Havuzdan alinan baglanti bu arada kopmussa (Neon uykuya gecti, ag kesildi)
    sorgu yeni bir baglantiyla bir kez daha denenir. Kopuk baglantida sorgu
    sunucuya ulasmadigi icin tekrar guvenlidir."""
    for deneme in range(2):
        baglanti, yeni = _havuz.al()
        try:
            with baglanti.cursor() as imlec:
                imlec.execute(sql, parametreler)
                if tek:
                    sonuc = imlec.fetchone()
                elif hepsi:
                    sonuc = imlec.fetchall()
                else:
                    sonuc = None
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            _havuz.birak(baglanti, bozuk=True)
            if yeni or deneme:
                raise
            continue
        except BaseException:
            _havuz.birak(baglanti)
            raise
        _havuz.birak(baglanti)
        return sonuc


def veritabanini_hazirla():
    """Tablolar ve indeksler yoksa olusturur. Uygulama acilisinda bir kez cagrilir.

    Tum komutlar tek seferde gonderilir: uzak veritabaninda her komut ayri bir
    gidis-donus (~yuzlerce ms) demektir. Cok komutlu sorgu tek islemde calisir;
    bastaki kilit ayni anda acilan sureclerin (gunicorn worker, paralel testler)
    ALTER TABLE'larinin birbirini kilitlemesini (deadlock) onler."""
    _sorgula(sema_sql())


def sema_sql():
    """Semayi olusturan/genisleten SQL (veri tasima betigi de hedefte kullanir)."""
    ekle = ", ".join(f"ADD COLUMN IF NOT EXISTS {sutun}" for sutun in _EKLENEN_SUTUNLAR)
    kullanici_ekle = ", ".join(f"ADD COLUMN IF NOT EXISTS {sutun}" for sutun in _KULLANICI_SUTUNLARI)
    return f"""
        SELECT pg_advisory_xact_lock(4172026);
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id               SERIAL PRIMARY KEY,
            kullanici_adi    TEXT NOT NULL UNIQUE,
            sifre_hash       TEXT NOT NULL,
            olusturma_tarihi TIMESTAMP NOT NULL DEFAULT NOW()
        );
        -- "Ahmet" ile "ahmet" ayni kullanici sayilsin diye benzersizlik
        -- kucuk harfe cevrilmis ad uzerinden de saglanir.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_kullanicilar_ad_kucuk
            ON kullanicilar (LOWER(kullanici_adi));
        ALTER TABLE kullanicilar {kullanici_ekle};
        CREATE TABLE IF NOT EXISTS belgeler (
            id               SERIAL PRIMARY KEY,
            kullanici_id     INTEGER NOT NULL
                             REFERENCES kullanicilar(id) ON DELETE CASCADE,
            dosya_adi        TEXT NOT NULL,
            mime_type        TEXT NOT NULL,
            sifreli_icerik   BYTEA NOT NULL,
            sifreli_onizleme BYTEA,
            ocr_metni        TEXT,
            tur              TEXT NOT NULL DEFAULT 'diger',
            guven            REAL,
            aciklama         TEXT,
            elle_duzeltildi  BOOLEAN NOT NULL DEFAULT FALSE,
            yuklenme_tarihi  TIMESTAMP NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_belgeler_kullanici_tur ON belgeler(kullanici_id, tur);
        -- v4+: tablolar gercek veri icerdigi icin sema yalnizca eklenerek
        -- genisletilir; hicbir tablo silinmez ya da yeniden olusturulmaz.
        ALTER TABLE belgeler {ekle};
        CREATE INDEX IF NOT EXISTS idx_belgeler_kullanici_tarih ON belgeler(kullanici_id, belge_tarihi);
        -- Arka plan kuyrugu: yalnizca bekleyen/islenen belgeleri iceren kucuk indeks.
        CREATE INDEX IF NOT EXISTS idx_belgeler_isleme ON belgeler(id)
            WHERE isleme_durumu IN ('{BEKLIYOR}', '{ISLENIYOR}');
        """


_EKLENEN_SUTUNLAR = (
    # v4
    "belge_tarihi DATE",
    "tutar NUMERIC(14,2)",
    "para_birimi TEXT",
    "kurum TEXT",  # firma / kurum / karsi taraf
    "alanlar JSONB",  # ture ozel diger alanlar; NULL = bilgi henuz cikarilmadi
    "alanlar_elle_duzeltildi BOOLEAN NOT NULL DEFAULT FALSE",
    "otomatik_duzeltildi BOOLEAN NOT NULL DEFAULT FALSE",  # OpenCV kirpma/duzeltme
    # v5: gorsellerde duzeltilmemis orijinal + koseler saklanir; duzeltilmis
    # goruntu gosterimde koselerden uretilir (koseler sonradan elle degisebilir).
    "koseler JSONB",  # [[x,y] x4] saklanan gorselin koordinatlarinda; NULL = duzeltme yok
    "orijinal_saklandi BOOLEAN NOT NULL DEFAULT FALSE",  # TRUE: sifreli_icerik duzeltilmemis orijinal
    # v6: arka planda isleme. Mevcut belgeler 'tamamlandi' sayilir. Yuklemede
    # belge 'bekliyor' olarak kaydedilir; isci OCR + siniflandirmayi yapar.
    f"isleme_durumu TEXT NOT NULL DEFAULT '{TAMAMLANDI}'",  # bekliyor | isleniyor | tamamlandi | hata
    # bekliyor: en erken deneme zamani (NULL = hemen); isleniyor: son kalp atisi
    "isleme_zamani TIMESTAMP",
    "isleme_deneme INTEGER NOT NULL DEFAULT 0",  # isin kac kez alindigi (cokme dongusunu keser)
    # asama (goruntu | siniflandirma), duzelt, uyarilar, kirpma_kontrol, groq_deneme, hata
    "isleme_bilgi JSONB",
    # Gorsel/onizleme her degistiginde artar; gorsel onbellegi ve ETag bununla gecersizlesir.
    "icerik_surumu INTEGER NOT NULL DEFAULT 0",
    # v6 (kurum): sahipsiz gelen belge (tarama klasoru) yoneticinin "Gelen
    # belgeler" kutusunda durur; sahibi yoneticidir ama arsivinde (listeler,
    # sayaclar, kota) gorunmez. Ataninca bayrak kalkar.
    "gelen_kutusu BOOLEAN NOT NULL DEFAULT FALSE",
    # Atama kaydi: [{"islem", "yapan_id", "yapan", "kime_id", "kime", "zaman"}]
    "atama_gecmisi JSONB",
)

_KULLANICI_SUTUNLARI = (
    # v6 (kurum): ilk kullanici ya da YONETICI_KULLANICI; "Gelen belgeler"i yonetir.
    "yonetici BOOLEAN NOT NULL DEFAULT FALSE",
)


# ---------------------------------------------------------------- kullanicilar

def kullanici_ekle(kullanici_adi, sifre_hash):
    """Yeni kullanici kaydeder, id'sini dondurur; ad aliniysa None dondurur."""
    try:
        satir = _sorgula(
            "INSERT INTO kullanicilar (kullanici_adi, sifre_hash) "
            "VALUES (%s, %s) RETURNING id",
            (kullanici_adi, sifre_hash),
            tek=True,
        )
    except psycopg2.errors.UniqueViolation:
        return None
    return satir["id"]


def kullanici_getir(kullanici_id):
    """Kullaniciyi id ile getirir, yoksa None dondurur."""
    return _sorgula(
        "SELECT id, kullanici_adi, sifre_hash, olusturma_tarihi, yonetici "
        "FROM kullanicilar WHERE id = %s",
        (kullanici_id,),
        tek=True,
    )


TSI_FARKI = timedelta(hours=3)  # veritabani saati UTC; hafta Turkiye saatine gore baslar

# Bilgisi cikarilmamis (toplu bilgi cikarmanin isleyecegi) belge kosulu.
# Arka planda islenmekte olan belgeleri isci zaten isleyecek.
_BILGISI_EKSIK = (
    "alanlar IS NULL AND NOT alanlar_elle_duzeltildi AND NOT gelen_kutusu "
    f"AND COALESCE(ocr_metni, '') <> '' AND isleme_durumu = '{TAMAMLANDI}'"
)


def hafta_basi():
    """Bu haftanin Pazartesi 00:00'i (Turkiye saati) UTC olarak."""
    simdi = datetime.now(timezone.utc).replace(tzinfo=None) + TSI_FARKI
    pazartesi = simdi.date() - timedelta(days=simdi.weekday())
    return datetime.combine(pazartesi, datetime.min.time()) - TSI_FARKI


def kullanici_ozeti(kullanici_id):
    """Oturumdaki kullanici ve her sayfada gereken sayaclar tek sorguda.

    Her istekte calisir (Flask-Login user_loader); menu sayaclari, kota, "bu
    hafta yuklenen" ve islenen belge sayisi icin ayri sorgu gerekmez. Donen
    satirdaki "sayaclar": sayac_ozeti() bicimi."""
    satir = _sorgula(
        f"""
        SELECT k.id, k.kullanici_adi, k.sifre_hash, k.olusturma_tarihi, k.yonetici,
          (SELECT COALESCE(json_agg(json_build_object('tur', t.tur, 'adet', t.adet, 'son', t.son)), '[]')
             FROM (SELECT tur, COUNT(*) AS adet, MAX(yuklenme_tarihi) AS son
                   FROM belgeler WHERE kullanici_id = k.id AND NOT gelen_kutusu GROUP BY tur) AS t) AS tur_ozeti,
          (SELECT json_build_object(
                    'bu_hafta', COUNT(*) FILTER (WHERE NOT gelen_kutusu AND yuklenme_tarihi >= %s),
                    'isleniyor', COUNT(*) FILTER (WHERE NOT gelen_kutusu AND isleme_durumu IN ('{BEKLIYOR}', '{ISLENIYOR}')),
                    'bilgisi_eksik', COUNT(*) FILTER (WHERE {_BILGISI_EKSIK}),
                    'gelen', COUNT(*) FILTER (WHERE gelen_kutusu))
             FROM belgeler WHERE kullanici_id = k.id) AS genel_ozet
        FROM kullanicilar k WHERE k.id = %s
        """,
        (hafta_basi(), kullanici_id),
        tek=True,
    )
    if satir is None:
        return None
    satir = dict(satir)
    satir["sayaclar"] = sayac_ozeti(satir.pop("tur_ozeti"), satir.pop("genel_ozet"))
    return satir


def sayac_ozeti(tur_satirlari, genel=None):
    """{"turler": {kod: {adet, son_tarih}}, "toplam", "bu_hafta", "isleniyor",
    "bilgisi_eksik", "gelen"}. "gelen": Gelen belgeler kutusundaki (arsive
    sayilmayan) belge sayisi. Hic belgesi olmayan turler de sifirla yer alir; tanimsiz
    tur "diger"e sayilir."""
    turler = {kod: {"adet": 0, "son_tarih": None} for kod in TURLER}
    for satir in tur_satirlari or []:
        kod = satir["tur"] if satir["tur"] in TURLER else VARSAYILAN_TUR
        son = satir.get("son", satir.get("son_tarih"))
        if isinstance(son, str):
            son = datetime.fromisoformat(son)
        turler[kod]["adet"] += satir["adet"]
        mevcut = turler[kod]["son_tarih"]
        if son and (mevcut is None or son > mevcut):
            turler[kod]["son_tarih"] = son
    genel = genel or {}
    return {
        "turler": turler,
        "toplam": sum(t["adet"] for t in turler.values()),
        "bu_hafta": genel.get("bu_hafta", 0),
        "isleniyor": genel.get("isleniyor", 0),
        "bilgisi_eksik": genel.get("bilgisi_eksik", 0),
        "gelen": genel.get("gelen", 0),
    }


def kullanici_adi_ile_getir(kullanici_adi):
    """Kullaniciyi adiyla (buyuk/kucuk harf duyarsiz) getirir."""
    return _sorgula(
        "SELECT id, kullanici_adi, sifre_hash, olusturma_tarihi, yonetici "
        "FROM kullanicilar WHERE LOWER(kullanici_adi) = LOWER(%s)",
        (kullanici_adi,),
        tek=True,
    )


def sifre_guncelle(kullanici_id, sifre_hash):
    _sorgula(
        "UPDATE kullanicilar SET sifre_hash = %s WHERE id = %s",
        (sifre_hash, kullanici_id),
    )


def kullanici_sil(kullanici_id):
    """Kullaniciyi siler; belgeleri ON DELETE CASCADE ile birlikte silinir."""
    _sorgula("DELETE FROM kullanicilar WHERE id = %s", (kullanici_id,))


# ---------------------------------------------------------------- yonetici

def yoneticiyi_belirle(ayar_adi=None):
    """Yonetici: ayar_adi (YONETICI_KULLANICI) verilmis ve bu adda kullanici
    varsa yalnizca o; yoksa (hic yonetici kalmadiysa) ilk olusturulan kullanici.
    Acilista ve her kayittan sonra cagrilir; komutlar tek gidis-donustur."""
    _sorgula(
        """
        UPDATE kullanicilar SET yonetici = (LOWER(kullanici_adi) = LOWER(%(ad)s))
        WHERE EXISTS (SELECT 1 FROM kullanicilar WHERE LOWER(kullanici_adi) = LOWER(%(ad)s))
          AND yonetici IS DISTINCT FROM (LOWER(kullanici_adi) = LOWER(%(ad)s));
        UPDATE kullanicilar SET yonetici = TRUE
        WHERE id = (SELECT MIN(id) FROM kullanicilar)
          AND NOT EXISTS (SELECT 1 FROM kullanicilar WHERE yonetici);
        -- Yonetici degistiyse eskisinin Gelen belgeler kutusu yenisine gecer.
        UPDATE belgeler SET kullanici_id = (SELECT MIN(id) FROM kullanicilar WHERE yonetici)
        WHERE gelen_kutusu AND EXISTS (SELECT 1 FROM kullanicilar WHERE yonetici)
          AND kullanici_id NOT IN (SELECT id FROM kullanicilar WHERE yonetici);
        """,
        {"ad": (ayar_adi or "").strip()},
    )


def yonetici_getir():
    """Gelen belgelerin sahibi olacak yonetici (birden fazlaysa ilk olusturulan)."""
    return _sorgula(
        "SELECT id, kullanici_adi FROM kullanicilar WHERE yonetici ORDER BY id LIMIT 1", tek=True
    )


def kullanicilari_listele():
    """Atama listesi icin kullanici adlari (belge bilgisi icermez)."""
    return _sorgula("SELECT id, kullanici_adi FROM kullanicilar ORDER BY LOWER(kullanici_adi)", hepsi=True)


def gelen_ata(yonetici_id, yonetici_adi, belge_id, hedef_id, hedef_adi, limit):
    """Gelen belgeler kutusundaki belgeyi hedef kullanicinin arsivine tasir ve
    atamayi belgenin atama_gecmisi'ne yazar (kim, kime, ne zaman).

    Donus: "tamam" | "yok" (belge yoneticinin gelen kutusunda degil) | "kota"
    (hedefin arsivi dolu). Kota denetimi ve atama tek sorguda yapilir."""
    kayit = {
        "islem": "atama",
        "yapan_id": yonetici_id,
        "yapan": yonetici_adi,
        "kime_id": hedef_id,
        "kime": hedef_adi,
        "zaman": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
    }
    satir = _sorgula(
        """
        WITH kota AS (
            SELECT COUNT(*) AS adet FROM belgeler WHERE kullanici_id = %(hedef)s AND NOT gelen_kutusu
        )
        UPDATE belgeler SET kullanici_id = %(hedef)s, gelen_kutusu = FALSE,
            atama_gecmisi = COALESCE(atama_gecmisi, '[]'::jsonb) || jsonb_build_array(%(kayit)s::jsonb)
        WHERE id = %(belge)s AND kullanici_id = %(yonetici)s AND gelen_kutusu
          AND (SELECT adet FROM kota) < %(limit)s
        RETURNING id
        """,
        {"hedef": hedef_id, "kayit": psycopg2.extras.Json(kayit), "belge": belge_id,
         "yonetici": yonetici_id, "limit": limit},
        tek=True,
    )
    if satir is not None:
        return "tamam"
    var = _sorgula(
        "SELECT 1 FROM belgeler WHERE id = %s AND kullanici_id = %s AND gelen_kutusu",
        (belge_id, yonetici_id),
        tek=True,
    )
    return "kota" if var else "yok"


# ---------------------------------------------------------------- belgeler
# VERI AYRIMI: Asagidaki her sorgu kullanici_id alir ve WHERE kullanici_id = %s
# icerir. Baska kullanicinin belgesi id ile istense bile bulunamaz (None / 0
# satir); route'lar bunu 404'e cevirir. Bu kuralin istisnasi yoktur.
#
# Gelen belgeler kutusu (gelen_kutusu = TRUE) yoneticiye aittir; yonetici bu
# belgeleri id ile acabilir (goruntu, tur, silme) ama arsiv listeleri, sayaclar
# ve kota onlari icermez. Yonetici baska kullanicilarin belgelerini goremez;
# atama belgenin sahibini degistirir (gelen_ata).

def belge_ekle(
    kullanici_id,
    dosya_adi,
    mime_type,
    sifreli_icerik,
    sifreli_onizleme,
    ocr_metni,
    tur,
    guven,
    aciklama,
    alanlar=None,
    otomatik_duzeltildi=False,
    koseler=None,
    orijinal_saklandi=False,
    isleme_durumu=TAMAMLANDI,
    isleme_bilgi=None,
    gelen_kutusu=False,
):
    """Yeni belgeyi kaydeder ve eklenen kaydin id'sini dondurur.

    alanlar: alanlar.dogrula() ciktisi; None ise bilgi cikarilamamis demektir.
    isleme_durumu=BEKLIYOR: yuklenen ham dosya; OCR ve siniflandirmayi
    arka plan iscisi yapar (isleme.py).
    gelen_kutusu=True: sahipsiz gelen belge; kullanici_id yoneticidir.
    """
    bilgi = _bilgi_sutunlari(alanlar)
    satir = _sorgula(
        """
        INSERT INTO belgeler
            (kullanici_id, dosya_adi, mime_type, sifreli_icerik,
             sifreli_onizleme, ocr_metni, tur, guven, aciklama,
             belge_tarihi, tutar, para_birimi, kurum, alanlar, otomatik_duzeltildi,
             koseler, orijinal_saklandi, isleme_durumu, isleme_bilgi, gelen_kutusu)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            kullanici_id,
            dosya_adi,
            mime_type,
            psycopg2.Binary(sifreli_icerik),
            psycopg2.Binary(sifreli_onizleme) if sifreli_onizleme else None,
            ocr_metni,
            tur,
            guven,
            aciklama,
            *bilgi,
            otomatik_duzeltildi,
            _kose_json(koseler),
            orijinal_saklandi,
            isleme_durumu,
            _json(isleme_bilgi),
            gelen_kutusu,
        ),
        tek=True,
    )
    return satir["id"]


def _json(deger):
    return None if deger is None else psycopg2.extras.Json(deger)


def _kose_json(koseler):
    """Kose dizisini [[x, y], ...] JSONB'ye cevirir (1 ondalik yeterli)."""
    if koseler is None:
        return None
    return psycopg2.extras.Json([[round(float(x), 1), round(float(y), 1)] for x, y in koseler])


def _bilgi_sutunlari(alanlar):
    """Dogrulanmis alan sozlugunu (belge_tarihi, tutar, para_birimi, kurum,
    alanlar JSONB) degerlerine ayirir. Bilgi cikarilmadiysa hepsi NULL olur;
    cikarildi ama bos ise JSONB '{}' olur (tekrar islenmez)."""
    if alanlar is None:
        return (None,) * (len(SUTUN_ALANLARI) + 1)
    diger = {
        anahtar: deger.isoformat() if isinstance(deger, date) else deger
        for anahtar, deger in alanlar.items()
        if anahtar not in SUTUN_ALANLARI and deger is not None
    }
    return (*(alanlar.get(a) for a in SUTUN_ALANLARI), psycopg2.extras.Json(diger))


# Listelerde sifreli icerik tasinmasin diye sadece gereken sutunlar secilir.
_OZET_SUTUNLAR = (
    "id, dosya_adi, mime_type, tur, guven, aciklama, "
    "elle_duzeltildi, yuklenme_tarihi, (sifreli_onizleme IS NOT NULL) AS onizleme_var, "
    "belge_tarihi, tutar, para_birimi, kurum, alanlar_elle_duzeltildi, otomatik_duzeltildi, "
    "orijinal_saklandi, isleme_durumu, isleme_bilgi, icerik_surumu, gelen_kutusu"
)


def belge_getir(kullanici_id, belge_id):
    """Kullanicinin tek bir belgesini (icerik haric) getirir, yoksa None dondurur."""
    return _sorgula(
        f"SELECT {_OZET_SUTUNLAR}, alanlar, koseler, ocr_metni, atama_gecmisi FROM belgeler "
        "WHERE id = %s AND kullanici_id = %s",
        (belge_id, kullanici_id),
        tek=True,
    )


def belge_icerigi(kullanici_id, belge_id, onizleme=False, bilinen_surumler=()):
    """Kullanicinin belgesinin sifreli ham icerigini (veya onizlemesini) dondurur.

    bilinen_surumler: cagiranin elindeki (surec onbellegi, tarayicinin ETag'i)
    icerik surumleri. Belgenin guncel surumu bunlardan biriyse "veri" None
    doner; buyuk icerik bosuna tasinmaz. Sahiplik kontrolu her durumda ayni
    sorguda yapilir."""
    sutun = "sifreli_onizleme" if onizleme else "sifreli_icerik"
    return _sorgula(
        "SELECT id, dosya_adi, mime_type, koseler, orijinal_saklandi, otomatik_duzeltildi, "
        "isleme_durumu, icerik_surumu, "
        f"CASE WHEN icerik_surumu = ANY(%s::int[]) THEN NULL ELSE {sutun} END AS veri, "
        f"({sutun} IS NOT NULL) AS veri_var FROM belgeler "
        "WHERE id = %s AND kullanici_id = %s",
        (list(bilinen_surumler), belge_id, kullanici_id),
        tek=True,
    )


def belgeleri_listele(kullanici_id, limit=50):
    """Kullanicinin belgelerini en yeniden eskiye dogru listeler."""
    return _sorgula(
        f"SELECT {_OZET_SUTUNLAR} FROM belgeler WHERE kullanici_id = %s AND NOT gelen_kutusu "
        "ORDER BY id DESC LIMIT %s",
        (kullanici_id, limit),
        hepsi=True,
    )


# Kullanicinin secebilecegi siralamalar; SQL'e yalnizca bu sabit metinler girer.
SIRALAMALAR = {
    "yukleme": "id DESC",
    "tarih": "belge_tarihi DESC NULLS LAST, id DESC",
    "tutar": "tutar DESC NULLS LAST, id DESC",
}


def belgeleri_suz(
    kullanici_id,
    tur=None,
    sorgu=None,
    baslangic=None,
    bitis=None,
    kurum=None,
    min_tutar=None,
    maks_tutar=None,
    siralama="yukleme",
    limit=None,
    gelen=False,
):
    """Kategori, arama ve Excel disa aktarmanin ortak sorgusu.

    sorgu: dosya adi, OCR metni, kurum ve alanlar (JSONB degerleri) icinde
    buyuk/kucuk harf duyarsiz arar. Tarih suzgeci belge_tarihi'ne uygulanir;
    tarihi olmayan belgeler tarih suzgeci verilince listelenmez.
    gelen=True: arsiv yerine kullanicinin Gelen belgeler kutusu.
    """
    kosullar, parametreler = ["kullanici_id = %s", "gelen_kutusu = %s"], [kullanici_id, gelen]

    def ekle(kosul, *degerler):
        kosullar.append(kosul)
        parametreler.extend(degerler)

    if tur:
        ekle("tur = %s", tur)
    if sorgu:
        kalip = f"%{sorgu}%"
        ekle(
            "(dosya_adi ILIKE %s OR ocr_metni ILIKE %s OR kurum ILIKE %s OR EXISTS "
            "(SELECT 1 FROM jsonb_each_text(alanlar) AS a WHERE a.value ILIKE %s))",
            kalip, kalip, kalip, kalip,
        )
    if baslangic:
        ekle("belge_tarihi >= %s", baslangic)
    if bitis:
        ekle("belge_tarihi <= %s", bitis)
    if kurum:
        ekle("kurum ILIKE %s", f"%{kurum}%")
    if min_tutar is not None:
        ekle("tutar >= %s", min_tutar)
    if maks_tutar is not None:
        ekle("tutar <= %s", maks_tutar)

    sql = (
        f"SELECT {_OZET_SUTUNLAR} FROM belgeler WHERE {' AND '.join(kosullar)} "
        f"ORDER BY {SIRALAMALAR.get(siralama, SIRALAMALAR['yukleme'])}"
    )
    if limit:
        sql += " LIMIT %s"
        parametreler.append(limit)
    return _sorgula(sql, parametreler, hepsi=True)


def belge_sayisi(kullanici_id):
    """Kullanicinin toplam belge sayisi (kota kontrolu icin)."""
    satir = _sorgula(
        "SELECT COUNT(*) AS adet FROM belgeler WHERE kullanici_id = %s AND NOT gelen_kutusu",
        (kullanici_id,),
        tek=True,
    )
    return satir["adet"]


def tur_sayilari(kullanici_id):
    """Kullanici icin her turun {belge sayisi, son yuklenme tarihi} sozlugu.

    Hic belgesi olmayan turler de sifir sayiyla yer alir; dashboard'daki
    kategori kartlari her zaman eksiksiz gosterilir.
    """
    satirlar = _sorgula(
        "SELECT tur, COUNT(*) AS adet, MAX(yuklenme_tarihi) AS son_tarih "
        "FROM belgeler WHERE kullanici_id = %s AND NOT gelen_kutusu GROUP BY tur",
        (kullanici_id,),
        hepsi=True,
    )
    return sayac_ozeti(satirlar)["turler"]


def turu_guncelle(kullanici_id, belge_id, yeni_tur):
    """Turu elle degistirir, kaydi 'elle duzeltildi' olarak isaretler.

    Belge bu kullaniciya ait degilse hicbir sey degismez ve False doner.
    """
    satir = _sorgula(
        "UPDATE belgeler SET tur = %s, elle_duzeltildi = TRUE "
        "WHERE id = %s AND kullanici_id = %s RETURNING id",
        (yeni_tur, belge_id, kullanici_id),
        tek=True,
    )
    return satir is not None


def alanlari_guncelle(kullanici_id, belge_id, alanlar, elle=True):
    """Belgenin bilgi alanlarini yazar.

    elle=True: kullanici duzeltti, kayit isaretlenir. elle=False: toplu bilgi
    cikarma; elle duzeltilmis belgelerin uzerine yazilmaz. Guncellenen kayit
    yoksa (baskasinin belgesi / elle duzeltilmis) False doner.
    """
    kosul = "" if elle else " AND NOT alanlar_elle_duzeltildi"
    satir = _sorgula(
        "UPDATE belgeler SET belge_tarihi = %s, tutar = %s, para_birimi = %s, "
        "kurum = %s, alanlar = %s, alanlar_elle_duzeltildi = alanlar_elle_duzeltildi OR %s "
        f"WHERE id = %s AND kullanici_id = %s{kosul} RETURNING id",
        (*_bilgi_sutunlari(alanlar), elle, belge_id, kullanici_id),
        tek=True,
    )
    return satir is not None


def koseleri_guncelle(kullanici_id, belge_id, koseler, sifreli_onizleme, ocr_metni):
    """Elle ayarlanan koseleri, yeniden uretilen onizlemeyi ve yeniden okunan
    OCR metnini yazar. Kose degisebilen belgeler: orijinali saklanmis gorseller
    ve hic duzeltilmemis eski gorseller (saklanan zaten orijinal). v4'te
    duzeltilip oyle saklanmis belgeler ve PDF'ler degismez; False doner."""
    satir = _sorgula(
        "UPDATE belgeler SET koseler = %s, orijinal_saklandi = TRUE, "
        "otomatik_duzeltildi = FALSE, sifreli_onizleme = %s, ocr_metni = %s, "
        "icerik_surumu = icerik_surumu + 1, isleme_bilgi = isleme_bilgi - 'uyarilar' - 'kirpma_kontrol' - 'taranmis' "
        "WHERE id = %s AND kullanici_id = %s AND mime_type <> 'application/pdf' "
        f"AND (orijinal_saklandi OR NOT otomatik_duzeltildi) AND isleme_durumu = '{TAMAMLANDI}' RETURNING id",
        (
            _kose_json(koseler),
            psycopg2.Binary(sifreli_onizleme) if sifreli_onizleme else None,
            ocr_metni,
            belge_id,
            kullanici_id,
        ),
        tek=True,
    )
    return satir is not None


def analizi_guncelle(kullanici_id, belge_id, tur, guven, aciklama):
    """Yeniden analizin tur sonucunu yazar; tur elle duzeltilmisse tur ve
    guven degismez, yalnizca aciklama guncellenir."""
    _sorgula(
        "UPDATE belgeler SET "
        "tur = CASE WHEN elle_duzeltildi THEN tur ELSE %s END, "
        "guven = CASE WHEN elle_duzeltildi THEN guven ELSE %s END, "
        "aciklama = %s, isleme_bilgi = isleme_bilgi - 'uyarilar' WHERE id = %s AND kullanici_id = %s",
        (tur, guven, aciklama, belge_id, kullanici_id),
    )


def bilgisi_eksik_belgeler(kullanici_id, son_id=0, limit=1):
    """Bilgi cikarilmamis (alanlar NULL), elle duzeltilmemis ve metni olan
    belgeler; id sirasiyla, son_id'den sonrakiler. Basarisiz olan belge tekrar
    tekrar denenmesin diye cagiran taraf son_id'yi ilerletir."""
    return _sorgula(
        "SELECT id, tur, ocr_metni FROM belgeler WHERE kullanici_id = %s AND id > %s "
        f"AND {_BILGISI_EKSIK} ORDER BY id LIMIT %s",
        (kullanici_id, son_id, limit),
        hepsi=True,
    )


def bilgisi_eksik_sayisi(kullanici_id, son_id=0):
    satir = _sorgula(
        "SELECT COUNT(*) AS adet FROM belgeler WHERE kullanici_id = %s AND id > %s "
        f"AND {_BILGISI_EKSIK}",
        (kullanici_id, son_id),
        tek=True,
    )
    return satir["adet"]


def belge_sil(kullanici_id, belge_id):
    """Kullanicinin belgesini siler; belge ona ait degilse False doner."""
    satir = _sorgula(
        "DELETE FROM belgeler WHERE id = %s AND kullanici_id = %s RETURNING id",
        (belge_id, kullanici_id),
        tek=True,
    )
    return satir is not None


# ---------------------------------------------------------------- arka plan isleme kuyrugu
# Kuyruk ayri bir tablo degil, belgeler satirlarinin isleme_* sutunlaridir;
# boylece Redis/Celery gibi harici servis gerekmez ve durum yeniden
# baslatmalarda kaybolmaz. Asagidaki is fonksiyonlari isciye (isleme.py)
# aittir ve isi belge id'siyle alir; kullaniciya donen her sorgu yine
# kullanici_id ile suzulur. Zamanlar UTC (yuklenme_tarihi gibi).

_SIMDI = "(NOW() AT TIME ZONE 'UTC')"
_ISLENEBILIR = (
    f"((isleme_durumu = '{BEKLIYOR}' AND (isleme_zamani IS NULL OR isleme_zamani <= {_SIMDI}))"
    f" OR (isleme_durumu = '{ISLENIYOR}' AND isleme_zamani < {_SIMDI} - %s * INTERVAL '1 second'))"
)


def is_al(kullanici_id=None, belge_id=None, gecikmeyi_yoksay=False):
    """Islenmeye hazir bir isi "isleniyor" yapip dondurur; yoksa None.

    Hazir is: bekleyen (ertelenmisse zamani gelmis) ya da kalp atisi
    ISLEME_ZAMAN_ASIMI_SN'den eski "isleniyor" is (sureci yeniden baslatilmis
    ya da cokmus iscinin yarim kalan isi). FOR UPDATE SKIP LOCKED ile ayni is
    iki surece verilmez. Icerik tasinmaz (gerekirse is_icerigi).
    kullanici_id / belge_id: testlerde yalnizca kendi belgesini islemek icin."""
    kosullar, parametreler = [], []
    if gecikmeyi_yoksay:
        kosullar.append(f"isleme_durumu IN ('{BEKLIYOR}', '{ISLENIYOR}')")
    else:
        kosullar.append(_ISLENEBILIR)
        parametreler.append(ISLEME_ZAMAN_ASIMI_SN)
    if kullanici_id is not None:
        kosullar.append("kullanici_id = %s")
        parametreler.append(kullanici_id)
    if belge_id is not None:
        kosullar.append("id = %s")
        parametreler.append(belge_id)
    return _sorgula(
        f"""
        UPDATE belgeler SET isleme_durumu = '{ISLENIYOR}', isleme_zamani = {_SIMDI},
                            isleme_deneme = isleme_deneme + 1
        WHERE id = (SELECT id FROM belgeler WHERE {' AND '.join(kosullar)}
                    ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
        RETURNING id, kullanici_id, dosya_adi, mime_type, tur, elle_duzeltildi, ocr_metni,
                  isleme_deneme, COALESCE(isleme_bilgi, '{{}}') AS isleme_bilgi
        """,
        parametreler,
        tek=True,
    )


def is_icerigi(belge_id):
    """Isin saklanan (sifreli) icerigi; yalnizca isci kullanir."""
    return _sorgula("SELECT sifreli_icerik FROM belgeler WHERE id = %s", (belge_id,), tek=True)["sifreli_icerik"]


def sonraki_is_suresi(kullanici_id=None):
    """Siradaki isin hazir olmasina kalan saniye (0 = simdi); is yoksa None.
    Isci bosta iken yalnizca bu kadar bekler, veritabanini surekli yoklamaz."""
    kullanici = "" if kullanici_id is None else " AND kullanici_id = %s"
    satir = _sorgula(
        f"""
        SELECT EXTRACT(EPOCH FROM MIN(CASE
                 WHEN isleme_durumu = '{BEKLIYOR}' THEN COALESCE(isleme_zamani, {_SIMDI})
                 ELSE isleme_zamani + %s * INTERVAL '1 second' END) - {_SIMDI}) AS kalan
        FROM belgeler WHERE isleme_durumu IN ('{BEKLIYOR}', '{ISLENIYOR}'){kullanici}
        """,
        (ISLEME_ZAMAN_ASIMI_SN,) + (() if kullanici_id is None else (kullanici_id,)),
        tek=True,
    )
    if satir is None or satir["kalan"] is None:
        return None
    return max(float(satir["kalan"]), 0.0)


def goruntu_asamasini_kaydet(belge_id, bilgi, ocr_metni, sifreli_onizleme, koseler=None,
                             otomatik_duzeltildi=False):
    """Goruntu asamasinin sonucu: OCR metni, koseler ve duzeltilmis onizleme
    (None: yuklemedeki onizleme kalir). Is "isleniyor" kalir; siradaki asama
    siniflandirmadir (bilgi["asama"]). Uygulama bu noktadan sonra yeniden
    baslarsa OCR tekrarlanmaz."""
    _sorgula(
        f"""
        UPDATE belgeler SET
            sifreli_onizleme = COALESCE(%s, sifreli_onizleme), ocr_metni = %s,
            koseler = %s, otomatik_duzeltildi = %s,
            icerik_surumu = icerik_surumu + 1, isleme_bilgi = %s, isleme_zamani = {_SIMDI}
        WHERE id = %s AND isleme_durumu = '{ISLENIYOR}'
        """,
        (
            psycopg2.Binary(sifreli_onizleme) if sifreli_onizleme else None,
            ocr_metni,
            _kose_json(koseler),
            otomatik_duzeltildi,
            _json(bilgi),
            belge_id,
        ),
    )


def is_ertele(belge_id, saniye, bilgi):
    """Gecici hatada (Groq yogun, baglanti) isi bir sure sonra yeniden denenmek
    uzere kuyruga geri koyar."""
    _sorgula(
        f"UPDATE belgeler SET isleme_durumu = '{BEKLIYOR}', isleme_bilgi = %s, "
        f"isleme_zamani = {_SIMDI} + %s * INTERVAL '1 second' "
        f"WHERE id = %s AND isleme_durumu = '{ISLENIYOR}'",
        (_json(bilgi), saniye, belge_id),
    )


def isi_tamamla(belge_id, tur, guven, aciklama, alanlar, bilgi):
    """Siniflandirma sonucunu yazar ve isi bitirir. Islenirken kullanici turu
    ya da bilgileri elle duzelttiyse onlarin uzerine yazilmaz. alanlar None:
    bilgi cikarilamadi (sutunlar NULL kalir, sonra "bilgi cikar" ile islenir)."""
    _sorgula(
        f"""
        UPDATE belgeler SET
            tur = CASE WHEN elle_duzeltildi THEN tur ELSE %s END,
            guven = CASE WHEN elle_duzeltildi THEN guven ELSE %s END,
            aciklama = %s,
            belge_tarihi = CASE WHEN alanlar_elle_duzeltildi THEN belge_tarihi ELSE %s END,
            tutar = CASE WHEN alanlar_elle_duzeltildi THEN tutar ELSE %s END,
            para_birimi = CASE WHEN alanlar_elle_duzeltildi THEN para_birimi ELSE %s END,
            kurum = CASE WHEN alanlar_elle_duzeltildi THEN kurum ELSE %s END,
            alanlar = CASE WHEN alanlar_elle_duzeltildi THEN alanlar ELSE %s END,
            isleme_durumu = '{TAMAMLANDI}', isleme_zamani = NULL, isleme_bilgi = %s
        WHERE id = %s AND isleme_durumu = '{ISLENIYOR}'
        """,
        (tur, guven, aciklama, *_bilgi_sutunlari(alanlar), _json(bilgi), belge_id),
    )


def is_hatasi(belge_id, bilgi):
    """Isi kalici olarak basarisiz isaretler (bilgi["hata"]: kullaniciya mesaj)."""
    _sorgula(
        f"UPDATE belgeler SET isleme_durumu = '{HATA}', isleme_zamani = NULL, isleme_bilgi = %s "
        f"WHERE id = %s AND isleme_durumu = '{ISLENIYOR}'",
        (_json(bilgi), belge_id),
    )


def isleme_durumlari(kullanici_id, belge_kimlikleri):
    """Kullanicinin verilen belgelerinin isleme durumu (tarayicinin yoklamasi)."""
    return _sorgula(
        "SELECT id, isleme_durumu, isleme_bilgi, tur, guven FROM belgeler "
        "WHERE kullanici_id = %s AND id = ANY(%s)",
        (kullanici_id, list(belge_kimlikleri)),
        hepsi=True,
    )


def yeniden_isle(kullanici_id, belge_id):
    """Hata durumundaki belgeyi kuyruga geri koyar (kaldigi asamadan)."""
    satir = _sorgula(
        f"UPDATE belgeler SET isleme_durumu = '{BEKLIYOR}', isleme_zamani = NULL, isleme_deneme = 0, "
        "isleme_bilgi = COALESCE(isleme_bilgi, '{}') - 'hata' - 'groq_deneme' "
        f"WHERE id = %s AND kullanici_id = %s AND isleme_durumu = '{HATA}' RETURNING id",
        (belge_id, kullanici_id),
        tek=True,
    )
    return satir is not None
