import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans:    ['Akko Pro', 'system-ui', 'sans-serif'],
        display: ['Soho Pro', 'Georgia', 'serif'],
        mono:    ['JetBrains Mono', 'monospace'],
      },
      colors: {
        brand: {
          50:  '#e8f6fb',
          100: '#b3e6f5',
          200: '#7dd4e8',
          300: '#40bfda',
          400: '#00A1CD',   // CBS primary brand — "Chat"
          500: '#0580A1',   // CBS link / interactive
          600: '#005470',   // CBS dark teal — hover
          700: '#3d3b8a',   // mid purple
          800: '#271D6C',   // CBS heading purple — "Cijfers"
          900: '#091D23',   // CBS body text / darkest
          950: '#060f13',   // deepest dark
        },
        // CBS semantic aliases for direct use
        cbs: {
          text:       '#091D23',
          heading:    '#271D6C',
          link:       '#0580A1',
          brand:      '#00A1CD',
          secondary:  '#878787',
          border:     '#D2D2D2',
          bg:         '#E9E9E9',
          white:      '#FFFFFF',
        },
      },
      animation: {
        'fade-in':    'fadeIn 0.2s ease-out',
        'slide-up':   'slideUp 0.25s ease-out',
        'pulse-soft': 'pulseSoft 1.5s ease-in-out infinite',
        'dot-bounce': 'dotBounce 1.2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn:   { from: { opacity: '0' },                   to: { opacity: '1' } },
        slideUp:  { from: { opacity: '0', transform: 'translateY(8px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        pulseSoft:{ '0%,100%': { opacity: '1' },              '50%': { opacity: '0.5' } },
        dotBounce:{ '0%,80%,100%': { transform: 'scale(0)' }, '40%': { transform: 'scale(1)' } },
      },
    },
  },
  plugins: [],
} satisfies Config
