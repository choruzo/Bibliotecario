from fastapi import HTTPException
from starlette.responses import JSONResponse


class UploadBodyLimit:
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PATCH"} or not scope["path"].startswith("/admin/"):
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        try:
            announced = int(headers.get(b"content-length", b"0"))
        except ValueError:
            announced = 0
        if announced > self.max_bytes:
            return await JSONResponse({"detail": "upload_too_large"}, status_code=413)(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                raise HTTPException(413, "upload_too_large")
            return message

        await self.app(scope, limited_receive, send)
