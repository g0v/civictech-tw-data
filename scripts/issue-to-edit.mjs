// 把「修改專案」的 issue（.github/ISSUE_TEMPLATE/edit-project.yml）轉成一份修改申請 edits/issue-{編號}.json，
// 交給 workflow 開 PR。合併之後由 apply-edit.mjs 寫回 Airtable。
//
// 申請裡記下每個欄位「申請時的值」（from），寫回時拿它跟 Airtable 比對，偵測期間有沒有人直接改過。
// from 取自公開的鏡像（data.civictech.tw），不打 Airtable：這一步不需要任何 token，
// 鏡像最多晚一天，晚到的那一天由寫回時的比對兜住。
//
// issue 內容是任何人都能寫的，所以這裡只做白名單：
//   - 只認得表單上有的欄位，其他一律忽略
//   - 網址要符合格式、專案代號要真的存在，不然整張 issue 回報錯誤、不開 PR
//   - 寫入的路徑只會是 edits/issue-{編號}.json
//
// 用法（workflow 裡）：node scripts/issue-to-edit.mjs "$GITHUB_EVENT_PATH"
// 結果寫到 issue-result.json：{ ok, files, title, body } 或 { ok: false, errors }
// PROJECTS_SOURCE 可以換成別的網址或本機路徑（測試用），預設是正式的鏡像

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PROJECTS_SOURCE = process.env.PROJECTS_SOURCE || 'https://data.civictech.tw/v0/tech/projects.json';

// 表單上的標題 → 表單欄位
const LABELS = {
  '專案代號': 'project_id', '專案名稱': 'name', '英文名稱': 'name_en', '簡介': 'intro',
  '官方網站': 'website', '原始碼': 'github', '專案文件': 'document', 'Facebook': 'facebook',
  '為什麼要改': 'reason',
};
// 表單欄位 → Airtable 欄位。apply-edit.mjs 另外會擋掉非純文字的欄位
const TO_AIRTABLE = {
  name: 'project name', name_en: 'project name EN', intro: 'Intro',
  website: 'Website URL', github: 'github', document: 'document', facebook: 'Facebook Page Link',
};
const URL_FIELDS = new Set(['website', 'github', 'document', 'facebook']);
// civictech.tw 用這三個欄位算專案頁網址（civictech.tw 的 src/lib/projects.ts baseSlug）
const SLUG_FIELDS = new Set(['name', 'name_en', 'github']);
const EMAIL_RE = /[\w.+-]+@[\w-]+\.[\w.]{2,}/;
const PHONE_RE = /\b09\d{2}[-\s]?\d{3}[-\s]?\d{3}\b|\b0[2-8][-\s]?\d{6,8}\b/;
const FIELD_NAME = Object.fromEntries(Object.entries(LABELS).map(([label, key]) => [key, label]));

export function parseIssueBody(body) {
  const out = {};
  for (const part of `\n${body ?? ''}`.split(/\n### /).slice(1)) {
    const nl = part.indexOf('\n');
    const label = part.slice(0, nl).trim();
    const value = part.slice(nl + 1).trim();
    const key = LABELS[label];
    if (key && value && value !== '_No response_') out[key] = value;
  }
  return out;
}

function validate(f, errors) {
  const v = {};
  for (const [k, raw] of Object.entries(f)) {
    const s = raw.trim();
    if (k === 'project_id') {
      if (!/^rec[A-Za-z0-9]{14}$/.test(s)) errors.push(`專案代號的格式不對：「${s}」`);
      else v[k] = s;
    } else if (URL_FIELDS.has(k)) {
      if (!/^https?:\/\/\S+$/.test(s)) errors.push(`「${FIELD_NAME[k]}」要以 http:// 或 https:// 開頭，現在是「${s}」`);
      else v[k] = s.slice(0, 500);
    } else if (k === 'intro' || k === 'reason') {
      v[k] = s.slice(0, 2000);
    } else {
      v[k] = s.replace(/\s+/g, ' ').slice(0, 200);
    }
  }
  return v;
}

async function loadProjects() {
  const text = /^https?:\/\//.test(PROJECTS_SOURCE)
    ? await (await fetch(PROJECTS_SOURCE)).text()
    : await readFile(PROJECTS_SOURCE, 'utf8');
  return JSON.parse(text);
}

async function author(issue) {
  const login = issue.user?.login;
  const relation = {
    OWNER: '擁有者', MEMBER: 'g0v 組織成員', COLLABORATOR: '協作者', CONTRIBUTOR: '貢獻過這個 repo',
    FIRST_TIME_CONTRIBUTOR: '第一次貢獻', FIRST_TIMER: '第一次在 GitHub 上貢獻', NONE: '第一次來',
  }[issue.author_association] ?? issue.author_association;
  let age = '';
  try {
    const r = await fetch(`https://api.github.com/users/${login}`, { headers: process.env.GH_TOKEN ? { Authorization: `Bearer ${process.env.GH_TOKEN}` } : {} });
    const u = await r.json();
    if (u.created_at) {
      const days = Math.floor((Date.now() - Date.parse(u.created_at)) / 864e5);
      age = days < 30 ? `，**帳號建立才 ${days} 天**` : `，帳號建立於 ${u.created_at.slice(0, 10)}`;
    }
  } catch {}
  return `@${login}（${relation}${age}）`;
}

const show = (v) => (v == null || v === '' ? '（空）' : String(v).replace(/\|/g, '\\|').replace(/\n+/g, ' '));

export async function handle(issue, projects) {
  const labels = (issue.labels ?? []).map((l) => (typeof l === 'string' ? l : l.name));
  if (!labels.includes('修改專案')) return { ok: false, errors: ['這張 issue 沒有「修改專案」標籤'] };
  const errors = [];
  const f = validate(parseIssueBody(issue.body), errors);

  if (!f.project_id) errors.push('缺少「專案代號」');
  const record = projects.records.find((r) => r.id === f.project_id);
  if (f.project_id && !record) errors.push(`找不到專案代號「${f.project_id}」，請從 civictech.tw 專案頁的「建議修改」進來`);
  if (errors.length) return { ok: false, errors };

  // 值跟現在一樣的欄位不列：表單常被整份預填，送出時只有一兩格真的有改
  const changes = Object.entries(TO_AIRTABLE)
    .filter(([k, field]) => f[k] && f[k] !== (record.fields[field] ?? '').trim())
    .map(([k, field]) => ({ key: k, field, from: record.fields[field] ?? null, to: f[k] }));
  if (!changes.length) return { ok: false, errors: ['沒有填任何跟現在不一樣的欄位'] };

  const edit = {
    dataset: 'tech',
    table: 'project list',
    record: record.id,
    issue: issue.number,
    changes: changes.map(({ field, from, to }) => ({ field, from, to })),
  };

  const name = record.fields['project name']?.trim() || record.id;
  const lines = [`由 #${issue.number} 自動產生，送出的人：${await author(issue)}`, ''];
  lines.push(`**專案**：${name}（\`${record.id}\`）`, '');
  lines.push('| 欄位 | 現在 | 改成 |', '|---|---|---|');
  for (const c of changes) lines.push(`| ${FIELD_NAME[c.key]} | ${show(c.from)} | **${show(c.to)}** |`);
  lines.push('');
  const warn = [];
  if (changes.some((c) => SLUG_FIELDS.has(c.key))) {
    warn.push('改到名稱、英文名稱或原始碼網址，**civictech.tw 上這個專案頁的網址可能會跟著變**，舊連結會失效。');
  }
  // 跟 sync.mjs 的個資掃描同一組規則：那邊掃到沒審過的會讓整個每日同步失敗，所以合併前就要知道
  const pii = changes.filter((c) => c.to.split(/\s+/).some((t) => !/https?:\/\//.test(t) && (EMAIL_RE.test(t) || PHONE_RE.test(t))));
  if (pii.length) {
    warn.push(`「${pii.map((c) => FIELD_NAME[c.key]).join('、')}」裡有像 email 或電話的字串。**合併後每日同步的個資掃描會擋下整個匯出**，除非先把它加進 sync.mjs 的 PII_REVIEWED。`);
  }
  if (warn.length) lines.push('### 合併前請注意', '', ...warn.map((w) => `- ${w}`), '');
  lines.push(
    `**理由**：${(f.reason ?? '').replace(/\n+/g, ' ').slice(0, 1000)}`, '', '---',
    '合併後會寫回 Airtable，結果留言在這個 PR 上；隔天同步後出現在 civictech.tw。',
    '「現在」是申請送出時鏡像上的值。如果期間有人直接在 Airtable 改過，寫回時會偵測到、整份不寫。',
    '不採用的話直接關掉這個 PR。', '', `Closes #${issue.number}`,
  );

  return {
    ok: true,
    files: [[`edits/issue-${issue.number}.json`, edit]],
    title: `修改：${issue.title.replace(/^修改[:：]\s*/, '') || name}`.slice(0, 120),
    body: lines.join('\n'),
  };
}

async function main() {
  const event = JSON.parse(await readFile(process.argv[2], 'utf8'));
  const result = await handle(event.issue, await loadProjects());
  if (result.ok) {
    for (const [file, data] of result.files) {
      await mkdir(path.join(ROOT, path.dirname(file)), { recursive: true });
      await writeFile(path.join(ROOT, file), JSON.stringify(data, null, 2) + '\n');
    }
    result.files = result.files.map(([f]) => f);
  }
  await writeFile(path.join(ROOT, 'issue-result.json'), JSON.stringify(result, null, 2));
  console.log(result.ok ? `OK：${result.files.join(', ')}` : `不開 PR：${result.errors.join('；')}`);
}

if (fileURLToPath(import.meta.url) === path.resolve(process.argv[1] ?? '')) await main();
