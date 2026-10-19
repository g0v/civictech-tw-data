#!/usr/bin/env node
/**
 * 把一份「修改申請」寫回 Airtable（實驗中）
 *
 * Airtable 是正本，data/ 是每天被 sync.mjs 整個重寫的鏡像，
 * 所以社群的修改不能改 data/，要改 Airtable。這支腳本讀一份 edit JSON：
 *
 *   {
 *     "dataset": "tech",                  ← 對應 sync.mjs 的 DATASETS slug
 *     "table": "project list",            ← 表名或 tbl id
 *     "record": "recXXXXXXXXXXXXXX",
 *     "changes": [
 *       { "field": "Intro", "from": "舊的簡介", "to": "新的簡介" }   ← field 可以是欄位名或 fld id
 *     ]
 *   }
 *
 * 寫入前先比對 Airtable 現值是否仍等於 from。不相等代表申請送出後有人直接在 Airtable 改過，
 * 整份不寫（不做部分寫入），由人決定。
 *
 * 用法：
 *   AIRTABLE_WRITE_PAT=patXXX node scripts/apply-edit.mjs edit.json            ← 只比對，不寫
 *   AIRTABLE_WRITE_PAT=patXXX node scripts/apply-edit.mjs edit.json --apply    ← 真的寫
 *   加 --base appXXX 可以改打沙盒 base（實驗用）
 *
 * PAT scope：data.records:read + data.records:write + schema.bases:read。
 * 跟 sync.mjs 的唯讀 PAT 分開放，唯讀那把外流的代價比較小。
 *
 * 結束碼：0 寫入成功或比對通過、2 衝突、1 其他錯誤（格式、欄位不允許、API 失敗）
 */

import { readFile } from 'node:fs/promises';

const BASES = {
  tech: 'app2R1DOrrO9iysOr',
};

// 只開放純文字欄位。關聯、選項、附件的寫入格式各不相同，也比較容易一改就壞，等這條路跑順再說
const EDITABLE_TYPES = new Set(['singleLineText', 'multilineText', 'url', 'email']);

const API = 'https://api.airtable.com/v0';
const PAT = process.env.AIRTABLE_WRITE_PAT;

const args = process.argv.slice(2);
const apply = args.includes('--apply');
const baseFlag = args.indexOf('--base');
const baseOverride = baseFlag >= 0 ? args[baseFlag + 1] : null;
const editPath = args.find((a, i) => !a.startsWith('--') && args[i - 1] !== '--base');

function fail(message, code = 1) {
  console.error(message);
  process.exit(code);
}

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: { Authorization: `Bearer ${PAT}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => null);
  if (!res.ok) throw new Error(`Airtable API ${res.status}：${JSON.stringify(json?.error ?? json)}`);
  return json;
}

// Airtable 回傳時會省略空欄位，所以「沒有這個 key」「null」「空字串」視為同一件事
const norm = (v) => (v == null || v === '' ? null : v);

async function main() {
  if (!PAT) fail('缺少 AIRTABLE_WRITE_PAT 環境變數');
  if (!editPath) fail('用法：node scripts/apply-edit.mjs edit.json [--apply] [--base appXXX]');

  const edit = JSON.parse(await readFile(editPath, 'utf8'));
  const baseId = baseOverride ?? BASES[edit.dataset];
  if (!baseId) fail(`不認得的 dataset：${edit.dataset}`);
  if (!/^rec[A-Za-z0-9]{14}$/.test(edit.record ?? '')) fail(`record id 格式不對：${edit.record}`);
  if (!Array.isArray(edit.changes) || edit.changes.length === 0) fail('changes 是空的');

  const { tables } = await api('GET', `${API}/meta/bases/${baseId}/tables`);
  const table = tables.find((t) => t.name === edit.table || t.id === edit.table);
  if (!table) fail(`base 裡找不到表：${edit.table}`);

  const changes = edit.changes.map((c) => {
    const field = table.fields.find((f) => f.name === c.field || f.id === c.field);
    if (!field) fail(`表「${table.name}」裡找不到欄位：${c.field}`);
    if (!EDITABLE_TYPES.has(field.type)) fail(`欄位「${field.name}」是 ${field.type}，目前不開放修改`);
    if (typeof c.to !== 'string') fail(`欄位「${field.name}」的 to 必須是字串`);
    return { field, from: norm(c.from), to: norm(c.to) };
  });

  const current = await api(
    'GET',
    `${API}/${baseId}/${table.id}/${edit.record}?returnFieldsByFieldId=true`,
  );

  const conflicts = changes.filter((c) => norm(current.fields[c.field.id]) !== c.from);
  for (const c of changes) {
    const now = norm(current.fields[c.field.id]);
    const mark = conflicts.includes(c) ? '✗ 衝突' : '✓';
    console.log(`${mark} ${c.field.name}`);
    console.log(`    申請時：${JSON.stringify(c.from)}`);
    console.log(`    現在　：${JSON.stringify(now)}`);
    console.log(`    改成　：${JSON.stringify(c.to)}`);
  }
  if (conflicts.length) fail('\n有欄位在申請送出後被改過，整份不寫入。', 2);

  if (!apply) {
    console.log('\n比對通過。這是預演，加 --apply 才會寫入。');
    return;
  }

  // typecast 關掉：值不合欄位型別時寧可失敗，也不要 Airtable 自作主張轉型
  const updated = await api('PATCH', `${API}/${baseId}/${table.id}/${edit.record}`, {
    fields: Object.fromEntries(changes.map((c) => [c.field.id, c.to])),
    returnFieldsByFieldId: true,
    typecast: false,
  });

  // 寫完讀回來核對，不拿「API 回 200」當成功
  const mismatched = changes.filter((c) => norm(updated.fields[c.field.id]) !== c.to);
  if (mismatched.length) {
    fail(`寫入後讀回的值不一致：${mismatched.map((c) => c.field.name).join('、')}`);
  }
  console.log(`\n已寫入 ${changes.length} 個欄位。`);
}

main().catch((err) => fail(err.message));
