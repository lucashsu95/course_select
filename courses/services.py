from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Enrollment, Section, Waitlist


@dataclass(frozen=True)
class Result:
    code: str  # enrolled / already / conflict / waitlisted / already_waitlisted / over_credits / not_open / closed
    message: str

    @property
    def ok(self):
        return self.code == "enrolled"


def register(user, section):
    """加選一個班別。先過選課時間窗，再查規則：同課不重複、不衝堂、額滿轉等待、不超學分。

    額滿不再直接拒絕：改為加入該班等待名單（等有人退選自動遞補）。
    成功加選時，該課其他班的等待紀錄自動清掉。
    """
    with transaction.atomic():
        # shortcut: sqlite 不支援列鎖，名額在高併發下可能超收；換 PostgreSQL 時 select_for_update 才會生效
        # course__term 一起帶進來，時間窗判斷永遠用新查出的 DB 狀態
        section = Section.objects.select_for_update().select_related("course__term").get(pk=section.pk)
        course = section.course
        term = course.term
        now = timezone.now()
        if term.enroll_open and now < term.enroll_open:
            return Result("not_open", f"選課 {term.enroll_open:%Y/%m/%d %H:%M} 開放。")
        if term.enroll_close and now > term.enroll_close:
            return Result("closed", f"選課已截止（{term.enroll_close:%Y/%m/%d %H:%M} 截止）。")
        # 目前這個學期已選的班別（每門課至多一個班別，由本函式的規則保證）
        mine = list(Section.objects.select_related("course")
                       .filter(enrollments__user=user, course__term=course.term))
        if (current := next((s for s in mine if s.course_id == course.pk), None)):
            return Result("already", f"你已經加選這門課（{current.label_display}）了。")
        if (clash := next((s for s in mine if s.conflicts_with(section)), None)):
            return Result("conflict",
                          f"衝堂：和「{clash.course.name} {clash.label_display}」時間重疊。")
        if section.is_full:
            wait = Waitlist.objects.filter(user=user, section=section).first()
            if wait:
                return Result("already_waitlisted",
                              f"{section.label_display}已額滿，你已在等待名單（第 {wait.position} 位）。")
            Waitlist.objects.create(user=user, section=section)
            return Result("waitlisted",
                          f"{section.label_display}已額滿，已加入等待名單（第 {section.waitlists.count()} 位），有人退選將自動遞補。")
        # 同一門課至多一個班別是 service 層規則；DB 允許 admin 手動造成同課兩班，故按課號去重算學分
        total = sum({s.course_id: s.course.credits for s in mine}.values()) + course.credits
        if total > settings.MAX_CREDITS:
            return Result("over_credits", f"超過學分上限 {settings.MAX_CREDITS}。")
        Enrollment.objects.create(user=user, section=section)
        # 選進了這門課，該課其他班的等待紀錄自動清掉
        Waitlist.objects.filter(user=user, section__course=course).delete()
        return Result("enrolled", f"已加選「{course.name} {section.label_display}」。")


def drop_enrollment(user, section):
    """退選一個班別；釋出的名額立即遞補等待名單第一位（同 transaction）。"""
    with transaction.atomic():
        deleted, _ = Enrollment.objects.filter(user=user, section=section).delete()
        if not deleted:
            return False
        _promote_next(section)
        return True


def _promote_next(section):
    """該班等待名單第一位轉為正式加選；若其已選同課另一班則移出並順延下一位。"""
    now = timezone.now()
    wait = (Waitlist.objects.filter(section=section, promoted_at__isnull=True)
            .select_related("user", "section__course").select_for_update().first())
    while wait:
        course = wait.section.course
        if Enrollment.objects.filter(user=wait.user, section__course=course).exists():
            # 排隊後又選了同課另一班：不再符合等待條件，移出名單後看下一位
            wait.delete()
            wait = (Waitlist.objects.filter(section=section, promoted_at__isnull=True)
                    .select_related("user", "section__course").select_for_update().first())
            continue
        Enrollment.objects.create(user=wait.user, section=section)
        wait.promoted_at = now
        wait.save(update_fields=["promoted_at"])
        return


def cancel_waitlist(user, section):
    """取消等待；回 True 表示真的有紀錄被取消。"""
    deleted, _ = Waitlist.objects.filter(user=user, section=section, promoted_at__isnull=True).delete()
    return deleted > 0
