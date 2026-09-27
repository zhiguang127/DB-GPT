// Stateful React component checks. Pass a React-18-compatible react-test-renderer path.
// Ant Design host controls are replaced; this is not browser/visual validation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const root = path.resolve(__dirname, '../..');
const requireWeb = Module.createRequire(path.join(root, 'web/package.json'));
const React = requireWeb('react');
const ts = requireWeb('typescript');
const originalLoad = Module._load;
Module._load = function (id, parent, main) {
  if (id === 'react') return React;
  if (id === 'antd') return {
    Input: props => React.createElement('input', props),
    Button: props => React.createElement('button', props, props.children),
    Tooltip: props => props.children,
  };
  if (id === '@ant-design/icons') return new Proxy({}, { get: () => () => React.createElement('i') });
  return originalLoad.call(this, id, parent, main);
};
for (const ext of ['.ts', '.tsx']) require.extensions[ext] = (module, filename) => {
  const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { fileName: filename, compilerOptions: {
    target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true,
  } });
  module._compile(result.outputText, filename);
};
require.extensions['.css'] = module => { module.exports = { __esModule: true, default: new Proxy({}, { get: (_, key) => key }) }; };
const { act, create } = require(path.resolve(process.argv[2]));
const folder = path.join(root, 'web/new-components/financial-analysis');
const Dock = require(path.join(folder, 'AskDbGPTDock.tsx')).default;
const { ReportDataProvider } = require(path.join(folder, 'ReportDataContext.tsx'));
const { alternateReportFixture } = require(path.join(folder, 'report-fixtures.ts'));
const { mockReportData } = require(path.join(folder, 'mock-report.ts'));
const report = alternateReportFixture;
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
async function main() {
  const calls = [];
  let gate = deferred(), selected, view;
  const questionAccess = { ask: (question, revision, signal) => { calls.push({ question, revision, signal }); return gate.promise; } };
  const tree = data => React.createElement(ReportDataProvider, { data, key: `${data.report.run.id}:${data.revision}` },
    React.createElement(Dock, { questionAccess, onOpenEvidence: value => { selected = value; } }));
  const input = () => view.root.findByType('input');
  const enter = () => input().props.onPressEnter({ nativeEvent: { isComposing: false } });
  const write = value => act(() => input().props.onChange({ target: { value } }));
  const text = () => JSON.stringify(view.toJSON(), (key, value) => key === 'props' ? undefined : value);
  const response = { runId: report.report.run.id, revision: report.revision, answer: '当前报告答案', citations: [{ factId: 'value-other' }] };
  await act(async () => { view = create(tree(report)); });
  write('收入是多少？');
  await act(async () => { enter(); enter(); });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].revision, report.revision);
  assert.ok(text().includes('正在根据当前报告查找依据'));
  await act(async () => gate.resolve(response));
  assert.ok(text().includes(response.answer));
  act(() => view.root.findAllByType('button').find(b => b.props.children?.[0] === '查看回答依据').props.onClick());
  assert.deepEqual(selected, { factId: 'value-other' });
  // Failure stays in the existing answer surface, then permits an explicit retry.
  gate = deferred();
  await act(async () => enter());
  await act(async () => gate.reject(new Error('回答超时，请重新发送。')));
  assert.ok(text().includes('回答超时'));
  gate = deferred();
  await act(async () => enter());
  await act(async () => gate.resolve({ ...response, revision: 'stale' }));
  assert.ok(text().includes('报告已更新'));
  assert.ok(!text().includes(response.answer));
  // Close cancels display delivery; a late answer cannot overwrite a later request.
  gate = deferred();
  const oldGate = gate;
  await act(async () => enter());
  act(() => view.root.findByProps({ 'aria-label': '收起回答' }).props.onClick());
  assert.ok(calls.at(-1).signal.aborted);
  gate = deferred();
  await act(async () => enter());
  await act(async () => oldGate.resolve({ ...response, answer: '旧请求不可展示' }));
  assert.ok(!text().includes('旧请求不可展示'));
  // Switching the provider key aborts the request and clears the prior report state.
  const switched = { ...report, report: { ...report.report, run: { ...report.report.run, id: 'another-run' } } };
  await act(async () => view.update(tree(switched)));
  assert.ok(calls.at(-1).signal.aborted);
  await act(async () => gate.resolve(response));
  assert.ok(!text().includes(response.answer));
  assert.equal(input().props.value, '');
  const count = calls.length;
  await act(async () => view.update(tree(mockReportData)));
  const sample = mockReportData.demoQuestions[0];
  await act(async () => view.root.findAllByType('button').find(b => b.props.children === sample.label).props.onClick());
  assert.ok(text().includes(sample.answer));
  assert.equal(calls.length, count);
  act(() => view.unmount());
  console.log('PASS question component: waiting, duplicate guard, evidence, failure/retry, stale revision, cancel, scope switch and unchanged demo.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
