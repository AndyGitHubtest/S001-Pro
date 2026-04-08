/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 背景色
        'bg-primary': '#0B0E11',
        'bg-secondary': '#151A21',
        'bg-tertiary': '#1C2128',
        
        // 文字色
        'text-primary': '#FFFFFF',
        'text-secondary': '#A0AEC0',
        'text-muted': '#64748B',
        
        // 功能色
        'up': '#00C853',
        'down': '#FF5252',
        'warning': '#FFB300',
        'info': '#448AFF',
        
        // 边框
        'border': '#2D3748',
      },
      fontFamily: {
        'mono': ['Roboto Mono', 'monospace'],
        'sans': ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
