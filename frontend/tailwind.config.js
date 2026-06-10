/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        ink: {
          900: '#1c1c1e',
          850: '#242427',
          800: '#2b2b2f',
          750: '#323237',
          700: '#3a3a40',
          650: '#22282e',
          600: '#4a535e',
          500: '#6e7880',
          400: '#939ca5',
          300: '#b4bcc4',
          200: '#d0d6dc',
          100: '#e8ebee',
          50:  '#f4f5f7',
        },
        up:   { DEFAULT: '#3ddc97', dim: '#1f8a5b', deep: '#0f3a2a', glow: 'rgba(61,220,151,0.18)' },
        down: { DEFAULT: '#ff5c6c', dim: '#b3303f', deep: '#3a1118', glow: 'rgba(255,92,108,0.18)' },
        warn: { DEFAULT: '#f5b942', dim: '#8a6418' },
        info: { DEFAULT: '#6ea8ff' },
        demo: { DEFAULT: '#a78bfa', dim: '#7c5cd6', deep: '#2a2150', glow: 'rgba(167,139,250,0.18)' },
      },
      boxShadow: {
        'inset-line': 'inset 0 -1px 0 0 rgba(255,255,255,0.04)',
      },
    },
  },
  plugins: [],
};
