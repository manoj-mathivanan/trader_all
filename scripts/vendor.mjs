import { mkdir, copyFile } from 'node:fs/promises';
await mkdir('dashboard/web/vendor', { recursive: true });
await copyFile('node_modules/klinecharts/dist/umd/klinecharts.min.js', 'dashboard/web/vendor/klinecharts.min.js');
await copyFile('node_modules/klinecharts/LICENSE', 'dashboard/web/vendor/KLINECHARTS-LICENSE');
