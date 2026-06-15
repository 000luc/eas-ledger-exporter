class ConfigError(Exception):
    """配置文件无法用于导出时抛出。"""


class ExportTimeoutError(TimeoutError):
    """导出文件在指定时间内未达到稳定可读状态。"""


class ExportFileError(OSError):
    """导出文件无法继续检查或读取时抛出。"""


class WorkbookRepairError(Exception):
    """无法修复 EAS 导出工作簿时抛出。"""


class ValidationError(Exception):
    """导出文件内容校验失败时抛出。"""
