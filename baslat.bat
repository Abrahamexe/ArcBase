@echo off
rem ArcBase'i yerel agda baslatir (waitress, sunucu.py).
rem   baslat.bat            : pencerede calisir, adresleri gosterir
rem   baslat.bat /otomatik  : Gorev Zamanlayici icin; cikti logs\arcbase.log dosyasina yazilir
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo HATA: Sanal ortam bulunamadi ^(.venv^). Kurulum rehberindeki "Python ve paketler" adimini uygulayin.
    if /i not "%~1"=="/otomatik" pause
    exit /b 1
)

set PYTHONIOENCODING=utf-8
if /i "%~1"=="/otomatik" (
    if not exist logs mkdir logs
    ".venv\Scripts\python.exe" sunucu.py >> logs\arcbase.log 2>&1
    exit /b %errorlevel%
)

".venv\Scripts\python.exe" sunucu.py
if errorlevel 1 (
    echo.
    echo ArcBase baslatilamadi. Yukaridaki hata mesajini okuyun.
    pause
)
