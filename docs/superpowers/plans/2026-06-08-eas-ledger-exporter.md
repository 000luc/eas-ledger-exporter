# 金蝶EAS批量序时账导出工具 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个本机Python程序，读取现有 `info.xlsx`，通过Java Access Bridge批量操作金蝶EAS导出并校验凭证序时簿。

**Architecture:** 纯业务逻辑与EAS界面适配分离。配置、命名、文件完成判断、XLSX修复和校验均可脱离EAS单元测试；`EasClient` 封装Java控件操作；`ExportRunner` 串联任务并在首个错误处停止。

**Tech Stack:** Python 3.11、RPA.JavaAccessBridge（`rpaframework==32.0.0`）、openpyxl、pytest、标准库 argparse/logging/zipfile/XML。

---

## 文件结构

```text
eas-ledger-exporter/
├── pyproject.toml
├── README.md
├── config/eas-locators.json
├── scripts/inspect_eas.py
├── src/eas_ledger_exporter/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── eas_client.py
│   ├── errors.py
│   ├── file_wait.py
│   ├── models.py
│   ├── reporting.py
│   ├── runner.py
│   ├── validation.py
│   └── xlsx_repair.py
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_file_wait.py
    ├── test_runner.py
    ├── test_validation.py
    └── test_xlsx_repair.py
```

### Task 1: 建立项目环境并验证EAS可访问性

**Files:**
- Create: `pyproject.toml`
- Create: `scripts/inspect_eas.py`
- Create: `config/eas-locators.json`

- [ ] **Step 1: 创建依赖配置**

```toml
[project]
name = "eas-ledger-exporter"
version = "0.1.0"
requires-python = ">=3.11,<3.12"
dependencies = [
  "openpyxl==3.1.5",
  "rpaframework==32.0.0",
]

[project.optional-dependencies]
dev = ["pytest==8.4.2", "pytest-cov==7.0.0"]

[project.scripts]
eas-ledger-exporter = "eas_ledger_exporter.cli:main"

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: 创建并安装隔离环境**

Run:

```powershell
uv venv --python 3.11
uv pip install -e ".[dev]"
```

Expected: `.venv` 创建成功，`python -c "from RPA.JavaAccessBridge import JavaAccessBridge"` 返回码为0。

- [ ] **Step 3: 启用Java Access Bridge**

Run:

```powershell
& 'D:\Kingdee\eas\oracle_jdk1.8\bin\jabswitch.exe' -enable
```

Expected: 命令提示Java Access Bridge已启用。关闭并重新打开EAS后继续。

- [ ] **Step 4: 编写控件树探测脚本**

```python
# scripts/inspect_eas.py
from pathlib import Path
from RPA.JavaAccessBridge import JavaAccessBridge


def main() -> None:
    jab = JavaAccessBridge(ignore_callbacks=True)
    windows = jab.list_java_windows()
    matches = [item for item in windows if "金蝶EAS" in item.title]
    if len(matches) != 1:
        raise RuntimeError(f"预期找到1个金蝶EAS窗口，实际为{len(matches)}个")
    jab.select_window_by_pid(matches[0].pid)
    rows = []
    for item in jab.context_info_tree:
        info = item.context_info
        rows.append(
            f"name={info.name!r}\trole={info.role!r}\t"
            f"states={info.states!r}\tancestry={item.ancestry!r}"
        )
    output = Path("artifacts/eas-controls.txt")
    output.parent.mkdir(exist_ok=True)
    output.write_text("\n".join(rows), encoding="utf-8")
    print(output.resolve())


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行探测并设置硬门槛**

Run:

```powershell
.venv\Scripts\python scripts\inspect_eas.py
rg "财务会计|凭证查询|条件查询|导出到Excel|确定" artifacts\eas-controls.txt
```

Expected: 至少能识别EAS窗口及“财务会计”。若控件树只有顶层窗口，停止实施并检查JAB位数、DLL路径和EAS自带JRE，不能退回屏幕坐标方案。

- [ ] **Step 6: 写入首版定位器**

```json
{
  "window_title": ".*金蝶EAS.*",
  "finance": "name:财务会计",
  "general_ledger": "name:总账",
  "voucher_processing": "name:凭证处理",
  "voucher_query": "name:凭证查询",
  "company": "role:text and name:公司",
  "period_mode": "name:按期间查询",
  "start_year": "role:text and ancestry:会计期间 and indexInParent:0",
  "start_month": "role:text and ancestry:会计期间 and indexInParent:1",
  "end_year": "role:text and ancestry:至 and indexInParent:0",
  "end_month": "role:text and ancestry:至 and indexInParent:1",
  "max_results": "name:最大返回结果数",
  "audit_all": "name:全部 and ancestry:审核状态",
  "posted_all": "name:全部 and ancestry:过账状态",
  "review_all": "name:全部 and ancestry:复核状态",
  "voucher_mode": "name:按凭证查询",
  "confirm": "role:push button and name:确定",
  "condition_query": "name:条件查询",
  "result_table": "role:table",
  "result_rows": "role:table cell and ancestry:凭证序时簿",
  "export_excel": "name:导出到Excel",
  "export_path": "role:text and ancestry:导出序时簿向导",
  "export_confirm": "role:push button and name:完成 and ancestry:导出序时簿向导"
}
```

逐项用 `jab.get_elements(locator)` 验证：普通控件必须唯一匹配；`result_rows` 可匹配零至多项。若实际控件树的角色或父级名称不同，只修改对应JSON值，并把最终控件树保存在 `artifacts/eas-controls.txt` 作为现场依据。

- [ ] **Step 7: 提交**

```powershell
git add eas-ledger-exporter/pyproject.toml eas-ledger-exporter/scripts eas-ledger-exporter/config
git commit -m "build: initialize EAS exporter and JAB probe"
```

### Task 2: 定义模型、错误和配置读取

**Files:**
- Create: `src/eas_ledger_exporter/models.py`
- Create: `src/eas_ledger_exporter/errors.py`
- Create: `src/eas_ledger_exporter/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

```python
def test_load_config_preserves_company_code_and_filters_disabled(config_book):
    config = load_config(config_book)
    assert config.year == 2026
    assert config.month == 6
    assert config.output_dir.name == "序时账"
    assert config.companies == (Company("001", "广州本部"),)


def test_load_config_rejects_invalid_month(invalid_month_book):
    with pytest.raises(ConfigError, match="月份必须是1至12"):
        load_config(invalid_month_book)
```

- [ ] **Step 2: 确认测试失败**

Run: `.venv\Scripts\pytest tests\test_config.py -v`

Expected: FAIL，原因是 `load_config` 尚不存在。

- [ ] **Step 3: 实现最小模型和读取逻辑**

```python
@dataclass(frozen=True)
class Company:
    code: str
    name: str


@dataclass(frozen=True)
class ExportConfig:
    year: int
    month: int
    output_dir: Path
    companies: tuple[Company, ...]


def load_config(path: Path) -> ExportConfig:
    workbook = load_workbook(path, read_only=True, data_only=True)
    period = workbook["执行期间"]
    year, month, output = int(period["A2"].value), int(period["B2"].value), period["C2"].value
    if not 1 <= month <= 12:
        raise ConfigError("月份必须是1至12")
    companies = tuple(
        Company(str(code).zfill(3), str(name).strip())
        for code, name, enabled in workbook["执行操作的公司"].iter_rows(
            min_row=2, max_col=3, values_only=True
        )
        if str(enabled).strip() == "是"
    )
    workbook.close()
    if not companies:
        raise ConfigError("没有启用的公司")
    return ExportConfig(year, month, Path(str(output)), companies)
```

- [ ] **Step 4: 运行测试**

Run: `.venv\Scripts\pytest tests\test_config.py -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add eas-ledger-exporter/src/eas_ledger_exporter/{models.py,errors.py,config.py} eas-ledger-exporter/tests/test_config.py
git commit -m "feat: load ledger export configuration"
```

### Task 3: 文件命名和写入完成判断

**Files:**
- Create: `src/eas_ledger_exporter/file_wait.py`
- Modify: `src/eas_ledger_exporter/models.py`
- Test: `tests/test_file_wait.py`

- [ ] **Step 1: 写失败测试**

```python
def test_job_uses_six_digit_period(tmp_path):
    job = ExportJob(Company("001", "广州本部"), 2026, 6, tmp_path)
    assert job.path.name == "001.广州本部_202606_凭证序时簿.xlsx"


def test_wait_until_stable_requires_two_equal_sizes(tmp_path, monkeypatch):
    path = tmp_path / "book.xlsx"
    sizes = iter([10, 20, 20])
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(Path, "stat", lambda self: SimpleNamespace(st_size=next(sizes)))
    assert wait_until_stable(path, timeout=1, interval=0) == 20
```

- [ ] **Step 2: 确认测试失败**

Run: `.venv\Scripts\pytest tests\test_file_wait.py -v`

Expected: FAIL。

- [ ] **Step 3: 实现**

```python
@dataclass(frozen=True)
class ExportJob:
    company: Company
    year: int
    month: int
    output_dir: Path

    @property
    def period(self) -> str:
        return f"{self.year}{self.month:02d}"

    @property
    def path(self) -> Path:
        return self.output_dir / (
            f"{self.company.code}.{self.company.name}_{self.period}_凭证序时簿.xlsx"
        )


def wait_until_stable(path: Path, timeout: float, interval: float = 1.0) -> int:
    deadline = monotonic() + timeout
    previous = None
    while monotonic() < deadline:
        if path.exists():
            size = path.stat().st_size
            if size > 0 and size == previous:
                with path.open("rb"):
                    return size
            previous = size
        sleep(interval)
    raise ExportTimeoutError(f"文件写入超时: {path}")
```

- [ ] **Step 4: 运行测试并提交**

Run: `.venv\Scripts\pytest tests\test_file_wait.py -v`

Expected: PASS。

```powershell
git add eas-ledger-exporter/src/eas_ledger_exporter eas-ledger-exporter/tests/test_file_wait.py
git commit -m "feat: name exports and wait for stable files"
```

### Task 4: 修复EAS错误的XLSX工作表范围

**Files:**
- Create: `src/eas_ledger_exporter/xlsx_repair.py`
- Test: `tests/test_xlsx_repair.py`

- [ ] **Step 1: 写失败测试**

```python
def test_repair_dimension_uses_last_cell(broken_dimension_xlsx):
    assert repair_dimension(broken_dimension_xlsx) == "A1:AB3"
    with ZipFile(broken_dimension_xlsx) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml")
    assert b'ref="A1:AB3"' in xml
```

- [ ] **Step 2: 确认失败**

Run: `.venv\Scripts\pytest tests\test_xlsx_repair.py -v`

Expected: FAIL。

- [ ] **Step 3: 实现流式扫描和原子替换**

```python
CELL_REF = re.compile(rb'<c r="([A-Z]+)(\d+)"')


def repair_dimension(path: Path) -> str:
    with ZipFile(path) as source:
        sheet = source.read("xl/worksheets/sheet1.xml")
        refs = CELL_REF.findall(sheet)
        if not refs:
            raise WorkbookRepairError("工作表没有单元格")
        last_col = max(refs, key=lambda item: column_index_from_string(item[0].decode()))[0]
        last_row = max(int(item[1]) for item in refs)
        dimension = f"A1:{last_col.decode()}{last_row}"
        repaired = re.sub(
            rb'<dimension ref="[^"]*"\s*/>',
            f'<dimension ref="{dimension}"/>'.encode(),
            sheet,
            count=1,
        )
        temp = path.with_suffix(".repairing.xlsx")
        with ZipFile(temp, "w", ZIP_DEFLATED) as target:
            for entry in source.infolist():
                target.writestr(
                    entry,
                    repaired if entry.filename == "xl/worksheets/sheet1.xml"
                    else source.read(entry.filename),
                )
    temp.replace(path)
    return dimension
```

- [ ] **Step 4: 运行测试并提交**

Run: `.venv\Scripts\pytest tests\test_xlsx_repair.py -v`

Expected: PASS。

```powershell
git add eas-ledger-exporter/src/eas_ledger_exporter/xlsx_repair.py eas-ledger-exporter/tests/test_xlsx_repair.py
git commit -m "fix: repair EAS workbook dimensions"
```

### Task 5: 校验导出内容

**Files:**
- Create: `src/eas_ledger_exporter/validation.py`
- Test: `tests/test_validation.py`

- [ ] **Step 1: 写失败测试**

```python
def test_validate_accepts_matching_company_and_period(valid_export):
    result = validate_export(valid_export, "广电计量检测集团股份有限公司", 2026, 6)
    assert result.row_count == 2
    assert result.empty is False


def test_validate_rejects_wrong_period(wrong_period_export):
    with pytest.raises(ValidationError, match="期间不一致"):
        validate_export(wrong_period_export, "广电计量检测集团股份有限公司", 2026, 6)
```

- [ ] **Step 2: 确认失败**

Run: `.venv\Scripts\pytest tests\test_validation.py -v`

Expected: FAIL。

- [ ] **Step 3: 实现**

```python
REQUIRED_HEADERS = {
    "公司", "记账日期", "期间", "凭证类型", "凭证号",
    "科目编码", "科目名称", "借方", "贷方",
}


def normalize_period(value: object) -> tuple[int, int]:
    year, month = str(value).strip().split(".", 1)
    return int(year), int(month)


def validate_export(path: Path, company: str, year: int, month: int) -> ValidationResult:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    headers = tuple(next(rows))
    missing = REQUIRED_HEADERS - set(headers)
    if missing:
        raise ValidationError(f"缺少表头: {sorted(missing)}")
    indexes = {name: headers.index(name) for name in ("公司", "期间")}
    count = 0
    for row in rows:
        if not any(value is not None for value in row):
            continue
        count += 1
        if row[indexes["公司"]] not in (None, company):
            raise ValidationError("公司不一致")
        if row[indexes["期间"]] is not None and normalize_period(row[indexes["期间"]]) != (year, month):
            raise ValidationError("期间不一致")
    workbook.close()
    return ValidationResult(row_count=count, empty=count == 0)
```

- [ ] **Step 4: 运行测试并提交**

Run: `.venv\Scripts\pytest tests\test_validation.py -v`

Expected: PASS。

```powershell
git add eas-ledger-exporter/src/eas_ledger_exporter/validation.py eas-ledger-exporter/tests/test_validation.py
git commit -m "feat: validate exported ledger workbooks"
```

### Task 6: 封装EAS Java控件操作

**Files:**
- Create: `src/eas_ledger_exporter/eas_client.py`
- Modify: `config/eas-locators.json`
- Test: `tests/test_runner.py`

- [ ] **Step 1: 定义可替换接口并写失败测试**

```python
class EasPort(Protocol):
    def open_voucher_query(self) -> None: ...
    def query(self, job: ExportJob) -> QueryResult: ...
    def export(self, job: ExportJob) -> None: ...
    def reopen_conditions(self) -> None: ...
    def screenshot(self, path: Path) -> None: ...


def test_client_sets_period_and_all_statuses(fake_jab, locators, job):
    client = EasClient(fake_jab, locators)
    result = client.query(job)
    assert fake_jab.typed == [("company", "001"), ("start_year", "2026"),
                              ("start_month", "6"), ("end_year", "2026"),
                              ("end_month", "6")]
    assert result.company_display == "广电计量检测集团股份有限公司"
```

- [ ] **Step 2: 确认失败**

Run: `.venv\Scripts\pytest tests\test_runner.py::test_client_sets_period_and_all_statuses -v`

Expected: FAIL。

- [ ] **Step 3: 实现EAS客户端**

```python
class EasClient:
    def __init__(self, jab: JavaAccessBridge, locators: dict[str, str]) -> None:
        self.jab = jab
        self.locators = locators

    def click(self, key: str, *, right: bool = False) -> None:
        self.jab.click_element(
            self.locators[key],
            action=not right,
            click_type="right click" if right else "click",
        )

    def type(self, key: str, value: str) -> None:
        self.jab.type_text(self.locators[key], value, clear=True, typing=False)

    def refresh(self) -> None:
        self.jab.application_refresh()

    def query(self, job: ExportJob) -> QueryResult:
        self.type("company", job.company.code)
        self.jab.press_keys("TAB")
        self.click("period_mode")
        self.type("start_year", str(job.year))
        self.type("start_month", str(job.month))
        self.type("end_year", str(job.year))
        self.type("end_month", str(job.month))
        self.jab.select_from_list("max_results", "全部")
        for key in ("audit_all", "posted_all", "review_all", "voucher_mode"):
            self.click(key)
        company_display = self.jab.get_element_text(self.locators["company"])
        self.click("confirm")
        self.refresh()
        empty = not self.jab.get_elements(self.locators["result_rows"], strict=False)
        return QueryResult(company_display=company_display, empty=empty)

    def export(self, job: ExportJob) -> None:
        self.click("result_table", right=True)
        self.click("export_excel")
        self.refresh()
        self.type("export_path", str(job.path))
        self.click("export_confirm")
```

实现时读取Task 1已验证的全部定位器。代码不得内嵌窗口坐标；定位器不唯一时抛出 `EasControlError` 并立即停止。

- [ ] **Step 4: 运行单元测试和单公司现场测试**

Run:

```powershell
.venv\Scripts\pytest tests\test_runner.py -v
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx --limit 1 --dry-run
```

Expected: 单元测试PASS；现场测试只完成查询条件填写，不导出。

- [ ] **Step 5: 提交**

```powershell
git add eas-ledger-exporter/src/eas_ledger_exporter/eas_client.py eas-ledger-exporter/config/eas-locators.json eas-ledger-exporter/tests/test_runner.py
git commit -m "feat: automate EAS voucher query and export"
```

### Task 7: 串联运行、失败停止和日志

**Files:**
- Create: `src/eas_ledger_exporter/runner.py`
- Create: `src/eas_ledger_exporter/reporting.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: 写失败停止测试**

```python
def test_runner_stops_on_first_failure(tmp_path, jobs, fake_eas):
    fake_eas.fail_on = jobs[1].company.code
    with pytest.raises(ExportError):
        ExportRunner(fake_eas, tmp_path / "logs").run(jobs)
    assert fake_eas.queried == ["001", "002"]
    assert "003" not in fake_eas.queried
```

- [ ] **Step 2: 确认失败**

Run: `.venv\Scripts\pytest tests\test_runner.py::test_runner_stops_on_first_failure -v`

Expected: FAIL。

- [ ] **Step 3: 实现串联逻辑**

```python
class ExportRunner:
    def __init__(self, eas: EasPort, log_dir: Path) -> None:
        self.eas = eas
        self.reporter = RunReporter(log_dir)

    def run(self, jobs: Sequence[ExportJob]) -> None:
        self.eas.open_voucher_query()
        for index, job in enumerate(jobs):
            try:
                job.output_dir.mkdir(parents=True, exist_ok=True)
                job.path.unlink(missing_ok=True)
                query = self.eas.query(job)
                self.eas.export(job)
                wait_until_stable(job.path, timeout=1800)
                repair_dimension(job.path)
                result = validate_export(
                    job.path, query.company_display, job.year, job.month
                )
                if result.empty != query.empty:
                    raise ValidationError("EAS查询结果与导出文件空数据状态不一致")
                self.reporter.success(job, result)
                if index < len(jobs) - 1:
                    self.eas.reopen_conditions()
            except Exception as exc:
                screenshot = self.reporter.failure_path(job)
                self.eas.screenshot(screenshot)
                self.reporter.failure(job, exc, screenshot)
                raise ExportError(f"{job.company.code} 导出失败") from exc
```

- [ ] **Step 4: 实现CSV汇总**

```python
FIELDS = ("公司编号", "公司名称", "期间", "状态", "数据行数", "文件", "错误")


def append_summary(path: Path, row: dict[str, object]) -> None:
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)
```

- [ ] **Step 5: 运行测试并提交**

Run: `.venv\Scripts\pytest tests\test_runner.py -v`

Expected: PASS，且失败后第三家公司未执行。

```powershell
git add eas-ledger-exporter/src/eas_ledger_exporter/{runner.py,reporting.py} eas-ledger-exporter/tests/test_runner.py
git commit -m "feat: stop safely and report export runs"
```

### Task 8: CLI、文档和分阶段现场验收

**Files:**
- Create: `src/eas_ledger_exporter/cli.py`
- Create: `src/eas_ledger_exporter/__init__.py`
- Create: `README.md`

- [ ] **Step 1: 实现CLI**

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    companies = config.companies[: args.limit] if args.limit else config.companies
    jobs = [ExportJob(item, config.year, config.month, config.output_dir) for item in companies]
    eas = create_eas_client(Path("config/eas-locators.json"))
    ExportRunner(eas, Path("logs") / datetime.now().strftime("%Y%m%d-%H%M%S")).run(jobs)
    return 0
```

- [ ] **Step 2: 写README运行步骤**

README必须包含：

```powershell
uv venv --python 3.11
uv pip install -e .
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx --limit 1
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx --limit 3
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx
```

并明确写明：EAS需预先登录；JAB需启用；失败不重试；日志位于 `logs`；运行时不要关闭EAS。

- [ ] **Step 3: 运行全部自动测试**

Run:

```powershell
.venv\Scripts\pytest -v
```

Expected: 全部PASS。

- [ ] **Step 4: 单公司验收**

Run:

```powershell
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx --limit 1
```

Expected: 生成一个 `YYYYMM` 六位期间文件，通过28列表头、公司、期间和数据行校验。

- [ ] **Step 5: 三家公司验收**

Run:

```powershell
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx --limit 3
```

Expected: 连续生成三个文件，条件窗口正确切换公司；故意关闭一次条件窗口时程序立即停止并保存截图。

- [ ] **Step 6: 全量验收**

Run:

```powershell
.venv\Scripts\eas-ledger-exporter --config D:\内部交易rpa\info.xlsx
```

Expected: 启用公司均得到“成功”或“空数据成功”，文件数量与汇总一致，运行期间鼠标键盘可用于其他程序。

- [ ] **Step 7: 最终提交**

```powershell
git add eas-ledger-exporter
git commit -m "feat: deliver EAS ledger exporter"
```
