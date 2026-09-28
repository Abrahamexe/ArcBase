"""Tarayici testleri (Playwright + Chromium): toplu yukleme arayuzu, kota
uyarisi ve mevcut belgelerden bilgi cikarma ilerlemesi gercek JS ile denenir.

Uygulama ayni surecte bir is parcaciginda calisir; OCR ve Groq taklit edilir.
Chromium kurulu degilse testler atlanir: playwright install chromium
"""

import threading
import time

import pytest
from werkzeug.serving import make_server

import app as uygulama_modulu
import database
import isleme
import ocr
from conftest import SIFRE, belge_ekle, jpeg

playwright_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def sunucu(uygulama, monkeypatch):
    uygulama.config["WTF_CSRF_ENABLED"] = True  # JS'in CSRF jetonu gonderdigi de denensin

    def yavas_ocr(veri, mime):
        time.sleep(0.2)
        return "FATURA metni"

    monkeypatch.setattr(ocr, "metin_cikar", yavas_ocr)
    sunucu = make_server("127.0.0.1", 0, uygulama, threaded=True)
    is_parcacigi = threading.Thread(target=sunucu.serve_forever, daemon=True)
    is_parcacigi.start()
    yield f"http://127.0.0.1:{sunucu.server_port}"
    sunucu.shutdown()


@pytest.fixture
def sayfa(sunucu, kullanici):
    k = kullanici()
    # Yuklemeleri arka plan iscisi isler (gercek is parcacigi); yalnizca bu
    # testin kullanicisinin isleri alinir.
    isleme.baslat(kullanici_id=k["id"])
    try:
        with playwright_api.sync_playwright() as p:
            tarayici = p.chromium.launch()
            s = tarayici.new_page()
            s.set_default_timeout(20000)
            s.goto(sunucu + "/giris")
            s.fill("input[name=kullanici_adi]", k["ad"])
            s.fill("input[name=sifre]", SIFRE)
            s.click("button[type=submit]")
            s.wait_for_url(sunucu + "/")
            yield s, k, sunucu
            tarayici.close()
    except playwright_api.Error as hata:
        if "Executable doesn't exist" in str(hata):
            pytest.skip("Chromium kurulu değil (playwright install chromium)")
        raise
    finally:
        isleme.durdur()


def dosya(ad, veri=None):
    return {"name": ad, "mimeType": "application/octet-stream", "buffer": veri if veri is not None else jpeg()}


FORM = "main [data-yukleme-formu]"  # dashboard'daki buyuk form


def test_bes_dosyalik_toplu_yukleme_biri_hatali(sayfa):
    s, k, _ = sayfa
    s.set_input_files(f"{FORM} [data-dosya-girisi]", [
        dosya("bir.jpg"), dosya("iki.jpg"), dosya("notlar.txt", b"metin"), dosya("dort.jpg"), dosya("bes.png"),
    ])
    satirlar = s.locator(f"{FORM} [data-kuyruk] li")
    assert satirlar.count() == 5
    assert satirlar.nth(2).get_attribute("data-durum") == "hata"
    assert "Sadece JPG, PNG ve PDF" in satirlar.nth(2).inner_text()
    assert s.locator(f"{FORM} [data-gonder]").inner_text().strip() == "4 belgeyi yükle ve analiz et"

    s.click(f"{FORM} [data-gonder]")
    s.wait_for_selector(f"{FORM} [data-ozet]:not([hidden])", timeout=60000)
    assert s.inner_text(f"{FORM} [data-ozet-metni]") == "4 belge kaydedildi, 1 hata."
    kaydedilen = s.locator(f'{FORM} [data-kuyruk] li[data-durum="kaydedildi"]')
    assert kaydedilen.count() == 4
    assert "Fatura" in kaydedilen.first.inner_text() and kaydedilen.first.locator("a", has_text="Aç").count() == 1
    assert database.belge_sayisi(k["id"]) == 4

    s.click(f"{FORM} a:has-text('Arşive git')")
    s.wait_for_selector(".belge-karti")
    assert s.locator(".belge-karti").count() == 4


def test_en_fazla_on_dosya(sayfa):
    s, _, _ = sayfa
    s.set_input_files(f"{FORM} [data-dosya-girisi]", [dosya(f"{i}.jpg", jpeg((64 + i, 48))) for i in range(12)])
    assert s.locator(f"{FORM} [data-kuyruk] li").count() == 10
    assert "en fazla 10 dosya" in s.inner_text(f"{FORM} [data-form-hata]")


def test_kota_asiminda_yukleme_baslamaz(sayfa, monkeypatch):
    s, k, _ = sayfa
    monkeypatch.setattr(uygulama_modulu, "KULLANICI_BELGE_LIMITI", 3)
    belge_ekle(k["id"])
    s.reload()
    s.set_input_files(f"{FORM} [data-dosya-girisi]", [dosya(f"{i}.jpg", jpeg((70 + i, 48))) for i in range(3)])
    s.click(f"{FORM} [data-gonder]")
    assert "Kotanızda 2 belgelik yer kaldı ama 3 dosya seçtiniz" in s.inner_text(f"{FORM} [data-form-hata]")
    time.sleep(1)
    assert database.belge_sayisi(k["id"]) == 1  # hic istek gonderilmedi
    # Fazla dosya cikarilinca yukleme yapilabilir
    s.locator(f"{FORM} [data-kuyruk] li [data-kaldir]").first.click()
    s.click(f"{FORM} [data-gonder]")
    s.wait_for_selector(f"{FORM} [data-ozet]:not([hidden])", timeout=60000)
    assert database.belge_sayisi(k["id"]) == 3


def test_tek_dosya_belge_sayfasina_gider(sayfa):
    s, k, sunucu = sayfa
    s.click("button[data-yukleme-ac] >> visible=true")
    pencere = "#yukleme-penceresi [data-yukleme-formu]"
    s.set_input_files(f"{pencere} [data-dosya-girisi]", [dosya("tek.jpg")])
    s.uncheck(f"{pencere} [data-duzelt-anahtari]")
    s.click(f"{pencere} [data-gonder]")
    s.wait_for_url(sunucu + "/belge/*")  # yukleme OCR'i beklemeden doner
    # Sayfa once "isleniyor" gosterir, is bitince kendiliginden yenilenir.
    s.wait_for_selector("[data-bilgi-karti]", timeout=30000)
    assert "Belge bilgileri" in s.content() and "Test Elektrik" in s.content()
    assert s.locator("[data-belge-isleniyor]").count() == 0
    assert not database.belgeleri_listele(k["id"])[0]["otomatik_duzeltildi"]


def test_mevcut_belgelerden_bilgi_cikarma_ilerlemesi(sayfa):
    s, k, sunucu = sayfa
    ids = [belge_ekle(k["id"], f"eski{i}.jpg", "fatura", "FATURA metni") for i in range(3)]
    s.goto(sunucu + "/hesap")
    assert "3 belgenin bilgileri henüz çıkarılmadı" in s.inner_text("[data-bilgi-durum]")
    s.click("[data-bilgi-cikar] button[type=submit]")
    s.wait_for_function(
        "document.querySelector('[data-bilgi-durum]').textContent.includes('3 belgeden bilgi çıkarıldı')",
        timeout=30000,
    )
    assert s.get_attribute("[data-bilgi-cubuk]", "aria-valuenow") == "100"
    assert all(database.belge_getir(k["id"], i)["kurum"] == "Test Elektrik A.Ş." for i in ids)


def test_filtre_ve_bilgi_duzenleme_formu(sayfa):
    s, k, sunucu = sayfa
    belge_id = belge_ekle(k["id"], "fatura.jpg", "fatura", kurum="Eski Firma", tutar=10)
    s.goto(f"{sunucu}/belge/{belge_id}")
    s.click("text=Bilgileri düzenle")
    s.fill("#bilgiler input[name=kurum]", "Yeni Firma")
    s.fill("#bilgiler input[name=tutar]", "1.250,50")
    s.select_option("#bilgiler select[name=para_birimi]", "TRY")
    s.click("#bilgiler button[type=submit]")
    s.wait_for_selector("text=Belge bilgileri güncellendi")
    assert "1.250,50 TL" in s.inner_text("#bilgiler")

    s.goto(sunucu + "/kategori/fatura")
    s.click("summary:has-text('Filtrele ve sırala')")
    s.fill("input[name=kurum]", "yeni")
    s.click("button:has-text('Uygula')")
    s.wait_for_url("**kurum=yeni**")
    assert s.locator(".belge-karti").count() == 1 and "1.250,50 TL" in s.inner_text("[data-fatura-ozeti]")


def _renkli_belge_ekle(kullanici_id):
    import crypto
    from ornek_gorseller import isik_bozulmasi, jpeg_bayt, renkli_belge

    veri = jpeg_bayt(isik_bozulmasi(renkli_belge((700, 990))[0]))
    return database.belge_ekle(
        kullanici_id=kullanici_id, dosya_adi="renkli.jpg", mime_type="image/jpeg",
        sifreli_icerik=crypto.sifrele(veri), sifreli_onizleme=crypto.sifrele(veri),
        ocr_metni="FATURA", tur="fatura", guven=0.9, aciklama="", orijinal_saklandi=True,
    )


def test_tarama_modu_secici_ve_karsilastirma(sayfa):
    s, k, sunucu = sayfa
    belge_id = _renkli_belge_ekle(k["id"])
    s.goto(f"{sunucu}/belge/{belge_id}")
    gorsel = s.locator("[data-tarama-gorsel]")
    assert gorsel.get_attribute("src").endswith("mod=renkli")

    s.click("[data-mod=gri]")
    s.wait_for_function("document.querySelector('[data-tarama-gorsel]').src.endsWith('mod=gri')")
    assert s.url.endswith(f"/belge/{belge_id}?mod=gri")  # sayfa yenilenmedi, adres guncellendi
    assert s.get_attribute("[data-mod=gri]", "aria-checked") == "true"
    assert s.get_attribute("#isik-kutusu .isik-gorsel", "src").endswith("mod=gri")

    # Son secilen mod hatirlanir: mod parametresiz acilista gri uygulanir
    s.goto(f"{sunucu}/belge/{belge_id}")
    s.wait_for_function("document.querySelector('[data-tarama-gorsel]').src.endsWith('mod=gri')")

    s.click("[data-karsilastir]")
    s.wait_for_selector("[data-karsilastirma]:not([hidden])")
    assert s.get_attribute("[data-once]", "src").endswith("mod=orijinal")
    assert s.get_attribute("[data-sonra]", "src").endswith("mod=gri")
    s.locator("[data-ayirici]").fill("20")
    assert "20%" in s.get_attribute("[data-karsilastirma]", "style")
    s.click("[data-karsilastir]")
    assert s.locator("[data-karsilastirma]").is_hidden()


def test_kose_editoru_surukle_kaydet_yeniden_analiz(sayfa):
    s, k, sunucu = sayfa
    belge_id = _renkli_belge_ekle(k["id"])  # 700x990, koseler yok
    s.goto(f"{sunucu}/belge/{belge_id}?koseler=1")  # "Kirpmayi kontrol et" baglantisi gibi
    s.wait_for_selector("[data-kose-editoru]:not([hidden])")
    s.wait_for_function("document.querySelector('[data-kose-gorsel]').naturalWidth > 0")
    assert s.locator("[data-isik-kutusu-ac]").is_hidden()

    tutamac = s.locator("[data-tutamac='0']")
    kutu = tutamac.bounding_box()
    sahne = s.locator("[data-kose-sahne]").bounding_box()
    s.mouse.move(kutu["x"] + kutu["width"] / 2, kutu["y"] + kutu["height"] / 2)
    s.mouse.down()
    s.mouse.move(sahne["x"] + sahne["width"] * 0.2, sahne["y"] + sahne["height"] * 0.1, steps=5)
    assert s.locator("[data-buyutec]").is_visible()  # suruklerken buyutec
    s.mouse.up()
    assert s.locator("[data-buyutec]").is_hidden()
    # klavye ile ince ayar
    tutamac.focus()
    s.keyboard.press("ArrowRight")

    s.click("[data-kose-kaydet]")
    s.wait_for_selector("[data-yeniden-analiz-onerisi]", timeout=30000)
    kayit = database.belge_getir(k["id"], belge_id)
    sol_ust = kayit["koseler"][0]
    assert abs(sol_ust[0] - 700 * 0.2) < 15 and abs(sol_ust[1] - 990 * 0.1) < 15
    assert kayit["koseler"][2] == [700, 990]
    assert "Kırpma elle ayarlandı" in s.content()
    assert "koseler=1" not in s.url

    s.click("text=Bilgileri güncelle")
    s.wait_for_selector("text=Belge yeniden analiz edildi")


def test_kose_editoru_gecersiz_dortgen_ve_otomatik(sayfa):
    s, k, sunucu = sayfa
    belge_id = _renkli_belge_ekle(k["id"])
    s.goto(f"{sunucu}/belge/{belge_id}")
    s.click("[data-kose-ac]")
    s.wait_for_function("document.querySelector('[data-kose-gorsel]').naturalWidth > 0")
    # sol ust tutamaci sag alta suruklemek dortgeni kesistirir
    ust = s.locator("[data-tutamac='0']").bounding_box()
    alt = s.locator("[data-tutamac='2']").bounding_box()
    s.mouse.move(ust["x"] + 10, ust["y"] + 10)
    s.mouse.down()
    s.mouse.move(alt["x"] + 40, alt["y"] + 40, steps=4)
    s.mouse.up()
    s.click("[data-kose-kaydet]")
    assert "Köşeler kesişiyor" in s.inner_text("[data-kose-mesaj]")
    s.click("[data-kose-otomatik]")
    s.wait_for_function("document.querySelector('[data-kose-mesaj]').textContent.includes('algılan') || document.querySelector('[data-kose-mesaj]').textContent.includes('eğiklik')")
    s.click("[data-kose-vazgec]")
    assert s.locator("[data-kose-editoru]").is_hidden() and s.locator("[data-isik-kutusu-ac]").is_visible()


def test_toplu_yuklemede_kirpmayi_kontrol_et(sayfa):
    from ornek_gorseller import jpeg_bayt, masada_egik_cekim

    s, _, _ = sayfa
    tasan = ((0.35, 0.10), (1.08, 0.12), (1.05, 0.92), (0.30, 0.90))
    s.set_input_files(f"{FORM} [data-dosya-girisi]", [
        {"name": "tasan.jpg", "mimeType": "image/jpeg", "buffer": jpeg_bayt(masada_egik_cekim(koseler=tasan))},
        {"name": "net.jpg", "mimeType": "image/jpeg", "buffer": jpeg_bayt(masada_egik_cekim())},
    ])
    s.click(f"{FORM} [data-gonder]")
    baglanti = s.wait_for_selector(f"{FORM} a:has-text('Kırpmayı kontrol et')", timeout=60000)
    assert baglanti.get_attribute("href").endswith("?koseler=1")
    assert "emin olunamadı" in s.inner_text(f"{FORM} [data-kuyruk]")
    # Belge sayfasi da kose editorunu onerir
    baglanti.click()
    s.wait_for_selector("[data-kose-editoru]:not([hidden])")
    assert s.locator("[data-kirpma-kontrol]").count() == 1


def test_pdf_indir_secili_modla(sayfa):
    s, k, sunucu = sayfa
    belge_id = _renkli_belge_ekle(k["id"])
    s.goto(f"{sunucu}/belge/{belge_id}")
    s.click("[data-mod=sb]")
    s.wait_for_function("document.querySelector('[data-pdf-indir]').href.endsWith('mod=sb')")
    assert "(Siyah-beyaz)" in s.inner_text("[data-pdf-indir]")
    with s.expect_download(timeout=60000) as indirme:
        s.click("[data-pdf-indir]")
    assert indirme.value.suggested_filename.startswith("fatura_") and indirme.value.suggested_filename.endswith(".pdf")
    # Menuden baska mod
    s.click("details.pdf-menu > summary")
    with s.expect_download(timeout=60000) as indirme:
        s.click("details.pdf-menu a:has-text('Gri')")
    assert indirme.value.suggested_filename.endswith(".pdf")
    assert not s.locator("details.pdf-menu").evaluate("m => m.open")


def test_coklu_secim_ve_pdf_birlestirme(sayfa, monkeypatch):
    s, k, sunucu = sayfa
    ids = [_renkli_belge_ekle(k["id"]) for _ in range(3)]
    monkeypatch.setattr(uygulama_modulu, "PDF_BIRLESTIRME_SINIRI", 2)
    s.goto(f"{sunucu}/kategori/fatura")
    s.click("[data-secim-ac]")
    assert s.locator("[data-secim-cubugu]").is_visible()

    s.click(f".belge-karti[data-belge-id='{ids[0]}']")
    s.click(f".belge-karti[data-belge-id='{ids[2]}']")
    assert s.url.endswith("/kategori/fatura")  # kart tiklamasi gezinmedi
    assert s.get_attribute(f".belge-karti[data-belge-id='{ids[2]}']", "data-sira") == "2"
    assert s.inner_text("[data-secim-sayisi]") == "2"

    s.click("[data-tumunu-sec]")  # 3 belge > sinir (2)
    assert "en fazla 2 belge" in s.inner_text("[data-secim-hata]")
    assert s.locator("[data-birlestir]").is_disabled()
    s.click(f".belge-karti[data-belge-id='{ids[1]}']")  # birini birak

    s.select_option("#birlestirme-modu", "sb")
    with s.expect_download(timeout=90000) as indirme:
        s.click("[data-birlestir]")
    assert indirme.value.suggested_filename.startswith("arsiv_birlesik_")
    import pymupdf
    pdf = pymupdf.open(indirme.value.path())
    assert pdf.page_count == 2 and len(pdf.get_toc()) == 2

    s.click("[data-secim-kapat]")
    assert s.locator("[data-secim-cubugu]").is_hidden()
    s.click(f".belge-karti[data-belge-id='{ids[0]}']")  # secim modu kapali: normal gezinme
    s.wait_for_url(f"**/belge/{ids[0]}")
