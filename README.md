# SeedLab · 种子试验管理系统

SeedLab 是供课题组长期使用的种子试验管理 Web 系统。当前正式发布版为 **v0.3.1 / Account Bootstrap and Management**。本开发分支正在收口 v0.3.2 人工测试反馈，应用版本仍为 0.3.1，尚未发布 v0.3.2。系统已具备实验配置、确认置床编号、分批实际置床、发芽巡检、累计发芽动态计算、按培养皿或材料取前 N 株幼苗、来源追踪、巡检纠错和审计，以及首次浏览器初始化和成员账号管理。

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

## 材料导入与实验执行

“导入与导出”页面以“种子材料一体导入”为主要入口。一张中文表同时包含物种和种子批次信息；先预检逐行状态，再确认整批写入。物种先按系统物种编号精确识别，没有编号时按学名精确识别，绝不只凭中文名合并。相同物种和原始材料编号对应已登记材料；缺少原始材料编号时，疑似重复和信息不足的行需人工选择复用或新增。完整清单可增量导入，例如先导入 10 行，再导入含原 10 行的 30 行清单，系统仅新增其余 20 行。导入成功可直接把本次新增或确认的材料带入创建实验。

物种、种子批次、实验材料和置床清单默认按中文名完整拼音排序，接着按学名、原始材料编号、系统批次编号稳定排序。SP 物种编号和 LOT 种子批次编号始终保持原样；原始材料编号来自材料原表。已就绪实验确认置床编号时，按排序结果固定本次实验编号（001、002……）并生成尚未置床的计划培养皿。单重复的现场编号为 001，多重复为 001-1、001-2 等。随后可按实际日期分批登记置床；首批登记自动使实验进入进行中，实验开始时间取最早实际置床时间。同一次批量发芽巡检共享一个巡检时间，空白不写记录，0 是已检查且无新增发芽。多实验联合导出会重新生成仅属于该工作簿的汇总编号，同时保留原实验和培养皿身份。

### 单独维护种子批次

旧的“仅导入物种”和“仅导入种子批次”入口仍放在“单独维护”区域。单独导入种子批次的模板会列出当前启用物种的编号、中文名和学名；仅按系统物种编号匹配，一个成功数据行创建一个新批次。数量可留空或填写非负整数，单次最多 500 行。导入前检查整表，任何一行有误都不会导入。

种子批次内部关联使用 UUID；当前 `LOT-YYYY-NNN` 是用户可见业务编号，正式编号规则将在 v1.0 前确定。批次编号继续由系统自动生成，与原始材料编号及本次实验编号相互独立。

## 项目结构

```text
backend/   FastAPI、业务模型、Alembic 迁移与 pytest 测试
frontend/  Vue 页面、路由、状态和样式
docs/      总体设计、数据模型、实验配置与执行业务规则、路线图与运行说明
scripts/   开发启动与测试入口
```

详细设计见 [docs/01_系统总体设计.md](docs/01_系统总体设计.md)、[docs/02_核心数据模型.md](docs/02_核心数据模型.md)、[docs/03_开发路线图.md](docs/03_开发路线图.md)、[docs/05_实验配置业务规则.md](docs/05_实验配置业务规则.md)、[docs/06_发芽实验执行业务规则.md](docs/06_发芽实验执行业务规则.md) 与 [docs/07_账号初始化与权限管理.md](docs/07_账号初始化与权限管理.md)。

## 版本与分支

版本唯一来源：`backend/app/version.py`，通过 `/api/health` 对前端和外部工具提供。`main` 为当前发布主线；`v0.1.0` 标记 Stage 0 Foundation，`v0.2.0` 标记 Stage 1 实验配置，`v0.3.0` 标记 Stage 2 Germination Execution，`v0.3.1` 标记 Stage 2.5 Account Bootstrap and Management。Stage 3 尚未开始。

## 开发者与许可

Steven_Chen、SS_Zhong。MIT License，见 [LICENSE](LICENSE) 与 [AUTHORS.md](AUTHORS.md)。
