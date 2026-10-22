from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Course, Enrollment, Teacher, Term
from .services import register


class CourseTestCase(TestCase):
    def setUp(self):
        self.term = Term.objects.create(code="114-1", is_current=True)
        self.teacher = Teacher.objects.create(name="T")
        self.u = get_user_model().objects.create_user("u")

    def course(self, code, start, end, capacity=40, day=1, term=None):
        return Course.objects.create(
            term=term or self.term, code=code, name=code, teacher=self.teacher,
            day=day, start_period=start, end_period=end, capacity=capacity)

    def mine(self):
        return Enrollment.objects.filter(user=self.u).count()


class RegisterTests(CourseTestCase):
    def test_enrolls(self):
        self.assertEqual(register(self.u, self.course("A", 1, 2)).code, "enrolled")
        self.assertEqual(self.mine(), 1)

    def test_already_enrolled(self):
        a = self.course("A", 1, 2)
        register(self.u, a)
        self.assertEqual(register(self.u, a).code, "already")
        self.assertEqual(self.mine(), 1)

    def test_overlap_is_rejected(self):
        self.course("A", 1, 2)
        a = Course.objects.get(code="A")
        b = self.course("B", 2, 3)  # 與 A 重疊一節
        register(self.u, a)
        self.assertEqual(register(self.u, b).code, "conflict")
        self.assertEqual(self.mine(), 1)

    def test_full_is_rejected(self):
        a = self.course("A", 1, 2, capacity=1)
        Enrollment.objects.create(user=get_user_model().objects.create_user("v"), course=a)
        self.assertEqual(register(self.u, a).code, "full")
        self.assertEqual(self.mine(), 0)

    @override_settings(MAX_CREDITS=3)
    def test_credit_limit_is_per_term(self):
        term2 = Term.objects.create(code="114-2")
        a = self.course("A", 1, 2)
        b = self.course("B", 1, 2, term=term2)  # 別的學期，同時段也不算衝堂、不算學分
        self.assertEqual(register(self.u, a).code, "enrolled")
        self.assertEqual(register(self.u, b).code, "enrolled")

    @override_settings(MAX_CREDITS=3)
    def test_over_credits_is_rejected(self):
        a = self.course("A", 1, 2)
        c = self.course("C", 4, 5)
        self.assertEqual(register(self.u, a).code, "enrolled")
        self.assertEqual(register(self.u, c).code, "over_credits")
        self.assertEqual(self.mine(), 1)


class EnrollViewTests(CourseTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.course("A", 1, 2, capacity=1)
        self.d = self.course("D", 4, 5)
        self.client.force_login(self.u)

    def post(self, course, name="enroll"):
        return self.client.post(reverse(name, args=[course.pk]), follow=True)

    def test_enroll_and_drop(self):
        self.post(self.a)
        self.assertEqual(self.mine(), 1)
        self.post(self.a, name="drop")
        self.assertEqual(self.mine(), 0)
        self.post(self.a)
        self.assertEqual(self.mine(), 1)

    def test_next_cannot_redirect_offsite(self):
        r = self.client.post(reverse("enroll", args=[self.a.pk]), {"next": "https://evil.example/x"})
        self.assertEqual(r["Location"], reverse("course_detail", args=[self.a.pk]))
        r = self.client.post(reverse("enroll", args=[self.d.pk]), {"next": "/my/"})
        self.assertEqual(r["Location"], "/my/")

    def test_list_only_shows_current_term(self):
        term2 = Term.objects.create(code="114-2")
        self.course("OLD", 1, 2, term=term2)
        codes = [c.code for c in self.client.get(reverse("course_list")).context["courses"]]
        self.assertIn("A", codes)
        self.assertNotIn("OLD", codes)

    def test_pages_render(self):
        for name, args in [("course_list", []), ("course_detail", [self.a.pk]), ("my_schedule", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)


class CourseConstraintTests(CourseTestCase):
    def test_end_before_start_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.course("BAD", 5, 3)

    def test_same_code_allowed_in_another_term(self):
        self.course("CS101", 1, 2)
        self.course("CS101", 1, 2, term=Term.objects.create(code="114-2"))
