"""Belgelerden cikarilan bilgi alanlari: ture gore tanimlar, dogrulama, bicimlendirme.

Ayni dogrulama hem Groq cevabina hem de kullanicinin elle duzelttigi forma
uygulanir. belge_tarihi, tutar, para_birimi ve kurum filtrelenip siralandigi icin
ayri sutunlarda; ture ozel diger alanlar belgeler.alanlar (JSONB) icinde durur.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# Tur -> (anahtar, etiket, tip). tip: tarih | tutar | para | metin
ALANLAR = {
    "fatura": (
        ("kurum", "Firma", "metin"),
        ("tutar", "Tutar", "tutar"),
        ("para_birimi", "Para birimi", "para"),
        ("belge_tarihi", "Fatura tarihi", "tarih"),
        ("fatura_no", "Fatura no", "metin"),
    ),
    "sozlesme": (
        ("kurum", "Taraflar", "metin"),
        ("belge_tarihi", "Sözleşme tarihi", "tarih"),
        ("konu", "Konu", "metin"),
        ("sure", "Süre", "metin"),
    ),
    "dilekce": (
        ("kurum", "Muhatap", "metin"),
        ("konu", "Konu", "metin"),
        ("belge_tarihi", "Tarih", "tarih"),
    ),
    "resmi_yazi": (
        ("kurum", "Kurum", "metin"),
        ("konu", "Konu", "metin"),
        ("sayi", "Sayı", "metin"),
        ("belge_tarihi", "Tarih", "tarih"),
    ),
    "kimlik": (
        ("belge_turu", "Belge türü", "metin"),
        ("gecerlilik_tarihi", "Geçerlilik tarihi", "tarih"),
    ),
    "diger": (
        ("konu", "Konu", "metin"),
        ("belge_tarihi", "Tarih", "tarih"),
    ),
}

SUTUN_ALANLARI = ("belge_tarihi", "tutar", "para_birimi", "kurum")

# Modelin bazen farkli adla dondurdugu alanlar
_ESANLAMLILAR = {"kurum": ("taraflar", "firma", "muhatap", "kurum_adi")}

METIN_SINIRI = 200
TUTAR_SINIRI = Decimal("1e12")  # NUMERIC(14,2) ust siniri
_BOS_DEGERLER = {"", "null", "none", "yok", "bilinmiyor", "belirtilmemiş", "-", "n/a"}
_PARA_ESLESME = {
    "TL": "TRY", "₺": "TRY", "YTL": "TRY", "TÜRK LİRASI": "TRY", "TURK LIRASI": "TRY",
    "$": "USD", "€": "EUR", "EURO": "EUR", "£": "GBP",
}
PARA_SIMGELERI = {"TRY": "TL", "USD": "$", "EUR": "€", "GBP": "£"}

# Gizlilik: kimlik belgelerinde TC kimlik no (11 hane) veya seri/belge numarasi
# iceren degerler saklanmaz. 5+ haneli rakam dizisi iceren metin alani reddedilir.
_KIMLIK_NUMARASI = re.compile(r"\d{5,}")
_TC_NUMARASI = re.compile(r"(?<!\d)\d{11}(?!\d)")


def _metin(deger):
    if isinstance(deger, (list, tuple)):
        deger = ", ".join(str(x).strip() for x in deger if x is not None and str(x).strip())
    elif isinstance(deger, (int, float, Decimal)) and not isinstance(deger, bool):
        deger = str(deger)
    if not isinstance(deger, str):
        return None
    temiz = " ".join(deger.split())
    if temiz.lower() in _BOS_DEGERLER:
        return None
    return temiz[:METIN_SINIRI]


def tarih_dogrula(deger):
    """YYYY-MM-DD (tercih edilen) veya GG.AA.YYYY; gecersizse None."""
    if isinstance(deger, datetime):
        deger = deger.date()
    if isinstance(deger, date):
        return deger if 1900 <= deger.year <= 2100 else None
    metin = _metin(deger)
    if not metin:
        return None
    for bicim in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            tarih = datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
        return tarih if 1900 <= tarih.year <= 2100 else None
    return None


def tutar_dogrula(deger):
    """Sayiya cevirir, 2 haneye yuvarlar. "1.234,56 TL" gibi elle girisleri de anlar."""
    if isinstance(deger, bool):
        return None
    if isinstance(deger, (int, float, Decimal)):
        metin = str(deger)
    else:
        metin = _metin(deger)
        if not metin:
            return None
        metin = re.sub(r"(?i)tl|try|usd|eur|gbp|[₺$€£\s]", "", metin)  # para birimi, bosluk
        if re.search(r"[^\d,.\-]", metin):
            return None  # "on lira", "1e20" gibi sayi olmayan metinler
        if re.fullmatch(r"-?\d{1,3}\.\d{3}", metin):
            metin = metin.replace(".", "")  # "1.500": iki haneli kurus olmadigi icin binlik ayirici
        elif "," in metin and "." in metin:
            # Sondaki ayirici ondaliktir: 1.234,56 veya 1,234.56
            if metin.rfind(",") > metin.rfind("."):
                metin = metin.replace(".", "").replace(",", ".")
            else:
                metin = metin.replace(",", "")
        elif metin.count(",") == 1:
            metin = metin.replace(",", ".")
        elif metin.count(",") > 1:
            metin = metin.replace(",", "")
        elif metin.count(".") > 1:
            metin = metin.replace(".", "")
    try:
        sayi = Decimal(metin)
    except InvalidOperation:
        return None
    if not sayi.is_finite() or abs(sayi) >= TUTAR_SINIRI:
        return None
    return sayi.quantize(Decimal("0.01"))


def para_dogrula(deger):
    """ISO para birimi koduna cevirir (TL -> TRY); taninmazsa None."""
    metin = _metin(deger)
    if not metin:
        return None
    kod = metin.upper().strip(" .")
    kod = _PARA_ESLESME.get(kod, kod)
    return kod if re.fullmatch(r"[A-Z]{3}", kod) else None


_DOGRULAYICILAR = {
    "tarih": tarih_dogrula,
    "tutar": tutar_dogrula,
    "para": para_dogrula,
    "metin": _metin,
}


def dogrula(tur, ham):
    """Ham alan sozlugunu (Groq JSON'u veya form) dogrular.

    Sadece o turun tanimli alanlari alinir; digerleri (ornegin modelin
    kurallara ragmen dondurdugu tc_kimlik_no) sessizce atilir. Donus:
    (temiz, hatalar) — temiz: {anahtar: deger veya None}, hatalar: bos
    olmayan ama gecersiz bulunan alanlarin etiketleri.
    """
    ham = ham if hasattr(ham, "get") else {}
    temiz, hatalar = {}, []
    for anahtar, etiket, tip in ALANLAR.get(tur, ALANLAR["diger"]):
        deger = ham.get(anahtar)
        for esanlamli in _ESANLAMLILAR.get(anahtar, ()):
            if _metin(deger) is None:
                deger = ham.get(esanlamli)
        sonuc = _DOGRULAYICILAR[tip](deger)
        if tur == "kimlik" and tip == "metin" and sonuc and _KIMLIK_NUMARASI.search(sonuc):
            sonuc = None
        if sonuc is None and _metin(deger) is not None:
            hatalar.append(etiket)
        temiz[anahtar] = sonuc
    return temiz, hatalar


def aciklamayi_temizle(tur, aciklama):
    """Kimlik belgelerinde modelin aciklamaya yazmis olabilecegi TC no'yu siler."""
    if tur == "kimlik" and aciklama:
        return _TC_NUMARASI.sub("•••••••••••", aciklama)
    return aciklama


# ---------------------------------------------------------------- bicimlendirme

def tutar_yaz(tutar, para_birimi=None):
    """1234.5, 'TRY' -> '1.234,50 TL'"""
    if tutar is None:
        return ""
    metin = f"{Decimal(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if para_birimi:
        return f"{metin} {PARA_SIMGELERI.get(para_birimi, para_birimi)}"
    return metin


def tarih_yaz(deger):
    """date veya 'YYYY-MM-DD' -> 'GG.AA.YYYY'; tanınmazsa oldugu gibi."""
    tarih = tarih_dogrula(deger)
    return tarih.strftime("%d.%m.%Y") if tarih else (deger or "")


def degerler(belge):
    """Belge kaydindaki (sutunlar + alanlar JSONB) tum alanlari tek sozlukte toplar."""
    sonuc = dict(belge.get("alanlar") or {})
    for anahtar in SUTUN_ALANLARI:
        if belge.get(anahtar) is not None:
            sonuc[anahtar] = belge[anahtar]
    return sonuc
