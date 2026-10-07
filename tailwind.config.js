// Tailwind CSS (v3) ayarlari. Tarayicida calisan CDN yerine bu dosyayla
// derlenmis static/tailwind.css kullanilir. Sablonlarda ya da app.js'te yeni
// bir sinif kullanildiginda yeniden derleyin (Node gerekmez, README "Gelistirme"):
//   tailwindcss -c tailwind.config.js -i static/tailwind.giris.css -o static/tailwind.css --minify
//
// Tasarim: Candy Blue zemin uzerinde beyaz, buyuk koseli kartlar (koyu temada
// Onyx zemin, Cosmic kartlar); tek sicak vurgu (amber), cok yumusak ve zeminin
// tonunu tasiyan golgeler, Plus Jakarta Sans. Renkler style.css degiskenlerinden.
module.exports = {
  content: ['./templates/**/*.html', './static/app.js'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
      },
      // Yazi olcegi: kucuk 12 · gövde 14 · alt baslik 16 · baslik 20/24
      fontSize: {
        xs: ['0.75rem', { lineHeight: '1rem' }],
        sm: ['0.875rem', { lineHeight: '1.25rem' }],
        base: ['1rem', { lineHeight: '1.5rem' }],
        lg: ['1.0625rem', { lineHeight: '1.5rem' }],
        xl: ['1.25rem', { lineHeight: '1.75rem' }],
        '2xl': ['1.5rem', { lineHeight: '2rem', letterSpacing: '-0.015em' }],
        '3xl': ['1.75rem', { lineHeight: '2.25rem', letterSpacing: '-0.02em' }],
        '4xl': ['2rem', { lineHeight: '2.5rem', letterSpacing: '-0.02em' }],
      },
      // Kose yuvarlakligi: referanstaki gibi yumusak; ic ogeler daha siki, kaplar daha genis.
      borderRadius: {
        md: '8px',
        lg: '10px',
        xl: '14px',
        '2xl': '20px',
        '3xl': '28px',
      },
      colors: {
        // Marka: celik mavi (Candy Blue ailesi); koyu temada lavanta. Ton olcegi her iki
        // temada da ayni anlamdadir (50 acik ... 900 koyu), yalnizca renk tonu degisir.
        marka: Object.fromEntries([50, 100, 200, 300, 400, 500, 600, 700, 800, 900]
          .map((n) => [n, `rgb(var(--marka-${n}) / <alpha-value>)`])),
        // Basari/onay yesili (tarihsel adiyla turkuaz); sicak vurgu gunes (amber #E8A33D).
        turkuaz: { 400: '#4FB892', 500: '#2F9E78', 600: '#237F60' },
        gunes: { 50: '#FDF6EA', 100: '#FAEACC', 400: '#F0B65A', 500: '#E8A33D', 600: '#B97A1C' },
        // Yuzey ve metin renkleri CSS degiskenlerinden gelir (style.css); boylece
        // koyu temada her sinifa ayrica dark: yazmak gerekmez.
        // Tek vurgu rengi (amber) ve secili hap/birincil dugmenin murekkep rengi.
        vurgu: 'rgb(var(--vurgu) / <alpha-value>)',
        murekkep: 'rgb(var(--murekkep) / <alpha-value>)',
        zemin: 'rgb(var(--zemin) / <alpha-value>)',
        kart: 'rgb(var(--kart) / <alpha-value>)',
        yuzey: 'rgb(var(--yuzey) / <alpha-value>)',
        cizgi: 'rgb(var(--cizgi) / <alpha-value>)',
        metin: {
          DEFAULT: 'rgb(var(--metin) / <alpha-value>)',
          2: 'rgb(var(--metin-2) / <alpha-value>)',
          3: 'rgb(var(--metin-3) / <alpha-value>)',
        },
      },
      boxShadow: {
        // Golgeler siyah degil, zeminin lacivert tonunu tasir; genis ve cok yumusak.
        kart: '0 1px 2px rgb(var(--golge) / 0.05), 0 8px 24px -12px rgb(var(--golge) / 0.14)',
        yukselt: '0 24px 60px -24px rgb(var(--golge) / 0.32), 0 4px 12px -4px rgb(var(--golge) / 0.08)',
      },
    },
  },
};
