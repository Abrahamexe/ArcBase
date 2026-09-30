"""Dijital Arsiv ve Belge Siniflandirma Sistemi — Flask uygulamasi."""

import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

import alanlar
import classifier
import crypto
import database
import excel
import goruntu_duzelt
import isleme
import izlenen_klasorler
import kimlik
import klasor_izleme
import ocr
import onbellek
import pdf_uret
import tarama
import tarama_gunlugu
import word_uret
import yerel_mod
from database import BEKLIYOR, DUSUK_GUVEN_SINIRI, HATA, ISLENIYOR, TAMAMLANDI, TURLER, VARSAYILAN_TUR

load_dotenv()

# YEREL_MOD=1: veritabani bu bilgisayarda ya da yerel agda olmali (yerel_mod.py).
# Kurala uymayan ayarla uygulama hic baslamaz, nedeni ekrana yazilir.
try:
    yerel_mod.denetle()
except yerel_mod.YerelModHatasi as _hata:
    raise SystemExit(f"ArcBase başlatılamadı: {_hata}") from None

# Alt bilgide gosterilen surum (yeni surumde elle artirilir).
SURUM = "1.1.0"

# Uzanti -> MIME tipi; izin verilen dosya turleri bu sozlukten belirlenir.
IZINLI_TURLER = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
}
MAKS_DOSYA_BOYUTU = 10 * 1024 * 1024  # 10 MB (gorseller; saklamadan once kucultulur)
MAKS_PDF_BOYUTU = 5 * 1024 * 1024  # PDF'ler oldugu gibi saklandigi icin daha dusuk
PDF_MIME = "application/pdf"
SON_BELGE_SAYISI = 6  # dashboard'da gosterilen son belge sayisi
ARAMA_SINIRI = 100  # aramada gosterilen en fazla sonuc
# JS kapaliyken "bilgi cikar" formu tek istekte en fazla bu kadar belge isler
# (her belge bir Groq cagrisi; gunicorn'un 120 sn zaman asimina takilmasin).
BILGI_CIKARMA_PARTISI = 5
GOSTERIM_KALITESI = 88  # aninda uretilen gorsellerin JPEG kalitesi
TOPLU_YUKLEME_SINIRI = 10
# Birlestirilecek en fazla belge: her gorsel sayfa icin OCR yapilir; gunicorn'un
# 120 sn zaman asimina takilmamasi icin.
PDF_BIRLESTIRME_SINIRI = 20  # tarayicida tek seferde secilebilecek en fazla dosya
# Neon ucretsiz plani 0.5 GB; kullanici basina belge sayisi sinirlanir.
KULLANICI_BELGE_LIMITI = int(os.getenv("KULLANICI_BELGE_LIMITI") or 50)
# Sifre dogrulayan formlar (giris, sifre degistirme, hesap silme) icin ortak sinir.
SIFRE_DENEME_SINIRI = "5 per minute;20 per hour"
# Islenmis gorseller (tarama, duzeltilmis gorsel, onizleme) icin surec basina bellek.
GORSEL_ONBELLEGI_MB = int(os.getenv("GORSEL_ONBELLEGI_MB") or 48)
DURUM_SORGU_SINIRI = 50  # tek yoklamada sorulabilecek en fazla belge
# Bu bilgisayara bagli tarayicidan dogrudan tarama (tarayici_wia.py): Windows'ta
# varsayilan acik, TARAYICI_WIA=0 kapatir. Kapaliyken modul yuklenmez, "Tara" gorunmez.
TARAYICI_WIA = sys.platform == "win32" and os.getenv("TARAYICI_WIA", "").strip() != "0"
# Gelen belgeler kutusunun yoneticisi; bos ise ilk olusturulan kullanici.
YONETICI_KULLANICI = (os.getenv("YONETICI_KULLANICI") or "").strip() or None

# Dockerfile URETIM=1 ayarlar (Render). Yerelde "python app.py" gelistirme
# modunda calisir: debug acik, cerezler HTTP uzerinden de gonderilir.
URETIM = os.getenv("URETIM") == "1"
# Yerel mod (kurum): uygulama yerel agda cogunlukla duz HTTP ile calisir
# (sunucu.py / baslat.bat). HTTPS=1: onde TLS saglayan bir sunucu var.
YEREL_MOD = yerel_mod.acik()
HTTPS = os.getenv("HTTPS") == "1"
# "Secure" cerez yalnizca HTTPS'te gonderilir; HTTP'de acik kalirsa giris
# yapilamaz. Render (URETIM) her zaman HTTPS'tir; yerel modda yalnizca HTTPS=1.
GUVENLI_CEREZ = HTTPS if YEREL_MOD else (URETIM or HTTPS)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or (
    None if URETIM or YEREL_MOD else "gelistirme-anahtari"
)
if not app.config["SECRET_KEY"]:
    raise RuntimeError("SECRET_KEY tanımlı değil; üretimde ve yerel modda zorunludur.")
app.config["MAX_CONTENT_LENGTH"] = MAKS_DOSYA_BOYUTU
app.config["WTF_CSRF_TIME_LIMIT"] = None  # token oturum boyunca gecerli
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=GUVENLI_CEREZ,
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_SECURE=GUVENLI_CEREZ,
)
if HTTPS:
    app.config["PREFERRED_URL_SCHEME"] = "https"
if URETIM and not YEREL_MOD:
    # Render istekleri bir vekil sunucu (proxy) uzerinden iletir; gercek istemci
    # IP'si (hiz siniri icin) ve https bilgisi X-Forwarded-* basliklarindan okunur.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.config["PREFERRED_URL_SCHEME"] = "https"

csrf = CSRFProtect(app)

oturum_yoneticisi = LoginManager(app)
oturum_yoneticisi.login_view = "giris"
oturum_yoneticisi.login_message = "Devam etmek için giriş yapın."
oturum_yoneticisi.login_message_category = "uyari"
oturum_yoneticisi.user_loader(kimlik.oturumdan_yukle)

# Sayaclar bellekte tutulur; her gunicorn islemi (worker) kendi sayacini tutar,
# yani 2 worker ile sinir en kotu durumda iki katina cikabilir. Bu olcekte
# Redis gibi ortak bir depo gerekmez.
limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")

_veritabani_hazir = False


def _veritabanini_hazirla_bir_kez():
    """Tabloyu ilk istekte olusturur ve arka plan iscisini baslatir.

    Acilista degil ilk istekte yapiliyor; boylece .env eksikse uygulama
    baslamak yerine anlasilir bir hata sayfasi gosterebiliyor. (Gunicorn'da
    isci ayrica worker acilir acilmaz baslar: gunicorn.conf.py.)
    """
    global _veritabani_hazir
    if not _veritabani_hazir:
        database.veritabanini_hazirla()
        database.yoneticiyi_belirle(YONETICI_KULLANICI)
        _veritabani_hazir = True
    if isleme.etkin():
        isleme.baslat()
    if klasor_izleme.etkin():
        klasor_izleme.baslat(KULLANICI_BELGE_LIMITI)
    arka_plan_izleyicilerini_baslat()


def arka_plan_izleyicilerini_baslat():
    """Windows varsayilan tarama klasorleri ve tarayici algilama (Windows'ta,
    arka plan iscisi aciksa; ikisi de surec basina bir kez baslar)."""
    if klasor_izleme.varsayilan_klasorler_etkin():
        klasor_izleme.varsayilan_baslat(KULLANICI_BELGE_LIMITI)
    if TARAYICI_WIA and isleme.etkin():
        _wia().izlemeyi_baslat()


@app.before_request
def _istek_oncesi():
    if request.endpoint == "static":
        return
    _veritabanini_hazirla_bir_kez()


# Statik dosyalar (CSS/JS) adreslerine degisiklik zamanini ekler: tarayici
# dosyayi uzun sure onbellekte tutar, dosya degisince adres de degisir.
_statik_surumler = {}


@app.url_defaults
def _statik_surum(endpoint, degerler):
    if endpoint != "static" or "filename" not in degerler:
        return
    dosya = degerler["filename"]
    if dosya not in _statik_surumler or not (URETIM or YEREL_MOD):
        yol = Path(app.static_folder) / dosya
        _statik_surumler[dosya] = int(yol.stat().st_mtime) if yol.is_file() else 0
    degerler["v"] = _statik_surumler[dosya]


@app.after_request
def _statik_onbellek(yanit):
    if request.endpoint == "static" and request.args.get("v") and yanit.status_code == 200:
        yanit.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return yanit


@app.errorhandler(database.VeritabaniHatasi)
def _veritabani_hatasi(hata):
    return render_template("hata.html", baslik="Veritabanı hatası", mesaj=str(hata)), 503


@app.errorhandler(crypto.SifrelemeHatasi)
def _sifreleme_hatasi(hata):
    return render_template("hata.html", baslik="Şifreleme hatası", mesaj=str(hata)), 503


@app.errorhandler(CSRFError)
def _csrf_hatasi(hata):
    mesaj = "Form süresi doldu veya geçersiz. Lütfen sayfayı yenileyip tekrar deneyin."
    if _json_istegi():
        return {"basarili": False, "hata": mesaj}, 400
    flash(mesaj, "hata")
    return redirect(_geri_adres())


def _geri_adres():
    """Istegin geldigi sayfa (yalnizca ayni siteyse), yoksa panel."""
    geldigi = request.referrer or ""
    return geldigi if urlsplit(geldigi).netloc == request.host else url_for("index")


@app.errorhandler(429)
def _cok_fazla_istek(hata):
    mesaj = "Çok fazla deneme yaptınız. Lütfen biraz bekleyip tekrar deneyin."
    if request.endpoint in ("giris", "kayit"):
        sablon = f"{request.endpoint}.html"
        return render_template(sablon, hata=mesaj, form=request.form), 429
    if request.endpoint in ("sifre_degistir", "hesap_sil"):
        flash(mesaj, "hata")
        return redirect(url_for("hesap"))
    return (
        render_template("hata.html", baslik="Çok fazla istek", mesaj=mesaj, ipuclari=False),
        429,
    )


@app.errorhandler(404)
def _bulunamadi(hata):
    # Baskasinin belgesi de buraya duser: belgenin var oldugu bile belli edilmez.
    return (
        render_template(
            "hata.html",
            baslik="Sayfa bulunamadı",
            mesaj="Aradığınız sayfa ya da belge bulunamadı.",
            ipuclari=False,
        ),
        404,
    )


@app.errorhandler(413)
def _dosya_cok_buyuk(hata):
    mesaj = "Dosya çok büyük. En fazla 10 MB yükleyebilirsiniz."
    if _json_istegi():
        return {"basarili": False, "hata": mesaj}, 413
    flash(mesaj, "hata")
    return redirect(url_for("index"))


app.add_template_filter(alanlar.tutar_yaz, "tutar")
app.add_template_filter(alanlar.tarih_yaz, "tarih")


@app.context_processor
def _ortak_degiskenler():
    """base.html'deki kategori menusu ve arama kutusu icin ortak veriler.

    Sayaclar sadece giris yapan kullanicinin belgelerini sayar. Kullaniciyla
    ayni sorguda gelir (kimlik.oturumdan_yukle); ayrica sorgu yapilmaz.
    """
    sayaclar = _sayaclar()
    sayilar = sayaclar["turler"]
    toplam = sayaclar["toplam"]
    return {
        "turler": TURLER,
        "tur_sayilari": sayilar,
        "bu_hafta_yuklenen": sayaclar["bu_hafta"],
        "isleniyor_sayisi": sayaclar["isleniyor"],
        "alan_tanimlari": alanlar.ALANLAR,
        "para_birimleri": alanlar.PARA_SIMGELERI,
        "dusuk_guven_siniri": DUSUK_GUVEN_SINIRI,
        "belge_limiti": KULLANICI_BELGE_LIMITI,
        "kalan_kota": max(KULLANICI_BELGE_LIMITI - toplam, 0),
        "toplu_yukleme_siniri": TOPLU_YUKLEME_SINIRI,
        "pdf_birlestirme_siniri": PDF_BIRLESTIRME_SINIRI,
        "kota_doldu": toplam >= KULLANICI_BELGE_LIMITI,
        "gelen_sayisi": sayaclar["gelen"],
        "tarayici_wia": TARAYICI_WIA,
        # Sayfa acilirken bilinen tarayicilar (yalnizca onbellek; WIA'ya sorulmaz).
        "bagli_tarayicilar": _wia().bagli_tarayicilar(False) if TARAYICI_WIA else [],
        "klasor_yonetimi_izinli": _klasor_yonetimi_izinli(),
        "yerel_mod": YEREL_MOD,
        "surum": SURUM,
        "gelen_kutusu_var": _gelen_kutusu_var(sayaclar),
        "arama_sorgusu": request.args.get("q", ""),
    }


def _sayaclar():
    """Kullanicinin sayaclari (database.sayac_ozeti bicimi); giris yoksa sifir."""
    try:
        if current_user.is_authenticated:
            if current_user.sayaclar is None:  # giris/kayit anindaki nesne
                current_user.sayaclar = database.kullanici_ozeti(current_user.id)["sayaclar"]
            return current_user.sayaclar
    except database.VeritabaniHatasi:
        pass
    return database.sayac_ozeti([])


def _gelen_kutusu_var(sayaclar=None):
    """Menude "Gelen belgeler": yoneticide her zaman, eski yoneticide kutuda
    belge kaldiysa."""
    if not current_user.is_authenticated:
        return False
    return current_user.yonetici or (sayaclar or _sayaclar())["gelen"] > 0


def _suzgecler(tur=None):
    """Kategori, arama ve Excel disa aktarmanin ortak suzgecleri (request.args).

    Donus: (database.belgeleri_suz'e verilecek parametreler, URL'de tasinacak
    bos olmayan ham degerler — sayfalama ve Excel baglantilari icin).
    """
    args = request.args
    suz = {
        "baslangic": alanlar.tarih_dogrula(args.get("baslangic")),
        "bitis": alanlar.tarih_dogrula(args.get("bitis")),
        "kurum": (args.get("kurum") or "").strip()[:100] or None,
        "siralama": args.get("siralama") if args.get("siralama") in database.SIRALAMALAR else "yukleme",
    }
    if tur == "fatura":  # tutar sadece faturalarda cikarilir
        suz["min_tutar"] = alanlar.tutar_dogrula(args.get("min_tutar"))
        suz["maks_tutar"] = alanlar.tutar_dogrula(args.get("maks_tutar"))
    url = {anahtar: args.get(anahtar) for anahtar, deger in suz.items() if deger is not None}
    if suz["siralama"] == "yukleme":
        url.pop("siralama", None)
    return suz, url


def _tutar_toplamlari(belgeler):
    """Para birimine gore toplam tutarlar: {'TRY': Decimal, ...}. Para birimi
    okunamayanlar '' anahtarinda toplanir."""
    toplamlar = {}
    for b in belgeler:
        if b["tutar"] is not None:
            para = b["para_birimi"] or ""
            toplamlar[para] = toplamlar.get(para, 0) + b["tutar"]
    return toplamlar


def _json_istegi():
    """fetch ile gelen (Accept: application/json) istekler JSON cevap alir."""
    return "application/json" in request.headers.get("Accept", "")


def _mime_belirle(dosya_adi):
    """Dosya uzantisindan MIME tipini bulur; izinli degilse None doner."""
    return IZINLI_TURLER.get(Path(dosya_adi).suffix.lower())


# ---------------------------------------------------------------- kayit / giris

def _giris_sonrasi_adres():
    return kimlik.guvenli_yonlendirme(request.args.get("next")) or url_for("index")


@app.route("/kayit", methods=["GET", "POST"])
@limiter.limit(
    "5 per hour",
    methods=["POST"],
    # Hatali doldurulan formlar sayilmaz; sinir acilan hesap sayisi icindir.
    deduct_when=lambda yanit: yanit.status_code == 302,
)
def kayit():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "GET":
        return render_template("kayit.html", form={})

    kullanici_adi = (request.form.get("kullanici_adi") or "").strip()
    sifre = request.form.get("sifre") or ""
    hata = kimlik.kullanici_adi_hatasi(kullanici_adi) or kimlik.sifre_hatasi(
        sifre, request.form.get("sifre_tekrar") or ""
    )
    if hata is None:
        kullanici_id = database.kullanici_ekle(kullanici_adi, kimlik.sifre_hashle(sifre))
        if kullanici_id is None:
            hata = "Bu kullanıcı adı alınmış, başka bir ad deneyin."
    if hata:
        return render_template("kayit.html", hata=hata, form=request.form), 400

    database.yoneticiyi_belirle(YONETICI_KULLANICI)  # ilk kullanici yonetici olur
    klasor_izleme.kullanici_klasoru_olustur(kullanici_adi)  # TARAMA_KLASORU\<ad> (ayar varsa)
    login_user(kimlik.Kullanici(database.kullanici_getir(kullanici_id)))
    flash(f"Hoş geldiniz, {kullanici_adi}! Hesabınız oluşturuldu.", "basari")
    return redirect(url_for("index"))


@app.route("/giris", methods=["GET", "POST"])
@limiter.limit(SIFRE_DENEME_SINIRI, methods=["POST"])
def giris():
    if current_user.is_authenticated:
        return redirect(_giris_sonrasi_adres())
    if request.method == "GET":
        return render_template("giris.html", form={})

    kullanici = kimlik.dogrula(
        (request.form.get("kullanici_adi") or "").strip(),
        request.form.get("sifre") or "",
    )
    if kullanici is None:
        return (
            render_template("giris.html", hata=kimlik.HATALI_GIRIS_MESAJI, form=request.form),
            401,
        )
    login_user(kullanici, remember=bool(request.form.get("beni_hatirla")))
    return redirect(_giris_sonrasi_adres())


@app.route("/cikis", methods=["POST"])
def cikis():
    logout_user()
    flash("Oturumunuz kapatıldı.", "basari")
    yanit = redirect(url_for("giris"))
    # Belge gorselleri tarayici onbellegindedir (private); cikista silinsin.
    yanit.headers["Clear-Site-Data"] = '"cache"'
    return yanit


# ---------------------------------------------------------------- hesap

@app.route("/hesap")
@login_required
def hesap():
    sayaclar = _sayaclar()
    return render_template(
        "hesap.html",
        belge_sayisi=sayaclar["toplam"],
        bilgisi_eksik=sayaclar["bilgisi_eksik"],
    )


@app.route("/hesap/bilgi-cikar", methods=["POST"])
@login_required
def bilgi_cikar():
    """Bilgisi cikarilmamis mevcut belgeleri kayitli OCR metni uzerinden isler.

    Tarayici her istekte bir belge isletir ve ilerlemeyi gosterir; son_id
    imleci sayesinde basarisiz olan belge atlanir, tekrar tekrar denenmez.
    Tur degistirilmez; elle duzeltilmis alanlarin uzerine yazilmaz.
    """
    json_mu = _json_istegi()
    son_id = request.form.get("son_id", 0, type=int)
    adet = 1 if json_mu else BILGI_CIKARMA_PARTISI
    islenen = hatali = 0
    yogun = False
    for kayit in database.bilgisi_eksik_belgeler(current_user.id, son_id, adet):
        sonuc = classifier.siniflandir(kayit["ocr_metni"], bilinen_tur=kayit["tur"])
        if sonuc["yogun"]:
            yogun = True  # bu belge atlanmaz; tarayici biraz bekleyip yeniden dener
            break
        son_id = kayit["id"]
        if sonuc["alanlar"] is None:
            hatali += 1
        elif database.alanlari_guncelle(current_user.id, kayit["id"], sonuc["alanlar"], elle=False):
            islenen += 1
    kalan = database.bilgisi_eksik_sayisi(current_user.id, son_id)

    if json_mu:
        return {"islenen": islenen, "hatali": hatali, "yogun": yogun, "son_id": son_id, "kalan": kalan}
    if yogun:
        flash("Yapay zeka şu an yoğun, bilgi çıkarmaya biraz sonra devam edin.", "uyari")
    mesaj = f"{islenen} belgeden bilgi çıkarıldı."
    if hatali:
        mesaj += f" {hatali} belgede hata oluştu."
    if kalan:
        mesaj += f" {kalan} belge kaldı, devam etmek için tekrar basın."
    flash(mesaj, "basari" if not hatali else "uyari")
    return redirect(url_for("hesap", _anchor="bilgi-cikar"))


@app.route("/hesap/sifre", methods=["POST"])
@login_required
@limiter.limit(SIFRE_DENEME_SINIRI)
def sifre_degistir():
    yeni = request.form.get("yeni_sifre") or ""
    if not kimlik.sifre_dogru_mu(current_user, request.form.get("mevcut_sifre")):
        flash("Mevcut şifreniz hatalı.", "hata")
    elif hata := kimlik.sifre_hatasi(yeni, request.form.get("yeni_sifre_tekrar") or ""):
        flash(hata, "hata")
    else:
        database.sifre_guncelle(current_user.id, kimlik.sifre_hashle(yeni))
        # Oturum kimligi sifre parmak izini icerdigi icin yeniden giris yaptirilir;
        # diger cihazlardaki oturumlar bu sayede kapanir.
        login_user(kimlik.Kullanici(database.kullanici_getir(current_user.id)))
        flash("Şifreniz değiştirildi. Diğer cihazlardaki oturumlar kapatıldı.", "basari")
    return redirect(url_for("hesap"))


@app.route("/hesap/sil", methods=["POST"])
@login_required
@limiter.limit(SIFRE_DENEME_SINIRI)
def hesap_sil():
    if not kimlik.sifre_dogru_mu(current_user, request.form.get("sifre")):
        flash("Şifre hatalı, hesabınız silinmedi.", "hata")
        return redirect(url_for("hesap"))
    database.kullanici_sil(current_user.id)  # belgeler CASCADE ile silinir
    logout_user()
    flash("Hesabınız ve tüm belgeleriniz kalıcı olarak silindi.", "basari")
    return redirect(url_for("index"))


# ---------------------------------------------------------------- belgeler

@app.route("/")
def index():
    if not current_user.is_authenticated:
        return render_template("giris-sayfasi.html")
    return render_template(
        "index.html",
        son_belgeler=database.belgeleri_listele(current_user.id, SON_BELGE_SAYISI),
    )


class YuklemeHatasi(Exception):
    """Kullaniciya gosterilecek yukleme hatasi; durum JSON cevabin HTTP kodudur."""

    def __init__(self, mesaj, durum=400):
        super().__init__(mesaj)
        self.durum = durum


@app.route("/yukle", methods=["POST"])
@login_required
def yukle():
    """Tek bir belge yukler; OCR, siniflandirma ve bilgi cikarma arka planda yapilir.

    Dosya dogrulanip sifrelenir ve "isleniyor" durumunda kaydedilir; cevap
    hemen doner (isleme.py). Tarayicidaki toplu yukleme dosyalari sirayla, her
    biri icin ayri bir fetch istegiyle (Accept: application/json) gonderir ve
    sonucu /isleme-durumu ile yoklar. JS kapaliyken cevap belge sayfasina
    yonlendirmedir; sayfa islem bitene kadar kendini yeniler.
    """
    json_mu = _json_istegi()
    dosyalar = [d for d in request.files.getlist("belge") if d.filename]
    try:
        if not dosyalar:
            raise YuklemeHatasi("Lütfen bir dosya seçin.")
        belge_id = _belge_kaydet(
            dosyalar[0],
            # Formdaki anahtar kapaliyken gizli alan "0" gonderir; alan hic yoksa varsayilan acik.
            duzelt=request.form.getlist("otomatik_duzelt")[-1:] != ["0"],
        )
    except YuklemeHatasi as hata:
        if json_mu:
            return {"basarili": False, "hata": str(hata), "yogun": False}, hata.durum
        flash(str(hata), "hata")
        return redirect(url_for("index"))

    adres = url_for("belge", belge_id=belge_id)
    if json_mu:
        return {"basarili": True, "belge_id": belge_id, "adres": adres, "durum": BEKLIYOR}
    if len(dosyalar) > 1:
        flash("JavaScript kapalıyken tek seferde bir dosya yüklenebilir; yalnızca ilk dosya yüklendi.", "uyari")
    flash("Belge yüklendi. Metni okunup türü belirleniyor; sayfa hazır olunca kendiliğinden güncellenir.", "basari")
    return redirect(adres)


def _belge_kaydet(dosya, duzelt=True):
    """Dogrulama -> sikistirma + hizli onizleme -> sifreleme -> kayit ("bekliyor")
    -> isciyi uyandir.

    Donus: belge_id. Gecersiz dosyada YuklemeHatasi firlatir. Kose algilama,
    OCR, siniflandirma ve bilgi cikarma isciye kalir; bu istek onlari beklemez.
    """
    if _sayaclar()["toplam"] >= KULLANICI_BELGE_LIMITI:
        raise YuklemeHatasi(
            f"Belge kotanız doldu ({KULLANICI_BELGE_LIMITI} belge). "
            "Yeni belge yüklemek için eski belgelerden bazılarını silin.",
            403,
        )
    mime_type = _mime_belirle(dosya.filename)
    if mime_type is None:
        raise YuklemeHatasi("Sadece JPG, PNG ve PDF dosyaları yüklenebilir.")
    veri = dosya.read()
    if not veri:
        raise YuklemeHatasi("Dosya boş görünüyor.")
    if mime_type == PDF_MIME and len(veri) > MAKS_PDF_BOYUTU:
        raise YuklemeHatasi("PDF çok büyük. PDF dosyaları en fazla 5 MB olabilir.")

    # Depolama sinirli (Neon 0.5 GB): gorsel hemen kucultulup saklanir (isleme.kuyruga_ekle).
    return isleme.kuyruga_ekle(current_user.id, veri, mime_type, secure_filename(dosya.filename) or "belge", duzelt)


def _isleme_ozeti(satir):
    """Bir belgenin isleme durumu, tarayiciya gidecek bicimde."""
    bilgi = satir["isleme_bilgi"] or {}
    durum = satir["isleme_durumu"]
    ozet = {"durum": durum, "adres": url_for("belge", belge_id=satir["id"])}
    if durum == TAMAMLANDI:
        ozet.update(
            tur=satir["tur"],
            tur_ad=TURLER.get(satir["tur"], TURLER[VARSAYILAN_TUR])["ad"],
            uyarilar=bilgi.get("uyarilar") or [],
            # Algilama emin degilse arayuz "Kirpmayi kontrol et" onerir.
            kirpma_kontrol=bool(bilgi.get("kirpma_kontrol")),
        )
    elif durum == HATA:
        ozet["hata"] = bilgi.get("hata") or isleme.ISLEME_HATASI
    else:
        ozet["asama"] = bilgi.get("asama", "goruntu")
    return ozet


@app.route("/isleme-durumu")
@login_required
def isleme_durumu():
    """Tarayicinin yokladigi durum: ?id=1&id=2 -> her belgenin isleme durumu,
    menu sayaclari ve islenmekte olan belge sayisi. Yalnizca kendi belgeleri."""
    kimlikler = [int(d) for d in request.args.getlist("id") if d.isdigit()][:DURUM_SORGU_SINIRI]
    satirlar = database.isleme_durumlari(current_user.id, kimlikler) if kimlikler else []
    sayaclar = _sayaclar()
    yanit = app.json.response(
        belgeler={str(s["id"]): _isleme_ozeti(s) for s in satirlar},
        sayaclar={kod: ozet["adet"] for kod, ozet in sayaclar["turler"].items()},
        isleniyor=sayaclar["isleniyor"],
    )
    yanit.headers["Cache-Control"] = "no-store"
    return yanit


@app.route("/belge/<int:belge_id>/yeniden-isle", methods=["POST"])
@login_required
def yeniden_isle(belge_id):
    """Islenemeyen (hata durumundaki) belgeyi kuyruga geri koyar."""
    if not database.yeniden_isle(current_user.id, belge_id):
        abort(404)
    isleme.uyandir()
    flash("Belge yeniden işleniyor.", "basari")
    return redirect(url_for("belge", belge_id=belge_id))


# ---------------------------------------------------------------- tarayicidan tarama (WIA)

def _wia():
    """tarayici_wia modulu; yalnizca TARAYICI_WIA acikken ice aktarilir."""
    if not TARAYICI_WIA:
        abort(404)
    import tarayici_wia

    return tarayici_wia


@app.route("/tarayici/durum")
@login_required
def tarayici_durumu():
    """Sayfalarin birkac saniyede bir sordugu durum: bagli tarayicilar, suren
    taramanin ilerlemesi ve kullanicinin bitirilmemis cok sayfali taramasi."""
    wia = _wia()
    return jsonify(
        tarayicilar=wia.bagli_tarayicilar(),
        ilerleme=wia.ilerleme(),
        bekleyen_sayfa=wia.bekleyenler.sayi(current_user.id),
    )


@app.route("/tara")
@login_required
def tara():
    wia = _wia()
    return render_template(
        "tara.html",
        tarayicilar=wia.bagli_tarayicilar(),
        bekleyen_sayfa=wia.bekleyenler.sayi(current_user.id),
        cozunurlukler=wia.COZUNURLUKLER,
        varsayilan_dpi=wia.VARSAYILAN_DPI,
    )


def _tarama_cevabi(hata=None, adres=None, sayfa_sayisi=0):
    """fetch istegine JSON; formla gelen istege (JS kapali) yonlendirme."""
    if _json_istegi():
        if hata:
            return jsonify(hata=hata, sayfa_sayisi=sayfa_sayisi), 400
        return jsonify(bitti=adres is not None, adres=adres, sayfa_sayisi=sayfa_sayisi)
    if hata:
        flash(hata, "hata")
    return redirect(adres or url_for("tara"))


# Cok sayfali tarama 5 MB'yi asarsa sirayla daha kucuk/sikistirilmis denenir.
PDF_KUCULTME_ADIMLARI = ((2480, 85), (2000, 70), (1650, 55))


def _taramayi_kaydet(sayfalar, dpi):
    """Taranan sayfalari tek belge olarak (tek sayfa gorsel, cok sayfa PDF)
    kullanicinin arsivine ekler; belge adresini dondurur."""
    wia = _wia()
    from PIL import Image

    for uzun_kenar, kalite in PDF_KUCULTME_ADIMLARI:
        veri, mime_type, uzanti = klasor_izleme.sayfalari_birlestir(
            [Image.open(io.BytesIO(s)) for s in sayfalar], dpi, uzun_kenar=uzun_kenar, kalite=kalite
        )
        if mime_type != PDF_MIME or len(veri) <= MAKS_PDF_BOYUTU:
            break
    else:
        raise wia.TarayiciHatasi(f"{len(sayfalar)} sayfa tek belgeye sığmadı. Belgeyi iki parça halinde tarayın.")
    dosya_adi = f"tarama_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}{uzanti}"
    belge_id = isleme.kuyruga_ekle(current_user.id, veri, mime_type, dosya_adi, kaynak="tarayici")
    flash(f"{len(sayfalar)} sayfa tarandı ve arşivinize eklendi. Metni okunup türü belirleniyor; "
          "sayfa hazır olunca kendiliğinden güncellenir.", "basari")
    return url_for("belge", belge_id=belge_id)


@app.route("/tara", methods=["POST"])
@login_required
def tara_baslat():
    """Tek tusla tarama. Besleyicide (ADF) kagit varsa tum sayfalar alinip
    hemen belge olur; camli yuzeyden taranan sayfa bekletilir ve kullanici
    "Sonraki sayfa" (yeniden bu adres) ya da "Bitir" (/tara/bitir) der.
    Tarayici ve ayarlar gonderilmezse: tek tarayici, 300 dpi, renkli."""
    wia = _wia()
    kimlik = current_user.id
    try:
        if _sayaclar()["toplam"] >= KULLANICI_BELGE_LIMITI:
            raise wia.TarayiciHatasi(
                f"Belge kotanız doldu ({KULLANICI_BELGE_LIMITI} belge). Yeni belge için eski belgelerden bazılarını silin."
            )
        cihaz = request.form.get("cihaz") or ""
        if not cihaz:
            tarayicilar = wia.bagli_tarayicilar()
            if not tarayicilar:
                raise wia.TarayiciHatasi(wia.BULUNAMADI)
            if len(tarayicilar) > 1:
                raise wia.TarayiciHatasi("Birden fazla tarayıcı bağlı; hangisiyle tarayacağınızı seçin.")
            cihaz = tarayicilar[0]["id"]
        if wia.bekleyenler.sayi(kimlik) >= wia.MAKS_SAYFA:
            raise wia.TarayiciHatasi(f"Bir belgede en fazla {wia.MAKS_SAYFA} sayfa olabilir; \"Bitir\"e basın.")
        dpi = request.form.get("dpi", wia.VARSAYILAN_DPI, type=int)
        sayfalar, besleyici = wia.tara(
            cihaz, dpi=dpi, renk=request.form.get("renk") or wia.VARSAYILAN_RENK,
            kaynak=request.form.get("kaynak") or "otomatik",
        )
        if not sayfalar:
            raise wia.TarayiciHatasi("Tarayıcıdan sayfa gelmedi. Kâğıdı yerleştirip yeniden deneyin.")
        toplam = wia.bekleyenler.ekle(kimlik, sayfalar, dpi)
        if not besleyici:
            return _tarama_cevabi(sayfa_sayisi=toplam)  # camli yuzey: sonraki sayfa ya da bitir
        tum_sayfalar, dpi = wia.bekleyenler.al(kimlik)
        return _tarama_cevabi(adres=_taramayi_kaydet(tum_sayfalar, dpi), sayfa_sayisi=len(tum_sayfalar))
    except wia.TarayiciHatasi as h:
        return _tarama_cevabi(hata=str(h), sayfa_sayisi=wia.bekleyenler.sayi(kimlik))


@app.route("/tara/bitir", methods=["POST"])
@login_required
def tara_bitir():
    """Sayfa sayfa taranan belgeyi tamamlar: tum sayfalar tek belge olur."""
    wia = _wia()
    sayfalar, dpi = wia.bekleyenler.al(current_user.id)
    if not sayfalar:
        return _tarama_cevabi(hata="Kaydedilecek taranmış sayfa yok. Önce \"Tara\"ya basın.")
    try:
        return _tarama_cevabi(adres=_taramayi_kaydet(sayfalar, dpi), sayfa_sayisi=len(sayfalar))
    except wia.TarayiciHatasi as h:
        return _tarama_cevabi(hata=str(h))


@app.route("/tara/iptal", methods=["POST"])
@login_required
def tara_iptal():
    """Bitirilmemis taramanin sayfalarini atar."""
    _wia().bekleyenler.al(current_user.id)
    if _json_istegi():
        return jsonify(bitti=False, adres=None, sayfa_sayisi=0)
    flash("Tarama iptal edildi; taranan sayfalar kaydedilmedi.", "uyari")
    return redirect(url_for("tara"))


@app.route("/tarama-durumu")
@login_required
def tarama_durumu():
    """Yonetici icin bilgi sayfasi: bagli tarayicilar, izlenen klasorler, son
    aktarilan dosyalar ve son hatalar. Ayar degistirmez."""
    if not current_user.yonetici:
        abort(404)
    return render_template(
        "tarama_durumu.html",
        tarayicilar=_wia().bagli_tarayicilar() if TARAYICI_WIA else None,
        klasorler=klasor_izleme.izlenen_klasorler(),
        aktarilanlar=tarama_gunlugu.son_aktarilanlar(),
        hatalar=tarama_gunlugu.son_hatalar(),
    )


# ---------------------------------------------------------------- tarama klasorleri (bulma, secme, kaldirma)

def _yerel_istek_mi():
    """Istek ArcBase'in calistigi bilgisayarin kendisinden mi (127.0.0.1 / ::1)?
    Vekil sunucu arkasinda (Render) hicbir istek yerel sayilmaz."""
    if URETIM and not YEREL_MOD:
        return False
    return request.remote_addr in ("127.0.0.1", "::1")


def _klasor_yonetimi_izinli():
    """Klasor arama/gezinme ve izlenen klasorleri degistirme: yalnizca yonetici
    ya da sunucu bilgisayarinin kendisi. Agdaki diger bilgisayarlar gormez."""
    return current_user.is_authenticated and (current_user.yonetici or _yerel_istek_mi())


def _klasor_yetkisi():
    if not _klasor_yonetimi_izinli():
        abort(404)
    import klasor_secimi

    return klasor_secimi


@app.route("/klasorler")
@login_required
def klasorler():
    klasor_secimi = _klasor_yetkisi()
    return render_template(
        "klasorler.html", klasorler=klasor_izleme.izlenen_klasorler(),
        arama_dakikasi=klasor_secimi.SON_DOSYA_SN // 60, hemen_bul=request.args.get("bul") == "1",
    )


@app.route("/klasorler/son-dosyalar")
@login_required
def klasor_son_dosyalar():
    """Kullanici klasorlerinde son 2 dakikada olusan gorsel/PDF dosyalari."""
    klasor_secimi = _klasor_yetkisi()
    dosyalar = []
    for dosya in klasor_secimi.son_dosyalari_bul():
        anahtar = klasor_secimi.anahtarlar.ver(current_user.id, dosya["yol"])
        dosyalar.append({"anahtar": anahtar, "ad": dosya["ad"], "klasor": dosya["klasor"],
                         "onizleme": url_for("klasor_onizleme", anahtar=anahtar)})
    return jsonify(dosyalar=dosyalar)


@app.route("/klasorler/onizleme/<anahtar>")
@login_required
def klasor_onizleme(anahtar):
    """Yalnizca aramada bu kullaniciya bulunan dosyanin onizlemesi."""
    klasor_secimi = _klasor_yetkisi()
    yol = klasor_secimi.anahtarlar.yol(current_user.id, anahtar)
    if yol is None:
        abort(404)
    try:
        veri = klasor_secimi.onizleme_uret(yol)
    except klasor_secimi.KlasorHatasi:
        abort(404)
    yanit = Response(veri, mimetype="image/jpeg")
    yanit.headers["Cache-Control"] = "private, no-store"
    return yanit


@app.route("/klasorler/gez")
@login_required
def klasor_gez():
    """Klasor secme penceresi: suruculer/kisayollar ya da bir klasorun alt klasorleri."""
    klasor_secimi = _klasor_yetkisi()
    try:
        return jsonify(klasor_secimi.klasoru_listele(request.args.get("yol")))
    except klasor_secimi.KlasorHatasi as hata:
        return jsonify(hata=str(hata)), 400


def _klasor_cevabi(hata=None, **veri):
    if _json_istegi():
        return (jsonify(hata=hata), 400) if hata else jsonify(**veri)
    if hata:
        flash(hata, "hata")
    return redirect(url_for("klasorler"))


@app.route("/klasorler/ekle", methods=["POST"])
@login_required
def klasor_ekle():
    """Klasoru izlenen klasorlere ekler. Klasor ya aramada bulunan dosyanin
    anahtariyla ("Bu belge") ya da gezinme penceresinden yoluyla gelir.
    Klasorde dosya varsa once sorulur: hepsi mi, yalnizca bundan sonrakiler mi?"""
    klasor_secimi = _klasor_yetkisi()
    try:
        anahtar = request.form.get("anahtar")
        if anahtar:
            dosya = klasor_secimi.anahtarlar.yol(current_user.id, anahtar)
            if dosya is None:
                raise klasor_secimi.KlasorHatasi("Süre doldu. Belgeyi yeniden arayın.")
            yol = str(dosya.parent)
        else:
            yol = request.form.get("yol", "")
        klasor = klasor_secimi.klasoru_dogrula(yol)
    except klasor_secimi.KlasorHatasi as hata:
        return _klasor_cevabi(hata=str(hata))
    ayar = klasor_izleme.klasor_ayari()
    if ayar and izlenen_klasorler.normal(ayar) == izlenen_klasorler.normal(klasor):
        return _klasor_cevabi(hata="Bu klasör zaten izleniyor.")

    mevcutlar = request.form.get("mevcutlar")  # "hepsi" | "sonrakiler" | yok: sor
    sayi = klasor_izleme.mevcut_dosya_sayisi(klasor)
    if mevcutlar not in ("hepsi", "sonrakiler"):
        if sayi and _json_istegi():
            return jsonify(soru=True, sayi=sayi, yol=str(klasor))
        mevcutlar = "sonrakiler"
    izlenen_klasorler.ekle(klasor, current_user.kullanici_adi, yalnizca_yeniler=mevcutlar != "hepsi")
    klasor_izleme.varsayilan_baslat(KULLANICI_BELGE_LIMITI)
    mesaj = f"“{klasor.name or klasor}” klasörü izleniyor. Bundan sonra buraya kaydedilen belgeler arşive gelir."
    if mevcutlar == "hepsi" and sayi:
        mesaj += f" İçindeki {sayi} belge de ekleniyor."
    flash(mesaj, "basari")
    return _klasor_cevabi(eklendi=True, adres=url_for("klasorler"))


@app.route("/klasorler/kaldir", methods=["POST"])
@login_required
def klasor_kaldir():
    """Klasoru izlemeyi birakir; icindeki dosyalara dokunulmaz."""
    _klasor_yetkisi()
    yol = request.form.get("yol", "")
    kayit = next((k for k in klasor_izleme.izlenen_klasorler()
                  if k["kaldirilabilir"] and izlenen_klasorler.normal(k["yol"]) == izlenen_klasorler.normal(yol)),
                 None) if yol else None
    if kayit is None:
        return _klasor_cevabi(hata="Bu klasör izlenen klasörler arasında yok.")
    izlenen_klasorler.kaldir(kayit["yol"], kayit["tur"] == klasor_izleme.VARSAYILAN_TUR, current_user.kullanici_adi)
    flash("Klasör artık izlenmiyor. İçindeki dosyalara dokunulmadı.", "basari")
    return _klasor_cevabi(kaldirildi=True, adres=url_for("klasorler"))


# ---------------------------------------------------------------- gelen belgeler (yonetici)

@app.route("/gelen")
@login_required
def gelen():
    """Sahipsiz gelen belgeler (tarama klasorunun kokune dusenler). Yalnizca
    yoneticinin kendi kutusu listelenir; baska kullanicilarin arsivleri degil."""
    if not _gelen_kutusu_var():
        abort(404)
    return render_template(
        "gelen.html",
        belgeler=database.belgeleri_suz(current_user.id, gelen=True),
        kullanicilar=database.kullanicilari_listele(),
    )


@app.route("/gelen/<int:belge_id>/ata", methods=["POST"])
@login_required
def gelen_ata(belge_id):
    """Gelen belgeyi bir kullanicinin (ya da yoneticinin kendi) arsivine atar.
    Atama belgenin atama_gecmisi'ne ve uygulama gunlugune yazilir."""
    hedef_id = request.form.get("kullanici", type=int)
    hedef = database.kullanici_getir(hedef_id) if hedef_id else None
    if hedef is None:
        flash("Atanacak kullanıcıyı seçin.", "hata")
        return redirect(url_for("gelen"))
    sonuc = database.gelen_ata(
        current_user.id, current_user.kullanici_adi, belge_id, hedef["id"], hedef["kullanici_adi"],
        KULLANICI_BELGE_LIMITI,
    )
    if sonuc == "yok":
        abort(404)
    if sonuc == "kota":
        flash(f"{hedef['kullanici_adi']} kullanıcısının belge kotası dolu ({KULLANICI_BELGE_LIMITI} belge); "
              "belge atanmadı.", "hata")
        return redirect(url_for("gelen"))
    app.logger.info("Gelen belge atandi: belge=%s yapan=%s kime=%s", belge_id, current_user.kullanici_adi,
                    hedef["kullanici_adi"])
    if hedef["id"] == current_user.id:
        flash("Belge arşivinize alındı.", "basari")
    else:
        flash(f"Belge {hedef['kullanici_adi']} kullanıcısına atandı.", "basari")
    return redirect(url_for("gelen"))


@app.route("/kategori/<tur>")
@login_required
def kategori(tur):
    if tur not in TURLER:
        abort(404)
    suz, suzgec_url = _suzgecler(tur)
    belgeler = database.belgeleri_suz(current_user.id, tur=tur, **suz)
    return render_template(
        "kategori.html",
        tur=tur,
        belgeler=belgeler,
        suzgec=suzgec_url,
        tutar_toplamlari=_tutar_toplamlari(belgeler) if tur == "fatura" else None,
    )


@app.route("/disa-aktar")
@login_required
def disa_aktar():
    """Kategori, arama ve paneldeki listeyi (ayni suzgeclerle) .xlsx indirir.

    Sadece giris yapan kullanicinin belgeleri; OCR metni ve gorseller aktarilmaz.
    """
    tur = request.args.get("tur") if request.args.get("tur") in TURLER else None
    sorgu = (request.args.get("q") or "").strip() or None
    suz, _ = _suzgecler(tur)
    belgeler = database.belgeleri_suz(current_user.id, tur=tur, sorgu=sorgu, **suz)
    veri = excel.olustur(
        belgeler, TURLER, _tutar_toplamlari(belgeler) if tur == "fatura" else None
    )
    bugun = (datetime.now(timezone.utc) + excel.TSI_FARKI).date().isoformat()
    return send_file(
        io.BytesIO(veri),
        mimetype=excel.MIME,
        as_attachment=True,
        download_name=f"arsiv_{tur or 'tumu'}_{bugun}.xlsx",
    )


@app.route("/belge/<int:belge_id>")
@login_required
def belge(belge_id):
    kayit = database.belge_getir(current_user.id, belge_id)
    if kayit is None:
        abort(404)
    bilgi = kayit["isleme_bilgi"] or {}
    return render_template(
        "belge.html",
        belge=kayit,
        bilgiler=alanlar.degerler(kayit),
        gorunum_modlari=GORUNUM_MODLARI,
        gorunum_modu=_gorunum_modu(),
        pdf_modlari={kod: GORUNUM_MODLARI[kod] for kod in tarama.MODLAR},
        kose_ayarlanabilir=_kose_ayarlanabilir(kayit),
        yeniden_analiz_oner=session.pop("yeniden_analiz_oner", None) == belge_id,
        isleniyor=kayit["isleme_durumu"] in (BEKLIYOR, ISLENIYOR),
        isleme_asamasi=bilgi.get("asama", "goruntu"),
        isleme_hatasi=(bilgi.get("hata") or isleme.ISLEME_HATASI) if kayit["isleme_durumu"] == HATA else None,
        # Yuklemedeki OCR/Groq uyarilari, kullanici turu elle duzeltene ya da
        # belge yeniden analiz edilene kadar gosterilir.
        isleme_uyarilari=[] if kayit["elle_duzeltildi"] else bilgi.get("uyarilar") or [],
        kirpma_kontrol=bool(bilgi.get("kirpma_kontrol")),
        # Tarayici ciktisi algilandi, kirpilmadi (koseler elle kaydedilince kalkar).
        taranmis=bool(bilgi.get("taranmis")),
        atama_kullanicilari=database.kullanicilari_listele() if kayit["gelen_kutusu"] else None,
    )


@app.route("/ara")
@login_required
def ara():
    sorgu = (request.args.get("q") or "").strip()
    suz, suzgec_url = _suzgecler()
    sonuclar = (
        database.belgeleri_suz(current_user.id, sorgu=sorgu, limit=ARAMA_SINIRI, **suz)
        if sorgu
        else []
    )
    return render_template(
        "arama.html", sorgu=sorgu, belgeler=sonuclar, suzgec=suzgec_url, arama_siniri=ARAMA_SINIRI
    )


@app.route("/belge/<int:belge_id>/tur", methods=["POST"])
@login_required
def turu_degistir(belge_id):
    yeni_tur = request.form.get("tur", "")
    if yeni_tur not in TURLER:
        flash("Geçersiz belge türü.", "hata")
        return redirect(url_for("belge", belge_id=belge_id))
    if not database.turu_guncelle(current_user.id, belge_id, yeni_tur):
        abort(404)
    flash(f"Belge türü '{TURLER[yeni_tur]['ad']}' olarak güncellendi.", "basari")
    return redirect(url_for("belge", belge_id=belge_id))


@app.route("/belge/<int:belge_id>/alanlar", methods=["POST"])
@login_required
def alanlari_duzenle(belge_id):
    kayit = database.belge_getir(current_user.id, belge_id)
    if kayit is None:
        abort(404)
    temiz, hatalar = alanlar.dogrula(kayit["tur"], request.form)
    if hatalar:
        mesaj = "Şu alanlar geçersiz olduğu için kaydedilmedi: " + ", ".join(hatalar) + "."
        if kayit["tur"] == "kimlik":
            mesaj += " Kimlik numarası veya seri numarası gibi bilgiler saklanmaz."
        flash(mesaj, "hata")
    else:
        database.alanlari_guncelle(current_user.id, belge_id, temiz)
        flash("Belge bilgileri güncellendi.", "basari")
    return redirect(url_for("belge", belge_id=belge_id, _anchor="bilgiler"))


@app.route("/belge/<int:belge_id>/sil", methods=["POST"])
@login_required
def sil(belge_id):
    if not database.belge_sil(current_user.id, belge_id):
        abort(404)
    flash("Belge silindi.", "basari")
    return redirect(url_for("index"))


def _cozulmus_icerik(belge_id, onizleme=False):
    """Kullanicinin sifreli icerigini okuyup cozer; yoksa ya da baskasinin
    belgesiyse 404 verir."""
    kayit = database.belge_icerigi(current_user.id, belge_id, onizleme=onizleme)
    if kayit is None or kayit["veri"] is None:
        abort(404)
    return kayit, crypto.coz(kayit["veri"])


def _duzeltilmis_goruntu(kayit, veri):
    """Saklanan gorselden gosterilecek BGR goruntu.

    v5 gorsellerinde (orijinal_saklandi) koseler aninda uygulanir. v4'te
    duzeltilip oyle saklanmis ya da hic duzeltilmemis eski gorseller aynen
    doner."""
    bgr = goruntu_duzelt.goruntu_ac(veri)
    if kayit["orijinal_saklandi"] and kayit["koseler"]:
        return goruntu_duzelt.uygula(bgr, kayit["koseler"])
    return bgr


_gorsel_onbellegi = onbellek.BaytOnbellegi(GORSEL_ONBELLEGI_MB * 1024 * 1024)


def gorsel_onbellegini_temizle():
    """Olcum ve testler icin (docs/hiz_olcumu.py)."""
    _gorsel_onbellegi.temizle()


def _istemci_surumu(belge_id, tur, mod):
    """Tarayicinin If-None-Match ile gonderdigi ETag'deki icerik surumu."""
    for deger in request.if_none_match.as_set():
        parca = deger.split("-")
        if len(parca) == 4 and parca[0] == str(belge_id) and parca[2:] == [tur, mod] and parca[1].isdigit():
            return int(parca[1])
    return None


def _gorsel_yaniti(belge_id, tur, mod, uret, onizleme=False):
    """Islenmis gorseli surec onbellegi ve tarayici onbellegiyle sunar.

    Sahiplik her istekte veritabaninda kontrol edilir (tek sorgu). Tarayicinin
    ya da surec onbelleginin elindeki surum guncelse sifreli icerik hic
    tasinmaz ve cozulmez: tarayiciya 304, yoksa onbellekteki goruntu doner.
    Kose ya da icerik degisince surum (belgeler.icerik_surumu) artar, mod da
    anahtarin parcasidir; boylece eski goruntu verilmez. Adreste guncel surum
    (?v=) varsa tarayici gorseli yeniden sormadan kullanir.
    uret(kayit, cozulmus_veri) -> (bayt, mime)"""
    anahtar = (belge_id, tur, mod)
    istemci = _istemci_surumu(belge_id, tur, mod)
    onbellekte = _gorsel_onbellegi.al(anahtar)
    bilinen = [s for s in (istemci, onbellekte[0] if onbellekte else None) if s is not None]
    kayit = database.belge_icerigi(current_user.id, belge_id, onizleme=onizleme, bilinen_surumler=bilinen)
    if kayit is None or not kayit["veri_var"]:
        abort(404)
    surum = kayit["icerik_surumu"]
    if istemci == surum:
        yanit = Response(status=304)
    else:
        if onbellekte is not None and onbellekte[0] == surum:
            _, govde, mime_type = onbellekte
        else:
            veri = crypto.coz(kayit["veri"])
            try:
                govde, mime_type = uret(kayit, veri)
            except Exception:
                abort(404)
            _gorsel_onbellegi.koy(anahtar, surum, govde, mime_type)
        yanit = Response(govde, mimetype=mime_type)
    yanit.set_etag(f"{belge_id}-{surum}-{tur}-{mod}")
    kalici = request.args.get("v") == str(surum)
    yanit.headers["Cache-Control"] = "private, max-age=31536000, immutable" if kalici else "private, no-cache"
    return yanit


def _gorsel_uret(kayit, veri, ham=False):
    """/gorsel: kirpilmis gorsel (koseler varsa); ham=True ya da PDF'te saklanan hal."""
    if not ham and kayit["mime_type"] != PDF_MIME and kayit["orijinal_saklandi"] and kayit["koseler"]:
        return goruntu_duzelt.jpeg(_duzeltilmis_goruntu(kayit, veri), GOSTERIM_KALITESI), "image/jpeg"
    return ocr.goruntu_baytlari(veri, kayit["mime_type"])


@app.route("/gorsel/<int:belge_id>")
@login_required
def gorsel(belge_id):
    ham = request.args.get("ham") == "1"  # kose editoru: duzeltilmemis saklanan gorsel
    return _gorsel_yaniti(
        belge_id, "ham" if ham else "gorsel", "x", lambda kayit, veri: _gorsel_uret(kayit, veri, ham)
    )


# Detay sayfasindaki mod secici: tarama.MODLAR + filtresiz (kirpilmis) fotograf.
GORUNUM_MODLARI = {
    "renkli": "Renkli tarama",
    "gri": "Gri",
    "sb": "Siyah-beyaz",
    "orijinal": "Orijinal fotoğraf",
}


def _gorunum_modu(varsayilan=tarama.VARSAYILAN_MOD):
    mod = request.args.get("mod")
    return mod if mod in GORUNUM_MODLARI else varsayilan


@app.route("/tarama/<int:belge_id>")
@login_required
def tarama_onizleme(belge_id):
    """Secilen tarama modunda JPEG onizleme (OCR yok). PDF'lere filtre
    uygulanmaz; ilk sayfa aynen doner."""
    mod = _gorunum_modu()

    def uret(kayit, veri):
        if kayit["mime_type"] == PDF_MIME:
            return _gorsel_uret(kayit, veri)
        bgr = _duzeltilmis_goruntu(kayit, veri)
        # "orijinal" da ayni kenar kirpmasini alir; karsilastirma gorunumunde
        # iki goruntu birebir ust uste oturur.
        bgr = tarama.kenar_kirp(bgr) if mod == "orijinal" else tarama.tara(bgr, mod)
        return goruntu_duzelt.jpeg(bgr, GOSTERIM_KALITESI), "image/jpeg"

    return _gorsel_yaniti(belge_id, "tarama", mod, uret)


def _kose_ayarlanabilir(kayit):
    """Koseler yalnizca saklanan gorsel duzeltilmemis orijinalse degistirilebilir:
    v5 gorselleri ve hic duzeltilmemis eski gorseller. v4'te duzeltilip oyle
    saklanmis belgelerin orijinali yoktur. Islenmekte olan belgede kose
    algilamayi isci yapar."""
    return (
        kayit["mime_type"] != PDF_MIME
        and (kayit["orijinal_saklandi"] or not kayit["otomatik_duzeltildi"])
        and kayit["isleme_durumu"] == TAMAMLANDI
    )


@app.route("/belge/<int:belge_id>/koseler/otomatik")
@login_required
def koseleri_algila(belge_id):
    """Kose editorundeki "Otomatik algila": saklanan orijinalde yeniden algilama."""
    kayit, veri = _cozulmus_icerik(belge_id)
    if not _kose_ayarlanabilir(kayit):
        abort(404)
    sonuc = goruntu_duzelt.analiz(goruntu_duzelt.goruntu_ac(veri))
    koseler = sonuc["koseler"]
    return {
        "koseler": None if koseler is None else [[round(float(x), 1), round(float(y), 1)] for x, y in koseler],
        "belge": sonuc["belge"],
        "taranmis": sonuc["taranmis"],
        "puan": round(sonuc["puan"], 2),
    }


@app.route("/belge/<int:belge_id>/koseler", methods=["POST"])
@login_required
def koseleri_kaydet(belge_id):
    """Elle ayarlanan koseleri kaydeder; onizlemeyi yeniden uretir ve OCR'i
    duzeltilmis goruntu uzerinde yeniden yapar. koseler bos: duzeltme kaldirilir."""
    kayit, veri = _cozulmus_icerik(belge_id)
    if not _kose_ayarlanabilir(kayit):
        abort(404)
    ham = (request.form.get("koseler") or "").strip()
    try:
        koseler = json.loads(ham) if ham and ham != "null" else None
    except ValueError:
        koseler = False
    bgr = goruntu_duzelt.goruntu_ac(veri)
    if koseler is not None and not goruntu_duzelt.koseler_gecerli(koseler, (bgr.shape[1], bgr.shape[0])):
        mesaj = "Köşeler geçersiz: dört köşe görselin üzerinde ve kesişmeyen bir dörtgen oluşturmalı."
        if _json_istegi():
            return {"basarili": False, "hata": mesaj}, 400
        flash(mesaj, "hata")
        return redirect(url_for("belge", belge_id=belge_id))

    duz, gri = isleme.ocr_girdisi(bgr, koseler)
    try:
        ocr_metni = ocr.metin_cikar(gri, "image/jpeg")
    except Exception:
        ocr_metni = database.belge_getir(current_user.id, belge_id)["ocr_metni"] or ""
    onizleme = ocr.onizleme_bgr(duz)
    database.koseleri_guncelle(
        current_user.id,
        belge_id,
        koseler,
        crypto.sifrele(onizleme) if onizleme else None,
        ocr_metni,
    )
    # Sayfa yeniden yuklendiginde "Yapay zeka ile yeniden analiz et" onerilir.
    session["yeniden_analiz_oner"] = belge_id
    mesaj = f"Kırpma kaydedildi, metin yeniden okundu ({len(ocr_metni)} karakter)."
    if _json_istegi():
        return {"basarili": True, "mesaj": mesaj, "ocr_karakter": len(ocr_metni)}
    flash(mesaj, "basari")
    return redirect(url_for("belge", belge_id=belge_id))


@app.route("/belge/<int:belge_id>/yeniden-analiz", methods=["POST"])
@login_required
def yeniden_analiz(belge_id):
    """Kayitli OCR metnini yeniden siniflandirir ve bilgileri cikarir. Elle
    duzeltilmis tur ve bilgi alanlarinin uzerine yazilmaz."""
    kayit = database.belge_getir(current_user.id, belge_id)
    if kayit is None:
        abort(404)
    session.pop("yeniden_analiz_oner", None)
    if kayit["isleme_durumu"] != TAMAMLANDI:
        flash("Belge henüz işleniyor; türü ve bilgileri birazdan kendiliğinden belirlenecek.", "uyari")
        return redirect(url_for("belge", belge_id=belge_id))
    if not (kayit["ocr_metni"] or "").strip():
        flash("Belgede okunmuş metin yok; yeniden analiz yapılamadı.", "uyari")
        return redirect(url_for("belge", belge_id=belge_id))

    sonuc = classifier.siniflandir(
        kayit["ocr_metni"], bilinen_tur=kayit["tur"] if kayit["elle_duzeltildi"] else None
    )
    if sonuc.get("hata_turu") == "baglanti":
        flash("Servise şu an ulaşılamadı; birkaç dakika sonra yeniden deneyin.", "uyari")
        return redirect(url_for("belge", belge_id=belge_id))
    if sonuc.get("yogun"):
        flash(classifier.YOGUN_MESAJI, "uyari")
        return redirect(url_for("belge", belge_id=belge_id))
    if sonuc.get("alanlar") is None:
        flash("Yeniden analiz yapılamadı: sınıflandırma servisi yapılandırmasında bir sorun var. "
              "Türü elle seçebilirsiniz.", "hata")
        return redirect(url_for("belge", belge_id=belge_id))

    database.analizi_guncelle(current_user.id, belge_id, sonuc["tur"], sonuc["guven"], sonuc["aciklama"])
    # Tur degistiyse alanlar yeni ture gore; elle duzeltilmis alanlar korunur.
    guncel_tur = kayit["tur"] if kayit["elle_duzeltildi"] else sonuc["tur"]
    bilgiler = sonuc["alanlar"] if guncel_tur == sonuc["tur"] else alanlar.dogrula(guncel_tur, {})[0]
    database.alanlari_guncelle(current_user.id, belge_id, bilgiler, elle=False)
    notlar = []
    if kayit["elle_duzeltildi"]:
        notlar.append("elle seçilen tür korundu")
    if kayit["alanlar_elle_duzeltildi"]:
        notlar.append("elle düzeltilen bilgiler korundu")
    flash("Belge yeniden analiz edildi" + (f" ({', '.join(notlar)})" if notlar else "") + ".", "basari")
    return redirect(url_for("belge", belge_id=belge_id))


def _tarih_etiketi(kayit):
    """Belge tarihi (yoksa yukleme tarihi) YYYY-MM-DD."""
    return (kayit["belge_tarihi"] or kayit["yuklenme_tarihi"].date()).isoformat()


def _pdf_modu():
    mod = request.args.get("mod")
    return mod if mod in tarama.MODLAR else tarama.VARSAYILAN_MOD


@app.route("/belge/<int:belge_id>/pdf")
@login_required
def pdf_indir(belge_id):
    """Aranabilir A4 PDF: duzeltilmis goruntu -> tarama filtresi -> metin
    katmani. Saklanmaz, her istekte uretilir. PDF olarak yuklenmis belgenin
    orijinali verilir (filtre uygulanmaz)."""
    kayit = database.belge_getir(current_user.id, belge_id)
    if kayit is None:
        abort(404)
    icerik, veri = _cozulmus_icerik(belge_id)
    tarih = _tarih_etiketi(kayit)
    dosya_adi = f"{kayit['tur']}_{tarih}.pdf"
    if icerik["mime_type"] != PDF_MIME:
        mod = _pdf_modu()
        belge_pdf = pdf_uret.yeni_belge()
        pdf_uret.goruntu_sayfasi_ekle(belge_pdf, tarama.tara(_duzeltilmis_goruntu(icerik, veri), mod), mod)
        baslik = f"{TURLER[kayit['tur']]['ad']} {alanlar.tarih_yaz(tarih)}"
        veri = pdf_uret.bitir(belge_pdf, baslik)
    return send_file(io.BytesIO(veri), mimetype=PDF_MIME, as_attachment=True, download_name=dosya_adi)


@app.route("/belge/<int:belge_id>/word")
@login_required
def word_indir(belge_id):
    """Baslik, bilgi alanlari tablosu ve OCR metniyle .docx (her istekte uretilir)."""
    kayit = database.belge_getir(current_user.id, belge_id)
    if kayit is None:
        abort(404)
    tarih = _tarih_etiketi(kayit)
    veri = word_uret.olustur(
        kayit, TURLER[kayit["tur"]]["ad"], f"{kayit['dosya_adi']} · {alanlar.tarih_yaz(tarih)}"
    )
    return send_file(
        io.BytesIO(veri), mimetype=word_uret.MIME, as_attachment=True, download_name=f"{kayit['tur']}_{tarih}.docx"
    )


@app.route("/pdf-birlestir", methods=["POST"])
@login_required
def pdf_birlestir():
    """Secilen belgeleri (secim sirasiyla) tek aranabilir PDF'te birlestirir.

    Gorseller tarama filtresiyle A4 sayfaya, PDF belgelerin sayfalari oldugu
    gibi eklenir; her belge icin yer imi olusturulur. Baska kullanicinin
    belgesi listede varsa 404 (varligi belli edilmez)."""
    kimlikler = []
    for deger in request.form.getlist("belge"):
        if deger.isdigit() and int(deger) not in kimlikler:
            kimlikler.append(int(deger))
    hata = None
    if not kimlikler:
        hata = "Birleştirmek için en az bir belge seçin."
    elif len(kimlikler) > PDF_BIRLESTIRME_SINIRI:
        hata = f"Tek seferde en fazla {PDF_BIRLESTIRME_SINIRI} belge birleştirilebilir; {len(kimlikler)} belge seçtiniz."
    if hata:
        if _json_istegi():
            return {"basarili": False, "hata": hata}, 400
        flash(hata, "hata")
        return redirect(_geri_adres())

    kayitlar = [database.belge_getir(current_user.id, i) for i in kimlikler]
    if any(k is None for k in kayitlar):
        abort(404)
    mod = request.form.get("mod") if request.form.get("mod") in tarama.MODLAR else tarama.VARSAYILAN_MOD

    belge_pdf = pdf_uret.yeni_belge()
    yer_imleri = []
    for kayit in kayitlar:
        icerik, veri = _cozulmus_icerik(kayit["id"])
        if icerik["mime_type"] == PDF_MIME:
            ilk_sayfa = pdf_uret.pdf_sayfalari_ekle(belge_pdf, veri)
        else:
            goruntu = tarama.tara(_duzeltilmis_goruntu(icerik, veri), mod)
            ilk_sayfa = pdf_uret.goruntu_sayfasi_ekle(belge_pdf, goruntu, mod)
        etiket = f"{TURLER[kayit['tur']]['ad']} · {alanlar.tarih_yaz(_tarih_etiketi(kayit))} · {kayit['dosya_adi']}"
        yer_imleri.append((etiket, ilk_sayfa))

    bugun = (datetime.now(timezone.utc) + excel.TSI_FARKI).date().isoformat()
    veri = pdf_uret.bitir(belge_pdf, f"ArcBase — {len(kayitlar)} belge", yer_imleri)
    return send_file(
        io.BytesIO(veri), mimetype=PDF_MIME, as_attachment=True, download_name=f"arsiv_birlesik_{bugun}.pdf"
    )


@app.route("/onizleme/<int:belge_id>")
@login_required
def onizleme(belge_id):
    """Grid kartlarindaki kucuk resim; kartlar adrese surumu (?v=) ekler."""
    return _gorsel_yaniti(belge_id, "onizleme", "x", lambda _, veri: (veri, "image/jpeg"), onizleme=True)


@app.route("/belge/<int:belge_id>/indir")
@login_required
def indir(belge_id):
    kayit, veri = _cozulmus_icerik(belge_id)
    return send_file(
        io.BytesIO(veri),
        mimetype=kayit["mime_type"],
        as_attachment=True,
        download_name=kayit["dosya_adi"],
    )


if __name__ == "__main__":
    # Sadece gelistirme icin; yayinda gunicorn (Dockerfile), Windows'ta
    # waitress (sunucu.py, baslat.bat) kullanilir.
      app.run(debug=True, port=5001)
