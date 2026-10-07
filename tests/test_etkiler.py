"""Gorsel etkiler ve yeni arayuz yapisi (ust hap menu, Panel bento izgarasi). Her etki tek yerde
kullanilir (kadran ve belge yigini yalniz vitrinde, cubuklar yalniz kategori dagiliminda, radar
yalniz tarayici kartinda...). Tarayici davranisi test_arayuz.py'de (yavas)."""

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
    # karsilama (vitrin): sunucu yedek selamlamayi kullanici adiyla yazar
    assert html.count("data-karsilama>") == 1
    # yukleme yalnizca asagidaki Hizli yukleme kartinda: vitrinde dugme tekrarlanmaz
    bas = html.index("data-karsilama>")
    vitrin = html[bas:html.index("</section>", bas)]
    assert "<button" not in vitrin and "data-yukleme-ac" not in vitrin
    assert 'data-selam>Merhaba,' in html and k["ad"] in html
    # vitrinde depolama kadrani ve belge yigini; kadran ve yigin yalniz burada
    assert vitrin.count('class="kadran"') == 1 and vitrin.count('class="yigin"') == 1
    assert html.count('class="kadran"') == 1 and html.count('class="yigin"') == 1
    # kategori dagilimi: her tur icin bir cubuk, oranla dolar; yalniz bir grafik
    assert html.count('class="cubuk-sutun"') == 6 and html.count('class="cubuk-grafik"') == 1
    assert len(re.findall(r'class="cubuk-iz"><i style="--oran: [\d.]+"', html)) == 6
    # yay yalniz "Bu hafta", radar yalniz tarayici kartinda
    assert html.count('class="yay"') == 1 and html.count('class="radar"') == 1
    assert html.count("data-tarayici-karti") == 1
    # hizli yukleme karti formu tasir (test_arayuz.py "main [data-yukleme-formu]")
    assert re.search(r'<h2 id="yukleme-bolumu"[^>]*>Hızlı yükleme</h2>', html)
    # sayaclar: kadran (kullanilan) ve haftalik
    assert html.count("data-sayac=") == 2
    # sayfa bolumleri bulanik girer
    assert html.count("bolum-giris") >= 6


def test_ust_hap_menu(girisli):
    c, _ = girisli
    html = _panel(c)
    menu = html[html.index('id="ana-menu"'):html.index("</nav>", html.index('id="ana-menu"'))]
    # kayan aktif hap ve aktif sayfa (Panel)
    assert "data-aktif-gosterge" in menu
    assert re.search(r'class="nav-hap" aria-current="page">\s*<span class="menu-ikon relative">', menu)
    # Belgeler acilir paneli: alti kategori, her birinin sayaci; komut paleti adi .menu-ad'dan okur
    assert 'data-acilir="belgeler"' in menu and 'id="acilir-belgeler"' in menu
    assert len(re.findall(r'data-tur="[a-z_]+" style="--i: \d+"', menu)) == 6
    assert menu.count("data-tur-sayaci=") == 6
    assert 'menu-ad">Panel</span>' in menu
    # eski kenar menu yok; mobil menude ayni baglantilar
    assert 'id="kenar-menu"' not in html and "kenar-dar" not in html
    mobil = html[html.index('id="mobil-menu"'):]
    assert len(re.findall(r'data-tur="[a-z_]+"', mobil[:mobil.index("</nav>")])) == 6


def test_belgeler_hapi_kategori_sayfasinda_aktif(girisli):
    c, _ = girisli
    kategori = c.get("/kategori/kimlik").get_data(as_text=True)
    menu = kategori[kategori.index('id="ana-menu"'):]
    assert re.search(r'data-acilir="belgeler"[^>]*data-aktif', menu)
    assert re.search(r'data-tur="kimlik" style="--i: \d+"\s*aria-current="page"', menu)
    panel = _panel(c)
    assert not re.search(r'data-acilir="belgeler"[^>]*data-aktif', panel)


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
