// Tailwind CSS (v3) ayarlari. Tarayicida calisan CDN yerine bu dosyayla
// derlenmis static/tailwind.css kullanilir. Sablonlarda ya da app.js'te yeni
// bir sinif kullanildiginda yeniden derleyin (Node gerekmez, README "Gelistirme"):
//   tailwindcss -c tailwind.config.js -i static/tailwind.giris.css -o static/tailwind.css --minify
//
// Tasarim: notr zemin, tek marka rengi (derin indigo), 1 px kenarlik ve cok
// hafif golge, olculu kose yuvarlakligi (6-8 px), 8 px aralik sistemi.
module.exports = {
  content: ['./templates/**/*.html', './static/app.js'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
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
      // Kose yuvarlakligi: mevcut siniflar olculu degerlere esitlenir (6-8 px).
      borderRadius: {
        md: '6px',
        lg: '6px',
        xl: '8px',
        '2xl': '8px',
        '3xl': '10px',
      },
      colors: {
        // Derin indigo (marka). Butonlar 600, koyu temada 400-500.
        marka: {
          50: '#EEF0F9', 100: '#DDE1F3', 200: '#BCC3E6', 300: '#97A1D6', 400: '#717FC4',
          500: '#5260AE', 600: '#3B4796', 700: '#2F397B', 800: '#252D61', 900: '#1C224A',
        },
        // Basari/onay yesili (tarihsel adiyla turkuaz); sicak vurgu gunes.
        turkuaz: { 400: '#4FB892', 500: '#2F9E78', 600: '#237F60' },
        gunes: { 50: '#FBF7EE', 100: '#F6EEDC', 400: '#D9A94A', 500: '#C18F2E', 600: '#9C7222' },
        // Yuzey ve metin renkleri CSS degiskenlerinden gelir (style.css); boylece
        // koyu temada her sinifa ayrica dark: yazmak gerekmez.
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
        kart: '0 1px 2px rgb(16 24 40 / 0.04)',
        yukselt: '0 12px 32px -12px rgb(16 24 40 / 0.18), 0 2px 6px rgb(16 24 40 / 0.05)',
      },
    },
  },
};
