/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        fin: {
          bg: '#0a0d14',
          surface: '#10141f',
          card: '#151b2b',
          elevated: '#1a2236',
          border: 'rgba(255, 255, 255, 0.08)',
          text: '#f1f5f9',
          muted: '#94a3b8',
          dim: '#64748b',
          emerald: '#10b981',
          cyan: '#06b6d4',
          amber: '#f59e0b',
          coral: '#f43f5e',
          purple: '#a855f7',
        }
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ["'JetBrains Mono'", 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      }
    },
  },
  plugins: [],
}
