# SeedLab · 种子试验管理系统

SeedLab 是供课题组长期使用的种子试验管理 Web 系统。当前稳定生产版本为 **v0.5.1**，已支持材料台账、一体导入、GER 种子萌发试验、分日置床、发芽巡检、前 N 株幼苗选样、根苗长测定、科研工作簿、账号及审计。幼苗测定采用 DAG（发芽后测定时间），保留实测 0、无法测量和尚无数据的区别。

**Architecture Foundation / AF-0—AF-3 已验收并合入 main**。当前 **AF-4** 分支建立 Measurement canonical dataset 与最小只读 Analysis 边界，完成后等待人工验收；保留现有 API、业务、科研数据语义、schema、VERSION 及正式 v0.5.1 产物。AF-1 源码的新能力尚未发布到现有 portable。阶段范围与操作契约从[文档唯一入口](docs/README.md)进入。

## 使用与开发

正式 portable 解压后运行 SeedLab Control Center.exe，日常运行无需 Python、Node 或 Git。程序与生产数据目录分离；目标电脑投产及历史 200 材料导入已完成，正式 Data Root 不在开发仓库。精确版本、tag、产物 SHA 及独立 importer 追溯见[v0.5.1 发布说明](docs/releases/v0.5.1.md)。

- 实验室部署与操作：[使用说明](packaging/使用说明.txt)。
- Windows 开发依赖、首次账号、启动与测试：[开发与运行说明](docs/04_开发与运行说明.md)。
- 生产运行、实例归属和正式数据库备份：[生产运维](docs/10_生产部署与控制中心设计.md)。
- portable 构建与只读安全门：[构建与分发](packaging/README.md)。
- 人工测试、开发重置和缓存工具：[开发维护方法](docs/09_人工测试与开发数据重置.md)。

后端测试入口为 run_tests.bat；前端在 frontend 目录运行 npm test、npm run build。隔离测试及固定历史源的使用方法见开发说明和[科研数据回归契约](docs/14_历史数据与导出回归契约.md)。

## 项目结构与技术栈

~~~text
backend/         FastAPI / SQLAlchemy / Alembic / pytest；SQLite WAL
frontend/        Vue 3 / TypeScript / Vite / Element Plus / Pinia
control_center/  Windows PySide6 运行控制中心
scripts/         启动、测试、构建、维护与临时历史回归夹具
packaging/       portable 入口、spec 和使用说明
docs/            当前权威文档与 releases
~~~

版本唯一来源为 backend/app/version.py。main 是发布主线；正式标签固定其发布提交，后续文档提交不改变发布身份。稳定编号、业务规则、数据模型及架构边界统一从[docs/README.md](docs/README.md)导航，历史追溯见[CHANGELOG](CHANGELOG.md)与 Git tag。

源码历史由 Git/GitHub 管理；只有不可替代的正式业务数据库 seedlab.db 进入长期备份机制。测试库、源码副本、可重建产物、运行配置与日志不另建历史备份体系。build/、dist/ 和开发依赖被 Git 忽略；当前已验收分发产物保持原样。

## 开发者与许可

Steven_Chen、SS_Zhong。MIT License，见[LICENSE](LICENSE)与[AUTHORS.md](AUTHORS.md)。
