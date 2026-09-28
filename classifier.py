"""Groq API ile OCR metninden belge turu siniflandirmasi ve bilgi cikarma.

Siniflandirma ve alan cikarma tek istekte yapilir; ekstra kota harcanmaz.
"""

import json
import logging
import os

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

import alanlar
from database import TURLER, VARSAYILAN_TUR

load_dotenv()

GROQ_TABAN_URL = "https://api.groq.com/openai/v1"
# Plandaki llama-3.3-70b-versatile Groq tarafindan kaldirildi (404); hesapta
# kullanilabilen metin modeli bu. .env icindeki GROQ_MODEL ile degistirilebilir.
VARSAYILAN_MODEL = "openai/gpt-oss-120b"
METIN_SINIRI = 4000  # uzun belgelerde tokenden tasarruf icin metni kirp
YOGUN_MESAJI = (
    "Yapay zeka şu an yoğun, belge türünü daha sonra elle düzeltebilirsiniz."
)
# Kullaniciya gosterilen mesajlar sade tutulur; teknik neden sunucu loguna yazilir.
BAGLANTI_MESAJI = (
    "Belgenin türü şu an belirlenemedi: servise ulaşılamadı. Belge kaydedildi; "
    "birkaç dakika sonra detay sayfasından yeniden deneyebilirsiniz."
)
KALICI_HATA_MESAJI = (
    "Belgenin türü belirlenemedi: sınıflandırma servisi yapılandırmasında bir sorun var. "
    "Belge kaydedildi; türü elle seçebilirsiniz."
)

log = logging.getLogger("dijital_arsiv.groq")

# Anahtarlar alanlar.ALANLAR ile ayni olmali (test_alan_tanimlari_prompt_ile_uyumlu).
ALAN_ACIKLAMALARI = {
    "fatura": "kurum (faturayı kesen firma), tutar (ödenecek genel toplam), "
    "para_birimi, belge_tarihi (fatura tarihi), fatura_no",
    "sozlesme": "kurum (sözleşmenin tarafları, virgülle ayrılmış), "
    "belge_tarihi (sözleşme tarihi), konu, sure (sözleşme süresi, ör. \"12 ay\")",
    "dilekce": "kurum (dilekçenin verildiği kurum/muhatap), konu, belge_tarihi",
    "resmi_yazi": "kurum (yazıyı gönderen kurum), konu, sayi (yazının sayısı), belge_tarihi",
    "kimlik": "belge_turu (kimlik kartı, ehliyet, pasaport vb.), "
    "gecerlilik_tarihi (son geçerlilik tarihi)",
    "diger": "konu, belge_tarihi (bulunursa)",
}

SISTEM_PROMPTU = (
    "Sen bir belge sınıflandırma ve bilgi çıkarma asistanısın. Sana verilen OCR "
    "metnine bakarak önce belgenin türünü belirle, sonra o türe ait alanları metinden "
    "çıkar. Tür şu listeden biri olmalı: "
    + ", ".join(TURLER)
    + ". OCR metninde okuma hataları olabilir, genel içeriğe göre karar ver.\n\n"
    "Türe göre çıkarılacak alanlar:\n"
    + "\n".join(f"- {tur}: {aciklama}" for tur, aciklama in ALAN_ACIKLAMALARI.items())
    + "\n\nKurallar:\n"
    "- Sadece metinde açıkça yazan bilgileri çıkar. Metinde bulunmayan veya emin "
    "olmadığın her alan için null döndür; asla tahmin etme, uydurma.\n"
    "- Tarihleri YYYY-MM-DD biçiminde yaz.\n"
    "- Tutarları nokta ondalık ayırıcılı düz sayı olarak yaz (ör. 1234.56); binlik "
    "ayırıcı ve para simgesi kullanma.\n"
    "- Para birimini ISO koduyla yaz (TRY, USD, EUR...).\n"
    "- GİZLİLİK: Kimlik belgelerinde TC kimlik numarasını, doğum tarihini ve seri "
    "numarasını ASLA çıkarma; bunları ne alanlara ne de açıklamaya yaz.\n\n"
    'Sadece JSON formatında cevap ver: {"tur": "...", "guven": 0-1, '
    '"aciklama": "kısa Türkçe açıklama", "alanlar": {"alan_adi": "değer veya null"}}'
)


def _istemci_olustur():
    """Groq icin OpenAI-uyumlu istemci olusturur; anahtar yoksa None doner."""
    anahtar = os.getenv("GROQ_API_KEY")
    if not anahtar:
        return None
    # Kota asiminda (429) uzun bekleme yapilmasin: tek yeniden deneme, 30 sn sinir.
    # Boylece istek gunicorn'un 120 sn zaman asimina takilmaz.
    return OpenAI(
        api_key=anahtar, base_url=GROQ_TABAN_URL, max_retries=1, timeout=30.0
    )


def _sonuc(tur, guven, aciklama, hata_turu=None, bilgiler=None):
    """hata_turu: None (basarili) | "yogun" (429) | "baglanti" (ag, zaman asimi,
    5xx) | "kalici" (anahtar, model, bozuk cevap, anahtar tanimsiz).
    yogun: sonra yeniden denemek anlamlı mi ("yogun" ve "baglanti"); toplu
    yukleme ve bilgi cikarma bu bayrakla yeniden dener.
    bilgiler: dogrulanmis alanlar; None ise bilgi cikarma yapilamadi demektir."""
    return {
        "tur": tur,
        "guven": guven,
        "aciklama": aciklama,
        "yogun": hata_turu in ("yogun", "baglanti"),
        "hata_turu": hata_turu,
        "alanlar": bilgiler,
    }


def siniflandir(ocr_metni, bilinen_tur=None):
    """OCR metnini Groq'a gonderip {tur, guven, aciklama, yogun, alanlar} dondurur.

    bilinen_tur verilirse (mevcut belgelerden bilgi cikarma) tur yeniden
    belirlenmez, sadece o turun alanlari cikarilir.

    API anahtari yoksa, cagri basarisiz olursa veya JSON ayristirilamazsa
    uygulama cokmez; belge 'diger' / guven 0 olarak isaretlenir, aciklamaya
    sebebi yazilir ve alanlar None doner.
    """
    varsayilan = bilinen_tur or VARSAYILAN_TUR
    if not ocr_metni or not ocr_metni.strip():
        return _sonuc(
            varsayilan, 0.0, "Metin okunamadı, daha net bir fotoğraf deneyin."
        )

    istemci = _istemci_olustur()
    if istemci is None:
        log.error("GROQ_API_KEY tanımlı değil; sınıflandırma yapılamadı.")
        return _sonuc(varsayilan, 0.0, KALICI_HATA_MESAJI, hata_turu="kalici")

    prompt = SISTEM_PROMPTU
    if bilinen_tur:
        prompt += (
            f"\n\nBu belgenin türü kesin olarak '{bilinen_tur}'. \"tur\" alanına bunu "
            "yaz ve yalnızca bu türün alanlarını çıkar."
        )
    try:
        yanit = istemci.chat.completions.create(
            model=os.getenv("GROQ_MODEL", VARSAYILAN_MODEL),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": ocr_metni[:METIN_SINIRI]},
            ],
        )
        veri = json.loads(yanit.choices[0].message.content)
        if not isinstance(veri, dict):
            raise ValueError("cevap JSON nesnesi değil")
    except RateLimitError:
        log.warning("Groq kotasi asildi (429).")
        return _sonuc(varsayilan, 0.0, YOGUN_MESAJI, hata_turu="yogun")
    except APIConnectionError as hata:  # ag/DNS kesintisi, zaman asimi
        log.warning("Groq'a ulasilamadi: %s: %s", type(hata).__name__, hata.__cause__ or hata)
        return _sonuc(varsayilan, 0.0, BAGLANTI_MESAJI, hata_turu="baglanti")
    except (AuthenticationError, PermissionDeniedError, NotFoundError) as hata:
        # 401 gecersiz anahtar, 403 yetki, 404 model kaldirilmis: tekrar denemek ise yaramaz.
        log.error("Groq yapilandirma hatasi (HTTP %s, model %s): %s",
                  hata.status_code, os.getenv("GROQ_MODEL", VARSAYILAN_MODEL), hata.message)
        return _sonuc(varsayilan, 0.0, KALICI_HATA_MESAJI, hata_turu="kalici")
    except APIStatusError as hata:
        if hata.status_code >= 500:  # Groq tarafinda gecici sunucu hatasi
            log.warning("Groq sunucu hatasi (HTTP %s): %s", hata.status_code, hata.message)
            return _sonuc(varsayilan, 0.0, BAGLANTI_MESAJI, hata_turu="baglanti")
        log.error("Groq istegi reddedildi (HTTP %s): %s", hata.status_code, hata.message)
        return _sonuc(varsayilan, 0.0, KALICI_HATA_MESAJI, hata_turu="kalici")
    except Exception as hata:  # bozuk JSON, beklenmeyen hata
        log.exception("Groq cevabi islenemedi: %s", hata)
        return _sonuc(varsayilan, 0.0, KALICI_HATA_MESAJI, hata_turu="kalici")

    tur = bilinen_tur or _turu_duzelt(veri.get("tur"))
    bilgiler, _ = alanlar.dogrula(tur, veri.get("alanlar"))
    return _sonuc(
        tur,
        _guveni_duzelt(veri.get("guven")),
        alanlar.aciklamayi_temizle(tur, (veri.get("aciklama") or "").strip()),
        bilgiler=bilgiler,
    )


def _turu_duzelt(tur):
    """Modelin dondurdugu turu sabit tur listesinden birine esler."""
    if not isinstance(tur, str) or not tur.strip():
        return VARSAYILAN_TUR
    temiz = tur.strip().lower().replace(" ", "_")
    return temiz if temiz in TURLER else VARSAYILAN_TUR


def _guveni_duzelt(guven):
    """Guven skorunu 0-1 araligina sikistirir; sayi degilse 0 doner."""
    try:
        deger = float(guven)
    except (TypeError, ValueError):
        return 0.0
    if deger > 1:  # model yuzde olarak dondurmusse
        deger = deger / 100
    return max(0.0, min(1.0, deger))
