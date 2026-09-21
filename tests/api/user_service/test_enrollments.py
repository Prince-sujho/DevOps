"""GET/POST/DELETE teacher-student enrollments."""

from __future__ import annotations

import pytest

from .conftest import create_user_body, student_profile_input, teacher_profile_input

pytestmark = pytest.mark.asyncio


async def _make_teacher_and_student(client, auth_headers):
    teacher = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(teacher_profile_input("919999933001"))
    )
    student = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999933002"))
    )
    return teacher.json()["userId"], student.json()["userId"]


async def test_get_enrollments_empty_for_unrelated_user(client, auth_headers):
    response = await client.get("/internal/users/no-such-user/enrollments", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"teacherUserIds": [], "studentUserIds": []}


async def test_create_enrollment_then_visible_from_both_sides(client, auth_headers):
    teacher_id, student_id = await _make_teacher_and_student(client, auth_headers)
    create = await client.post(
        "/internal/enrollments",
        headers=auth_headers,
        json={"teacherUserId": teacher_id, "studentUserId": student_id},
    )
    assert create.status_code == 204

    teacher_view = await client.get(f"/internal/users/{teacher_id}/enrollments", headers=auth_headers)
    assert teacher_view.json() == {"teacherUserIds": [], "studentUserIds": [student_id]}

    student_view = await client.get(f"/internal/users/{student_id}/enrollments", headers=auth_headers)
    assert student_view.json() == {"teacherUserIds": [teacher_id], "studentUserIds": []}


async def test_create_enrollment_422_missing_field(client, auth_headers):
    response = await client.post(
        "/internal/enrollments", headers=auth_headers, json={"teacherUserId": "t1"}
    )
    assert response.status_code == 422


async def test_delete_enrollment_removes_it(client, auth_headers):
    teacher_id, student_id = await _make_teacher_and_student(client, auth_headers)
    await client.post(
        "/internal/enrollments",
        headers=auth_headers,
        json={"teacherUserId": teacher_id, "studentUserId": student_id},
    )
    delete = await client.request(
        "DELETE",
        "/internal/enrollments",
        headers=auth_headers,
        json={"teacherUserId": teacher_id, "studentUserId": student_id},
    )
    assert delete.status_code == 204
    after = await client.get(f"/internal/users/{student_id}/enrollments", headers=auth_headers)
    assert after.json() == {"teacherUserIds": [], "studentUserIds": []}


async def test_delete_enrollment_422_missing_field(client, auth_headers):
    response = await client.request(
        "DELETE", "/internal/enrollments", headers=auth_headers, json={"studentUserId": "s1"}
    )
    assert response.status_code == 422
