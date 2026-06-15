# 金蝶EAS批量序时账导出工具

通过 Java Access Bridge 操作金蝶EAS客户端，批量导出多家公司的凭证序时簿。

## 安装

```powershell
uv venv --python 3.11
uv pip install -e ".[dev]"
```

## 前提

- 金蝶EAS已登录
- Java Access Bridge已启用（`jabswitch -enable`）
- Python 3.11

启用 JAB：

```powershell
& 'D:\Kingdee\eas\oracle_jdk1.8\bin\jabswitch.exe' -enable
```

## 用法

```powershell
# 全部公司
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx

# 只处理前 3 家
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx --limit 3

# 干运行：只列出将处理的公司，不操作 EAS
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx --dry-run
```

参数：

- `--config`：配置Excel路径（必填），需包含"执行期间"和"执行操作的公司"工作表
- `--limit`：限制处理公司数（可选）
- `--dry-run`：仅列出公司将处理的公司，不操作 EAS（可选）

## 开发

```powershell
# 运行测试
.venv\Scripts\pytest -q

# 探测EAS控件树
.venv\Scripts\python scripts/inspect_eas.py
```

## 工作原理

1. 读取 `info.xlsx` 获取年份、月份和公司清单
2. 通过 Java Access Bridge 连接已登录的EAS
3. 对每家公司：填写查询条件 → 执行查询 → 导出Excel → 等待文件完成 → 修复 XLSX 维度 → 校验内容
4. 任一失败立即停止，保留现场、截图和 CSV 汇总

不依赖屏幕坐标或图像识别，不占用鼠标键盘。

## 输出

每次运行在当前目录 `logs\YYYYMMDD-HHMMSS` 下生成：

- `run.log`：文本运行日志
- `summary.csv`：公司执行汇总
- `{公司编号}_{期间}_{时间}.png`：失败时的 EAS 窗口截图

## 注意事项

- 运行期间不要关闭 EAS
- 失败时保留 EAS 当前窗口，供人工检查
- 未经验证的 EAS 定位器列在 `config/eas-locators.json` 的 `pending_locator_keys` 中
