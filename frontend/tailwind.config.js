/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        abyss: '#05070d',
        panel: '#0c111c',
        panel2: '#111827',
        line: 'rgba(148, 163, 184, 0.14)',
        cyan: { DEFAULT: '#22d3ee', glow: '#67e8f9' },
        violet: { DEFAULT: '#a78bfa' },
        amber: { DEFAULT: '#fbbf24' },
      },
      fontFamily: {
        display: ['Orbitron', 'Inter', 'sans-serif'],
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glow: '0 0 24px rgba(34, 211, 238, 0.25)',
        'glow-violet': '0 0 24px rgba(167, 139, 250, 0.25)',
        'glow-amber': '0 0 24px rgba(251, 191, 36, 0.25)',
      },
      keyframes: {
        'fade-up': { '0%': { opacity: 0, transform: 'translateY(8px)' }, '100%': { opacity: 1, transform: 'none' } },
        'banner': { '0%': { opacity: 0, transform: 'scale(0.9)' }, '15%': { opacity: 1, transform: 'scale(1)' }, '80%': { opacity: 1 }, '100%': { opacity: 0 } },
      },
      animation: {
        'fade-up': 'fade-up 0.35s ease-out both',
        banner: 'banner 2.6s ease-out both',
      },
    },
  },
  plugins: [],
};
