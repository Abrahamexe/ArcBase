# ArcBase — Kurum Kurulum Rehberi (Windows, yerel mod)

Bu rehber ArcBase'i kurumun kendi Windows bilgisayarına kurmak içindir. Belgeler ve veritabanı bu
bilgisayarda kalır; kurum içindeki diğer bilgisayarlar uygulamayı tarayıcıdan (Chrome, Edge) yerel ağ
üzerinden açar. İnternete giden tek bağlantı, belge türünü belirlemek için Groq'a gönderilen **okunmuş
metindir** (bkz. [11. Veri akışı](#11-veri-akışı)).

Adımları sırayla uygulayın. Komutlar **PowerShell**'e yazılır: Başlat menüsünde "PowerShell" arayın.
`<...>` ile gösterilen yerlere kendi değerinizi yazın.

**İçindekiler**

1. [Gereksinimler](#1-gereksinimler)
2. [PostgreSQL ve `arcbase` veritabanı](#2-postgresql-ve-arcbase-veritabanı)
3. [Tesseract ve Türkçe dil paketi](#3-tesseract-ve-türkçe-dil-paketi)
4. [Groq API anahtarı](#4-groq-api-anahtarı)
5. [Python, proje, sanal ortam, paketler](#5-python-proje-sanal-ortam-paketler)
6. [`.env` dosyasını doldurma](#6-env-dosyasını-doldurma)
7. [Tarama klasörü ve tarayıcı ayarı](#7-tarama-klasörü-ve-tarayıcı-ayarı)
8. [Başlatma, otomatik başlatma, güvenlik duvarı](#8-başlatma-otomatik-başlatma-güvenlik-duvarı)
9. [Yedekleme ve `ENCRYPTION_KEY`'i saklama](#9-yedekleme-ve-encryption_keyi-saklama)
10. [Sorun giderme](#10-sorun-giderme)
11. [Veri akışı](#11-veri-akışı)

Ekler: [Buluttan (Neon) taşıma](#ek-a-buluttaki-arşivi-taşıma-isteğe-bağlı) ·
[Gerçek tarayıcıyla kontrol listesi](#ek-b-gerçek-tarayıcıyla-kontrol-listesi)

---

## 1. Gereksinimler

| | Önerilen |
|---|---|
| İşletim sistemi | Windows 10 veya 11 (64 bit) |
| Bellek (RAM) | En az 8 GB (OCR sırasında 1-2 GB kullanılır) |
| Disk | Kurulum için 3 GB + belgeler için yer (belge başına ortalama 0,5-1 MB) + yedekler |
| İnternet | Yalnızca Groq'a erişim için (belge türü ve bilgileri). İnternet yoksa belgeler yine arşivlenir, türü "Diğer" olur; bağlantı gelince belge sayfasından "Yeniden analiz" yapılabilir. |
| Ağ | Diğer bilgisayarlardan erişilecekse aynı yerel ağda olmalı. Bu bilgisayara sabit IP verilmesi önerilir (ağ yöneticisi ya da modem ayarı). |

Bilgisayar sürekli açık kalacaksa güç ayarlarında **uyku modunu kapatın** (Ayarlar → Sistem → Güç).

## 2. PostgreSQL ve `arcbase` veritabanı

1. <https://www.postgresql.org/download/windows/> adresinden **PostgreSQL 16 veya 17** kurulum dosyasını
   (EDB) indirip çalıştırın.
2. Kurulumda:
   - Bileşenlerde **PostgreSQL Server**, **pgAdmin 4** ve **Command Line Tools** seçili kalsın.
   - `postgres` yönetici kullanıcısı için güçlü bir şifre belirleyin ve **not edin**.
   - Port **5432** kalsın. "Stack Builder" adımını atlayabilirsiniz.
3. PowerShell'i açıp PostgreSQL'e bağlanın (sürüm numarası farklıysa yolu düzeltin):

   ```powershell
   & "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres
   ```

4. `postgres=#` isteminde uygulamanın kullanıcısını ve veritabanını oluşturun (şifreyi değiştirin):

   ```sql
   CREATE ROLE arcbase LOGIN PASSWORD '<guclu_bir_sifre>';
   CREATE DATABASE arcbase OWNER arcbase ENCODING 'UTF8';
   \q
   ```

Tablolar uygulama ilk açıldığında kendiliğinden oluşturulur. PostgreSQL'in 5432 portunu güvenlik
duvarında **açmayın**: veritabanına yalnızca bu bilgisayardaki uygulama bağlanır.

## 3. Tesseract ve Türkçe dil paketi

1. <https://github.com/UB-Mannheim/tesseract/wiki> adresinden Windows 64 bit kurulum dosyasını indirin.
2. Kurulumda **"Additional language data"** altından **Turkish**'i işaretleyin.
3. Varsayılan klasör `C:\Program Files\Tesseract-OCR` kalsın. `.env`'de `TESSERACT_CMD` bu klasördeki
   `tesseract.exe`'yi gösterecek (6. adım).

Kontrol: `& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs` çıktısında `tur` görünmelidir.

## 4. Groq API anahtarı

1. <https://console.groq.com> adresinde kurum adına bir hesap açın.
2. **API Keys → Create API Key** ile bir anahtar oluşturun ve kopyalayın (yalnızca bir kez gösterilir).
3. Bu anahtar 6. adımda `.env`'e yazılacak. Anahtarı kimseyle paylaşmayın.

## 5. Python, proje, sanal ortam, paketler

1. <https://www.python.org/downloads/windows/> adresinden **Python 3.12 veya daha yeni** bir sürümü kurun.
   Kurulumun ilk ekranında **"Add python.exe to PATH"** kutusunu işaretleyin.
2. Proje dosyalarını `C:\ArcBase\uygulama` klasörüne koyun (Git ile `git clone <repo-adresi> C:\ArcBase\uygulama`
   ya da GitHub'dan ZIP indirip açarak).
3. PowerShell'de:

   ```powershell
   cd C:\ArcBase\uygulama
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

   Bu adım internetten paket indirir ve birkaç dakika sürer.

## 6. `.env` dosyasını doldurma

`C:\ArcBase\uygulama` içindeki `.env.example` dosyasını kopyalayıp adını `.env` yapın ve Not Defteri ile
açın. Aşağıdaki bloğu kendi değerlerinizle doldurup dosyaya yapıştırabilirsiniz:

```ini
GROQ_API_KEY=<4. adımdaki anahtar>
DATABASE_URL=postgresql://arcbase:<guclu_bir_sifre>@localhost:5432/arcbase
ENCRYPTION_KEY=<aşağıdaki komutla üretilen anahtar>
SECRET_KEY=<aşağıdaki komutla üretilen anahtar>
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

# Yerel mod: veritabanı bu bilgisayarda olmalı, bulut adresiyle uygulama başlamaz.
YEREL_MOD=1
PORT=5001

# Yönetici (Gelen belgeler kutusu); boşsa ilk kaydolan kullanıcı.
YONETICI_KULLANICI=

# Tarama klasörü (7. adım)
TARAMA_KLASORU=C:\ArcBase\Tarama
TARAMA_VARSAYILAN_KULLANICI=

# USB tarayıcıdan doğrudan tarama (7b); tarayıcı yoksa silin.
TARAYICI_WIA=1

# Yedekleme (9. adım)
YEDEK_KLASORU=C:\ArcBase\Yedekler
YEDEK_SAYISI=14
PG_DUMP=C:\Program Files\PostgreSQL\17\bin\pg_dump.exe

# Kullanıcı başına belge sınırı (varsayılan 50)
KULLANICI_BELGE_LIMITI=5000
```

Anahtarları üretmek için (PowerShell, `C:\ArcBase\uygulama` içinde):

```powershell
.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

İlki `ENCRYPTION_KEY`, ikincisi `SECRET_KEY` olur.

> ⚠️ **`ENCRYPTION_KEY` bir kez üretilir, asla değiştirilmez ve kaybedilmez.** Belgeler bu anahtarla
> şifrelenir; anahtar kaybolursa belgeler de yedekler de **açılamaz**. Hemen 9. adımdaki gibi ayrı bir
> yere yedekleyin.

## 7. Tarama klasörü ve tarayıcı ayarı

ArcBase tarayıcıdan gelen belgeleri iki yolla alır. İkisi birlikte de kullanılabilir.

### 7a. İzlenen klasör (ağ tarayıcıları ve tarayıcı yazılımları için)

`TARAMA_KLASORU` (ör. `C:\ArcBase\Tarama`) uygulama tarafından sürekli izlenir. Klasöre düşen JPG, PNG, PDF
ve TIFF dosyaları birkaç saniye içinde alınır, sınıflandırılır ve arşive eklenir.

```
C:\ArcBase\Tarama\                  ← sahibi belli olmayan belgeler
C:\ArcBase\Tarama\ayse\             ← "ayse" kullanıcısının belgeleri
C:\ArcBase\Tarama\...\islendi\2026-09-29\   ← alınan dosyalar buraya taşınır
C:\ArcBase\Tarama\...\hata\         ← alınamayanlar (yanında nedenini yazan .hata.txt)
```

- Her kullanıcının alt klasörü kullanıcı kaydolunca **kendiliğinden oluşur**. Klasörün adı kullanıcı
  adıyla aynıdır.
- Ana klasöre düşen dosyalar `TARAMA_VARSAYILAN_KULLANICI`'ya gider. Bu boşsa **yöneticinin "Gelen belgeler"
  kutusuna** gider; yönetici menüdeki **Gelen belgeler** sayfasından her belgeyi ilgili kullanıcıya atar ya
  da kendi arşivine alır. Atamalar kaydedilir (kim, hangi belgeyi, kime, ne zaman).
- Hiçbir dosya silinmez. Kotası dolan kullanıcının dosyası `hata\` klasörüne "Kota dolu" nedeniyle taşınır.
- Çok sayfalı TIFF tek belge (PDF) olarak kaydedilir. PDF'ler en fazla 5 MB, görseller en fazla 10 MB
  olabilir; daha büyükleri `hata\` klasörüne gider (çok sayfalı belgeleri gri ya da siyah-beyaz tarayın).

**Ağ tarayıcısı ("Klasöre tara / Scan to folder, SMB"):**

1. Tarayıcı için bir Windows kullanıcısı açın (ör. `tarayici`, şifreli): Ayarlar → Hesaplar → Diğer
   kullanıcılar → **Hesap ekle** → "Bu kişinin oturum açma bilgilerine sahip değilim" → "Microsoft hesabı
   olmadan kullanıcı ekle".
2. `C:\ArcBase\Tarama` klasörüne sağ tıklayın → **Özellikler → Paylaşım → Gelişmiş Paylaşım** →
   "Bu klasörü paylaş" → Paylaşım adı `Tarama` → **İzinler** → `tarayici` kullanıcısını ekleyip
   **Değiştir** iznini verin.
3. **Güvenlik** sekmesinde de `tarayici` kullanıcısına **Değiştir** izni verin.
4. Tarayıcının kendi ayar ekranında (genellikle tarayıcının IP adresi tarayıcıda açılarak girilir) "Scan to
   Folder / SMB / Ağ klasörü" hedefi ekleyin:
   - Adres: `\\<bu bilgisayarın IP adresi>\Tarama` (kişiye özel: `\\192.168.1.50\Tarama\ayse`)
   - Kullanıcı adı / şifre: 1. maddedeki `tarayici` hesabı
   - Dosya biçimi: **PDF** (çok sayfalı) ya da JPEG/TIFF, çözünürlük 300 dpi
5. Bir deneme sayfası tarayın; birkaç saniye sonra ArcBase'de görünmeli ve dosya `islendi\` altına
   taşınmalıdır.

**USB tarayıcı, üretici yazılımıyla:** Tarayıcının kendi yazılımında (ör. Canon IJ Scan Utility, Epson Scan,
HP Scan) **kayıt klasörünü** `C:\ArcBase\Tarama` (ya da kişiye özel alt klasör) olarak ayarlayın. Windows'un
**Tarayıcı** uygulamasında da "Kaydedilecek konum" bu klasör seçilebilir. **Windows Faks ve Tarama**
kullanılıyorsa taranan belgeyi "Farklı kaydet" ile bu klasöre kaydedin. USB tarayıcı için en kolay yol
aşağıdaki doğrudan taramadır.

### 7b. Uygulamadan doğrudan tarama (USB tarayıcı)

Ayar gerekmez: **uygulamanın çalıştığı bu bilgisayara** bağlı tarayıcı (USB ya da Windows'a eklenmiş ağ
tarayıcısı) birkaç saniye içinde kendiliğinden algılanır. Açık olan her sayfada **"Tarayıcı bulundu"**
bildirimi ve üst çubukta **Tara** düğmesi çıkar; tarayıcı çıkarılınca düğme kaybolur. (Kapatmak için
`.env`'e `TARAYICI_WIA=0`.)

- Tek tarayıcı varsa seçim sorulmaz; ayarlar hazırdır (300 dpi, renkli). Gelişmiş ayarlar küçük
  **Ayarlar** bağlantısının arkasındadır.
- Besleyicide (ADF) kâğıt varsa tüm sayfalar tek seferde alınır. Camlı yüzeyde her sayfadan sonra
  **Sonraki sayfa** ve **Bitir** çıkar; tüm sayfalar tek belge olur.
- Sayfalar, düğmeye basan kullanıcının arşivine eklenir.

**Windows'un tarama klasörleri de kendiliğinden izlenir:** Windows Faks ve Tarama ve yaygın tarayıcı
programlarının kayıt yerleri (Belgeler\Scanned Documents, Belgeler\Taranan Belgeler, Resimler\Scans,
Resimler\Taranan…). Oraya düşen dosya, ArcBase'te tek kullanıcı varsa onun arşivine, birden fazlaysa
yöneticinin **Gelen belgeler** kutusuna gider; dosya silinmez, **"ArcBase'e aktarıldı"** alt klasörüne
taşınır.

**Tarayıcınız başka bir klasöre kaydediyorsa:** menüde **Yönetim → Tarama klasörleri → Taradığım belgeler
görünmüyor**. Bir sayfa tarayın; ArcBase son 2 dakikada kaydedilen belgeleri önizlemeleriyle gösterir,
"Evet, bu" deyince o klasör izlenir. Ya da **Klasörü kendim seçeceğim** ile klasörü gezerek seçin. Bu
sayfa yalnızca yöneticiye ve sunucu bilgisayarının kendisinden (http://localhost:5001) açana görünür.
Durum için **Yönetim → Tarama durumu** sayfasına bakın.

- Tarayıcının Windows sürücüsü kurulu olmalıdır (üreticinin sitesinden). Windows'un **Tarayıcı**
  uygulamasında tarayıcı görünüyorsa ArcBase de görür.
- Tarayıcı yalnızca bu bilgisayara bağlıdır; ama "Tara" düğmesine yerel ağdaki başka bir bilgisayardan
  basılsa da tarama bu bilgisayardaki tarayıcıda yapılır. Kâğıdı tarayıcıya koyan kişi taramayı
  başlatmalıdır.
- Aynı anda tek tarama yapılır. Tarayıcı yok, meşgul ya da kâğıt sıkıştıysa ekranda açıklama çıkar.

## 8. Başlatma, otomatik başlatma, güvenlik duvarı

### Elle başlatma

`C:\ArcBase\uygulama\baslat.bat` dosyasına çift tıklayın. Açılan pencerede adresler yazar:

```
ArcBase çalışıyor. Tarayıcıdan şu adreslerden açabilirsiniz:
  Bu bilgisayardan:  http://localhost:5001
  Yerel ağdan:       http://192.168.1.50:5001
```

Pencere açık kaldıkça uygulama çalışır. İlk kaydolan kullanıcı **yönetici** olur (ya da
`YONETICI_KULLANICI`). Kurum personeli kendi kullanıcılarını **Kayıt ol** sayfasından açar.

### Bilgisayar açılınca otomatik başlatma (Görev Zamanlayıcı)

1. Başlat → **Görev Zamanlayıcı** → sağda **Görev Oluştur** (Temel görev değil).
2. **Genel:** Ad `ArcBase`. **"Kullanıcı oturum açmış olsun veya olmasın çalıştır"** seçin, "En yüksek
   ayrıcalıklarla çalıştır"ı işaretleyin.
   - Uygulamadan doğrudan tarama (7b, varsayılan açık) kullanılacaksa bunun yerine **"Yalnızca kullanıcı
     oturum açtığında çalıştır"** seçin: Windows, oturum açılmadan USB tarayıcıya erişim vermeyebilir.
     Bu durumda bilgisayarın otomatik oturum açması gerekir.
3. **Tetikleyiciler → Yeni:** "Görevi başlat: **Başlangıçta**" (oturum açıldığında seçtiyseniz "Oturum
   açıldığında").
4. **Eylemler → Yeni:** Program: `C:\ArcBase\uygulama\baslat.bat` · Bağımsız değişkenler: `/otomatik` ·
   Başlangıç yeri: `C:\ArcBase\uygulama`.
5. **Koşullar:** "Bilgisayar AC güçteyse başlat" işaretini kaldırın (dizüstü için).
6. **Ayarlar:** "Görev şundan uzun sürerse durdur" işaretini **kaldırın**; "Görev başarısız olursa yeniden
   başlat: 1 dakikada bir, 3 kez" seçin.
7. Tamam'a basınca Windows kullanıcı şifresini sorar.

Otomatik modda ekran açılmaz; çıktılar `C:\ArcBase\uygulama\logs\arcbase.log` dosyasına yazılır.

### Güvenlik duvarı (diğer bilgisayarlardan erişim)

PowerShell'i **yönetici olarak** açın (Başlat → PowerShell → sağ tık → Yönetici olarak çalıştır):

```powershell
New-NetFirewallRule -DisplayName "ArcBase" -Direction Inbound -Protocol TCP -LocalPort 5001 -Profile Private -Action Allow
```

Kural yalnızca **Özel** ağ profilinde geçerlidir. Ağın özel olarak tanımlı olduğunu kontrol edin: Ayarlar →
Ağ ve İnternet → bağlantı → **Ağ profili türü: Özel ağ**. Uygulamayı internete açmayın (modemde port
yönlendirme yapmayın).

**HTTPS:** Uygulama yerel ağda HTTP ile çalışır; oturum çerezleri buna göre ayarlıdır. Önüne TLS sağlayan
bir sunucu (ters vekil) konursa `.env`'e `HTTPS=1` ekleyin.

## 9. Yedekleme ve `ENCRYPTION_KEY`'i saklama

Yerel modda yedekleme **kurumun sorumluluğundadır**. `scripts\yedekle.py` veritabanının tarihli bir yedeğini
`YEDEK_KLASORU`'na alır ve en son `YEDEK_SAYISI` yedeği tutar (eskileri siler; klasördeki başka dosyalara
dokunmaz).

**Deneme:** `C:\ArcBase\uygulama\.venv\Scripts\python.exe C:\ArcBase\uygulama\scripts\yedekle.py`
→ "Yedek alındı: ..." yazmalıdır.

**Her gün otomatik yedek (Görev Zamanlayıcı):** 8. adımdaki gibi yeni görev: Ad `ArcBase yedek` ·
"Kullanıcı oturum açmış olsun veya olmasın çalıştır" · Tetikleyici **Günlük**, ör. 23:00 · Eylem: Program
`C:\ArcBase\uygulama\.venv\Scripts\python.exe`, Bağımsız değişkenler `scripts\yedekle.py`, Başlangıç yeri
`C:\ArcBase\uygulama`.

**Yedekleri başka yerde de saklayın:** Yedek klasörü aynı diskte durduğu için disk bozulursa yedekler de
gider. Haftada en az bir kez son yedeği harici diske ya da kurumun yedekleme sistemine kopyalayın.

**`ENCRYPTION_KEY`'i saklama:** `.env`'deki `ENCRYPTION_KEY` satırını kâğıda yazın ya da şifreli bir USB
belleğe/parola kasasına kaydedip **bilgisayardan ayrı**, kilitli bir yerde saklayın. Yedekler bu anahtar
olmadan açılamaz. Anahtarı yedeklerle aynı yere koymayın.

**Geri yükleme** (yeni ya da boşaltılmış bir `arcbase` veritabanına; 2. adımdaki gibi oluşturun):

```powershell
& "C:\Program Files\PostgreSQL\17\bin\pg_restore.exe" --no-owner -U arcbase -d arcbase "C:\ArcBase\Yedekler\arcbase_2026-09-29_230000.dump"
```

Geri yüklenen veritabanıyla uygulama **aynı `ENCRYPTION_KEY`** ile çalıştırılmalıdır.

## 10. Sorun giderme

| Belirti | Neden ve çözüm |
|---|---|
| Pencere açılıp "ArcBase başlatılamadı: YEREL_MOD=1 açık, ancak DATABASE_URL ..." yazıyor | `DATABASE_URL` bu bilgisayardaki veritabanını göstermiyor. `@localhost:5432/arcbase` olmalı. |
| "SECRET_KEY tanımlı değil" | `.env`'de `SECRET_KEY` boş; 6. adımdaki komutla üretin. |
| Sayfada "Veritabanı hatası" | PostgreSQL hizmeti çalışmıyor ya da şifre yanlış. Başlat → **Hizmetler** → `postgresql-x64-17` → Başlat. `.env`'deki şifreyi kontrol edin. |
| Belgelerin türü hep "Diğer", "servise ulaşılamadı" uyarısı | **Groq'a ulaşılamıyor.** İnterneti kontrol edin; kurum güvenlik duvarı/proxy `api.groq.com` (HTTPS, 443) adresine izin vermeli. `GROQ_API_KEY`'in doğru olduğunu kontrol edin. Bağlantı gelince belge sayfasından **Yeniden analiz**. |
| "Metin okunamadı" | Tesseract ya da Türkçe paketi eksik: 3. adımı ve `TESSERACT_CMD` yolunu kontrol edin. |
| **Tarayıcı görünmüyor** ("Tarayıcı bulunamadı") | Tarayıcı açık ve USB takılı mı? Sürücü kurulu mu (**Windows Faks ve Tarama**'da görünüyor mu)? Başlat → Hizmetler → **Windows Görüntü Alma (WIA)** çalışıyor mu? Görev Zamanlayıcı ile oturum açılmadan başlatıldıysa 8. adımdaki notu okuyun. `.env`'de `TARAYICI_WIA=0` olmamalı. Teknik ayrıntı `logs\arcbase.log`'dadır. |
| Tarayıcının kendi düğmesiyle taranan belgeler gelmiyor | **Yönetim → Tarama klasörleri → Taradığım belgeler görünmüyor** ile tarayıcının kaydettiği klasörü ekleyin. |
| "Tarayıcı şu an meşgul" | Başka bir program (üretici yazılımı) tarayıcıyı kullanıyor; kapatıp yeniden deneyin. |
| **Klasör işlenmiyor** (dosyalar klasörde kalıyor) | Uygulama çalışıyor mu? `.env`'de `TARAMA_KLASORU` doğru mu? Dosya uzantısı JPG/PNG/PDF/TIF mi? Hiç kullanıcı yoksa ana klasördeki dosyalar ilk kullanıcı kaydolunca alınır. `logs\arcbase.log`'a bakın. |
| Dosyalar `hata\` klasörüne gidiyor | Yanındaki `.hata.txt` nedeni yazar (kota dolu, dosya çok büyük, kullanıcı klasörü adı yanlış...). Sorunu giderip dosyayı ilgili klasöre geri taşıyın. |
| Ağ tarayıcısı klasöre kaydedemiyor | Paylaşım ve Güvenlik izinlerini (7a, 2-3. maddeler), tarayıcıdaki kullanıcı adı/şifreyi ve adresi kontrol edin. Bazı eski tarayıcılar yalnızca SMB1 destekler; üretici yazılımını güncelleyin. |
| **Giriş yapılamıyor** (şifre doğru ama tekrar giriş sayfasına dönüyor) | `.env`'de `HTTPS=1` varken HTTP ile bağlanılıyor olabilir; satırı silip uygulamayı yeniden başlatın. Adresi `http://` ile yazın. |
| "Çok fazla deneme yaptınız" | Kısa sürede çok hatalı giriş denendi; birkaç dakika bekleyin. |
| Diğer bilgisayarlardan açılmıyor | Güvenlik duvarı kuralı (8. adım), ağ profilinin **Özel** olması ve adresin doğru IP ile yazılması. Bu bilgisayarda `http://localhost:5001` açılıyor mu? |
| "Belge kotanız doldu" | `.env`'de `KULLANICI_BELGE_LIMITI`'ni artırıp uygulamayı yeniden başlatın. |

## 11. Veri akışı

| Veri | Nerede durur | Dışarı gider mi? |
|---|---|---|
| Belge dosyaları (görsel, PDF) | Bu bilgisayardaki PostgreSQL veritabanında, **şifreli** (Fernet) | **Hayır** |
| Kullanıcılar, şifreler (hash), belge bilgileri | Bu bilgisayardaki PostgreSQL | **Hayır** |
| Tarama klasörü dosyaları | `TARAMA_KLASORU` altında (`islendi\`, `hata\`); **şifresizdir**, klasör izinlerini kısıtlayın | **Hayır** |
| Yedekler | `YEDEK_KLASORU`; belgeler yedekte de şifreli | **Hayır** (kurum kendisi kopyalar) |
| `ENCRYPTION_KEY`, `.env` | Bu bilgisayarda (ve kâğıt/kasadaki kopyası) | **Hayır** |
| **OCR ile okunmuş metin** | Veritabanında; türü ve bilgileri belirlemek için **Groq'a gönderilir** | **Evet — yalnızca metin** |

- Uygulamanın dışarıya yaptığı **tek** bağlantı Groq API çağrısıdır (`api.groq.com`, HTTPS). Groq'a yalnızca
  belgenin okunmuş **metni** gider; görsel, dosya, kullanıcı bilgisi ve veritabanı içeriği **gitmez**. Metin
  belgede ne yazıyorsa odur: kimlik belgesinin metninde TC kimlik numarası da bulunur ve Groq'a gider;
  ancak TC kimlik numarası, doğum tarihi ve seri numarası belgenin bilgi alanlarına yazılmaz.
- Metin tanıma (Tesseract), kırpma/düzeltme (OpenCV), PDF/Word/Excel üretimi bu bilgisayarda yapılır.
- Arayüz (yazı tipi, ikonlar, JavaScript) uygulamayla birlikte gelir; kullanıcıların tarayıcısı da
  dışarıya (CDN, Google Fonts) istek atmaz.
- `YEREL_MOD=1` iken uygulama, veritabanı adresi bu bilgisayar ya da yerel ağ dışında bir yeri (bulut)
  gösteriyorsa **hiç başlamaz**.
- Groq'a metin de gönderilmesin istenirse `GROQ_API_KEY` boş bırakılabilir: belgeler yine okunur,
  şifrelenir ve aranabilir; yalnızca türü "Diğer" olur (belge sayfasında uyarı görünür), tür ve bilgi
  alanları elle seçilir.

---

## Ek A. Buluttaki arşivi taşıma (isteğe bağlı)

Daha önce bulut sürümünde (Neon) kullanılan kullanıcılar ve belgeler yerel veritabanına taşınabilir.
Kurum sıfırdan başlayacaksa bu eki atlayın.

1. Bulut uygulamasına taşıma bitene kadar belge **yüklemeyin** (sonradan yüklenenler taşınmaz).
2. `.env`'de: `DATABASE_URL` hâlâ bulut (Neon) adresi, `YEREL_DATABASE_URL` yerel adres
   (`postgresql://arcbase:<sifre>@localhost:5432/arcbase`), `ENCRYPTION_KEY` **bulut uygulamasıyla aynı**
   olmalı. `YEREL_MOD=1` bu sırada yazılmamış olmalı.
3. Taşıma:

   ```powershell
   cd C:\ArcBase\uygulama
   .venv\Scripts\python.exe scripts\veri_tasi.py
   ```

   Betik iki taraftaki sayıları gösterir, hedef boş değilse durur, anahtarın belgeleri çözebildiğini
   dener ve **"evet"** yazmanızı ister. Kopyalamadan sonra her kaydı iki tarafta karşılaştırır; fark varsa
   hiçbir şeyi kaydetmez. Buluttaki veriye dokunmaz.
4. "Doğrulama başarılı" yazınca `.env`'de `DATABASE_URL`'i yerel adresle değiştirin ve `YEREL_MOD=1`
   ekleyin; uygulamayı başlatın.

## Ek B. Gerçek tarayıcıyla kontrol listesi

Otomatik testler tarayıcıyı taklit eder; kurulumdan sonra gerçek tarayıcıyla bir kez şunları deneyin:

**Doğrudan tarama (7b):**

- [ ] **Tarayıcıdan tara** sayfasında tarayıcının adı listeleniyor.
- [ ] Camlı yüzeyden 300 dpi **renkli** tek sayfa → belge açılıyor, türü belirleniyor.
- [ ] 200 dpi **gri** ve **siyah-beyaz** tarama → görüntü beklenen renkte.
- [ ] Besleyiciye 3 sayfa koyup **Besleyiciden tara** → tek PDF belge, 3 sayfa.
- [ ] Besleyici boşken besleyiciden tarama → "Besleyicide kâğıt yok" mesajı.
- [ ] Tarayıcı kapalıyken sayfa açılıyor, "Bağlı tarayıcı bulunamadı" yazıyor, uygulama çalışmaya devam ediyor.
- [ ] Tarama sürerken ikinci bir bilgisayardan tarama → "başka bir tarama yapıyor" mesajı.
- [ ] Kotası dolu kullanıcı → "Belge kotanız doldu", tarayıcı çalışmıyor.
- [ ] Başka bir bilgisayardan giriş yapıp tarama → belge o kullanıcının arşivinde.

**İzlenen klasör (7a):**

- [ ] Ağ tarayıcısından kişiye özel klasöre tarama → birkaç saniyede o kullanıcının arşivinde; dosya
  `islendi\<tarih>\` altında.
- [ ] Ana klasöre tarama → yöneticinin **Gelen belgeler** kutusunda; bir kullanıcıya atanınca o kullanıcıda
  görünüyor, belge sayfasında "Gelen belgelerden atandı" yazıyor.
- [ ] Çok sayfalı PDF ve çok sayfalı TIFF tarama → tek belge.
- [ ] Büyük (uzun) bir taramanın yazımı sürerken yarım dosya alınmıyor; bitince alınıyor.
- [ ] Desteklenmeyen bir dosya (ör. `.txt`) → `hata\` klasöründe, yanında nedeni.
- [ ] Uygulama kapalıyken klasöre düşen dosyalar uygulama açılınca alınıyor.
