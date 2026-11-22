// Builds the website (`dist/`) and makes it installable on a phone's home screen.
//
//   npm run build:web
//
// 1. `expo export -p web` with an empty API address, so the app calls the address it was opened
//    from (the API serves the website itself; see PHARMAVIQUE_WEB_DIR).
// 2. The exported index.html has no manifest, no home-screen icon, an English left-to-right page
//    and a zoomable viewport; this adds what a phone needs. The icons and the manifest are in
//    `public/`, which the export copies into `dist/`.
import { execSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';

execSync('npx expo export -p web --output-dir dist', {
  stdio: 'inherit',
  env: { ...process.env, EXPO_PUBLIC_API_URL: '' },
});

const HEAD = `
    <meta name="theme-color" content="#F5F9F8" />
    <meta name="color-scheme" content="light" />
    <meta name="mobile-web-app-capable" content="yes" />
    <meta name="apple-mobile-web-app-capable" content="yes" />
    <meta name="apple-mobile-web-app-status-bar-style" content="default" />
    <meta name="apple-mobile-web-app-title" content="Pharmavique" />
    <meta name="format-detection" content="telephone=no" />
    <meta name="description" content="معلومات الأدوية من سجل هيئة الغذاء والدواء. للاطلاع فقط وليست نصيحة طبية." />
    <link rel="manifest" href="/manifest.webmanifest" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
    <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />
    <style id="pharmavique-page">
      html, body { background: #F5F9F8; overscroll-behavior: none; -webkit-text-size-adjust: 100%; }
    </style>
`;

const file = 'dist/index.html';
let html = readFileSync(file, 'utf8');
html = html.replace('<html lang="en">', '<html lang="ar" dir="rtl">');
html = html.replace(
  /<meta name="viewport"[^>]*>/,
  '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover" />',
);
html = html.replace('</head>', `${HEAD}  </head>`);
if (!html.includes('rel="manifest"') || !html.includes('dir="rtl"')) {
  throw new Error('index.html was not patched: the export format changed');
}
writeFileSync(file, html);
console.log('dist/index.html patched for the home screen');
