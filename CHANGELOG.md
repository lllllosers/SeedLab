# Changelog

SeedLab 使用 [Semantic Versioning](https://semver.org/)；版本号唯一来源是 `backend/app/version.py`。0.x 为开发阶段，已发布 `v0.1.0` 和 `v0.2.0`。

## 0.2.0 — Stage 1 实验配置

- 增加七步实验创建向导、可编辑的实验详情和动态工作量估算。
- 扩展默认实验方案、材料参数覆盖、材料显示顺序、计划开始日期和 `ready` 状态；通过第三个 Alembic 迁移升级。
- 建立统一的 effective 参数计算、两种取样范围的容量校验、动态 DAG API 与配置保护。
- 保留 Stage 0 发芽后 DAG 语义；本阶段不生成培养皿、幼苗样本或测定任务。

## 0.1.0 — Stage 0 Foundation

- 修正幼苗测定计划为发芽后天数 DAG；通过第二个 Alembic 迁移增加样本实际发芽时间，保留首版迁移。
- 建立 FastAPI、SQLAlchemy、Alembic、SQLite 与 Vue 3 项目基础。
- 建立 13 个核心业务实体及会话表，完成首次迁移。
- 实现账号登录、CSRF 防护、物种与实验基础业务、种子批次、审计、工作台和物种数据交换。
- 建立自动化测试、Windows 启动入口与项目文档。
