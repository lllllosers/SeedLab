# Windows portable 构建与分发

当前已投产版本为 **v0.5.1**。版本唯一来源是 `backend/app/version.py`；数据库唯一 head 为 `d2e7a46b910c`。本目录保存打包入口与spec，当前质量门只构建前端，不重新生成已验收portable或importer。

## 开发构建

依赖由开发者明确安装，构建脚本不联网安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -e './backend[test,control,packaging]'
cd frontend
npm ci
cd ..
.\scripts\build_portable.ps1 -OutputName portable
```

此命令用于未来明确授权的构建，输出到默认开发分发目录 `dist/portable`。不要对本次保留的 `portable-v051` 执行构建。正式文件名从VERSION生成；后续重新构建会形成另一份产物，不能沿用原验收SHA。

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

正常运行无需Python、Node、Git或源码。程序目录只保存安装定位文件，正式数据库、配置、日志和备份位于独立Data Root。详见[用户说明](使用说明.txt)、[生产部署设计](../docs/10_生产部署与控制中心设计.md)。

## 当前产物与品牌维护

三套已验收目录保留在被Git忽略的dist中：`portable-v051`、`legacy-importer-v1`、`delivery-v051`。它们不属于备份，不作为源码或测试输入提交Git。本轮完整保留现有文件和哈希。版本、commit与正式SHA统一见[v0.5.1说明](../docs/releases/v0.5.1.md)。

`control_center/assets/seedlab.svg` 为品牌图形源；未来需要重生成时可运行 `scripts/build_brand_icon.py`，生成七尺寸ICO与通知PNG。本轮不改品牌资产。

importer的正式源码、spec和构建入口位于独立tag与maintenance分支，未合入主程序。见[importer维护索引](../docs/11_历史生产导入维护工具.md)。旧portable验收证据集中在[归档记录](../docs/archive/portable-v040-v041验收记录.md)，不在当前构建说明重复维护。
