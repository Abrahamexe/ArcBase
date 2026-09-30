"""ENCRYPTION_KEY yenileme betigi (scripts/anahtar_yenile.py).

Yalnizca TEST_DATABASE_URL'deki, bu test icin acilan gecici bir semada calisir; sonunda sema
silinir. Canli veritabanina (DATABASE_URL / YEREL_DATABASE_URL) hicbir kosulda baglanilmaz
(conftest.py + db_korumasi.py). Anahtarlar her testte Fernet.generate_key() ile uretilir;
uygulamanin .env'deki ENCRYPTION_KEY'i kullanilmaz.
"""

import os
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import psycopg2
import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import anahtar_yenile as ay  # noqa: E402
import conftest  # noqa: E402
import database  # noqa: E402

# 5 satir; onizlemesi olmayan bir tane (NULL) dahil. (kullanici_id, dosya_adi, icerik, onizleme)
BELGELER = [
    (5, "a.jpg", b"icerik-a" * 500, b"onizleme-a"),
    (5, "b.pdf", b"icerik-b" * 300, None),
    (5, "c.jpg", b"icerik-c" * 700, b"onizleme-c"),
    (9, "d.jpg", b"icerik-d" * 200, b"onizleme-d"),
    (9, "e.jpg", b"icerik-e" * 900, b"onizleme-e"),
]


@pytest.fixture
def sema(veritabani):
    """Test veritabaninda bos, gecici bir sema (tablolar hazir): baglanti adresi."""
    assert conftest.TEST_VERITABANI, "TEST_DATABASE_URL olmadan bu test calismaz"
    ad = f"anahtar_{uuid.uuid4().hex[:8]}"
    yonetim = psycopg2.connect(conftest.TEST_VERITABANI)
    yonetim.autocommit = True
    with yonetim.cursor() as imlec:
        imlec.execute(f"CREATE SCHEMA {ad}")
    ayrac = "&" if "?" in conftest.TEST_VERITABANI else "?"
    adres = f"{conftest.TEST_VERITABANI}{ayrac}options={quote(f'-csearch_path={ad}')}"
    with _baglan(adres) as b, b.cursor() as imlec:
        imlec.execute(database.sema_sql())
    try:
        yield adres
    finally:
        with yonetim.cursor() as imlec:
            imlec.execute(f"DROP SCHEMA IF EXISTS {ad} CASCADE")
        yonetim.close()


def _baglan(adres):
    baglanti = psycopg2.connect(adres)
    baglanti.autocommit = True
    return baglanti


@contextmanager
def _b(adres):
    """Betigin kendi baglantisi (autocommit kapali); sonunda kapatilir."""
    baglanti = ay.baglan(adres)
    try:
        yield baglanti
    finally:
        baglanti.close()


@pytest.fixture
def anahtarlar():
    """(eski_fernet, yeni_fernet, eski_metin, yeni_metin)"""
    eski, yeni = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    return Fernet(eski), Fernet(yeni), eski, yeni


@pytest.fixture
def veri(sema, anahtarlar):
    """Eski anahtarla sifrelenmis sentetik kayitlar: (adres, {belge_id: (icerik, onizleme)})."""
    eski = anahtarlar[0]
    acik = {}
    with _baglan(sema) as b, b.cursor() as imlec:
        imlec.execute("INSERT INTO kullanicilar (id, kullanici_adi, sifre_hash) VALUES (5, 'ayse', 'h1'), (9, 'mehmet', 'h2')")
        for kullanici_id, ad, icerik, onizleme in BELGELER:
            imlec.execute(
                "INSERT INTO belgeler (kullanici_id, dosya_adi, mime_type, sifreli_icerik, sifreli_onizleme, ocr_metni) "
                "VALUES (%s, %s, 'image/jpeg', %s, %s, %s) RETURNING id",
                (
                    kullanici_id,
                    ad,
                    psycopg2.Binary(eski.encrypt(icerik)),
                    psycopg2.Binary(eski.encrypt(onizleme)) if onizleme else None,
                    "ocr " + ad,
                ),
            )
            acik[imlec.fetchone()[0]] = (icerik, onizleme)
    return sema, acik


def _anlik(adres):
    """Tablonun tam goruntusu (karsilastirma icin): sifreli sutunlar bayt olarak."""
    with _baglan(adres) as b, b.cursor() as imlec:
        imlec.execute("SELECT id, kullanici_id, dosya_adi, ocr_metni, sifreli_icerik, sifreli_onizleme FROM belgeler ORDER BY id")
        return [(i, k, d, o, bytes(c), None if z is None else bytes(z)) for i, k, d, o, c, z in imlec.fetchall()]


def _ortam(adres, anahtarlar, klasor, **ek):
    return {"DATABASE_URL": adres, ay.ENV_ESKI: anahtarlar[2], ay.ENV_YENI: anahtarlar[3], "YEDEK_KLASORU": str(klasor), **ek}


def _yedek_yaz(klasor, baslik=b"PGDMP", saat_once=0.0, ad="arcbase_2026-09-30_030000.dump"):
    yol = Path(klasor) / ad
    yol.write_bytes(baslik + b"\x00" * 64)
    ts = time.time() - saat_once * 3600
    os.utime(yol, (ts, ts))
    return yol


# ---------------------------------------------------------------- cekirdek islev

def test_dry_run_rapor_verir_ve_hicbir_sey_yazmaz(veri, anahtarlar):
    adres, _ = veri
    once = _anlik(adres)
    with _b(adres) as b:
        rapor = ay.incele(b, anahtarlar[0], anahtarlar[1])
    assert rapor.toplam_satir == 5
    assert rapor.yeniden_sifrelenecek_satir == 5
    assert rapor.sutunlar["sifreli_icerik"] == {"eski": 5, "yeni": 0, "cozulemez": 0, "bos": 0}
    assert rapor.sutunlar["sifreli_onizleme"] == {"eski": 4, "yeni": 0, "cozulemez": 0, "bos": 1}
    assert rapor.cozulemeyen_satir == 0 and rapor.cozulemeyen_idler == []
    assert rapor.kullanici_sayilari == {5: 3, 9: 2}
    assert not rapor.uygulandi
    assert _anlik(adres) == once


def test_uygula_yeni_anahtarla_cozer_eskiyle_cozmez_geri_kalan_sutunlar_ayni(veri, anahtarlar):
    adres, acik = veri
    eski, yeni = anahtarlar[0], anahtarlar[1]
    once = _anlik(adres)
    with _b(adres) as b:
        rapor = ay.yeniden_sifrele(b, eski, yeni, ornek_sayisi=None)
    assert rapor.uygulandi
    assert rapor.yeniden_sifrelenecek_satir == 5
    assert rapor.dogrulanan_ornek == 9  # 5 icerik + 4 onizleme, hepsi dogrulandi
    sonra = _anlik(adres)
    assert len(sonra) == len(once)
    for (i, k, ad, ocr, icerik, onizleme), (i0, k0, ad0, ocr0, icerik0, onizleme0) in zip(sonra, once):
        # kullanici_id, dosya adi, OCR metni: dokunulmaz (kullanici veri ayrimi)
        assert (i, k, ad, ocr) == (i0, k0, ad0, ocr0)
        assert icerik != icerik0
        assert yeni.decrypt(icerik) == acik[i][0]
        with pytest.raises(Exception):
            eski.decrypt(icerik)
        if acik[i][1] is None:
            assert onizleme is None and onizleme0 is None
        else:
            assert yeni.decrypt(onizleme) == acik[i][1]
            with pytest.raises(Exception):
                eski.decrypt(onizleme)


def test_varsayilan_ornek_sayisiyla_da_dogrular(veri, anahtarlar):
    adres, _ = veri
    with _b(adres) as b:
        rapor = ay.yeniden_sifrele(b, anahtarlar[0], anahtarlar[1])
    assert rapor.dogrulanan_ornek == 9  # ornek sayisi (25) alan sayisindan fazla: hepsi


def test_kucuk_ornek_sayisi_o_kadar_kaydi_dogrular(veri, anahtarlar):
    adres, _ = veri
    with _b(adres) as b:
        rapor = ay.yeniden_sifrele(b, anahtarlar[0], anahtarlar[1], ornek_sayisi=3)
    assert rapor.dogrulanan_ornek == 3


def test_tekrar_calistirmak_guvenlidir(veri, anahtarlar):
    adres, _ = veri
    with _b(adres) as b:
        ay.yeniden_sifrele(b, anahtarlar[0], anahtarlar[1])
    ilk = _anlik(adres)
    with _b(adres) as b:
        rapor = ay.yeniden_sifrele(b, anahtarlar[0], anahtarlar[1])
    assert rapor.yeniden_sifrelenecek_satir == 0
    assert rapor.sutunlar["sifreli_icerik"]["yeni"] == 5
    assert rapor.cozulemeyen_satir == 0
    assert _anlik(adres) == ilk


def test_hatali_eski_anahtar_hicbir_seyi_degistirmez(veri, anahtarlar):
    adres, _ = veri
    yanlis = Fernet(Fernet.generate_key())
    once = _anlik(adres)
    with _b(adres) as b:
        rapor = ay.incele(b, yanlis, anahtarlar[1])
    assert rapor.cozulemeyen_satir == 5
    assert rapor.yeniden_sifrelenecek_satir == 0
    assert rapor.cozulemeyen_idler and len(rapor.cozulemeyen_idler) == 5
    with _b(adres) as b, pytest.raises(ay.CozulemeyenKayitHatasi):
        ay.yeniden_sifrele(b, yanlis, anahtarlar[1])
    assert _anlik(adres) == once
    # bilerek atlanirsa: hicbir sey degismez, kayit sayisi raporlanir
    with _b(adres) as b:
        rapor = ay.yeniden_sifrele(b, yanlis, anahtarlar[1], cozulemeyenleri_atla=True)
    assert rapor.cozulemeyen_satir == 5 and rapor.yeniden_sifrelenecek_satir == 0
    assert _anlik(adres) == once


def _sonuncuyu_boz(adres):
    with _baglan(adres) as b, b.cursor() as imlec:
        imlec.execute("UPDATE belgeler SET sifreli_icerik = %s WHERE id = (SELECT MAX(id) FROM belgeler)", (psycopg2.Binary(b"bozuk"),))


def test_tek_bozuk_kayit_butun_islemi_geri_alir(veri, anahtarlar, monkeypatch):
    adres, _ = veri
    monkeypatch.setattr(ay, "PARTI", 1)  # bozuk kayit son partide: onceki partiler yazilmis olur, sonra geri alinmali
    _sonuncuyu_boz(adres)
    once = _anlik(adres)
    with _b(adres) as b, pytest.raises(ay.CozulemeyenKayitHatasi) as hata:
        ay.yeniden_sifrele(b, anahtarlar[0], anahtarlar[1])
    assert "belge" in str(hata.value).lower()
    assert _anlik(adres) == once


def test_bozuk_kayit_atlanirsa_digerleri_yenilenir_bozuk_dokunulmaz(veri, anahtarlar, monkeypatch):
    adres, acik = veri
    monkeypatch.setattr(ay, "PARTI", 2)
    _sonuncuyu_boz(adres)
    once = _anlik(adres)
    with _b(adres) as b:
        rapor = ay.yeniden_sifrele(b, anahtarlar[0], anahtarlar[1], cozulemeyenleri_atla=True)
    assert rapor.cozulemeyen_satir == 1
    sonra = _anlik(adres)
    assert sonra[-1] == once[-1]  # bozuk kaydin satirina hic dokunulmaz (onizlemesi bile eski anahtarli kalir)
    for satir in sonra[:-1]:
        assert anahtarlar[1].decrypt(satir[4]) == acik[satir[0]][0]


def test_dogrulama_hatasi_islemi_geri_alir(veri, anahtarlar, monkeypatch):
    adres, _ = veri
    once = _anlik(adres)

    def basarisiz(*_a, **_k):
        raise ay.DogrulamaHatasi("deneme")

    monkeypatch.setattr(ay, "_ornekleri_dogrula", basarisiz)
    with _b(adres) as b, pytest.raises(ay.DogrulamaHatasi):
        ay.yeniden_sifrele(b, anahtarlar[0], anahtarlar[1])
    assert _anlik(adres) == once


def test_yazilmayan_guncelleme_dogrulamada_yakalanir(veri, anahtarlar, monkeypatch):
    """UPDATE'ler bir sekilde yazilmazsa ornek dogrulamasi (eski anahtarla hala aciliyor) islemi durdurur."""
    adres, _ = veri
    once = _anlik(adres)
    monkeypatch.setattr(ay.psycopg2.extras, "execute_batch", lambda *a, **k: None)
    with _b(adres) as b, pytest.raises(ay.DogrulamaHatasi):
        ay.yeniden_sifrele(b, anahtarlar[0], anahtarlar[1])
    assert _anlik(adres) == once


def test_baglanti_hatasi_adresi_sizdirmaz():
    gizli = "postgresql://kullanici:cokgizlisifre@yok.invalid:1/veritabani"
    with pytest.raises(ay.AnahtarYenilemeHatasi) as hata:
        ay.baglan(gizli)
    assert "cokgizlisifre" not in str(hata.value)


# ---------------------------------------------------------------- yedek denetimi

def test_yedegi_dogrula(tmp_path):
    with pytest.raises(ay.YedekDogrulamaHatasi):  # klasor bos
        ay.yedegi_dogrula(tmp_path)
    _yedek_yaz(tmp_path, ad="arcbase_2026-09-29_030000.dump", saat_once=0)
    yol, yas = ay.yedegi_dogrula(tmp_path)
    assert yol.name == "arcbase_2026-09-29_030000.dump" and yas < 1
    # en yeni ad secilir; o eskiyse hata (eski yedegin tazeligi kurtarmaz)
    _yedek_yaz(tmp_path, ad="arcbase_2026-09-30_030000.dump", saat_once=5)
    with pytest.raises(ay.YedekDogrulamaHatasi, match="dakika önce"):
        ay.yedegi_dogrula(tmp_path, en_fazla_dk=60)
    _yedek_yaz(tmp_path, ad="arcbase_2026-09-30_040000.dump", baslik=b"XXXXX")
    with pytest.raises(ay.YedekDogrulamaHatasi, match="pg_dump"):
        ay.yedegi_dogrula(tmp_path)
    (tmp_path / "arcbase_2026-09-30_050000.dump").write_bytes(b"")
    with pytest.raises(ay.YedekDogrulamaHatasi, match="boş"):
        ay.yedegi_dogrula(tmp_path)
    (tmp_path / "notlar.dump").write_bytes(b"PGDMP")  # betigin adina uymayan dosya sayilmaz
    with pytest.raises(ay.YedekDogrulamaHatasi, match="boş"):
        ay.yedegi_dogrula(tmp_path)


# ---------------------------------------------------------------- komut satiri

def _gizli_yok(capsys, anahtarlar):
    cikti = capsys.readouterr()
    for parca in (cikti.out, cikti.err):
        assert anahtarlar[2] not in parca and anahtarlar[3] not in parca
    return cikti


def test_varsayilan_dry_run(veri, anahtarlar, tmp_path, capsys):
    adres, _ = veri
    once = _anlik(adres)
    kod = ay.calistir([], _ortam(adres, anahtarlar, tmp_path))
    cikti = _gizli_yok(capsys, anahtarlar)
    assert kod == 0
    assert "DRY-RUN" in cikti.out and "Yeniden şifrelenecek satır: 5" in cikti.out
    assert _anlik(adres) == once


def test_dry_run_yanlis_anahtarla_hazir_degil(veri, anahtarlar, tmp_path, capsys):
    adres, _ = veri
    ortam = _ortam(adres, anahtarlar, tmp_path, **{ay.ENV_ESKI: Fernet.generate_key().decode()})
    assert ay.calistir([], ortam) == 1
    cikti = capsys.readouterr()
    assert "Çözülemeyen satır (ne eski ne yeni anahtarla açılıyor): 5" in cikti.out
    assert "HAZIR DEĞİL" in cikti.err


def test_uygula_yedeksiz_baslamaz(veri, anahtarlar, tmp_path, capsys):
    adres, _ = veri
    once = _anlik(adres)
    assert ay.calistir(["--uygula"], _ortam(adres, anahtarlar, tmp_path)) == 1
    assert "yedek" in _gizli_yok(capsys, anahtarlar).err.lower()
    assert _anlik(adres) == once


def test_uygula_eski_yedekle_baslamaz(veri, anahtarlar, tmp_path, capsys):
    adres, _ = veri
    once = _anlik(adres)
    _yedek_yaz(tmp_path, saat_once=3)
    assert ay.calistir(["--uygula"], _ortam(adres, anahtarlar, tmp_path)) == 1
    assert "dakika önce" in _gizli_yok(capsys, anahtarlar).err
    assert _anlik(adres) == once


def test_uygula_taze_yedekle_yeniden_sifreler(veri, anahtarlar, tmp_path, capsys):
    adres, acik = veri
    _yedek_yaz(tmp_path)
    assert ay.calistir(["--uygula"], _ortam(adres, anahtarlar, tmp_path)) == 0
    cikti = _gizli_yok(capsys, anahtarlar)
    assert "Yedek doğrulandı" in cikti.out and "COMMIT edildi" in cikti.out and "ENCRYPTION_KEY" in cikti.out
    for belge_id, _k, _a, _o, icerik, onizleme in _anlik(adres):
        assert anahtarlar[1].decrypt(icerik) == acik[belge_id][0]


def test_uygula_calisan_uygulamada_baslamaz(veri, anahtarlar, tmp_path, capsys):
    adres, _ = veri
    _yedek_yaz(tmp_path)
    with _baglan(adres) as b, b.cursor() as imlec:
        imlec.execute(
            "UPDATE belgeler SET isleme_durumu = 'isleniyor', isleme_zamani = (NOW() AT TIME ZONE 'UTC') "
            "WHERE id = (SELECT MIN(id) FROM belgeler)"
        )
    once = _anlik(adres)
    assert ay.calistir(["--uygula"], _ortam(adres, anahtarlar, tmp_path)) == 1
    assert "uygulama çalışıyor" in _gizli_yok(capsys, anahtarlar).err
    assert _anlik(adres) == once


def test_uygula_bozuk_kayitta_baslamaz(veri, anahtarlar, tmp_path, capsys):
    adres, _ = veri
    _yedek_yaz(tmp_path)
    _sonuncuyu_boz(adres)
    once = _anlik(adres)
    assert ay.calistir(["--uygula"], _ortam(adres, anahtarlar, tmp_path)) == 1
    _gizli_yok(capsys, anahtarlar)
    assert _anlik(adres) == once


@pytest.mark.parametrize(
    "degisiklik, beklenen",
    [
        ({ay.ENV_ESKI: ""}, ay.ENV_ESKI),
        ({ay.ENV_YENI: ""}, ay.ENV_YENI),
        ({ay.ENV_YENI: "gecersiz-anahtar"}, "geçerli bir Fernet"),
    ],
)
def test_anahtar_eksik_ya_da_gecersiz(veri, anahtarlar, tmp_path, capsys, degisiklik, beklenen):
    adres, _ = veri
    once = _anlik(adres)
    assert ay.calistir([], _ortam(adres, anahtarlar, tmp_path, **degisiklik)) == 1
    cikti = _gizli_yok(capsys, anahtarlar)
    assert beklenen in cikti.err and "gecersiz-anahtar" not in cikti.err
    assert _anlik(adres) == once


def test_ayni_anahtar_reddedilir(veri, anahtarlar, tmp_path, capsys):
    adres, _ = veri
    assert ay.calistir(["--uygula"], _ortam(adres, anahtarlar, tmp_path, **{ay.ENV_YENI: anahtarlar[2]})) == 1
    assert "aynı" in capsys.readouterr().err


def test_anahtarlar_komut_satirindan_verilemez():
    with pytest.raises(SystemExit):
        ay.calistir(["--eski-anahtar", "x"], {})
