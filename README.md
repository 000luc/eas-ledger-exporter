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

## 用法

```powershell
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx --limit 1
```

参数：
- `--config`：配置Excel路径（必填），需包含"执行期间"和"执行操作的公司"工作表
- `--limit`：限制处理公司数（可选）
- `--dry-run`：仅填写查询条件不导出（可选）

## 开发

```powershell
# 运行测试
pytest -v --cov

# 探测EAS控件树
python scripts/inspect_eas.py
```

## 工作原理

1. 读取 `info.xlsx` 获取年份、月份和公司清单
2. 通过 Java Access Bridge 连接已登录的EAS
3. 对每家公司：填写查询条件 → 执行查询 → 导出Excel → 等待文件完成 → 校验内容
4. 任一失败立即停止，保留现场和截图

不依赖屏幕坐标或图像识别，不占用鼠标键盘。
