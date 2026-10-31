"""學期學分規則與官方班級課程學分摘要。"""
from dataclasses import dataclass

from .models import OfficialCourseCredit


@dataclass(frozen=True)
class CreditLimits:
    minimum: int
    maximum: int


@dataclass(frozen=True)
class CreditSummary:
    official_confirmed: int
    enrolled: int
    total: int
    complete: bool
    pending_course_codes: tuple[str, ...]
    limits: CreditLimits | None


def credit_limits(class_group):
    """依學制與年級解析學分上下限；未配置的學制不套用預設規則。"""
    if class_group is None or class_group.grade_no is None:
        return None
    program_type = class_group.department.program_type
    if program_type.code != "4":
        return None
    return CreditLimits(minimum=9 if class_group.grade_no == 4 else 16,
                        maximum=25)


def summarize_credits(class_group, term, sections=(), official_entries=()):
    """計算官方核對課程與本站加選的聯集學分，不使用節數推算。"""
    official_codes = {
        (entry.course_code or "").strip()
        for entry in official_entries
        if entry.entry_type == "course" and (entry.course_code or "").strip()
    }
    confirmations = {
        row.course_code: row.credits
        for row in OfficialCourseCredit.objects.filter(
            class_group=class_group, term=term,
            course_code__in=official_codes)
    } if class_group is not None and term is not None else {}
    pending = tuple(sorted(official_codes - set(confirmations)))
    official_confirmed = sum(confirmations.values())
    enrolled_by_code = {}
    for section in sections:
        enrolled_by_code.setdefault(section.course.code, section.course.credits)
    enrolled = sum(enrolled_by_code.values())
    enrolled_not_official = sum(
        credits for code, credits in enrolled_by_code.items()
        if code not in official_codes)
    return CreditSummary(
        official_confirmed=official_confirmed,
        enrolled=enrolled,
        total=official_confirmed + enrolled_not_official,
        complete=not pending,
        pending_course_codes=pending,
        limits=credit_limits(class_group),
    )
