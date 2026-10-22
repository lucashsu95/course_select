from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from .models import Course, Enrollment


@dataclass(frozen=True)
class Result:
    code: str  # enrolled / already / conflict / full / over_credits
    message: str

    @property
    def ok(self):
        return self.code == "enrolled"


def register(user, course):
    """加選一門課。四條規則：不重複、不衝堂、有名額、不超學分。"""
    with transaction.atomic():
        # shortcut: sqlite 不支援列鎖，名額在高併發下可能超收；換 PostgreSQL 時 select_for_update 才會生效
        course = Course.objects.select_for_update().get(pk=course.pk)
        mine = list(Course.objects.filter(enrollment__user=user, term=course.term))
        if course in mine:
            return Result("already", "你已經加選過這門課了。")
        if (clash := next((c for c in mine if c.conflicts_with(course)), None)):
            return Result("conflict", f"衝堂：和「{clash.name}」時間重疊。")
        if course.is_full:
            return Result("full", "名額已滿。")
        total = sum(c.credits for c in mine) + course.credits
        if total > settings.MAX_CREDITS:
            return Result("over_credits", f"超過學分上限 {settings.MAX_CREDITS}。")
        Enrollment.objects.create(user=user, course=course)
        return Result("enrolled", f"已加選「{course.name}」。")
