// Tailwind CSS (v3) ayarlari. Tarayicida calisan CDN yerine bu dosyayla
// derlenmis static/tailwind.css kullanilir. Sablonlarda ya da app.js'te yeni
// bir sinif kullanildiginda yeniden derleyin (Node gerekmez, README "Gelistirme"):
//   tailwindcss -c tailwind.config.js -i static/tailwind.giris.css -o static/tailwind.css --minify
module.exports = {
  content: ['./templates/**/*.html', './static/app.js'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      colors: {
        marka: {
          50: '#EFF6FF', 100: '#DBEAFE', 200: '#BFDBFE', 300: '#93C5FD', 400: '#60A5FA',
          500: '#3B82F6', 600: '#2563EB', 700: '#1D4ED8', 800: '#1E40AF', 900: '#1E3A8A',
        },
        // Basari/onay yesili (tarihsel adiyla turkuaz); sicak vurgu gunes.
        turkuaz: { 400: '#34D399', 500: '#10B981', 600: '#059669' },
        gunes: { 50: '#FFFBEB', 100: '#FFF7DB', 400: '#FBBF24', 500: '#F59E0B', 600: '#D97706' },
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
        kart: '0 1px 2px rgb(16 24 40 / 0.04), 0 1px 3px rgb(16 24 40 / 0.06)',
        yukselt: '0 18px 36px -12px rgb(16 24 40 / 0.18), 0 6px 12px -6px rgb(16 24 40 / 0.08)',
      },
    },
  },
};
