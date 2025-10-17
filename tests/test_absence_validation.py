from datetime import datetime, timedelta, timezone

from typing import Optional

from models import Absence, Area, EntryStatus, Role, User


def _make_user(
    user_id: int,
    role: Role,
    *,
    group_id: Optional[int] = None,
    area_id: Optional[int] = None,
    responsible_id: Optional[int] = None,
) -> User:
    return User(
        id=user_id,
        email=f"user{user_id}@example.com",
        name=f"User {user_id}",
        password_hash="hashed",
        role=role,
        is_active=True,
        group_id=group_id,
        area_id=area_id,
        responsible_id=responsible_id,
    )


def _make_absence(worker: User) -> Absence:
    now = datetime.now(timezone.utc)
    return Absence(
        id=1,
        user_id=worker.id,
        user=worker,
        date_from=now,
        date_to=now + timedelta(days=1),
        type="vacaciones",
        status=EntryStatus.pending,
    )


def test_absence_can_be_validated_by_direct_responsible():
    area = Area(id=1, name="Area 1")
    responsible = _make_user(2, Role.responsable, group_id=10, area_id=area.id)
    worker = _make_user(3, Role.employee, group_id=10, area_id=area.id, responsible_id=responsible.id)

    # Link relationships manually
    worker.area = area
    responsible.area = area
    area.users.extend([worker, responsible])

    absence = _make_absence(worker)

    assert absence.can_be_validated_by(responsible)


def test_absence_can_be_validated_by_area_cap_assigned_to_area():
    area = Area(id=5, name="Area 5", cap_id=7)
    cap = _make_user(7, Role.cap_area, area_id=area.id)
    area.cap = cap
    worker = _make_user(8, Role.employee, area_id=area.id, responsible_id=None)
    worker.area = area
    area.users.append(worker)

    absence = _make_absence(worker)

    assert absence.can_be_validated_by(cap)


def test_absence_can_be_validated_by_admin():
    admin = _make_user(9, Role.admin)
    worker = _make_user(10, Role.employee, responsible_id=admin.id)
    absence = _make_absence(worker)

    assert absence.can_be_validated_by(admin)


def test_absence_not_validated_by_unrelated_user():
    area = Area(id=11, name="Area 11")
    worker = _make_user(12, Role.employee, group_id=4, area_id=area.id)
    worker.area = area
    outsider = _make_user(13, Role.employee)
    absence = _make_absence(worker)

    assert not absence.can_be_validated_by(outsider)
