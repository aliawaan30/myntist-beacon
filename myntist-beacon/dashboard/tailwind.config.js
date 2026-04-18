/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          50: "#e8edf5",
          100: "#c5d0e6",
          200: "#9fb0d6",
          300: "#7990c6",
          400: "#5c78bb",
          500: "#3f60b0",
          600: "#1F3864",
          700: "#1a2f55",
          800: "#152646",
          900: "#0f1c38",
        },
      },
    },
  },
  plugins: [],
};
