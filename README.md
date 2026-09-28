# SeedLab · 种子试验管理系统

SeedLab 是供课题组长期使用的种子试验管理 Web 系统。当前为 **Stage 0 Foundation / 0.1.0-dev**，重点是可追溯的基础数据、可用的工作台和后续实验执行功能的数据基础。

## 技术栈

- 后端：Python 3.12+、FastAPI、SQLAlchemy 2、Alembic、Pydantic 2、SQLite WAL、Argon2、pytest、openpyxl。
- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、Axios。

## 本地启动（Windows）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e './backend[test]'
cd frontend
npm install
cd ..
Copy-Item .env.example .env
```

Alembic 和管理员命令应在 `backend` 目录运行：

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.cli create-admin admin --name "管理员"
cd ..
.\run_dev.bat
```

浏览器访问 <http://localhost:5173>；开发 API 文档位于 <http://localhost:8000/docs>。`run_dev.bat` 会检查依赖、执行迁移并同时启动两个开发服务。可在同一局域网内通过主机 IP 和 5173 端口访问；对外访问前请参照[运行说明](docs/04_开发与运行说明.md)配置 HTTPS 和 Cookie。

运行测试：`run_tests.bat`。前端构建：在 `frontend` 目录执行 `npm run build`。

## 项目结构

```text
backend/   FastAPI、业务模型、Alembic 迁移与 pytest 测试
frontend/  Vue 页面、路由、状态和样式
docs/      总体设计、数据模型、路线图与运行说明
scripts/   开发启动与测试入口
```

详细设计见 [docs/01_系统总体设计.md](docs/01_系统总体设计.md)、[docs/02_核心数据模型.md](docs/02_核心数据模型.md)、[docs/03_开发路线图.md](docs/03_开发路线图.md)。

## 版本与分支

版本唯一来源：`backend/app/version.py`，通过 `/api/health` 对前端和外部工具提供。`main` 为稳定主线，短期使用 `feat/*`、`fix/*`。Stage 0 验收后再考虑 `v0.1.0` 标签。

## 开发者与许可

Steven_Chen、SS_Zhong。MIT License，见 [LICENSE](LICENSE) 与 [AUTHORS.md](AUTHORS.md)。
