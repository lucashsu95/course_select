from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Comment, Course, Enrollment, Teacher, Term
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


class CommentTests(CourseTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.course("A", 1, 2)
        self.url = reverse("add_comment", args=[self.a.pk])

    def post(self, body, **kwargs):
        return self.client.post(self.url, {"body": body}, **kwargs)

    def test_login_required(self):
        r = self.post("hi")
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("google_login"), r["Location"])
        self.assertEqual(self.a.comments.count(), 0)

    def test_posts_and_lists(self):
        self.client.force_login(self.u)
        r = self.post("  會點名嗎？  ", follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("course_detail", args=[self.a.pk]))
        c = self.a.comments.get()
        self.assertEqual(c.body, "會點名嗎？")
        self.assertContains(r, "會點名嗎？")

    def test_blank_is_rejected(self):
        self.client.force_login(self.u)
        r = self.post("   ", follow=True)
        self.assertEqual(self.a.comments.count(), 0)
        self.assertContains(r, "留言不能是空白。")

    def test_too_long_is_rejected(self):
        self.client.force_login(self.u)
        r = self.post("字" * (Comment.MAX_LENGTH + 1), follow=True)
        self.assertEqual(self.a.comments.count(), 0)
        self.assertContains(r, "留言最多")

    def test_anonymous_sees_login_hint_not_form(self):
        r = self.client.get(reverse("course_detail", args=[self.a.pk]))
        self.assertContains(r, "登入後才能留言")
        self.assertNotContains(r, self.url)


class TeacherRoleTests(CourseTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.course("A", 1, 2)
        self.student = get_user_model().objects.create_user("s", first_name="王小明", email="s@example.com")
        Enrollment.objects.create(user=self.student, course=self.a)
        self.teacher.user = self.u
        self.teacher.save()

    def test_teaching_lists_only_own_current_term_courses(self):
        self.course("OLD", 1, 2, term=Term.objects.create(code="114-2"))
        self.client.force_login(self.u)
        r = self.client.get(reverse("teaching"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c.pk for c in r.context["courses"]], [self.a.pk])

    def test_unbound_user_sees_empty_teaching_page(self):
        self.client.force_login(self.student)
        r = self.client.get(reverse("teaching"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(list(r.context["courses"]), [])
        self.assertContains(r, "這學期沒有你的課程")

    def test_roster_shows_student_name(self):
        self.client.force_login(self.u)
        r = self.client.get(reverse("course_roster", args=[self.a.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "王小明")
        self.assertContains(r, "s@example.com")

    def test_other_user_gets_404_on_roster(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("course_roster", args=[self.a.pk])).status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        for name, args in [("teaching", []), ("course_roster", [self.a.pk])]:
            r = self.client.get(reverse(name, args=args))
            self.assertEqual(r.status_code, 302)
            self.assertIn(reverse("google_login"), r["Location"])
        self.assertEqual(self.client.get(reverse("course_list")).status_code, 200)

    def test_roster_link_only_for_teacher(self):
        detail = reverse("course_detail", args=[self.a.pk])
        roster = reverse("course_roster", args=[self.a.pk])
        self.assertNotContains(self.client.get(detail), roster)
        self.client.force_login(self.student)
        self.assertNotContains(self.client.get(detail), roster)
        self.client.force_login(self.u)
        self.assertContains(self.client.get(detail), roster)

    def test_deleting_user_keeps_teacher(self):
        self.u.delete()
        self.teacher.refresh_from_db()
        self.assertIsNone(self.teacher.user)
        self.assertTrue(Course.objects.filter(pk=self.a.pk).exists())


class CourseConstraintTests(CourseTestCase):
    def test_end_before_start_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.course("BAD", 5, 3)

    def test_same_code_allowed_in_another_term(self):
        self.course("CS101", 1, 2)
        self.course("CS101", 1, 2, term=Term.objects.create(code="114-2"))
