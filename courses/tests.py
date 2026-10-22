from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Course, Enrollment, Teacher


class EnrollTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(name="T")
        self.a = self.course("A", 1, 2, capacity=1)  # 名額 1
        self.b = self.course("B", 2, 3)  # 與 A 衝堂
        self.c = self.course("C", 4, 5)  # 不衝堂
        self.d = self.course("D", 1, 2, day=2)  # 換一天，不衝堂
        self.u = get_user_model().objects.create_user("u")
        self.client.force_login(self.u)

    def course(self, code, start, end, capacity=40, day=1):
        return Course.objects.create(
            code=code, name=code, teacher=self.teacher, day=day,
            start_period=start, end_period=end, capacity=capacity)

    def post(self, course, name="enroll"):
        return self.client.post(reverse(name, args=[course.pk]), follow=True)

    def mine(self):
        return Enrollment.objects.filter(user=self.u).count()

    def test_enroll_adds_course(self):
        self.post(self.a)
        self.assertEqual(self.mine(), 1)

    def test_overlapping_course_is_rejected(self):
        self.post(self.a)
        self.post(self.b)
        self.assertEqual(self.mine(), 1)

    def test_course_at_capacity_is_rejected(self):
        other = get_user_model().objects.create_user("v")
        Enrollment.objects.create(user=other, course=self.a)  # 名額 1 剛好滿
        self.post(self.a)
        self.assertEqual(self.mine(), 0)

    @override_settings(MAX_CREDITS=3)
    def test_credit_limit_is_enforced(self):
        self.post(self.a)  # 3 學分，剛好到上限
        self.post(self.c)  # 再加一門就超過
        self.assertEqual(self.mine(), 1)

    def test_drop_removes_enrollment(self):
        self.post(self.a)
        self.post(self.a, name="drop")
        self.assertEqual(self.mine(), 0)

    def test_can_reenroll_after_drop(self):
        self.post(self.a)
        self.post(self.a, name="drop")
        self.post(self.a)
        self.assertEqual(self.mine(), 1)

    def test_course_rejects_end_before_start(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Course.objects.create(code="BAD", name="BAD", teacher=self.teacher,
                                  day=1, start_period=5, end_period=3)

    def test_next_cannot_redirect_offsite(self):
        r = self.client.post(reverse("enroll", args=[self.a.pk]), {"next": "https://evil.example/x"})
        self.assertEqual(r["Location"], reverse("course_detail", args=[self.a.pk]))
        r = self.client.post(reverse("enroll", args=[self.d.pk]), {"next": "/my/"})
        self.assertEqual(r["Location"], "/my/")

    def test_pages_render(self):
        for name, args in [("course_list", []), ("course_detail", [self.a.pk]), ("my_schedule", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
