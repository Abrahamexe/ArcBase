"""README ekran görüntülerini üretir (ArcBase, Playwright + Chromium).

Kullanım (proje kökünden):
    .venv\\Scripts\\python scripts/ekran_goruntusu.py [--cikti docs/screenshots] [--sadece panel,belge]
                                                     [--veriyi-tut] [--eski-demoyu-sil]

Güvenlik:
  - Yalnızca .env'deki TEST_DATABASE_URL kullanılır (tests/db_korumasi.py); canlı veritabanına
    (DATABASE_URL / YEREL_DATABASE_URL) hiçbir koşulda bağlanılmaz. Adresler yazdırılmaz.
  - Sunucu bu bilgisayarda (127.0.0.1) ve sistemin seçtiği geçici bir portta açılır, iş bitince kapatılır.
  - Yalnızca sentetik belgeler ve "demo" kullanıcısı; iş bitince oluşturulan kullanıcılar (ve belgeleri)
    silinir. Gerçek ad, TC no, IBAN, telefon, adres yoktur.
  - OCR ve Groq taklit edilir: kota harcanmaz, sonuç her çalıştırmada aynıdır. Köşe algılama, önizleme,
    tarama filtresi ve şifreleme gerçek boru hattından geçer.
  - İzlenen klasör yolları ve tarama günlüğü, gerçek klasör adları görünmesin diye bellekte
    sentetik değerlerle değiştirilir (yalnızca bu süreçte).

Çıktı adları README'dekilerle aynıdır; yeni görseller: gelen-belgeler, izlenen-klasorler,
yonetici-tarama-durumu. "tarama-once-sonra-sentetik.jpg" docs/once_sonra.py ile üretilir.
"""

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "tests"))

for akis in (sys.stdout, sys.stderr):
    akis.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(KOK / ".env")
os.environ["ARKA_PLAN_ISCISI"] = "0"  # isci yalnızca toplu yükleme adımında başlatılır
os.environ["TARAYICI_WIA"] = "0"  # gerçek tarayıcı taranmasın
_gecici = Path(tempfile.mkdtemp(prefix="arcbase_ekran_"))
os.environ["IZLENEN_KLASORLER_DOSYASI"] = str(_gecici / "izlenen_klasorler.json")

import db_korumasi  # noqa: E402

try:
    TEST_VERITABANI = db_korumasi.veritabanini_ayarla()
except db_korumasi.CanliVeritabaniHatasi as hata:
    sys.exit(str(hata))
if not TEST_VERITABANI:
    sys.exit("TEST_DATABASE_URL tanımlı değil: canlı veritabanı kullanılmayacağı için işlem durduruldu.")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import ornek_gorseller as og  # noqa: E402

DEMO_AD = "demo"
DEMO_SIFRE = "DemoSifre2026"
DIGER_KULLANICILAR = ("muhasebe", "insan_kaynaklari")  # Gelen belgeler atama listesinde görünür
GENISLIK, YUKSEKLIK = 1440, 900
MOBIL = (390, 844)
BITIR = ("document.getAnimations().forEach(a => { const t = a.effect && a.effect.getTiming(); "
         "if (t && t.iterations !== Infinity) a.finish(); })")
GORSELLER_HAZIR = ("() => [...document.images].filter(i => i.src && i.getBoundingClientRect().width > 0 "
                   "&& i.getBoundingClientRect().top < innerHeight)"
                   ".every(i => i.complete && i.naturalWidth > 0)")
YASAK = (r"Dijital Ar[sş]iv", r"Traceback", r"Internal Server Error", r"\bt_[0-9a-f]{12}\b", r"demo_[0-9a-f]{6}")


# ---------------------------------------------------------------- sentetik belgeler

def _yazi(boyut, kalin=False):
    adlar = ("arialbd.ttf", "DejaVuSans-Bold.ttf") if kalin else ("arial.ttf", "DejaVuSans.ttf")
    for ad in adlar:
        try:
            return ImageFont.truetype(ad, boyut)
        except OSError:
            pass
    return ImageFont.load_default()


def sayfa_ciz(s):
    """A4 oranında, yazılı sentetik belge sayfası (RGB numpy). Logo kutusu sayfa kenarına değmez."""
    g_, y_ = 1240, 1754
    sayfa = Image.new("RGB", (g_, y_), "white")
    d = ImageDraw.Draw(sayfa)
    renk = s["renk"]
    d.rounded_rectangle((70, 70, 190, 130), 12, fill=renk)
    d.text((215, 72), s["firma"], fill=(30, 30, 30), font=_yazi(40, True))
    if s.get("alt_baslik"):
        d.text((215, 122), s["alt_baslik"], fill=(120, 120, 120), font=_yazi(26))
    d.line((70, 180, g_ - 70, 180), fill=renk, width=5)
    d.text((70, 215), s["baslik"], fill=(20, 20, 20), font=_yazi(52, True))
    y = 310
    for etiket, deger in s.get("bilgiler", ()):
        d.text((70, y), etiket, fill=(110, 110, 110), font=_yazi(30))
        d.text((400, y), deger, fill=(20, 20, 20), font=_yazi(32, True))
        y += 54
    y += 26
    if s.get("kalemler"):
        d.rectangle((70, y, g_ - 70, y + 56), fill=(236, 238, 243))
        d.text((90, y + 12), "Açıklama", fill=(60, 60, 60), font=_yazi(28, True))
        d.text((g_ - 90 - d.textlength("Tutar", font=_yazi(28, True)), y + 12), "Tutar", fill=(60, 60, 60), font=_yazi(28, True))
        y += 56
        for ad, tutar in s["kalemler"]:
            d.text((90, y + 14), ad, fill=(20, 20, 20), font=_yazi(30))
            d.text((g_ - 90 - d.textlength(tutar, font=_yazi(30)), y + 14), tutar, fill=(20, 20, 20), font=_yazi(30))
            d.line((70, y + 62, g_ - 70, y + 62), fill=(218, 220, 226), width=2)
            y += 64
        y += 24
        for i, (etiket, deger) in enumerate(s["toplamlar"]):
            son = i == len(s["toplamlar"]) - 1
            yz = _yazi(36 if son else 30, son)
            d.text((g_ - 90 - d.textlength(deger, font=yz), y), deger, fill=(20, 20, 20), font=yz)
            d.text((g_ - 430 - d.textlength(etiket, font=yz), y), etiket, fill=(90, 90, 90), font=yz)
            y += 56 if son else 46
    for satir in s.get("govde", ()):
        d.text((70, y), satir, fill=(25, 25, 25), font=_yazi(30))
        y += 46
    if s.get("muhur"):
        mx, my, r = 300, 1420, 110
        d.ellipse((mx - r, my - r, mx + r, my + r), outline=(200, 30, 40), width=7)
        d.ellipse((mx - r + 20, my - r + 20, mx + r - 20, my + r - 20), outline=(200, 30, 40), width=3)
        for k in range(3):
            d.line((mx - 60, my - 30 + k * 30, mx + 60, my - 30 + k * 30), fill=(200, 30, 40), width=4)
    if s.get("imza"):
        xs = np.linspace(700, 1000, 60)
        ys = 1430 + np.sin(np.linspace(0, 5 * np.pi, 60)) * 30
        d.line(list(zip(xs, ys)), fill=(30, 60, 200), width=6)
    d.text((70, y_ - 100), "Örnek amaçlı üretilmiş sentetik belge. Kişi ve kurum bilgileri gerçek değildir.",
           fill=(150, 150, 150), font=_yazi(22))
    return np.asarray(sayfa)


def metin_uret(s):
    """Sahte OCR çıktısı: sayfada yazan her şey."""
    parcalar = [s["firma"], s.get("alt_baslik", ""), s["baslik"]]
    parcalar += [f"{e}: {d}" for e, d in s.get("bilgiler", ())]
    parcalar += [f"{a} {t}" for a, t in s.get("kalemler", ())]
    parcalar += [f"{e}: {d}" for e, d in s.get("toplamlar", ())]
    parcalar += list(s.get("govde", ()))
    return "\n".join(p for p in parcalar if p)


def a4_koseleri(aci=0.0, olcek=0.75, perspektif=0.03, merkez=(0.5, 0.5), tuval=(3000, 2250)):
    """Tuvalde döndürülmüş, hafif perspektifli A4 kâğıdın köşeleri (oransal; sol üst, sağ üst, sağ alt, sol alt).
    Kâğıt gerçek A4 oranındadır (tests/ornek_gorseller.py'deki sabitler bu orana uymaz ve çıktı basık görünür)."""
    genislik, yukseklik = tuval
    h = yukseklik * olcek
    w = h / 2 ** 0.5
    nokta = np.array([(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)])
    nokta[:2, 0] *= 1 - perspektif  # üst kenar biraz daha uzakta
    r = np.radians(aci)
    donus = np.array([[np.cos(r), -np.sin(r)], [np.sin(r), np.cos(r)]])
    nokta = nokta @ donus.T + np.array([merkez[0] * genislik, merkez[1] * yukseklik])
    return tuple((float(x / genislik), float(y / yukseklik)) for x, y in nokta)


def fotograf(rgb, stil, tohum):
    if stil == "tarama":
        return og.tarayici_ciktisi(rgb, tohum)
    if stil == "masa_koyu":
        ham = og.masada_egik_cekim(kagit=rgb, tohum=tohum, koseler=a4_koseleri(-6, 0.8, 0.04))
        return og.isik_bozulmasi(ham, sari=True, golge=True, tohum=tohum)
    if stil == "masa_acik":
        ham = og.masada_egik_cekim(kagit=rgb, tohum=tohum, koseler=a4_koseleri(4, 0.78, 0.03), zemin_tonu=215)
        return og.isik_bozulmasi(ham, sari=False, golge=True, tohum=tohum)
    if stil == "masa_egik":
        ham = og.masada_egik_cekim(kagit=rgb, tohum=tohum, koseler=a4_koseleri(12, 0.74, 0.05))
        return og.isik_bozulmasi(ham, sari=False, golge=True, tohum=tohum)
    raise ValueError(stil)


TURUNCU, MAVI, YESIL, MOR, GRI = (232, 120, 20), (30, 100, 210), (20, 150, 110), (110, 70, 190), (90, 100, 115)

# saat: yüklenme zamanı kaç saat önce. ("yukleme": ilk çekimde yüklenmez; toplu yükleme adımında gönderilir)
BELGELER = [
    dict(ad="abc_elektronik_fatura.jpg", tur="fatura", guven=0.97, saat=2, stil="masa_koyu", tohum=1, muhur=True, imza=True,
         firma="ABC Elektronik Ticaret Ltd. Şti.", baslik="E-ARŞİV FATURA", renk=TURUNCU,
         bilgiler=[("Fatura No", "ABC2026000000123"), ("Fatura Tarihi", "15.03.2026")],
         kalemler=[("Kablosuz kulaklık, 1 adet", "1.000,00 TL")],
         toplamlar=[("KDV %20", "200,00 TL"), ("Genel Toplam", "1.200,00 TL")],
         aciklama="ABC Elektronik kablosuz kulaklık faturası",
         alanlar=dict(kurum="ABC Elektronik Ticaret Ltd. Şti.", tutar=1200.0, para_birimi="TRY",
                      belge_tarihi="2026-03-15", fatura_no="ABC2026000000123")),
    dict(ad="turkcell_mart.jpg", tur="fatura", guven=0.95, saat=5, stil="tarama", tohum=2,
         firma="Turkcell", alt_baslik="Örnek mobil hat faturası", baslik="FATURA", renk=(20, 60, 160),
         bilgiler=[("Fatura No", "TC2026031234"), ("Fatura Tarihi", "05.03.2026")],
         kalemler=[("Mobil hat paketi, Mart 2026", "349,00 TL")],
         toplamlar=[("Ödenecek Tutar", "349,00 TL")],
         aciklama="Turkcell mobil hat faturası",
         alanlar=dict(kurum="Turkcell", tutar=349.0, para_birimi="TRY", belge_tarihi="2026-03-05", fatura_no="TC2026031234")),
    dict(ad="iski_subat.jpg", tur="fatura", guven=0.93, saat=27, stil="masa_acik", tohum=3,
         firma="İSKİ", alt_baslik="Örnek su faturası", baslik="SU FATURASI", renk=(20, 130, 200),
         bilgiler=[("Fatura No", "IS2026004512"), ("Fatura Tarihi", "18.02.2026")],
         kalemler=[("Su tüketim bedeli", "352,80 TL"), ("Atık su bedeli", "60,00 TL")],
         toplamlar=[("Ödenecek Tutar", "412,80 TL")],
         aciklama="İSKİ su faturası",
         alanlar=dict(kurum="İSKİ", tutar=412.8, para_birimi="TRY", belge_tarihi="2026-02-18", fatura_no="IS2026004512")),
    dict(ad="enerjisa_ocak.jpg", tur="fatura", guven=0.94, saat=70, stil="masa_egik", tohum=4, muhur=True,
         firma="Enerjisa Başkent Elektrik", alt_baslik="Örnek elektrik faturası", baslik="E-ARŞİV FATURA", renk=(230, 190, 20),
         bilgiler=[("Fatura No", "EBK2026000112"), ("Fatura Tarihi", "12.01.2026")],
         kalemler=[("Elektrik tüketim bedeli", "1.070,50 TL"), ("Dağıtım bedeli", "214,10 TL")],
         toplamlar=[("Genel Toplam", "1.284,60 TL")],
         aciklama="Enerjisa elektrik faturası",
         alanlar=dict(kurum="Enerjisa Başkent Elektrik", tutar=1284.6, para_birimi="TRY", belge_tarihi="2026-01-12",
                      fatura_no="EBK2026000112")),
    dict(ad="kira_sozlesmesi.jpg", tur="sozlesme", guven=0.91, saat=100, stil="tarama", tohum=5, imza=True, muhur=True,
         firma="Örnek Yapı A.Ş.", alt_baslik="Örnek iş yeri kira sözleşmesi", baslik="KİRA SÖZLEŞMESİ", renk=MOR,
         bilgiler=[("Sözleşme Tarihi", "02.01.2026"), ("Süre", "12 ay")],
         govde=["Kiraya veren: Örnek Yapı A.Ş.", "Kiracı: Deneme Ticaret Ltd. Şti.",
                "Konu: Ataşehir Örnek Plaza 3. kattaki ofisin kiralanması.", "Aylık kira bedeli 25.000,00 TL'dir.",
                "Bu sözleşme iki nüsha olarak düzenlenmiştir."],
         aciklama="Örnek Yapı A.Ş. ile Deneme Ticaret Ltd. Şti. arasında iş yeri kira sözleşmesi",
         alanlar=dict(kurum="Örnek Yapı A.Ş. – Deneme Ticaret Ltd. Şti.", belge_tarihi="2026-01-02",
                      konu="İş yeri kira sözleşmesi", sure="12 ay")),
    dict(ad="izin_dilekcesi.jpg", tur="dilekce", guven=0.88, saat=120, stil="masa_koyu", tohum=6, imza=True,
         firma="Deneme Ticaret Ltd. Şti.", baslik="DİLEKÇE", renk=YESIL,
         bilgiler=[("Tarih", "10.03.2026")],
         govde=["ÖRNEK BELEDİYESİ FEN İŞLERİ MÜDÜRLÜĞÜNE", "", "Şirketimiz önündeki cadde üzerinde yapılacak", "yol çalışması için geçici izin talep ediyoruz.",
                "Gereğini arz ederim."],
         aciklama="Yol çalışması izin talebi dilekçesi",
         alanlar=dict(kurum="Örnek Belediyesi Fen İşleri Müdürlüğü", konu="Yol çalışması izin talebi", belge_tarihi="2026-03-10")),
    dict(ad="belediye_yazisi.jpg", tur="resmi_yazi", guven=0.9, saat=150, stil="masa_acik", tohum=7, muhur=True,
         firma="Örnek Belediyesi", alt_baslik="Yazı İşleri Müdürlüğü", baslik="RESMİ YAZI", renk=(190, 40, 60),
         bilgiler=[("Sayı", "2026/1457"), ("Tarih", "20.03.2026")],
         govde=["Konu: İşyeri açma ve çalışma ruhsatı", "", "İlgi: 10.03.2026 tarihli başvurunuz.", "Başvurunuz incelenmiş olup ruhsat", "işlemleriniz tamamlanmıştır."],
         aciklama="Örnek Belediyesi ruhsat bildirimi",
         alanlar=dict(kurum="Örnek Belediyesi Yazı İşleri Müdürlüğü", konu="İşyeri açma ve çalışma ruhsatı", sayi="2026/1457",
                      belge_tarihi="2026-03-20")),
    dict(ad="servis_formu.jpg", tur="diger", guven=0.52, saat=200, stil="masa_egik", tohum=8,
         firma="Örnek Teknik Servis", baslik="SERVİS FORMU", renk=GRI,
         bilgiler=[("Form No", "SF-2026-0087"), ("Tarih", "04.03.2026")],
         govde=["Cihaz: Yazıcı", "İşlem: Bakım ve temizlik yapıldı.", "Sonraki bakım: 6 ay sonra"],
         aciklama="Cihaz servis formu",
         alanlar=dict(konu="Yazıcı servis formu", belge_tarihi="2026-03-04")),
]

# Gelen belgeler kutusu (yöneticinin, sahibi belli olmayan taramalar)
GELEN = [
    dict(ad="Tarama_20260930_0001.jpg", tur="fatura", guven=0.9, saat=1, stil="tarama", tohum=11,
         firma="Örnek Kırtasiye Ltd. Şti.", baslik="E-ARŞİV FATURA", renk=(220, 60, 90),
         bilgiler=[("Fatura No", "OK2026000451"), ("Fatura Tarihi", "29.09.2026")],
         kalemler=[("A4 fotokopi kâğıdı, 10 paket", "1.450,00 TL")],
         toplamlar=[("Genel Toplam", "1.450,00 TL")],
         aciklama="Örnek Kırtasiye faturası",
         alanlar=dict(kurum="Örnek Kırtasiye Ltd. Şti.", tutar=1450.0, para_birimi="TRY", belge_tarihi="2026-09-29",
                      fatura_no="OK2026000451")),
    dict(ad="Tarama_20260930_0002.jpg", tur="resmi_yazi", guven=0.86, saat=1, stil="tarama", tohum=12,
         firma="Örnek Vergi Dairesi Başkanlığı", baslik="RESMİ YAZI", renk=(60, 90, 150),
         bilgiler=[("Sayı", "2026/8812"), ("Tarih", "28.09.2026")],
         govde=["Konu: Beyanname hatırlatması", "", "Eylül dönemi beyannamesinin son günü", "duyurulur."],
         aciklama="Vergi dairesi hatırlatma yazısı",
         alanlar=dict(kurum="Örnek Vergi Dairesi Başkanlığı", konu="Beyanname hatırlatması", sayi="2026/8812",
                      belge_tarihi="2026-09-28")),
    dict(ad="Tarama_20260930_0003.jpg", tur="diger", guven=0.55, saat=1, stil="tarama", tohum=13,
         firma="Örnek Lojistik A.Ş.", baslik="TESLİMAT TUTANAĞI", renk=(120, 130, 60),
         bilgiler=[("Tutanak No", "TT-30912"), ("Tarih", "30.09.2026")],
         govde=["Koli sayısı: 4", "Teslim alan: Depo sorumlusu", "Hasar: Yok"],
         aciklama="Teslimat tutanağı",
         alanlar=dict(konu="Teslimat tutanağı", belge_tarihi="2026-09-30")),
]

# Toplu yükleme adımında tarayıcıdan gönderilecek dosyalar (sıra önemlidir)
YUKLENECEKLER = [
    dict(ad="dogalgaz_mart.jpg", tur="fatura", guven=0.94, stil="tarama", tohum=21,
         firma="Örnek Doğalgaz A.Ş.", baslik="FATURA", renk=(40, 120, 190),
         bilgiler=[("Fatura No", "DG2026007731"), ("Fatura Tarihi", "09.03.2026")],
         kalemler=[("Doğalgaz tüketim bedeli", "1.180,40 TL")], toplamlar=[("Ödenecek Tutar", "1.180,40 TL")],
         aciklama="Doğalgaz faturası",
         alanlar=dict(kurum="Örnek Doğalgaz A.Ş.", tutar=1180.4, para_birimi="TRY", belge_tarihi="2026-03-09", fatura_no="DG2026007731")),
    dict(ad="internet_mart.jpg", tur="fatura", guven=0.93, stil="tarama", tohum=22,
         firma="Örnek İnternet Hizmetleri", baslik="FATURA", renk=(120, 60, 180),
         bilgiler=[("Fatura No", "IN2026002210"), ("Fatura Tarihi", "11.03.2026")],
         kalemler=[("Fiber internet, Mart 2026", "429,90 TL")], toplamlar=[("Ödenecek Tutar", "429,90 TL")],
         aciklama="İnternet faturası",
         alanlar=dict(kurum="Örnek İnternet Hizmetleri", tutar=429.9, para_birimi="TRY", belge_tarihi="2026-03-11", fatura_no="IN2026002210")),
    dict(ad="aidat_mart.jpg", tur="fatura", guven=0.9, stil="tarama", tohum=23, engelle=True,
         firma="Örnek Apartmanı Yönetimi", baslik="AİDAT MAKBUZU", renk=(30, 150, 120),
         bilgiler=[("Makbuz No", "AP2026-031"), ("Tarih", "01.03.2026")],
         kalemler=[("Mart 2026 aidatı", "750,00 TL")], toplamlar=[("Toplam", "750,00 TL")],
         aciklama="Aidat makbuzu",
         alanlar=dict(kurum="Örnek Apartmanı Yönetimi", tutar=750.0, para_birimi="TRY", belge_tarihi="2026-03-01")),
    dict(ad="sigorta_police.jpg", tur="sozlesme", guven=0.9, stil="tarama", tohum=24,
         firma="Örnek Sigorta A.Ş.", baslik="SİGORTA POLİÇESİ", renk=(200, 80, 40),
         bilgiler=[("Poliçe No", "PL-2026-55120"), ("Tarih", "01.03.2026")],
         govde=["Teminat: İş yeri yangın sigortası", "Süre: 12 ay"], aciklama="İş yeri sigorta poliçesi",
         alanlar=dict(kurum="Örnek Sigorta A.Ş.", belge_tarihi="2026-03-01", konu="İş yeri yangın sigortası", sure="12 ay")),
    dict(ad="makbuz_mart.jpg", tur="diger", guven=0.9, stil="tarama", tohum=25,
         firma="Örnek Kırtasiye Ltd. Şti.", baslik="TAHSİLAT MAKBUZU", renk=(90, 100, 115),
         bilgiler=[("Makbuz No", "TM-0417"), ("Tarih", "12.03.2026")],
         govde=["Tutar: 320,00 TL", "Açıklama: Kırtasiye malzemesi"], aciklama="Tahsilat makbuzu",
         alanlar=dict(konu="Tahsilat makbuzu", belge_tarihi="2026-03-12")),
]
for _s in BELGELER + GELEN + YUKLENECEKLER:
    _s["metin"] = metin_uret(_s)
TUM = {s["ad"]: s for s in BELGELER + GELEN + YUKLENECEKLER}
METINLER = {s["metin"]: s for s in TUM.values()}
OLUSTURULAN = []  # bu çalıştırmada eklenen kullanıcı id'leri (temizlik yalnızca bunları siler)
ENGELLER = {}  # dosya adı -> Event: sınıflandırma bu olay kurulana kadar bekler


def jpeg_baytlari(s):
    return og.jpeg_bayt(fotograf(sayfa_ciz(s), s["stil"], s["tohum"]), 90)


# ---------------------------------------------------------------- uygulama ve veri

def uygulamayi_hazirla():
    import alanlar
    import classifier
    import database
    import isleme

    ozgun_asama = isleme._goruntu_asamasi
    durum = {"aktif": None}

    def sarmal(is_, bilgi):
        durum["aktif"] = TUM[is_["dosya_adi"]]
        return ozgun_asama(is_, bilgi)

    def sahte_metin(veri, mime, uyarilar):
        return durum["aktif"]["metin"]

    def sahte_siniflandir(metin, bilinen_tur=None):
        s = METINLER[metin]
        olay = ENGELLER.get(s["ad"])
        if olay is not None:
            olay.wait(120)
        return {"tur": s["tur"], "guven": s["guven"], "aciklama": s["aciklama"], "yogun": False,
                "alanlar": alanlar.dogrula(s["tur"], s["alanlar"])[0]}

    isleme._goruntu_asamasi = sarmal
    isleme._metin_oku = sahte_metin
    classifier.siniflandir = sahte_siniflandir

    import app as uygulama_modulu

    uygulama_modulu.limiter.enabled = False
    database.veritabanini_hazirla()
    return uygulama_modulu, database, isleme


def veriyi_olustur(database, isleme, kimlik):
    """demo (yönetici) ve diğer kullanıcılar; demo'nun belgeleri ve Gelen belgeler kutusu."""
    if database.kullanici_adi_ile_getir(DEMO_AD):
        sys.exit(f"Test veritabanında '{DEMO_AD}' kullanıcısı zaten var (önceki çalıştırmadan kalmış olabilir). "
                 "Silmek için --eski-demoyu-sil ile yeniden çalıştırın.")
    sifre_hash = kimlik.sifre_hashle(DEMO_SIFRE)
    demo_id = database.kullanici_ekle(DEMO_AD, sifre_hash)
    OLUSTURULAN.append(demo_id)
    diger = [database.kullanici_ekle(ad, sifre_hash) for ad in DIGER_KULLANICILAR]
    OLUSTURULAN.extend(diger)
    database._sorgula("UPDATE kullanicilar SET yonetici = TRUE WHERE id = %s", (demo_id,))
    ids = {}
    for s in BELGELER:
        ids[s["ad"]] = _yukle(database, isleme, demo_id, s)
    for s in GELEN:
        ids[s["ad"]] = _yukle(database, isleme, demo_id, s, gelen=True)
    return demo_id, diger, ids


def _yukle(database, isleme, kullanici_id, s, gelen=False):
    belge_id = isleme.kuyruga_ekle(kullanici_id, jpeg_baytlari(s), "image/jpeg", s["ad"], True, gelen,
                                   "klasor" if gelen else None)
    isleme.bekleyenleri_isle(belge_id=belge_id)
    database._sorgula("UPDATE belgeler SET yuklenme_tarihi = NOW() - %s WHERE id = %s",
                      (timedelta(hours=s["saat"]), belge_id))
    return belge_id


def taklit_tarayici(uygulama_modulu):
    """Bağlı tarayıcı olarak sentetik bir ağ tarayıcısı gösterilir (gerçek WIA taraması yapılmaz)."""
    import time

    import tarayici_wia

    tarayici_wia._durum.tarayicilar = [{"id": "ornek-tarayici", "ad": "Örnek Ağ Tarayıcısı"}]
    tarayici_wia._durum.son_kontrol = time.monotonic() + 10 ** 7  # liste yenilenmez, gerçek cihaz sorulmaz
    uygulama_modulu.TARAYICI_WIA = True


def taklit_klasorler_ve_gunluk():
    """Yönetici sayfaları için sentetik klasör yolları ve günlük (yalnızca bellekte)."""
    import klasor_izleme
    import tarama_gunlugu

    klasor_izleme.izlenen_klasorler = lambda: [
        {"yol": r"D:\ArcBase\Tarama", "tur": "Tarama klasörü (TARAMA_KLASORU)", "izleniyor": True, "kaldirilabilir": False,
         "not": "Alt klasörler kullanıcı adıdır; .env'deki ayardan değiştirilir."},
        {"yol": r"C:\Users\Public\Documents\Taramalar", "tur": klasor_izleme.VARSAYILAN_TUR, "izleniyor": True,
         "kaldirilabilir": True, "not": ""},
        {"yol": r"D:\Belgeler\Muhasebe\Gelen", "tur": klasor_izleme.EKLENEN_TUR, "izleniyor": True,
         "kaldirilabilir": True, "not": "Yalnızca eklendikten sonra düşen dosyalar alınır."},
    ]
    tarama_gunlugu.temizle()
    tarama_gunlugu.hata("Klasör: D:\\ArcBase\\Tarama", "'satis' adlı bir kullanıcı yok; klasör adı kullanıcı adıyla aynı olmalı.")
    tarama_gunlugu.aktarildi("Tarama_20260930_0003.jpg", "demo", gelen_kutusu=True, kaynak="D:\\ArcBase\\Tarama")
    tarama_gunlugu.aktarildi("Tarama_20260930_0002.jpg", "demo", gelen_kutusu=True, kaynak="D:\\ArcBase\\Tarama")
    tarama_gunlugu.aktarildi("fatura_eylul.pdf", "muhasebe", kaynak="D:\\ArcBase\\Tarama\\muhasebe")
    tarama_gunlugu.aktarildi("Tarama_20260930_0001.jpg", "demo", gelen_kutusu=True, kaynak="D:\\ArcBase\\Tarama")
    tarama_gunlugu.aktarildi("tedarikci_sozlesme.pdf", "insan_kaynaklari", kaynak="D:\\ArcBase\\Tarama\\insan_kaynaklari")


# ---------------------------------------------------------------- çekim

class Cekim:
    def __init__(self, taban, cikti, secim, uygulama_belgeleri):
        self.taban, self.cikti, self.secim = taban, cikti, secim
        self.ids = uygulama_belgeleri
        self.uyarilar = []
        self.cekilenler = []

    def istenen(self, ad):
        return not self.secim or ad in self.secim

    def sayfa_ac(self, baglam, izleme):
        s = baglam.new_page()
        s.set_default_timeout(20000)
        s.on("pageerror", lambda h: self.uyarilar.append(f"[{izleme[0]}] sayfa hatası: {h}"))
        s.on("console", lambda m: m.type == "error" and self.uyarilar.append(f"[{izleme[0]}] konsol: {m.text}"))
        s.on("response", lambda r: r.status >= 400 and self.uyarilar.append(f"[{izleme[0]}] HTTP {r.status} {r.url.split('/', 3)[-1]}"))
        return s

    def hazirla(self, s):
        try:
            s.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        try:
            s.wait_for_function(GORSELLER_HAZIR, timeout=10000)
        except Exception:
            self.uyarilar.append("görseller tam yüklenmedi: " + s.url)
        s.wait_for_timeout(1500)
        s.evaluate(BITIR)
        s.wait_for_timeout(150)

    def denetle(self, s, ad):
        metin = s.inner_text("body")
        for desen in YASAK:
            if re.search(desen, metin):
                self.uyarilar.append(f"[{ad}] yasak metin bulundu: {desen}")

    def cek_oge(self, s, ad, secici, yukseklik=1500):
        """Öğeyi, sabit üst çubuğun altında kalmasın diye görünüm yüksekliği artırılıp sayfa başında çeker."""
        s.set_viewport_size({"width": s.viewport_size["width"], "height": yukseklik})
        s.evaluate("window.scrollTo(0, 0)")
        s.wait_for_timeout(500)
        self.denetle(s, ad)
        yol = self.cikti / f"{ad}.png"
        s.screenshot(path=str(yol), clip=s.locator(secici).first.bounding_box())
        s.set_viewport_size({"width": s.viewport_size["width"], "height": YUKSEKLIK})
        self.cekilenler.append(yol)
        print("  çekildi:", yol.name)

    def cek(self, s, ad, oge=None, tam_sayfa=False, hazirla=True):
        if hazirla:
            self.hazirla(s)
        self.denetle(s, ad)
        yol = self.cikti / f"{ad}.png"
        if oge is not None:
            oge.screenshot(path=str(yol))
        else:
            s.screenshot(path=str(yol), full_page=tam_sayfa)
        self.cekilenler.append(yol)
        print("  çekildi:", yol.name)


def cek_hepsi(tarayici, cekim, uygulama_modulu, database, isleme, demo_id, ids):
    taban, secim = cekim.taban, cekim.istenen
    izleme = [""]

    def baglam(tema="acik", mobil=False, storage=None):
        secenekler = dict(locale="tr-TR", timezone_id="Europe/Istanbul", color_scheme="light", storage_state=storage,
                          viewport={"width": MOBIL[0], "height": MOBIL[1]} if mobil else {"width": GENISLIK, "height": YUKSEKLIK})
        if mobil:
            secenekler.update(device_scale_factor=2, is_mobile=True, has_touch=True)
        b = tarayici.new_context(**secenekler)
        # "Tarayıcı bulundu" bildirimi çıkmasın: sentetik tarayıcı bu sekmede zaten bilinen sayılır
        b.add_init_script(f"try {{ localStorage.setItem('tema', '{tema}'); "
                          "sessionStorage.setItem('bilinenTarayicilar', '[\"ornek-tarayici\"]'); } catch (e) {}")
        return b

    def giris_yap(b, sayfa):
        sayfa.goto(taban + "/giris")
        sayfa.fill("input[name=kullanici_adi]", DEMO_AD)
        sayfa.fill("input[name=sifre]", DEMO_SIFRE)
        sayfa.click("button[type=submit]")
        sayfa.wait_for_url(taban + "/")
        return b.storage_state()

    def adim(ad):
        izleme[0] = ad
        return secim(ad)

    # -- çıkış yapmamış (misafir) sayfalar
    if any(adim(a) for a in ("acilis", "giris")):
        b = baglam()
        s = cekim.sayfa_ac(b, izleme)
        if adim("acilis"):
            s.goto(taban + "/")
            cekim.hazirla(s)
            s.set_viewport_size({"width": GENISLIK, "height": s.evaluate("document.documentElement.scrollHeight")})
            s.wait_for_timeout(600)
            cekim.cek(s, "acilis", hazirla=False)
            s.set_viewport_size({"width": GENISLIK, "height": YUKSEKLIK})
        if adim("giris"):
            s.goto(taban + "/giris")
            s.fill("input[name=kullanici_adi]", DEMO_AD)
            cekim.cek(s, "giris")
        b.close()
    if adim("mobil-giris"):
        b = baglam(mobil=True)
        s = cekim.sayfa_ac(b, izleme)
        s.goto(taban + "/giris")
        s.fill("input[name=kullanici_adi]", DEMO_AD)
        cekim.cek(s, "mobil-giris")
        b.close()

    # -- oturum aç
    b0 = baglam()
    s0 = cekim.sayfa_ac(b0, izleme)
    oturum = giris_yap(b0, s0)
    b0.close()

    b = baglam(storage=oturum)
    s = cekim.sayfa_ac(b, izleme)

    def menuyu_ac(sayfa):
        for grup in ("arsiv", "yonetim"):
            sayfa.click(f"[data-grup-dugmesi={grup}]")
        sayfa.wait_for_timeout(600)

    if adim("panel"):
        s.goto(taban + "/")
        menuyu_ac(s)
        cekim.cek(s, "panel")

    if adim("belge") or adim("tarama-karsilastirma") or adim("kose-duzenleme"):
        abc = ids["abc_elektronik_fatura.jpg"]
        if adim("belge"):
            s.goto(f"{taban}/belge/{abc}")
            s.wait_for_selector("[data-karsilastir]:not([hidden])")
            cekim.cek(s, "belge")
        if adim("tarama-karsilastirma"):
            s.goto(f"{taban}/belge/{abc}")
            s.wait_for_selector("[data-karsilastir]:not([hidden])")
            s.click("[data-karsilastir]")
            s.wait_for_selector("[data-karsilastirma]:not([hidden])")
            s.evaluate("""() => { const r = document.querySelector('[data-ayirici]'); r.value = 46;
                                  r.dispatchEvent(new Event('input', {bubbles: true})); }""")
            cekim.hazirla(s)
            cekim.cek_oge(s, "tarama-karsilastirma", "section[data-tarama] > div")
        if adim("kose-duzenleme"):
            s.goto(f"{taban}/belge/{abc}")
            s.wait_for_selector("[data-kose-ac]:not([hidden])")
            s.click("[data-kose-ac]")
            s.wait_for_selector("[data-kose-editoru]:not([hidden])")
            s.wait_for_function("() => { const i = document.querySelector('[data-kose-gorsel]'); return i && i.complete && i.naturalWidth > 0; }")
            s.wait_for_timeout(1200)
            s.set_viewport_size({"width": GENISLIK, "height": 1500})  # cek_oge ile aynı boy: sürüklerken yeniden dizilim olmasın
            s.evaluate("window.scrollTo(0, 0)")
            s.wait_for_timeout(500)
            kutu = s.locator('[data-tutamac="1"]').bounding_box()
            x, y = kutu["x"] + kutu["width"] / 2, kutu["y"] + kutu["height"] / 2
            s.mouse.move(x, y)
            s.mouse.down()
            s.mouse.move(x - 5, y + 7, steps=6)
            s.wait_for_timeout(300)
            cekim.cek_oge(s, "kose-duzenleme", "section[data-tarama] > div")
            s.mouse.up()
            s.click("[data-kose-vazgec]")

    if adim("fatura-filtre"):
        s.goto(taban + "/kategori/fatura?baslangic=2026-02-01&bitis=2026-03-31&min_tutar=300&siralama=tutar")
        cekim.cek(s, "fatura-filtre")

    if adim("secim-birlestirme"):
        s.goto(taban + "/kategori/fatura")
        s.wait_for_selector("[data-secim-ac]:not([hidden])")
        s.click("[data-secim-ac]")
        kartlar = s.locator(".belge-karti")
        for sira in (2, 0, 1):
            kartlar.nth(sira).click()
            s.wait_for_timeout(250)
        cekim.cek(s, "secim-birlestirme")

    if adim("hesap"):
        s.goto(taban + "/hesap")
        cekim.cek(s, "hesap")

    if adim("gelen-belgeler"):
        s.goto(taban + "/gelen")
        cekim.cek(s, "gelen-belgeler")
    if adim("izlenen-klasorler"):
        s.goto(taban + "/klasorler")
        cekim.cek(s, "izlenen-klasorler")
    if adim("yonetici-tarama-durumu"):
        s.goto(taban + "/tarama-durumu")
        cekim.cek(s, "yonetici-tarama-durumu")
    b.close()

    # -- koyu tema
    if adim("panel-koyu"):
        b = baglam(tema="koyu", storage=oturum)
        s = cekim.sayfa_ac(b, izleme)
        s.goto(taban + "/")
        menuyu_ac(s)
        cekim.cek(s, "panel-koyu")
        b.close()

    # -- mobil
    if adim("mobil-panel") or adim("mobil-menu"):
        b = baglam(mobil=True, storage=oturum)
        s = cekim.sayfa_ac(b, izleme)
        s.goto(taban + "/")
        if adim("mobil-panel"):
            cekim.cek(s, "mobil-panel")
        if adim("mobil-menu"):
            s.click("[data-menu-ac]")
            s.wait_for_timeout(700)
            menuyu_ac(s)
            cekim.cek(s, "mobil-menu", hazirla=False)
        b.close()

    # -- toplu yükleme: gerçek arka plan işçisiyle; bazı adımlar bilerek bekletilir
    if adim("toplu-yukleme"):
        toplu_yukleme(tarayici, cekim, baglam, oturum, isleme, database, demo_id, izleme)


def toplu_yukleme(tarayici, cekim, baglam, oturum, isleme, database, demo_id, izleme):
    """Gerçek arka plan işçisiyle 6 dosya: geçersiz olan hata satırı olur, işçi ilk ikisini bitirir, üçüncüsü
    (aidat_mart.jpg) sınıflandırmada bekletilir; istemci durum yoklamasını tüm dosyalar gönderildikten sonra
    başlatır, kalan satırlar "Metin okunuyor ve belge sınıflandırılıyor…" durumunda görünür."""
    taban = cekim.taban
    engel = ENGELLER["aidat_mart.jpg"] = threading.Event()
    isleme.baslat(kullanici_id=demo_id)
    b = baglam(storage=oturum)
    s = cekim.sayfa_ac(b, izleme)
    s.goto(taban + "/")
    form = s.locator("main [data-yukleme-formu]").first
    dosyalar = [{"name": ad, "mimeType": tur, "buffer": veri} for ad, tur, veri in [
        ("dogalgaz_mart.jpg", "image/jpeg", jpeg_baytlari(TUM["dogalgaz_mart.jpg"])),
        ("internet_mart.jpg", "image/jpeg", jpeg_baytlari(TUM["internet_mart.jpg"])),
        ("aidat_mart.jpg", "image/jpeg", jpeg_baytlari(TUM["aidat_mart.jpg"])),
        ("notlar.txt", "text/plain", b"toplanti notlari"),
        ("sigorta_police.jpg", "image/jpeg", jpeg_baytlari(TUM["sigorta_police.jpg"])),
        ("makbuz_mart.jpg", "image/jpeg", jpeg_baytlari(TUM["makbuz_mart.jpg"])),
    ]]
    form.locator("[data-dosya-girisi]").set_input_files(dosyalar)
    form.locator("button[type=submit]").click()
    try:
        s.wait_for_function(
            "() => document.querySelectorAll('main [data-yukleme-formu] [data-kuyruk] li[data-durum=kaydedildi]').length >= 2",
            timeout=60000)
        s.wait_for_timeout(1500)
        cekim.hazirla(s)
        cekim.cek_oge(s, "toplu-yukleme", ".kenar-isini")
    finally:
        engel.set()  # bırak: her şey bitsin (temizlik için)
        deadline = time.time() + 90
        while time.time() < deadline:
            kalan = database._sorgula(
                "SELECT COUNT(*) AS n FROM belgeler WHERE kullanici_id = %s AND isleme_durumu IN ('bekliyor', 'isleniyor')",
                (demo_id,), tek=True)["n"]
            if not kalan:
                break
            time.sleep(1)
        b.close()


# ---------------------------------------------------------------- sonuç görselleri

def once_sonra_uret(cikti):
    """tarama-once-sonra-sentetik.jpg: docs/once_sonra.py ile, tests/ornek_gorseller.py çekimlerinden."""
    rgb, _ = og.renkli_belge()
    kok = _gecici / "once_sonra"
    kok.mkdir()
    bir = og.isik_bozulmasi(og.masada_egik_cekim(kagit=rgb, koseler=a4_koseleri(22, 0.7, 0.05)), sari=True, golge=True)
    iki = og.isik_bozulmasi(og.masada_egik_cekim(kagit=rgb, koseler=a4_koseleri(-7, 0.8, 0.03), zemin_tonu=215), sari=False, golge=True)
    yollar = []
    for i, foto in enumerate((bir, iki), 1):
        yol = kok / f"foto{i}.jpg"
        yol.write_bytes(og.jpeg_bayt(foto, 92))
        yollar.append(str(yol))
    hedef = cikti / "tarama-once-sonra-sentetik.jpg"
    subprocess.run([sys.executable, str(KOK / "docs" / "once_sonra.py"), *yollar, "--cikti", str(hedef)],
                   check=True, cwd=str(KOK))
    return hedef


def png_kucult(yol, en_fazla_kb=480):
    """PNG'yi kayıpsız sıkıştırır; hâlâ büyükse 256 renge indirir (arayüz görüntülerinde fark edilmez)."""
    g = Image.open(yol)
    g.load()
    g.save(yol, optimize=True)
    if yol.stat().st_size > en_fazla_kb * 1024:
        g.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(yol, optimize=True)


def main():
    arg = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    arg.add_argument("--cikti", default=str(KOK / "docs" / "screenshots"))
    arg.add_argument("--sadece", default="", help="virgülle ayrılmış görsel adları (uzantısız)")
    arg.add_argument("--veriyi-tut", action="store_true", help="işlem sonunda demo verisini silme")
    arg.add_argument("--eski-demoyu-sil", action="store_true", help="test veritabanında kalmış 'demo' kullanıcılarını sil")
    a = arg.parse_args()
    cikti = Path(a.cikti)
    cikti.mkdir(parents=True, exist_ok=True)
    secim = {x.strip() for x in a.sadece.split(",") if x.strip()}

    uygulama_modulu, database, isleme = uygulamayi_hazirla()
    import kimlik

    if a.eski_demoyu_sil:
        for ad in (DEMO_AD, *DIGER_KULLANICILAR):
            satir = database.kullanici_adi_ile_getir(ad)
            if satir:
                database.kullanici_sil(satir["id"])
                print("silindi (test veritabanı):", ad)
    print("Test veritabanındaki kullanıcı sayısı (demo öncesi):",
          database._sorgula("SELECT COUNT(*) AS n FROM kullanicilar", tek=True)["n"])

    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright

    demo_id = diger = None
    sunucu = None
    try:
        print("Sentetik veri oluşturuluyor (gerçek boru hattı: köşe algılama, önizleme, şifreleme)...")
        demo_id, diger, ids = veriyi_olustur(database, isleme, kimlik)
        taklit_klasorler_ve_gunluk()
        taklit_tarayici(uygulama_modulu)
        sunucu = make_server("127.0.0.1", 0, uygulama_modulu.app, threaded=True)
        threading.Thread(target=sunucu.serve_forever, daemon=True).start()
        taban = f"http://127.0.0.1:{sunucu.server_port}"
        print("Geçici sunucu portu:", sunucu.server_port)
        cekim = Cekim(taban, cikti, secim, ids)
        with sync_playwright() as p:
            tarayici = p.chromium.launch()
            try:
                cek_hepsi(tarayici, cekim, uygulama_modulu, database, isleme, demo_id, ids)
            finally:
                tarayici.close()
        if not secim or "tarama-once-sonra-sentetik" in secim:
            cekim.cekilenler.append(once_sonra_uret(cikti))
        for yol in cekim.cekilenler:
            if yol.suffix == ".png":
                png_kucult(yol)
        print("\nDosya boyutları:")
        for yol in cekim.cekilenler:
            print(f"  {yol.name:<40} {yol.stat().st_size / 1024:7.1f} KB  {Image.open(yol).size}")
        if cekim.uyarilar:
            print("\nUYARILAR:")
            for u in dict.fromkeys(cekim.uyarilar):
                print("  -", u)
        else:
            print("\nUyarı yok (konsol hatası, HTTP hatası ya da yasak metin bulunmadı).")
    finally:
        isleme.durdur(bekle=15)
        if sunucu is not None:
            sunucu.shutdown()
            print("Geçici sunucu kapatıldı.")
        if not a.veriyi_tut:
            for kullanici_id in OLUSTURULAN:
                database.kullanici_sil(kullanici_id)
            print("Demo kullanıcıları ve belgeleri test veritabanından silindi.")
        shutil.rmtree(_gecici, ignore_errors=True)


if __name__ == "__main__":
    main()
