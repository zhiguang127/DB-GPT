# 第 4 轮：计算、任务 API 和真实报告页面

2026-09-25。本轮已接通上传 PDF、后台解析、确定性计算、数据库保存和页面读取。原 mock 数据、样式和 Skill 模板保持不变。阿里 Qwen 的 `.env` 与模型配置保持不变；本轮数值处理不需要模型推算。

## 使用入口

- [上传并分析年度报告](http://localhost:3000/financial-analysis)
- [保留的原有演示](http://localhost:3000/financial-analysis?demo=1)
- [安靠智电真实报告](http://localhost:3000/financial-analysis?run_id=d16791d5-a006-4d31-9c89-a8c13666f530&session_id=financial-run-check-9596fd1531f145e193ee5f325ce9e2c2)
- [海翔药业真实报告](http://localhost:3000/financial-analysis?run_id=727d3ba3-814c-4c41-a69b-426f355e286a&session_id=financial-run-check-169c2cdd33cf432dad44689deb9a0e8d)

两份预生成报告及上传文件保留在当前本地服务中，使用匿名开发用户 `001`。若浏览器已登录为其他用户，请从上传入口建立自己会话的报告，访问限制不会绕过。

上传后页面显示排队、解析、计算和保存状态。完成后，Overview、关键报表和趋势来自 PDF；点击指标可查看公式、输入值、计算步骤和原文摘录。保留完整页面链接即可刷新或重新打开。失败时显示原因并可重新分析。实际 PDF 页级预览属于下一轮，当前来源面板仍是摘录展示。

## 后端与持久化

新增 `packages/dbgpt-serve/src/dbgpt_serve/financial_analysis/`，通过现有 `SessionFileServe` 生命周期挂载：

| 接口 | 用途 |
| --- | --- |
| `POST /api/v1/financial-analysis/runs` | `session_id`、一个 `file_ids`、可选 UUID `request_id`，返回 202 和任务状态 |
| `GET /api/v1/financial-analysis/runs/{id}?session_id=...` | 查询进度和错误 |
| `GET /api/v1/financial-analysis/runs/{id}/report?session_id=...` | 获取完成的 ReportData 快照 |

沿用文件服务的 `user-id`、API key 和会话归属规则。报告未完成返回 409，不属于当前用户/会话返回 404。前端沿用已有 HTTP 客户端与上传 API。

任务及完整报告保存在现有 metadata 数据库的 `dbgpt_financial_analysis_run` 表。完成状态与快照在同一事务写入。相同 request ID 不重复运行；失败后新 ID 为新任务。前端会保留一次提交的 request ID，网络重试复用它。

后台最多同时执行两个任务，总计最多四个执行/排队任务，超过后返回 429。解析使用固定 Skill 脚本，子进程限时 120 秒。后台通过文件 registry 独立打开和物化原始文件，保持到解析结束后再清理，不引用聊天回合的临时路径。解析输出 SHA-256 必须与上传记录一致。

这是当前个人开发环境的**单服务进程**实现。启动时将遗留 pending/running 任务标为中断失败，已完成报告保持可读；正常停止会等待已提交工作结束。多 worker 或多实例协调、断点恢复和跨实例队列不在本轮范围，不能以多个进程共享此 runner 数据库运行。

## 计算规则

`calculations.py` 使用 Decimal（计算精度 38 位），API 通过十进制字符串返回金额和计算结果；显示结果保留两位小数。图表绘制坐标单独转为数值，不作为计算输入。

每份报告包含 8 项计算：营收、归母净利润、扣非归母净利润、经营现金流的同比；非经常性净影响及其占归母净利润比例；经营现金流/归母净利润；资产负债率。

每项包含 formula、inputFactIds、steps、result、displayResult 和状态/原因。输入必须是可用的人民币元金额，报表口径、归母归属、期间类型和期间匹配。同比只比较相邻年度，以 `（本期－上期）/|上期|` 计算，负基数时在步骤中明示；缺输入、口径冲突、非有限值、零分母均不可计算。

| 2019 年计算 | 安靠智电 | 海翔药业 |
| --- | ---: | ---: |
| 营业收入同比 | -0.64% | 8.20% |
| 归母净利润同比 | -15.49% | 27.40% |
| 扣非归母净利润同比 | -26.61% | 24.18% |
| 经营现金流同比 | -37.88% | -22.62% |
| 非经常性净影响 | 15,762,672.15 元 | 19,572,324.86 元 |
| 非经常性净影响占比 | 24.78% | 2.54% |
| 经营现金流/归母净利润 | 0.57× | 0.79× |
| 资产负债率 | 21.14% | 15.16% |

旧 `calculate_ratios.py` 继续供旧 HTML Skill 使用，未把其简化 ROE 算法引入新页面。新报告不生成没有依据的分析结论、流动比率或虚构交付文件。

## 验证

- 后端计算、任务和现有文件服务生命周期：15 项测试通过。覆盖精确计算、负基数、缺失、零分母、口径拒绝、后台文件生命周期、重复请求、API key、用户/会话隔离、失败与持久化恢复。
- 两份真实 PDF：隔离环境和本地正式服务均通过上传、后台计算、保存、重复读取。25 个原始金额基准值通过，每份返回 8 项带引用的计算。
- 前端：原有 demo/替换数据/空数据回归，以及两份真实 ReportData 的渲染、指标点击回调、公式/输入值/证据解析通过。ESLint 通过；TypeScript 对比基线无新增错误（仓库原有 138 项）。
- Next 页面编译及 HTTP 200 检查通过。目前未连接可自动操作的浏览器，未宣称完成浏览器鼠标交互与视觉验收。
- mock-data、CSS 和 HTML/Markdown 模板的 Git diff 为空。

复现命令（项目根目录）：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -m pytest packages/dbgpt-serve/src/dbgpt_serve/financial_analysis/tests packages/dbgpt-serve/src/dbgpt_serve/session_file/tests/test_serve.py -q
# 隔离文件存储和数据库，不调用模型
.venv/Scripts/python.exe scripts/financial_analysis_run_check.py
# 正式本地服务，保留两份上传和报告供查看
.venv/Scripts/python.exe scripts/financial_analysis_run_check.py --base-url http://127.0.0.1:5670 --keep
node standalone/financial-analysis/test-data.cjs .work/financial-analysis/round4/ankao-report.json .work/financial-analysis/round4/haixiang-report.json
```

Windows 环境需允许文件检查及 PDF 解析启动本地子进程。验证输出保存在 `.work/financial-analysis/round4/`，其中 `runs.json` 记录最近一次测试链接；默认隔离运行的链接不能在正式服务里使用。保留的正式任务仍可通过上方固定链接访问。

## 下一轮

第 5 轮接真实 PDF 来源预览：从指标证据打开正确文件和物理页，保留摘录与明确页码。完整模型分析和追问分别留在第 6/7 轮。第三家独立样本及用户人工核对仍待补充。
