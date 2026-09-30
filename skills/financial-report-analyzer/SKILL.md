---
name: financial-report-analyzer
description: 在当前智能体对话中分析中文上市公司文本型年度报告 PDF。提取真实财务事实，执行确定性计算，由当前智能体撰写带引用的结论，并用固定财报组件展示报告、来源和下载。
---

# 财报分析技能

用户直接在智能体对话上传年报或点击首页财报示例。所有步骤在当前对话完成，右侧 Computer 展示财报组件，不要求用户跳转独立页面。

## 工作流程

1. 调用 `prepare_financial_report`。仅有一份 PDF 可省略参数；有多份时指定当前附件清单的 `file_id`，不猜测路径或 ID。该工具复用页级提取器、Decimal 计算和报告存储，返回真实 facts、calculations、evidence、run_id、revision。它不调用另一个模型生成结论。
2. 阅读返回数据并由当前智能体撰写结构化 `findings`。遵循工具返回的 `publication_instructions`：尽量覆盖 overview、profitability、cashflow、balance；引用真实 ID；年份、金额、百分比等数字必须使用工具说明中的双花括号占位符，后端替换真实显示值。缺少事实、计算或附注时明确不足，不使用示例值、不心算、不补造原因。
3. 调用 `publish_financial_report(run_id, revision, findings)`。结论结构、数字及引用由后端验证。全部被拒绝时修正并重试；部分通过时如实保留“部分分析”。无可支持结论时可提交空数组，报告仍保留事实、计算与原 PDF 来源。
4. 用一两句话总结实际结果并调用 `terminate`。报告已经作为当前智能体的产物显示，用户可以查看原有五个章节、证据、PDF 原页与 JSON/HTML 导出。不要再调用 `html_interpreter`、生成另一套网页，或让用户进入 `/financial-analysis`。
5. 后续追问调用 `read_financial_report`，省略 run_id 默认读取当前对话最近报告，也可明确指定该对话的报告 ID。只依据读取到的事实、确定性计算、有效结论和摘录作答；没有的指标和原因明确说明缺少依据。需要新分析时才重新调用 prepare。

## 数据边界

- 当前提取器支持中文、人民币、非金融企业的文本型年度报告 PDF，使用真实比较期，缺项不补零。
- 归母净利润、扣非归母净利润、合并口径及期初/期末不能混用。
- 自动提取值仍待人工核对，引用校验不等于结论语义已经人工确认。
- `references/financial_metrics.md` 和 `references/analysis_framework.md` 可供参考，不能用参考材料中的常量补齐当前报告。
- 旧 scripts 与 HTML 模板保留兼容用途；当前智能体财报交付统一通过上述工具与固定组件完成。
