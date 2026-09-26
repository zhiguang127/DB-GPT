# 第 6C/6D 轮：Qwen 结构化分析、引用校验和失败降级

2026-09-26。已验收的 6A/6B 提交为 `b3fbbaab`。按用户要求，本轮分批本地提交：后端分析及验证为 `733fbbc0`，前端进度、重试及渲染回归为 `4be6d32c`，开发与验收文档单独提交；均未推送。mock 数据、mock 报告、CSS 和旧 Skill 模板均未修改。

## 本轮行为

界面修正（用户反馈后）：删除了报告标题和章节导航之间新增的黄色分析状态横幅。此前虽然未修改 mock 数据文件，却改变了原版报告布局，不符合保留 mock 模板的要求。分析状态复用“执行过程 → 生成并校验模型分析”的现有状态及详情位置，重新读取与重新分析入口仅放在该步骤内，使用已有文字链接样式。后续“保持 mock”同时约束布局和视觉，不能只检查 mock 文件是否变更。

上传后先完成提取和 24 条确定性计算并保存报告，再调用现有模型服务中的 `qwen-plus`。页面先显示财务数据，继续轮询模型阶段。模型完成后更新同一报告的 revision、结论和执行记录。

分析上下文仅包含本期、上期可用事实、计算及相关摘录；上限分别为 60 条事实、40 条计算、100 条摘录，每条摘录最多 600 字符，总序列化长度最多 60000 字符。不会把本地路径、凭证、聊天历史或完整 PDF 加入这一上下文。未新增附注检索。

复用 DefaultLLMClient 和既有 Qwen worker，在应用实际执行的 async_after_start 生命周期绑定服务事件循环。沿用当前 `.env` 和 `configs/dbgpt-proxy-tongyi.toml`，不需要另配密钥。默认模型名为 `qwen-plus`；仅在已注册其他模型时可用 `DBGPT_FINANCIAL_MODEL` 指定名称。

模型必须输出严格 JSON，文本中的数值必须引用 `{{fact:ID}}` 或 `{{calculation:ID}}`，由服务端替换成已有显示值及单位。校验字段、章节、引用存在性、来源归属、计算输入，以及未引用数字和重复单位；不合格条目单独丢弃。全部不合格时最多要求模型纠正一次，两次请求共享 90 秒期限。校验只约束结构、数字来源和引用关系，不证明因果解释、趋势判断或提取数据的语义正确性。

自动生成的每条结论最多标记为 `partial`，或保留 `unresolved`，不能升级成已人工核实。运行层面的分析状态为 `running/completed/partial/failed`；缺少任一分析章节或有条目被拒绝时显示部分分析。概览没有独立结论时可以展示其他章节已通过的结论。

模型超时、不可用或格式校验失败，财务事实、计算和 PDF 来源仍可读取。服务重启会将未完成的模型阶段标为中断，保留数据。“执行过程”的模型分析步骤提供重新读取进度、重新分析此文件；重新分析会创建新任务并重跑提取和计算，不是阶段续跑。业务报告仅保存通过校验的内容及处理后的错误摘要；现有模型 worker 的日志行为未在本轮调整。

原报告兼容，新字段为可选；未增加数据库列，不需要新迁移。旧报告快照不会自动生成结论。

## 实测结果

两份样本通过隔离的本地 5671 服务调用真实阿里 Qwen；使用独立数据库、文件和向量目录，没有改动用户的 3000/5670 服务。验收后已关闭本轮临时后端及其 worker，确认 5671 端口释放。

| 样本 | 分析状态 | 保留结论 | 拒绝条目 | 上传至最终报告耗时 |
| --- | --- | ---: | ---: | ---: |
| 安靠智电 | partial | 2 | 2 | 63.1 秒 |
| 海翔药业 | partial | 1 | 3 | 50.7 秒 |

这次输出未覆盖全部分析章节，不能据此声称五个章节的模型结论全部完成。已接通可用结论及失败降级链路，结论覆盖率与表达质量仍需持续改善。两份报告的事实数据、24 条计算、重复读取和 owner/session 隔离均通过检查；13 个 PDF 物理页可预览，下载字节与原文件一致。

真实调用前，已从公开披露来源核对对应文件：[安靠智电年报](https://static.cninfo.com.cn/finalpage/2020-01-21/1207277424.PDF)、[海翔药业年报](https://static.cninfo.com.cn/finalpage/2020-01-23/1207280406.PDF)。分别核对 8 页、9 页的规范化全文，与本地样本中引用页一致。记录位于忽略目录 `.work/financial-analysis/round6cd/public-verification/verification.json`。

- 后端财务分析、文件服务生命周期和提取器测试：58 项通过，包括模型超时、无效引用、未引用数字、纠正次数限制、重启恢复、数据提前可读和错误信息处理。Windows 子进程管道测试须在允许子进程的执行环境中运行。
- 两份真实模型报告及原 demo 的 SSR 回归通过，结论引用可解析到事实、计算和证据；修正后增加报告页在四种分析状态下 HTML 保持一致的检查，执行步骤的状态、重新读取和重试回调检查通过。
- Ruff、ESLint、离线构建通过；TypeScript 对比原有 138 项错误，本轮新增 0 项。
- 未完成真实浏览器鼠标交互和整页视觉验收；SSR 检查不能替代浏览器验收。结论语义仍待用户核对，第三家样本未补。

## 本地验收

在原后端终端按 Ctrl+C，等待退出后，在项目根目录重新运行原启动命令。避免在旧服务未退出时另起一份：

```powershell
uv run --env-file .env --no-sync dbgpt start webserver --config configs/dbgpt-proxy-tongyi.toml
```

前端开发服务如仍在运行，刷新即可。访问 `http://127.0.0.1:3000/financial-analysis/`，重新上传一份样本生成新报告；旧快照保持原样。观察先出现财务数据，再更新模型结论；逐条点击证据核对来源。部分分析或失败时尝试“重新分析此文件”。原 demo 仍为 `?demo=1`。

本轮生成的报告 JSON 和检查产物位于 `.work/financial-analysis/round6cd/`，属于隔离测试数据库；其中 runs.json 的报告 ID 不能直接用于日常 5670 后端。

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -m pytest packages/dbgpt-serve/src/dbgpt_serve/financial_analysis/tests packages/dbgpt-serve/src/dbgpt_serve/session_file/tests/test_serve.py skills/financial-report-analyzer/tests/test_financial_document.py -q
# 下列命令要求日常后端已运行，会上传两份样本并调用 Qwen
.venv/Scripts/python.exe scripts/financial_analysis_run_check.py --base-url http://127.0.0.1:5670 --keep --check-analysis --output-dir .work/financial-analysis/round6cd-local
node standalone/financial-analysis/test-data.cjs .work/financial-analysis/round6cd-local/ankao-report.json .work/financial-analysis/round6cd-local/haixiang-report.json
```

`--check-analysis` 会等待模型阶段结束并检查存在有效结论；不传此选项只要求数据报告就绪，模型可能仍在后台执行。

## 下一轮

第 7 轮接通真实追问：问题绑定 run ID 和 revision，限定当前报告上下文，回答沿用数字及引用校验，资料不足时明确说明。当前追问入口尚未接入真实模型。
