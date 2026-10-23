"""使用者在一個學期的 standing：已選班別、等待順位、總學分、已修課號。

加選規則（services）與頁面顯示（views）共用的單一來源；
學期範圍在這裡明確，不再由各呼叫者各自決定。
"""
from dataclasses import dataclass

from .models import Enrollment, Section, Waitlist


def total_credits(sections):
    """總學分：同一門課只算一次（防禦 admin 手動造成同課兩班的狀態）。"""
    return sum({s.course_id: s.course.credits for s in sections}.values())


def completed_codes(user):
    """過去學期有過加選紀錄的課號（＝「已修」）；本學期加選不算。"""
    return frozenset(Enrollment.objects.filter(
        user=user, section__course__term__is_current=False)
        .values_list("section__course__code", flat=True))


@dataclass(frozen=True)
class Standing:
    sections: tuple  # 本學期已加的班別（Section）
    waiting: dict    # 還在排隊的班別：{section_id: 順位}
    credits: int     # 本學期總學分（按課去重）
    passed: frozenset  # 過去學期已修的課號

    @property
    def section_ids(self):
        return frozenset(s.pk for s in self.sections)


def get_standing(user, term):
    """使用者在 term 的 standing；未登入或沒有學期回空 standing。"""
    if not user.is_authenticated or term is None:
        return Standing((), {}, 0, frozenset())
    sections = tuple(Section.objects.filter(enrollments__user=user, course__term=term)
                     .select_related("course__teacher"))
    waiting = {w.section_id: w.position for w in
               Waitlist.objects.filter(user=user, promoted_at__isnull=True)}
    return Standing(sections, waiting, total_credits(sections), completed_codes(user))
