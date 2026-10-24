from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import Course, Enrollment, Section, Teacher, Term
from ..services import register
from ..standing import get_standing
from ..verdict import evaluate
from ..window import window_gate
from .base import CourseTestCase


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


class WindowGateTests(TestCase):
    """時間窗 gate 模組：三態 vocabulary 只有一個產生點，未知狀態必須大聲失敗。"""

    def setUp(self):
        self.term = Term.objects.create(code="114-1", is_current=True)
        self.teacher = Teacher.objects.create(name="T")
        self.u = get_user_model().objects.create_user("u")
        self.s = Section.objects.create(
            course=Course.objects.create(term=self.term, code="A", name="A", teacher=self.teacher),
            label="A", day=1, start_period=1, end_period=2, capacity=10)

    def test_window_gate_states_and_messages(self):
        now = timezone.now()
        # 無時間窗（兩欄皆空）＝永遠 open
        self.assertEqual(window_gate(self.term), ("open", None))
        self.term.enroll_open = now + timedelta(hours=1)
        self.term.save()
        state, msg = window_gate(self.term)
        self.assertEqual(state, "not_open")
        self.assertIn("開放", msg)
        self.term.enroll_open = now - timedelta(hours=2)
        self.term.enroll_close = now - timedelta(hours=1)
        self.term.save()
        state, msg = window_gate(self.term)
        self.assertEqual(state, "closed")
        self.assertIn("截止", msg)

    def test_evaluate_unknown_window_state_raises(self):
        # 三態 vocabulary 只由 window_gate 產生；未知狀態代表上游出錯，
        # 不能隱式當成某一種 policy（舊 code 的 else 會一律畫成「已截止」）
        with self.assertRaises(ValueError):
            evaluate(get_standing(self.u, self.term), self.s, ("bogus", None))
