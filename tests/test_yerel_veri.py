"""Yerel moda gecis araclari: veri tasima (scripts/veri_tasi.py), yedekleme
(scripts/yedekle.py) ve testlerin yerel asil veritabanina baglanmama korumasi.

Veri tasima testi yalnizca TEST_DATABASE_URL'de, bu test icin acilan iki gecici
semada (kaynak ve hedef) calisir; sonunda bu semalar silinir.
"""

import sys
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import psycopg2
import psycopg2.extras
import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import conftest  # noqa: E402
import crypto  # noqa: E402
import database  # noqa: E402
import db_korumasi  # noqa: E402
import veri_tasi  # noqa: E402
import yedekle  # noqa: E402

# ---------------------------------------------------------------- veri tasima


def _sema_adresi(sema):
    ayrac = "&" if "?" in conftest.TEST_VERITABANI else "?"
    return f"{conftest.TEST_VERITABANI}{ayrac}options={quote(f'-csearch_path={sema}')}"


@pytest.fixture
def semalar(veritabani):
    """Test veritabaninda iki bos gecici sema: (kaynak_adresi, hedef_adresi)."""
    ek = uuid.uuid4().hex[:8]
    adlar = (f"tasi_kaynak_{ek}", f"tasi_hedef_{ek}")
    yonetim = psycopg2.connect(conftest.TEST_VERITABANI)
    yonetim.autocommit = True
    with yonetim.cursor() as imlec:
        for ad in adlar:
            imlec.execute(f"CREATE SCHEMA {ad}")
    try:
        yield tuple(_sema_adresi(ad) for ad in adlar)
    finally:
        with yonetim.cursor() as imlec:
            for ad in adlar:
                imlec.execute(f"DROP SCHEMA IF EXISTS {ad} CASCADE")
        yonetim.close()


def _baglan(adres):
    baglanti = psycopg2.connect(adres, cursor_factory=psycopg2.extras.RealDictCursor)
    baglanti.autocommit = True
    return baglanti


def _kaynagi_doldur(adres):
    """Kaynak semaya 2 kullanici ve 3 belge (sifreli icerik, JSONB, tutar) ekler."""
    with _baglan(adres) as b, b.cursor() as imlec:
        imlec.execute(database.sema_sql())
        imlec.execute(
            "INSERT INTO kullanicilar (id, kullanici_adi, sifre_hash) VALUES (5, 'ayse', 'h1'), (9, 'mehmet', 'h2')"
        )
        for kullanici_id, ad, tutar in ((5, "a.jpg", 720.5), (5, "b.pdf", None), (9, "c.jpg", 12)):
            imlec.execute(
                "INSERT INTO belgeler (kullanici_id, dosya_adi, mime_type, sifreli_icerik, sifreli_onizleme, "
                "ocr_metni, tur, guven, tutar, alanlar, koseler, belge_tarihi) "
                "VALUES (%s, %s, 'image/jpeg', %s, %s, 'FATURA ğüşiöç', 'fatura', 0.93, %s, %s, %s, '2026-01-15')",
                (
                    kullanici_id,
                    ad,
                    psycopg2.Binary(crypto.sifrele(ad.encode() * 1000)),
                    psycopg2.Binary(crypto.sifrele(b"onizleme")),
                    tutar,
                    psycopg2.extras.Json({"fatura_no": "2026-1"}),
                    psycopg2.extras.Json([[1.5, 2], [3, 4], [5, 6], [7, 8]]),
                ),
            )


def _satirlar(adres, tablo):
    with _baglan(adres) as b, b.cursor() as imlec:
        imlec.execute(f"SELECT * FROM {tablo} ORDER BY id")
        return [
            {k: bytes(v) if isinstance(v, memoryview) else v for k, v in satir.items()} for satir in imlec.fetchall()
        ]


def test_veri_tasima_birebir_kopyalar(semalar):
    kaynak, hedef = semalar
    _kaynagi_doldur(kaynak)
    mesajlar, onaylar = [], []

    sonuc = veri_tasi.tasi(kaynak, hedef, onayla=lambda m: onaylar.append(m) or True, yaz=mesajlar.append)

    assert sonuc == {"kullanicilar": 2, "belgeler": 3}
    assert "2 kullanıcı ve 3 belge" in onaylar[0]
    assert any("Doğrulama başarılı" in m for m in mesajlar)
    for tablo in veri_tasi.TABLOLAR:
        assert _satirlar(hedef, tablo) == _satirlar(kaynak, tablo)
    # Sifreli icerik ayni anahtarla cozulebilir.
    ilk = _satirlar(hedef, "belgeler")[0]
    assert crypto.coz(ilk["sifreli_icerik"]) == b"a.jpg" * 1000
    # id sayaclari ilerletildi: yeni kayit tasinan id'lerle cakismaz.
    with _baglan(hedef) as b, b.cursor() as imlec:
        imlec.execute("INSERT INTO kullanicilar (kullanici_adi, sifre_hash) VALUES ('yeni', 'h') RETURNING id")
        assert imlec.fetchone()["id"] == 10


def test_veri_tasima_dolu_hedefe_yazmaz(semalar):
    kaynak, hedef = semalar
    _kaynagi_doldur(kaynak)
    veri_tasi.tasi(kaynak, hedef, onayla=lambda m: True, yaz=lambda m: None)
    with pytest.raises(veri_tasi.TasimaHatasi, match="boş değil"):
        veri_tasi.tasi(kaynak, hedef, onayla=lambda m: True, yaz=lambda m: None)
    assert len(_satirlar(hedef, "belgeler")) == 3


def test_veri_tasima_onaysiz_kopyalamaz(semalar):
    kaynak, hedef = semalar
    _kaynagi_doldur(kaynak)
    assert veri_tasi.tasi(kaynak, hedef, onayla=lambda m: False, yaz=lambda m: None) is None
    assert _satirlar(hedef, "kullanicilar") == []  # sema olusturuldu, veri yok


def test_veri_tasima_yanlis_anahtarla_baslamaz(semalar, monkeypatch):
    kaynak, hedef = semalar
    _kaynagi_doldur(kaynak)
    monkeypatch.setattr(crypto, "_fernet", Fernet(Fernet.generate_key()))
    with pytest.raises(veri_tasi.TasimaHatasi, match="ENCRYPTION_KEY"):
        veri_tasi.tasi(kaynak, hedef, onayla=lambda m: True, yaz=lambda m: None)
    assert _satirlar(hedef, "belgeler") == []


def test_veri_tasima_dogrulama_hatasinda_geri_alir(semalar, monkeypatch):
    kaynak, hedef = semalar
    _kaynagi_doldur(kaynak)
    monkeypatch.setattr(veri_tasi, "_ozet", lambda baglanti, tablo, sutunlar: (id(baglanti), None))
    with pytest.raises(veri_tasi.TasimaHatasi, match="Doğrulama başarısız"):
        veri_tasi.tasi(kaynak, hedef, onayla=lambda m: True, yaz=lambda m: None)
    assert _satirlar(hedef, "kullanicilar") == []


def test_veri_tasima_ayni_veritabanini_reddeder():
    adres = "postgresql://u:p@localhost:5432/arcbase"
    for hedef in (adres, "postgresql://u:p@127.0.0.1/arcbase"):
        with pytest.raises(veri_tasi.TasimaHatasi, match="aynı"):
            veri_tasi.tasi(adres, hedef)


# ---------------------------------------------------------------- yedekleme


def test_yedek_adi_ve_eski_yedeklerin_silinmesi(tmp_path):
    assert yedekle.yedek_adi(datetime(2026, 9, 29, 3, 0, 5)) == "arcbase_2026-09-29_030005.dump"
    adlar = [yedekle.yedek_adi(datetime(2026, 9, gun, 3)) for gun in range(1, 6)]
    for ad in adlar:
        (tmp_path / ad).write_bytes(b"x")
    (tmp_path / "notlar.txt").write_text("dokunulmaz")
    (tmp_path / "arcbase_elle.dump").write_bytes(b"x")

    silinen = yedekle.eski_yedekleri_sil(tmp_path, 2)

    assert [p.name for p in silinen] == adlar[:3]
    kalan = sorted(p.name for p in tmp_path.iterdir())
    assert kalan == sorted(adlar[3:] + ["notlar.txt", "arcbase_elle.dump"])


def _sahte_pg_dump(monkeypatch, cikis=0, yaz=True, stderr=""):
    cagrilar = []

    def calistir(komut, **_):
        cagrilar.append(komut)
        dosya = next(a.split("=", 1)[1] for a in komut if a.startswith("--file="))
        if yaz:
            Path(dosya).write_bytes(b"PGDMP")
        return type("Sonuc", (), {"returncode": cikis, "stderr": stderr})()

    monkeypatch.setattr(yedekle.subprocess, "run", calistir)
    return cagrilar


def test_yedekle_basarili_yedek_ve_tutma_siniri(tmp_path, monkeypatch):
    cagrilar = _sahte_pg_dump(monkeypatch)
    adres = "postgresql://u:gizli@localhost/arcbase"
    for gun in range(1, 5):
        yol, _ = yedekle.yedekle(adres, tmp_path, 3, pg_dump="pg_dump", zaman=datetime(2026, 9, gun))
        assert yol.read_bytes() == b"PGDMP"
    assert "--format=custom" in cagrilar[0] and f"--dbname={adres}" in cagrilar[0]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        yedekle.yedek_adi(datetime(2026, 9, gun)) for gun in (2, 3, 4)
    ]


def test_yedekle_hatada_yarim_dosya_birakmaz_ve_adresi_gizler(tmp_path, monkeypatch):
    adres = "postgresql://u:gizli@localhost/arcbase"
    _sahte_pg_dump(monkeypatch, cikis=1, stderr=f'connection to "{adres}" failed')
    with pytest.raises(yedekle.YedekHatasi) as hata:
        yedekle.yedekle(adres, tmp_path, 3, pg_dump="pg_dump")
    assert "gizli" not in str(hata.value)
    assert list(tmp_path.iterdir()) == []


def test_yedekle_pg_dump_yoksa_anlasilir_hata(monkeypatch):
    monkeypatch.setenv("PG_DUMP", "")
    monkeypatch.setattr(yedekle.shutil, "which", lambda ad: None)
    with pytest.raises(yedekle.YedekHatasi, match="pg_dump bulunamadı"):
        yedekle.pg_dump_yolu()


@pytest.mark.slow
def test_yedekle_gercek_pg_dump(veritabani, tmp_path):
    try:
        pg_dump = yedekle.pg_dump_yolu()
    except yedekle.YedekHatasi:
        pytest.skip("pg_dump kurulu değil")
    yol, _ = yedekle.yedekle(conftest.TEST_VERITABANI, tmp_path, 2, pg_dump=pg_dump)
    assert yol.read_bytes()[:5] == b"PGDMP"


# ---------------------------------------------------------------- test veritabani korumasi


def test_yerel_asil_veritabani_testlerde_reddedilir(monkeypatch):
    monkeypatch.setattr(db_korumasi, "ENV_DOSYASI", Path("olmayan.env"))
    monkeypatch.setenv("YEREL_DATABASE_URL", "postgresql://u:p@localhost:5432/arcbase")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://u:p@127.0.0.1/arcbase")
    monkeypatch.setenv("DATABASE_URL", "")
    with pytest.raises(db_korumasi.CanliVeritabaniHatasi):
        db_korumasi.veritabanini_ayarla()
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://u:p@localhost:5432/arcbase_test")
    assert db_korumasi.veritabanini_ayarla().endswith("/arcbase_test")
