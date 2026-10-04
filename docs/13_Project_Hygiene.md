# v0.5.1 投产后的项目卫生记录

日期：2026-10-04。分支：`maintenance/project-hygiene`；起点：`04fe5719daa9b859005fc922daae3d4a975bf004`。先完成只读盘点，再执行确认范围内的清理。正式投产及历史数据导入完成状态来自用户确认；目标电脑的生产 Data Root 不在本开发机，本轮不访问它。

## 清理前盘点

- `main` 与 fetch 后的 `origin/main` 一致，均为起点提交；工作区无未提交修改。
- 根目录仅有项目说明、配置样例、许可和五个仍被使用的 BAT 入口，无临时源码副本或重复 README。
- `build/` 有 111 个文件、158534595 字节，包括旧 PyInstaller 中间产物、三套旧隔离验收 Data Root、浏览器编排、报告、发布辅助脚本和日志。它们均被忽略且可重新生成，不是正式分发目录。
- `backend/data/seedlab.db` 为开发人工测试库：迁移 c6d91f28a405，99 个物种、99 个批次、1 个“人工测试1”实验、36 株幼苗和36条测定。与正式历史库的198/200/1665/4955基线不同。
- `backend/backups/` 六份数据库是 dev-reset、索引修复前、Stage 3 升级前及最终人工验收快照；只读检查确认实验名称为人工验收或人工测试。另有一组旧 WAL/SHM。
- `build/isolation-runtime-data-bb_17bsf`、`build/isolation-runtime-data-l2namnxu`、`build/v041-runtime-data-7ilba3dv` 是旧验收 Data Root，业务表为空。未发现使用这些目录的 SeedLab/Python/Node 进程。
- 源码目录有14个 Python/pytest缓存目录；另有两份开发运行日志和旧 `frontend/dist`。没有仓库内浏览器 profile、Playwright报告、截图、trace或coverage输出。
- `.venv`、`frontend/node_modules`、editable 安装的 egg-info 是当前开发依赖，保留。
- 三套正式目录全部保留：`dist/portable-v051`、`dist/legacy-importer-v1`、`dist/delivery-v051`。清理前记录所有文件的路径、大小与哈希摘要，完成后复核。

## scripts 分类与引用证据

| 分类 | 文件 | 用途及引用 |
|---|---|---|
| 长期维护 | project_hygiene_check.ps1、clean_dev_artifacts.ps1 | README、开发说明和维护说明引用；分别用于只读盘点和白名单缓存清理 |
| 构建 | build_brand_icon.py | 从现有SVG重新生成正式ICO/PNG，保留并补充构建文档入口 |
| 构建 | build_production.ps1、build_portable.ps1、check_portable.py | 运行/打包说明引用；portable脚本调用安全门，打包回归测试直接覆盖安全门 |
| 数据维护 | reset_dev_data.ps1 | BAT、维护说明引用；只操作显式开发环境，保留 |
| 启动与测试 | run_dev.py、run_prod.py、run_control_center.py、run_tests.py | BAT、开发说明引用；控制中心路径构造及测试直接使用生产runner |
| 历史回归夹具 | maintenance/backfill_legacy_200_species.py | test_legacy_backfill.py直接调用；覆盖真实历史源、回滚、缺测、数值0、结束实验和正式长宽表，保留，不作为生产导入入口 |
| 失效/重复 | build内旧publish_v041.py、v050-browser-acceptance.cjs及报告 | 不被当前构建、安装、测试、配置或控制中心引用，随旧build清理 |

main 的所有正式行为测试保留，包含原文件集成测试；原文件通过显式环境变量只读启用。前端全部10个测试文件保留。没有仅凭测试名或计数删除测试。

## importer 可追溯性

正式 importer 没有合入 main，本 hygiene 分支也不引入其业务实现。保留 `maintenance/legacy-production-import` 于 `20e04538e878bb8371b4eeb49ede6f8140d3bfcf`；保留 `legacy-importer-v1.0.0` 精确指向 `724db347a70d5cf1567aec5d138c35f587152ce1`。

该tag保留生产入口、共享核心、schema contract、PyInstaller spec、构建入口、保护/故障测试和工具说明。maintenance HEAD还保留独立EXE与浏览器验收测试、演练编排及完整验收记录。不删除分支或tag、不修改其源码、不清理已有正式EXE。

在当前docs提供维护工具索引和原验收记录。演练脚本留在历史维护分支，未复制到当前主程序维护树；不新增另一套解析器或构建入口。

## 死代码与边界检查

对所有受控源码进行Python AST、文本引用及Vue文件引用检查，结合FastAPI路由注册、Vue动态路由、CLI入口、Alembic模型注册和PyInstaller hiddenimports复核。没有确认可安全删除的业务模块、组件、service/helper或API端点；未发现业务源码TODO/FIXME、breakpoint、debugger或console.log残留。服务器、初始化和CLI的print属于运行输出，保留。

缓存清理工具补充 build/dist保护，防止递归触及正式产物；同时补充mypy缓存识别。新增隔离回归验证真实清理与dry-run均保护dist、build、数据、依赖和受控文件。

只补缺失的ignore规则；不改变build/dist正式产物策略。业务源码、UI、接口、模型、历史迁移与VERSION不变；不执行正式历史导入，不重建portable或importer。

## 完成记录

### 删除与移动

没有删除任何受控业务源码或正式行为测试。移除旧文档中已被当前说明替代的阶段性计划、临时状态和重复验收描述，其原版本仍在Git历史。

本地删除范围均先检查绝对路径边界、祖先及后代重定向、tracked文件，再执行；数据库在删除前复核盘点SHA未变：

- `build/`：全部111个旧中间文件与验收生成物，包括两个isolation-runtime-data目录、v041-runtime-data、三套legacy-importer构建目录、portable-cache、portable-pyinstaller，以及旧发布脚本、浏览器编排、日志与报告。不操作仓库外历史演练目录。
- `backend/data/seedlab.db`：已确认的人工测试库。
- `backend/backups/dev-reset-20260930-122752-d1212d3e.db`。
- `backend/backups/dev-reset-20260930-230529-9d4c8472.db`。
- `backend/backups/dev-reset-20261001-094704-76aac93a.db`。
- `backend/backups/seedlab-pre-index-repair-20260929-212045-b18e737c.db`及其WAL/SHM。
- `backend/backups/seedlab-pre-stage3-20260929-221708.db`。
- `backend/backups/stage3-final-acceptance-20261001-120504-1a0537f1.db`。
- `logs/control-center.log`、`logs/production-server.log`。
- 源码内14个缓存目录及旧frontend/dist；完整质量门成功后，再移除本轮重新生成的缓存和frontend/dist，不保留测试输出。

文档移动：

1. `docs/releases/v0.4.1.md` → `docs/archive/releases/v0.4.1.md`，原内容保持。
2. `docs/10_历史回填能力验证.md` → `docs/14_历史数据与导出回归契约.md`，保留长期回归契约、更新当前投产状态，消除重复10编号。
3. packaging/README的旧v0.4.0/v0.4.1验收段落集中到 `docs/archive/portable-v040-v041验收记录.md`；当前构建文档只保留构建与分发说明。

### 最终结构与保留决定

- docs共18份Markdown：导航；01—09架构/业务/开发维护；10生产部署；11 importer索引；12原完整验收记录；13本卫生记录；14历史与导出契约；releases/v0.5.1；archive内一份旧验收记录和v0.4.1历史版本说明。
- scripts共12个入口：11个根级长期维护、启动、测试或构建工具，加maintenance内一个被正式测试引用的旧回填夹具。品牌生成器有实际生成用途，保留并补充文档入口。
- backend/tests共25个test模块及conftest，原测试全部保留，新增维护清理边界的2项回归；frontend/tests保持10个文件、28项测试。
- dist只保留portable-v051、legacy-importer-v1、delivery-v051，分别963、2、6个文件；三目录全部文件的路径/大小/SHA汇总与清理前相同。
- .venv、frontend/node_modules、backend/seedlab_backend.egg-info保留；本轮不安装或升级依赖。
- 最终仓库（排除Git与依赖环境）的SQLite数据库/WAL/SHM/journal、临时Data Root、cache、测试日志/报告、browser profile和前端构建输出均为0。交付Excel为固定源文件，不是测试导出；未改其SHA。

### 修改范围与质量门

受控修改仅为ignore、两个卫生工具、维护工具回归测试、一个启动脚本过时docstring，以及当前README、AGENTS事实状态、CHANGELOG、架构/运维文档与文档索引。业务源码、前端、模型、schema、migration、依赖声明、品牌资源和旧回填夹具均与起点逐路径diff一致。

| 质量门 | 实际结果 |
|---|---|
| 完整backend pytest（含固定源集成） | 282 passed / 1 skipped；142.76s |
| Windows跳过项 | 当前账号不能创建symbolic link，既有备份符号链接保护测试跳过 |
| frontend unit tests | 28 passed / 0 failed |
| vue-tsc --noEmit | PASS |
| npm run build | PASS，1754 modules；输出验证后清理 |
| pip check / npm ls --depth=0 | PASS / PASS |
| Python源码AST | 117个受控Python文件语法通过 |
| 模块导入 | 70个app/control_center模块通过，显式内存目标，不产生数据库文件 |
| 维护工具 | 原生Windows PowerShell只读盘点成功；真实清理与dry-run隔离回归通过 |
| ruff / mypy | 项目没有配置且当前环境未安装，未新增工具或规则 |
| Alembic heads | 唯一d2e7a46b910c |
| VERSION / 正式EXE产品版本 | 0.5.1 / 两份主程序EXE均0.5.1 |
| 文档链接 / git diff --check | 本地链接全有效 / 无实际错误 |

测试初次使用旧桌面源路径时5项集成夹具报文件不存在；改用交付目录中SHA完全匹配的固定Excel后，完整质量门通过。Windows沙箱曾阻止pytest临时目录清理和Vite realpath，改在正常用户环境运行通过，未为此改测试断言或业务源码。保留既有Starlette测试客户端弃用提示及Vite chunk大小提示，不在卫生阶段重构依赖或拆包。

### 正式基线复核

- main、origin/main、v0.5.1仍为 `04fe5719daa9b859005fc922daae3d4a975bf004`。
- maintenance/importer分支与精确tag的object/peeled commit均未改变。
- portable SHA：`8e59e50ff8cfe39ef13ac54e453b9b1ec9505eef1a1ae21f09c2ea1435c70ac8`。
- importer SHA：`25dd5ab503cb443f2db368c37cd5a4d5a3a084b127564db7479cae5d23e3e90e`。
- Excel SHA：`1099d3074570ef83f53c03ed24ffb413848dfd256969258d24fb41d049255f3e`。
- 三套dist目录的全文件树SHA摘要：delivery `866d816635bf333cb08191b479c4746e488727ad9de65d0e0f95d92efdada9ae`；importer `7ae9a1a068d599d3d570b4dbf97c39aafa4963b5cfa2104f7132abd61ec983f1`；portable `fcc3da13418bb44f1ce2593e85dc6b429d6db1d08298e6544dd4f5b5760d2d9e`。

提交按两批组织：`chore: protect delivery artifacts during project hygiene`与 `docs: consolidate v0.5.1 maintenance documentation`。最终HEAD与工作区状态以本分支提交后复核为准。不merge、不push任何分支，不创建tag或Release，不重建正式产物，不新增migration、不修改业务逻辑。

**PROJECT HYGIENE PASSED**
