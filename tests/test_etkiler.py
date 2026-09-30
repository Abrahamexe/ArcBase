"""Gorsel etkiler (docs/vitrin): sablonlarin yeni yapisi. Hangi etki nerede: her biri tek yerde
kullanilir (spotlight yalniz Kategoriler izgarasinda, kenar isini yalniz hizli yukleme kartinda,
miknatis yalniz Panel'in ana dugmesinde...). Tarayici davranisi test_arayuz.py'de (yavas)."""

import re

from conftest import belge_ekle, isleme_durumu


def _panel(c):
    return c.get("/").get_data(as_text=True)


def test_etki_dosyalari_sayfada_ve_servis_edilir(girisli):
    c, _ = girisli
    html = _panel(c)
    css = re.search(r'href="(/static/etkiler\.css[^"]*)"', html).group(1)
    js = re.search(r'src="(/static/etkiler\.js[^"]*)"', html).group(1)
    for adres in (css, js):
        yanit = c.get(adres)
        assert yanit.status_code == 200
        yanit.close()
    assert "cdn." not in html and "googleapis" not in html


def test_panel_etkileri_tek_yerde(girisli):
    c, k = girisli
    for tur in ("fatura", "fatura", "kimlik"):
        belge_ekle(k["id"], tur=tur)
    html = _panel(c)
    # 13 karsilama: sunucu yedek selamlamayi kullanici adiyla yazar; ana eylem dugmesi tek ve miknatisli (15)
    assert html.count("data-karsilama>") == 1
    # yukleme yalnizca asagidaki Hizli yukleme kartinda: karsilamada dugme tekrarlanmaz
    bas = html.index("data-karsilama>")
    karsilama = html[bas:html.index("</section>", bas)]
    assert "<button" not in karsilama and "data-yukleme-ac" not in karsilama
    assert 'data-selam>Merhaba,' in html and k["ad"] in html
    # istatistik kutulari alt alta uc tane: toplam, haftalik, tarayici durumu
    assert html.count("data-tarayici-karti") == 1
    assert len(re.findall(r'class="renkli-kart [^"]*bolum-giris', html)) == 3
    # 6 spotlight: her tur icin bir kart, hepsi Kategoriler izgarasinda
    assert html.count("data-spot-kart") == 6 and html.count("data-spot-alani") == 1
    # 7 kenar isini yalniz hizli yukleme kartinda
    assert len(re.findall(r'class="kenar-isini[ "]', html)) == 1
    assert re.search(r'class="kenar-isini[^"]*"[^>]*>\s*<div class="kenar-isini-ic">\s*<h2[^>]*>Hızlı yükleme', html)
    # 12 sayaclar: toplam ve haftalik; kategori kartlarinda dagilim cubugu oranla dolar
    assert html.count("data-sayac=") == 2
    assert html.count('class="spot-cubuk"') == 6
    # 11 sayfa bolumleri bulanik girer
    assert html.count("bolum-giris") >= 6


def test_menu_renkli_karolar_ve_aciklamalar(girisli):
    c, _ = girisli
    html = _panel(c)
    menu = html[html.index('id="kenar-menu"'):html.index("</aside>")]
    # 5 aurora + 1 renk tonu her ogede + 4 aciklama satirlari
    assert 'class="aurora"' in menu
    tonlar = re.findall(r'class="menu-ogesi"[^>]*style="--h: (\d+)', menu)
    assert len(tonlar) >= 4 and len(set(tonlar)) >= len(tonlar) - 1  # her ogenin kendi rengi (Arama ve Diger ayni notr ton)
    assert menu.count("menu-alt") >= 4 and "Özet ve son belgeler" in menu
    # Kategori alt ogeleri: tur ikonu + kendi tonu + sira (asamali beliris icin)
    assert len(re.findall(r'data-tur="[a-z_]+" style="--h: \d+; --i: \d+', menu)) == 6
    # komut paleti sayfa adini ilk .kenar-etiket'ten okur: ad, aciklamadan once gelir
    assert re.search(r'menu-ad">Panel</span><small class="kenar-etiket menu-alt"', menu)


def test_kategori_agac_cizgisi_aktif_ture_gore(girisli):
    c, _ = girisli
    kategori = c.get("/kategori/kimlik").get_data(as_text=True)
    m = re.search(r'class="alt-liste" style="--n: (\d+); --dolgu: ([\d.]+); --h: (\d+)"', kategori)
    assert m and m.group(1) == "6"
    # kimlik listede ucuncu (indeks 2): (2 + .5) / (6 - .5)
    assert abs(float(m.group(2)) - 2.5 / 5.5) < 1e-3
    panel = _panel(c)
    assert re.search(r'class="alt-liste" style="--n: 6; --dolgu: 0;', panel)


def test_morph_ve_tarama_isigi_kancalari(girisli):
    c, k = girisli
    import database

    biten = belge_ekle(k["id"], "biten.jpg", ocr_metni="FATURA\nGenel Toplam: 720,00 TL")
    isleyen = belge_ekle(k["id"], "isleyen.jpg", tur="diger")
    database._sorgula("UPDATE belgeler SET isleme_durumu = 'isleniyor' WHERE id = %s", (isleyen,))
    liste = c.get("/kategori/diger").get_data(as_text=True)
    # 8 tarama isigi: yalniz islenen kartin kucuk resminde kanca (data-isleniyor) vardir
    assert f'data-belge-id="{isleyen}" data-isleniyor' in liste
    sayfa = c.get(f"/belge/{biten}").get_data(as_text=True)
    assert "onizleme-cercevesi" in sayfa and "data-isik-kutusu-ac data-isleniyor" not in sayfa
    isleyen_sayfa = c.get(f"/belge/{isleyen}").get_data(as_text=True)
    assert re.search(r"data-isik-kutusu-ac data-isleniyor", isleyen_sayfa)
    # 9 metin cikarma: metin kutusu ve kopyalama hedefi ayni kalir (textContent bozulmaz)
    assert 'data-ocr' in sayfa and 'id="ocr-metni"' in sayfa and "Genel Toplam: 720,00 TL" in sayfa
    assert isleme_durumu(c, isleyen)["durum"] == "isleniyor"


def test_tarayici_bilgi_kutusu_durumu(girisli):
    """Panel'deki ucuncu bilgi kutusu tarayici durumunu gosterir: kapali (bu bilgisayarda
    dogrudan tarama yok), bagli degil ya da bagli; canli guncellemeyi app.js yapar."""
    import app as uygulama_modulu

    c, _ = girisli
    html = _panel(c)
    kart = html[html.index("data-tarayici-karti"):]
    kart = kart[:kart.index("</div>\n  </div>")]
    durum = re.search(r'data-durum="(\w+)"', html[html.index("data-tarayici-karti"):]).group(1)
    if uygulama_modulu.TARAYICI_WIA:
        assert durum in ("bagli", "yok") and "data-tarayici-tara" in kart
    else:
        assert durum == "kapali" and "data-tarayici-tara" not in kart
    assert "data-tarayici-ozet" in kart and "data-tarayici-ad" in kart
