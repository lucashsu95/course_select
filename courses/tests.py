from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Course, Enrollment, Section, Teacher, Term
from .services import register


class CourseTestCase(TestCase):
    def setUp(self):
        self.term = Term.objects.create(code="114-1", is_current=True)
        self.teacher = Teacher.objects.create(name="T")
        self.u = get_user_model().objects.create_user("u")

    def course(self, code, term=None):
        c, _ = Course.objects.get_or_create(term=term or self.term, code=code,
                                            defaults=dict(name=code, teacher=self.teacher))
        return c

    def section(self, code, label, start, end, capacity=40, day=1, term=None):
        return Section.objects.create(
            course=self.course(code, term=term),
            label=label, day=day, start_period=start, end_period=end, capacity=capacity)

    def my_sections(self):
        return list(Section.objects.filter(enrollment__user=self.u))

    def mine(self):
        return Enrollment.objects.filter(user=self.u).count()


class RegisterTests(CourseTestCase):
    def test_enrolls(self):
        self.assertEqual(register(self.u, self.section("A", "A", 1, 2)).code, "enrolled")
        self.assertEqual(self.mine(), 1)

    def test_already_enrolled_same_section(self):
        a = self.section("A", "A", 1, 2)
        register(self.u, a)
        self.assertEqual(register(self.u, a).code, "already")
        self.assertEqual(self.mine(), 1)

    def test_other_section_of_same_course_is_rejected(self):
        a = self.section("A", "A", 1, 2)
        b = self.section("A", "B", 4, 5)  # 同課的 B 班，不同時段
        register(self.u, a)
        r = register(self.u, b)
        self.assertEqual(r.code, "already")
        self.assertIn("A 班", r.message)
        self.assertEqual(self.mine(), 1)

    def test_can_switch_section_after_dropping(self):
        a = self.section("A", "A", 1, 2)
        b = self.section("A", "B", 4, 5)
        register(self.u, a)
        Enrollment.objects.filter(user=self.u, section=a).delete()
        self.assertEqual(register(self.u, b).code, "enrolled")
        self.assertEqual(self.mine(), 1)

    def test_overlap_is_rejected(self):
        a = self.section("A", "A", 1, 2)
        b = self.section("B", "A", 2, 3)  # 不同課程，重疊一節
        register(self.u, a)
        r = register(self.u, b)
        self.assertEqual(r.code, "conflict")
        self.assertIn("B", r.message)
        self.assertEqual(self.mine(), 1)

    def test_conflict_checked_per_section_time(self):
        a1 = self.section("A", "A", 1, 2)   # A 課 A 班：週一 1-2
        b1 = self.section("B", "A", 4, 5)   # B 課 A 班：週一 4-5（不衝堂）
        register(self.u, a1)
        self.assertEqual(register(self.u, b1).code, "enrolled")

    def test_full_is_rejected_per_section(self):
        a = self.section("A", "A", 1, 2, capacity=1)
        b = self.section("A", "B", 4, 5)
        Enrollment.objects.create(user=get_user_model().objects.create_user("v"), section=a)
        self.assertEqual(register(self.u, a).code, "full")  # A 班滿
        self.assertEqual(register(self.u, b).code, "enrolled")  # B 班不受影響
        self.assertEqual(self.mine(), 1)

    @override_settings(MAX_CREDITS=3)
    def test_credit_limit_is_per_term(self):
        term2 = Term.objects.create(code="114-2")
        a = self.section("A", "A", 1, 2)
        b = self.section("B", "A", 1, 2, term=term2)  # 別的學期，同時段也不算衝堂、不算學分
        self.assertEqual(register(self.u, a).code, "enrolled")
        self.assertEqual(register(self.u, b).code, "enrolled")

    @override_settings(MAX_CREDITS=3)
    def test_over_credits_is_rejected(self):
        a = self.section("A", "A", 1, 2)
        c = self.section("C", "A", 4, 5)
        self.assertEqual(register(self.u, a).code, "enrolled")
        self.assertEqual(register(self.u, c).code, "over_credits")
        self.assertEqual(self.mine(), 1)


class EnrollViewTests(CourseTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.section("A", "A", 1, 2, capacity=1)
        self.d = self.section("D", "A", 4, 5)
        self.client.force_login(self.u)

    def post(self, section, name="enroll"):
        return self.client.post(reverse(name, args=[section.pk]), follow=True)

    def test_enroll_and_drop(self):
        self.post(self.a)
        self.assertEqual(self.mine(), 1)
        self.post(self.a, name="drop")
        self.assertEqual(self.mine(), 0)
        self.post(self.a)
        self.assertEqual(self.mine(), 1)

    def test_next_cannot_redirect_offsite(self):
        r = self.client.post(reverse("enroll", args=[self.a.pk]), {"next": "https://evil.example/x"})
        self.assertEqual(r["Location"], reverse("course_detail", args=[self.a.course_id]))
        r = self.client.post(reverse("enroll", args=[self.d.pk]), {"next": "/my/"})
        self.assertEqual(r["Location"], "/my/")

    def test_list_shows_sections_of_current_term_only(self):
        term2 = Term.objects.create(code="114-2")
        self.section("OLD", "A", 1, 2, term=term2)
        rows = self.client.get(reverse("course_list")).context["sections"]
        codes = [s.course.code for s in rows]
        self.assertIn("A", codes)
        self.assertNotIn("OLD", codes)

    def test_pages_render(self):
        for name, args in [("course_list", []), ("course_detail", [self.a.course_id]), ("my_schedule", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)


class TeacherRoleTests(CourseTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.section("A", "A", 1, 2)
        self.student = get_user_model().objects.create_user("s", first_name="王小明", email="s@example.com")
        Enrollment.objects.create(user=self.student, section=self.a)
        self.teacher.user = self.u
        self.teacher.save()

    def test_teaching_lists_only_own_current_term_courses(self):
        self.section("OLD", "A", 1, 2, term=Term.objects.create(code="114-2"))
        self.client.force_login(self.u)
        r = self.client.get(reverse("teaching"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c.pk for c in r.context["courses"]], [self.a.course_id])

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


class SectionConstraintTests(CourseTestCase):
    def test_end_before_start_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.section("BAD", "A", 5, 3)

    def test_same_code_allowed_in_another_term(self):
        self.section("CS101", "A", 1, 2)
        self.section("CS101", "A", 1, 2, term=Term.objects.create(code="114-2"))

    def test_duplicate_label_in_same_course_is_rejected(self):
        self.section("A", "A", 1, 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.section("A", "A", 4, 5)
