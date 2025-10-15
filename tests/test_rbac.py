import types
import pytest

from models import Base, Role, User, Group, Area, GuestAccess, SessionLocal, engine
from rbac import can_view_user, can_edit_entries
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine


@pytest.fixture()
def db_session():
    eng = create_engine('sqlite:///:memory:', future=True)
    TestingSession = sessionmaker(bind=eng, expire_on_commit=False)
    Base.metadata.create_all(eng)
    sess = TestingSession()
    yield sess
    sess.close()


def make_user(sess, email, role, group=None, area=None):
    if area is None:
        area = Area(name='A')
        sess.add(area); sess.flush()
    if group is None:
        group = Group(name='G', area=area)
        sess.add(group); sess.flush()
    u = User(email=email, name=email.split('@')[0], role=role, group=group, area=area, password_hash='x')
    sess.add(u); sess.flush()
    return u


def test_invitado_can_view_only_whitelisted(db_session):
    area = Area(name='A1'); db_session.add(area); db_session.flush()
    g = Group(name='G1', area=area); db_session.add(g); db_session.flush()
    guest = User(email='guest@test', name='guest', role=Role.invitado, password_hash='x')
    u1 = User(email='u1@test', name='u1', role=Role.employee, group=g, area=area, password_hash='x')
    u2 = User(email='u2@test', name='u2', role=Role.employee, group=g, area=area, password_hash='x')
    db_session.add_all([guest, u1, u2]); db_session.flush()
    # whitelist only u1
    db_session.add(GuestAccess(guest_user_id=guest.id, target_user_id=u1.id)); db_session.commit()

    assert can_view_user(guest, u1, db_session) is True
    assert can_view_user(guest, u2, db_session) is False
    # invitado nunca edita
    assert can_edit_entries(guest, u1) is False


def test_responsable_scope_group_can_and_cannot(db_session):
    a = Area(name='A1'); db_session.add(a); db_session.flush()
    g1 = Group(name='G1', area=a); g2 = Group(name='G2', area=a)
    db_session.add_all([g1, g2]); db_session.flush()
    resp = User(email='resp@test', name='resp', role=Role.responsable, group=g1, area=a, password_hash='x')
    e1 = User(email='e1@test', name='e1', role=Role.employee, group=g1, area=a, password_hash='x')
    e2 = User(email='e2@test', name='e2', role=Role.employee, group=g2, area=a, password_hash='x')
    db_session.add_all([resp, e1, e2]); db_session.commit()

    assert can_view_user(resp, e1) is True
    assert can_view_user(resp, e2) is False
    assert can_edit_entries(resp, e1) is True
    assert can_edit_entries(resp, e2) is False

