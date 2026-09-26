# 第 6A/6B 轮：扩展事实、费率和流动性数据

2026-09-26。本轮完成第 5 轮提交以及 6A/6B 开发。第 5 轮提交为 `7f9a11e0`；6A/6B 经用户验收后已提交为 `b3fbbaab`，均未推送远端。mock 数据、mock 报告、CSS 和旧 Skill 模板未改动，阿里 Qwen 配置保持不变。

本轮仍是确定性提取与计算。Qwen 分析结论和真实追问分别留待 6C/6D、第 7 轮。

## 可直接查看的新报告

- [上传并分析](http://127.0.0.1:3000/financial-analysis/)
- [安靠智电](http://127.0.0.1:3000/financial-analysis/?run_id=84551de0-a8b2-4b4d-8fc8-602a612d17c6&session_id=financial-run-check-00126a8ac2f4461fadd74bf1b43e374b)
- [海翔药业](http://127.0.0.1:3000/financial-analysis/?run_id=30a479f5-354e-4931-aa4f-647b923696c6&session_id=financial-run-check-baecad60b3ee4de79560503b5d9a36df)
- [原 demo](http://127.0.0.1:3000/financial-analysis/?demo=1)

样本归匿名开发用户 `001`；其他用户请自行上传。旧报告快照不会自动补入新指标，需重新分析或使用上方新报告。

验收重点：在“盈利质量”查看毛利率与费用率对照表，分别点击本期、上期及变动值检查公式和来源；在“资产负债”检查流动资产、流动负债、存货和流动比率；在“关键报表”核对新增金额。费用率图表使用真实计算结果，负费用保持负数，缺失项不补零。

## 实现范围

提取指标由 8 类扩展至 15 类，新增销售费用、管理费用、研发费用、财务费用、流动资产、流动负债、存货。营业成本沿用已有提取，补充两家公司两年的基准验证。

利润表与资产负债表分别限制允许的指标，继续排除母公司报表干扰。期末余额使用 instant 期间类型，费用使用 flow；缺失、冲突、负数、期间和来源页信息仍按原规则保留。未新增 OCR 或附注检索。

计算由 8 条扩展至 24 条：

- 原有 8 条计算保持。
- 本期和上期毛利率及 4 项费用率：10 条。
- 毛利率及 4 项费用率的同比变动：5 条，单位为百分点。
- 本期流动比率：1 条。

毛利率为 `(营业收入－营业成本) / 营业收入 × 100%`；各项费用率为 `费用 / 营业收入 × 100%`；流动比率为 `流动资产 / 流动负债`。费率变动使用未舍入的本期、上期费率之差，不是费用同比，也不是已显示两位小数的差。缺输入、口径不一致、零分母返回不可计算及原因。

本期/上期计算使用不同 ID，报告组装按期间选择，避免上期覆盖本期。费用图表点保留 calculationId；新对照表复用 Ant Design Table 和证据面板，新增字段可选，旧快照和 demo 仍可渲染。

## 样本核对

逐张检查了新增指标涉及的 7 张原始报表页。结合原基准，两家公司共 57 个金额值通过真实 PDF 提取检查，每个值均检查预期来源页。正式接口各生成 45 条事实记录，其中 36 条有值，其余明确缺失；未把空项视作零。

| 指标（2019 年） | 安靠智电 | 海翔药业 |
| --- | ---: | ---: |
| 毛利率 | 50.43% | 50.26% |
| 毛利率变动 | -0.05 百分点 | 5.87 百分点 |
| 销售费用率 | 11.36% | 2.03% |
| 管理费用率 | 12.67% | 13.13% |
| 研发费用率 | 7.02% | 4.17% |
| 财务费用率 | 1.31% | -1.29% |
| 流动比率 | 4.06× | 3.26× |

| 原始金额来源 | 安靠智电物理页 | 海翔药业物理页 |
| --- | ---: | ---: |
| 营业成本 | 168 | 83 |
| 销售、管理、研发、财务费用 | 168 | 84 |
| 流动资产及存货 | 161 | 78 |
| 流动负债 | 163 | 79 |

这只是两份样本的验证，不代表所有年度报告格式均受支持。基准保留 AI 原页核对标记，用户人工核对和第三家公司样本仍待补充。

## 检查结果与复现

- 提交第 5 轮前：20 项来源预览和文件服务生命周期回归通过。
- 6A/6B：提取器及财务分析后端 26 项测试通过，覆盖负费用、母公司隔离、跨期精度、缺项、零分母、引用关系及原任务/来源接口。
- 两家公司正式上传、后台计算、保存、重复读取和权限隔离通过，每份 24 条可用计算。
- 扩展来源预览检查通过：安靠 6 个不同页、海翔 7 个不同页；原 PDF 下载与样本字节一致。
- 前端原 demo、替换/空数据、新报告及第 5 轮旧快照回归通过；新增对照表各单元格点击回调、计算输入和证据关系通过。
- Ruff、ESLint、离线构建、Next 页面编译及 HTTP 200 检查通过。TypeScript 仍有仓库原先 138 项错误，本轮新增 0 项。
- 浏览器工具未提供可连接的浏览器；未完成实际鼠标交互及完整页面视觉验收。SSR、接口和原 PDF 图像核对不替代浏览器验收。

```powershell
# 项目根目录；已有虚拟环境
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -m pytest skills/financial-report-analyzer/tests/test_financial_document.py packages/dbgpt-serve/src/dbgpt_serve/financial_analysis/tests -q
.venv/Scripts/python.exe scripts/financial_analysis_extract_check.py --output-dir .work/financial-analysis/round6
# 以下需要本地后端运行，生成并保留新的样本报告
.venv/Scripts/python.exe scripts/financial_analysis_run_check.py --base-url http://127.0.0.1:5670 --keep --output-dir .work/financial-analysis/round6
.venv/Scripts/python.exe scripts/financial_analysis_preview_check.py --runs .work/financial-analysis/round6/runs.json --output-dir .work/financial-analysis/round6 --extended
node standalone/financial-analysis/test-data.cjs .work/financial-analysis/round6/ankao-report.json .work/financial-analysis/round6/haixiang-report.json
node standalone/financial-analysis/build.cjs .work/financial-analysis/demo-round6.html
```

最新报告链接、JSON、原页图像和检查摘要在忽略目录 `.work/financial-analysis/round6/`。重新运行上传脚本会创建新报告，链接以该目录的 runs.json 为准。

## 下一步：6C/6D

复用项目 DefaultLLMClient 接入 Qwen，基于已有事实、计算及摘录生成结构化 findings。先保存可查看的数据报告，再运行模型分析；模型超时或引用校验失败不能丢失事实和计算。独立记录模型分析状态，校验引用归属及数字单位，无附注依据时限制因果结论。现有五个章节的布局和 mock 保持。
