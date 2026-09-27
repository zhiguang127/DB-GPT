// Compare initial SSR markup against an accepted Git revision without checkout.
// Dynamic chart/agent components use the same stubs as test-data.cjs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const root = path.resolve(__dirname, '../..');
if (!process.env.FINANCIAL_LAYOUT_CHILD) {
  const reference = process.argv[2];
  assert.ok(reference, 'Provide the accepted Git revision, e.g. 5eb7ac42');
  const run = baseline => {
    const result = execFileSync(process.execPath, [__filename, reference], {
      cwd: root, encoding: 'utf8', env: { ...process.env, FINANCIAL_LAYOUT_CHILD: baseline ? 'baseline' : 'current' },
    });
    return JSON.parse(result.trim().split(/\r?\n/).at(-1));
  };
  assert.deepEqual(run(false), run(true));
  console.log('PASS initial report/demo markup matches accepted revision; no new report banners or layout blocks.');
} else {
  if (process.env.FINANCIAL_LAYOUT_CHILD === 'baseline') {
    const prefix = 'web/new-components/financial-analysis/';
    const files = execFileSync('git', ['ls-tree', '-r', '--name-only', process.argv[2], '--', prefix], { cwd: root, encoding: 'utf8' })
      .trim().split(/\r?\n/).filter(file => /\.tsx?$/.test(file));
    const originals = new Map(files.map(file => [path.resolve(root, file).toLowerCase(),
      execFileSync('git', ['show', `${process.argv[2]}:${file}`], { cwd: root, encoding: 'utf8' })]));
    const read = fs.readFileSync;
    fs.readFileSync = function (filename, ...args) {
      const original = typeof filename === 'string' && originals.get(path.resolve(filename).toLowerCase());
      return original === undefined || original === false ? read.call(this, filename, ...args) : original;
    };
  }
  process.argv = process.argv.slice(0, 2);
  require('./test-data.cjs');
  const requireWeb = require('node:module').createRequire(path.join(root, 'web/package.json'));
  const React = requireWeb('react');
  const { renderToStaticMarkup } = requireWeb('react-dom/server');
  const folder = path.join(root, 'web/new-components/financial-analysis');
  const Page = require(path.join(folder, 'FinancialAnalysisPage.tsx')).default;
  const { mockReportData } = require(path.join(folder, 'mock-report.ts'));
  const { alternateReportFixture, emptyReportFixture } = require(path.join(folder, 'report-fixtures.ts'));
  const hashes = [mockReportData, alternateReportFixture, emptyReportFixture].map(data =>
    createHash('sha256').update(renderToStaticMarkup(React.createElement(Page, { data }))).digest('hex'));
  console.log(JSON.stringify(hashes));
}
