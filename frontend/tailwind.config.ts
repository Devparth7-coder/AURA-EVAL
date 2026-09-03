import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        base: { 950: '#07090d', 900: '#0b0e14', 850: '#0f131b', 800: '#141924', 700: '#1d2432' },
        line: '#222a38',
        accent: { DEFAULT: '#4f9cf9', soft: '#7fb8ff', dim: '#1e3a5f' },
        ok: '#3ecf8e',
        warn: '#f5a623',
        danger: '#f2555a',
        violet: '#a78bfa',
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      keyframes: {
        'fade-up': { '0%': { opacity: '0', transform: 'translateY(6px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        'pulse-ring': { '0%': { boxShadow: '0 0 0 0 rgba(79,156,249,0.35)' }, '70%': { boxShadow: '0 0 0 10px rgba(79,156,249,0)' }, '100%': { boxShadow: '0 0 0 0 rgba(79,156,249,0)' } },
        'flow-dash': { to: { strokeDashoffset: '-16' } },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
      },
      animation: {
        'fade-up': 'fade-up 0.35s ease-out both',
        'pulse-ring': 'pulse-ring 1.8s ease-out infinite',
        'flow-dash': 'flow-dash 0.7s linear infinite',
      },
    },
  },
  plugins: [],
};
export default config;
