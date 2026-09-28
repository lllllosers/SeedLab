# Changelog

SeedLab 使用 [Semantic Versioning](https://semver.org/)；版本号唯一来源是 `backend/app/version.py`。0.x 为开发阶段，已发布 `v0.1.0` 和 `v0.2.0`。

## 未发布 — Stage 2 发芽实验执行

- 新增正式开始实验事务：从 effective 配置生成稳定编号的培养皿并记录实际置床时间；普通 PATCH 不能直接进入 `active`。
- 支持一天多次批量发芽巡检，空白与明确的 0 分开处理；累计、发芽率和观察期进度动态派生。
- 根据 `first_germinated` 和 `per_dish` / `per_material` 自动选择前 N 株，记录巡检来源与判定发芽时间；同时间按重复号确定稳定顺序。
- 提供巡检纠错与审计、独立执行页及第四个 Alembic 迁移；尚未开发根苗长测定。

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
