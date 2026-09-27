# 第 7 轮：当前报告真实追问

2026-09-26 开发，2026-09-27 按用户要求分批提交。布局修正为 `5eb7ac42`；第 7 轮后端与验证为 `7eda5436`，前端接入与布局/交互测试为 `03b31cd0`，文档单独提交。第 7 轮本次未推送；当前进度和里程碑见[阶段评估](financial-analysis-status-20260927.zh-CN.md)。

## 使用行为

现有 Ask DB-GPT 输入框在真实报告中调用阿里 `qwen-plus`。输入、等待、回答、失败和重试均复用原有问答区域，没有新增报告横幅、布局区块或 CSS。demo 仍使用原来的示例问题和答案，不调用模型。

回答绑定 run ID、session ID、owner 和报告 revision。问题最多 1000 字，前后端拒绝空问题；报告权限检查先于模型调用，版本不一致返回明确错误。模型返回后再次检查版本，避免展示处理期间已过期的回答。切换报告或版本会清空旧回答，停止接收旧请求的结果。关闭回答也会中止客户端请求；服务端已经发出的模型调用不保证立即取消，仍受超时限制。

普通请求一次返回完整答案，等待文字放在原回答区。重复点击不会重复提交。失败后输入保留，可以重新发送；答案中的依据按钮打开现有事实/计算证据面板，再进入原 PDF 来源页。

## 上下文与校验

新增 `POST /api/v1/financial-analysis/runs/{run_id}/questions`，请求字段为 `session_id`、`revision`、`question`。复用项目 DefaultLLMClient、Qwen worker 及已有身份校验，不新增密钥配置或数据库列。

上下文先按利润、收入、现金、费用、资产负债等词选择相关事实与计算，未匹配问题使用有界结构化报告数据。仅取本期、上期已解析事实及其摘录；最多 60 条事实、40 条计算、100 条摘录，每条摘录最多 600 字符，以及至多 6 条相关研究发现，总长度最多 70000 字符。上下文不包含凭证、本地文件路径、完整 PDF 或其他报告会话。

模型只能通过事实或计算占位符输出数字。服务端替换成已保存的指标、值及单位，检查引用存在性、输入关系、来源文档归属和未引用数字。计算问题引用已有的 24 项 Decimal 计算，未实现的公式不会交给模型心算。原文证据由服务端从事实和计算输入补齐；页面中的数字、公式、输入值和 PDF 来源保持同一套依据。

问答最多占用两个并发槽位，超出返回 429。每个问题最多两次模型请求（一次生成、一次纠正），共享 60 秒期限。纠正请求说明具体格式或引用错误，不无限重试。

返回 `answerMode` 区分三种情况：

| 状态 | 页面内容 |
| --- | --- |
| `validated` | 模型文字已通过数字和引用校验；这不等于语义或因果解释已核实 |
| `references_only` | 模型解释未通过校验，丢弃全部模型文字，仅由服务端列出其有效引用对应的已保存数据，并明确说明降级 |
| `insufficient` | 无法给出有依据的回答，明确说明当前已提取资料不足 |

降级不会保留模型手写的数字、单位或解释。若连引用本身也不合法、结构错误或模型不可用，返回处理过的错误，不回退到 demo，不修改报告事实或结论。所有自动回答最多标为 `partial`，资料不足及降级标为 `unresolved`，仍需用户核对。

“提取上下文不足”不代表完整 PDF 未披露。未新增附注检索、客户名单解析、多轮会话记忆、问题持久化或新的公式，这些限制不会用推测补齐。

## 验证

- 新增 22 项后端追问测试，连同财务分析、文件服务生命周期和提取器共 80 项通过。覆盖规范化数值、计算输入、未知/多余引用、未引用数字、只保留已存数据的降级、owner/session 隔离、版本变化、并发上限、超时、错误信息处理及纠正次数限制。
- 有状态 React 测试通过：等待、重复点击、证据跳转、失败重试、过期版本、关闭请求、切换报告、demo 不调用服务。测试使用真实 React 和 react-test-renderer，Ant Design 控件替换为宿主控件，不等同于真实浏览器交互。
- 将当前初始页面与布局修正提交 `5eb7ac42` 比较，demo、替换报告、空报告的 SSR HTML 哈希完全一致。mock 数据、mock 报告、CSS 和 Skill 模板无改动。
- 两份真实报告的 SSR 回归、ESLint、Ruff、离线构建通过；TypeScript 原有 138 项错误，本轮新增 0 项。现有前端页面 HTTP 200。
- 浏览器工具没有提供可连接会话，未宣称完成浏览器视觉或鼠标交互验收。

真实问答使用两份已核对公开披露来源的年报，复用 `.work/financial-analysis/round6cd/` 的隔离快照和 5671 测试服务。问题覆盖利润变化、现金转化、费用率、数值来源、缺乏资料的客户名单。输出记录保存在 `.work/financial-analysis/round7/questions-final.json`，按 `answerMode` 区分完整解释和降级，不能把“引用数据可读”描述成模型解释全部通过。

最终十个问题全部完成接口、引用数值及报告不变性检查：七条为 `validated`、一条为 `references_only`、两条为 `insufficient`。安靠的四个有数据问题均返回通过校验的回答；海翔的现金覆盖问题仅返回已保存的 `0.79×` 计算及依据，明确说明模型解释未通过。两家客户名单问题都说明资料不足。单次请求耗时约 1.3–5.7 秒；这是本轮样本结果，不代表普遍成功率或固定延迟。部分回答会重复指标名称，表达质量和语义正确性仍需人工核对。

验收后已停止临时后端及其 worker，确认 5671 释放。没有停止或重启用户的 3000/5670 日常服务。

## 本地验收

在原后端终端按 Ctrl+C，等待退出后，从项目根目录重新运行：

```powershell
uv run --env-file .env --no-sync dbgpt start webserver --config configs/dbgpt-proxy-tongyi.toml
```

刷新前端并打开一份已有真实报告，直接在左侧 Ask DB-GPT 提问，不需要重新上传或重新生成报告。可试：

1. 本期归母净利润和扣非归母净利润如何变化？
2. 经营现金流对归母净利润的覆盖情况如何？
3. 本期销售费用率和管理费用率是多少？与上期相比有何变化？
4. 本期营业收入是多少？请提供原文依据。
5. 列出公司前五大客户的具体名称和各自销售占比。

核对答案中的数值，点击依据进入公式或事实，再打开 PDF 页。最后一个问题应说明现有提取资料不足；模型解释校验失败时可能仅展示已保存引用数据，不能将其视为完整解释。

## 复现命令

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -m pytest packages/dbgpt-serve/src/dbgpt_serve/financial_analysis/tests packages/dbgpt-serve/src/dbgpt_serve/session_file/tests/test_serve.py skills/financial-report-analyzer/tests/test_financial_document.py -q
node standalone/financial-analysis/test-data.cjs
node standalone/financial-analysis/test-layout.cjs 5eb7ac42
# 测试渲染器仅安装在忽略目录，不改变项目依赖；版本与当前 React 对齐
npm install --prefix .work/financial-analysis/round7/ui-test --no-save --package-lock=false --ignore-scripts react-test-renderer@18.3.1
node standalone/financial-analysis/test-questions.cjs .work/financial-analysis/round7/ui-test/node_modules/react-test-renderer
# 需要已运行的后端及属于该后端数据库的 runs.json；会实际调用 Qwen
.venv/Scripts/python.exe scripts/financial_analysis_question_check.py --base-url http://127.0.0.1:5670 --runs .work/financial-analysis/round6/runs.json --output .work/financial-analysis/round7/local-questions.json
```

第 8 轮继续报告历史、保存/下载和日常使用闭环；本轮不包含这些能力。
