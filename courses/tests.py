from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Course, Enrollment, Teacher


class EnrollTests(TestCase):
    def setUp(self):
        t = Teacher.objects.create(name="T")
        mk = lambda code, s, e, cap=1: Course.objects.create(
            code=code, name=code, teacher=t, day=1, start_period=s, end_period=e, capacity=cap)
        self.a, self.b, self.c = mk("A", 1, 2), mk("B", 2, 3), mk("C", 4, 5)
        self.u = get_user_model().objects.create_user("u")
        self.client.force_login(self.u)

    def post(self, course):
        return self.client.post(reverse("enroll", args=[course.pk]), follow=True)

    def test_enroll_conflict_full_and_drop(self):
        self.post(self.a)
        self.post(self.b)  # 與 A 衝堂
        self.assertEqual(Enrollment.objects.filter(user=self.u).count(), 1)
        other = get_user_model().objects.create_user("v")
        Enrollment.objects.create(user=other, course=self.c)  # C 名額 1，已滿
        self.post(self.c)
        self.assertEqual(Enrollment.objects.filter(user=self.u).count(), 1)
        self.client.post(reverse("drop", args=[self.a.pk]))
        self.assertEqual(Enrollment.objects.filter(user=self.u).count(), 0)

    def test_pages_render(self):
        for name, args in [("course_list", []), ("course_detail", [self.a.pk]), ("my_schedule", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
