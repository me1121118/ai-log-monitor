const esbuild = require('esbuild');

esbuild.buildSync({
  entryPoints: ['src/index.jsx'],
  bundle: true,
  minify: true,
  outfile: '../server/server/app/static/js/er-flow.bundle.js',
  define: { 'process.env.NODE_ENV': '"production"' },
});
console.log('Built er-flow.bundle.js + er-flow.bundle.css successfully');
