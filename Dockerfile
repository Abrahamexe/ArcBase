# Dijital Arsiv — Render (Web Service, Docker) icin uretim imaji.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    URETIM=1

# Tesseract OCR + Turkce dil paketi. Linux'ta PATH'te oldugu icin
# TESSERACT_CMD ayari gerekmez. libglib2.0-0: OpenCV (headless) icin.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-tur libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bagimliliklar ayri katmanda: sadece kod degistiginde yeniden kurulmaz.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Uygulama root olmayan bir kullaniciyla calisir.
RUN useradd --create-home --shell /usr/sbin/nologin uygulama
USER uygulama

# Render PORT degiskenini kendisi verir (yerel docker run icin varsayilan 10000).
# OCR ve Groq arka plan iscisinde calisir (isleme.py); istekler kisa surer.
# Her worker birden fazla is parcacigiyla calisir: bir sayfanin onizlemeleri
# ayni anda sunulur. Worker sayisi varsayilan 2; bellek yetmezse Render'da
# WEB_CONCURRENCY=1 verilebilir. gunicorn.conf.py isciyi worker acilinca baslatir.
EXPOSE 10000
CMD gunicorn app:app --bind 0.0.0.0:${PORT:-10000} --workers ${WEB_CONCURRENCY:-2} --threads ${GUNICORN_THREADS:-4} --timeout 120 --access-logfile -
