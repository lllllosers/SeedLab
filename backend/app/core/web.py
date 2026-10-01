"""Safe static serving; Vue Router alone decides which SPA pages exist."""
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class ProductionWeb(StaticFiles):
    def __init__(self, root: Path):
        self.root = root.resolve()
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
        segments = request_path.split("/")
        # Inspect the original decoded URL before StaticFiles normalization can
        # erase traversal segments. Invalid requests must not become SPA 200s.
        if (any(part in {".", ".."} for part in segments)
                or any(character in request_path for character in ("\\", "\x00", ":"))):
            raise HTTPException(status_code=404)
        if (request_path == "/api" or request_path.startswith("/api/")
                or url_path == "api" or url_path.startswith("api/")
                or url_path in {"docs", "openapi.json"}):
            raise HTTPException(status_code=404)
        # StaticFiles refuses outside-root symlinks; apply the same boundary
        # before fallback so a rejected extensionless symlink stays a 404.
        try:
            inside_root = (self.root / path).resolve().is_relative_to(self.root)
        except (OSError, ValueError):
            inside_root = False
        if not inside_root:
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            navigation = (url_path != "assets" and not url_path.startswith("assets/")
                          and not Path(url_path).suffix
                          and not any(part.startswith(".") for part in segments if part))
            if exc.status_code == 404 and scope["method"] in {"GET", "HEAD"} and navigation:
                # Also resolve the SPA entry through StaticFiles so an index
                # symlink cannot bypass its root boundary checks.
                return await super().get_response("index.html", scope)
            raise
