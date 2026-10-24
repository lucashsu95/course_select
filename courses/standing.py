"""使用者在一個學期的 standing：已選班別、等待順位、總學分、已修課號。

加選規則（services）與頁面顯示（views）共用的單一來源。
sections、waiting、credits 以傳入的 term 為範圍；passed 刻意跨學期
（「已修」的定義就是過去學期有同課號紀錄）。
waiting 的順位由 waitlist 模組計算（waitlist.positions）。
"""
from dataclasses import dataclass

from .models import Enrollment, Section
from .waitlist import positions


def total_credits(sections):
    """總學分：同一門課只算一次（防禦 admin 手動造成同課兩班的狀態）。"""
    return sum({s.course_id: s.course.credits for s in sections}.values())


def completed_codes(user):
    """過去學期有過加選紀錄的課號（＝「已修」）；本學期加選不算。"""
    return frozenset(Enrollment.objects.filter(
        user=user, section__course__term__is_current=False)
        .values_list("section__course__code", flat=True))


def enrolled_sections(user, term):
    """該使用者在 term 已加的班別；未登入或沒有學期回空 tuple。"""
    if not user.is_authenticated or term is None:
        return ()
    return tuple(Section.objects.filter(enrollments__user=user, course__term=term)
                 .select_related("course__teacher"))


@dataclass(frozen=True)
class Standing:
    sections: tuple  # 本學期已加的班別（Section）
    waiting: dict    # 本學期還在排隊的班別：{section_id: 順位}
    credits: int     # 本學期總學分（按課去重）
    passed: frozenset  # 過去學期已修的課號（刻意跨學期）

    @property
    def section_ids(self):
        return frozenset(s.pk for s in self.sections)


def get_standing(user, term):
    """使用者在 term 的 standing；未登入或沒有學期回空 standing。"""
    if not user.is_authenticated or term is None:
        return Standing(sections=(), waiting={}, credits=0, passed=frozenset())
    sections = enrolled_sections(user, term)
    return Standing(sections=sections, waiting=positions(user, term),
                    credits=total_credits(sections), passed=completed_codes(user))
