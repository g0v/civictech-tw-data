#!/usr/bin/env node
/**
 * 掃 data/v0/{dataset}/{table}.json，重建 data/index.json。
 *
 * 為什麼不讓各同步腳本自己寫 index：資料集不只一個來源（Airtable、Google Sheet），
 * 誰最後寫誰就蓋掉別人的條目。改成看「磁碟上實際有什麼」，index 永遠跟端點一致。
 *
 * 用法：node scripts/build-index.mjs（sync.mjs 與 sync-aimonday.mjs 結尾都會呼叫）
 */

import { readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const VERSION = 'v0';

// 排序沿用上一版 index.json：同樣的資料重跑不該產生 diff。新出現的資料集／表排在最後。
// 這只決定順序，不是白名單——舊 index 沒有的照樣收。
async function previousOrder() {
  try {
    const prev = JSON.parse(await readFile(path.join(ROOT, 'data', 'index.json'), 'utf8'));
    return prev.datasets.flatMap((d) => [d.slug, ...d.tables.map((t) => `${d.slug}/${t.slug}`)]);
  } catch {
    return [];
  }
}

export async function buildIndex() {
  const order = await previousOrder();
  const rank = (key) => (order.includes(key) ? order.indexOf(key) : order.length);
  const base = path.join(ROOT, 'data', VERSION);
  const datasets = [];
  const dirs = (await readdir(base, { withFileTypes: true })).filter((d) => d.isDirectory());
  for (const dir of dirs) {
    let dsIndex = null;
    const files = (await readdir(path.join(base, dir.name))).filter((f) => f.endsWith('.json')).sort();
    for (const f of files) {
      const out = JSON.parse(await readFile(path.join(base, dir.name, f), 'utf8'));
      if (!out.dataset || !out.table) continue; // report.json 這類非端點檔
      dsIndex ??= { slug: out.dataset.slug, name: out.dataset.name, label: out.dataset.label, tables: [] };
      dsIndex.tables.push({
        slug: out.table.slug,
        name: out.table.name,
        label: out.table.label,
        recordCount: out.recordCount,
        path: `${VERSION}/${dir.name}/${f}`,
      });
    }
    if (!dsIndex) continue;
    const ds = dsIndex.slug;
    dsIndex.tables.sort((a, b) => rank(`${ds}/${a.slug}`) - rank(`${ds}/${b.slug}`) || a.slug.localeCompare(b.slug));
    datasets.push(dsIndex);
  }
  datasets.sort((a, b) => rank(a.slug) - rank(b.slug) || a.slug.localeCompare(b.slug));

  const index = { version: VERSION, license: 'CC BY 4.0', attribution: 'g0v civictech.tw', datasets };
  await writeFile(path.join(ROOT, 'data', 'index.json'), JSON.stringify(index, null, 2) + '\n');
  return index;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const index = await buildIndex();
  console.log(`index.json：${index.datasets.map((d) => `${d.slug}(${d.tables.length})`).join('、')}`);
}
