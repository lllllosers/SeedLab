# Windows portable 构建与分发

当前已投产版本为 **v0.5.1**；本阶段构建 **v0.6.0 开发验收产物**，尚未 tag 或 Release。版本唯一来源为 `backend/app/version.py`，数据库 head 为 `d2e7a46b910c`，10 个迁移不变。已验收 v0.5.1 portable、importer、delivery 保持冻结。

## 开发构建

依赖由开发者明确安装，构建脚本不联网安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -e './backend[test,control,packaging]'
cd frontend
npm ci
cd ..
.\scripts\build_portable.ps1 -OutputName portable-v060
.\.venv\Scripts\python.exe scripts\build_operations.py
.\.venv\Scripts\python.exe scripts\check_operations.py --directory .\dist\operations-v060
.\.venv\Scripts\python.exe scripts\smoke_operations.py --artifacts .\dist\operations-v060
```

portable 输出到 `dist/portable-v060`，独立工具、upgrade ZIP 和报告输出到 `dist/operations-v060`。构建脚本使用已有依赖，不自动安装。`portable-v051` 显式禁止作为重建目标。所有文件名由 VERSION 生成，构建后记录的单一 ZIP SHA 仅属于该次产物，不沿用旧 SHA。

脚本只清理带 `.seedlab-build-owned` 标记的选定输出和build工作目录，核对路径与后代重定向，遇到运行数据、部署配置或数据库时拒绝删除。前端产物放入 `app/web`，全部Alembic资源放入 `app/migrations`；构建验证迁移head、目录/ZIP禁止项与CRC，生成artifact-report。源码构建入口 `build_production.ps1` 仅运行前端production build。

## 分发结构与运行

```text
SeedLab/
  SeedLab Control Center.exe
  SeedLabServer.exe
  _internal/
  app/web/
  app/migrations/
  config/                         首次部署前为空
  使用说明.txt
  LICENSE
  AUTHORS.md
```

`seedlab.spec` 使用两个Analysis、两个PYZ/EXE和共享COLLECT，服务器由控制中心隐藏启动。UTF-8、无缓冲stdout、版本资源和品牌资源显式打包；PyInstaller收集动态模型、SQLite、Uvicorn、Qt、Argon2、拼音与时区资源。`scripts/check_portable.py` 是只读目录/ZIP安全门，也由回归测试覆盖。

`write_build_info.py` 写入 app/build-info.json，包含应用版本、唯一 Alembic head 和 Git 构建身份（未提交 tree 会明确标 dirty）。发布验收应使用提交后的精确 tree。该文件与 upgrade manifest 共用身份，不引入逐文件 hash。

## 离线升级交付

`operations.spec` 分别 onefile 构建小型 Launcher、独立 Qt Updater 和 Bootstrap。Launcher 不含 Qt/数据库/升级 GUI；Updater 自带运行库，完全独立于 App `_internal`。Bootstrap 内嵌该次 upgrade ZIP 和两项工具，与普通 Updater 共用 `production_ops` executor，没有第二套升级核心。

~~~text
dist/operations-v060/
  tools/SeedLab Launcher.exe
  tools/SeedLab Updater.exe
  SeedLab-v0.6.0-Upgrade.exe
  SeedLab-v0.6.0-upgrade.zip
  artifact-report.json
~~~

upgrade ZIP 采用 manifest.json + payload/SeedLab，manifest 保存版本、支持来源、revision、build identity、format/updater protocol 和简洁 migration 信息。CRC、安全解包、必需文件及基本版本一致性作为完整性门，**无逐文件 SHA manifest、无签名、无在线下载**。报告记录整个 upgrade ZIP 单一 SHA256 和产物尺寸，普通用户无需处理 SHA。

`check_operations.py` 只读检查 ZIP、PE 版本和 CArchive 内独立 runtime，确认 Bootstrap 内嵌交付完整。`smoke_operations.py` 只在 OS TEMP 创建合成实验/账号，复制冻结 v0.5.1 作为隔离旧程序，测试真实 EXE 依赖、旧 Server 运行时 staging、v060 candidate Control Center/Server、一次备份、commit 和原数据库 same-schema 回退；成功清理临时目录，失败保留诊断路径。不登记桌面/HKCU 启动入口，**不访问 Production Mirror**，合成库不能称为 production clone。镜像上的真实 GUI 升级及最终生产发布须另行授权。

正常运行无需Python、Node、Git或源码。程序目录只保存安装定位文件，正式数据库、配置、日志和备份位于独立Data Root。详见[用户说明](使用说明.txt)、[生产部署设计](../docs/10_生产部署与控制中心设计.md)。

## 当前产物与品牌维护

三套已验收目录保留在被Git忽略的dist中：`portable-v051`、`legacy-importer-v1`、`delivery-v051`。它们不属于备份，不提交Git；历史回归可只读使用其中固定SHA的Excel源，不运行正式部署或importer。本轮完整保留现有文件和哈希。版本、commit与正式SHA统一见[v0.5.1说明](../docs/releases/v0.5.1.md)。

`control_center/assets/seedlab.svg` 为品牌图形源；未来需要重生成时可运行 `scripts/build_brand_icon.py`，生成七尺寸ICO与通知PNG。本轮不改品牌资产。

importer的正式源码、spec和构建入口位于独立tag与maintenance分支，未合入主程序。精确实现与原验收提交见[v0.5.1 追溯索引](../docs/releases/v0.5.1.md#importer与历史验收追溯)。旧 portable 开发验收过程由 Git 历史保留，正式交付说明统一位于[releases](../docs/README.md#发布历史)。
