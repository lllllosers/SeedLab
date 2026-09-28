# Changelog

SeedLab 使用 [Semantic Versioning](https://semver.org/)；版本号唯一来源是 `backend/app/version.py`。0.x 为开发阶段，已发布 `v0.1.0`、`v0.2.0`、`v0.3.0` 和 `v0.3.1`。

## 0.3.1 — Account Bootstrap and Management（Stage 2.5）

- 首次部署可在浏览器使用服务器本机一次性初始化码创建管理员并建立会话；成功后初始化入口关闭，CLI 仍可用于应急维护。
- 管理员可以创建成员、编辑姓名、调整角色、启停账号、重置临时密码；用户可以修改自己的密码，首次登录必须修改管理员设置的临时密码。
- 统一 8 至 128 位密码规则；改密、重置和停用清除相关会话；保护本人账号和最后一个启用的管理员，审计不保存密码或初始化码。
- 新增 `must_change_password` 迁移与账号页面。Stage 3 的 DAG 测定任务、根苗长录入及统计分析尚未实现。

## 0.3.0 — Germination Execution（Stage 2）

- 在既有实验配置基础上，新增正式开始实验事务：从 effective 配置生成稳定编号的培养皿并记录实际置床时间；普通 PATCH 不能直接进入 `active`。
- 支持一天多次批量发芽巡检，空白与明确的 0 分开处理；累计发芽数、发芽率和观察期进度动态派生。
- 根据 `first_germinated` 和 `per_dish` / `per_material` 自动选择前 N 株，记录 SeedlingSample 来源巡检与判定发芽时间；同时间按重复号确定稳定顺序。
- 提供巡检纠错与审计、独立执行页及第四个 Alembic 迁移。
- Stage 3 尚未实现 DAG 今日测定任务、根长苗长录入、`SeedlingMeasurement` 正式操作接口、测定历史与快速纠错，以及数据统计分析。

## 0.2.0 — Stage 1 实验配置

- 增加七步实验创建向导、可编辑的实验详情和动态工作量估算。
- 扩展默认实验方案、材料参数覆盖、材料显示顺序、计划开始日期和 `ready` 状态；通过第三个 Alembic 迁移升级。
- 建立统一的 effective 参数计算、两种取样范围的容量校验、动态 DAG API 与配置保护。
- 保留 Stage 0 发芽后 DAG 语义；本阶段不生成培养皿、幼苗样本或测定任务。

## 0.1.0 — Stage 0 Foundation

- 修正幼苗测定计划为发芽后天数 DAG；通过第二个 Alembic 迁移增加样本发芽判定时间字段，保留首版迁移。
- 建立 FastAPI、SQLAlchemy、Alembic、SQLite 与 Vue 3 项目基础。
- 建立 13 个核心业务实体及会话表，完成首次迁移。
- 实现账号登录、CSRF 防护、物种与实验基础业务、种子批次、审计、工作台和物种数据交换。
- 建立自动化测试、Windows 启动入口与项目文档。
