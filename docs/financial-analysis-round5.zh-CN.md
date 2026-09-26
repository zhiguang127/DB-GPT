# 第 5 轮：真实 PDF 来源预览

2026-09-25。已接通指标证据到原始 PDF 物理页的预览、翻页和下载，并修复会话文件在服务重启后无法读取的问题。mock 数据、CSS、Skill HTML/Markdown 模板及 Qwen `.env` 配置未改动。

## 本轮开始前的分批提交

原有第 1–4 轮修改已在 `feat/financial-analysis-demo` 分成四个本地提交，未推送远端：

| 提交 | 内容 |
| --- | --- |
| `993a0b9f` | PDF 事实提取、来源页码和样本回归 |
| `9e9150e1` | 后台任务、Decimal 计算和报告持久化 |
| `52c1df9f` | 真实报告页面、数据入口及前端回归 |
| `dabe2fd6` | 第 1–4 轮计划与验证记录 |

2026-09-26：第 5 轮后端 20 项回归再次通过，本轮修改整理为独立本地提交。当前未连接可操作的浏览器，鼠标交互验收仍待用户核对。

## 使用入口与核对方法

- [上传并分析](http://localhost:3000/financial-analysis)
- [原有演示](http://localhost:3000/financial-analysis?demo=1)
- [安靠智电](http://localhost:3000/financial-analysis?run_id=601d9b81-e12d-4721-93d4-4f06d1d98a0a&session_id=financial-run-check-ab76076901464a6db4fb176ea37a1946)
- [海翔药业](http://localhost:3000/financial-analysis?run_id=0029cf86-bc9a-42dd-838f-a84a520d0bd5&session_id=financial-run-check-2c77535c2715483dae87062278a29269)

样本报告归匿名开发用户 `001`；其他登录用户需自行上传。点击指标，在证据面板选取来源，再打开来源预览。上方展示原 PDF 页面图像，下方保留原文摘录；可输入物理页码、前后翻页，以及跳到该证据记录的表头页和单位声明页。页码从 PDF 第 1 页开始，不能假定等于印刷页码。下载按钮返回原始 PDF。

原文件缺失或渲染失败时显示原因、重试入口、文件名和页码，摘录仍保留。没有精确区域高亮、OCR 或 PDF 文本选择；可下载原文件放大核对。

## 接口与实现边界

新增接口共用 `/api/v1/financial-analysis` 前缀及现有身份校验：

| GET 接口 | 返回 |
| --- | --- |
| `/runs/{run_id}/documents/{document_id}/pages/{page_number}?session_id=...` | 原 PDF 指定物理页的 PNG |
| `/runs/{run_id}/documents/{document_id}/download?session_id=...` | 原始 PDF 附件 |

来源文档必须属于该报告及其上传文件，用户和会话必须一致；校验报告快照与上传记录 SHA-256，渲染前进一步校验物化文件内容。响应禁止缓存。前端沿用共享 HTTP 客户端传递认证信息，切换页面会取消旧请求并释放对象 URL。

渲染复用已安装的 `pypdfium2`，由固定子进程执行，单页限时 20 秒、最多同时渲染 2 页，图像最长边限制为 1800 像素。子进程退出后清理物化文件；超时或失败不占用后续渲染名额。当前没有页面缓存，连续翻页会重复读取原文件。

## 重启后原文件不可用的修复

联调发现：会话文件服务在 `init_app` 阶段创建 fallback 客户端，此时共享文件服务尚未在 `after_init` 注册持久化客户端。fallback 的文件元数据在内存中，导致数据库仍有上传记录、报告仍可读取，但重启后无法打开 PDF。

修复为在 `before_start`、接受请求前，将 fallback registry 绑定到已经注册的共享持久化客户端。显式注入的客户端和 registry 保持不变。新增生命周期回归覆盖晚注册绑定、实际上传落点以及显式客户端保留。

修复不会恢复旧内存索引。第 4 轮旧报告的保存结果仍可读，其原文件不可用；本页链接来自修复后重新上传的样本。已经实测使用同一组新 run/file ID，重启服务后再次预览及下载，无需重新上传。

## 验证结果

- 后端财务分析及文件服务生命周期：20 项测试通过。涵盖物理页定位、范围检查、用户/会话/文档隔离、内容不一致、原文件删除、超时后的清理和恢复。
- 两份真实 PDF 重新上传、提取、计算及保存通过：25 个金额基准值，每份 8 项计算。
- 重启前后，均验证两份原文件下载字节与用户 PDF 完全相同，并检查以下六页；逐张检查图像，表格与指标值可读。

| 样本 | 营收来源页 | 负债合计来源页 | 经营现金流来源页 |
| --- | ---: | ---: | ---: |
| 安靠智电 | 8 | 164 | 175 |
| 海翔药业 | 7 | 80 | 89 |

- 前端原演示、替换/空数据、两份真实报告渲染与指标证据导航回归通过；新增来源控件渲染和表头/单位页去重检查通过。
- ESLint、Ruff、离线构建通过。TypeScript 对比第 4 轮提交基线仍为 138 项已有错误，本轮新增 0 项。
- 上传页、演示页和两份真实报告的 Next 编译及 HTTP 200 检查通过。未完成浏览器鼠标交互与整体布局验收，接口和 SSR 测试不替代该项验收。

复现命令（项目根目录，本地后端需已启动）：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -m pytest packages/dbgpt-serve/src/dbgpt_serve/financial_analysis/tests packages/dbgpt-serve/src/dbgpt_serve/session_file/tests/test_serve.py -q
.venv/Scripts/python.exe scripts/financial_analysis_run_check.py --base-url http://127.0.0.1:5670 --keep --output-dir .work/financial-analysis/round5
.venv/Scripts/python.exe scripts/financial_analysis_preview_check.py
# 重启后端后再次执行 preview_check，使用保存的同一组 ID
node standalone/financial-analysis/test-data.cjs .work/financial-analysis/round5/ankao-report.json .work/financial-analysis/round5/haixiang-report.json
node standalone/financial-analysis/build.cjs .work/financial-analysis/demo-round5.html
```

PNG、报告 JSON、任务链接与验证摘要保存在被忽略的 `.work/financial-analysis/round5/`，PDF 和密钥不进入提交。重新运行上传脚本会创建新的报告，最新链接以该目录的 `runs.json` 为准。

## 下一任务

第 6 轮扩展费用、流动资产/负债和存货等事实与计算，基于阿里 Qwen 生成带有效引用的结构化分析，填充现有五个章节。真实追问留在第 7 轮。第三家独立样本及用户人工核对仍待补充。
