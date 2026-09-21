const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const vm = require('node:vm');
const crypto = require('node:crypto');
const dir = __dirname;
const repo = path.resolve(dir, '../..');
const name = 'DB-GPT-Financial-Analysis-Demo.html';
const original = path.join(repo, name);
const html = fs.readFileSync(original, 'utf8');
const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
assert.equal(scripts.length, 1, 'One classic inline script');
assert(!/\bsrc\s*=|\btype\s*=/.test(scripts[0][1]), 'No external/module script');
new vm.Script(scripts[0][2], { filename: name });
const markup = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
assert(!/<(?:script|link|img|iframe|source)\b[^>]*(?:src|href)\s*=\s*['"](?!data:|blob:)/i.test(markup), 'No external HTML resource');
assert(!/@import\b|url\(\s*['"]?(?!data:)[^)'"\s]/i.test(markup), 'No external CSS resource');
assert(html.includes("connect-src 'none'"), 'CSP forbids network connections');
assert(!/\bimport\s*\(/.test(scripts[0][2]), 'No native dynamic imports');
const buildReport = JSON.parse(fs.readFileSync(path.join(dir, '.work/build-report.json'), 'utf8'));
assert.deepEqual(buildReport.assets, ['demo.js', 'financial_analysis_module_css.css']);
for (const [file, hash] of Object.entries(buildReport.originalSourceHashes)) {
  assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(repo, 'web/new-components/financial-analysis', file))).digest('hex'), hash, `Unchanged development source: ${file}`);
}
const tempDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'dbgpt-financial-demo-'));
const copy = path.join(tempDirectory, name);
fs.copyFileSync(original, copy);
assert.deepEqual(fs.readdirSync(tempDirectory), [name]);
assert(fs.readFileSync(copy).equals(fs.readFileSync(original)), 'Byte-identical clean-directory copy');
const result = {
  output: original, bytes: fs.statSync(original).size, cleanCopy: copy,
  staticChecks: 'passed', inlineAssets: true, developmentSourcesUnchanged: true,
  browserDirectOpen: 'not verified: Computer Use stopped because the browser URL could not be determined',
  runtimeNetworkRequests: 'not verified', runtimeConsoleErrors: 'not verified', runtimeInteractions: 'not verified',
};
fs.writeFileSync(path.join(dir, '.work/verification.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
