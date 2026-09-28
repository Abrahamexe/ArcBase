"""Gunicorn ayarlari (Dockerfile'daki komut satiri secenekleriyle birlikte okunur).

Her worker sureci acilir acilmaz kendi arka plan iscisini baslatir; boylece
uygulama yeniden baslatildiginda yarim kalan isler ilk istegi beklemeden
kaldigi yerden devam eder (isleme.py).
"""


def post_worker_init(worker):
    import isleme

    if isleme.etkin():
        isleme.baslat()
