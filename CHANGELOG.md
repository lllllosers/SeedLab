# Changelog

SeedLab 使用 [Semantic Versioning](https://semver.org/)；版本号唯一来源是 `backend/app/version.py`。0.x 为开发阶段，Stage 0 验收后再考虑标记 `v0.1.0`。

## 0.1.0-dev — Stage 0 Foundation

- 修正幼苗测定计划为发芽后天数 DAG；通过第二个 Alembic 迁移增加样本实际发芽时间，保留首版迁移。
- 建立 FastAPI、SQLAlchemy、Alembic、SQLite 与 Vue 3 项目基础。
- 建立 13 个核心业务实体及会话表，完成首次迁移。
- 实现账号登录、CSRF 防护、物种与实验基础业务、种子批次、审计、工作台和物种数据交换。
- 建立自动化测试、Windows 启动入口与项目文档。
