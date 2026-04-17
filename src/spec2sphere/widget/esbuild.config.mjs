import * as esbuild from 'esbuild';
import * as fs from 'node:fs';
import * as crypto from 'node:crypto';
import * as zlib from 'node:zlib';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

await esbuild.build({
  entryPoints: ['src/main.ts'],
  bundle: true,
  minify: true,
  sourcemap: true,
  target: 'es2020',
  format: 'iife',
  globalName: 'Spec2SphereWidget',
  outfile: 'dist/main.js',
});

// Read built bundle
const bundleBytes = fs.readFileSync(path.join(__dirname, 'dist/main.js'));

// Compute sha384 integrity
const hash = crypto.createHash('sha384').update(bundleBytes).digest('base64');
const integrity = `sha384-${hash}`;

// Size guard — must be < 50 KB gzipped
const gzipped = zlib.gzipSync(bundleBytes);
const gzipSizeKb = (gzipped.length / 1024).toFixed(1);

if (gzipped.length > 50 * 1024) {
  console.error(
    `ERROR: gzipped widget size ${gzipSizeKb}KB exceeds 50KB limit. Reduce bundle size.`,
  );
  process.exit(1);
}

// Write manifest.json from template
const templatePath = path.join(__dirname, 'manifest.template.json');
const template = fs.readFileSync(templatePath, 'utf8');
const manifest = template.replace('{{INTEGRITY}}', integrity);
fs.mkdirSync(path.join(__dirname, 'dist'), { recursive: true });
fs.writeFileSync(path.join(__dirname, 'dist/manifest.json'), manifest, 'utf8');

console.log(`widget bundled, integrity: ${integrity} gzip=${gzipSizeKb}kb`);
