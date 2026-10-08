#!/usr/bin/env node
// AI Monday 講題紀錄：Google Sheet（揪松團維護）→ 靜態 JSON
//
// 讀三張表中的兩張：「場次」「講題」。「場次查詢」是給人看的，不讀。
// 輸出 data/v0/aimonday/{events,talks}.json，警告與錯誤寫到 reports/aimonday.json（不對外發布）。
// 有 error 就不動 data/、exit 1——寧可讓排程亮紅燈，也不要拿壞資料蓋掉昨天的好資料。
//
// 用法：node scripts/sync-aimonday.mjs（不需要 token，Sheet 是「知道連結者可檢視」）
// sync.mjs 結尾也會呼叫它。

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildIndex } from './build-index.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const SHEET_ID = '1y9RLwi-O040_NhvmGpuEhXXPSvsbgbHWgiAmIioI6i0';
const GIDS = { events: '1021523876', talks: '2123466296' };
const OUT_DIR = path.join(ROOT, 'data', 'v0', 'aimonday');
const REPORT = path.join(ROOT, 'reports', 'aimonday.json');

// 欄名 → 內部名稱。左邊必須和 Sheet 第一列一字不差；Sheet 多出的欄位不讀（例如「線上會議網址」「備註」）。
const EVENT_COLS = {
  場次: 'key', 日期: 'date', 系列: 'series', 場次主題: 'theme', 狀態: 'status',
  開始時間: 'start_time', 結束時間: 'end_time', 形式: 'format', 地點: 'venue', 共筆: 'notes_url',
  宣傳: 'promotions', 贊助: 'sponsor',
};
const TALK_COLS = {
  場次: 'event_key', 講者: 'speakers', 講者單位: 'affiliations', 講者網址: 'speaker_urls',
  講題: 'title', 簡介: 'description', 時間長度: 'duration_min', 簡報: 'slides_url',
  影片: 'video', 關鍵字: 'keywords', 影像授權: 'license',
};

const SERIES_SLUG = { 'AI Monday': 'ai-monday', 'g0v 國會松': 'congressthon', COSCUP: 'coscup' };
const EVENT_STATUS = ['已完成', '已排定', '邀約中', '停辦'];
// 這兩種狀態代表時間已經談定：開始與結束時間必填（網站的日曆與 .ics 靠它）。
// 缺了只發警告、照樣輸出，不讓一格漏填擋住整份資料更新；網站會把這場排除在 .ics 外，
// 並由 AI-Monday repo 的每日建置讀公開的 report.json、開 issue 通知維護者。
const TIME_REQUIRED = ['已完成', '已排定'];
const FORMATS = ['線上', '實體', '混合'];
const LICENSES = { 'CC-BY': 'CC-BY', 'CC-BY-ND': 'CC-BY-ND', 'CC-BY-SA': 'CC-BY-SA' };
const LICENSE_PENDING = ['待詢問', '待確認'];
// 揪松團「確定沒有錄影」的寫法。影片欄與授權欄都可能出現，等同留空，不警告
const NO_VIDEO = ['X', '無', '無錄影', '無影片'];
const isNoVideo = (s) => NO_VIDEO.includes(s.trim().toUpperCase());

const errors = [];
const warnings = [];
// notices：照慣例填的、不是錯，例如還沒邀到講者時講題欄寫「再請 X 提供」。只記錄，不通知
const notices = [];
const warn = (where, msg) => { if (!warnings.some((w) => w.where === where && w.msg === msg)) warnings.push({ where, msg }); };
const fail = (where, msg) => errors.push({ where, msg });

// ---------- CSV ----------

// RFC 4180：引號內可含逗號與換行，"" 是跳脫的引號。
function parseCsv(text) {
  const rows = [];
  let row = [], field = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') q = false;
      else field += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field); rows.push(row); row = []; field = '';
    } else field += c;
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  return rows;
}

async function fetchTable(gid, cols, name) {
  const url = `https://docs.google.com/spreadsheets/d/${SHEET_ID}/export?format=csv&gid=${gid}`;
  const res = await fetch(url, { redirect: 'follow' });
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
  const text = await res.text();
  if (text.trimStart().startsWith('<')) throw new Error(`${name}: 拿到 HTML 不是 CSV（Sheet 是否改成不公開？）`);
  const [header, ...body] = parseCsv(text);
  const idx = {};
  for (const [label, key] of Object.entries(cols)) {
    const i = header.findIndex((h) => h.replace(/\s+/g, '') === label);
    if (i === -1) fail(name, `找不到欄位「${label}」。現有欄位：${header.join('、')}`);
    idx[key] = i;
  }
  return body
    .map((cells, n) => {
      const r = { _row: n + 2 };
      for (const [key, i] of Object.entries(idx)) // 只削行尾與頭尾空白，不削開頭的換行：多行欄位靠行序對齊，開頭的空行代表「第一位沒有值」
      r[key] = i >= 0 ? (cells[i] ?? '').replace(/^[ \t\u3000]+|\s+$/g, '') : '';
      return r;
    });
}

// ---------- 欄位解析 ----------

const lines = (s) => s.split('\n').map((x) => x.trim());
const orNull = (s) => (s == null || s.trim() === '' ? null : s.trim());
const isUrl = (s) => /^https?:\/\/\S+$/.test(s);
const URL_IN_TEXT = /https?:\/\/\S+/;

function parseDate(s, where) {
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) { fail(where, `日期看不懂：「${s}」`); return null; }
  const d = new Date(`${m[0]}T00:00:00Z`);
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== m[0]) { fail(where, `不存在的日期：「${m[0]}」`); return null; }
  return m[0];
}

function parseTime(s, where, label) {
  if (!s) return null;
  const m = s.match(/^(\d{1,2}):(\d{2})/);
  if (!m || Number(m[1]) > 23 || Number(m[2]) > 59) { warn(where, `${label}看不懂：「${s}」`); return null; }
  return `${m[1].padStart(2, '0')}:${m[2]}`;
}

// 「宣傳」：每則以 "- " 開頭；沒有 "- " 的行併回上一則。
function parsePromotions(s) {
  if (!s) return [];
  const items = [];
  for (const line of lines(s)) {
    if (!line) continue;
    if (line.startsWith('- ') || line.startsWith('-')) items.push(line.replace(/^-\s*/, ''));
    else if (items.length) items[items.length - 1] += `\n${line}`;
    else items.push(line);
  }
  return items.map((text) => ({ text, urls: text.match(/https?:\/\/\S+/g) ?? [] }));
}

// 講者／單位／網址：一人一行、行序對齊。單位或網址只有一行時套用到所有人。
function parseSpeakers(r, where) {
  if (!r.speakers.trim()) return [];
  const names = lines(r.speakers).filter(Boolean);
  const pick = (col, label) => {
    if (!r[col]) return names.map(() => null);
    const vs = lines(r[col]);
    while (vs.length > names.length && vs.at(-1) === '') vs.pop();
    if (vs.length === 1) return names.map(() => orNull(vs[0]));
    if (vs.length !== names.length) warn(where, `${label}有 ${vs.length} 行，講者有 ${names.length} 位，對不齊`);
    return names.map((_, i) => orNull(vs[i] ?? '') === '-' ? null : orNull(vs[i] ?? ''));
  };
  const affs = pick('affiliations', '講者單位');
  const urls = pick('speaker_urls', '講者網址');
  return names.map((name, i) => {
    let affiliation = affs[i], url = urls[i], affiliationUrl = null;
    // 單位欄可以帶單位官網（「CONSUL DEMOCRACY https://…」）：拆成單位名稱與單位連結。
    // 它是單位的網址，不是講者個人的，所以不併進講者網址
    if (affiliation && URL_IN_TEXT.test(affiliation)) {
      affiliationUrl = affiliation.match(URL_IN_TEXT)[0];
      affiliation = orNull(affiliation.replace(affiliationUrl, '').trim());
    }
    if (url && !isUrl(url)) { warn(where, `講者網址不是網址：「${url}」`); url = null; }
    return { name, affiliation, affiliation_url: affiliationUrl, url };
  });
}

// YouTube：youtu.be/ID、youtube.com/watch?v=ID；t=1213 或 t=1h2m3s。追蹤參數 si 丟掉。
function parseVideo(s, where) {
  if (!s || isNoVideo(s)) return null;
  let u;
  try { u = new URL(s); } catch { warn(where, `影片欄不是網址：「${s}」，視為沒有影片`); return null; }
  let id = null;
  if (u.hostname === 'youtu.be') id = u.pathname.slice(1);
  else if (/(^|\.)youtube\.com$/.test(u.hostname)) id = u.searchParams.get('v') ?? u.pathname.match(/^\/(?:live|embed|shorts)\/([\w-]+)/)?.[1];
  if (!id || !/^[\w-]{11}$/.test(id)) { warn(where, `認不出 YouTube 影片 ID：「${s}」`); return { url: s, youtube_id: null, start_sec: 0 }; }
  const t = u.searchParams.get('t') ?? u.searchParams.get('start') ?? '0';
  const hms = t.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$/);
  const start = hms ? (+(hms[1] ?? 0)) * 3600 + (+(hms[2] ?? 0)) * 60 + (+(hms[3] ?? 0)) : 0;
  const clean = `https://www.youtube.com/watch?v=${id}${start ? `&t=${start}s` : ''}`;
  return { url: clean, youtube_id: id, start_sec: start };
}

function parseLicense(s, hasVideo, where) {
  if (!s || isNoVideo(s)) return { license: null, license_status: hasVideo ? 'unknown' : null };
  const norm = s.toUpperCase().replace(/\s+/g, '');
  if (LICENSES[norm]) return { license: LICENSES[norm], license_status: 'confirmed' };
  if (LICENSE_PENDING.includes(s)) return { license: null, license_status: 'pending' };
  warn(where, `授權看不懂：「${s}」`);
  return { license: null, license_status: 'unknown' };
}

// ---------- 主流程 ----------

const slugify = (series) => SERIES_SLUG[series] ?? series.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

const [eventRows, talkRows] = await Promise.all([
  fetchTable(GIDS.events, EVENT_COLS, '場次'),
  fetchTable(GIDS.talks, TALK_COLS, '講題'),
]);

const events = [];
const byKey = new Map();
for (const r of eventRows) {
  if (!r.key && !r.date) continue;
  const where = `場次 第 ${r._row} 列`;
  const date = parseDate(r.date, where);
  if (!date) continue;
  if (!r.series) fail(where, '系列是空的');
  const id = `${date}-${slugify(r.series)}`;
  if (byKey.has(r.key)) { fail(where, `場次「${r.key}」重複`); continue; }
  if (events.some((e) => e.id === id)) { fail(where, `同一天同一系列有兩場（${id}）`); continue; }
  if (r.status && !EVENT_STATUS.includes(r.status)) warn(where, `狀態看不懂：「${r.status}」`);
  if (r.format && !FORMATS.includes(r.format)) warn(where, `形式看不懂：「${r.format}」`);
  if (r.notes_url && !isUrl(r.notes_url)) warn(where, `共筆不是網址：「${r.notes_url}」`);
  const start = parseTime(r.start_time, where, '開始時間');
  const end = parseTime(r.end_time, where, '結束時間');
  if (TIME_REQUIRED.includes(r.status)) {
    if (!start) warn(where, `狀態是「${r.status}」，開始時間必填（這場先不放進訂閱日曆）`);
    if (!end) warn(where, `狀態是「${r.status}」，結束時間必填（這場先不放進訂閱日曆）`);
  }
  let endOk = end;
  if (start && end && end <= start) { warn(where, `結束時間（${end}）沒有晚於開始時間（${start}），視為沒填`); endOk = null; }
  if (end && !start) warn(where, '有結束時間但沒有開始時間');
  const ev = {
    id, date,
    weekday: '日一二三四五六'[new Date(`${date}T00:00:00Z`).getUTCDay()],
    series: r.series, series_slug: slugify(r.series),
    theme: orNull(r.theme), status: orNull(r.status),
    start_time: start, end_time: endOk, format: orNull(r.format), venue: orNull(r.venue),
    notes_url: orNull(r.notes_url), sponsor: orNull(r.sponsor),
    promotions: parsePromotions(r.promotions),
    talk_ids: [],
  };
  events.push(ev);
  byKey.set(r.key, ev);
}

const talks = [];
for (const r of talkRows) {
  if (!r.event_key) {
    if (Object.values(r).some((v) => v && typeof v === 'string')) warn(`講題 第 ${r._row} 列`, '沒有選場次，略過');
    continue;
  }
  const where = `講題 第 ${r._row} 列（${r.event_key}）`;
  const ev = byKey.get(r.event_key);
  if (!ev) { fail(where, `場次「${r.event_key}」在「場次」表裡找不到`); continue; }

  let title = orNull(r.title);
  if (title && /^再請/.test(title)) { notices.push({ where, msg: `講題欄放的是內部提示，不輸出：「${title}」` }); title = null; }
  const isQa = title?.toUpperCase() === 'QA';

  let slides = orNull(r.slides_url);
  if (slides && slides === ev.notes_url) slides = null; // 場次共筆被重複貼在講題列：不算投影片
  else if (slides && !isUrl(slides)) { warn(where, `簡報不是網址：「${slides}」`); slides = null; }

  let duration = null;
  if (r.duration_min) {
    duration = Number(r.duration_min);
    if (!Number.isFinite(duration) || duration <= 0) { warn(where, `時間長度不是正數：「${r.duration_min}」`); duration = null; }
  }

  const video = parseVideo(r.video, where);
  const speakers = parseSpeakers(r, where);
  const order = ev.talk_ids.length + 1;
  const t = {
    id: `${ev.id}-${order}`,
    event_id: ev.id,
    order,
    kind: isQa ? 'qa' : 'talk',
    title: isQa ? 'QA' : title,
    description: orNull(r.description),
    speakers,
    open_slot: !isQa && !title && speakers.length === 0,
    duration_min: duration,
    slides_url: slides,
    video,
    keywords: r.keywords ? r.keywords.split(/[、,，]/).map((k) => k.trim()).filter(Boolean) : [],
    ...parseLicense(r.license, !!video, where),
  };
  ev.talk_ids.push(t.id);
  talks.push(t);
}

// 個資掃描：自由文字裡的 email／電話。比照 civictech-tw-data，掃到就失敗。
const PII = [/[\w.+-]+@[\w-]+\.[\w.-]+/, /(?<!\d)09\d{2}-?\d{3}-?\d{3}(?!\d)/];
for (const obj of [...events, ...talks]) {
  const text = JSON.stringify(obj);
  for (const re of PII) {
    const m = text.match(re);
    if (m && !m[0].includes('://')) fail(obj.id, `疑似個資：「${m[0]}」`);
  }
}

const report = {
  counts: { events: events.length, talks: talks.length, warnings: warnings.length, errors: errors.length },
  errors, warnings, notices,
};

await fs.writeFile(REPORT, `${JSON.stringify(report, null, 2)}\n`);

// 公開版：data.civictech.tw/v0/aimonday/report.json，給 AI-Monday repo 的每日建置讀、開 issue 通知維護者。
// 有 error 時資料不更新，但這份照寫——它就是用來說「為什麼沒更新」的。
// 訊息會引用儲存格內容，所以先把疑似個資遮掉；build-index 看到沒有 dataset／table 就不會當成端點。
const redact = (s) => PII.reduce((t, re) => t.replace(new RegExp(re.source, 'g'), '［已遮蔽］'), s);
const pub = (list) => list.map(({ where, msg }) => ({ where, msg: redact(msg) }));
await fs.mkdir(OUT_DIR, { recursive: true });
await fs.writeFile(path.join(OUT_DIR, 'report.json'), `${JSON.stringify({
  sheet: `https://docs.google.com/spreadsheets/d/${SHEET_ID}/`,
  counts: { errors: errors.length, warnings: warnings.length },
  errors: pub(errors), warnings: pub(warnings),
}, null, 2)}\n`);
for (const w of warnings) console.warn(`  ⚠ ${w.where}：${w.msg}`);

if (errors.length) {
  for (const e of errors) console.error(`  ✗ ${e.where}：${e.msg}`);
  console.error(`\n✗ ${errors.length} 個錯誤，不寫檔。`);
  process.exit(1);
}

const envelope = (slug, name, label, records) => ({
  version: 'v0',
  dataset: { slug: 'aimonday', name: 'AI Monday 講題紀錄（Google Sheet）', label: 'AI Monday 講題紀錄' },
  table: { slug, name, label },
  recordCount: records.length,
  records,
});

await fs.mkdir(OUT_DIR, { recursive: true });
const write = (f, o) => fs.writeFile(path.join(OUT_DIR, f), `${JSON.stringify(o, null, 2)}\n`);
await write('events.json', envelope('events', '場次', '場次', events));
await write('talks.json', envelope('talks', '講題', '講題', talks));
await buildIndex();
console.log(`✓ ${events.length} 場、${talks.length} 個講題、${warnings.length} 則警告 → data/v0/aimonday/`);
