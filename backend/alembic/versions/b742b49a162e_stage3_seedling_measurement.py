"""Require complete seedling measurements and explicit unavailable values.

Revision ID: b742b49a162e
Revises: 0b6111724c00
"""

from alembic import op
import sqlalchemy as sa


revision = "b742b49a162e"
down_revision = "0b6111724c00"
branch_labels = None
depends_on = None


def _prepare() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if bind.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("无法安全暂停 SQLite 外键检查，请先关闭其他事务后重试迁移")


def _verify() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and bind.exec_driver_sql("PRAGMA foreign_key_check").first():
        raise RuntimeError("幼苗测定迁移后的 SQLite 外键检查未通过")


def upgrade() -> None:
    bind = op.get_bind()
    incomplete = bind.execute(sa.text("""
        SELECT id FROM seedling_measurements
        WHERE measured_at IS NULL OR root_length_mm IS NULL OR shoot_length_mm IS NULL
           OR root_length_mm < 0 OR shoot_length_mm < 0
        LIMIT 1
    """)).first()
    if incomplete:
        raise RuntimeError(
            f"历史幼苗测定 {incomplete.id} 缺少时间或根苗长，或存在负值；请人工核对后再升级。"
            "迁移不会推测无法测量、零值或测定时间。"
        )
    _prepare()
    with op.batch_alter_table("seedling_measurements", recreate="always") as batch:
        batch.add_column(sa.Column("root_unavailable", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("shoot_unavailable", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch.alter_column("measured_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.drop_constraint("ck_root_length", type_="check")
        batch.drop_constraint("ck_shoot_length", type_="check")
        batch.create_check_constraint("ck_root_resolved", "(root_length_mm IS NOT NULL AND root_length_mm >= 0 AND root_unavailable = 0) OR (root_length_mm IS NULL AND root_unavailable = 1)")
        batch.create_check_constraint("ck_shoot_resolved", "(shoot_length_mm IS NOT NULL AND shoot_length_mm >= 0 AND shoot_unavailable = 0) OR (shoot_length_mm IS NULL AND shoot_unavailable = 1)")
    _verify()


def downgrade() -> None:
    bind = op.get_bind()
    lossy = bind.execute(sa.text("""
        SELECT id FROM seedling_measurements
        WHERE root_unavailable = 1 OR shoot_unavailable = 1 OR notes IS NOT NULL
        LIMIT 1
    """)).first()
    if lossy:
        raise RuntimeError(
            f"幼苗测定 {lossy.id} 包含无法测量状态或备注，旧版本不能保存这些事实；"
            "请先备份并人工处理，不会静默丢失数据。"
        )
    _prepare()
    with op.batch_alter_table("seedling_measurements", recreate="always") as batch:
        batch.drop_constraint("ck_root_resolved", type_="check")
        batch.drop_constraint("ck_shoot_resolved", type_="check")
        batch.create_check_constraint("ck_root_length", "root_length_mm IS NULL OR root_length_mm >= 0")
        batch.create_check_constraint("ck_shoot_length", "shoot_length_mm IS NULL OR shoot_length_mm >= 0")
        batch.alter_column("measured_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch.drop_column("notes")
        batch.drop_column("shoot_unavailable")
        batch.drop_column("root_unavailable")
    _verify()
