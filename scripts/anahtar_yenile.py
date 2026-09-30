"""ENCRYPTION_KEY'i yeniler: belgelerin sifreli icerigini eski anahtarla cozup yeni anahtarla sifreler.

Sifreli veri yalnizca veritabanindadir: belgeler.sifreli_icerik ve belgeler.sifreli_onizleme
(BYTEA, Fernet). Diskte sifreli dosya yoktur (tarama klasoru sifresizdir; yedekler pg_dump
ciktisidir ve ESKI anahtarla sifreli veri icerir), bu yuzden dosya donusumu yapilmaz.

Anahtarlar YALNIZCA ortam degiskenlerinden okunur; komut satirina yazilmaz, dosyaya yazilmaz,
hicbir cikti ya da hata mesajinda gosterilmez:
    ESKI_ENCRYPTION_KEY   su an belgeleri sifreleyen anahtar (.env'deki ENCRYPTION_KEY)
    YENI_ENCRYPTION_KEY   yeni anahtar
Bunlari yalnizca kullandiginiz terminal oturumunda tanimlayin, .env'ye yazmayin (README/rapor).

Varsayilan DRY-RUN'dur: hicbir sey yazilmaz; kac kaydin yeniden sifrelenecegi ve kac kaydin
cozulemedigi raporlanir. Gercek islem icin --uygula gerekir. --uygula su kosullar saglanmadan
baslamaz:
  * Uygulama durdurulmus olmali (islenmekte olan belge varsa reddedilir); aksi halde calisan
    uygulama eski anahtarla yeni kayit yazabilir.
  * Taze bir yedek olmali (scripts/yedekle.py; --yedek-al ile betik kendisi alir). Yedegin
    var oldugu, bos olmadigi, pg_dump bicimi tasidigi ve --yedek-yasi-dk'dan yeni oldugu denetlenir.
  * Cozulemeyen kayit olmamali (--cozulemeyenleri-atla ile bilerek atlanabilir).

Islem tek transaction'dir: belgeler tablosu yazmaya karsi kilitlenir (okuyanlar calisir, yazanlar
islem bitene kadar bekler; kilit alinamazsa 15 sn sonra islem baslamadan durur), butun satirlar
yeniden sifrelenir, sonuc dogrulanir ve ancak ondan sonra COMMIT edilir. Kilit, calisan bir
uygulamayi GUVENLI hale getirmez: bekleyen yazma COMMIT'ten sonra eski anahtarla yapilir. Bu
yuzden uygulama durdurulmalidir. Herhangi bir
hata tam geri alma (ROLLBACK) demektir; veritabani eski haliyle kalir. Dogrulama: satir ve
kullanici basina belge sayilari degismemis olmali; rastgele ornek kayitlar (varsayilan 25,
--tam-dogrula ile hepsi) YENI anahtarla cozulmeli, acik metinlerinin ozeti eskisiyle ayni olmali
ve ESKI anahtarla artik cozulememeli. Yalnizca iki sifreli sutun degistirilir; kullanici_id,
dosya adi, OCR metni vb. okunmaz, yazdirilmaz ve degistirilmez (kullanici veri ayrimi korunur).

Tekrar calistirmak guvenlidir: zaten yeni anahtarla sifreli kayitlar "yeni" sayilir, degistirilmez.

Kullanim (proje kokunden; ayrintili sira icin README / rapora bakin):
    python scripts/anahtar_yenile.py                      # dry-run
    python scripts/anahtar_yenile.py --uygula             # gercek islem
    python scripts/anahtar_yenile.py --uygula --yedek-al  # yedegi de betik alsin

Veritabani adresi DATABASE_URL'den (.env) okunur ve yazdirilmaz. Testler yalnizca
TEST_DATABASE_URL'deki gecici bir semada calisir (tests/test_anahtar_yenile.py).
"""

import argparse
import hashlib
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.errors
import psycopg2.extras
from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values, load_dotenv

PROJE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yedekle  # noqa: E402

ENV_ESKI = "ESKI_ENCRYPTION_KEY"
ENV_YENI = "YENI_ENCRYPTION_KEY"
TABLO = "belgeler"
SUTUNLAR = ("sifreli_icerik", "sifreli_onizleme")
PARTI = 50  # satirlar bu kadarlik partilerle okunur/yazilir (bellekte az icerik tutulur)
KILIT_ZAMAN_ASIMI = "15s"
ORNEK_SAYISI = 25
VARSAYILAN_YEDEK_YASI_DK = 60
ISLENIYOR_ESIGI_SN = 180  # database.ISLEME_ZAMAN_ASIMI_SN ile ayni: bundan yeni kalp atisi = calisan isci
ID_LISTE_SINIRI = 20  # raporda en fazla bu kadar belge id'si yazilir
PGDMP_BASLIGI = b"PGDMP"  # pg_dump --format=custom dosyalarinin ilk baytlari


class AnahtarYenilemeHatasi(RuntimeError):
    """Islem baslamadi ya da geri alindi; mesaj kullaniciya gosterilir (anahtar/adres icermez)."""


class AnahtarHatasi(AnahtarYenilemeHatasi):
    """Ortam degiskenlerindeki anahtarlar eksik/gecersiz."""


class CozulemeyenKayitHatasi(AnahtarYenilemeHatasi):
    """Eski anahtarla da yeni anahtarla da cozulemeyen kayit var."""


class DogrulamaHatasi(AnahtarYenilemeHatasi):
    """Yeniden sifreleme sonrasi dogrulama basarisiz: islem geri alinir."""


class YedekDogrulamaHatasi(AnahtarYenilemeHatasi):
    """Taze ve gecerli bir yedek bulunamadi."""


# ---------------------------------------------------------------- anahtarlar

def _fernet(ad, ortam):
    deger = (ortam.get(ad) or "").strip()
    if not deger:
        raise AnahtarHatasi(f"{ad} ortam değişkeni tanımlı değil.")
    try:
        return Fernet(deger.encode()), deger
    except (ValueError, TypeError):
        # Fernet'in hata metni anahtari icermez, ama ne olursa olsun yazdirilmaz.
        raise AnahtarHatasi(f"{ad} geçerli bir Fernet anahtarı değil (44 karakterlik url-safe base64 olmalı).") from None


def anahtarlari_oku(ortam):
    """(eski_fernet, yeni_fernet). Anahtarlar yalnizca ortam degiskenlerinden okunur."""
    eski, eski_ham = _fernet(ENV_ESKI, ortam)
    yeni, yeni_ham = _fernet(ENV_YENI, ortam)
    if eski_ham == yeni_ham:
        raise AnahtarHatasi("Eski ve yeni anahtar aynı; yeni bir anahtar üretin.")
    return eski, yeni


def _coz(fernet, veri):
    try:
        return fernet.decrypt(bytes(veri))
    except (InvalidToken, TypeError, ValueError):
        return None


def _siniflandir(eski, yeni, veri):
    """(durum, acik_metin): "bos" | "eski" (eski anahtarla cozuldu) | "yeni" (zaten yeni anahtarla
    sifreli) | "cozulemez"."""
    if veri is None:
        return "bos", None
    acik = _coz(eski, veri)
    if acik is not None:
        return "eski", acik
    if _coz(yeni, veri) is not None:
        return "yeni", None
    return "cozulemez", None


# ---------------------------------------------------------------- rapor

@dataclass
class Rapor:
    toplam_satir: int = 0
    yeniden_sifrelenecek_satir: int = 0  # en az bir sutunu eski anahtarla cozulen satir
    sutunlar: dict = field(default_factory=lambda: {s: {"eski": 0, "yeni": 0, "cozulemez": 0, "bos": 0} for s in SUTUNLAR})
    cozulemeyen_satir: int = 0
    cozulemeyen_idler: list = field(default_factory=list)
    kullanici_sayilari: dict = field(default_factory=dict)
    dogrulanan_ornek: int = 0
    uygulandi: bool = False

    def say(self, sutun, durum):
        self.sutunlar[sutun][durum] += 1

    @property
    def yeniden_sifrelenecek_sutun(self):
        return sum(s["eski"] for s in self.sutunlar.values())


def rapor_yaz(rapor, cikti=print):
    cikti(f"Toplam belge satırı: {rapor.toplam_satir}")
    cikti(f"Yeniden şifrelenecek satır: {rapor.yeniden_sifrelenecek_satir} "
          f"({rapor.yeniden_sifrelenecek_sutun} şifreli alan)")
    for sutun, s in rapor.sutunlar.items():
        cikti(f"  {sutun}: eski anahtarla çözülen {s['eski']}, zaten yeni anahtarlı {s['yeni']}, "
              f"çözülemeyen {s['cozulemez']}, boş {s['bos']}")
    cikti(f"Çözülemeyen satır (ne eski ne yeni anahtarla açılıyor): {rapor.cozulemeyen_satir}")
    if rapor.cozulemeyen_idler:
        ek = " ..." if rapor.cozulemeyen_satir > len(rapor.cozulemeyen_idler) else ""
        cikti("  belge id: " + ", ".join(map(str, rapor.cozulemeyen_idler)) + ek)
    if rapor.dogrulanan_ornek:
        cikti(f"Yeni anahtarla doğrulanan kayıt: {rapor.dogrulanan_ornek}")


# ---------------------------------------------------------------- veritabani

def baglan(adres):
    if not adres:
        raise AnahtarYenilemeHatasi("DATABASE_URL tanımlı değil.")
    try:
        baglanti = psycopg2.connect(adres)
    except psycopg2.Error as hata:
        mesaj = str(hata).replace(adres, "<DATABASE_URL>").strip().splitlines()[0]
        raise AnahtarYenilemeHatasi(f"Veritabanına bağlanılamadı: {mesaj}") from None
    baglanti.autocommit = False
    return baglanti


def _partiler(imlec):
    """belgeler satirlarini id sirasiyla (id, kullanici_id, icerik, onizleme) partileri olarak verir."""
    son = 0
    while True:
        imlec.execute(
            f"SELECT id, kullanici_id, {', '.join(SUTUNLAR)} FROM {TABLO} WHERE id > %s ORDER BY id LIMIT %s",
            (son, PARTI),
        )
        satirlar = imlec.fetchall()
        if not satirlar:
            return
        yield satirlar
        son = satirlar[-1][0]


def _kullanici_sayilari(imlec):
    imlec.execute(f"SELECT kullanici_id, COUNT(*) FROM {TABLO} GROUP BY kullanici_id")
    return {kullanici: adet for kullanici, adet in imlec.fetchall()}


def uygulama_calisiyor_mu(baglanti):
    """Bir isci belgeyi su an isliyor mu (kalp atisi taze)? Islem ortasinda eski anahtarla yazma riski."""
    with baglanti.cursor() as imlec:
        imlec.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = %s AND column_name = 'isleme_zamani'",
            (TABLO,),
        )
        if imlec.fetchone() is None:
            baglanti.rollback()
            return False
        imlec.execute(
            f"SELECT COUNT(*) FROM {TABLO} WHERE isleme_durumu = 'isleniyor' "
            "AND isleme_zamani > (NOW() AT TIME ZONE 'UTC') - %s * INTERVAL '1 second'",
            (ISLENIYOR_ESIGI_SN,),
        )
        adet = imlec.fetchone()[0]
    baglanti.rollback()
    return adet > 0


def _incele(imlec, eski, yeni, rapor):
    """Tum satirlari siniflandirir (yalnizca sayar; --uygula ile ayni satir kurallari)."""
    for parti in _partiler(imlec):
        for belge_id, _kullanici, *veriler in parti:
            rapor.toplam_satir += 1
            durumlar = []
            for sutun, veri in zip(SUTUNLAR, veriler):
                durum, _acik = _siniflandir(eski, yeni, veri)
                rapor.say(sutun, durum)
                durumlar.append(durum)
            if "cozulemez" in durumlar:  # --uygula bu satira hic dokunmaz (ya da hic baslamaz)
                rapor.cozulemeyen_satir += 1
                if len(rapor.cozulemeyen_idler) < ID_LISTE_SINIRI:
                    rapor.cozulemeyen_idler.append(belge_id)
            elif "eski" in durumlar:
                rapor.yeniden_sifrelenecek_satir += 1


def incele(baglanti, eski, yeni):
    """DRY-RUN: hicbir sey yazmadan Rapor dondurur (salt okunur transaction)."""
    baglanti.rollback()
    baglanti.set_session(readonly=True, autocommit=False)
    rapor = Rapor()
    try:
        with baglanti.cursor() as imlec:
            _incele(imlec, eski, yeni, rapor)
            rapor.kullanici_sayilari = _kullanici_sayilari(imlec)
    finally:
        baglanti.rollback()
        baglanti.set_session(readonly=False, autocommit=False)
    return rapor


class _Ornek:
    """Yeniden sifrelenen alanlardan rastgele ornek tutar (reservoir sampling); yalnizca (id, sutun, sha256) saklanir."""

    def __init__(self, boyut, rastgele):
        self.boyut, self.rastgele, self.gorulen, self.liste = boyut, rastgele, 0, []

    def ekle(self, belge_id, sutun, acik):
        oge = (belge_id, sutun, hashlib.sha256(acik).hexdigest())
        self.gorulen += 1
        if self.boyut is None or len(self.liste) < self.boyut:
            self.liste.append(oge)
        else:
            j = self.rastgele.randrange(self.gorulen)
            if j < self.boyut:
                self.liste[j] = oge


def _ornekleri_dogrula(imlec, eski, yeni, ornek):
    for belge_id, sutun, ozet in ornek.liste:
        imlec.execute(f"SELECT {sutun} FROM {TABLO} WHERE id = %s", (belge_id,))
        satir = imlec.fetchone()
        if satir is None or satir[0] is None:
            raise DogrulamaHatasi(f"Doğrulama başarısız: belge {belge_id} ({sutun}) bulunamadı.")
        acik = _coz(yeni, satir[0])
        if acik is None or hashlib.sha256(acik).hexdigest() != ozet:
            raise DogrulamaHatasi(f"Doğrulama başarısız: belge {belge_id} ({sutun}) yeni anahtarla aynı içerikle çözülemedi.")
        if _coz(eski, satir[0]) is not None:
            raise DogrulamaHatasi(f"Doğrulama başarısız: belge {belge_id} ({sutun}) hâlâ eski anahtarla açılıyor.")
    return len(ornek.liste)


def yeniden_sifrele(baglanti, eski, yeni, ornek_sayisi=ORNEK_SAYISI, cozulemeyenleri_atla=False, rastgele=None):
    """Tum sifreli alanlari tek transaction'da eski anahtardan yeni anahtara gecirir; Rapor dondurur.

    ornek_sayisi None ise yeniden sifrelenen HER alan dogrulanir. Herhangi bir hatada ROLLBACK yapilir
    ve hata yeniden firlatilir; veritabani degismemis olur."""
    rastgele = rastgele or random.Random()
    baglanti.rollback()
    baglanti.set_session(readonly=False, autocommit=False)
    rapor = Rapor()
    ornek = _Ornek(ornek_sayisi, rastgele)
    try:
        with baglanti.cursor() as imlec, baglanti.cursor() as yazma:
            imlec.execute(f"SET LOCAL lock_timeout = '{KILIT_ZAMAN_ASIMI}'")
            try:
                imlec.execute(f"LOCK TABLE {TABLO} IN SHARE ROW EXCLUSIVE MODE")
            except psycopg2.errors.LockNotAvailable:
                raise AnahtarYenilemeHatasi(
                    f"{TABLO} tablosu kilitlenemedi (zaman aşımı). Uygulama çalışıyor olabilir; durdurup yeniden deneyin."
                ) from None
            once_toplam_kullanici = _kullanici_sayilari(imlec)

            for parti in _partiler(imlec):
                guncellemeler = []
                for belge_id, _kullanici, *veriler in parti:
                    rapor.toplam_satir += 1
                    siniflar = [_siniflandir(eski, yeni, veri) for veri in veriler]
                    for sutun, (durum, _acik) in zip(SUTUNLAR, siniflar):
                        rapor.say(sutun, durum)
                    if any(durum == "cozulemez" for durum, _ in siniflar):
                        rapor.cozulemeyen_satir += 1
                        if len(rapor.cozulemeyen_idler) < ID_LISTE_SINIRI:
                            rapor.cozulemeyen_idler.append(belge_id)
                        if not cozulemeyenleri_atla:
                            raise CozulemeyenKayitHatasi(
                                f"Belge {belge_id} ne eski ne yeni anahtarla çözülebiliyor; işlem geri alındı. "
                                "Anahtarların doğru olduğunu denetleyin (bilerek atlamak için --cozulemeyenleri-atla)."
                            )
                        continue  # bilerek atlandi: satira hic dokunulmaz (iki sutun farkli anahtarlarla kalmasin)
                    if not any(durum == "eski" for durum, _ in siniflar):
                        continue  # bos ya da zaten yeni anahtarli
                    yeni_veriler = []
                    for sutun, veri, (durum, acik) in zip(SUTUNLAR, veriler, siniflar):
                        if durum == "eski":
                            yeni_veri = yeni.encrypt(acik)
                            if _coz(yeni, yeni_veri) != acik:  # bellekte hemen dogrula
                                raise DogrulamaHatasi(f"Belge {belge_id} ({sutun}) yeniden şifrelenirken tutarsızlık.")
                            ornek.ekle(belge_id, sutun, acik)
                            yeni_veriler.append(psycopg2.Binary(yeni_veri))
                        else:
                            yeni_veriler.append(None if veri is None else psycopg2.Binary(bytes(veri)))
                    rapor.yeniden_sifrelenecek_satir += 1
                    guncellemeler.append((*yeni_veriler, belge_id))
                if guncellemeler:
                    psycopg2.extras.execute_batch(
                        yazma,
                        f"UPDATE {TABLO} SET {', '.join(f'{s} = %s' for s in SUTUNLAR)} WHERE id = %s",
                        guncellemeler,
                        page_size=PARTI,
                    )

            # Dogrulama (hala ayni transaction'da; hata olursa asagida geri alinir)
            sonra_toplam_kullanici = _kullanici_sayilari(imlec)
            if sonra_toplam_kullanici != once_toplam_kullanici:
                raise DogrulamaHatasi("Doğrulama başarısız: kullanıcı başına belge sayıları değişti.")
            imlec.execute(f"SELECT COUNT(*) FROM {TABLO}")
            if imlec.fetchone()[0] != rapor.toplam_satir:
                raise DogrulamaHatasi("Doğrulama başarısız: satır sayısı değişti.")
            rapor.dogrulanan_ornek = _ornekleri_dogrula(imlec, eski, yeni, ornek)
            rapor.kullanici_sayilari = sonra_toplam_kullanici
        baglanti.commit()
        rapor.uygulandi = True
        return rapor
    except BaseException:
        baglanti.rollback()
        raise


# ---------------------------------------------------------------- yedek

def yedek_klasoru(ortam):
    return Path((ortam.get("YEDEK_KLASORU") or "").strip() or PROJE / "yedekler")


def yedegi_dogrula(klasor, en_fazla_dk=VARSAYILAN_YEDEK_YASI_DK, simdi=None):
    """En yeni yedegin (scripts/yedekle.py adlari) var, bos degil, pg_dump bicimli ve yeterince taze
    oldugunu denetler; (yol, yas_dakika) dondurur. Aksi halde YedekDogrulamaHatasi."""
    klasor = Path(klasor)
    yedekler = sorted(p for p in klasor.iterdir() if p.is_file() and yedekle.AD_KALIBI.match(p.name)) if klasor.is_dir() else []
    komut = "python scripts/yedekle.py"
    if not yedekler:
        raise YedekDogrulamaHatasi(f"Yedek klasöründe yedek yok. Uygulamayı durdurup önce `{komut}` çalıştırın (ya da --yedek-al).")
    yol = yedekler[-1]
    boyut = yol.stat().st_size
    if boyut == 0:
        raise YedekDogrulamaHatasi(f"En yeni yedek boş: {yol.name}. `{komut}` ile yeniden alın.")
    with open(yol, "rb") as dosya:
        if not dosya.read(len(PGDMP_BASLIGI)) == PGDMP_BASLIGI:
            raise YedekDogrulamaHatasi(f"{yol.name} geçerli bir pg_dump (custom) dosyası gibi görünmüyor.")
    yas = ((simdi or datetime.now()) - datetime.fromtimestamp(yol.stat().st_mtime)).total_seconds() / 60
    if yas > en_fazla_dk:
        raise YedekDogrulamaHatasi(
            f"En yeni yedek {yas:.0f} dakika önce alınmış (en fazla {en_fazla_dk}). "
            f"Uygulama durdurulduktan sonra `{komut}` çalıştırın (ya da --yedek-al)."
        )
    return yol, max(yas, 0.0)


# ---------------------------------------------------------------- komut satiri

def _ayril(argv):
    arg = argparse.ArgumentParser(description="ENCRYPTION_KEY yenileme (varsayılan: dry-run).")
    arg.add_argument("--uygula", action="store_true", help="gerçekten yeniden şifrele (yedek ve durdurulmuş uygulama gerekir)")
    arg.add_argument("--yedek-al", action="store_true", help="--uygula öncesi scripts/yedekle.py ile yedeği kendisi alsın")
    arg.add_argument("--yedek-yasi-dk", type=int, default=VARSAYILAN_YEDEK_YASI_DK, help="kabul edilen en eski yedek yaşı (dakika)")
    arg.add_argument("--ornek", type=int, default=ORNEK_SAYISI, help="doğrulanacak rastgele kayıt sayısı")
    arg.add_argument("--tam-dogrula", action="store_true", help="yeniden şifrelenen her alanı doğrula (yavaş)")
    arg.add_argument("--cozulemeyenleri-atla", action="store_true", help="çözülemeyen kayıtlar varsa onlara dokunmadan devam et")
    a = arg.parse_args(argv)
    if a.ornek < 1:
        arg.error("--ornek en az 1 olmalı")
    return a


def calistir(argv=None, ortam=None, cikti=print, hata_cikti=None):
    """Komut satiri mantigi; 0 basari, 1 hata / hazir degil. Testler ortam sozlugu verir."""
    hata_cikti = hata_cikti or (lambda m: print(m, file=sys.stderr, flush=True))
    a = _ayril(argv)
    ortam_sozlugu = os.environ if ortam is None else ortam
    uyarilar = []
    if ortam is None:
        env_yolu = PROJE / ".env"
        load_dotenv(env_yolu)
        yazili = dotenv_values(env_yolu) if env_yolu.exists() else {}
        for ad in (ENV_ESKI, ENV_YENI):
            if ad in yazili:
                uyarilar.append(f"UYARI: {ad} .env dosyasında tanımlı; anahtarlar dosyada durmamalı, yalnızca terminal oturumunda tanımlayın.")
    baglanti = None
    try:
        eski, yeni = anahtarlari_oku(ortam_sozlugu)
        cari = (ortam_sozlugu.get("ENCRYPTION_KEY") or "").strip()
        if cari and cari != (ortam_sozlugu.get(ENV_ESKI) or "").strip():
            uyarilar.append("UYARI: ESKI_ENCRYPTION_KEY, .env'deki ENCRYPTION_KEY ile aynı değil (mevcut kayıtlar hangisiyle şifreli?).")
        for u in uyarilar:
            hata_cikti(u)
        baglanti = baglan(ortam_sozlugu.get("DATABASE_URL"))

        cikti("== " + ("UYGULA" if a.uygula else "DRY-RUN (hiçbir şey yazılmıyor)") + " ==")
        calisiyor = uygulama_calisiyor_mu(baglanti)
        if calisiyor:
            mesaj = "Bir belge şu anda işleniyor görünüyor: uygulama çalışıyor olabilir. Uygulamayı durdurun."
            if a.uygula:
                raise AnahtarYenilemeHatasi(mesaj)
            hata_cikti("UYARI: " + mesaj)

        rapor = incele(baglanti, eski, yeni)
        rapor_yaz(rapor, cikti)
        hazir = rapor.cozulemeyen_satir == 0 or a.cozulemeyenleri_atla
        if not a.uygula:
            if not hazir:
                hata_cikti("HAZIR DEĞİL: çözülemeyen kayıt var; anahtarları denetleyin.")
                return 1
            cikti("Dry-run tamamlandı; hiçbir şey değiştirilmedi. Gerçek işlem için: python scripts/anahtar_yenile.py --uygula")
            return 0

        if not hazir:
            raise CozulemeyenKayitHatasi("Çözülemeyen kayıt var; işlem başlatılmadı (bilerek atlamak için --cozulemeyenleri-atla).")
        if a.yedek_al:
            yol, _ = yedekle.yedekle(ortam_sozlugu.get("DATABASE_URL"), yedek_klasoru(ortam_sozlugu))
            cikti(f"Yedek alındı: {yol.name}")
        yol, yas = yedegi_dogrula(yedek_klasoru(ortam_sozlugu), a.yedek_yasi_dk)
        cikti(f"Yedek doğrulandı: {yol.name} ({yas:.0f} dk önce, {yol.stat().st_size / 1024 / 1024:.1f} MB)")
        sonuc = yeniden_sifrele(
            baglanti, eski, yeni, None if a.tam_dogrula else a.ornek, a.cozulemeyenleri_atla
        )
        cikti("Yeniden şifreleme tamamlandı ve COMMIT edildi.")
        rapor_yaz(sonuc, cikti)
        cikti("SIRADAKİ ADIM: .env'deki ENCRYPTION_KEY değerini YENI anahtarla değiştirin, ardından uygulamayı başlatın. "
              "Eski anahtarı ve yedeği, yeni düzenin çalıştığını doğrulayana kadar saklayın.")
        return 0
    except yedekle.YedekHatasi as hata:
        hata_cikti(f"HATA (yedek alınamadı): {hata}")
        return 1
    except AnahtarYenilemeHatasi as hata:
        hata_cikti(f"HATA: {hata}")
        return 1
    except psycopg2.Error as hata:
        adres = ortam_sozlugu.get("DATABASE_URL") or ""
        ilk = (str(hata).replace(adres, "<DATABASE_URL>") if adres else str(hata)).strip().splitlines()
        hata_cikti(f"HATA (veritabanı, işlem geri alındı): {ilk[0] if ilk else type(hata).__name__}")
        return 1
    finally:
        if baglanti is not None:
            baglanti.close()


if __name__ == "__main__":
    for akis in (sys.stdout, sys.stderr):
        akis.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(calistir())
