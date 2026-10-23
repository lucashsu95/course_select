"""使用者在一個學期的 standing：已選班別、等待順位、總學分、已修課號。

加選規則（services）與頁面顯示（views）共用的單一來源。
sections、waiting、credits 以傳入的 term 為範圍；passed 刻意跨學期
（「已修」的定義就是過去學期有同課號紀錄）。
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


def enrolled_sections(user, term):
    """該使用者在 term 已加的班別；未登入或沒有學期回空 tuple。"""
    if not user.is_authenticated or term is None:
        return ()
    return tuple(Section.objects.filter(enrollments__user=user, course__term=term)
                 .select_related("course__teacher"))


def _position(queued_at, section_times):
    """「第 N 位」的單一定義：1＋同班級中排隊時間更早（還沒遞補）的列數。

    section_times 是該班級所有還沒遞補列的 queued_at。
    排隊時間相同的列會拿到同一順位（只數「更早」，不數「相同」）。
    """
    return 1 + sum(1 for t in section_times if t < queued_at)


def _queued_times_by_section(section_ids):
    """{section_id: 該班級所有還沒遞補列的 queued_at}，固定 1 筆查詢。

    順位規則（_position）的單一查詢點：單列版與批量版共用同一個 filter 形狀。
    """
    times = {}
    for section_id, queued in Waitlist.objects.filter(promoted_at__isnull=True,
                                                      section_id__in=set(section_ids)) \
            .values_list("section_id", "queued_at"):
        times.setdefault(section_id, []).append(queued)
    return times


def waiting_position(wait):
    """單一等待列的目前順位（1 筆查詢）。"""
    times = _queued_times_by_section([wait.section_id])
    return _position(wait.queued_at, times[wait.section_id])


def waiting_positions(user, term):
    """該使用者在 term 還在排隊的班別：{section_id: 順位}（2 筆查詢，非每列一筆 COUNT）。"""
    if not user.is_authenticated or term is None:
        return {}
    rows = list(Waitlist.objects.filter(user=user, promoted_at__isnull=True,
                                        section__course__term=term)
                .values_list("section_id", "queued_at"))
    if not rows:
        return {}
    section_times = _queued_times_by_section({section_id for section_id, _ in rows})
    # rows 的每個 section_id 都進了上面的查詢，直接取；KeyError＝邏輯有錯，要顯性化
    return {section_id: _position(queued, section_times[section_id])
            for section_id, queued in rows}


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
    return Standing(sections=sections, waiting=waiting_positions(user, term),
                    credits=total_credits(sections), passed=completed_codes(user))
