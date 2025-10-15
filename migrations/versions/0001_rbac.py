from alembic import op
import sqlalchemy as sa

revision = '0001_rbac'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('areas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=120), nullable=False, unique=True)
    )
    op.create_table('groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('area_id', sa.Integer(), sa.ForeignKey('areas.id'), nullable=False)
    )
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('group_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('area_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_users_group', 'users', 'groups', ['group_id'], ['id'])
    op.create_foreign_key('fk_users_area', 'users', 'areas', ['area_id'], ['id'])

    op.create_table('time_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('ts_in', sa.DateTime(timezone=True)),
        sa.Column('ts_out', sa.DateTime(timezone=True)),
        sa.Column('type', sa.Enum('in', 'out', 'pause', name='timeentrytype')),
        sa.Column('status', sa.Enum('pending', 'approved', 'rejected', name='entrystatus'), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True))
    )

    op.create_table('absences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('date_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('date_to', sa.DateTime(timezone=True), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.Enum('pending', 'approved', 'rejected', name='absencestatus'), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True))
    )

    op.create_table('guest_access',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('guest_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('target_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False)
    )


def downgrade():
    op.drop_table('guest_access')
    op.drop_table('absences')
    op.drop_table('time_entries')
    op.drop_constraint('fk_users_area', 'users', type_='foreignkey')
    op.drop_constraint('fk_users_group', 'users', type_='foreignkey')
    op.drop_column('users', 'area_id')
    op.drop_column('users', 'group_id')
    op.drop_column('users', 'is_active')
    op.drop_table('groups')
    op.drop_table('areas')

