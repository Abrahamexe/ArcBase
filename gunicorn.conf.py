"""Gunicorn ayarlari (Dockerfile'daki komut satiri secenekleriyle birlikte okunur).

Her worker sureci acilir acilmaz kendi arka plan iscisini baslatir; boylece
uygulama yeniden baslatildiginda yarim kalan isler ilk istegi beklemeden
kaldigi yerden devam eder (isleme.py).
"""


def post_worker_init(worker):
    import app
    import isleme
    import klasor_izleme

    if isleme.etkin():
        isleme.baslat()
    # Tarama klasoru (TARAMA_KLASORU): her worker izler; dosya once tasinip sonra
    # kuyruga eklendigi icin ayni dosyayi iki worker alamaz.
    if klasor_izleme.etkin():
        klasor_izleme.baslat(app.KULLANICI_BELGE_LIMITI)
