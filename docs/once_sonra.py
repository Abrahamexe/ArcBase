"""README icin tarama oncesi/sonrasi gorseli uretir.

Kullanim (proje kokunden):
    python docs/once_sonra.py foto1.jpg [foto2.jpg ...] [--mod renkli|gri|sb] [--cikti docs/screenshots/tarama-once-sonra.jpg]

Her fotograf icin: solda cekildigi hali, sagda uygulamanin urettigi sonuc
(otomatik kose algilama + perspektif/egiklik duzeltme + tarama filtresi).
Fotograflar veritabanina yuklenmez; yalnizca yerelde islenir.
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import goruntu_duzelt  # noqa: E402
import tarama  # noqa: E402

YUKSEKLIK = 640
ARALIK = 24


def _yukseklige_getir(goruntu):
    if goruntu.ndim == 2:
        goruntu = cv2.cvtColor(goruntu, cv2.COLOR_GRAY2BGR)
    oran = YUKSEKLIK / goruntu.shape[0]
    return cv2.resize(goruntu, None, fx=oran, fy=oran, interpolation=cv2.INTER_AREA)


def satir(yol, mod):
    once = goruntu_duzelt.goruntu_ac(Path(yol).read_bytes())
    sonuc = goruntu_duzelt.analiz(once)
    sonra = tarama.tara(goruntu_duzelt.uygula(once, sonuc["koseler"]), mod)
    sol, sag = _yukseklige_getir(once), _yukseklige_getir(sonra)
    bosluk = np.full((YUKSEKLIK, ARALIK, 3), 245, np.uint8)
    durum = "belge algilandi" if sonuc["belge"] else ("egiklik duzeltildi" if sonuc["koseler"] is not None else "duzeltme yok")
    print(f"{yol}: {durum}, puan {sonuc['puan']:.2f}")
    return np.hstack([sol, bosluk, sag])


def main():
    arg = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    arg.add_argument("fotograflar", nargs="+")
    arg.add_argument("--mod", choices=tarama.MODLAR, default=tarama.VARSAYILAN_MOD)
    arg.add_argument("--cikti", default="docs/screenshots/tarama-once-sonra.jpg")
    a = arg.parse_args()
    satirlar = [satir(yol, a.mod) for yol in a.fotograflar]
    genislik = max(s.shape[1] for s in satirlar)
    satirlar = [np.pad(s, ((0, 0), (0, genislik - s.shape[1]), (0, 0)), constant_values=245) for s in satirlar]
    ayrac = np.full((ARALIK, genislik, 3), 245, np.uint8)
    birlesik = satirlar[0]
    for s in satirlar[1:]:
        birlesik = np.vstack([birlesik, ayrac, s])
    cv2.imwrite(a.cikti, birlesik, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print("yazildi:", a.cikti)


if __name__ == "__main__":
    main()
