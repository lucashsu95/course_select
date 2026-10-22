from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from .models import Enrollment, Section


@dataclass(frozen=True)
class Result:
    code: str  # enrolled / already / conflict / full / over_credits
    message: str

    @property
    def ok(self):
        return self.code == "enrolled"


def register(user, section):
    """加選一個班別。四條規則：同課不重複、不衝堂、有名額、不超學分。"""
    with transaction.atomic():
        # shortcut: sqlite 不支援列鎖，名額在高併發下可能超收；換 PostgreSQL 時 select_for_update 才會生效
        section = Section.objects.select_for_update().select_related("course").get(pk=section.pk)
        course = section.course
        # 目前這個學期已選的班別（每門課至多一個班別，由本函式的規則保證）
        mine = list(Section.objects.select_related("course")
                       .filter(enrollment__user=user, course__term=course.term))
        if (current := next((s for s in mine if s.course_id == course.pk), None)):
            return Result("already", f"你已經加選這門課（{current.label_display}）了。")
        if (clash := next((s for s in mine if s.conflicts_with(section)), None)):
            return Result("conflict",
                          f"衝堂：和「{clash.course.name} {clash.label_display}」時間重疊。")
        if section.is_full:
            return Result("full", f"{section.label_display}名額已滿。")
        total = sum(s.course.credits for s in mine) + course.credits
        if total > settings.MAX_CREDITS:
            return Result("over_credits", f"超過學分上限 {settings.MAX_CREDITS}。")
        Enrollment.objects.create(user=user, section=section)
        return Result("enrolled", f"已加選「{course.name} {section.label_display}」。")
