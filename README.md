# SeedLab · 种子试验管理系统

SeedLab 是供课题组长期使用的种子试验管理 Web 系统。当前正式发布版为 **v0.3.0 / Germination Execution**；Stage 2.5 账号初始化与成员管理正在开发分支中。系统已具备实验配置、正式开始实验与培养皿生成、发芽巡检、累计发芽动态计算、`per_dish` / `per_material` 前 N 株选样、幼苗来源追踪，以及巡检纠错和审计。

幼苗根苗长测定采用 DAG（Days After Germination）：实验配置非负的 `day_after_germination` 节点，未来以单株首次在巡检中判定发芽的时间 `germinated_at` 计算测定任务。培养皿置床时间 `sown_at` 另行保留，用于派生巡检所需的置床后天数。Stage 3 的 DAG 今日测定任务、根长苗长录入、`SeedlingMeasurement` 正式操作接口、测定历史与快速纠错，以及数据统计分析尚未实现。

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

Alembic 应在 `backend` 目录运行；之后从仓库根目录启动服务：

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
cd ..
.\run_dev.bat
```

系统没有预设账号或密码。首次启动且数据库没有用户时，服务器终端会显示一次性 Bootstrap Token；浏览器打开 `/setup`，输入该码并设置首个管理员。初始化完成后入口永久关闭。无法使用网页时，服务器本机仍可在 `backend` 目录执行 `..\.venv\Scripts\python.exe -m app.cli create-admin admin --name "管理员"`，交互式输入 8 至 128 位密码。详见[账号初始化与权限管理](docs/07_账号初始化与权限管理.md)。

浏览器访问 <http://localhost:5173>；开发 API 文档位于 <http://localhost:8000/docs>。`run_dev.bat` 会检查依赖、执行迁移并同时启动两个开发服务。可在同一局域网内通过主机 IP 和 5173 端口访问；对外访问前请参照[运行说明](docs/04_开发与运行说明.md)配置 HTTPS 和 Cookie。

运行测试：`run_tests.bat`。前端构建：在 `frontend` 目录执行 `npm run build`。

## 项目结构

```text
backend/   FastAPI、业务模型、Alembic 迁移与 pytest 测试
frontend/  Vue 页面、路由、状态和样式
docs/      总体设计、数据模型、实验配置与执行业务规则、路线图与运行说明
scripts/   开发启动与测试入口
```

详细设计见 [docs/01_系统总体设计.md](docs/01_系统总体设计.md)、[docs/02_核心数据模型.md](docs/02_核心数据模型.md)、[docs/03_开发路线图.md](docs/03_开发路线图.md)、[docs/05_实验配置业务规则.md](docs/05_实验配置业务规则.md)、[docs/06_发芽实验执行业务规则.md](docs/06_发芽实验执行业务规则.md) 与 [docs/07_账号初始化与权限管理.md](docs/07_账号初始化与权限管理.md)。

## 版本与分支

版本唯一来源：`backend/app/version.py`，通过 `/api/health` 对前端和外部工具提供。`main` 为当前发布主线；`v0.1.0` 标记 Stage 0 Foundation，`v0.2.0` 标记 Stage 1 实验配置，`v0.3.0` 标记 Stage 2 Germination Execution。Stage 2.5 保持应用版本 `0.3.0`，验收后再发布 `v0.3.1`。

## 开发者与许可

Steven_Chen、SS_Zhong。MIT License，见 [LICENSE](LICENSE) 与 [AUTHORS.md](AUTHORS.md)。
