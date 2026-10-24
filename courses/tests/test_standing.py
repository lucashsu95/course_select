from django.contrib.auth import get_user_model
from django.test import TestCase

from ..models import Course, Section, Teacher, Term, Waitlist
from ..standing import get_standing


class StandingScopeTests(TestCase):
    """standing 各欄的範圍：waiting 只取傳入的學期（「已修」的跨學期定義由 test_register 的 PrereqTests 覆蓋）。"""

    def setUp(self):
        self.term = Term.objects.create(code="114-1", is_current=True)
        self.past = Term.objects.create(code="113-2", is_current=False)
        self.teacher = Teacher.objects.create(name="T")
        self.u = get_user_model().objects.create_user("u")

    def section(self, code, label, start, end, term=None):
        return Section.objects.create(
            course=Course.objects.create(term=term or self.term, code=code, name=code,
                                         teacher=self.teacher),
            label=label, day=1, start_period=start, end_period=end, capacity=10)

    def test_waiting_from_other_term_not_in_standing(self):
        old = self.section("HIST100", "A", 1, 2, term=self.past)
        new = self.section("HIST101", "A", 3, 4)
        Waitlist.objects.create(user=self.u, section=old)
        Waitlist.objects.create(user=self.u, section=new)
        standing = get_standing(self.u, self.term)
        # position 依 queued_at 算（定義在 waitlist.position_of），這裡只斷言範圍（哪些班別出現在 standing）
        self.assertEqual(set(standing.waiting), {new.pk})
