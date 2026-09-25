# 财报分析第 1 轮：本地运行与验收

更新：2026-09-24。对应[八轮开发计划](financial-analysis-development-plan.zh-CN.md)的第 1 轮。

## 当前结果

- `web/new-components/financial-analysis/`、mock 数据、CSS、Skill HTML 模板和离线 demo 均未修改。
- 本机 Python 3.11 虚拟环境可以加载 DB-GPT、FastAPI、httpx、pdfplumber；Node 为 24.19.0，前端依赖已安装。
- 用现有 Next 开发服务请求 `/financial-analysis/` 得到 HTTP 200；自动化接口未发现可连接浏览器，尚未做浏览器交互验收。
- 已用真实 312 页 PDF，通过现有 session-file API、真实 SQLite、真实本地存储和 PDF 检查器验证上传、列表、预览、下载字节一致、错误会话 404，以及聊天附件读取和回合结束后的临时文件清理。隔离验证不连接业务数据库。
- 预览返回 `ready`、`truncated=true`：这是有界预览，不是完整财报提取结果。
- 已启动完整 Qwen 后端（5670），确认注册模型为 `qwen-plus`，真实聊天返回指定测试文本；正式 HTTP 文件上传、预览、下载字节一致和错误会话 404 均通过。
- 已通过 `POST /api/v1/chat/react-agent` 验证真实附件 → `execute_skill_script_file` → `extract_financials.py` → `terminate`，收到完成的 `final`、`done` 事件。营收、归母净利润结果与本表一致，但总资产、总负债有误，见下面的回归记录。
- **第 1 轮技术链路已接通；尚待浏览器交互验收与用户人工核对。** 已确认使用阿里 Qwen，沿用 `configs/dbgpt-proxy-tongyi.toml`，密钥通过根目录 `.env` 提供。Embedding 配置已加载，本轮没有单独做向量调用验收。旧脚本能运行不代表其提取准确，财报页面当前仍使用 mock。

## 入口和调用链

| 环节 | 实际入口 | 本轮确认的边界 |
| --- | --- | --- |
| 财报页面 | `web/pages/financial-analysis/index.tsx` → `FinancialAnalysisPage` | 当前直接导入 mock；上传不会自动改变此页面 |
| 上传入口 | 首页 `/` 的聊天输入框附件按钮或拖入文件 | `web/modules/session-files/api.ts` 上传表单包含 `session_id`、`files` |
| 文件 API | `/api/v1/agent/files` | `user-id` 确定 owner；列表、预览、下载都要同一 `session_id`；有 API key 配置时还需 Bearer token |
| Agent | `POST /api/v1/chat/react-agent` | `conv_uid` 必须与上传 `session_id` 一致，请求使用 `file_ids`，不混用旧 `file_path` |
| 附件读取 | `attachment_react_adapter.prepare_react_attachments` → `open_session_attachments` | 文件在当前回合物化，结束后清理；后续后台任务不可保存这个临时路径继续使用 |
| Skill | `tools/skill_tools.make_execute_skill_script_file` → SkillManager | 主 ReAct 工具会把路径参数换为本轮实际附件路径；`subagent/react_tools.py` 另有工具执行路径，也需后续联调 |
| Skill 目录 | `DBGPT_SKILLS_DIR` → 源码目录 `skills/` → 用户目录 | 本地开发显式设置仓库 `skills`，避免调用到另一份技能 |
| 离线演示 | `node standalone/financial-analysis/build.cjs` | 继续使用 mock，不连接后端；本轮无需重建交付 HTML |

## 最短运行步骤（PowerShell）

以下命令从仓库根目录运行。使用现有依赖，不重新同步整套环境。

前端终端：

```powershell
Set-Location web
$env:NODE_OPTIONS = '--max_old_space_size=8192'
node node_modules/next/dist/bin/next dev --hostname 127.0.0.1
```

打开 `http://127.0.0.1:3000/financial-analysis/` 查看原 mock；打开 `http://127.0.0.1:3000/` 使用真实聊天上传。直接调用 Next 避开 `package.json` 中不适用于 PowerShell 的 POSIX 环境变量赋值语法。API 当前指向 `127.0.0.1:5670`。

后端使用阿里 Qwen。编辑仓库根目录 `.env`（不是 `web/.env`），填写：

```dotenv
DASHSCOPE_API_KEY=你的阿里百炼API密钥
```

本地 `.env` 已准备好空密钥位置及开发目录配置，且被 Git 忽略。不要把密钥发到聊天或提交仓库。已有 TOML 配置使用 `qwen-plus` 和 `text-embedding-v3`，均读取 `DASHSCOPE_API_KEY`。

在仓库根目录启动后端：

```powershell
uv run --env-file .env --no-sync dbgpt start webserver --config configs/dbgpt-proxy-tongyi.toml
```

`--env-file .env` 显式加载文件，`--no-sync` 复用现有虚拟环境。直接调用 `dbgpt.exe` 不会自动加载这份 `.env`。已使用本地密钥启动并验证 Qwen 响应，检查过程不打印密钥。若受限执行环境无法写入 uv 全局缓存，可在 `uv` 后加入 `--cache-dir .work/financial-analysis/uv-cache`。

本机 `.env` 已补充 `PYTHONIOENCODING=utf-8`：Windows 默认 GBK 在重定向启动日志时无法编码启动图标，会在启动服务前退出；UTF-8 配置解决了此问题。

`.env` 中的 `DBGPT_SKILLS_DIR` 指向本仓库技能；`DBGPTS_HOME`、`DBGPTS_REPO_HOME` 把 CLI 自动创建的 dbgpts 目录放入项目临时目录，移动仓库后需更新这些路径。不设置时本机受限执行环境曾因不能创建 `~/.dbgpts` 而报错。Next worker 和 PDF 检查器均使用子进程；受限沙箱可能出现 `spawn EPERM` / `WinError 5`，本次在允许子进程的环境中验证通过，没有修改隔离机制。

## 固定真实样本

使用[巨潮资讯原始 PDF：安靠智电 2019 年年度报告（更新后）](https://static.cninfo.com.cn/finalpage/2020-01-21/1207277424.PDF)。该文件与 mock 的公司、年度一致，但核对数字直接取自原 PDF。

```powershell
New-Item -ItemType Directory -Force .work/financial-analysis | Out-Null
Invoke-WebRequest -Uri 'https://static.cninfo.com.cn/finalpage/2020-01-21/1207277424.PDF' -OutFile .work/financial-analysis/ankao-2019.pdf
Get-FileHash .work/financial-analysis/ankao-2019.pdf -Algorithm SHA256
```

- 页数：312；物理页码从 1 开始。本表引用的物理页与印刷页码相同。
- SHA-256：`2545a81118d4e9a547bd6770bb467065c70696fad9b3fb77ef75186bbc64dd4e`。
- PDF 和页面图片只保存在忽略目录，不加入源码。

以下为 AI 阅读原 PDF 渲染页后的核对基线，**待用户人工确认**。金额单位人民币元，保留两位小数；不得作为真实模式的兜底值。年度流量比较 2019/2018 全年；期末余额比较 2019-12-31/2018-12-31。

| 指标 | 期间类型 | 口径 | 2019 | 2018 | 物理页 |
| --- | --- | --- | ---: | ---: | ---: |
| 营业收入 | 全年 | 合并 | 318,024,319.30 | 320,070,653.13 | 8 |
| 归母净利润 | 全年 | 合并、归属于上市公司股东 | 63,616,426.50 | 75,275,286.09 | 8 |
| 扣非归母净利润 | 全年 | 合并、归属于上市公司股东、扣非 | 47,853,754.35 | 65,201,451.76 | 8 |
| 经营活动现金流量净额 | 全年 | 合并 | 36,228,660.52 | 58,318,179.79 | 8 |
| 总资产 | 年末 | 合并 | 1,050,566,795.15 | 1,060,545,382.44 | 8 |
| 总负债 | 年末 | 合并 | 222,045,561.29 | 204,119,281.03 | 164（表头期间见 161） |
| 加权平均净资产收益率 | 全年 | 直接披露，单位 % | 7.77 | 9.06 | 8 |

额外负数回归候选：第 8 页 2017 年合并经营现金流净额 `-21,008,592.71` 元。注意第 167 页母公司负债不应代替第 164 页合并负债；ROE 不使用净利润/期末权益冒充。

### 真实 Skill 执行发现的旧提取器错误

2026-09-24 使用同一 PDF，经正式上传与 Agent 工具调用取得以下结果。当前脚本使用全文首个正则匹配，缺少页级证据与表格期间定位；留待计划第 3 轮改造，不在本轮以样本数字修补正则或添加兜底。

| 字段 | 旧脚本返回（元） | 原 PDF 基线（元） | 问题 |
| --- | ---: | ---: | --- |
| `total_assets` | 73,992,141.9 | 1,050,566,795.15 | 抓到了货币资金附近数值，而非总资产，且数值精度也不完整 |
| `total_liabilities` | 199,521,915.12 | 222,045,561.29 | 抓到流动负债合计，遗漏非流动负债 |

营收 `318,024,319.30`、归母净利润 `63,616,426.50`、经营现金流 `36,228,660.52` 与第 8 页一致；这不代表其他指标或其他公司的报告已验证。

## 可重复的文件链路检查

不依赖模型或完整服务，使用真实文件组件的隔离检查：

```powershell
.venv/Scripts/python.exe scripts/financial_analysis_smoke.py --isolated --pdf .work/financial-analysis/ankao-2019.pdf
```

已启动后端后，复用同一检查走真实 HTTP：

```powershell
.venv/Scripts/python.exe scripts/financial_analysis_smoke.py --base-url http://127.0.0.1:5670 --owner 001 --pdf .work/financial-analysis/ankao-2019.pdf
```

同时验证真实模型和 Agent Skill（会产生少量模型请求，执行旧提取脚本，不生成图表或 HTML）：

```powershell
.venv/Scripts/python.exe scripts/financial_analysis_smoke.py --base-url http://127.0.0.1:5670 --model qwen-plus --check-skill --pdf .work/financial-analysis/ankao-2019.pdf
```

`--model` 检查实际回复中的随机测试标记，不将 HTTP 200 或模型注册视作响应成功。`--check-skill` 额外要求对应工具调用完成、返回结构化提取结果和完整终止事件。`extraction_accuracy` 保持 `not_checked`，不能把链路验收误读成准确性验收。测试会话及工具执行记录会保留在应用历史中，本次上传的 PDF 在检查结束后删除。

若后端要求 API key，在当前终端设置 `DBGPT_SMOKE_API_KEY`，脚本读取它作为 Bearer token，不打印密钥。脚本创建随机测试会话，在 `finally` 中删除本次上传的文件，不清理已有用户文件。在线模式不验证服务端临时路径生命周期；输出明确标记 `not_checked`。脚本失败返回非零退出码，不将失败标记为通过。

待完成的浏览器验收：在首页选择 Qwen，新建会话上传上述 PDF，要求调用 `financial-report-analyzer` 读取报告。核对附件列表、执行记录与回答是否正常展示。后端 API 路径已验证，但尚未由自动化浏览器操作 UI。旧提取脚本目前仍属于待改造实现，其输出不能代替本表基线，也不能证明财报页面已连接真实结果。

## 本轮交接

- 已完成：入口梳理、真实样本与核对表、文件/模型/Skill 检查脚本、前端 HTTP 可访问、Qwen 后端及 Agent 附件链路联调。
- 当前缺口：浏览器交互与用户人工核对；旧提取器存在指标行误匹配，属于第 3 轮已知任务。
- 下一任务：第 2 轮，定义 `ReportData` 并保留 mock 作为离线数据源；不调整现有视觉设计。
- 静态检查：`.venv/Scripts/ruff.exe check scripts/financial_analysis_smoke.py`；`.venv/Scripts/ruff.exe format --check scripts/financial_analysis_smoke.py`。
