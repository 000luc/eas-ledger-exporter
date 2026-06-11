class ConfigError(Exception):
    """配置文件无法用于导出时抛出。"""


class ExportTimeoutError(TimeoutError):
    """导出文件在指定时间内未达到稳定可读状态。"""
