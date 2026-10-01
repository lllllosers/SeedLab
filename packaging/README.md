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

QLocalServer/QLocalSocket 提供用户会话单实例，第二次运行激活已有窗口并退出 0。--startup 已部署时留在托盘，未部署时仍显示向导。auto_start_server 默认 false，旧 schema 1 缺字段兼容；首次初始化完成仍自动启动一次。

登录启动只管理 HKCU\Software\Microsoft\Windows\CurrentVersion\Run 的 SeedLabControlCenter 值：带引号的绝对控制中心 EXE 路径加 --startup。默认关闭，开发模式禁用；旧位置只提示，明确保存才更新，取消只删除该值。

候选 ZIP 必须在仓库外、收缩 PATH、隔离数据条件下验证实际 EXE。此机安装了开发工具，不能称为“干净 Windows 验证”。另一设备 LAN、真实 SakuraFrp、真实登录启动和 UI 未实测部分须如实记录，完整验收前不能宣布全部通过。

内部包未签名，不改变 Windows 安全策略。没有实现升级、恢复、系统服务或安装器。

## 本轮验证记录（2026-10-01）

- 源码回归：后端 194 passed / 1 skipped；前端 18 passed，构建成功。迁移 head 保持 c6d91f28a405，没有修改 VERSION 或历史迁移。
- 最终候选 ZIP 已在仓库外的含空格及中文程序目录解压，运行 PATH 仅保留 Windows 系统目录。真实服务器从空数据目录完成迁移，数据库完整性正常、外键检查为空；真实浏览器完成管理员创建、登录、Excel 导入/模板导出、实验创建与拼音编号、巡检及测定页面检查。
- 中文路径的真实控制中心通过显式临时数据参数和 --startup 启动服务器、生成有效的每日自动备份，并复用账号登录；第二个 EXE 退出 0，第一实例继续运行。实际子进程为包内 SeedLabServer.exe，命令和运行日志没有开发仓库路径，外部 web/migrations 没有生成字节码缓存。
- 同机局域网地址完成登录；远程模式 Secure Cookie 通过本地隔离服务验证。这不等于第二设备 LAN 或真实 SakuraFrp 验收。
- Windows 窗口工具两次初始化失败（os error 3），首次向导、托盘交互、手工备份按钮、真实登录启动设置以及其余五张窗口截图等待人工验证。显式临时目录的自动启动验证不能代替普通首次部署向导或完整托盘操作验收。未完成全部人工门，不能宣布 portable 全部通过。
- 只结束代理所属临时控制中心，服务器先通过停机信号正常退出；用户的现有开发服务保持运行。没有操作真实登录启动注册表，没有更改 Windows 安全设置，没有进行干净 Windows 或 VM 验证。
