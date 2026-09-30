"""Uygulamayi waitress ile yerel agda calistirir (Windows; baslat.bat).

gunicorn Windows'ta calismadigi icin kurum kurulumunda waitress kullanilir;
Linux/Docker'da (Render) gunicorn aynen kalir. Tek surec, cok is parcacigi:
arka plan iscisi (isleme.py) bu surecte bir kez baslar.

Ayarlar (.env):
    PORT                 dinlenecek port (varsayilan 5001)
    SUNUCU_ADRESI        dinlenecek arayuz (varsayilan 0.0.0.0: tum yerel ag;
                         yalnizca bu bilgisayar icin 127.0.0.1)
    SUNUCU_IS_PARCACIGI  ayni anda islenen istek sayisi (varsayilan 8)
    HTTPS=1              onde TLS saglayan bir sunucu (ters vekil) varsa

Kullanim: python sunucu.py   (ya da baslat.bat)
"""

import os
import socket
import sys

from dotenv import load_dotenv

load_dotenv()

VARSAYILAN_PORT = 5001


def yerel_ag_adresleri():
    """Bu bilgisayarin yerel ag IPv4 adresleri (kullaniciya gosterilecek
    adres icin). Disariya hicbir baglanti acilmaz; yalnizca bilgisayarin
    kendi adinin adresleri okunur."""
    import yerel_mod

    try:
        bilgiler = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except socket.gaierror:
        return []
    adresler = []
    for *_, (adres, _port) in bilgiler:
        if adres not in adresler and not adres.startswith("127.") and yerel_mod.sunucu_yerel_mi(adres):
            adresler.append(adres)
    return adresler


def main():
    from waitress import serve

    for akis in (sys.stdout, sys.stderr):
        if not akis.isatty():  # gunluk dosyasi (baslat.bat /otomatik) UTF-8 yazilsin
            akis.reconfigure(encoding="utf-8", errors="replace")

    import app as uygulama  # YEREL_MOD denetimi burada yapilir; uymazsa cikar
    import isleme
    import klasor_izleme

    port = int(os.getenv("PORT") or VARSAYILAN_PORT)
    arayuz = (os.getenv("SUNUCU_ADRESI") or "0.0.0.0").strip()
    is_parcacigi = int(os.getenv("SUNUCU_IS_PARCACIGI") or 8)
    sema = "https" if uygulama.HTTPS else "http"

    print("ArcBase çalışıyor. Tarayıcıdan şu adreslerden açabilirsiniz:", flush=True)
    print(f"  Bu bilgisayardan:  {sema}://localhost:{port}", flush=True)
    if arayuz in ("0.0.0.0", ""):
        for adres in yerel_ag_adresleri():
            print(f"  Yerel ağdan:       {sema}://{adres}:{port}", flush=True)
    print("Durdurmak için bu pencereyi kapatın ya da Ctrl+C'ye basın.", flush=True)

    # Sema, yonetici, arka plan iscisi ve tarama klasoru ilk istegi beklemeden
    # hazirlanir. Veritabanina ulasilamazsa sunucu yine acilir; ilk istekte
    # yeniden denenir ve sayfada hata gosterilir.
    try:
        uygulama._veritabanini_hazirla_bir_kez()
    except Exception as hata:
        print(f"UYARI: Veritabanı hazırlanamadı: {hata}", file=sys.stderr, flush=True)
        if isleme.etkin():
            isleme.baslat()
        uygulama.arka_plan_izleyicilerini_baslat()
    if klasor_izleme.etkin():
        print(f"Tarama klasörü izleniyor: {klasor_izleme.klasor_ayari()}", flush=True)
    for klasor in klasor_izleme.izlenen_klasorler():
        if klasor["izleniyor"] and klasor["tur"] == "Windows tarama klasörü":
            print(f"Windows tarama klasörü izleniyor: {klasor['yol']}", flush=True)
    if uygulama.TARAYICI_WIA:
        print("Bağlı tarayıcılar kendiliğinden algılanıyor.", flush=True)
    serve(
        uygulama.app,
        host=arayuz,
        port=port,
        threads=is_parcacigi,
        url_scheme=sema,
        ident="ArcBase",
    )


if __name__ == "__main__":
    sys.exit(main())
