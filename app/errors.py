"""跨层错误定义（供 db / gates / services 共用，避免包内循环导入）。"""


class ServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
