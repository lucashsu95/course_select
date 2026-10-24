from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from ..models import Course, Enrollment, Term, Waitlist
from ..services import register
from ..standing import get_standing
from ..verdict import evaluate
from .base import CourseTestCase


class VerdictTests(CourseTestCase):
    """evaluate 判定表：(code, action, severity) 每支規則一條。"""

    def verdict(self, section, state="open"):
        return evaluate(get_standing(self.u, self.term), section, (state, None))

    def past_course(self, code):
        past = Term.objects.get_or_create(code="113-2")[0]
        c, _ = Course.objects.get_or_create(term=past, code=code,
                                            defaults=dict(name=code, teacher=self.teacher))
        return c

    def test_clean_is_enroll(self):
        v = self.verdict(self.section("A", "A", 1, 2))
        self.assertEqual((v.code, v.action, v.severity), ("enrolled", "enroll", "success"))

    def test_enrolled_same_section_is_drop(self):
        a = self.section("A", "A", 1, 2)
        register(self.u, a)
        v = self.verdict(a)
        self.assertEqual((v.code, v.action, v.severity), ("already", "drop", "info"))

    def test_enrolled_same_section_closed_still_drop(self):
        # 退選不受時間窗影響（docs §7）：code 照 register 回 closed，action 仍是 drop
        a = self.section("A", "A", 1, 2)
        register(self.u, a)
        v = self.verdict(a, state="closed")
        self.assertEqual((v.code, v.action, v.severity), ("closed", "drop", "warning"))

    def test_enrolled_same_section_not_open_still_drop(self):
        # 未開放同不受影響：按鈕仍是退選（closed 版見上）
        a = self.section("A", "A", 1, 2)
        register(self.u, a)
        v = self.verdict(a, state="not_open")
        self.assertEqual((v.code, v.action, v.severity), ("not_open", "drop", "warning"))

    def test_enrolled_same_course_other_section_closed_is_blocked_closed(self):
        # 已選同課另一班＋已截止：code 照 register 回 closed，action 置灰 blocked_closed
        a = self.section("A", "A", 1, 2)
        b = self.section("A", "B", 4, 5)
        register(self.u, b)
        v = self.verdict(a, state="closed")
        self.assertEqual((v.code, v.action, v.severity), ("closed", "blocked_closed", "warning"))

    def test_enrolled_same_course_other_section_is_blocked(self):
        a = self.section("A", "A", 1, 2)
        b = self.section("A", "B", 4, 5)
        register(self.u, b)
        v = self.verdict(a)
        self.assertEqual((v.code, v.action, v.severity), ("already", "blocked_same_course", "info"))
        self.assertIn("B 班", v.message)

    def test_waiting_on_full_is_cancel_wait(self):
        a = self.section("A", "A", 1, 2, capacity=1)
        Enrollment.objects.create(user=get_user_model().objects.create_user("v"), section=a)
        register(self.u, a)
        v = self.verdict(a)
        self.assertEqual((v.code, v.action, v.severity), ("already_waitlisted", "cancel_wait", "info"))
        self.assertEqual(v.position, 1)

    def test_waiting_closed_still_cancel_wait(self):
        # 取消等待同不受時間窗影響
        a = self.section("A", "A", 1, 2, capacity=1)
        Enrollment.objects.create(user=get_user_model().objects.create_user("v"), section=a)
        register(self.u, a)
        v = self.verdict(a, state="closed")
        self.assertEqual((v.code, v.action, v.severity), ("closed", "cancel_wait", "warning"))
        self.assertEqual(v.position, 1)

    def test_waiting_not_full_falls_through_to_enroll(self):
        # 等待列還在但班別已不額滿（admin 調高名額）：落回正常規則，
        # 按鈕是加選、POST 直接加選（docs §7 按鈕表：cancel_wait 要求該班額滿）
        a = self.section("A", "A", 1, 2)
        Waitlist.objects.create(user=self.u, section=a)
        v = self.verdict(a)
        self.assertEqual((v.code, v.action, v.severity), ("enrolled", "enroll", "success"))
        self.assertIsNone(v.position)

    def test_full_not_waiting_is_waitlist(self):
        a = self.section("A", "A", 1, 2, capacity=1)
        Enrollment.objects.create(user=get_user_model().objects.create_user("v"), section=a)
        v = self.verdict(a)
        self.assertEqual((v.code, v.action, v.severity), ("waitlisted", "waitlist", "info"))

    def test_not_open(self):
        v = self.verdict(self.section("A", "A", 1, 2), state="not_open")
        self.assertEqual((v.code, v.action, v.severity), ("not_open", "blocked_not_open", "warning"))

    def test_closed(self):
        v = self.verdict(self.section("A", "A", 1, 2), state="closed")
        self.assertEqual((v.code, v.action, v.severity), ("closed", "blocked_closed", "warning"))

    def test_window_runs_before_prereq(self):
        # business-rules §5：規則 0（時間窗）在一切檢查之前
        a = self.section("CS301", "A", 3, 5)
        a.course.prerequisites.set([self.past_course("CS201")])
        self.assertEqual(self.verdict(a, state="not_open").code, "not_open")

    def test_missing_prereq_is_error(self):
        a = self.section("CS301", "A", 3, 5)
        a.course.prerequisites.set([self.past_course("CS201")])
        v = self.verdict(a)
        self.assertEqual((v.code, v.action, v.severity), ("prereq", "blocked_prereq", "error"))
        self.assertIn("CS201", v.message)

    def test_conflict_is_error(self):
        a = self.section("A", "A", 1, 2)
        b = self.section("B", "A", 2, 3)  # 重疊一節
        register(self.u, a)
        v = self.verdict(b)
        self.assertEqual((v.code, v.action, v.severity), ("conflict", "blocked_conflict", "error"))

    @override_settings(MAX_CREDITS=3)
    def test_over_credits_is_error(self):
        a = self.section("A", "A", 1, 2)
        b = self.section("B", "A", 4, 5)
        register(self.u, a)
        v = self.verdict(b)
        self.assertEqual((v.code, v.action, v.severity), ("over_credits", "blocked_credits", "error"))


class ButtonPreviewTests(CourseTestCase):
    """班別列按鈕預示加選結果：按鈕顯示什麼，POST 就回什麼。"""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.u)

    def body(self):
        return self.client.get(reverse("course_list")).content.decode()

    def past_course(self, code):
        past = Term.objects.get_or_create(code="113-2")[0]
        c, _ = Course.objects.get_or_create(term=past, code=code,
                                            defaults=dict(name=code, teacher=self.teacher))
        return c

    def test_full_section_shows_waitlist_button(self):
        a = self.section("A", "A", 1, 2, capacity=1)
        Enrollment.objects.create(user=get_user_model().objects.create_user("v"), section=a)
        body = self.body()
        self.assertIn("加入等待</button>", body)
        self.assertNotIn("加選</button>", body)

    def test_waiting_shows_cancel_not_waitlist(self):
        a = self.section("A", "A", 1, 2, capacity=1)
        Enrollment.objects.create(user=get_user_model().objects.create_user("v"), section=a)
        register(self.u, a)
        body = self.body()
        self.assertIn("等待中（第 1 位）", body)
        self.assertIn("取消等待</button>", body)
        self.assertNotIn("加入等待</button>", body)

    def test_missing_prereq_shows_blocked(self):
        a = self.section("CS301", "A", 3, 5)
        a.course.prerequisites.set([self.past_course("CS201")])
        body = self.body()
        self.assertIn("缺先修", body)
        self.assertNotIn("加選</button>", body)

    def test_conflict_shows_blocked(self):
        a = self.section("A", "A", 1, 2)
        b = self.section("B", "A", 2, 3)
        register(self.u, a)
        body = self.body()
        self.assertIn("衝堂", body)  # B 班的列
        self.assertIn("退選</button>", body)  # A 班的列
        self.assertNotIn("加選</button>", body)

    @override_settings(MAX_CREDITS=3)
    def test_over_credits_shows_blocked(self):
        a = self.section("A", "A", 1, 2)
        b = self.section("B", "A", 4, 5)
        register(self.u, a)
        body = self.body()
        self.assertIn("超學分", body)
        self.assertNotIn("加選</button>", body)

    def test_same_course_other_section_shows_blocked(self):
        a = self.section("A", "A", 1, 2)
        b = self.section("A", "B", 4, 5)
        register(self.u, a)
        body = self.body()
        self.assertIn("已選此課", body)  # B 班的列
        self.assertIn("退選</button>", body)  # A 班的列
        self.assertNotIn("加選</button>", body)

    def test_closed_window_shows_closed_on_all_rows(self):
        self.section("A", "A", 1, 2)
        self.term.enroll_close = timezone.now() - timedelta(hours=1)
        self.term.save()
        body = self.body()
        self.assertIn("已截止", body)
        self.assertNotIn("加選</button>", body)

    def test_closed_window_keeps_drop_button(self):
        # 截止後已加選者仍看得到「退選」（docs §7）
        a = self.section("A", "A", 1, 2)
        register(self.u, a)
        self.term.enroll_close = timezone.now() - timedelta(hours=1)
        self.term.save()
        self.assertIn("退選</button>", self.body())

    def test_closed_window_keeps_cancel_wait_button(self):
        a = self.section("A", "A", 1, 2, capacity=1)
        Enrollment.objects.create(user=get_user_model().objects.create_user("v"), section=a)
        register(self.u, a)  # 額滿 → 等待第 1 位
        self.term.enroll_close = timezone.now() - timedelta(hours=1)
        self.term.save()
        body = self.body()
        self.assertIn("等待中（第 1 位）", body)
        self.assertIn("取消等待</button>", body)

    def test_not_open_window_shows_not_open_on_all_rows(self):
        self.section("A", "A", 1, 2)
        self.term.enroll_open = timezone.now() + timedelta(hours=1)
        self.term.save()
        body = self.body()
        self.assertIn("未開放", body)
        self.assertNotIn("加選</button>", body)
