# 第 3 轮：真实 PDF 页级事实提取

2026-09-25。本轮完成页级解析、核心表格识别、事实标准化及两家公司样本回归。页面仍为第 2 轮的演示数据入口；真实 run/API/计算接入属于第 4 轮。

## 实现

- `skills/financial-report-analyzer/scripts/financial_document.py` 逐页读取文本，在关键财务数据及财务报表区域保留原始表格、行列和物理页码。按页面位置区分合并表与母公司表，继承跨页表头和单位。
- 完整行名匹配营收、归母净利润、扣非归母净利润、经营现金流、总资产、总负债；同时提供旧脚本需要的归母净资产和营业成本。避免流动负债/总负债、营业总成本/营业成本混淆。
- 金额使用 Decimal 转成以元计价的十进制字符串；支持括号负数及元/千元/万元/百万元/亿元。比较期由表头识别，增长率列不会作为金额，年初重述列不会作为年末数据。
- `facts` 保存期间、合并及归母归属口径、原始值、单位、标准化值和证据 ID。`evidence` 保存文档标识、物理页码、完整行摘录及表头/单位的来源页。
- 来源金额一致时合并证据；冲突返回 `null/conflict`。缺失、未知单位、显式非人民币币种返回 null 和原因。自动提取事实统一标记 `qualityStatus=warning`，待人工核对。
- `extract_financials.py` 保持 Skill 入口及 JSON 参数，保留旧顶层数值字段并新增 `prev_*`。后续 API/计算使用 `facts[].normalizedValue`，旧浮点字段仅作兼容。
- Skill 说明同步支持范围。mock 数据、CSS、HTML/Markdown 模板和已交付演示 HTML 均未修改。

## 样本核对

以下均为 **2019 年、人民币元**。页码为从 1 开始的 PDF 物理页码。本表由 AI 对照 PDF 渲染页核对，尚待用户人工验收。

| 指标 | 安靠智电 | 来源页 | 海翔药业 | 来源页 |
| --- | ---: | ---: | ---: | ---: |
| 营业收入 | 318,024,319.30 | 8 | 2,941,412,770.30 | 7 |
| 归母净利润 | 63,616,426.50 | 8 | 770,782,185.09 | 7 |
| 扣非归母净利润 | 47,853,754.35 | 8 | 751,209,860.23 | 7 |
| 经营活动现金流量净额 | 36,228,660.52 | 8 | 612,399,095.31 | 7 |
| 总资产 | 1,050,566,795.15 | 8、162 | 6,747,198,664.47 | 7、79 |
| 总负债 | 222,045,561.29 | 164 | 1,022,736,568.92 | 80 |

基准还覆盖两家公司 2018 年的同组 6 项指标，以及安靠智电 2017 年经营现金流 **-21,008,592.71**，共 25 个值。总负债表头来源分别为安靠智电第 161 页、海翔药业第 77 页，单位另有来源页。

基准文件为 `skills/financial-report-analyzer/tests/sample-baselines.json`，通过 SHA-256 匹配原始 PDF。生产解析代码没有硬编码公司、金额或页码。两份文件分别为 312/204 页，每份输出 24 个事实槽位和 32 条证据，未披露的比较期槽位标记 missing。当前环境耗时约 20/11 秒，低于 Skill 的 120 秒限制。

## 验证与复现

项目根目录运行：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -m unittest discover -s skills/financial-report-analyzer/tests -v
.venv/Scripts/python.exe scripts/financial_analysis_extract_check.py --pdf-dir testpdf
```

规则回归覆盖金额精度、单位、负数、错序期间、拆行、缺项、跨页表头、母公司排除、冲突、重述、外币、无文本和损坏 PDF。两份样本的 25 个基准值及引用完整性通过。

输出位于 `.work/financial-analysis/round3/ankao-result.json` 和 `haixiang-result.json`。逐页文本及识别区域的原始表格保存为同目录 `{sha256前16位}-pages.json`。该目录被 Git 忽略。完整页级结构仅在传入开发参数 `artifact_dir` 时落盘，不进入模型上下文；正式持久化将在第 4 轮接入。

阿里 `qwen-plus` 的真实上传 → 附件 → `execute_skill_script_file` → 提取 → 完成响应链路已使用安靠智电样本通过，核验返回的文件 SHA-256、事实和证据。该链路不生成图表或 HTML。联调修复了 `scripts/financial_analysis_smoke.py` 对长文本 SSE 分片未拼接的问题；金额准确性由独立基准检查负责。

后端按本地运行说明启动后可复现：

```powershell
$samplePdf = Get-ChildItem -LiteralPath testpdf -Filter '*300617*.pdf' | Select-Object -First 1
.venv/Scripts/python.exe scripts/financial_analysis_smoke.py --base-url http://127.0.0.1:5670 --model qwen-plus --check-skill --pdf $samplePdf.FullName
```

## 当前边界与下一任务

限定中文、人民币、非金融企业文本年报的规则表格；没有 OCR，不声称支持所有版式、金融行业、季度报告、重述或多币种换算。只写“元”的中文年报按人民币解释，以 `currencyBasis` 明示；显式外币不转换成人民币。纯文本旧正则路径已移除，避免把邻近数字当事实。

目前验证两家公司，原计划第三家独立样本尚未提供，不能据此宣称普遍准确率。浏览器页面本轮无新增功能，未重新做视觉验收。

下一任务为第 4 轮：基于十进制事实计算同比、现金利润比和资产负债率等，接通 run API、报告保存及现有页面。上传文件 ID 和 owner/session 绑定沿用文件服务；文档内容哈希不是下载授权。旧 `calculate_ratios.py` 的简化 ROE 等算法本轮未重写，不属于新计算链路的验收结果。
