"""Islenmis gorseller icin surec ici LRU bellek onbellegi (toplam bayt sinirli).

Belge detayindaki tarama goruntusu her istekte sifre cozme + perspektif
duzeltme + tarama filtresi demektir; ayni goruntu (ayni belge surumu, ayni
mod) tekrar istendiginde buradan verilir. Anahtar belge kimligi, goruntu turu
ve moddur; deger icerik surumuyla birlikte tutulur, kose ya da icerik
degisince surum artar ve eski deger kullanilmaz. Sahiplik kontrolu onbellege
bakmadan once her istekte veritabaninda yapilir.
"""

import threading
from collections import OrderedDict


class BaytOnbellegi:
    def __init__(self, en_fazla_bayt):
        self._veri = OrderedDict()  # anahtar -> (surum, bayt, mime)
        self._boyut = 0
        self._sinir = en_fazla_bayt
        self._kilit = threading.Lock()

    def al(self, anahtar):
        with self._kilit:
            deger = self._veri.get(anahtar)
            if deger is not None:
                self._veri.move_to_end(anahtar)
            return deger

    def koy(self, anahtar, surum, bayt, mime):
        if len(bayt) > self._sinir // 8:  # tek bir dev goruntu onbellegi silip supurmesin
            return
        with self._kilit:
            eski = self._veri.pop(anahtar, None)
            if eski is not None:
                self._boyut -= len(eski[1])
            self._veri[anahtar] = (surum, bayt, mime)
            self._boyut += len(bayt)
            while self._boyut > self._sinir:
                _, (_, silinen, _) = self._veri.popitem(last=False)
                self._boyut -= len(silinen)

    def temizle(self):
        with self._kilit:
            self._veri.clear()
            self._boyut = 0
