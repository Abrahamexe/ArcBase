# ArcBase — çalışma kuralları

## Testler

- Varsayılan olarak **yalnızca değişen kodla ilgili testleri** çalıştır (ör. `pytest tests/test_duzelt.py`).
  Tam paketi ve Playwright testlerini (`tests/test_arayuz.py`) **yalnızca kullanıcı açıkça isterse** çalıştır.
- Yavaş testler `@pytest.mark.slow` ile işaretlidir (Playwright, gerçek OCR, gerçek Groq, uzun uçtan uca
  testler) ve varsayılan çalıştırmada atlanır (`pytest.ini`: `-m "not slow"`). Yeni yavaş test yazarsan
  onu da işaretle.
  - Hızlı: `pytest`
  - Tam (yavaşlar dahil): `pytest -m "slow or not slow"`
  - Paralel: `pytest -n auto` (tam paket için `-m "slow or not slow"` ekle)
- Testler **asla** `.env`'deki `DATABASE_URL`'e (canlı veritabanı) bağlanmaz; yalnızca `TEST_DATABASE_URL`
  kullanılır. `TEST_DATABASE_URL` tanımlı değilse veritabanı gerektiren testler atlanır; `DATABASE_URL` ile
  aynıysa testler hata verip durur. Ölçüm betikleri (`docs/hiz_olcumu.py`) de aynı kurala uyar.

## Gizli bilgiler ve veritabanı

- `.env` dosyasına dokunma; anahtarları, bağlantı adreslerini ekrana yazdırma.
- Veritabanında tablo silme veya yeniden oluşturma; şema değişikliği yalnızca sütun eklemektir
  (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).

## Git

- `plan*.md`, `DEVAM.md`, `tests/ozel/` ve `.araclar/` git'e gitmez (`.gitignore`'da).
- Commit ve push yapma; onları kullanıcı yapar.
