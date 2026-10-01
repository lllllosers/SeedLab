# Windows portable 内部候选包

VERSION 保持 0.4.0。本目录只保存打包源码，不发布 tag 或 GitHub Release。

## 构建

先在 Windows 开发环境手工准备依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e './backend[test,control,packaging]'
cd frontend
npm install
cd ..
.\scripts\build_portable.ps1
```

实际工具为 PyInstaller 6.22.3。packaging 可选依赖接受 6.x，构建检查版本并打印。脚本不联网安装，仅清理带所有权标记的 build/portable-pyinstaller、build/portable-cache、dist/portable；路径或后代有重定向时拒绝删除，不碰用户数据。

一个 spec、两次 Analysis、两个 PYZ/EXE、一个共享 COLLECT。控制中心为 windowed；服务器保留 stdout，由控制中心 CREATE_NO_WINDOW 启动。两份 EXE 共用 _internal，服务器在程序根目录，避免复制整套 DLL。前端和迁移源码放在 app/web、app/migrations，运行时禁止写入字节码缓存。动态模型、SQLite、Uvicorn、Qt Network/SVG、Argon2、拼音和 tzdata 通过 spec/hook 收集。

spec 显式设置冻结解释器 UTF-8 与无缓冲 stdout。冻结解释器不读取 PYTHONUTF8；服务输出必须与控制中心 UTF-8 日志管道一致，不能依赖用户的 Windows 区域设置。

```text
dist/portable/SeedLab/
  SeedLab Control Center.exe
  SeedLabServer.exe
  _internal/
  app/web/
  app/migrations/
  config/                         首次部署前为空
  使用说明.txt
  LICENSE
  AUTHORS.md
dist/portable/SeedLab-v0.4.0-stage35-portable-test.zip
dist/portable/artifact-report.json
```

脚本验证迁移 head，扫描目录及 ZIP 的用户数据、配置、日志、开发资产、重定向和 CRC，报告数量、体积及最大 20 个文件。候选包日常不调用 Python、Node、npm 或 Git；构建仍需要开发依赖。

## 运行与验收

RuntimePaths 集中解析 program_root（EXE 根）、resource_root（冻结依赖目录）和 data_root（独立数据）。移动程序不改变 installation.json 的绝对数据位置。首次部署需要程序 config 可写，不提权、不使用 VirtualStore。

QLocalServer/QLocalSocket 在当前用户会话内按程序目录和数据目录隔离控制中心；同一程序或同一数据目录重复运行时激活已有窗口并退出 0。--startup 已部署时留在托盘，未部署时仍显示向导。auto_start_server 默认 false，旧 schema 1 缺字段兼容；首次初始化完成仍自动启动一次。

登录启动只管理 HKCU\Software\Microsoft\Windows\CurrentVersion\Run 的 SeedLabControlCenter 值：带引号的绝对控制中心 EXE 路径加 --startup。默认关闭，开发模式禁用；旧位置只提示，明确保存才更新，取消只删除该值。

候选 ZIP 必须在仓库外、收缩 PATH、隔离数据条件下验证实际 EXE。此机安装了开发工具，不能称为“干净 Windows 验证”。另一设备 LAN、真实 SakuraFrp、真实登录启动和 UI 未实测部分须如实记录，完整验收前不能宣布全部通过。

内部包未签名，不改变 Windows 安全策略。没有实现升级、恢复、系统服务或安装器。

## 实例隔离与修复候选包

每份数据目录的 config/instance.json 保存独立部署编号和本机探测凭据；已有部署缺文件时安全补建，不修改业务库结构。公开 health 继续只返回状态与版本，携带本部署凭据的控制中心才能读取部署编号、数据目录、端口、访问方式、监听地址和进程号。控制中心核对身份、规范化数据路径、端口、访问方式和自己启动的进程号；另一份服务及缺少身份的旧版均不接管、不读取账号状态、不提供停止或重启。

单实例锁分别按当前 Windows 会话中的程序目录和数据目录建立。同一程序重复运行激活已有窗口，同一数据目录的不同程序副本也只保留一个控制中心；不同部署不会被全会话锁带入旧窗口。首次向导完成后再取得数据目录锁。

首次部署在数据写入前检查端口。访问方式页可修改端口，冲突时返回该步骤处理；新空目录准备独立初始化码，已有目录保留账号。HTTP 会话、初始化码及 Cookie 设置绑定当前应用的显式 Settings；导入模块不再创建默认数据库目录。LAN 保存并重启后由实际服务响应确认 0.0.0.0 和 LAN 模式，未生效时明确显示当前与已保存配置不同。

SeedLab.ico 从现有品牌 SVG 生成七个尺寸；EXE、主窗口、向导、托盘及通知共用该图形。Windows 产品描述从唯一 VERSION 动态生成；任务栏使用 SeedLab.ControlCenter，便携版仅注册当前用户该产品的 DisplayName/IconUri，不修改其他产品或登录启动项。通知名称统一为“SeedLab 运行控制中心”。真实 Windows 图标缓存与通知外观仍需人工验收。

重建修复候选包可运行 `scripts/build_portable.ps1 -OutputName portable-instance-fix`，输出在 dist/portable-instance-fix。此方式保留此前人工部署的 dist/portable；默认构建仍遇到用户部署文件时拒绝清理。运行身份文件与凭据禁止进入候选 ZIP。

### 本轮修复验证

- 后端完整回归 211 passed / 1 skipped，其中新增 17 项实例隔离及品牌测试；前端 18 passed，生产构建成功。pip check、npm ls、Alembic current/check、git diff --check 通过；迁移 head 保持 c6d91f28a405，VERSION 保持 0.4.0。
- 最终候选 ZIP 在仓库外的中文及空格路径解压，运行 PATH 只保留 Windows 系统目录。旧实例占用端口时，新部署在写入前拒绝继续；另一个控制中心不能读取旧实例账号状态，也不能停止或重启它。全新数据目录无账号、初始化码独立，真实浏览器完成 /setup 创建管理员和登录；另一份数据的账号不能登录新库。
- 真实冻结服务器经保存和正常重启，在 127.0.0.1 本机模式与 0.0.0.0 LAN 模式之间切换；同机 LAN IPv4 地址完成访问及新账号登录，三个控制中心页面显示一致。普通安装定位文件启动的真实控制中心复用新库及账号；同程序重复启动、不同程序副本指向同数据目录均退出 0，原控制中心继续运行。子进程只使用包内 SeedLabServer.exe。
- 两份 EXE 均含同源七尺寸图标及 0.4.0 产品资源；当前用户产品显示名称实际注册为“SeedLab 运行控制中心”。程序目录未创建默认 data 或外部资源字节码缓存；既有正式配置、数据库及备份的 12 个受保护文件哈希保持不变，数据库只读完整性及外键检查通过。用户原有控制中心未被停止。
- Windows 窗口自动化工具两次初始化失败（helper_unknown_error）。EXE 图标、主窗口、五步向导、任务栏、托盘、通知横幅的真实视觉和交互仍待人工验收；自动化资源检查及正常安装定位文件重开不能代替这些人工步骤。第二设备 LAN、真实 SakuraFrp 和干净 Windows 环境也未验证。

## Phase 4B 初版验证记录（2026-10-01）

- 源码回归：后端 194 passed / 1 skipped；前端 18 passed，构建成功。迁移 head 保持 c6d91f28a405，没有修改 VERSION 或历史迁移。
- 最终候选 ZIP 已在仓库外的含空格及中文程序目录解压，运行 PATH 仅保留 Windows 系统目录。真实服务器从空数据目录完成迁移，数据库完整性正常、外键检查为空；真实浏览器完成管理员创建、登录、Excel 导入/模板导出、实验创建与拼音编号、巡检及测定页面检查。
- 中文路径的真实控制中心通过显式临时数据参数和 --startup 启动服务器、生成有效的每日自动备份，并复用账号登录；第二个 EXE 退出 0，第一实例继续运行。实际子进程为包内 SeedLabServer.exe，命令和运行日志没有开发仓库路径，外部 web/migrations 没有生成字节码缓存。
- 同机局域网地址完成登录；远程模式 Secure Cookie 通过本地隔离服务验证。这不等于第二设备 LAN 或真实 SakuraFrp 验收。
- Windows 窗口工具两次初始化失败（os error 3），首次向导、托盘交互、手工备份按钮、真实登录启动设置以及其余五张窗口截图等待人工验证。显式临时目录的自动启动验证不能代替普通首次部署向导或完整托盘操作验收。未完成全部人工门，不能宣布 portable 全部通过。
- 只结束代理所属临时控制中心，服务器先通过停机信号正常退出；用户的现有开发服务保持运行。没有操作真实登录启动注册表，没有更改 Windows 安全设置，没有进行干净 Windows 或 VM 验证。
