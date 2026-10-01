#!/usr/bin/env node
/**
 * Airtable → 靜態 JSON API 匯出腳本
 *
 * 從兩個 Airtable base 抓取資料表，輸出成公開端點需要的靜態 JSON（data/v0/）。
 * 匯出檔內不含時間戳，資料無變動時重跑不會產生 diff；
 * 「最後更新時間」以 git commit 歷史為準。
 *
 * 用法：
 *   AIRTABLE_PAT=patXXX node scripts/sync.mjs
 *   （本地開發可將 PAT 放在 .env，見 README）
 *
 * PAT 只需唯讀 scope：data.records:read + schema.bases:read
 *
 * ── 為什麼路徑長這樣（2026-09-17 定）────────────────────────────────
 * 端點格式：data.civictech.tw/v0/{dataset}/{table}.json
 *
 *   v0        Airtable 欄位改名是常態，schema 現在給不起穩定承諾。
 *             v0 是約定俗成的「這還會變」訊號，比假裝 v1 誠實。
 *   dataset   tech / science —— 這是兩份資料集真正的差別，
 *             不是 Airtable 的 base 名稱。不把內部結構洩漏成公開介面。
 *   table     ASCII slug。中文表名留在 index.json 當標籤：
 *             機器讀路徑，人讀 index。原本的中文檔名有 16/18 個
 *             需要 URL 編碼，貼進文件會斷、唸也唸不出來。
 * ───────────────────────────────────────────────────────────────
 */

import { mkdir, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const VERSION = 'v0';
const OUT_DIR = path.join(ROOT, 'data', VERSION);

const PAT = process.env.AIRTABLE_PAT;
if (!PAT) {
  console.error('缺少 AIRTABLE_PAT 環境變數（唯讀 scope 即可）');
  process.exit(1);
}

/**
 * 要匯出的 base，以及它在公開路徑上的樣子。
 * tables 是「表名 → 公開 slug」的對照。
 *
 * ⚠️ 這是白名單，而白名單會兩個方向靜默失效（見 civictech.tw 的
 *    KnowHow.astro categoriesOrder，2026-08-15 踩過）：
 *    表加了沒補進來 → 靜靜不匯出；表刪了沒拿掉 → 留一個空端點。
 *    所以下面兩種情況都會讓匯出**直接失敗**，不會安靜跳過。
 */
const DATASETS = [
  {
    id: 'app2R1DOrrO9iysOr',
    slug: 'tech',
    name: 'civic tech project database',
    label: '公民科技專案資料庫',
    tables: {
      'project list': { slug: 'projects', label: '公民科技專案' },
      影響力類別: { slug: 'categories', label: '影響力類別（SDGs）' },
      標籤: { slug: 'tags', label: '標籤' },
      presentation: { slug: 'talks', label: '專案發表紀錄' },
    },
  },
  {
    id: 'appAilQ8XpcZkvBko',
    slug: 'science',
    name: '公民科學與群眾參與計畫清冊資料集',
    label: '公民科學與群眾參與計畫',
    tables: {
      公民科學與群眾參與計畫: { slug: 'programs', label: '公民科學與群眾參與計畫' },
      '[持續整理] 文獻、研究成果、文章': { slug: 'papers', label: '文獻、研究成果、文章' },
      機構與單位: { slug: 'orgs', label: '機構與單位' },
      類別: { slug: 'categories', label: '類別' },
      縣市: { slug: 'counties', label: '縣市' },
      行政區: { slug: 'districts', label: '行政區' },
      數據資料彙整方案或平台: { slug: 'platforms', label: '數據資料彙整方案或平台' },
      禮品與獎勵: { slug: 'rewards', label: '禮品與獎勵' },
      設備器材: { slug: 'equipment', label: '設備器材' },
      計畫執行的時段或時節: { slug: 'seasons', label: '計畫執行的時段或時節' },
      國際地區: { slug: 'regions', label: '國際地區' },
      文獻或知識素材類型: { slug: 'material-types', label: '文獻或知識素材類型' },
      演算或分析方案: { slug: 'methods', label: '演算或分析方案' },
      '中正社區大學-學群主題': { slug: 'ccu-topics', label: '中正社區大學學群主題' },
    },
  },
];

/**
 * 不匯出的表（內部工作性質）。這些不列進 DATASETS.tables 也不會報錯。
 *
 * `[空白N]` 是 Airtable 內建範本表（Name/Notes/Assignee/Status/Attachments），
 * 用型樣比對而不是一個一個列，否則哪天多一個 [空白6] 就又要來改一次。
 * ⚠️ 它的 Assignee 是 singleCollaborator——會帶出人名與 email，
 *    現在是空的，但這正是不能讓這種表流出去的理由。
 *
 * `修改建議` 是網站專案頁的「建議修改」表單寫入的地方，有填寫者自留的聯絡 email，
 * 而且內容是未經審核的投稿——不是資料本身，不能流出去。
 *
 * 另外，**完全沒有內容的表也會自動排除**（依內容判斷，不依名字）。
 */
const EXCLUDE_TABLE_NAMES = new Set(['[工作文件]', '【工作區】', '修改建議']);
const EXCLUDE_TABLE_PATTERNS = [/^\[空白\d*\]$/];
const isExcludedTable = (name) =>
  EXCLUDE_TABLE_NAMES.has(name) || EXCLUDE_TABLE_PATTERNS.some((re) => re.test(name));

/** 不匯出的欄位（個人聯絡資料），key 為表名 */
const EXCLUDE_FIELDS = {
  'project list': new Set(['name', 'slack id']),
  presentation: new Set(['owner name', 'facebook', 'slack id', 'email', 'telegram']),
};

/**
 * 已人工檢視、決定保留的個資（`recordId|欄位名`）。
 *
 * 這四筆都是專案**自己對外公告的聯絡管道**（實驗室信箱、團隊信箱、洽詢電話），
 * 砍掉會傷到「怎麼聯絡這個專案」這個正當用途，所以留。
 * 掃描掃到不在這張表上的 → 匯出失敗，逼人看過再決定。
 *
 * 為什麼要有這道：EXCLUDE_FIELDS 是依欄位名的黑名單，
 * 而真正的個資躲在自由文字的「描述」裡——欄位名比對結構上抓不到。
 */
const PII_REVIEWED = new Set([
  'recQv1piWBiGDazRW|描述', // 米爾頓釉小蜂寄主植物調查：中興大學昆蟲系公開信箱
  'recd1WOZYOT7BuFHd|描述', // 合境平安：GeoNight@Taiwan 團隊公開信箱
  'recNiPhjN7ILySUa4|描述', // 蘭陽鰭跡：研海團隊公開信箱
  'rectJYAfvEfAiJH6D|描述', // 大翅鯨回報：生態主意有限公司洽詢電話
]);

const EMAIL_RE = /[\w.+-]+@[\w-]+\.[\w.]{2,}/;
const PHONE_RE = /\b09\d{2}[-\s]?\d{3}[-\s]?\d{3}\b|\b0[2-8][-\s]?\d{6,8}\b/;

/** 掃一個字串裡的 email／電話。跳過網址與百分比編碼——DOI 與網址路徑會誤判成電話。 */
function findPII(value) {
  const hits = [];
  for (const token of String(value).split(/\s+/)) {
    if (/https?:\/\//.test(token) || token.includes('%') || /doi\.org/.test(token)) continue;
    if (EMAIL_RE.test(token)) hits.push('email');
    else if (PHONE_RE.test(token)) hits.push('phone');
  }
  return hits;
}

/**
 * Airtable 自己算出來的欄位。空白列上它們照樣有值（count 是 0），
 * 所以判斷「這列是不是空的」時不能算進去。
 */
const COMPUTED_FIELD_TYPES = new Set([
  'count', 'formula', 'rollup', 'multipleLookupValues', 'autoNumber',
  'createdTime', 'lastModifiedTime', 'createdBy', 'lastModifiedBy', 'button',
]);

/**
 * 這一列有沒有人填過東西。
 *
 * 只看「欄位數 > 0」不夠：science 那邊有三種空白列會漏過去——
 *   主欄位被整批填成 `[空白列]`（orgs 3105 筆裡 3036 筆是這種）、
 *   只剩 count 欄位的 0（categories 575 筆裡 497 筆）、
 *   文字欄只有換行。
 */
function isBlankRecord(rec, table) {
  const typeOf = Object.fromEntries(table.fields.map((f) => [f.name, f.type]));
  return Object.entries(rec.fields).every(([key, value]) => {
    if (COMPUTED_FIELD_TYPES.has(typeOf[key])) return true;
    if (value == null) return true;
    if (Array.isArray(value)) return value.length === 0;
    if (typeof value === 'string') return /^\s*(\[空白[^\]]*\])?\s*$/.test(value);
    return false;
  });
}

const API = 'https://api.airtable.com/v0';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function apiGet(url) {
  for (let attempt = 1; attempt <= 5; attempt++) {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${PAT}` } });
    if (res.status === 429) {
      console.warn(`  rate limited，第 ${attempt} 次，等待重試…`);
      await sleep(30_000);
      continue;
    }
    if (!res.ok) throw new Error(`Airtable API ${res.status} ${res.statusText}：${url}`);
    return res.json();
  }
  throw new Error(`重試多次仍失敗：${url}`);
}

function fetchSchema(baseId) {
  return apiGet(`${API}/meta/bases/${baseId}/tables`);
}

async function fetchAllRecords(baseId, tableId) {
  const records = [];
  let offset;
  do {
    const u = new URL(`${API}/${baseId}/${tableId}`);
    u.searchParams.set('pageSize', '100');
    u.searchParams.set('returnFieldsByFieldId', 'false');
    if (offset) u.searchParams.set('offset', offset);
    const page = await apiGet(u);
    records.push(...page.records);
    offset = page.offset;
    await sleep(250); // 控制在 5 req/s 限制內
  } while (offset);
  return records;
}

async function main() {
  const index = {
    version: VERSION,
    license: 'CC BY 4.0',
    attribution: 'g0v civictech.tw',
    datasets: [],
  };
  const piiFindings = [];

  await rm(OUT_DIR, { recursive: true, force: true });

  for (const ds of DATASETS) {
    console.log(`\n=== ${ds.label}（${ds.id}）→ /${VERSION}/${ds.slug}/ ===`);
    const { tables } = await fetchSchema(ds.id);

    // 先抓齊所有表，才能展開跨表關聯（含不匯出的表，關聯名稱可能指向它們）
    const recordsByTable = {};
    for (const table of tables) {
      console.log(`抓取 ${table.name}…`);
      recordsByTable[table.id] = await fetchAllRecords(ds.id, table.id);
      console.log(`  ${recordsByTable[table.id].length} 筆`);
    }

    const primaryValueById = {};
    for (const table of tables) {
      const primaryField = table.fields.find((f) => f.id === table.primaryFieldId);
      for (const rec of recordsByTable[table.id]) {
        primaryValueById[rec.id] = rec.fields[primaryField.name] ?? null;
      }
    }

    // 完全沒有內容的表（Airtable 預開的 [空白N] 之類）自動排除。
    // 依「有沒有內容」判斷而不是依名字，否則就是再造一個會腐爛的白名單。
    const emptyTables = tables
      .filter((t) => recordsByTable[t.id].every((r) => Object.keys(r.fields).length === 0))
      .map((t) => t.name);
    for (const n of emptyTables) console.log(`略過全空的表 ${n}`);

    // ── 白名單對帳：有內容卻沒對照 → 炸。不准安靜跳過 ──
    const live = tables
      .map((t) => t.name)
      .filter((n) => !isExcludedTable(n) && !emptyTables.includes(n));
    const mapped = Object.keys(ds.tables);
    const unmapped = live.filter((n) => !mapped.includes(n));
    const stale = mapped.filter((n) => !live.includes(n));
    if (unmapped.length || stale.length) {
      console.error(`\n✗ ${ds.slug}：DATASETS 的表對照與 Airtable 不一致`);
      if (unmapped.length)
        console.error(`   Airtable 有、對照表沒有（會靜靜不匯出）：${unmapped.join('、')}`);
      if (stale.length)
        console.error(`   對照表有、Airtable 沒有（會留一個空端點）：${stale.join('、')}`);
      console.error(`   → 補進 scripts/sync.mjs 的 DATASETS，或確認該表是否該排除。`);
      process.exit(1);
    }

    const dsDir = path.join(OUT_DIR, ds.slug);
    await mkdir(dsDir, { recursive: true });

    const dsIndex = { slug: ds.slug, name: ds.name, label: ds.label, tables: [] };
    for (const table of tables) {
      if (isExcludedTable(table.name) || emptyTables.includes(table.name)) continue;
      const meta = ds.tables[table.name];
      const excludeFields = EXCLUDE_FIELDS[table.name] ?? new Set();

      const records = recordsByTable[table.id]
        // Airtable 預開的空白列不匯出：原本 898 筆裡有 686 筆是空的，
        // 消費者會以為有 898 個專案。關聯展開已用上面的 primaryValueById，
        // 先建後濾，所以丟掉空列不影響關聯名稱。
        .filter((rec) => !isBlankRecord(rec, table))
        .map((rec) => {
          const fields = {};
          for (const [key, value] of Object.entries(rec.fields)) {
            if (excludeFields.has(key)) continue;
            fields[key] = linkNames(table).has(key)
              ? value.map((id) => ({ id, name: primaryValueById[id] ?? null }))
              : value;
            if (typeof value === 'string') {
              const kinds = findPII(value);
              if (kinds.length && !PII_REVIEWED.has(`${rec.id}|${key}`)) {
                piiFindings.push({
                  path: `${VERSION}/${ds.slug}/${meta.slug}.json`,
                  record: rec.id,
                  field: key,
                  kinds: [...new Set(kinds)].join('/'),
                  name: primaryValueById[rec.id] ?? '(無名稱)',
                });
              }
            }
          }
          return { id: rec.id, createdTime: rec.createdTime, fields };
        })
        .sort((a, b) =>
          a.createdTime === b.createdTime
            ? a.id.localeCompare(b.id)
            : a.createdTime.localeCompare(b.createdTime),
        );

      const out = {
        version: VERSION,
        dataset: { slug: ds.slug, name: ds.name, label: ds.label },
        table: { slug: meta.slug, name: table.name, label: meta.label, id: table.id },
        recordCount: records.length,
        fields: table.fields
          .filter((f) => !excludeFields.has(f.name))
          .map((f) => ({ id: f.id, name: f.name, type: f.type })),
        records,
      };
      await writeFile(
        path.join(dsDir, `${meta.slug}.json`),
        JSON.stringify(out, null, 2) + '\n',
      );

      dsIndex.tables.push({
        slug: meta.slug,
        name: table.name,
        label: meta.label,
        recordCount: records.length,
        path: `${VERSION}/${ds.slug}/${meta.slug}.json`,
      });
      console.log(`寫出 ${VERSION}/${ds.slug}/${meta.slug}.json（${records.length} 筆）`);
    }
    index.datasets.push(dsIndex);
  }

  // ── 個資閘門：新的個資一定要有人看過才放行 ──
  if (piiFindings.length) {
    console.error(`\n✗ 掃到 ${piiFindings.length} 筆未經檢視的個人聯絡資料：\n`);
    for (const f of piiFindings) {
      console.error(`   ${f.path}`);
      console.error(`     ${f.name}（${f.record}）欄位「${f.field}」→ ${f.kinds}`);
      console.error(`     若確認可公開，加入 PII_REVIEWED：'${f.record}|${f.field}'\n`);
    }
    console.error('   這些躲在自由文字裡，EXCLUDE_FIELDS 抓不到。人看過再決定留或刪。');
    process.exit(1);
  }

  await writeFile(
    path.join(ROOT, 'data', 'index.json'),
    JSON.stringify(index, null, 2) + '\n',
  );
  console.log(`\n完成。索引 data/index.json，端點 /${VERSION}/{dataset}/{table}.json`);
}

/** 快取每張表的關聯欄位名 */
const _linkCache = new Map();
function linkNames(table) {
  if (!_linkCache.has(table.id)) {
    _linkCache.set(
      table.id,
      new Set(table.fields.filter((f) => f.type === 'multipleRecordLinks').map((f) => f.name)),
    );
  }
  return _linkCache.get(table.id);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
