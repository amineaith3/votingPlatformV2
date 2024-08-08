module.exports = {
  content: ['./templates/**/*.html'],
  theme: {
    extend: {
      backgroundImage: {
        'custom-grid': "linear-gradient(to right, #f0f0f0 1px, transparent 1px), linear-gradient(to bottom, #f0f0f0 1px, transparent 1px)",
        'custom-radial': "radial-gradient(circle 800px at 100% 200px, #d5c5ff, transparent)"
      },
      backgroundSize: {
        'custom-size': '6rem 4rem',
      },
    },
  },
  plugins: [],
}
