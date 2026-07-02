/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg:      '#0f1117',
        card:    '#1a1d2e',
        border:  '#2d3748',
        up:      '#48bb78',
        down:    '#fc8181',
        blue:    '#4299e1',
        purple:  '#b794f4',
        orange:  '#f6ad55',
      },
    },
  },
  plugins: [],
}
