# ArcBase

**Dijital arşiv ve belge sınıflandırma sistemi**

Telefonla çekilmiş yamuk, gölgeli bir belge fotoğrafını **tarayıcıdan çıkmış gibi görünen bir belgeye**
dönüştüren ve **aranabilir A4 PDF** olarak veren bir "tarayıcı + arşiv" uygulaması. Fotoğraf **OpenCV** ile
kırpılıp düzeltilir ve tarama filtresinden geçirilir, **Tesseract OCR** ile metne çevrilir, **Groq** üzerindeki
bir dil modeliyle türü (fatura, sözleşme, kimlik, dilekçe, resmi yazı, diğer) belirlenip **tarih, tutar, kurum
gibi bilgileri çıkarılır**; dosya **Fernet ile şifrelenerek PostgreSQL'de** saklanır. Çok kullanıcılı bir
Flask web uygulamasıdır.

Her kullanıcı kayıt olup giriş yapar ve **yalnızca kendi belgelerini** görür.

Bulutta (Neon + Render) ya da **kurumun kendi Windows bilgisayarında, belgeler ve veritabanı dışarı
çıkmadan** (yerel mod) çalışır; yerel modda tarayıcıdan gelen belgeler izlenen bir klasörden ya da doğrudan
bağlı tarayıcıdan alınıp arşivlenir. Bkz. [Yerel mod](#yerel-mod-kurum-kurulumu) ve [Veri akışı](#veri-akışı).

> **Canlı site:** _yayına alındıktan sonra buraya eklenecek_ (Render ücretsiz katmanında çalışır; site
> bir süre boşta kalınca uykuya geçer, ilk açılış 30-60 saniye sürebilir.)

![Panel](docs/screenshots/panel.png)

## Özellikler

- **Arka planda işleme (v6):** Yükleme beklemez; dosya şifrelenip kaydedilir ve belge listede hemen
  **"İşleniyor"** rozetiyle görünür. Köşe algılama, OCR, sınıflandırma ve bilgi çıkarma arka plandaki bir
  işçi iş parçacığında yapılır; sayfa hazır olunca kendiliğinden güncellenir. İş durumu veritabanında tutulur,
  uygulama yeniden başlarsa yarım kalan işler kaldığı aşamadan devam eder (Redis/Celery gerekmez)
- **Hız (v6):** Bağlantı havuzu, sayfa başına 2 sorgu, işlenmiş görsel önbelleği + tarayıcı önbelleği
  (ETag), derlenmiş Tailwind CSS; sayfalar ~15 kat, yükleme ~7–16 kat hızlı ([Performans](#performans))
- **Tarama filtresi (v5):** Gölge ve sarı ışık temizlenir, kâğıt beyazlar; **renkli** (varsayılan — mavi
  mürekkep, kırmızı/mor mühür, renkli logolar korunur), **gri** ve **siyah-beyaz** modlar. Detay sayfasında
  mod seçici ve sürüklenebilir "önce | sonra" karşılaştırması
- **Güçlü yamukluk düzeltme (v5):** Dört farklı yöntemle köşe adayları üretilip puanlanır (beyaz masada beyaz
  kâğıt dahil), yazı satırları tam yatay olacak şekilde ince eğiklik düzeltilir; **köşeler elle ayarlanabilir**
  (fare/dokunmatik, büyüteç). Emin olunamayan kırpmalarda "Kırpmayı kontrol et" önerilir
- **Taranmış belge algılama:** Tarayıcı çıktısı JPG/PNG'ler (kenarları düz beyaz, arka plan ve perspektif
  yok) otomatik tanınır; kırpma ve perspektif düzeltmesi yapılmaz, yalnızca ±3° eğiklik düzeltilir ve belge
  sayfasında **"Taranmış belge, kırpma uygulanmadı"** rozeti gösterilir. Belgenin içindeki çerçeve veya
  tablo hiçbir zaman kâğıt kenarı sanılıp kırpılmaz
- **Aranabilir A4 PDF (v5):** Görünmez metin katmanlı; metin seçilebilir ve Ctrl+F ile aranabilir. Seçilen
  belgeler **tek PDF'te birleştirilebilir** (yer imleriyle, en fazla 20 belge)
- **Word'e aktarma (v5):** Belge bilgileri tablosu ve okunan metin `.docx` olarak indirilir
- **Otomatik sınıflandırma:** OCR ile okunan metin yapay zekaya gönderilir, belge türü ve güven skoru belirlenir
- **Bilgi çıkarma (v4):** Aynı istekte türe göre önemli alanlar çıkarılır (fatura: firma, tutar, para birimi,
  tarih, fatura no · sözleşme: taraflar, tarih, konu, süre · dilekçe / resmi yazı: kurum, konu, sayı, tarih ·
  kimlik: belge türü, geçerlilik tarihi). Alanlar elle düzeltilebilir. Kimlik belgelerinde **TC kimlik no,
  doğum tarihi ve seri numarası çıkarılmaz ve saklanmaz.**
- **Filtre, sıralama, fatura özeti (v4):** Belge tarihi aralığı, kurum, tutar aralığı; yüklenme tarihi / belge
  tarihi / tutara göre sıralama; fatura kategorisinde seçili filtreye göre toplam tutar
- **Toplu yükleme (v4):** Tek seferde 10 dosyaya kadar sürükle-bırak; her dosyanın durumu (yükleniyor →
  işleniyor → türü) ayrı gösterilir, bir dosyadaki hata diğerlerini durdurmaz
- **Excel'e aktarma (v4):** Liste ve çıkarılan bilgiler, sayfadaki filtrelerle `.xlsx` olarak indirilir
- **Kategoriler ve arama:** Belgeler türüne göre kategorilere ayrılır; dosya adında, belgenin içindeki metinde
  ve çıkarılan bilgilerde (kurum, konu, fatura no…) arama yapılır
- **Kullanıcı hesapları:** Kayıt, giriş, "beni hatırla", şifre değiştirme, hesap silme
- **Veri ayrımı:** Her sorgu giriş yapan kullanıcıya göre filtrelenir; başkasının belgesine erişim denemesi 404 döner
- **Şifreli saklama:** Dosyalar ve önizlemeler veritabanına yazılmadan önce Fernet ile şifrelenir
- **Düzeltme:** Güven %60'ın altındaysa belge "Kontrol edilmeli" olarak işaretlenir, tür tek tıkla düzeltilir
- **PDF desteği:** Çok sayfalı PDF'lerin ilk 3 sayfası okunur (metin katmanı olan sayfalar OCR'sız,
  taranmış sayfalar paralel), ilk sayfa önizlenir
- **Depolama tasarrufu:** Görseller en fazla 2000 px'e küçültülüp JPEG olarak saklanır (EXIF temizlenir);
  OCR tam çözünürlüklü dosyadan yapılır
- **Güvenlik:** Şifreler hash'lenir, tüm formlarda CSRF koruması, giriş denemelerine hız sınırı
- **Arayüz:** Açık/koyu tema, mobil uyumlu, animasyonlu modern tasarım

## Ekran görüntüleri

| Belge detayı: renkli tarama ve çıkarılan bilgiler | Önce \| sonra karşılaştırması |
|---|---|
| ![Belge](docs/screenshots/belge.png) | ![Önce sonra](docs/screenshots/tarama-karsilastirma.png) |
| **Elle köşe ayarlama (büyüteçle)** | **Seçilen belgeleri tek PDF'te birleştirme** |
| ![Köşe ayarlama](docs/screenshots/kose-duzenleme.png) | ![Seçim ve birleştirme](docs/screenshots/secim-birlestirme.png) |
| **Fatura filtreleri ve toplam tutar** | **Toplu yükleme (sürerken)** |
| ![Fatura filtreleri](docs/screenshots/fatura-filtre.png) | ![Toplu yükleme](docs/screenshots/toplu-yukleme.png) |
| **Hesap: kota ve mevcut belgelerden bilgi çıkarma** | **Açılış sayfası** |
| ![Hesap](docs/screenshots/hesap.png) | ![Açılış](docs/screenshots/acilis.png) |
| **Koyu tema** | |
| ![Koyu tema](docs/screenshots/panel-koyu.png) | |


<p align="center">
  <img src="docs/screenshots/mobil-giris.png" width="240" alt="Mobil giriş">
  <img src="docs/screenshots/mobil-panel.png" width="240" alt="Mobil panel">
  <img src="docs/screenshots/mobil-menu.png" width="240" alt="Mobil menü">
</p>

## Kullanılan teknolojiler

| Katman | Teknoloji |
|---|---|
| Web çatısı | Flask, Jinja2 |
| Oturum / güvenlik | Flask-Login, Flask-WTF (CSRF), Flask-Limiter, werkzeug.security (scrypt hash) |
| OCR | Tesseract (Türkçe dil paketi), pytesseract, Pillow, PyMuPDF (PDF) |
| Görüntü düzeltme ve tarama filtresi | OpenCV (`opencv-python-headless`), NumPy |
| Aranabilir PDF | Tesseract metin katmanı (`textonly_pdf`) + PyMuPDF (A4 yerleşim, birleştirme, yer imleri) |
| Word | python-docx |
| Sınıflandırma + bilgi çıkarma | Groq API (OpenAI uyumlu istemci, varsayılan model `openai/gpt-oss-120b`) |
| Excel | openpyxl |
| Veritabanı | PostgreSQL (Neon ya da yerel), psycopg2 |
| Şifreleme | cryptography (Fernet) |
| Arayüz | Tailwind CSS (standalone CLI ile önceden derlenmiş statik CSS), sade JavaScript |
| Arka plan işleri | Uygulama içi işçi iş parçacığı, kuyruk PostgreSQL'de (`FOR UPDATE SKIP LOCKED`) |
| Yayın | Docker, gunicorn, Render · Windows'ta waitress (yerel mod) |
| Tarayıcı entegrasyonu | watchdog (izlenen klasör), pywin32 + WIA (bağlı tarayıcı, yalnızca Windows) |

## Mimari

```mermaid
flowchart LR
    K[Kullanıcı<br/>tarayıcı] -->|HTTPS| F

    subgraph F[Flask uygulaması]
        direction TB
        G[Flask-Login oturum<br/>CSRF · hız sınırı] --> Y[/yukle/<br/>sıkıştır + şifrele]
        Y -->|tam çözünürlüklü dosya<br/>bellekte| I
        subgraph I[isleme.py — arka plan işçisi]
            direction TB
            R[goruntu_duzelt.py<br/>köşe algılama] --> T[tarama.py<br/>gri tarama]
            T --> O[ocr.py<br/>Tesseract OCR]
            O --> C[classifier.py<br/>+ alanlar.py doğrulama]
        end
        X["/disa-aktar<br/>excel.py (Excel)"]
        P["/tarama · /pdf · /word<br/>tarama.py · pdf_uret.py · word_uret.py<br/>+ görsel önbelleği"]
        Z["/isleme-durumu<br/>tarayıcı yoklaması"]
    end

    C -->|OCR metni| Q[(Groq API)]
    Q -->|tür, güven, açıklama, alanlar| C
    Y -->|belge: bekliyor| D[(PostgreSQL<br/>kullanicilar · belgeler<br/>+ iş kuyruğu sütunları)]
    I <-->|iş al · aşama sonucu · tamamla| D
    D -->|kullanici_id ile filtrelenmiş sorgular<br/>bağlantı havuzu| F
    D --> X
    D -->|orijinal + köşeler| P
    D --> Z
```

**Yükleme akışı:**

1. Kullanıcı en fazla 10 dosya seçer (JPG / PNG en fazla 10 MB, PDF en fazla 5 MB). Tarayıcı dosyaları
   **sırayla, tek tek** `POST /yukle`'ye gönderir (fetch, JSON cevap). Seçilen dosya sayısı kalan kotayı
   (varsayılan 50 belge) aşarsa yükleme hiç başlamaz
2. **Yükleme isteği (kullanıcının beklediği kısım):** dosya doğrulanır; görselin EXIF yönü uygulanır,
   **düzeltilmemiş orijinal** en fazla 2000 px'e küçültülüp JPEG (kalite 85) yapılır ve kırpılmamış hızlı
   bir önizleme üretilir. Dosya ve önizleme Fernet ile şifrelenip `belgeler` tablosuna `BYTEA` olarak,
   kullanıcının id'siyle ve `isleme_durumu = 'bekliyor'` olarak yazılır. Tam çözünürlüklü dosya işçiye
   bellekte bırakılır (veritabanına gidip geri gelmez) ve cevap hemen döner. PDF olduğu gibi saklanır
3. **Arka plan işçisi — görüntü aşaması:** "Otomatik kırp ve düzelt" açıksa (varsayılan) belgenin köşeleri
   bulunur (PDF'lere uygulanmaz). OCR, köşelerle düzeltilmiş, **OCR çözünürlüğüne (uzun kenar 2400 px ≈ A4'te
   200 DPI) indirilmiş** ve **gri tarama filtresinden geçmiş** görüntüde **bir kez** yapılır (gölgeli/sarı
   ışıklı fotoğraflarda okuma belirgin şekilde iyileşir). Köşeler saklanan görselin koordinatlarına
   ölçeklenir, önizleme düzeltilmiş halden üretilir. PDF'te metin katmanı olan sayfalar OCR'sız okunur,
   taranmış sayfalar (ilk 3) paralel Tesseract süreçleriyle okunur. Sonuç veritabanına yazılır
4. **Sınıflandırma aşaması:** metnin ilk 4000 karakteri Groq'a **tek istekte** gönderilir;
   `{"tur", "guven", "aciklama", "alanlar"}` JSON'u istenir. Alanlar Python tarafında doğrulanır
   (`alanlar.py`): tarih `YYYY-MM-DD`, tutar sayı, para birimi ISO kodu olmalı; geçersiz değer `NULL`
   kaydedilir, türde tanımlı olmayan alanlar atılır. Belge `tamamlandi` olur
5. Tarayıcı `/isleme-durumu`'nu kısa aralıklarla yoklar; belge hazır olunca kart, detay sayfası ve menü
   sayaçları kendiliğinden güncellenir
6. Gösterim, tarama önizlemesi, PDF ve Word istek anında üretilir: orijinal çözülür, köşeler uygulanır,
   seçilen tarama filtresi geçirilir. Böylece depolama artmaz ve köşeler sonradan değiştirilebilir. Üretilen
   görseller süreç içi önbellekte tutulur (bkz. [Performans](#performans))

OCR veya Groq hatası yüklemeyi durdurmaz: belge `diğer` / güven 0 olarak tamamlanır ve detay sayfasında
uyarı gösterilir. Groq hız sınırına (HTTP 429) ya da bağlantı hatasına takılan iş birkaç saniye sonra
(5 sn, 20 sn) yeniden denenir; yine olmazsa "Yapay zeka şu an yoğun" uyarısıyla tamamlanır ve "Yeniden dene"
ile sonradan sınıflandırılabilir. JavaScript kapalıyken form normal gönderilir, yalnızca ilk dosya işlenir
ve belge sayfası iş bitene kadar birkaç saniyede bir kendini yeniler.

## Arka planda işleme

Harici servis (Redis, Celery…) yoktur; kuyruk `belgeler` tablosunun `isleme_*` sütunlarıdır (`isleme.py`):

| Durum | Anlamı |
|---|---|
| `bekliyor` | Yüklendi, sırada (ertelenmiş işte `isleme_zamani` en erken deneme zamanıdır) |
| `isleniyor` | Bir işçi aldı; `isleme_zamani` son kalp atışıdır |
| `tamamlandi` | Tür ve bilgiler belirlendi (v6 öncesi tüm belgeler bu durumdadır) |
| `hata` | 6 denemede bitirilemedi; detay sayfasında "Yeniden işle" |

- Her süreçte (gunicorn worker) bir işçi iş parçacığı çalışır; worker açılır açılmaz başlar
  (`gunicorn.conf.py`). İş `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)` ile alınır; aynı iş
  iki sürece verilmez.
- İş iki aşamalıdır ve her aşamanın sonucu veritabanına yazılır (`isleme_bilgi.asama`). Uygulama yeniden
  başlarsa `bekliyor` işler hemen, kalp atışı 3 dakikayı geçmiş `isleniyor` işler (ölmüş işçinin işi)
  kaldığı aşamadan devam eder: OCR yapılmışsa tekrarlanmaz, yalnızca sınıflandırma yapılır. Tam
  çözünürlüklü dosya bellekten gittiyse OCR saklanan 2000 px görselden yapılır.
- İşçi boştayken veritabanını yoklamaz (Neon uykuya geçebilsin): yeni yükleme işçiyi uyandırır; ertelenmiş
  ya da başka süreçte yarım kalmış iş varsa yalnızca onun zamanına kadar bekler.
- İşlenirken kullanıcı türü elle seçerse işçi onu korur ve yalnızca o türün bilgilerini çıkarır. İşlenen
  belgede köşe ayarlama ve yeniden analiz kapalıdır; silme ve indirme açıktır.

## Bilgi çıkarma

| Tür | Çıkarılan alanlar |
|---|---|
| Fatura | firma, tutar, para birimi, fatura tarihi, fatura no |
| Sözleşme | taraflar, sözleşme tarihi, konu, süre |
| Dilekçe | muhatap kurum, konu, tarih |
| Resmi yazı | kurum, konu, sayı, tarih |
| Kimlik | belge türü (kimlik kartı, ehliyet, pasaport…), geçerlilik tarihi |
| Diğer | konu, tarih (bulunursa) |

- Filtrelenen/sıralanan alanlar (`belge_tarihi`, `tutar`, `para_birimi`, `kurum`) ayrı sütunlarda, diğerleri
  `alanlar` (JSONB) içinde tutulur.
- Modelden metinde olmayan alan için `null` dönmesi, uydurmaması istenir.
- **Gizlilik:** Prompt'ta kimlik belgelerinden TC kimlik numarası, doğum tarihi ve seri numarasının
  çıkarılmaması açıkça istenir. Buna ek olarak kimlik türünde yalnızca tanımlı iki alan kabul edilir, 5+ haneli
  rakam dizisi içeren metin alanları reddedilir ve açıklamadaki 11 haneli numaralar maskelenir. (OCR metni
  v3'te olduğu gibi aramada kullanılmak üzere saklanmaya devam eder.)
- Belge detayındaki "Belge bilgileri" kartından alanlar elle düzeltilebilir; düzeltilen belge işaretlenir.
- v4 öncesinden kalan belgeler için **Hesabım → Mevcut belgelerden bilgi çıkar**: kayıtlı OCR metni üzerinden
  (yeniden OCR yapmadan) belgeler sırayla işlenir ve ilerleme gösterilir; tür değişmez, elle düzeltilmiş
  alanlara dokunulmaz.

## Tarama

![Tarama öncesi ve sonrası (sentetik)](docs/screenshots/tarama-once-sonra-sentetik.jpg)

`tarama.py` her renk kanalı için yazısız "kâğıt ışığı" haritasını tahmin eder ve kanalı bu haritaya **böler**:
gölge ve sarı ışık kaybolur, kâğıt beyaz olur; arka plandan koyu olan her şey — siyah yazı, mavi mürekkep,
kırmızı mühür, renkli logo — rengini korur. Harita iki tahminin büyüğüdür: ince tahmin (küçültülmüş kopyada
`dilate` + `medianBlur`) yazıyı siler; kaba tahmin (karo başına en parlak %10, kenarlarda doğrusal uzatılır) QR
kod, logo ve mühür gibi büyük koyu alanların ince tahmini aşağı çekip **solmasını ve çevresinde hale oluşmasını**
önler, vinyetli kenarlarda gri şerit bırakmaz. Ardından eşikli keskinleştirme (kâğıt dokusu ve gürültü
büyütülmez), siyah/beyaz noktası ve ara tonları koyulaştıran eğri uygulanır (neredeyse beyaz pikseller tam beyaz,
bulanık yazı gövdesi koyu) ve kenardan birkaç piksellik şerit kırpılır.

| Mod | Yöntem | Not |
|---|---|---|
| Renkli (varsayılan) | Kanal başına arka plana bölme + seviye ayarı | Telefonların "belge tara" çıktısına benzer |
| Gri | Aynı normalizasyon gri tonda + CLAHE | OCR girdisi olarak da kullanılır |
| Siyah-beyaz | Uyarlamalı eşik (Gaussian) + küçük leke temizliği | En küçük PDF; mühür ve imzalar silik çıkabilir |

2000 px'lik bir görselde her mod ~0,2 saniyede, 300 DPI A4 sayfada ~0,5 saniyede çalışır. PDF olarak yüklenen belgelere filtre
uygulanmaz. Detay sayfasındaki mod seçici görseli `GET /tarama/<id>?mod=…` ile sayfa yenilenmeden değiştirir;
son seçilen mod tarayıcıda hatırlanır; "Önce | sonra" filtresiz fotoğrafı seçili modla sürüklenebilir bir
ayırıcıyla karşılaştırır.

> **Görseller hakkında:** Yukarıdaki öncesi/sonrası görseli gerçek fotoğraf değil, `tests/ornek_gorseller.py`
> ile üretilmiş sentetik çekimlerdir (sarı ışık, gölge, ~30° dönük ve hafif perspektifli A4; açık renkli masada
> beyaz kâğıt; mühür ve imza). Kendi fotoğraflarınızla aynı görseli üretmek için:
> ```bash
> python docs/once_sonra.py foto1.jpg foto2.jpg --cikti docs/screenshots/tarama-once-sonra.jpg
> ```
> Fotoğraflar yalnızca yerelde işlenir, veritabanına yüklenmez.

## Kırpma ve yamukluk düzeltme

`goruntu_duzelt.py` tüm geometrik düzeltmeyi **dört köşeyle** ifade eder:

0. **Taranmış belge kontrolü:** Görüntünün dört kenar şeridi düz ve açık renkliyse (beyaz/krem kâğıt; masa,
   gölge, nesne yok), şeritler birbirine ve sayfanın içindeki kâğıt rengine yakınsa (ışık azalması, arka plan
   yok) ve yazı satırlarının açısı sayfanın üst/alt ve sol/sağ yarısında aynıysa (perspektif yok) görüntü
   **taranmış belge** sayılır: kırpma ve perspektif düzeltmesi yapılmaz, "Kırpmayı kontrol et" önerilmez,
   yalnızca ±3°'ye kadar eğiklik düzeltilir. Belge sayfasında "Taranmış belge, kırpma uygulanmadı" rozeti
   çıkar; algılama yanlışsa rozetten köşe düzenleyici açılıp elle kırpılabilir (elle kaydedilince rozet
   kalkar). "Otomatik kırp ve düzelt" anahtarı (varsayılan açık) düzeltmeyi tamamen kapatmak için kalır
1. **Aday üretimi** (küçültülmüş kopyada):
   - **Kenar çizgileri:** Lab kanallarında Canny + `HoughLinesP`; aynı doğru üzerindeki parçalar birleştirilir.
     Her yönde (yatay/dikey) en çok desteklenen 10 çizgi ve görüntünün kendi kenarları eşleştirilip dörtgenler
     kurulur; köşeler çizgilerin kesişimidir, bu yüzden **kadraj dışında kalan köşeler** de bulunur
   - **Maskeler:** iki hassasiyette Canny, parlaklık eşiği (Otsu), masa rengine Lab uzaklığı ve "beyazlık"
     maskelerinin konturları (`convexHull` + `approxPolyDP`)
2. **Kontrast puanı** (tüm adaylar için aynı): dörtgenin her kenarı boyunca iç taraf kâğıt renginde, dış taraf
   ondan belirgin şekilde farklı (daha koyu ya da renkçe uzak) mı? Kâğıtla aynı renkteki **beyaz duvar veya
   parlak masa yansıması** bu ölçüte takılır; yazı satırı (iç taraf mürekkep) ve kâğıt dışındaki masa/laptop
   sınırı (iç taraf ahşap) kenar sayılmaz. Hafif kavisli kâğıt için gerçek kenarın çizgiye birkaç piksel yakın
   olması yeterlidir. Kadrajda görünmeyen (**görüntü kenarına dayanan**) kenar destek almaz. **Çerçeve/tablo
   koruması:** koyu bir çerçeve çizgisi de bu ölçüte uyar; bu yüzden her kenarın iki yanına çizginin birkaç kat
   ötesinden bakılır — dışı en az üç kenarda da kâğıt renginde olan dörtgen (belgenin içindeki çerçeve ya da
   tablo) reddedilir. Seçilen dörtgenin kenarları yakındaki Canny piksellerine yeniden oturtulur
3. **Güven:** puan kenar desteklerinin ortalamasıdır; zayıf bir kenar varsa puan 0,8'in altında kalır ve toplu
   yükleme listesinde ve belge sayfasında **"Kırpmayı kontrol et"** bağlantısı çıkar (köşeler elle
   kaydedilince kalkar); iki zayıf kenarlı dörtgen belge sayılmaz
4. **İnce eğiklik:** perspektif düzeltmesinden sonra yazı satırlarının açısı izdüşüm profiliyle ölçülür
   (±5°) ve köşelere katlanır; belge bulunamazsa aynı yöntemle ±15° (taranmış belgede ±3°) eğiklik düzeltilir
5. **Boyut:** kâğıdın gerçek en-boy oranı perspektiften tahmin edilir (Zhang–He; kameraya eğik tutulan kâğıt
   fotoğrafta basık görünür). Dörtgen makul bir telefon odağıyla (uzun kenarın 0,55–1,6 katı) A4 olabiliyorsa
   (±%5) tam A4 üretilir: kaynak yetiyorsa **300 DPI (2480×3508)**, çok küçük fotoğrafta en az 150 DPI.
   Perspektifsiz dörtgenlerde (4:3 kart, fiş) oran olduğu gibi kalır. Kadraj dışına taşan kâğıt bölgesi, fotoğrafın en dış birkaç pikseli
   atlanarak kenar pikselleriyle doldurulur

| Senaryo (sentetik, 3000×2250) | v4 algılaması | v6 köşe hatası | v6 kalan eğiklik |
|---|---|---|---|
| ~15° yamuk, koyu masa | bulundu | köşegenin %0,32'si | 0,1° |
| ~30° dönük | bulundu | %0,33 | 0,3° |
| Sarı ışıklı, gölgeli, mühürlü belge | — | %0,39 | 0,1° |
| Beyaz masada beyaz kâğıt (masa 240–245) | **bulunamadı** | %0,38–0,41 | ≤0,3° |
| Kâğıda değen beyaz duvar + parlak masa yansıması | v5: **bulunamadı** | %0,32 | — |
| Alt iki köşe kadraj dışında | v5: kenara yapışık, emin değil | %0,52 | — |
| Kâğıda 3° yamuk basılmış yazı | yazı eğik kalır | köşeler döndürülür | 0,1° |

(Köşe hatasının çoğu, masa şeridi kalmasın diye köşelerin bilerek %1 içeri çekilmesinden gelir.)

**Elle köşe ayarlama:** Detay sayfasında "Köşeleri ayarla", kırpılmamış orijinal üzerinde dört tutamaç açar
(fare ve dokunmatik; klavyede ok tuşları). Sürüklerken büyüteç köşenin yakın görünümünü gösterir. "Otomatik
algıla" yeniden algılar, "Tüm görsel" düzeltmeyi kaldırır. Kaydedince önizleme yeniden üretilir, **OCR yeniden
yapılır** ve "Yapay zeka ile yeniden analiz et" önerilir (elle düzeltilmiş tür ve bilgi alanları korunur).

**Eski belgeler:** v4'te otomatik düzeltilip öyle saklanmış belgelerin orijinali olmadığından aynen gösterilir
ve köşeleri ayarlanamaz ("eski sürümle yüklendi" notu). Hiç düzeltilmemiş eski görsellerde saklanan zaten
orijinal olduğundan köşe ayarlama kullanılabilir.

## PDF ve Word

- **PDF indir** (`GET /belge/<id>/pdf?mod=renkli|gri|sb` → `<tür>_<belge tarihi veya yükleme tarihi>.pdf`):
  düzeltilmiş görüntü → tarama filtresi → Tesseract'tan yalnızca görünmez metin katmanı (`textonly_pdf`) →
  PyMuPDF ile A4 sayfaya yerleştirme. En-boy oranı korunur, görsel ortalanır, dört kenarda eşit ~1 cm boşluk
  kalır; yatay belgeler yatay A4'e yerleşir. Renkli/gri sayfa JPEG (tipik 110–130 KB), siyah-beyaz 1-bit PNG
  (~20 KB) olarak gömülür. Başlık (tür + tarih) ve oluşturan ("ArcBase") meta verisi yazılır. PDF
  saklanmaz, her istekte üretilir. PDF olarak yüklenmiş belgelerde orijinal PDF verilir. "Orijinali indir"
  fotoğrafın kırpılmamış (küçültülmüş) halini verir
- **Birleştirme:** Kategori ve arama sayfalarında "Seç" ile kartlar seçilir (seçim sırası kartta numara olarak
  görünür), "Seçilenleri PDF yap" → `POST /pdf-birlestir`. Görseller filtreli A4 sayfa, PDF belgeler sayfalarıyla
  aynen eklenir; her belge için "tür · tarih · dosya adı" yer imi oluşturulur. Tek seferde en fazla **20
  belge** (gunicorn 120 sn zaman aşımı için). Dosya adı `arsiv_birlesik_<YYYY-MM-DD>.pdf`
- **Word** (`GET /belge/<id>/word`): başlık (türün adı), çıkarılan bilgiler tablosu, "Bu metin otomatik
  okunmuştur, hatalar içerebilir." notu ve OCR metni paragraflar halinde

## Excel'e aktarma

Kategori, arama ve panel sayfalarındaki **Excel'e aktar** butonu `GET /disa-aktar` ile sayfadaki filtreleri
aynen uygulayarak `arsiv_<tür>_<YYYY-MM-DD>.xlsx` indirir (tür seçilmemişse `arsiv_tumu_...`). Sütunlar:
dosya adı, tür, belge tarihi, kurum, tutar, para birimi, güven, elle düzeltildi, yüklenme tarihi (TSİ),
açıklama. Başlık satırı kalın ve dondurulmuştur; tarih ve tutar hücreleri gerçek tarih/sayıdır. Fatura
filtrelendiğinde en alta para birimi başına toplam satırı eklenir. OCR metni ve görseller aktarılmaz; `=` ile
başlayan değerler formül olarak çalıştırılmaz.

## Veritabanı değişiklikleri (v4, v5, v6)

Veritabanında gerçek kullanıcı verisi olduğu için **hiçbir tablo silinmez veya yeniden oluşturulmaz**.
Uygulama ilk istekte yalnızca şunları çalıştırır (tekrar tekrar çalıştırılabilir):

```sql
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS belge_tarihi DATE;
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS tutar NUMERIC(14,2);
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS para_birimi TEXT;
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS kurum TEXT;
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS alanlar JSONB;               -- NULL: bilgi henüz çıkarılmadı
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS alanlar_elle_duzeltildi BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS otomatik_duzeltildi BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_belgeler_kullanici_tarih ON belgeler(kullanici_id, belge_tarihi);
-- v5
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS koseler JSONB;       -- [[x,y] x4] saklanan görselde; NULL = düzeltme yok
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS orijinal_saklandi BOOLEAN NOT NULL DEFAULT FALSE;  -- TRUE: sifreli_icerik düzeltilmemiş orijinal
-- v6: arka planda işleme ve görsel önbelleği (mevcut belgeler 'tamamlandi' sayılır)
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS isleme_durumu TEXT NOT NULL DEFAULT 'tamamlandi';
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS isleme_zamani TIMESTAMP;   -- bekliyor: en erken deneme; isleniyor: kalp atışı
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS isleme_deneme INTEGER NOT NULL DEFAULT 0;
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS isleme_bilgi JSONB;        -- aşama, uyarılar, kırpma kontrolü, hata
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS icerik_surumu INTEGER NOT NULL DEFAULT 0;  -- görsel değişince artar (ETag)
CREATE INDEX IF NOT EXISTS idx_belgeler_isleme ON belgeler(id) WHERE isleme_durumu IN ('bekliyor', 'isleniyor');
-- v6 (kurum / yerel mod): yönetici ve Gelen belgeler kutusu
ALTER TABLE kullanicilar ADD COLUMN IF NOT EXISTS yonetici BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS gelen_kutusu BOOLEAN NOT NULL DEFAULT FALSE;  -- yöneticinin kutusunda, arşive sayılmaz
ALTER TABLE belgeler ADD COLUMN IF NOT EXISTS atama_gecmisi JSONB;  -- [{islem, yapan_id, yapan, kime_id, kime, zaman}]
```

Tüm komutlar tek gidiş-dönüşte gönderilir.

Mevcut belgeler bu sütunlar boşken de açılır ve indirilir; bilgileri hesap sayfasından sonradan
çıkarılabilir. Köşeleri elle kaydedilen belgede `otomatik_duzeltildi` FALSE yapılır ve "Kırpma elle ayarlandı"
rozeti gösterilir.

## Performans

Ölçümler `docs/hiz_olcumu.py` ile, aynı makinede, uzak bir Neon veritabanına karşı (bu makineden yeni
bağlantı ~0,8 sn, bir sorgu ~0,2 sn) önce eski sonra yeni kodla art arda alındı. 30 belgelik geçici bir
kullanıcı oluşturulur; her istek 5 kez (ilk ısınma istemi sayılmaz) çalıştırılır, en yavaş tekrar atılıp
ortalama alınır. Groq çağrıları gerçektir. Render ile Neon aynı bölgedeyken ağ gecikmesi çok daha küçük
olduğundan mutlak süreler düşer; oranlar yol göstericidir.

| İstek | Önce | Sonra | Fark |
|---|---|---|---|
| Panel | 2.985 ms | 189 ms | 15,8× |
| Kategori (12 kart) | 3.442 ms | 190 ms | 18,1× |
| Belge detayı | 3.348 ms | 185 ms | 18,1× |
| Arama | 3.343 ms | 239 ms | 14,0× |
| Belge görseli `/tarama` (ilk açılış) | 3.394 ms | 989 ms | 3,4× |
| Belge görseli `/tarama` (tekrar, 304) | 3.330 ms | 240 ms | 13,9× |
| Önizleme (grid küçük resmi) | 2.819 ms | 273 ms | 10,3× |
| Yükleme, gerçek fotoğraf — kullanıcının beklediği | 7.307 ms | 447 ms | 16,4× |
| Yükleme, gerçek fotoğraf — belge hazır | 7.307 ms | 3.468 ms | 2,1× |
| Yükleme, 12 MP fotoğraf — kullanıcının beklediği | 6.757 ms | 1.001 ms | 6,8× |
| Yükleme, 12 MP fotoğraf — belge hazır | 6.757 ms | 3.837 ms | 1,8× |

Gerçek tarayıcıda (Chromium) ilk çizim: panel 3.376 → 232 ms, belge detayı 4.248 → 280 ms; belge detayının
tam yüklenmesi (tarama görseli dahil) 9.169 → 258 ms.

**Ne değişti?**

- **Bağlantı havuzu:** eskiden her sorgu yeni bağlantı açıyordu (sayfa başına 3 bağlantı ≈ 2 sn). Artık
  bağlantılar süreç başına havuzda tutulur, autocommit'tir (sorgu başına tek gidiş-dönüş); 2 dakikadan uzun
  boşta kalan bağlantı önce yoklanır, kopmuşsa yenisiyle değiştirilir.
- **Sayfa başına 2 sorgu:** kullanıcı, menü sayaçları, kota, "bu hafta yüklenen" ve işlenen belge sayısı
  tek sorguda gelir (Flask-Login `user_loader`); ikinci sorgu sayfanın verisidir. Panel eskiden "bu hafta"
  sayısı için kategori sayfalarını arka planda ayrıca indiriyordu; bu kaldırıldı.
- **Görsel önbelleği:** işlenmiş görseller (tarama, kırpılmış görsel, önizleme) süreç içinde bayt sınırlı
  LRU önbellekte tutulur (`GORSEL_ONBELLEGI_MB`, varsayılan 48). Yanıtlarda `ETag` ve
  `Cache-Control: private` vardır; tarayıcının elindeki sürüm güncelse şifreli içerik veritabanından hiç
  taşınmaz ve 304 döner. Kartlar önizleme adresine içerik sürümünü (`?v=`) ekler: tarayıcı küçük resmi
  bir daha sormaz. Köşe değişince sürüm (`icerik_surumu`) artar, tarama modu anahtarın parçasıdır; eski
  görsel verilmez. Çıkışta `Clear-Site-Data: "cache"` ile tarayıcı önbelleği temizlenir.
- **Grid'ler** yalnızca küçük önizleme (`loading="lazy"`) kullanır.
- **Derlenmiş CSS:** Tailwind CDN betiği (tarayıcıda çalışma anında derleme) yerine önceden derlenmiş
  ~38 KB statik CSS; statik dosyalar sürümlü adresle bir yıl önbelleklenir. Eski ve yeni sürümün beş
  sayfası açık ve koyu temada ekran görüntüsüyle karşılaştırıldı: piksel farkı yok.
- **Sayfa geçiş animasyonları** en fazla 200 ms (gecikmeler dahil).
- **gunicorn** worker başına 4 iş parçacığıyla çalışır (bir sayfanın önizlemeleri aynı anda sunulur).

### OCR hızlandırma ve doğruluk

- OCR girdisi JPEG'e kodlanıp yeniden açılmaz; düzeltilmiş gri tarama doğrudan Tesseract'a verilir.
- Perspektif düzeltme doğrudan OCR çözünürlüğünde (uzun kenar 2400 px) yapılır; 300 DPI A4'e (3508 px) göre
  piksel sayısı yarıdan az.
- Tesseract `--oem 1 -c tessedit_do_invert=0` ile çalışır (satırları ters renkte ikinci kez okumaz).
- Çok sayfalı PDF'te sayfalar paralel okunur (3 taranmış sayfa: 2,6 sn → 1,1 sn), metin katmanı olan
  sayfalar hiç OCR'lanmaz; PDF sayfaları PNG'ye kodlanmadan doğrudan piksellerden okunur.
- Her yüklemede OCR **bir kez** yapılır (testle doğrulanır).

Doğruluk, gerçek bir telefon fotoğrafında (`tests/ozel/`, repoya girmez; metni elle yazılmış referansla) ve
metni bilinen 6 sentetik 12 MP fotoğrafta (8–12 pt yazı, 15–30° yamuk, gölge/sarı ışık) eski ve yeni boru
hattıyla karşılaştırıldı (kelime F1: referanstaki kelimelerin bulunma/doğruluk oranı):

| Fotoğraf | Kelime F1 önce → sonra | Karakter benzerliği | Anahtar alanlar | OCR aşaması süresi |
|---|---|---|---|---|
| Gerçek fotoğraf | 0,677 → **0,724** | 0,926 → 0,936 | 4/8 → 4/8 | 482 → 453 ms |
| Sentetik (6 fotoğraf) | 5'inde aynı, 1'inde 0,977 → 0,970 | ±0,002 | 6/6 → 6/6 (hepsi) | ~790 → ~550 ms |

Sentetik fotoğraftaki tek fark, iki sürümde de yanlış okunan "%2" işaretinin farklı yanlış okunmasıdır
(eski "2", yeni "902"). 8–9 pt yazıda 2400 px sınırı tam çözünürlükle aynı sonucu verdi.

Kendi ortamınızda ölçmek için:

```bash
python docs/hiz_olcumu.py --tarayici --json sonra.json               # bu kod
python docs/hiz_olcumu.py --kok ../eski-kopya --tarayici --json once.json
python docs/hiz_olcumu.py --karsilastir once.json sonra.json
```

## Çalıştırma modları

Tek repo, tek kod tabanı: ArcBase **yerel mod** (kurumun kendi bilgisayarı) ya da **bulut modu** (Neon +
Render) ile çalışır. Seçim `.env` dosyasıyla yapılır.

| | Yerel mod | Bulut modu |
|---|---|---|
| Veritabanı | Bu bilgisayardaki (ya da yerel ağdaki) PostgreSQL | Neon gibi barındırılan PostgreSQL |
| Veri konumu | Belgeler ve veritabanı kurumun bilgisayarında kalır; dışarı yalnızca Groq'a OCR metni gider | Veritabanı bulut sağlayıcıda, uygulama Render'da |
| Kimler için uygun | Belgelerin kurum dışına çıkmaması gereken kurumlar; tek bilgisayar ya da yerel ağ | Kurulum istemeyen, internetten erişilen deneme ve canlı yayın |
| `YEREL_MOD` | `1` | Tanımlı değil (boş) |
| `DATABASE_URL` | `localhost` ya da özel ağ adresi | Bulut adresi (`?sslmode=require`) |
| Sunucu | Windows, `baslat.bat` (waitress) | Render + Docker (gunicorn) |

Kod her iki modda aynıdır. Modlar arasındaki fark `.env` içindeki `YEREL_MOD`, `DATABASE_URL` (ve testler
için `TEST_DATABASE_URL`) değerleridir; yerel moda özgü ek ayarlar (tarama klasörü, yedekleme vb.) isteğe
bağlıdır ve `.env.example`'ın "Yerel mod" bölümündedir.

> ⚠️ **`.env` dosyası asla commit edilmez.** Groq anahtarı, veritabanı şifresi, `ENCRYPTION_KEY` ve
> `SECRET_KEY` yalnızca orada durur; `.gitignore` bu dosyayı dışarıda tutar. Depoya yalnızca yer tutuculu
> `.env.example` girer.

### Ortak adımlar (iki modda da)

1. Projeyi indirip Python ortamını kurun ([Geliştirme ortamı kurulumu](#geliştirme-ortamı-kurulumu)).
2. `.env.example` dosyasını `.env` olarak kopyalayın (Windows: `copy .env.example .env`).
3. [Groq API anahtarı](https://console.groq.com/keys) alıp `GROQ_API_KEY`'e yazın. Boş kalırsa uygulama
   çalışır, belge türü "Diğer" olur.
4. Anahtarları üretip `.env`'e yazın:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # ENCRYPTION_KEY
   python -c "import secrets; print(secrets.token_hex(32))"                                    # SECRET_KEY
   ```
   `ENCRYPTION_KEY` bir kez üretilir ve **asla değiştirilmez**; kaybolursa belgeler çözülemez.

### Yerel mod

1. PostgreSQL 16 veya 17'yi kurun ([postgresql.org](https://www.postgresql.org/download/windows/));
   `postgres` şifresini not edin. Tesseract OCR'yi Türkçe dil paketiyle kurun.
2. Veritabanını oluşturun (tabloları uygulama ilk açılışta kendisi oluşturur):
   ```sql
   CREATE ROLE arcbase LOGIN PASSWORD '<guclu_bir_sifre>';
   CREATE DATABASE arcbase OWNER arcbase ENCODING 'UTF8';
   ```
3. `.env` içinde şunları ayarlayın:
   ```ini
   YEREL_MOD=1
   DATABASE_URL=postgresql://arcbase:<guclu_bir_sifre>@localhost:5432/arcbase
   ```
   `YEREL_MOD=1` iken `DATABASE_URL` bu bilgisayarı ya da yerel ağı göstermelidir; bulut adresiyle uygulama
   başlamaz. Yerel modda `SECRET_KEY` zorunludur.
4. `baslat.bat` dosyasına çift tıklayın ve http://127.0.0.1:5001 adresini açın. İlk kaydolan kullanıcı
   yönetici olur.

Adım adım ve teknik olmayan biri için hazırlanmış Windows rehberi (tarayıcı, otomatik başlatma, yedekleme,
güvenlik duvarı): **[docs/KURULUM_KURUM.md](docs/KURULUM_KURUM.md)**. Yerel moda özgü özellikler için
[Yerel mod (kurum kurulumu)](#yerel-mod-kurum-kurulumu) bölümüne bakın.

### Bulut modu

1. [Neon](https://neon.com) (ya da başka bir barındırılan PostgreSQL) hesabı açıp bir veritabanı oluşturun
   ve bağlantı adresini kopyalayın.
2. `.env` içinde bulut adresini yazın ve `YEREL_MOD`'u tanımlamayın (ya da boş bırakın):
   ```ini
   DATABASE_URL=postgresql://kullanici:sifre@host/neondb?sslmode=require
   ```
3. Yerelde denemek için `python app.py` (bkz. [Geliştirme ortamı kurulumu](#geliştirme-ortamı-kurulumu)).
   İnternete açmak için: [Yayına alma (Render + Docker)](#yayına-alma-render--docker). Render'da ortam
   değişkenleri panelden girilir; `.env` dosyası sunucuya gönderilmez.

## Geliştirme ortamı kurulumu

**Gereksinimler:** Python 3.10+, Tesseract OCR + Türkçe dil paketi (`tur.traineddata`),
bir [Groq API anahtarı](https://console.groq.com/keys) ve bir PostgreSQL veritabanı
(ör. [Neon](https://neon.com) ücretsiz planı).

```bash
git clone <repo-adresi>
cd dijital-arsiv
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

`.env.example` dosyasını `.env` olarak kopyalayın ve anahtarları doldurun:

| Anahtar | Açıklama |
|---|---|
| `GROQ_API_KEY` | Groq konsolundan alınan API anahtarı |
| `DATABASE_URL` | `postgresql://kullanici:sifre@host/veritabani?sslmode=require` biçiminde bağlantı adresi |
| `TEST_DATABASE_URL` | Testler ve `docs/hiz_olcumu.py` için **ayrı** bir veritabanı (aynı biçim); `DATABASE_URL` ile aynı olamaz |
| `ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GROQ_MODEL` | Opsiyonel, varsayılan `openai/gpt-oss-120b` |
| `KULLANICI_BELGE_LIMITI` | Opsiyonel, kullanıcı başına belge sınırı (varsayılan 50) |
| `TESSERACT_CMD` | Opsiyonel, Tesseract PATH'te değilse tam yolu |
| `YEREL_MOD`, `HTTPS`, `YONETICI_KULLANICI`, `TARAMA_KLASORU`, `TARAYICI_WIA`, `VARSAYILAN_TARAMA_KLASORLERI`, `YEDEK_KLASORU`... | Yerel mod (kurum) ayarları; açıklamalarıyla `.env.example`'da, bkz. [Yerel mod](#yerel-mod-kurum-kurulumu) |

Tüm değişkenlerin tam listesi için `.env.example` dosyasına bakın.

> ⚠️ **`ENCRYPTION_KEY` bir kez üretilir ve asla değiştirilmez.** Kaybolursa veya değişirse
> veritabanındaki tüm belgeler çözülemez hale gelir. Güvenli bir yere yedekleyin.

Çalıştırma:

```bash
python app.py
```

Tarayıcıdan http://127.0.0.1:5001 adresine gidin. Tablolar ilk istekte otomatik oluşturulur; arka plan
işçisi de ilk istekte başlar.

### Arayüz stillerini derleme (Tailwind)

Arayüz Tailwind CSS sınıflarıyla yazılır ve `static/tailwind.css` olarak **önceden derlenmiş halde repoda**
bulunur; çalıştırmak için derleme gerekmez. Şablonlarda ya da `static/app.js`'te yeni bir sınıf
kullanırsanız Tailwind'in Node gerektirmeyen tek dosyalık
[standalone CLI'ı](https://github.com/tailwindlabs/tailwindcss/releases/tag/v3.4.17) (v3.4.17,
`tailwindcss-windows-x64.exe` / `-linux-x64` / `-macos-arm64`) ile yeniden derleyin:

```bash
tailwindcss -c tailwind.config.js -i static/tailwind.giris.css -o static/tailwind.css --minify
```

(İkili dosyayı `.araclar/` altına koyabilirsiniz; bu klasör git dışıdır.)

### Testler

```bash
pip install -r requirements-dev.txt
playwright install chromium      # tarayıcı testleri için (opsiyonel)

pytest                                    # hızlı: yavaş testler atlanır
pytest -m "slow or not slow"              # tam paket (Playwright, gerçek OCR, uçtan uca dahil)
pytest -n auto                            # hızlı paket, paralel (pytest-xdist)
pytest -m "slow or not slow" -n auto      # tam paket, paralel
```

Yavaş testler (Playwright tarayıcı testleri, gerçek Tesseract OCR, gerçek Groq, uzun uçtan uca testler)
`@pytest.mark.slow` ile işaretlidir ve `pytest.ini`'deki `-m "not slow"` ayarıyla varsayılan çalıştırmada
atlanır.

**Test veritabanı:** Testler yalnızca `.env`'deki **`TEST_DATABASE_URL`**'i kullanır; canlı veritabanına
(`DATABASE_URL`) hiçbir koşulda bağlanmaz. `TEST_DATABASE_URL` tanımlı değilse veritabanı gerektiren testler
açık bir uyarıyla atlanır (saf görüntü/tarama testleri yine çalışır); `DATABASE_URL` ile aynıysa test oturumu
hata verip durur. `docs/hiz_olcumu.py` da aynı kurala uyar. Testler benzersiz adlı geçici kullanıcılar
oluşturup sonunda siler. Testlerde arka plan işçisi kendiliğinden başlamaz; yüklenen belgenin işi test
içinde hemen çalıştırılır ve yalnızca o belge işlenir. Groq çağrıları taklit edilir. Taklit, anahtarın geçersizleşmesi,
modelin kaldırılması ya da bağlantı sorunları gibi gerçek hataları yakalayamaz; bunlar için gerçek Groq'a
istek atan entegrasyon testlerini (~7 istek) ayrıca çalıştırın:

```bash
GROQ_ENTEGRASYON=1 pytest -m slow tests/test_groq_entegrasyon.py
```

(Tüm paketi gerçek Groq ile çalıştırmak için `GERCEK_GROQ=1 pytest`; çok daha fazla istek harcar.) OCR testleri Tesseract, tarayıcı testleri (`tests/test_arayuz.py`) Chromium kurulu
değilse atlanır.

| Test dosyası | Kapsam |
|---|---|
| `test_bilgi.py` | Bilgi çıkarma (fatura, dilekçe, kimlik — TC no / doğum tarihi / seri no saklanmaz), elle düzenleme, filtreler, sıralama, fatura özeti, arama, mevcut belgelerden bilgi çıkarma |
| `test_toplu_yukleme.py` | `/yukle` JSON cevapları ve `/isleme-durumu`, 5 dosyalık toplu yükleme (biri hatalı), kota aşımı, Groq 429'da işin ertelenip yeniden denenmesi |
| `test_arka_plan.py` | Yüklemenin hemen dönmesi ve "İşleniyor" rozeti, JS kapalıyken yenilenen sayfa, yarım kalan işin yeniden alınması, kaldığı aşamadan devam (OCR tekrarlanmaz), bellek boşalınca saklanan görselden OCR, çökme döngüsü → hata → "Yeniden işle", işlenirken elle seçilen tür, durumun kullanıcıya özel olması, gerçek işçi iş parçacığı |
| `test_hiz.py` | Sayfa başına sorgu sayısı ve havuzdan bağlantı, kopmuş bağlantının yenilenmesi, ETag/304 ve bellek önbelleği, köşe/mod değişince önbelleğin geçersizleşmesi, sürümlü adres, önbelleğin başka kullanıcıya belge vermemesi, grid'de lazy önizleme, tek OCR ve küçültülmüş girdi, paralel PDF OCR, derlenmiş CSS, ≤200 ms animasyonlar |
| `test_tarama.py` | Gölge/sarı ışık temizliği, renk korunumu (mavi mürekkep, kırmızı mühür, logo), gri/siyah-beyaz, gürültü, hız, `/tarama` route'u |
| `test_duzelt.py` | Çoklu aday algılama (15–30°, beyaz masa, mühürlü belge), ince eğiklik, kadrajdan taşan kâğıt, taranmış belge algılama (kırpılmaz, ±3° eğiklik, rozet; büyük çerçeveli tablo kâğıt kenarı sanılmaz), orijinal + köşe saklama, eski v3/v4 belgeleri, EXIF |
| `test_koseler.py` | Elle köşe ayarlama, yeniden OCR, otomatik yeniden algılama, yeniden analiz (elle düzeltilenler korunur), eski belgelerde kapalı olması |
| `test_pdf.py` | PDF'te metin arama, A4 yerleşimi (dikey/yatay, eşit kenar), boyut, meta veri, birleştirme sırası ve yer imleri, 20 belge sınırı |
| `test_word.py` | Başlık, bilgi tablosu, not satırı, OCR paragrafları |
| `test_groq_hatalari.py` | Groq hatalarının ayrımı (bağlantı/5xx/429 geçici, 401/404 kalıcı), kullanıcıya uyarı, geçici hatada işin yeniden denenmesi, kalıcıda denenmemesi, "Yeniden dene" |
| `test_groq_entegrasyon.py` | **İsteğe bağlı, gerçek Groq:** model mevcut mu, fatura/dilekçe/kimlik sınıflandırması, geçersiz anahtar, uçtan uca yükleme |
| `test_v5_uctan_uca.py` | Zor fotoğraf (sarı ışık, gölge, 30°, açık masa, mühür) yüklemeden aranabilir PDF'e; eski v3/v4 belgeleri tüm yeni yollarda; v5 veri ayrımı |
| `test_excel.py` | Dosya adı, başlıklar, hücre tipleri, filtreler, toplam satırı, formül enjeksiyonu |
| `test_arayuz.py` | Gerçek tarayıcıda (arka plan işçisiyle) toplu yükleme ve işleme durumu, tek dosyada kendiliğinden güncellenen belge sayfası, 10 dosya sınırı, kota uyarısı, bilgi çıkarma ilerlemesi, filtre ve düzenleme formu, tarama modu ve karşılaştırma, köşe editörü (sürükleme, büyüteç, kaydetme), "Kırpmayı kontrol et", PDF indirme, çoklu seçim ve birleştirme |
| `test_veri_ayrimi.py` | İki kullanıcı arasında veri ayrımı (v4 uç noktaları dahil) |
| `test_kimlik.py`, `test_belgeler.py` | Hesaplar, oturum, yükleme, OCR, sıkıştırma, PDF, kota |

## Yayına alma (Render + Docker)

Uygulama, Tesseract'ı ve Türkçe dil paketini içeren `Dockerfile` ile [Render](https://render.com)
üzerinde ücretsiz bir **Web Service** olarak çalışır. Render GitHub reposunu izler, her `git push`
sonrası imajı yeniden oluşturup yayınlar ve HTTPS'i kendisi sağlar.

1. **Repoyu GitHub'a gönderin.** `.env` dosyasının gitmediğini kontrol edin:
   ```bash
   git status --ignored        # .env "Ignored files" altında görünmeli
   ```
2. [dashboard.render.com](https://dashboard.render.com) → **New +** → **Web Service** → GitHub hesabınızı
   bağlayıp bu repoyu seçin.
3. Ayarlar:
   | Alan | Değer |
   |---|---|
   | **Language** | Docker (Dockerfile otomatik bulunur) |
   | **Branch** | `main` |
   | **Region** | Frankfurt (EU Central) — Neon veritabanınız da AB'deyse gecikme düşük olur |
   | **Instance Type** | Free |
4. **Environment Variables** bölümüne `.env` dosyanızdaki değerleri tek tek girin
   (`.env` dosyası sunucuya gönderilmez, Docker imajına da girmez):
   | Anahtar | Not |
   |---|---|
   | `GROQ_API_KEY` | |
   | `DATABASE_URL` | Neon bağlantı adresi (`?sslmode=require` ile) |
   | `ENCRYPTION_KEY` | Yereldekiyle **aynı** olmalı; aksi halde mevcut belgeler çözülemez |
   | `SECRET_KEY` | Uzun rastgele bir değer; tanımlı değilse uygulama başlamaz |
   | `GROQ_MODEL` | Opsiyonel |
   | `KULLANICI_BELGE_LIMITI` | Opsiyonel (varsayılan 50) |

   `PORT` Render tarafından otomatik verilir; `URETIM=1` Dockerfile'da tanımlıdır, `TESSERACT_CMD`
   gerekmez.
5. **Create Web Service** ile ilk yayını başlatın. İmaj oluşturma birkaç dakika sürer; loglarda
   `Listening at: http://0.0.0.0:...` görünce site `https://<servis-adi>.onrender.com` adresinde açılır.
6. Siteyi açıp bir hesap oluşturun ve bir belge yükleyerek OCR + sınıflandırmanın çalıştığını doğrulayın.
   Ardından bu README'nin başındaki **Canlı site** satırına adresi ekleyin.

**Üretimde otomatik açılan ayarlar** (`URETIM=1`): `debug` kapalı, oturum ve "beni hatırla" çerezleri
`Secure` + `HttpOnly` + `SameSite=Lax`, Render'ın vekil sunucusu için `ProxyFix` (hız sınırı gerçek istemci
IP'sine göre çalışır).

**Ücretsiz katman notları:**

- Site 15 dakika istek almazsa uykuya geçer; ilk açılış 30-60 saniye sürebilir. Neon veritabanı da boşta
  uyuduğu için ilk istek ayrıca birkaç saniye gecikebilir.
- Bellek 512 MB'tır. OpenCV büyük telefon fotoğraflarında (12 MP) geçici olarak ~100 MB kullanabilir; bellek
  hatası görülürse ortam değişkenlerine `WEB_CONCURRENCY=1` ekleyerek gunicorn worker sayısını düşürün.
  Her worker kendi arka plan işçisini, görsel önbelleğini (`GORSEL_ONBELLEGI_MB`, varsayılan 48) ve işçiye
  aktarılan tam çözünürlüklü dosyaları (`HAM_BELLEK_MB`, varsayılan 64) tutar; gerekirse bunlar da
  küçültülebilir. İş parçacığı sayısı `GUNICORN_THREADS` (varsayılan 4) ile değiştirilir.
- İmaj, OpenCV için `libglib2.0-0` paketini de kurar.
- Uygulamayı yerelde Docker ile denemek için:
  ```bash
  docker build -t dijital-arsiv .
  docker run --rm -p 10000:10000 --env-file .env dijital-arsiv
  ```
  (Yerel HTTP'de `Secure` çerezler gönderilmediği için giriş yapabilmek adına `-e URETIM=0` ekleyin.)

## Yerel mod (kurum kurulumu)

Aynı kod iki şekilde çalışır; seçim `.env` ile yapılır:

| | Bulut modu (varsayılan) | Yerel mod (`YEREL_MOD=1`) |
|---|---|---|
| Veritabanı | Neon (bulut PostgreSQL) | Kurumun bilgisayarındaki PostgreSQL |
| Sunucu | Render, Docker, gunicorn | Windows, waitress (`baslat.bat` / `sunucu.py`) |
| Dış bağlantı | Groq | **Yalnızca Groq** (yalnızca OCR metni) |
| Tarayıcı entegrasyonu | — | İzlenen klasör + bağlı tarayıcıdan doğrudan tarama |

Yeni ayarların hiçbiri verilmezse uygulama bugünkü gibi çalışır. Teknik olmayan biri için adım adım Windows
kurulumu: **[docs/KURULUM_KURUM.md](docs/KURULUM_KURUM.md)**.

- **Yerel mod koruması** (`yerel_mod.py`): `YEREL_MOD=1` iken `DATABASE_URL`'in sunucusu `localhost`,
  `127.x`, `::1`, Unix soketi ya da özel ağ adresi (10.x, 172.16-31.x, 192.168.x, fc00::/7) olmalıdır. Bulut
  adresiyle uygulama **başlamaz** ve nedenini yazar (adres ve şifre yazdırılmaz). Sunucu adları kabul
  edilmez; yerel ağdaki veritabanı IP adresiyle yazılır. Yerel modda `SECRET_KEY` zorunludur.
- **SSL**: bağlantı kodu SSL'i zorunlu tutmaz; `sslmode` yalnızca adreste yazılıysa uygulanır (Neon:
  `?sslmode=require`, yerel: yok).
- **Windows'ta çalıştırma**: gunicorn Windows'ta çalışmadığı için `sunucu.py` uygulamayı **waitress** ile
  yerel ağda (`0.0.0.0:5001`) açar, açılışta şemayı hazırlar, arka plan işçisini ve klasör izlemeyi başlatır,
  yerel ağ adreslerini (ör. `http://192.168.1.50:5001`) yazar. `baslat.bat` sanal ortamı kullanarak bunu
  çalıştırır; `baslat.bat /otomatik` Görev Zamanlayıcı içindir (çıktı `logs\arcbase.log`). Linux/Docker'da
  gunicorn aynen kalır.
- **Çerezler**: yerel ağda HTTP kullanıldığı için yerel modda `Secure` çerez yalnızca `HTTPS=1` iken açıktır
  (aksi halde tarayıcı çerezi göndermez, giriş yapılamaz). Render'da (`URETIM=1`) her zaman açıktır. Yerel
  modda `X-Forwarded-For` başlığına güvenilmez (hız sınırı atlatılamaz).
- **Dış kaynak yok**: yazı tipi (Inter, `static/fonts/`), ikonlar ve JavaScript uygulamayla
  gelir; sayfalar hiçbir dış adrese (CDN, Google Fonts) istek atmaz. Bunu bir test doğrular.
- **Yönetici ve Gelen belgeler**: `YONETICI_KULLANICI` ya da (boşsa) ilk kaydolan kullanıcı yöneticidir.
  Tarama klasörüne sahipsiz düşen belgeler yöneticinin **Gelen belgeler** kutusuna (`/gelen`) gider; yönetici
  bunları bir kullanıcıya atar ya da kendi arşivine alır. Atama belgenin `atama_gecmisi`'ne (kim, kime, ne
  zaman) ve uygulama günlüğüne yazılır. Yönetici **başka kullanıcıların arşivlerini göremez**: kutudaki
  belgelerin sahibi yöneticidir ama arşivine, sayaçlarına ve kotasına sayılmaz; atanınca sahibi değişir.
- **İzlenen klasör** (`klasor_izleme.py`, `TARAMA_KLASORU`): watchdog + birkaç saniyelik yoklama (ağ
  paylaşımları için). `Tarama\<kullanici>\` o kullanıcıya, kök `TARAMA_VARSAYILAN_KULLANICI`'ya ya da
  yöneticinin Gelen belgeler kutusuna gider. Boyutu 3 sn sabit kalmayan (yazımı süren) dosya alınmaz. JPG,
  PNG, PDF ve TIFF (tek sayfa → PNG, çok sayfa → tek PDF). Alınan dosya `islendi\YYYY-AA-GG\`, alınamayan
  `hata\` altına (yanında nedeni yazan `.hata.txt`) taşınır; hiçbir dosya silinmez. Dosya önce taşınır,
  sonra normal yüklemeyle aynı kuyruğa (`isleme.kuyruga_ekle`) eklenir; iki süreç aynı dosyayı alamaz.
- **Doğrudan tarama** (`tarayici_wia.py`, Windows'ta varsayılan açık, `TARAYICI_WIA=0` kapatır): WIA
  tarayıcı listesi (USB ve WSD ağ tarayıcıları) arka planda 3 saniyede bir yenilenir; sayfalar
  `/tarayici/durum`'u sorar, yeni tarayıcıda "Tarayıcı bulundu" bildirimi ve "Tara" düğmesi çıkar. Tek
  tuşla tarama: besleyicide kâğıt varsa tüm sayfalar, yoksa camdan sayfa sayfa ("Sonraki sayfa" / "Bitir",
  sayfalar bellekte kullanıcı başına bekler). Hatalar sade Türkçe mesajdır; hata kodu yalnızca günlüğe
  yazılır. Windows dışında modül yüklenmez, düğme görünmez. Testlerde WIA sahte COM nesneleriyle taklit edilir.
- **Bilgisayardaki tarama klasörleri** (`klasor_izleme.VarsayilanKlasorIzleyici`): Windows'un varsayılan
  tarama klasörleri ve "Tarama klasörleri" sayfasında eklenenler tek izleyiciyle izlenir; alınan dosya
  `ArcBase'e aktarıldı\` altına taşınır. Klasör bulma/gezme (`klasor_secimi.py`) yalnızca yöneticiye ya da
  sunucu bilgisayarının kendisinden (127.0.0.1) gelen isteğe açıktır; Windows sistem klasörleri listelenmez.
- **Veri taşıma** (`scripts/veri_tasi.py`): Neon'daki (`DATABASE_URL`) kullanıcıları ve belgeleri yerel
  veritabanına (`YEREL_DATABASE_URL`) id'leriyle kopyalar; şifreli içerik olduğu gibi taşınır (aynı
  `ENCRYPTION_KEY` gerekir, betik bunu dener). Önce sayıları gösterir, hedef boş değilse durur, onay ister;
  kopyadan sonra her satırın özetini iki tarafta karşılaştırır, uyuşmazsa hiçbir şey kaydedilmez.
- **Yedekleme** (`scripts/yedekle.py`): `pg_dump` ile tarihli yedek (`YEDEK_KLASORU`), en son `YEDEK_SAYISI`
  yedek tutulur. Windows Görev Zamanlayıcı ile günlük çalıştırma ve `ENCRYPTION_KEY`'in ayrıca saklanması
  kurulum rehberindedir.

## Veri akışı

| Veri | Nerede | Dışarı gider mi? |
|---|---|---|
| Belge dosyaları (görsel, PDF) | PostgreSQL, Fernet ile şifreli | Hayır |
| Kullanıcılar, şifre hash'leri, belge bilgileri, OCR metni | PostgreSQL | Hayır |
| Tarama klasörü dosyaları (yerel mod) | `TARAMA_KLASORU` (`islendi\`, `hata\`), şifresiz | Hayır |
| **OCR metni** (sınıflandırma ve bilgi çıkarma için) | — | **Evet, Groq API'ye (HTTPS)** |

Uygulamanın dışarıya yaptığı **tek** bağlantı Groq API çağrısıdır (`classifier.py`). Groq'a yalnızca OCR
metni gider; görsel, dosya ve veritabanı içeriği gitmez. OCR (Tesseract), görüntü düzeltme (OpenCV) ve
PDF/Word/Excel üretimi sunucuda yapılır. Arayüz dış kaynak yüklemez. Bulut modunda veritabanı Neon'da
(şifreli içerik), yerel modda kurumun bilgisayarındadır; yerel modda bulut veritabanıyla uygulama başlamaz.

## Dosya yapısı

| Dosya | Görevi |
|---|---|
| `app.py` | Flask route'ları, yükleme (JSON / form), işleme durumu, görsel önbelleği ve ETag, filtreler, oturum/CSRF/hız sınırı ayarları, hata sayfaları |
| `isleme.py` | Arka plan işçisi: iş alma, görüntü (köşe, OCR) ve sınıflandırma aşamaları, erteleme, yeniden başlatmada devam |
| `onbellek.py` | İşlenmiş görseller için süreç içi, bayt sınırlı LRU önbellek |
| `kimlik.py` | Kullanıcı modeli, şifre hash'leme, kayıt/giriş kuralları, güvenli yönlendirme |
| `database.py` | PostgreSQL bağlantı havuzu, şema, sorgular (her belge sorgusu `kullanici_id` ile filtrelenir), iş kuyruğu sorguları |
| `ocr.py` | PDF → görüntü (metin katmanı, paralel OCR), ön işleme, Tesseract OCR, görsel sıkıştırma, önizleme |
| `classifier.py` | Groq çağrısı (sınıflandırma + bilgi çıkarma tek istekte), 429 yönetimi |
| `alanlar.py` | Türe göre alan tanımları, tarih/tutar/para birimi doğrulama, kimlik gizlilik kuralı, biçimlendirme |
| `goruntu_duzelt.py` | OpenCV ile çoklu aday köşe algılama ve puanlama, perspektif ve eğiklik düzeltme |
| `tarama.py` | Renkli / gri / siyah-beyaz tarama filtreleri |
| `pdf_uret.py` | Aranabilir A4 PDF sayfası, PDF birleştirme, yer imleri, meta veri |
| `word_uret.py` | `.docx` üretimi (python-docx) |
| `excel.py` | `.xlsx` üretimi (openpyxl) |
| `crypto.py` | Fernet ile şifreleme / çözme |
| `templates/` | Açılış, giriş, kayıt, panel, kategori, belge, arama, hesap ve hata sayfaları |
| `static/` | `app.js` (arayüz davranışları, işleme durumu yoklaması), `style.css` (tema ve animasyonlar), `tailwind.css` (derlenmiş Tailwind), `tailwind.giris.css` (derleme girdisi) |
| `tailwind.config.js` | Tailwind derleme ayarları (renkler, font, taranan dosyalar) |
| `tests/` | pytest testleri; `ornek_gorseller.py` sentetik fotoğraflar üretir (masa, perspektif, sarı ışık, gölge, mühür) |
| `docs/once_sonra.py` | Kendi fotoğraflarınızdan README için tarama öncesi/sonrası görseli üretir |
| `docs/hiz_olcumu.py` | İstek sürelerini parçalara ayırarak ölçer, iki ölçümü karşılaştırır |
| `Dockerfile` | Tesseract + gunicorn içeren üretim imajı |
| `gunicorn.conf.py` | Worker açılınca arka plan işçisini (ve ayarlıysa klasör izlemeyi) başlatır |
| `yerel_mod.py` | `YEREL_MOD=1` koruması: veritabanı adresinin yerel/özel ağ olduğunu denetler |
| `sunucu.py` · `baslat.bat` | Windows/yerel ağ sunucusu (waitress); açılışta hazırlık, yerel ağ adresleri |
| `klasor_izleme.py` | İzlenen tarama klasörü (`TARAMA_KLASORU`) ve Windows'un varsayılan / eklenen tarama klasörleri: sahiplik, yazım bitince alma, TIFF, taşıma |
| `tarayici_wia.py` | Bağlı tarayıcıyı algılama ve WIA ile tarama (Windows'ta varsayılan açık, `TARAYICI_WIA=0` kapatır) |
| `klasor_secimi.py` | Tarayıcının kaydettiği klasörü bulma (son taranan dosya) ve sunucu klasörlerini gezme |
| `izlenen_klasorler.py` | Sonradan eklenen/kaldırılan izlenen klasörlerin kaydı (`veri/izlenen_klasorler.json`) |
| `tarama_gunlugu.py` | Son aktarılan dosyalar ve son tarama hataları (yöneticinin durum sayfası) |
| `scripts/veri_tasi.py` · `scripts/yedekle.py` | Neon → yerel veri taşıma (doğrulamalı) · `pg_dump` ile tarihli yedek |
| `docs/KURULUM_KURUM.md` | Kurum için adım adım Windows kurulum rehberi |
| `static/fonts/`, `static/fonts.css` | Yerel yazı tipi (Inter, OFL) |

## Route'lar

| Route | Açıklama |
|---|---|
| `GET /` | Giriş yapılmamışsa açılış sayfası, yapılmışsa panel |
| `GET, POST /kayit` | Kayıt (IP başına saatte 5 hesap) |
| `GET, POST /giris` | Giriş (IP başına dakikada 5, saatte 20 deneme) |
| `POST /cikis` | Oturumu kapatır |
| `GET /hesap` | Hesap bilgileri, kota, bilgi çıkarma, şifre değiştirme, hesap silme |
| `POST /hesap/bilgi-cikar` | Bilgisi çıkarılmamış mevcut belgeleri işler (JSON: birer birer, form: 5'er) |
| `POST /hesap/sifre` · `POST /hesap/sil` | Şifre değiştirme · hesabı ve tüm belgeleri silme |
| `POST /yukle` | Tek belgeyi sıkıştırıp şifreler, "bekliyor" olarak kaydeder ve hemen döner (`Accept: application/json` ile JSON cevap); işi arka plan işçisi yapar |
| `GET /isleme-durumu?id=…` | Belgelerin işleme durumu (tür, uyarılar, kırpma kontrolü), menü sayaçları; tarayıcı yoklar |
| `POST /belge/<id>/yeniden-isle` | İşlenemeyen (hata) belgeyi kuyruğa geri koyar |
| `GET /kategori/<tur>` · `GET /ara?q=` | Kategori listesi · arama; `baslangic`, `bitis`, `kurum`, `min_tutar`, `maks_tutar`, `siralama` filtreleri |
| `GET /disa-aktar` | Aynı filtrelerle `.xlsx` indirir |
| `GET /belge/<id>` | Belge detayı |
| `POST /belge/<id>/tur` · `POST /belge/<id>/alanlar` · `POST /belge/<id>/sil` | Tür düzeltme · bilgi düzenleme · silme |
| `GET /belge/<id>/indir` · `/gorsel/<id>` · `/onizleme/<id>` | Orijinali indirme ve görseller (`/gorsel/<id>?ham=1`: kırpılmamış orijinal); görsellerde `ETag` + `?v=<sürüm>` |
| `GET /tarama/<id>?mod=renkli\|gri\|sb\|orijinal` | Tarama önizlemesi (JPEG) |
| `GET /belge/<id>/pdf?mod=` · `GET /belge/<id>/word` | Aranabilir A4 PDF · Word |
| `GET /belge/<id>/koseler/otomatik` · `POST /belge/<id>/koseler` | Köşeleri yeniden algılama · elle köşe kaydetme (yeniden OCR) |
| `POST /belge/<id>/yeniden-analiz` | Kayıtlı metni yeniden sınıflandırma ve bilgi çıkarma |
| `POST /pdf-birlestir` | Seçilen belgeleri (en fazla 20) tek PDF'te birleştirme |
| `GET /gelen` · `POST /gelen/<id>/ata` | Yöneticinin Gelen belgeler kutusu · belgeyi bir kullanıcıya (ya da kendi arşivine) atama |
| `GET /tara` · `POST /tara` · `POST /tara/bitir` · `POST /tara/iptal` | Tek tuşla tarama (besleyicide tüm sayfalar; camda sayfa sayfa, "Bitir" ile tek belge) · vazgeçme (Windows) |
| `GET /tarayici/durum` | Bağlı tarayıcılar, tarama ilerlemesi, bitirilmemiş sayfa sayısı (sayfalar birkaç saniyede bir sorar) |
| `GET /tarama-durumu` | Yönetici: bağlı tarayıcılar, izlenen klasörler, son aktarılan dosyalar, son hatalar (yalnızca bilgi) |
| `GET /klasorler` · `GET /klasorler/son-dosyalar` · `GET /klasorler/gez` · `POST /klasorler/ekle` · `POST /klasorler/kaldir` | Tarama klasörleri: son taranan belgeyi bulma, klasör gezme, ekleme/kaldırma (yalnızca yönetici ya da sunucu bilgisayarının kendisi) |

Belge route'larının tamamı giriş gerektirir; başka kullanıcının belgesi istendiğinde 404 döner.

## Notlar

- **Veritabanı tek doğru kaynaktır** — dosyalar diske yazılmaz.
- Şifre değiştirilince diğer cihazlardaki oturumlar ve "beni hatırla" çerezleri geçersiz olur.
- Hız sınırı sayaçları bellekte tutulur; gunicorn'un her işlemi (worker) kendi sayacını tutar.
- Neon ücretsiz planda veritabanı boşta kalınca uykuya geçer; yeni bağlantı bir kez yeniden denenir,
  havuzdaki kopmuş bağlantı yenisiyle değiştirilir. Arka plan işçisi boştayken veritabanını yoklamaz.
- Tüm SQL sorguları parametreli (`%s`) yazılmıştır.

## Lisans

Bu proje [GNU Affero Genel Kamu Lisansı v3.0](LICENSE) (AGPL-3.0) ile lisanslanmıştır.
Telif hakkı © 2026 İbrahim Hakkı Evin.

Özetle: kodu kullanabilir, değiştirebilir ve dağıtabilirsiniz; değiştirilmiş bir sürümü dağıtırsanız **ya da
bir ağ hizmeti olarak kullanıcılara sunarsanız**, kaynak kodunu da aynı lisansla bu kullanıcılara açmanız
gerekir. PDF işleme için kullanılan PyMuPDF de AGPL-3.0 lisanslıdır. Diğer Python bağımlılıklarının
lisansları (MIT, MIT-CMU/HPND, BSD, Apache-2.0, LGPL-3.0, PSF-2.0, 0BSD, Zlib, CC0) ve arayüzde kullanılanlar
(Tailwind CSS — MIT, derlenmiş CSS'teki lisans notu korunur; Lucide ikonları — ISC; Inter yazı
tipi — OFL-1.1, `static/fonts/` içinde lisansıyla birlikte gelir) AGPL-3.0 ile uyumludur. Yerel mod
paketleri: waitress (ZPL-2.1), watchdog (Apache-2.0), pywin32 (PSF-2.0).

## Geliştirici

- **Geliştirici:** İbrahim Hakkı Evin
- **GitHub:** https://github.com/Abrahamexe
- **Lisans:** AGPL-3.0, ayrıntılar yukarıdaki [Lisans](#lisans) bölümünde ([LICENSE](LICENSE)).
