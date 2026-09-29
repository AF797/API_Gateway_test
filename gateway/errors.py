"""게이트웨이 공통 에러. 직원에게는 항상 같은 형식의 JSON으로 응답한다."""
from fastapi.responses import JSONResponse


class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.meta: dict | None = None

    def to_response(self) -> JSONResponse:
        headers = {"Retry-After": str(self.retry_after)} if self.retry_after else None
        return JSONResponse(
            status_code=self.status,
            content={"success": False, "error": {"code": self.code, "message": self.message}, "meta": self.meta},
            headers=headers,
        )
