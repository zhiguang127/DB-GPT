# 第 9 轮：表格结构、期间与重述口径

分支 `feat/financial-analysis-round9`，起点 `12ee1a17`。本轮实现及测试已完成，按提取逻辑与基准、报告审计保存、开发文档三批提交。发布标识为 `financial-analysis/round9-extraction-alpha`，定位为 Alpha 预发布；用户核对待完成。

## 范围与结果

本轮执行上一阶段计划的第 9 轮，只修提取基础、第三份样本和报告审计保存。主表全部科目扩展、附注检索、质量覆盖率展示和模型分析深化留在后续轮次。

| 项目 | 第 8 轮最终状态 | 第 9 轮结果 |
| --- | --- | --- |
| 长缆正式数值 | 2 个经营现金流值 | 32 个数值：2023 年 15 个、2022 年 11 个、2021 年 6 个 |
| 已有公式 | 1 项可计算 | 24 项可计算，没有增加公式或补造输入 |
| 调整前/后 | 遇到子表头停止使用该区块 | 坐标与年份子列对应明确时选择调整后，保留调整前记录 |
| 期初余额 | 未识别 | 独立保留 6 项 2023-01-01 余额，不转换成 2022 年末事实 |
| 核对基准 | 原两家公司 57 项 | 原 57 项 + 长缆 42 项均通过 |

32 个数值是固定 15 类指标在不同年份的结果，不等于完整年报，也不是 32 种指标。未将独立保存的期初、调整前金额加入“正式数值”计数。

## 修改内容

### 坐标映射与跨页

新增 `table_structure.py`，按金额单元格横向范围恢复列对应，合并 PDF 空白边距形成的伪列；保留原始 `rows`、`cellBoxes` 和归一化列的 `sourceCells` 映射。多层年份表头只在其实际覆盖范围内展开，多个金额列重叠或单元格归属不明确时拒绝映射。

后续页继承表头时，检查报表范围、章节和归一化列位置，不再只依赖数组列数。合并、母公司报表分别处理。对于下一页落在科目列内、且拼接后能确认指标名称的文字片段，连接跨页科目名称；保留金额所在页和标签续页的来源。长缆第 7/8 页“归属于上市公司股东的净资产（元）”由此恢复。

原始单元格和结构映射可通过提取校验脚本的开发产物检查；它们没有全部塞入模型上下文。报告中正式值的来源保留金额单元格坐标、表头及子表头、期间和跨页标签记录。

### 期间与重述

`sourcePeriod` 明确区分年度列、期末日期、期初日期，另记录 `unspecified/before/after` 调整属性。只有能对应年份和列范围的显式“调整前/调整后”才启用；未知口径、无法区分的重复年份列不作确定值。

期初值和调整前值进入 `sourceObservations`，与用于计算的 `facts` 分离。正式报告新增可选审计信息 `extractionAudit`，保存这些观测值及表格问题，JSON 导出会保留；现有页面不增加布局。审计记录不会进入现有 Qwen 事实上下文或计算输入。

长缆 2022 年总资产现在使用第 7 页明确披露的调整后金额 2,219,763,827.15 元。第 67 页的 2023 年期初金额即使数值相同，也独立保存，不能据此把其他期初余额自动当作上年末。

长缆 2022 年总负债、流动资产、流动负债、存货仍保持缺失：本次识别出的对应主表列是 2023-01-01，尚未建立期初与上年末的口径对齐。这是保留边界，不是把这些项目认定为未披露或为零。

### 基准与集成

新增 `changlan-baseline.json`：原 PDF 的 SHA-256、物理页码、32 个正式金额、6 个期初金额、4 个不同于调整后值的调整前金额，以及不能冒充上期末的缺项断言。金额依据原页图像核对，属于 AI 核对，仍待用户复核。

原基准文件保持两份用户样本。提取与任务校验脚本新增 `--baseline` 参数，可单独验证第三份样本，不改变原默认命令。任务校验还检查期初记录持久化、重复读取、归属隔离和导出 JSON 与报告一致。

## 已完成的验证

- 100 项相关测试通过，覆盖原有任务、分析、问答、导出，以及本轮坐标映射、空值不串列、显式调整后选择、未知口径拒绝、期初隔离、跨页标签、母公司排除、冲突保留和审计数据不进入模型上下文。
- 原两份 PDF 的 57 个金额基准通过；长缆的 42 项新增金额/口径基准通过，并验证三张合并主表所在页及来源引用。
- 使用真实文件上传和真实提取子进程，在临时数据库/存储的 TestClient 栈中完成长缆任务，保存报告、重新读取、生成并下载 JSON；32 个正式值、24 项计算及期初审计记录通过检查。
- Ruff 与 `git diff --check` 通过。
- 前端组件、mock 数据、CSS、离线导出组件和 Qwen 调用代码没有改动。本轮没有重跑模型质量评测或浏览器视觉验收，也未重新运行全仓 TypeScript 检查。
- 没有启动或停止日常 3000/5670 服务，也没有创建 5671 监听服务；API 测试使用进程内 TestClient，退出后释放临时文件和数据库。

原样本基准：

```powershell
.venv/Scripts/python.exe scripts/financial_analysis_extract_check.py --output-dir .work/financial-analysis/round9/final-originals
```

第三份样本基准：

```powershell
.venv/Scripts/python.exe scripts/financial_analysis_extract_check.py --baseline skills/financial-report-analyzer/tests/changlan-baseline.json --pdf-dir .work/financial-analysis/round8 --output-dir .work/financial-analysis/round9/final-samples
```

隔离任务与 JSON 导出检查，不调用模型：

```powershell
.venv/Scripts/python.exe scripts/financial_analysis_run_check.py --baseline skills/financial-report-analyzer/tests/changlan-baseline.json --pdf-dir .work/financial-analysis/round8 --output-dir .work/financial-analysis/round9/api
```

样本仍为[巨潮资讯公开的长缆科技 2023 年报](https://static.cninfo.com.cn/finalpage/2024-03-15/1219307390.PDF)，保存在 `.work/financial-analysis/round8/changlan-2023.pdf`。原页图像、提取结构、结果和集成测试输出位于被忽略的 `.work/financial-analysis/round9/`；不会提交 PDF、数据库、凭证或生成的报告文件。

## 验收方式与下一轮

用户更新后端代码后，重新上传或显式重新分析长缆年报，核对本期收入、归母净利润、总资产、流动资产和费用。旧历史报告、旧 revision 和已生成导出不重写，因此原第 8 轮失败样本不会自动变成新结果。

下一轮为完整三表提取：在当前结构层上保存合并资产负债表、利润表、现金流量表的全部披露科目，包括暂时不能标准化的行，再映射到计算事实。随后建立独立覆盖率/勾稽检查，再扩展重点附注与 Qwen 分析。现有 `evidenceCoverage` 仍只表示已提取值的来源完整性，本轮未将其改成提取覆盖率。
