"""Telefon fotograflarinda belgeyi algilama, perspektif ve egiklik duzeltme (OpenCV).

Tum geometrik duzeltme dort koseyle ifade edilir: kaynak goruntudeki
(sol ust, sag ust, sag alt, sol alt) noktalar dik bir dikdortgene esitlenir.
Kose listesi veritabaninda saklanir (belgeler.koseler); duzeltilmis goruntu
gosterim ve indirmede uygula() ile aninda uretilir, boylece kullanici koseleri
sonradan elle degistirebilir.

Algilama iki aday kaynagi kullanir: kenar cizgileri (Hough; kagidin dort
kenar cizgisinin kesisimleri, kadraj disina tasan koseler dahil) ve
parlaklik/renk maskelerinin konturlari. Tum adaylar ayni olcutle puanlanir:
dortgenin her kenari boyunca ic taraf kagit renginde, dis taraf ondan
belirgin sekilde farkli mi? Kagitla ayni renkteki beyaz duvar ya da parlak
masa yansimasi bu olcute takilir; goruntu kenarina dayanan (gorunmeyen)
kenarlar destek almaz. Zayif bir kenar varsa puan "emin" esiginin altinda
kalir ve arayuz "Kirpmayi kontrol et" onerir. Ardindan yazi satirlari tam
yatay olacak sekilde ince egiklik duzeltmesi koselere katlanir. Belge
bulunamazsa yalnizca egiklik (±15 derece) duzeltilir; o da olculemezse
goruntuye dokunulmaz.

Taranmis belgeler (tarayici ciktisi) once ayirt edilir: kenar seritleri duz
ve acik renkli, arka plan (masa, golge) yok ve perspektif bozulmasi yoksa
kirpma ve perspektif duzeltmesi hic yapilmaz, yalnizca ±3 derece egiklik
duzeltilir. Belgenin icindeki bir cerceve ya da tablo kagit kenari sanilmasin
diye disi da kagit renginde olan aday dortgenler reddedilir.

Duzeltilmis goruntunun orani perspektiften tahmin edilen gercek kagit
oranidir; A4'e yakinsa tam A4 (kaynak yetiyorsa 300 DPI) uretilir.
"""

import io

import cv2
import numpy as np
from PIL import Image, ImageOps

ANALIZ_UZUN_KENAR = 1000  # kenar algilama kucultulmus kopyada yapilir (hiz)
MIN_BELGE_ORANI = 0.25  # belge dortgeni goruntunun en az bu kadarini kaplamali
MAKS_BELGE_ORANI = 0.98  # bundan buyuk dortgen goruntunun kendi cercevesidir
KOSE_ICERI_CEKME = 0.99  # kirpma koseleri merkeze dogru %1 iceri alinir (masa seridi kalmasin)
MIN_PUAN = 0.5  # bu puanin altindaki dortgen belge sayilmaz
EMIN_PUANI = 0.8  # bunun altinda "Kirpmayi kontrol et" onerilir
MIN_KARSITLIK = 6.0  # kagit ile masa arasindaki en kucuk Lab renk farki (duz renk goruntu belge degildir)
MIN_KENAR_PX = 100  # daha kucuk goruntulerde algilama yapilmaz
KONTRAST_ESIGI = 12.0  # kenarin iki yani arasinda "gercek kenar" sayilan en kucuk Lab farki
KAGIT_TOLERANSI = 35.0  # kenarin ic yani kagit rengine en fazla bu kadar uzak olabilir
KENAR_OFSETI = 0.006  # kenarin iki yanindan ornek alinan uzaklik (uzun kenara oranla)
KENAR_KAYMASI = 0.008  # gercek kenarin cizgiden en fazla bu kadar uzakta olabilecegi (kavisli kagit)
MIN_GORUNURLUK = 0.5  # kenarin bundan azi kadrajda gorunuyorsa destegi orantili duser
ZAYIF_KENAR = 0.35  # bu destegin altindaki kenar "zayif": bir tane varsa emin olunmaz
MAKS_TASMA = 0.12  # kose kadrajin bu kadar (uzun kenar oraninda) disinda olabilir
CIZGI_ADAYI = 10  # her yonde (yatay/dikey) denenen en guclu kenar cizgisi sayisi
IKINCI_TUR = 40  # on puanla secilip kesin puanlanan cizgi dortgeni sayisi
A4_ORANI = 2 ** 0.5
A4_TOLERANSI = 0.05  # oran A4'e bu kadar yakinsa tam A4'e esitlenir (perspektifsiz 4:3 = %5.7 disarida)
A4_300DPI = (2480, 3508)
A4_150DPI = (1240, 1754)
A4_MAKS_BUYUTME = 1.5  # kagit kaynakta en az 3508/1.5 px uzunsa 300 DPI A4 uretilir
ODAK_ARALIGI = (0.55, 0.8, 1.6)  # odak hesaplanamazsa denenen telefon odaklari (uzun kenara oranla; orta: tipik)
MIN_ODAK, MAKS_ODAK = 0.3, 5.0  # bunun disinda hesaplanan odak gurultudur
KADRAJ_KENAR_PAYI = 0.005  # kadraj disi tekrarlamada atlanan en dis piksel seridi
MAKS_EGIKLIK = 15.0  # belge bulunamadiginda duzeltilen en buyuk egiklik (derece)
INCE_EGIKLIK = 5.0  # perspektif duzeltmesinden sonra olculen en buyuk egiklik
MIN_EGIKLIK = 0.3  # bundan kucuk egiklik duzeltilmez (gereksiz yeniden ornekleme)
PROFIL_UZUN_KENAR = 700  # satir acisi olcumu bu boyutta yapilir
CIKTI_KALITESI = 95  # OCR'a gidecegi icin yuksek; saklamadan once zaten sikistirilir
# Taranmis belge algilama
TARAMA_SERIDI = 0.03  # bakilan kenar seridi (kisa kenara oranla)
TARAMA_MIN_ACIKLIK = 200.0  # seridin medyan Lab L degeri (0-255) en az bu kadar acik (beyaz/krem kagit)
TARAMA_MAKS_RENKLILIK = 12.0  # seridin a/b degeri notr renge bu kadar yakin (renkli masa degil)
TARAMA_DUZLUK = 0.85  # serit piksellerinin en az bu kadari seridin rengine yakin (duz zemin, nesne yok)
TARAMA_RENK_TOLERANSI = 12.0  # seritler birbirine ve kagida bu kadar yakin (isik azalmasi, arka plan yok)
TARAMA_PERSPEKTIF_FARKI = 1.0  # yazi satirlarinin acisi sayfanin iki yarisinda bundan fazla farkliysa perspektif var
TARAMA_MAKS_EGIKLIK = 3.0  # taranmis belgede duzeltilen en buyuk egiklik (derece)
DIS_KAGIT_BENZERLIGI = 5.0  # kenarin disi icine bu kadar yakinsa (Lab) disarisi da kagittir (icteki cerceve)


# ---------------------------------------------------------------- disa acik API

def goruntu_ac(veri):
    """JPG/PNG baytlarini EXIF yonu uygulanmis BGR diziye cevirir."""
    with Image.open(io.BytesIO(veri)) as acilan:
        goruntu = _rgb(ImageOps.exif_transpose(acilan))
    return cv2.cvtColor(np.asarray(goruntu), cv2.COLOR_RGB2BGR)


def analiz(bgr):
    """Goruntudeki belgeyi bulur.

    Donus: {"koseler": 4x2 float dizi veya None, "puan": 0-1, "belge": bool,
    "taranmis": bool}. koseler None ise duzeltme gerekmiyor/olculemedi. belge
    False iken koseler yalnizca egiklik duzeltmesidir (dondurulmus tam goruntu
    cercevesi). puan belge algilamanin guvenidir; egiklikte 1, hicbir sey
    yoksa 0. taranmis: tarayici ciktisi algilandi; kirpilmaz, yalnizca ±3
    derece egiklik duzeltilir.
    """
    if taranmis_mi(bgr):
        return {**_yalnizca_egiklik(bgr, TARAMA_MAKS_EGIKLIK), "taranmis": True}
    koseler, puan = belge_koseleri(bgr)
    if koseler is not None:
        return {"koseler": _ince_egiklik_kat(bgr, koseler), "puan": puan, "belge": True, "taranmis": False}
    return {**_yalnizca_egiklik(bgr, MAKS_EGIKLIK), "taranmis": False}


def _yalnizca_egiklik(bgr, sinir):
    """Belge kirpilmadan yalnizca yazi satirlarinin egikligi duzeltilir. Aci
    her zaman ±15 derecede olculur; sinirdan buyukse (taranmis belgede 3
    derece) goruntuye dokunulmaz."""
    aci = egiklik_acisi(bgr)
    if aci is not None and MIN_EGIKLIK <= abs(aci) <= sinir:
        y, g = bgr.shape[:2]
        cerceve = np.float32([[0, 0], [g, 0], [g, y], [0, y]])
        return {"koseler": _dondur(cerceve, aci, icine_sigdir=False, boyut=(y, g)), "puan": 1.0, "belge": False}
    return {"koseler": None, "puan": 0.0, "belge": False}


def taranmis_mi(bgr):
    """Goruntu tarayici ciktisi mi (telefon fotografi degil)?

    Uc kosul birlikte aranir: (1) dort kenar seridi duz ve acik renkli (beyaz
    ya da krem kagit; nesne, yazi, golge yok), (2) arka plan yok: seritler
    birbirine ve sayfanin icindeki kagit rengine yakin (masa, isik azalmasi,
    vinyet yok), (3) perspektif bozulmasi yok: yazi satirlarinin acisi
    sayfanin ust/alt ve sol/sag yarisinda ayni. Telefonla kagidin tamami
    kadraji dolduracak sekilde dik cekilmis duzgun isikli fotograf da taranmis
    sayilir; onda da kirpilacak bir sey yoktur."""
    if min(bgr.shape[:2]) < MIN_KENAR_PX:
        return False
    kucuk, _ = _kucult(bgr)
    lab = cv2.cvtColor(cv2.GaussianBlur(kucuk, (3, 3), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    y, g = lab.shape[:2]
    s = max(3, int(TARAMA_SERIDI * min(y, g)))
    kagit = np.median(lab[s:-s, s:-s].reshape(-1, 3), axis=0)
    renkler = []
    for serit in (lab[:s], lab[-s:], lab[:, :s], lab[:, -s:]):
        piksel = serit.reshape(-1, 3)
        renk = np.median(piksel, axis=0)
        if renk[0] < TARAMA_MIN_ACIKLIK or np.hypot(renk[1] - 128, renk[2] - 128) > TARAMA_MAKS_RENKLILIK:
            return False
        if (np.linalg.norm(piksel - renk, axis=1) < TARAMA_RENK_TOLERANSI).mean() < TARAMA_DUZLUK:
            return False
        if np.linalg.norm(renk - kagit) > TARAMA_RENK_TOLERANSI:
            return False
        renkler.append(renk)
    renkler = np.array(renkler)
    if np.linalg.norm(renkler[:, None] - renkler[None], axis=2).max() > TARAMA_RENK_TOLERANSI:
        return False
    # Perspektifte karsilikli yarilardaki satirlar farkli acilarla egilir.
    yy, gg = bgr.shape[0] // 2, bgr.shape[1] // 2
    for a, b in ((bgr[:yy], bgr[yy:]), (bgr[:, :gg], bgr[:, gg:])):
        if not (_yazili(a) and _yazili(b)):
            continue  # bos yarida olculen aci gurultudur
        aci_a, aci_b = _satir_acisi(a, MAKS_EGIKLIK), _satir_acisi(b, MAKS_EGIKLIK)
        if aci_a is not None and aci_b is not None and abs(aci_a - aci_b) > TARAMA_PERSPEKTIF_FARKI:
            return False
    return True


def _yazili(parca, en_az=0.005):
    """Parcada satir acisi olculebilecek kadar koyu (murekkep) piksel var mi?
    Sabit esik: bos kagitta Otsu JPEG gurultusunu yazi sanar."""
    kucuk, _ = _kucult(parca, PROFIL_UZUN_KENAR)
    gri = cv2.cvtColor(kucuk, cv2.COLOR_BGR2GRAY) if kucuk.ndim == 3 else kucuk
    return (gri < 128).mean() >= en_az


def uygula(bgr, koseler, uzun_kenar=None):
    """Koseleri dik dikdortgene esitleyen perspektif donusumu. koseler None ise
    goruntu aynen doner.

    Cikti orani perspektiften tahmin edilen gercek kagit oranidir; A4'e
    yakinsa tam A4 olur ve kaynak yeterince buyukse 300 DPI A4 (2480x3508)
    uretilir. Goruntu disina tasan koseler (kadrajdan tasan kagit, egiklik
    duzeltmesi) kenar piksellerini tekrarlar; fotograf kenarindaki ince
    serit (baska nesne, vinyet) tekrarlanmasin diye en distaki birkac piksel
    atlanir.

    uzun_kenar: cikti bu boyutu asiyorsa dogrudan kucuk uretilir (OCR icin);
    once tam boyut uretip sonra kucultmekten hizlidir."""
    if koseler is None:
        return bgr
    koseler = np.asarray(koseler, dtype=np.float32)
    y, g = bgr.shape[:2]
    genislik, yukseklik = _hedef_boyut(koseler, (y, g))
    if uzun_kenar and max(genislik, yukseklik) > uzun_kenar:
        oran = uzun_kenar / max(genislik, yukseklik)
        genislik, yukseklik = max(1, round(genislik * oran)), max(1, round(yukseklik * oran))
    hedef = np.float32([[0, 0], [genislik, 0], [genislik, yukseklik], [0, yukseklik]])
    matris = cv2.getPerspectiveTransform(koseler, hedef)
    pay = max(1, int(round(KADRAJ_KENAR_PAYI * max(y, g))))
    tasiyor = (koseler < 0).any() or (koseler[:, 0] > g).any() or (koseler[:, 1] > y).any()
    if tasiyor and min(y, g) > 4 * pay:
        bgr = cv2.copyMakeBorder(bgr[pay:y - pay, pay:g - pay], pay, pay, pay, pay, cv2.BORDER_REPLICATE)
    return cv2.warpPerspective(
        bgr, matris, (genislik, yukseklik), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def duzelt(veri):
    """JPG/PNG baytlarini alir; (veri, uygulandi_mi) dondurur.

    Kose saklamayan cagiranlar icin kisayol. Duzeltme uygulanmazsa ya da bir
    hata olursa orijinal baytlar aynen doner.
    """
    try:
        bgr = goruntu_ac(veri)
        koseler = analiz(bgr)["koseler"]
        if koseler is None:
            return veri, False
        return jpeg(uygula(bgr, koseler)), True
    except Exception:
        return veri, False


def jpeg(bgr, kalite=CIKTI_KALITESI):
    tamam, veri = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, kalite])
    if not tamam:
        raise ValueError("Görüntü JPEG'e çevrilemedi.")
    return veri.tobytes()


def koseleri_olcekle(koseler, oran):
    """Koseleri baska cozunurlukteki ayni goruntuye tasir (orn. 4000 px -> 2000 px)."""
    return None if koseler is None else np.asarray(koseler, dtype=np.float32) * oran


def koseler_gecerli(koseler, boyut):
    """Kullanicidan gelen koseler: 4 nokta, goruntunun makul yakininda, disbukey
    ve yeterince buyuk mu? boyut: (genislik, yukseklik)."""
    try:
        nokta = np.asarray(koseler, dtype=np.float32).reshape(4, 2)
    except (TypeError, ValueError):
        return False
    g, y = boyut
    pay = 0.15 * max(g, y)  # egiklik duzeltmesinde koseler goruntu disina tasabilir
    if not np.isfinite(nokta).all() or (nokta < -pay).any() or (nokta[:, 0] > g + pay).any() or (nokta[:, 1] > y + pay).any():
        return False
    if not cv2.isContourConvex(nokta.reshape(4, 1, 2)):
        return False
    return cv2.contourArea(nokta) >= 0.02 * g * y


# ---------------------------------------------------------------- algilama

def _rgb(goruntu):
    if goruntu.mode in ("RGBA", "LA", "P"):
        rgba = goruntu.convert("RGBA")
        zemin = Image.new("RGB", rgba.size, "white")
        zemin.paste(rgba, mask=rgba.getchannel("A"))
        return zemin
    return goruntu.convert("RGB")


def kucult(goruntu, uzun_kenar):
    """Uzun kenari en fazla uzun_kenar olacak sekilde kucultur; buyutmez."""
    return _kucult(goruntu, uzun_kenar)[0]


def _kucult(goruntu, uzun_kenar=ANALIZ_UZUN_KENAR):
    oran = uzun_kenar / max(goruntu.shape[:2])
    if oran >= 1:
        return goruntu, 1.0
    return cv2.resize(goruntu, None, fx=oran, fy=oran, interpolation=cv2.INTER_AREA), oran


def belge_koseleri(bgr):
    """Belgenin 4 kosesini (orijinal cozunurlukte, sol ust/sag ust/sag alt/sol alt)
    ve algilama puanini dondurur; bulunamazsa (None, 0).

    Adaylar iki kaynaktan gelir: kenar cizgileri (Hough; kagidin 4 kenar
    cizgisinin kesisimleri, koseler kadraj disinda da olabilir) ve parlaklik/
    renk maskelerinin konturlari. Hepsi ayni olcutle puanlanir: dortgenin
    kenarlari boyunca ic taraf kagit rengindeyken dis taraf belirgin sekilde
    farkli mi? Beyaz duvar ya da parlak masa yansimasi kagitla ayni renkte
    oldugu icin bu olcute takilir; goruntu kenarina dayanan (gorunmeyen)
    kenarlar destek almaz."""
    if min(bgr.shape[:2]) < MIN_KENAR_PX:
        return None, 0.0
    kucuk, oran = _kucult(bgr)
    ortam = _ortam(kucuk)
    adaylar = _cizgi_dortgenleri(ortam) + _maske_dortgenleri(kucuk, ortam["boyut"])
    puanlar = [_dortgen_puani(ortam, dortgen) for dortgen in adaylar]
    en_iyi_puan, en_iyi = 0.0, None
    for i in sorted(range(len(adaylar)), key=lambda i: puanlar[i], reverse=True):
        if puanlar[i] < MIN_PUAN:
            break
        # Belgenin icindeki cerceve ya da tablo: disi da kagit, kagit kenari degil.
        if not _disi_kagit_mi(ortam, adaylar[i]):
            en_iyi_puan, en_iyi = puanlar[i], adaylar[i]
            break
    if en_iyi is None:
        return None, en_iyi_puan
    if _karsitlik(ortam["lab"], en_iyi) < MIN_KARSITLIK:
        return None, en_iyi_puan
    inceltilmis = _kenarlari_incelt(ortam, en_iyi)
    if inceltilmis is not None:
        yeni_puan = _dortgen_puani(ortam, inceltilmis)
        if yeni_puan >= en_iyi_puan - 0.02:
            en_iyi_puan, en_iyi = max(en_iyi_puan, yeni_puan), inceltilmis

    koseler = en_iyi / oran
    merkez = koseler.mean(axis=0)
    return merkez + (koseler - merkez) * KOSE_ICERI_CEKME, en_iyi_puan


def _ortam(kucuk):
    """Puanlamada tekrar tekrar kullanilan olcumler: bulanik Lab, kenar haritasi."""
    y, g = kucuk.shape[:2]
    lab8 = cv2.cvtColor(cv2.GaussianBlur(kucuk, (5, 5), 0), cv2.COLOR_BGR2LAB)
    kenar = np.zeros((y, g), np.uint8)
    for kanal in cv2.split(lab8):
        kenar |= cv2.Canny(kanal, 20, 60)
    return {
        "lab": lab8.astype(np.float32),
        "kenar": kenar,
        "boyut": (y, g),
        # kenarin iki yanindan ornek alinan uzaklik: yazi tek pikselli
        # gurultuden, kagit kenarindaki bulaniklik da bu kadardan kucuk
        "ofset": max(3.0, KENAR_OFSETI * max(y, g)),
        "kayma": max(2.0, KENAR_KAYMASI * max(y, g)),
    }


def _ornekle(lab, noktalar):
    """Noktalardaki Lab degerleri ve goruntu icinde olup olmadiklari."""
    y, g = lab.shape[:2]
    x = np.rint(noktalar[:, 0]).astype(np.int64)
    yy = np.rint(noktalar[:, 1]).astype(np.int64)
    icinde = (x >= 0) & (x < g) & (yy >= 0) & (yy < y)
    return lab[np.clip(yy, 0, y - 1), np.clip(x, 0, g - 1)], icinde


def _kagit_uzakligi(renk, kagit):
    """Kagit rengine uzaklik; parlaklik farki yarim agirlikli (golge ve isik
    azalmasi kagidin parlakligini sayfa boyunca degistirir, rengini degil)."""
    fark = renk - kagit
    return np.sqrt((0.5 * fark[..., 0]) ** 2 + fark[..., 1] ** 2 + fark[..., 2] ** 2)


def _kenar_puanlari(ortam, dortgen):
    """Her kenar icin 0-1 arasi kontrast destegi.

    Kenar boyunca ornek noktalarin iki yanina bakilir: ic taraf kagit rengine
    yakin, dis taraf ondan belirgin sekilde uzak ve iki taraf arasinda gercek
    bir renk farki varsa o nokta kenari destekler. Kadraj disinda kalan
    noktalar sayilmaz; kenarin yarisindan azi gorunuyorsa puani orantili duser
    (goruntu kenarina dayanan kenar supheli)."""
    lab, ofset = ortam["lab"], ortam["ofset"]
    kagit = _kagit_rengi(lab, dortgen)
    merkez = dortgen.mean(axis=0)
    puanlar = np.zeros(4)
    for i in range(4):
        a, b = dortgen[i], dortgen[(i + 1) % 4]
        uzunluk = float(np.linalg.norm(b - a))
        if uzunluk < 1:
            continue
        yon = (b - a) / uzunluk
        normal = np.array([-yon[1], yon[0]], np.float32)
        if np.dot(merkez - a, normal) < 0:
            normal = -normal  # iceriyi gosteren normal
        t = np.linspace(0.03, 0.97, max(12, int(uzunluk / 2)))[:, None]
        noktalar = a + t * (b - a)
        gorunur = np.zeros(len(t), bool)
        destek = np.zeros(len(t), bool)
        # Kagit kenari hafif kavisli olabilir (bukulmus sayfa): gercek kenar
        # cizgiye birkac piksel yakinsa da nokta destek sayilir.
        for kayma in np.linspace(-ortam["kayma"], ortam["kayma"], 5):
            merkez_nokta = noktalar + normal * kayma
            ic, ic_gorunur = _ornekle(lab, merkez_nokta + normal * ofset)
            dis, dis_gorunur = _ornekle(lab, merkez_nokta - normal * ofset)
            burada = ic_gorunur & dis_gorunur
            gorunur |= burada
            destek |= burada & _kenar_destegi(ic, dis, kagit)
        if not gorunur.any():
            continue
        gorunurluk = gorunur.mean()
        puanlar[i] = destek.sum() / gorunur.sum() * min(1.0, gorunurluk / MIN_GORUNURLUK)
    return puanlar


def _kenar_destegi(ic, dis, kagit):
    """Kenarin iki yanindaki ornek ciftleri kagit kenarina uyuyor mu?

    Ic taraf kagit renginde (golgede biraz koyu olabilir), dis taraf ondan
    belirgin sekilde farkli ve ya daha koyu ya da renkce kagittan uzak olmali.
    Boylece yazi satiri (ic taraf murekkep, dis taraf kagit) ya da kagidin
    disindaki masa/laptop siniri (ic taraf ahsap) kenar sayilmaz."""
    ic_ab = np.linalg.norm(ic[:, 1:] - kagit[1:], axis=1)
    dis_ab = np.linalg.norm(dis[:, 1:] - kagit[1:], axis=1)
    return (
        (np.linalg.norm(ic - dis, axis=1) > KONTRAST_ESIGI)
        & (_kagit_uzakligi(ic, kagit) < KAGIT_TOLERANSI)
        & ((ic[:, 0] > dis[:, 0] + KONTRAST_ESIGI / 2) | (dis_ab > ic_ab + KONTRAST_ESIGI / 2))
    )


def _disi_kagit_mi(ortam, dortgen):
    """Dortgenin disi da kagit mi (belgenin icindeki cerceve ya da tablo)?

    Koyu bir cerceve cizgisi kontrast puanini kagit kenari kadar destekler
    (ic yani kagit, cizginin kendisi koyu). Bu yuzden her kenarin iki yanina,
    cizginin otesinde birkac kat uzaktan bakilir: gercek kagit kenarinin disi
    masa/zemindir; icteki cercevenin disi ise yine ayni kagittir. Disi kadrajda
    gorunen kenarlardan en az ucunde dis taraf ic tarafla (ya da dortgenin
    kagit rengiyle; ic taraf tablonun gri baslik satiri olabilir) ayni
    renkteyse dortgen kagit kenari sayilmaz."""
    lab, ofset, kayma = ortam["lab"], ortam["ofset"], ortam["kayma"]
    kagit = _kagit_rengi(lab, dortgen)
    merkez = dortgen.mean(axis=0)
    kagit_disli = 0
    for i in range(4):
        a, b = dortgen[i], dortgen[(i + 1) % 4]
        uzunluk = float(np.linalg.norm(b - a))
        if uzunluk < 1:
            continue
        yon = (b - a) / uzunluk
        normal = np.array([-yon[1], yon[0]], np.float32)
        if np.dot(merkez - a, normal) < 0:
            normal = -normal  # iceriyi gosteren normal
        noktalar = a + np.linspace(0.1, 0.9, max(10, int(uzunluk / 4)))[:, None] * (b - a)
        ic_renk, dis_renk = [], []
        for uzaklik in np.linspace(kayma + 2 * ofset, kayma + 6 * ofset, 3):
            ic, ic_gorunur = _ornekle(lab, noktalar + normal * uzaklik)
            dis, dis_gorunur = _ornekle(lab, noktalar - normal * uzaklik)
            burada = ic_gorunur & dis_gorunur
            ic_renk.append(ic[burada])
            dis_renk.append(dis[burada])
        ic_renk, dis_renk = np.concatenate(ic_renk), np.concatenate(dis_renk)
        if len(dis_renk) < 0.3 * 3 * len(noktalar):
            continue  # disi kadrajda gorunmuyor: karar verilemez
        dis = np.median(dis_renk, axis=0)
        fark = min(np.linalg.norm(np.median(ic_renk, axis=0) - dis), np.linalg.norm(kagit - dis))
        if fark < DIS_KAGIT_BENZERLIGI:
            kagit_disli += 1
    return kagit_disli >= 3


def _kagit_rengi(lab, dortgen):
    """Dortgenin icinden (kenarlardan uzak) alinan orneklerin medyan rengi."""
    birim = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
    matris = cv2.getPerspectiveTransform(birim, dortgen.astype(np.float32))
    u = np.linspace(0.1, 0.9, 15, dtype=np.float32)
    izgara = np.stack(np.meshgrid(u, u), axis=-1).reshape(-1, 1, 2)
    noktalar = cv2.perspectiveTransform(izgara, matris).reshape(-1, 2)
    renk, icinde = _ornekle(lab, noktalar)
    return np.median(renk[icinde] if icinde.any() else renk, axis=0)


def _dortgen_puani(ortam, dortgen):
    """Dortgenin belge olma puani (0-1); belge olamayacak dortgen icin 0.

    Puan kenarlarin kontrast desteklerinin ortalamasidir. Tek bir zayif kenar
    (kadrajdan tasan ya da duvar/yansima ile birlesen kagit) puani emin olma
    esiginin altina ceker; iki zayif kenarli dortgen belge sayilmaz."""
    if not _gecerli_dortgen(dortgen, ortam["boyut"]):
        return 0.0
    kenarlar = _kenar_puanlari(ortam, dortgen)
    zayif = int((kenarlar < ZAYIF_KENAR).sum())
    if zayif >= 2:
        return 0.0
    puan = float(kenarlar.mean())
    if zayif:
        puan = min(puan, EMIN_PUANI - 0.05)
    return puan


def _gecerli_dortgen(dortgen, boyut):
    """Alan, disbukeylik, ic acilar, en-boy orani ve kadraj tasmasi kontrolu."""
    y, g = boyut
    if not cv2.isContourConvex(dortgen.reshape(4, 1, 2)):
        return False
    pay = MAKS_TASMA * max(y, g)
    if (dortgen < -pay).any() or (dortgen[:, 0] > g + pay).any() or (dortgen[:, 1] > y + pay).any():
        return False
    cerceve = np.float32([[0, 0], [g, 0], [g, y], [0, y]])
    gorunen_alan, _ = cv2.intersectConvexConvex(dortgen.astype(np.float32), cerceve)
    if not MIN_BELGE_ORANI <= gorunen_alan / (g * y) <= MAKS_BELGE_ORANI:
        return False
    if np.abs(_acilar(dortgen) - 90).max() > 55:
        return False
    genislik, yukseklik = _hedef_boyut(dortgen)
    return max(genislik, yukseklik) / max(min(genislik, yukseklik), 1) <= 3


def _acilar(dortgen):
    acilar = []
    for i in range(4):
        a, b, c = dortgen[i - 1], dortgen[i], dortgen[(i + 1) % 4]
        v1, v2 = a - b, c - b
        cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        acilar.append(np.degrees(np.arccos(np.clip(cos, -1, 1))))
    return np.array(acilar)


def _karsitlik(lab, dortgen):
    """Dortgenin ici ile disi arasindaki ortalama Lab renk farki."""
    maske = np.zeros(lab.shape[:2], np.uint8)
    cv2.fillConvexPoly(maske, np.rint(dortgen).astype(np.int32), 255)
    if cv2.countNonZero(maske) == maske.size:
        return 0.0
    ic = cv2.mean(lab, mask=maske)[:3]
    dis = cv2.mean(lab, mask=255 - maske)[:3]
    return float(np.linalg.norm(np.subtract(ic, dis)))


# ---- kenar cizgilerinden adaylar

def _cizgiler(ortam):
    """Kenar haritasindaki duz cizgiler: (nokta, birim yon). Hough parcalari
    ayni dogru uzerindekiler birlestirilerek tek cizgiye indirgenir."""
    y, g = ortam["boyut"]
    kisa = min(y, g)
    parcalar = cv2.HoughLinesP(
        ortam["kenar"], 1, np.pi / 360, threshold=max(20, int(0.06 * kisa)),
        minLineLength=int(0.08 * kisa), maxLineGap=max(3, int(0.01 * max(y, g))),
    )
    if parcalar is None:
        return []
    parcalar = parcalar.reshape(-1, 4).astype(np.float32)
    boylar = np.hypot(parcalar[:, 2] - parcalar[:, 0], parcalar[:, 3] - parcalar[:, 1])
    aci_payi = np.cos(np.radians(2.0))
    uzaklik_payi = 0.01 * np.hypot(y, g)
    kumeler = []  # [yon, normal, uc noktalar]
    for i in np.argsort(-boylar):
        x1, y1, x2, y2 = parcalar[i]
        yon = np.array([x2 - x1, y2 - y1], np.float32) / boylar[i]
        orta = np.array([(x1 + x2) / 2, (y1 + y2) / 2], np.float32)
        for kume in kumeler:
            if abs(np.dot(yon, kume[0])) > aci_payi and abs(np.dot(orta - kume[2][0], kume[1])) < uzaklik_payi:
                kume[2].extend([(x1, y1), (x2, y2)])
                break
        else:
            kumeler.append([yon, np.array([-yon[1], yon[0]]), [(x1, y1), (x2, y2)]])
    cizgiler = []
    for _, _, uclar in kumeler:
        vx, vy, x0, y0 = cv2.fitLine(np.float32(uclar), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        cizgiler.append((np.array([x0, y0], np.float32), np.array([vx, vy], np.float32)))
    return cizgiler


def _cizgi_destegi(ortam, nokta, yon):
    """Cizgi boyunca kontrast destegi: her iki yana bakan kumulatif sayaclar.

    Donus: (t, gorunur_kumulatif, destek_kumulatif). t cizgi uzerindeki
    konumdur (nokta + t * yon); bir kenarin destegi iki t arasindaki farktan
    O(1)'de okunur. Burada kagit rengi bilinmedigi icin yalnizca iki yan
    arasindaki renk farkina bakilir; kesin puan _kenar_puanlari'dadir."""
    y, g = ortam["boyut"]
    yaricap = np.hypot(y, g)
    merkez = np.array([g / 2, y / 2], np.float32)
    nokta = nokta + np.dot(merkez - nokta, yon) * yon  # goruntu merkezine en yakin nokta
    t = np.arange(-yaricap, yaricap, 1.5, dtype=np.float32)
    noktalar = nokta + t[:, None] * yon
    normal = np.array([-yon[1], yon[0]], np.float32)
    a, a_icinde = _ornekle(ortam["lab"], noktalar + normal * ortam["ofset"])
    b, b_icinde = _ornekle(ortam["lab"], noktalar - normal * ortam["ofset"])
    gorunur = a_icinde & b_icinde
    destek = gorunur & (np.linalg.norm(a - b, axis=1) > KONTRAST_ESIGI)
    return nokta, t, np.cumsum(gorunur), np.cumsum(destek)


def _kesisim(c1, c2):
    (p1, u1), (p2, u2) = c1, c2
    capraz = u1[0] * u2[1] - u1[1] * u2[0]
    if abs(capraz) < 1e-6:
        return None
    fark = p2 - p1
    t = (fark[0] * u2[1] - fark[1] * u2[0]) / capraz
    return p1 + t * u1


def _cizgi_dortgenleri(ortam):
    """Yatay ve dikey cizgi ciftlerinin kesisimlerinden aday dortgenler.

    Her yonde en cok desteklenen CIZGI_ADAYI cizgi ve goruntunun kendi
    kenarlari (kagit kadrajdan tasmissa) denenir. Tum kombinasyonlar hizli bir
    on puanla (iki yan arasi renk farki) siralanir, en iyi IKINCI_TUR aday
    kesin puanlamaya gecer."""
    y, g = ortam["boyut"]
    cizgiler = []
    for nokta, yon in _cizgiler(ortam):
        nokta, t, gorunur, destek = _cizgi_destegi(ortam, nokta, yon)
        cizgiler.append({"nokta": nokta, "yon": yon, "t": t, "gorunur": gorunur, "destek": destek,
                         "yatay": abs(yon[0]) >= abs(yon[1]), "guc": int(destek[-1])})
    for nokta, yon, yatay in (((0, 0), (1, 0), True), ((0, y - 1), (1, 0), True),
                              ((0, 0), (0, 1), False), ((g - 1, 0), (0, 1), False)):
        cizgiler.append({"nokta": np.float32(nokta), "yon": np.float32(yon), "t": None,
                         "yatay": yatay, "guc": 0})

    def secilen(yatay):
        grup = [c for c in cizgiler if c["yatay"] == yatay and c["t"] is not None]
        grup = sorted(grup, key=lambda c: c["guc"], reverse=True)[:CIZGI_ADAYI]
        grup += [c for c in cizgiler if c["yatay"] == yatay and c["t"] is None]
        # yataylar goruntu ortasindaki y'ye, dikeyler x'e gore siralanir
        eksen = 1 if yatay else 0
        merkez = np.array([g / 2, y / 2], np.float32)

        def konum(c):
            kesim = _kesisim((c["nokta"], c["yon"]), (merkez, np.float32([0, 1] if yatay else [1, 0])))
            return float(kesim[eksen]) if kesim is not None else 0.0
        return sorted(grup, key=konum), konum

    yataylar, y_konum = secilen(True)
    dikeyler, x_konum = secilen(False)
    ciftler = lambda grup, konum, en_az: [  # noqa: E731
        (a, b) for i, a in enumerate(grup) for b in grup[i + 1:] if konum(b) - konum(a) >= en_az
    ]
    yatay_ciftleri = ciftler(yataylar, y_konum, 0.25 * y)
    dikey_ciftleri = ciftler(dikeyler, x_konum, 0.25 * g)

    def kenar_on_puani(c, a, b):
        if c["t"] is None:
            return 0.0
        ta, tb = sorted((float(np.dot(a - c["nokta"], c["yon"])), float(np.dot(b - c["nokta"], c["yon"]))))
        i, j = np.searchsorted(c["t"], [ta, tb])
        i, j = min(i, len(c["t"]) - 1), min(j, len(c["t"]) - 1)
        toplam = max(j - i, 1)
        gorunur = c["gorunur"][j] - c["gorunur"][i]
        if gorunur <= 0:
            return 0.0
        return (c["destek"][j] - c["destek"][i]) / gorunur * min(1.0, gorunur / toplam / MIN_GORUNURLUK)

    adaylar = []
    for ust, alt in yatay_ciftleri:
        for sol, sag in dikey_ciftleri:
            if ust["t"] is None and alt["t"] is None or sol["t"] is None and sag["t"] is None:
                continue
            koseler = [_kesisim((ust["nokta"], ust["yon"]), (sol["nokta"], sol["yon"])),
                       _kesisim((ust["nokta"], ust["yon"]), (sag["nokta"], sag["yon"])),
                       _kesisim((alt["nokta"], alt["yon"]), (sag["nokta"], sag["yon"])),
                       _kesisim((alt["nokta"], alt["yon"]), (sol["nokta"], sol["yon"]))]
            if any(k is None for k in koseler):
                continue
            dortgen = np.float32(koseler)
            pay = MAKS_TASMA * max(y, g)
            if (dortgen < -pay).any() or (dortgen[:, 0] > g + pay).any() or (dortgen[:, 1] > y + pay).any():
                continue
            on_puan = (kenar_on_puani(ust, dortgen[0], dortgen[1]) + kenar_on_puani(sag, dortgen[1], dortgen[2])
                       + kenar_on_puani(alt, dortgen[2], dortgen[3]) + kenar_on_puani(sol, dortgen[3], dortgen[0]))
            adaylar.append((on_puan, dortgen))
    adaylar.sort(key=lambda a: a[0], reverse=True)
    return [d for _, d in adaylar[:IKINCI_TUR]]


def _kenarlari_incelt(ortam, dortgen):
    """Her kenari, yakinindaki kenar piksellerine (Canny) yeniden oturtur;
    Hough'un aci/konum adimlarindan ve maske konturlarinin yuvarlak
    koselerinden kaynaklanan birkac piksellik hatayi giderir."""
    ys, xs = np.nonzero(ortam["kenar"])
    pikseller = np.stack([xs, ys], axis=1).astype(np.float32)
    cizgiler = []
    for i in range(4):
        a, b = dortgen[i], dortgen[(i + 1) % 4]
        uzunluk = float(np.linalg.norm(b - a))
        yon = (b - a) / max(uzunluk, 1e-6)
        normal = np.array([-yon[1], yon[0]], np.float32)
        goreli = pikseller - a
        t = goreli @ yon
        yakin = (np.abs(goreli @ normal) < 3) & (t > 0.05 * uzunluk) & (t < 0.95 * uzunluk)
        if yakin.sum() < 0.2 * uzunluk:
            cizgiler.append((a, yon))
            continue
        vx, vy, x0, y0 = cv2.fitLine(pikseller[yakin], cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        yeni_yon = np.array([vx, vy], np.float32)
        if abs(np.dot(yeni_yon, yon)) < np.cos(np.radians(3)):
            cizgiler.append((a, yon))
        else:
            cizgiler.append((np.array([x0, y0], np.float32), yeni_yon))
    koseler = [_kesisim(cizgiler[i - 1], cizgiler[i]) for i in range(4)]
    if any(k is None for k in koseler):
        return None
    return np.float32(koseler)


# ---- parlaklik/renk maskelerinden adaylar

def _maske_dortgenleri(kucuk, boyut):
    adaylar = []
    for maske in _aday_maskeler(kucuk).values():
        konturlar, _ = cv2.findContours(maske, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for kontur in sorted(konturlar, key=cv2.contourArea, reverse=True)[:5]:
            if cv2.contourArea(kontur) < MIN_BELGE_ORANI * boyut[0] * boyut[1] * 0.8:
                break
            dortgen = _dortgen(kontur)
            if dortgen is not None:
                adaylar.append(_koseleri_sirala(dortgen))
    return adaylar


def _aday_maskeler(kucuk):
    """Belge kagidini ayirmaya calisan farkli yontemlerin ikili maskeleri."""
    gri = cv2.GaussianBlur(cv2.cvtColor(kucuk, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    cekirdek = np.ones((5, 5), np.uint8)
    maskeler = {}

    # 1) Kenarlar: iki farkli hassasiyet (dusuk kontrastli beyaz masa icin 20/60)
    for ad, (alt, ust) in {"canny": (50, 150), "canny_hassas": (20, 60)}.items():
        kenar = cv2.Canny(gri, alt, ust)
        maskeler[ad] = cv2.dilate(kenar, np.ones((3, 3), np.uint8), iterations=2)

    # 2) Parlaklik: kagit genelde masadan aciktir
    _, parlak = cv2.threshold(gri, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    maskeler["parlaklik"] = cv2.morphologyEx(parlak, cv2.MORPH_CLOSE, cekirdek, iterations=3)

    # 3) Masa rengine uzaklik: kenardaki seritten masa rengi tahmin edilir (Lab)
    lab = cv2.cvtColor(cv2.GaussianBlur(kucuk, (7, 7), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    y, g = gri.shape
    s = max(3, int(min(y, g) * 0.03))
    serit = np.concatenate([lab[:s].reshape(-1, 3), lab[-s:].reshape(-1, 3),
                            lab[:, :s].reshape(-1, 3), lab[:, -s:].reshape(-1, 3)])
    uzaklik = np.linalg.norm(lab - np.median(serit, axis=0), axis=2)
    uzaklik = cv2.normalize(uzaklik, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, farkli = cv2.threshold(uzaklik, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    maskeler["renk_farki"] = cv2.morphologyEx(farkli, cv2.MORPH_CLOSE, cekirdek, iterations=3)

    # 4) Dusuk doygunluk + yuksek parlaklik: beyaz kagit, bej/ahsap masadan ayrilir
    hsv = cv2.cvtColor(kucuk, cv2.COLOR_BGR2HSV)
    beyazlik = cv2.subtract(hsv[..., 2], hsv[..., 1])
    beyazlik = cv2.GaussianBlur(beyazlik, (5, 5), 0)
    _, beyaz = cv2.threshold(beyazlik, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    maskeler["beyazlik"] = cv2.morphologyEx(beyaz, cv2.MORPH_CLOSE, cekirdek, iterations=3)
    return maskeler


def _dortgen(kontur):
    """Konturun dis bukey zarfini artan hassasiyetle 4 koseye indirger."""
    zarf = cv2.convexHull(kontur)
    cevre = cv2.arcLength(zarf, True)
    for oran in (0.01, 0.015, 0.02, 0.03, 0.04, 0.05, 0.07):
        yaklasik = cv2.approxPolyDP(zarf, oran * cevre, True)
        if len(yaklasik) == 4:
            return yaklasik.reshape(4, 2).astype(np.float32)
        if len(yaklasik) < 4:
            return None
    return None


def _koseleri_sirala(noktalar):
    """Sol ust, sag ust, sag alt, sol alt."""
    toplam = noktalar.sum(axis=1)
    fark = np.diff(noktalar, axis=1).ravel()  # y - x
    return np.array(
        [
            noktalar[np.argmin(toplam)],
            noktalar[np.argmin(fark)],
            noktalar[np.argmax(toplam)],
            noktalar[np.argmax(fark)],
        ],
        dtype=np.float32,
    )


def _hedef_boyut(koseler, boyut=None):
    """Duzeltilmis goruntunun (genislik, yukseklik) degeri.

    Cozunurluk en uzun gorunen kenardan gelir. boyut (kaynak goruntunun
    (yukseklik, genislik) degeri) verilirse en-boy orani perspektiften
    tahmin edilir: kameraya egik tutulmus kagit fotografta oldugundan kisa
    gorunur. Dortgen makul bir telefon odagiyla A4 olabiliyorsa tam A4'e
    esitlenir ve boyut 300 DPI'ye (kaynak yetiyorsa) ya da en az 150 DPI'ye
    oturtulur. Perspektifsiz dortgende (4:3, fis) oran aynen kalir."""
    su, sa_ust, sa_alt, so = koseler
    genislik = max(np.linalg.norm(sa_ust - su), np.linalg.norm(sa_alt - so), 1.0)
    yukseklik = max(np.linalg.norm(so - su), np.linalg.norm(sa_alt - sa_ust), 1.0)
    if boyut is None:
        return int(round(genislik)), int(round(yukseklik))
    # Odak kosegenden hesaplanabilir ama birkac piksellik kose hatasina cok
    # duyarlidir (ya da simetrik yamukta hic hesaplanamaz). Bu yuzden makul
    # telefon odaklari denenir: A4 bunlardan biriyle uyusuyorsa kagit A4'tur.
    adaylar = [_gercek_oran(koseler, boyut, c * max(boyut)) for c in ODAK_ARALIGI]
    adaylar = [a for a in adaylar if a] or [yukseklik / genislik]
    oran = adaylar[len(adaylar) // 2]
    hesaplanan = _gercek_oran(koseler, boyut)
    if hesaplanan is not None and min(adaylar) <= hesaplanan <= max(adaylar):
        oran = hesaplanan
    a4 = A4_ORANI if oran >= 1 else 1 / A4_ORANI
    a4_mu = min(adaylar) * (1 - A4_TOLERANSI) <= a4 <= max(adaylar) * (1 + A4_TOLERANSI)
    if a4_mu:
        oran = a4
    genislik = max(genislik, yukseklik / oran)
    yukseklik = genislik * oran
    if a4_mu:
        # Kaynak yetiyorsa 300 DPI; cok dusuk cozunurlukte en az 150 DPI
        # (kucuk yazi okunur kalir, tarama filtresi harf kenarlarini yumusatir).
        uzun = max(genislik, yukseklik)
        if uzun * A4_MAKS_BUYUTME >= A4_300DPI[1]:
            return A4_300DPI if oran >= 1 else A4_300DPI[::-1]
        if uzun < A4_150DPI[1]:
            return A4_150DPI if oran >= 1 else A4_150DPI[::-1]
    return max(int(round(genislik)), 1), max(int(round(yukseklik)), 1)


def _gercek_oran(koseler, boyut, odak=None):
    """Perspektif altindaki dikdortgenin gercek yukseklik/genislik orani
    (Zhang ve He, "Whiteboard scanning and image enhancement", 2007).

    Goruntu merkezinin optik merkez oldugu varsayilir. odak verilmezse
    dortgenden hesaplanir; hesaplanamiyorsa (karsilikli kenarlardan en az bir
    cift paralel: odak gozlemlenemez) None doner."""
    y, g = boyut
    su, sa_ust, sa_alt, so = (np.array([p[0] - g / 2, p[1] - y / 2, 1.0]) for p in koseler)
    with np.errstate(divide="ignore", invalid="ignore"):
        k2 = np.dot(np.cross(su, sa_alt), so) / np.dot(np.cross(sa_ust, sa_alt), so)
        k3 = np.dot(np.cross(su, sa_alt), sa_ust) / np.dot(np.cross(so, sa_alt), sa_ust)
    if not np.isfinite([k2, k3]).all():
        return None
    n2, n3 = k2 * sa_ust - su, k3 * so - su
    uzun = max(y, g)
    if odak is None:
        # n2[2], n3[2] ~ 0: kenar ciftleri paralel, kaybolma noktasi sonsuzda
        if min(abs(n2[2]), abs(n3[2])) < 1e-3:
            return None
        odak_kare = -(n2[0] * n3[0] + n2[1] * n3[1]) / (n2[2] * n3[2])
        if not (MIN_ODAK * uzun) ** 2 <= odak_kare <= (MAKS_ODAK * uzun) ** 2:
            return None
    else:
        odak_kare = float(odak) ** 2
    pay = n3[0] ** 2 + n3[1] ** 2 + odak_kare * n3[2] ** 2
    payda = n2[0] ** 2 + n2[1] ** 2 + odak_kare * n2[2] ** 2
    if payda <= 0 or pay <= 0:
        return None
    return float(np.sqrt(pay / payda))


# ---------------------------------------------------------------- egiklik

def _satir_acisi(bgr, sinir):
    """Yazi satirlarinin yataydan sapmasi (izdusum profili yontemi).

    Goruntu -sinir..+sinir arasinda dondurulur; satirlar tam yatay oldugunda
    satir toplamlari en keskin (tepe/vadi) hale gelir. Donus: goruntuyu
    duzeltmek icin getRotationMatrix2D'ye verilecek aci; guvenilir tepe yoksa
    ya da en iyi aci aralik sinirindaysa None."""
    kucuk, _ = _kucult(bgr, PROFIL_UZUN_KENAR)
    gri = cv2.cvtColor(kucuk, cv2.COLOR_BGR2GRAY) if kucuk.ndim == 3 else kucuk
    _, ikili = cv2.threshold(gri, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    doluluk = cv2.countNonZero(ikili) / ikili.size
    if not 0.002 < doluluk < 0.4:  # bos ya da neredeyse tamamen koyu
        return None
    y, g = ikili.shape
    merkez = (g / 2, y / 2)

    def keskinlik(aci):
        matris = cv2.getRotationMatrix2D(merkez, aci, 1.0)
        donmus = cv2.warpAffine(ikili, matris, (g, y), flags=cv2.INTER_NEAREST)
        profil = donmus.sum(axis=1, dtype=np.float64)
        return float(np.square(np.diff(profil)).sum())

    kaba = np.arange(-sinir, sinir + 1e-9, 0.5)
    kaba_puan = np.array([keskinlik(a) for a in kaba])
    en_iyi = float(kaba[kaba_puan.argmax()])
    ince = np.arange(en_iyi - 0.5, en_iyi + 0.5 + 1e-9, 0.1)
    ince_puan = np.array([keskinlik(a) for a in ince])
    aci = float(ince[ince_puan.argmax()])
    tepe_belirgin = kaba_puan.max() >= 1.3 * np.median(kaba_puan)
    if not tepe_belirgin or abs(aci) >= sinir - 0.25:
        return None
    return aci


def egiklik_acisi(bgr, sinir=MAKS_EGIKLIK):
    """Goruntuyu duzeltmek icin getRotationMatrix2D'ye verilecek aci (derece);
    olculemezse None."""
    return _satir_acisi(bgr, sinir)


def _dondur(koseler, aci, icine_sigdir, boyut=None):
    """Kose dortgeninin temsil ettigi cikti goruntusunu 'aci' kadar dondurmek
    icin gereken yeni kaynak koseleri.

    Cikti uzayindaki dikdortgen ters yonde dondurulur ve perspektif
    donusumunun tersiyle kaynaga geri tasinir. icine_sigdir: dondurulmus
    dikdortgen kagidin icinde kalacak kadar kucultulur (koselerde masa
    gorunmesin). boyut: kaynak goruntunun (yukseklik, genislik) degeri; cikti
    orani uygula() ile ayni hesaplansin diye."""
    genislik, yukseklik = _hedef_boyut(koseler, boyut)
    hedef = np.float32([[0, 0], [genislik, 0], [genislik, yukseklik], [0, yukseklik]])
    ters = cv2.getPerspectiveTransform(hedef, koseler)
    radyan = np.radians(aci)
    cos, sin = abs(np.cos(radyan)), abs(np.sin(radyan))
    olcek = 1.0
    if icine_sigdir:
        olcek = min(genislik / (genislik * cos + yukseklik * sin), yukseklik / (genislik * sin + yukseklik * cos))
    merkez = np.float32([genislik / 2, yukseklik / 2])
    donus = cv2.getRotationMatrix2D((0, 0), -aci, 1.0)[:, :2].astype(np.float32)
    dikdortgen = (hedef - merkez) * olcek @ donus.T + merkez
    kaynak = cv2.perspectiveTransform(dikdortgen.reshape(-1, 1, 2), ters).reshape(4, 2)
    return kaynak.astype(np.float32)


def _ince_egiklik_kat(bgr, koseler):
    """Perspektif duzeltmesinden sonra kalan kucuk satir egikligini (±5 derece)
    olcer ve koselere katlar."""
    kucuk, oran = _kucult(bgr)
    aci = _satir_acisi(uygula(kucuk, koseler * oran), INCE_EGIKLIK)
    if aci is None or abs(aci) < MIN_EGIKLIK:
        return koseler
    return _dondur(koseler, aci, icine_sigdir=True, boyut=bgr.shape[:2])
