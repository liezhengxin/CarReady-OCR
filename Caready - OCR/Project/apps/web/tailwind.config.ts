import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Grade colours are referenced by label from config/grading.yaml. Keyed
      // by the placeholder A-E scale; if Caready's real scale is numeric these
      // move with it (docs/OPEN_ITEMS.md #1).
      colors: {
        grade: {
          a: '#047857',
          b: '#65a30d',
          c: '#ca8a04',
          d: '#ea580c',
          e: '#b91c1c',
        },
      },
    },
  },
  plugins: [],
};

export default config;
