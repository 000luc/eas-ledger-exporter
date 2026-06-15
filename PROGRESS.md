# 项目进度与接手说明

更新日期：2026-06-15

本文档供没有历史对话的 agent 直接接手。执行前先读本文档，再读设计和实施计划。

## 项目目标

读取 `D:\内部交易rpa\info.xlsx`，通过 Java Access Bridge 操作金蝶 EAS，批量导出、修复并校验凭证序时簿。任一公司失败后立即停止并保留现场。

## 仓库与工作目录

- 项目根目录：`D:\BaiduSyncdisk\claude\eas-ledger-exporter`
- 这是独立 Git 仓库，`.git` 位于项目根目录。
- 不要在上级目录 `D:\BaiduSyncdisk\claude` 执行本项目 Git 命令。
- 分支：`codex/eas-ledger-exporter`
- 本文档扩充前的基线提交：`76714b3`。实际最新提交以 `git log -1 --oneline` 为准。
- 远端分支：`origin/codex/eas-ledger-exporter`
- 本地与远端差异以 `git status --short --branch` 为准；本文档提交前本地领先 1 个提交。
- `README.md`、`CLAUDE.md` 当前是未跟踪文件，来源不明。未确认前不要删除、覆盖或提交。

检查命令：

```powershell
cd D:\BaiduSyncdisk\claude\eas-ledger-exporter
git status --short --branch
git log -5 --oneline
```

## 当前状态

- 自动测试：任务 5 定向测试 8 项通过，全量 133 项通过
- EAS 环境：已证明 JAB 能识别金蝶 EAS 原生控件
- 总进度：任务 1、2、3、4、5 完成；任务 6-8 未开始

基线验证：

```powershell
.venv\Scripts\pytest tests/test_validation.py -q
.venv\Scripts\pytest -q
```

预期分别为 `8 passed`、`133 passed`。

## 环境与外部依赖

- 操作系统：Windows，PowerShell。
- Python：必须使用项目 `.venv` 中的 Python 3.11。
- 依赖：`openpyxl==3.1.5`、`rpaframework==32.0.0`。
- 配置文件：`D:\内部交易rpa\info.xlsx`。
- 历史导出样本：`D:\内部交易rpa\序时账`。
- EAS安装目录：`D:\Kingdee\eas`。
- EAS客户端Java：`D:\Kingdee\eas\clientjdk\bin\javaw.exe`，32位 Java 6。
- JAB DLL：`D:\Kingdee\eas\oracle_jdk1.8\jre\bin\WindowsAccessBridge-64.dll`。
- JAB启用命令：

```powershell
& 'D:\Kingdee\eas\oracle_jdk1.8\bin\jabswitch.exe' -enable
```

虽然EAS是32位Java 6，现有64位Python/JAB DLL已在本机真实连接成功，不要仅根据位数推断不可用。

### EAS启动注意

`D:\Kingdee\eas\client\bin\client.bat` 是官方入口，但从自动化Shell直接调用时，旧批处理的相对 `set-client-env.bat` 曾未生效，导致环境变量为空。不要盲目重复启动。

已验证可用的方法是读取 `set-client-env.bat` 中的参数，直接启动：

- 更新服务器：`172.18.0.148:8080`
- EAS服务器：`tcp://172.18.0.148:11033`
- 主类：`com.kingdee.eas.tools.bodyguard.BodyguardDlg`

一般情况下不要自动关闭或重启EAS。需要重启前先确认用户没有未保存操作。EAS登录必须由用户完成。

## 核心技术决策

- 只使用 Java Access Bridge 定位和操作EAS控件。
- 禁止以固定屏幕坐标或图像识别作为主流程。
- 旧Java 6会返回损坏的版本/快捷键字符串，`scripts/inspect_eas.py` 已做局部兼容和清理。
- “财务会计”分类标签本身没有稳定暴露名称；目前以EAS原生“凭证查询”“标准凭证引出”证明内部控件可访问。
- 未实际看到的控件不能伪造定位器，必须在 `config/eas-locators.json` 标为 pending。
- 每项任务按 TDD 实施，之后必须依次做规格符合性复核、代码质量复核；复核问题未关闭不能进入下一任务。
- 不读取或修改 `D:\内部交易rpa\info.xlsx` 和历史序时账样本，除非是只读测试。

## 已完成

### 任务 1：项目环境与 JAB 控件探测

- 建立 Python 3.11 虚拟环境和项目依赖。
- 启用 Java Access Bridge。
- 兼容 EAS 使用的 Java 6 异常数据。
- 真实识别 EAS 窗口及原生“凭证查询”“标准凭证引出”控件。
- 导出真实控件树到 `artifacts/eas-controls.txt`。
- 已验证定位器写入 `config/eas-locators.json`。
- 探测脚本具备原子写入、资源清理和状态恢复测试。
- 已通过规格复核和代码质量复核。

### 任务 2：配置读取

- 建立 `Company`、`ExportConfig` 不可变模型。
- 读取期间、输出路径和启用公司。
- 公司编号统一为三位 ASCII 数字。
- 严格校验年份、月份、公司、执行标志、重复编号和损坏工作簿。
- 保证文件句柄关闭，错误统一为中文 `ConfigError`。
- 真实读取现有配置：2025 年 9 月、27 家公司。
- 已通过规格复核和代码质量复核。

### 任务 3：文件命名与完成等待

已完成：

- 建立 `ExportJob`，输出六位期间 `YYYYMM`。
- 校验 Windows 文件名、保留设备名和长度。
- 等待文件存在、非空并连续稳定。
- 使用文件大小和修改时间作为稳定指纹。
- 实际读取 XLSX 关键 ZIP 成员并检查 CRC。
- 区分临时文件锁和永久文件错误。
- 超时错误包含路径、秒数和最后状态。
- 校验 XLSX 后再次读取 `stat()`，使用校验后指纹判断稳定，避免校验期间文件写入导致误判。

相关提交：

- `af1bb04`：初版文件命名与等待。
- `47fbe74`：读取失败后重置稳定状态。
- `475b126`：验证完整XLSX。
- `42e079f`：实际读取关键ZIP成员并细分文件错误。
- `d4c1da4`：使用校验后指纹判断稳定。

### 任务 4：XLSX 工作表范围修复

已完成：

- 实现 `repair_dimension()` 修复 EAS 导出文件错误的 `dimension ref="A1"`。
- 流式扫描 `xl/worksheets/sheet1.xml` 中 `<c r="..."/>` 坐标，定位实际最后单元格。
- 将 `dimension` 更新为 `A1:列标行号`（例如 `A1:AB12345`）。
- 使用临时目录、临时 XLSX 文件和原子替换，保留工作簿其他内容。
- 处理缺少工作表和空工作表错误，统一抛 `WorkbookRepairError`。

### 任务 5：导出内容校验

已完成：

- 实现 `validate_export()`，校验导出文件内容。
- 校验 28 列标准表头（基于真实 EAS 导出样本）。
- 校验公司、期间和数据行。
- 跳过全空行，区分空数据与非空数据。
- 期间格式统一按 `.` 拆分后比较 `(year, month)`，支持 `2026.5` 与 `2026.05`。

## 立即继续的位置

任务 5 已完成。当前开始任务 6：EAS 自动化。

任务 6 要点：

1. 打开凭证查询。
2. 设置公司、起止期间和全部状态。
3. 查询凭证序时簿。
4. 右键执行“导出到 Excel”。
5. 处理导出向导和下一家公司切换。
6. 未经验证的定位器（如“条件查询”“导出”）必须在 EAS 对应窗口现场探测，不得伪造。

完成命令：

```powershell
.venv\Scripts\pytest tests/test_runner.py -q
.venv\Scripts\pytest -q
git diff --check
```

然后进行独立代码质量复核。复核通过后：

1. 更新本文档，将任务 6 标为完成。
2. 提交代码和文档。
3. 开始任务 7。

## 未完成

### 任务 6：EAS 自动化

- 打开凭证查询。
- 设置公司、起止期间和全部状态。
- 查询凭证序时簿。
- 右键执行“导出到 Excel”。
- 处理导出向导和下一家公司切换。
- 当前“条件查询”“导出”定位器仍需在对应窗口现场探测。
- 现场探测需要EAS已登录并进入相应窗口；不要根据截图猜定位器。

### 任务 7：总流程、失败停止与日志

- 串联配置、EAS 查询、导出、等待、修复和校验。
- 任一步失败立即停止。
- 保存文本日志、CSV 汇总和失败截图。

### 任务 8：CLI、文档与现场验收

- 完成正式命令行入口。
- 编写运行说明。
- 依次完成 1 家、3 家和全部公司现场验收。
- 验证运行期间不持续占用鼠标和键盘。

## 下一步

1. 实现任务 6：封装 EAS Java 控件操作（eas_client.py）。
2. 实现任务 7：串联运行、失败停止与日志（runner.py, reporting.py）。
3. 实现任务 8：CLI 入口、README 与现场验收。

## 重要文件

- 设计：`docs/superpowers/specs/2026-06-08-eas-ledger-exporter-design.md`
- 实施计划：`docs/superpowers/plans/2026-06-08-eas-ledger-exporter.md`
- 控件树：`artifacts/eas-controls.txt`
- 定位器：`config/eas-locators.json`
- 配置读取：`src/eas_ledger_exporter/config.py`
- 文件任务模型：`src/eas_ledger_exporter/models.py`
- 文件稳定等待：`src/eas_ledger_exporter/file_wait.py`
- 当前任务测试：`tests/test_file_wait.py`

## 执行纪律

- 先检查工作区，保留用户未提交文件。
- 手工编辑使用 `apply_patch`。
- 出错后不要盲目重复；先查具体报错，技术问题优先查官方文档或GitHub。
- 每个实现任务单独提交，提交时避免根仓库曾出现的自动GC卡顿：

```powershell
git -c maintenance.auto=false -c gc.auto=0 commit -m "<message>"
```

- 不要把 `.venv`、`.coverage`、`jab_wrapper.log`、缓存文件提交。
- 不要把当前通过的119项测试当作任务3已完成证据；已知竞态尚未修复。
