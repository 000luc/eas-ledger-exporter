# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# 全部测试
.venv\Scripts\pytest -q

# 单个测试文件
.venv\Scripts\pytest tests\test_file_wait.py -q

# 单个测试
.venv\Scripts\pytest tests\test_config.py::test_load_config_preserves_company_code_and_filters_disabled -v

# 安装/重新安装（开发模式）
uv pip install -e ".[dev]"

# 探测 EAS 控件树（EAS 需已登录，JAB 需启用）
.venv\Scripts\python scripts\inspect_eas.py

# CLI 入口（当前仅打印帮助，主流程未串联）
.venv\Scripts\eas-ledger-exporter --help
```

## 项目目标

本机 Python 工具，读取 `D:\内部交易rpa\info.xlsx`，通过 Java Access Bridge 操作已登录的金蝶 EAS 客户端，批量导出多家公司的凭证序时簿，失败即停。

## 当前状态

- 任务 1、2 已完成并通过规格复核与代码质量复核。
- 任务 3（文件命名与完成等待）已写实现和测试，但存在一个已知竞态，**必须先修复才能进入任务 4**。
- 任务 4–8 尚未开始。
- 基线测试：`tests\test_file_wait.py` 70 项通过，全量 119 项通过。不要把通过测试当作任务 3 已完成的证据；竞态尚未修复。

任务 3 竞态说明与修复要求见 `PROGRESS.md` 的“立即继续的位置”。核心问题：`wait_until_stable()` 在校验 XLSX 前读取 `stat()`，若校验期间文件继续写入，下一轮可能按旧指纹误判稳定。修复需在 validator 之后再次 `target.stat()` 并比对校验前后的 `(st_size, st_mtime_ns)`，不一致则重置稳定计数。

## 架构

代码按“可单元测试的业务逻辑”与“EAS 界面适配”分离：

- `src/eas_ledger_exporter/config.py` — 读取并校验 `info.xlsx`，输出 `ExportConfig`。
- `src/eas_ledger_exporter/models.py` — `Company`、`ExportConfig`、`ExportJob` 三个不可变模型；`ExportJob` 负责生成期间 `YYYYMM` 和 Windows 安全文件名。
- `src/eas_ledger_exporter/file_wait.py` — `wait_until_stable()` 轮询文件直到稳定可读；默认校验 XLSX 的 ZIP 结构和关键成员，处理 Windows 临时锁（error 32/33）。
- `src/eas_ledger_exporter/errors.py` — `ConfigError`、`ExportTimeoutError`、`ExportFileError`。
- `scripts/inspect_eas.py` — 通过 JAB 导出 EAS 控件树到 `artifacts/eas-controls.txt`，含焦点/前台恢复逻辑。
- `config/eas-locators.json` — 已验证的控件定位器；未实际看到的控件标为 `pending_controls`，不得伪造。

尚未实现的模块（按任务 4–8 顺序）：`xlsx_repair.py`（修正错误的 `dimension ref="A1"`）、`validation.py`（表头/公司/期间校验）、`eas_client.py`（JAB 控件操作）、`runner.py`（串联流程与失败停止）、`reporting.py`（CSV 汇总与日志）。

## EAS 环境

- EAS 安装目录：`D:\Kingdee\eas`
- EAS 客户端 Java：`D:\Kingdee\eas\clientjdk\bin\javaw.exe`（32 位 Java 6）
- JAB DLL：`D:\Kingdee\eas\oracle_jdk1.8\jre\bin\WindowsAccessBridge-64.dll`
- 启用 JAB：

  ```powershell
  & 'D:\Kingdee\eas\oracle_jdk1.8\bin\jabswitch.exe' -enable
  ```

- 运行前 EAS 必须由用户登录；运行时不要自动关闭或重启 EAS。
- 控件定位器只写实际通过 JAB 验证的控件；未看到的控件保留在 `pending_controls`。

## Git 与提交

- 分支：`codex/eas-ledger-exporter`
- 项目根目录：`D:\BaiduSyncdisk\claude\eas-ledger-exporter`，不要在上级目录执行 Git 命令。
- 为避免自动 GC 卡顿，提交使用：

  ```powershell
  git -c maintenance.auto=false -c gc.auto=0 commit -m "<message>"
  ```

- 不要提交 `.venv`、`.coverage`、`jab_wrapper.log`、缓存文件。

## 关键实现约定

- 测试通过依赖注入控制时间和 IO：`FakeTime`/`SequenceClock`（clock/sleep）、`monkeypatch`、自定义 `validator`。
- 临时文件写入用 `tempfile.NamedTemporaryFile` + `os.replace` 原子发布。
- 异常链完整保留：主错误不因清理错误被掩盖，清理错误记录到 logger。
- 每项任务按 TDD 实施，之后依次做规格符合性复核、代码质量复核；复核问题未关闭不能进入下一任务。
- 不读取或修改 `D:\内部交易rpa\info.xlsx` 和历史序时账样本，除非是只读测试。
