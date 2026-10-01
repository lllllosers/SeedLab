"""Safe static serving with fallback limited to existing Vue page routes."""
import re
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles


# Keep aligned with frontend/src/router/index.ts when adding page routes.
PAGE_ROUTE = re.compile(
    r"(?:|login|setup|change-password|taxa|seed-lots|experiments|data|audit|users"
    r"|taxa/[^/.]+|experiments/[^/.]+(?:/germination)?)"
)


class ProductionWeb(StaticFiles):
    def __init__(self, root: Path):
        self.index = root / "index.html"
        if not self.index.is_file():
            raise RuntimeError(
                f"前端生产文件缺失：{self.index}。请先构建前端，或通过 SEEDLAB_WEB_ROOT 指定已构建目录。"
            )
        super().__init__(directory=root, follow_symlink=False)

    async def get_response(self, path, scope):
        # StaticFiles normalizes to OS separators; routing uses URL separators.
        url_path = path.replace("\\", "/")
        request_path = scope["path"]
        if (request_path == "/api" or request_path.startswith("/api/")
                or url_path == "api" or url_path.startswith("api/")
                or url_path in {"docs", "openapi.json"}):
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            page_path = "" if url_path == "." else url_path
            if exc.status_code == 404 and scope["method"] in {"GET", "HEAD"} and PAGE_ROUTE.fullmatch(page_path):
                return FileResponse(self.index)
            raise
