from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Course, Enrollment, Section, Teacher, Term, Waitlist
from .services import cancel_waitlist, drop_enrollment, register


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
        return list(Section.objects.filter(enrollments__user=self.u))

    def mine(self):
        return Enrollment.objects.filter(user=self.u).count()


class RegisterTests(CourseTestCase):
    def test_enrolls(self):
        a = self.section("A", "A", 1, 2)
        self.assertEqual(register(self.u, a).code, "enrolled")
        self.assertEqual(self.mine(), 1)
        self.assertEqual([s.pk for s in self.my_sections()], [a.pk])

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
        # 衝堂訊息引用的是「已選」的 A 課 A 班，不是被擋的 B
        self.assertIn("A 班", r.message)
        self.assertEqual(self.mine(), 1)

    def test_conflict_checked_per_section_time(self):
        a1 = self.section("A", "A", 1, 2)   # A 課 A 班：週一 1-2
        b1 = self.section("B", "A", 4, 5)   # B 課 A 班：週一 4-5（不衝堂）
        register(self.u, a1)
        self.assertEqual(register(self.u, b1).code, "enrolled")

    def test_full_section_goes_to_waitlist(self):
        a = self.section("A", "A", 1, 2, capacity=1)
        b = self.section("A", "B", 4, 5)
        Enrollment.objects.create(user=get_user_model().objects.create_user("v"), section=a)
        self.assertEqual(register(self.u, a).code, "waitlisted")  # A 班滿 → 進等待名單
        self.assertEqual(register(self.u, b).code, "enrolled")  # B 班不受影響
        self.assertEqual(self.mine(), 1)
        # 選進 B 班後，同課的等待紀錄自動清掉
        self.assertFalse(Waitlist.objects.filter(user=self.u, section=a).exists())

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
        r = self.client.get(reverse("course_roster", args=[self.a.course_id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "王小明")
        self.assertContains(r, "s@example.com")

    def test_other_user_gets_404_on_roster(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("course_roster", args=[self.a.course_id])).status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        for name, args in [("teaching", []), ("course_roster", [self.a.course_id])]:
            r = self.client.get(reverse(name, args=args))
            self.assertEqual(r.status_code, 302)
            self.assertIn(reverse("google_login"), r["Location"])
        self.assertEqual(self.client.get(reverse("course_list")).status_code, 200)

    def test_roster_link_only_for_teacher(self):
        detail = reverse("course_detail", args=[self.a.course_id])
        roster = reverse("course_roster", args=[self.a.course_id])
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


class WindowTests(CourseTestCase):
    def set_window(self, open=None, close=None):
        self.term.enroll_open = open
        self.term.enroll_close = close
        self.term.save()

    def _open_later(self):
        self.set_window(open=timezone.now() + timedelta(hours=1))

    def _closed_earlier(self):
        self.set_window(close=timezone.now() - timedelta(hours=1))

    def test_not_open_blocks_register(self):
        a = self.section("A", "A", 1, 2)
        self._open_later()
        r = register(self.u, a)
        self.assertEqual(r.code, "not_open")
        self.assertIn("開放", r.message)
        self.assertEqual(self.mine(), 0)

    def test_gate_runs_before_other_checks(self):
        a = self.section("A", "A", 1, 2, capacity=1)
        Enrollment.objects.create(user=get_user_model().objects.create_user("v"), section=a)
        self._open_later()
        self.assertEqual(register(self.u, a).code, "not_open")  # 時間窗在額滿之前

    def test_closed_blocks_register(self):
        a = self.section("A", "A", 1, 2)
        self._closed_earlier()
        r = register(self.u, a)
        self.assertEqual(r.code, "closed")
        self.assertIn("截止", r.message)
        self.assertEqual(self.mine(), 0)

    def test_open_window_allows(self):
        a = self.section("A", "A", 1, 2)
        self.set_window(open=timezone.now() - timedelta(days=1),
                        close=timezone.now() + timedelta(days=1))
        self.assertEqual(register(self.u, a).code, "enrolled")

    def test_no_window_always_open(self):
        a = self.section("A", "A", 1, 2)
        self.assertEqual(register(self.u, a).code, "enrolled")

    def test_window_gate_reads_db_not_cached_term(self):
        # caller 手上的 section 可能快取著舊的 term；時間窗必須以 DB 新狀態為準
        a = self.section("A", "A", 1, 2)
        _ = a.course.term  # 先快取一份
        v = get_user_model().objects.create_user("v")
        Term.objects.filter(pk=self.term.pk).update(
            enroll_close=timezone.now() - timedelta(hours=1))
        self.assertEqual(register(v, a).code, "closed")

    def test_list_shows_not_open_and_disabled_button(self):
        self.client.force_login(self.u)
        self.section("A", "A", 1, 2)
        self._open_later()
        r = self.client.get(reverse("course_list"))
        self.assertContains(r, "開放")
        self.assertContains(r, "未開放")

    def test_list_shows_closed_and_drop_still_available(self):
        self.client.force_login(self.u)
        a = self.section("A", "A", 1, 2)
        register(self.u, a)
        self._closed_earlier()
        r = self.client.get(reverse("course_list"))
        self.assertContains(r, "已截止")
        self.assertContains(r, "退選")

    def test_post_enroll_blocked_when_not_open(self):
        self.client.force_login(self.u)
        a = self.section("A", "A", 1, 2)
        self._open_later()
        r = self.client.post(reverse("enroll", args=[a.pk]), follow=True)
        self.assertContains(r, "開放")
        self.assertEqual(self.mine(), 0)

    def test_drop_unaffected_by_closed_window(self):
        self.client.force_login(self.u)
        a = self.section("A", "A", 1, 2)
        register(self.u, a)
        self._closed_earlier()
        r = self.client.post(reverse("drop", args=[a.pk]), follow=True)
        self.assertContains(r, "已退選")
        self.assertEqual(self.mine(), 0)

    def test_schedule_unaffected_by_closed_window(self):
        self.client.force_login(self.u)
        a = self.section("A", "A", 1, 2)
        register(self.u, a)
        self._closed_earlier()
        self.assertEqual(self.client.get(reverse("my_schedule")).status_code, 200)

    def test_list_shows_enroll_button_when_open(self):
        self.client.force_login(self.u)
        self.section("A", "A", 1, 2)
        r = self.client.get(reverse("course_list"))
        self.assertContains(r, "加選</button>")
class WaitlistTests(CourseTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.section("A", "A", 1, 2, capacity=1)
        self.v = get_user_model().objects.create_user("v")
        Enrollment.objects.create(user=self.v, section=self.a)  # A 班額滿

    def test_waitlisted_with_position(self):
        r = register(self.u, self.a)
        self.assertEqual(r.code, "waitlisted")
        self.assertIn("第 1 位", r.message)

    def test_already_waitlisted_shows_position(self):
        register(self.u, self.a)
        r = register(self.u, self.a)
        self.assertEqual(r.code, "already_waitlisted")
        self.assertIn("第 1 位", r.message)

    def test_promotes_on_drop(self):
        register(self.u, self.a)
        drop_enrollment(self.v, self.a)
        self.assertTrue(Enrollment.objects.filter(user=self.u, section=self.a).exists())
        self.assertIsNotNone(Waitlist.objects.get(user=self.u, section=self.a).promoted_at)

    def test_no_skip_order(self):
        first = get_user_model().objects.create_user("w1")
        register(first, self.a)   # 第 1 位
        register(self.u, self.a)  # 第 2 位
        drop_enrollment(self.v, self.a)      # 只開一個位置
        self.assertTrue(Enrollment.objects.filter(user=first, section=self.a).exists())
        self.assertFalse(Enrollment.objects.filter(user=self.u, section=self.a).exists())
        self.assertEqual(Waitlist.objects.get(user=self.u, section=self.a).position, 1)

    def test_cancel_wait(self):
        register(self.u, self.a)
        self.assertTrue(cancel_waitlist(self.u, self.a))
        self.assertFalse(cancel_waitlist(self.u, self.a))
        self.assertFalse(Waitlist.objects.filter(user=self.u).exists())

    def test_list_shows_waiting_row_and_cancel_button(self):
        register(self.u, self.a)  # 額滿 → 等待第 1 位
        self.client.force_login(self.u)
        r = self.client.get(reverse("course_list"))
        self.assertContains(r, "等待中（第 1 位）")
        self.assertContains(r, "取消等待</button>")
        self.assertNotContains(r, "加選</button>")

    def test_cancel_wait_via_view(self):
        self.client.force_login(self.u)
        register(self.u, self.a)
        r = self.client.post(reverse("cancel_wait", args=[self.a.pk]), follow=True)
        self.assertContains(r, "已取消等待")
        self.assertFalse(Waitlist.objects.filter(user=self.u).exists())

    def test_enrolling_other_section_clears_waitlist(self):
        b = self.section("A", "B", 4, 5)
        register(self.u, self.a)  # 等 A 班
        self.assertEqual(register(self.u, b).code, "enrolled")
        self.assertFalse(Waitlist.objects.filter(user=self.u).exists())

    def test_cannot_wait_when_enrolled_same_course(self):
        b = self.section("A", "B", 4, 5)
        register(self.u, b)  # 已選 B 班
        r = register(self.u, self.a)  # A 班額滿
        self.assertEqual(r.code, "already")
        self.assertFalse(Waitlist.objects.filter(user=self.u).exists())

    def test_banner_shown_until_acked(self):
        self.client.force_login(self.u)
        register(self.u, self.a)
        drop_enrollment(self.v, self.a)
        # GET 不消耗通知：反覆開頁面 banner 都在
        self.assertContains(self.client.get(reverse("my_schedule")), "你已遞補進")
        self.assertContains(self.client.get(reverse("my_schedule")), "你已遞補進")
        # 明確 POST 之後才消失
        self.client.post(reverse("ack_promotion"), follow=True)
        self.assertNotContains(self.client.get(reverse("my_schedule")), "你已遞補進")

    def test_admin_page_does_not_consume_banner(self):
        self.client.force_login(self.u)
        register(self.u, self.a)
        drop_enrollment(self.v, self.a)
        self.client.get("/admin/")  # 任何不顯示 banner 的渲染都不能吃掉通知
        self.assertContains(self.client.get(reverse("my_schedule")), "你已遞補進")

    def test_cancel_wait_rejects_get_and_anonymous(self):
        self.client.force_login(self.u)
        register(self.u, self.a)
        self.assertEqual(self.client.get(reverse("cancel_wait", args=[self.a.pk])).status_code, 405)
        anon = Client()
        r = anon.post(reverse("cancel_wait", args=[self.a.pk]))
        self.assertIn("/accounts/google/login/", r.headers["Location"])
        self.assertTrue(Waitlist.objects.filter(user=self.u).exists())

    def test_requeue_after_promotion_and_drop(self):
        # 被遞補 → 退選 → 班別再額滿 → 重新排隊不能卡死
        register(self.u, self.a)
        drop_enrollment(self.v, self.a)  # u 被遞補
        self.assertTrue(Enrollment.objects.filter(user=self.u, section=self.a).exists())
        drop_enrollment(self.u, self.a)  # u 又退選
        w = get_user_model().objects.create_user("w")
        self.assertEqual(register(w, self.a).code, "enrolled")  # 再額滿
        r = register(self.u, self.a)
        self.assertEqual(r.code, "waitlisted")  # 不再是 already_waitlisted
        self.assertIn("第 1 位", r.message)
        self.assertTrue(cancel_waitlist(self.u, self.a))  # 取消也要動得了

    def test_position_message_after_promotion(self):
        # 發生過遞補後，新加入者的「第 N 位」不能把歷史列算進去
        w1 = get_user_model().objects.create_user("w1")
        register(w1, self.a)
        drop_enrollment(self.v, self.a)  # w1 被遞補，A 班又額滿
        w2 = get_user_model().objects.create_user("w2")
        r = register(w2, self.a)
        self.assertEqual(r.code, "waitlisted")
        self.assertIn("第 1 位", r.message)
        self.assertNotIn("第 2 位", r.message)

    def test_promotion_clears_other_same_course_wait(self):
        # 遞補進 A 班後，同課 B 班的等待紀錄要同步清掉
        b = self.section("A", "B", 4, 5, capacity=1)
        w = get_user_model().objects.create_user("w")
        Enrollment.objects.create(user=w, section=b)  # B 班額滿
        register(self.u, self.a)
        register(self.u, b)
        drop_enrollment(self.v, self.a)  # u 遞補進 A 班
        self.assertTrue(Enrollment.objects.filter(user=self.u, section=self.a).exists())
        self.assertFalse(Waitlist.objects.filter(
            user=self.u, section=b, promoted_at__isnull=True).exists())

    def test_promotion_skips_conflicting_waiter(self):
        # 排隊第一的人選了與本班衝堂的課 → 遞補時移出、順延下一位
        c = self.section("C", "A", 1, 2)  # 與 A 班同時段
        register(self.u, self.a)  # 第 1 位
        self.assertEqual(register(self.u, c).code, "enrolled")
        w2 = get_user_model().objects.create_user("w2")
        register(w2, self.a)  # 第 2 位
        drop_enrollment(self.v, self.a)  # 只開一個位置
        self.assertTrue(Enrollment.objects.filter(user=w2, section=self.a).exists())
        self.assertFalse(Enrollment.objects.filter(user=self.u, section=self.a).exists())
        # u 的等待列已被移出
        self.assertFalse(Waitlist.objects.filter(user=self.u, section=self.a).exists())
class PrereqTests(CourseTestCase):
    def past_section(self, code, label="A"):
        past = Term.objects.get_or_create(code="113-2", defaults={})[0]
        c, _ = Course.objects.get_or_create(term=past, code=code,
                                            defaults=dict(name=code, teacher=self.teacher))
        return Section.objects.update_or_create(course=c, label=label,
                                                defaults=dict(day=5, start_period=1, end_period=2))[0]

    def with_prereq(self, section, *prereq_codes):
        section.course.prerequisites.set([self.past_section(c).course for c in prereq_codes])

    def test_missing_prereq_blocks(self):
        a = self.section("CS301", "A", 3, 5)
        self.with_prereq(a, "CS201")
        r = register(self.u, a)
        self.assertEqual(r.code, "prereq")
        self.assertIn("CS201", r.message)
        self.assertEqual(self.mine(), 0)

    def test_completed_prereq_allows(self):
        a = self.section("CS301", "A", 3, 5)
        self.with_prereq(a, "CS201")
        Enrollment.objects.create(user=self.u, section=self.past_section("CS201"))
        self.assertEqual(register(self.u, a).code, "enrolled")

    def test_multiple_prereqs_missing_one(self):
        a = self.section("CS301", "A", 3, 5)
        self.with_prereq(a, "CS101", "CS201")
        Enrollment.objects.create(user=self.u, section=self.past_section("CS101"))
        r = register(self.u, a)
        self.assertEqual(r.code, "prereq")
        self.assertIn("CS201", r.message)
        self.assertNotIn("CS101", r.message)

    def test_current_term_enrollment_does_not_count(self):
        # 同一學期的加選不算「修過」，只有過去學期才算
        a = self.section("CS301", "A", 3, 5)
        self.with_prereq(a, "CS201")
        cur = self.section("CS201", "A", 1, 2)
        Enrollment.objects.create(user=self.u, section=cur)  # 本學期選了 CS201（但先修比的是 past course 的 code）
        # 本學期那筆的 course.term 是 is_current=True → 不算已修
        self.assertEqual(register(self.u, a).code, "prereq")

    def test_post_enroll_blocked_via_view(self):
        self.client.force_login(self.u)
        a = self.section("CS301", "A", 3, 5)
        self.with_prereq(a, "CS201")
        r = self.client.post(reverse("enroll", args=[a.pk]), follow=True)
        self.assertContains(r, "先修")
        self.assertEqual(self.mine(), 0)

    def test_guest_list_shows_prereqs_unmarked(self):
        a = self.section("CS301", "A", 3, 5)
        self.with_prereq(a, "CS201")
        r = self.client.get(reverse("course_list"))
        self.assertContains(r, "先修：CS201")
        self.assertNotContains(r, "未修")
        self.assertNotContains(r, "✓")

    def test_logged_in_list_marks_completed_and_missing(self):
        self.client.force_login(self.u)
        a = self.section("CS301", "A", 3, 5)
        self.with_prereq(a, "CS101", "CS201")
        Enrollment.objects.create(user=self.u, section=self.past_section("CS101"))
        r = self.client.get(reverse("course_list"))
        self.assertContains(r, "CS101✓")
        self.assertContains(r, "CS201")
        self.assertContains(r, "未修")

    def test_detail_shows_prereqs(self):
        self.client.force_login(self.u)
        a = self.section("CS301", "A", 3, 5)
        self.with_prereq(a, "CS201")
        r = self.client.get(reverse("course_detail", args=[a.course_id]))
        self.assertContains(r, "先修：CS201")
        self.assertContains(r, "未修")


class SlotFilterTests(CourseTestCase):
    def setUp(self):
        super().setUp()
        # 四個時段各一、day 分開
        self.am = self.section("AM1", "A", 2, 3)          # start 2，週一
        self.mid = self.section("MID1", "A", 5, 6)         # start 5，週一
        self.pm = self.section("PM1", "A", 8, 9, day=3)    # start 8，週三
        self.eve = self.section("EVE1", "A", 11, 12, day=3)  # start 11，週三

    def codes(self, **params):
        r = self.client.get(reverse("course_list"), params)
        return {s.course.code for s in r.context["sections"]}

    def test_am(self):
        self.assertEqual(self.codes(slot="am"), {"AM1"})

    def test_midday(self):
        self.assertEqual(self.codes(slot="midday"), {"MID1"})

    def test_pm(self):
        self.assertEqual(self.codes(slot="pm"), {"PM1"})

    def test_evening(self):
        self.assertEqual(self.codes(slot="evening"), {"EVE1"})

    def test_slot_combines_with_day(self):
        self.assertEqual(self.codes(day="3", slot="pm"), {"PM1"})
        self.assertEqual(self.codes(day="3", slot="evening"), {"EVE1"})
        self.assertEqual(self.codes(day="3", slot="am"), set())

    def test_form_remembers_selection(self):
        r = self.client.get(reverse("course_list"), {"slot": "pm"})
        self.assertContains(r, 'value="pm" selected')


class PrereqLimitTests(CourseTestCase):
    """先修課至多 2 門；走 admin 的新增與編輯頁面。"""

    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser("root", password="pw"))

    def course_data(self, code, *prereq_codes):
        return {"term": self.term.pk, "code": code, "name": "測試課", "teacher": self.teacher.pk,
                "credits": 3, "syllabus": "",
                "prerequisites": [self.course(c).pk for c in prereq_codes]}

    def test_add_course_with_two_prereqs_saves(self):
        r = self.client.post(reverse("admin:courses_course_add"), self.course_data("CS999", "CS101", "CS202"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Course.objects.get(term=self.term, code="CS999").prerequisites.count(), 2)

    def test_add_course_with_three_prereqs_is_rejected(self):
        r = self.client.post(reverse("admin:courses_course_add"),
                             self.course_data("CS999", "CS101", "CS202", "CS303"))
        self.assertContains(r, "先修課程最多設 2 門。")
        self.assertFalse(Course.objects.filter(term=self.term, code="CS999").exists())

    def test_edit_course_to_three_prereqs_is_rejected(self):
        target = self.course("CS999")
        target.prerequisites.set([self.course("CS101"), self.course("CS202")])
        r = self.client.post(reverse("admin:courses_course_change", args=[target.pk]),
                             self.course_data("CS999", "CS101", "CS202", "CS303"))
        self.assertContains(r, "先修課程最多設 2 門。")
        self.assertEqual(target.prerequisites.count(), 2)
