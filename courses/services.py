from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Enrollment, Section, Waitlist
from .standing import get_standing


def missing_prereqs(course, passed):
    """使用者還沒修的先修課。「已修」＝課號在 passed（過去學期有同課號加選紀錄）。"""
    return [c for c in course.prerequisites.all() if c.code not in passed]


@dataclass(frozen=True)
class Result:
    code: str  # enrolled / already / prereq / conflict / waitlisted / already_waitlisted / over_credits / not_open / closed
    message: str

    @property
    def ok(self):
        return self.code == "enrolled"


def register(user, section):
    """加選一個班別。先過選課時間窗，再查規則：同課不重複、先修已修、不衝堂、額滿轉等待、不超學分。

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
        # 該使用者在本學期的 standing（同課、衝堂、學分都從這裡讀）
        standing = get_standing(user, term)
        if (current := next((s for s in standing.sections if s.course_id == course.pk), None)):
            return Result("already", f"你已經加選這門課（{current.label_display}）了。")
        if missing := missing_prereqs(course, standing.passed):
            names = "、".join(f"{c.code} {c.name}" for c in missing)
            return Result("prereq", f"還缺先修課：{names}。")
        if (clash := next((s for s in standing.sections if s.conflicts_with(section)), None)):
            return Result("conflict",
                          f"衝堂：和「{clash.course.name} {clash.label_display}」時間重疊。")
        if section.is_full:
            wait = Waitlist.objects.filter(user=user, section=section,
                                           promoted_at__isnull=True).first()
            if wait:
                return Result("already_waitlisted",
                              f"{section.label_display}已額滿，你已在等待名單（第 {wait.position} 位）。")
            # 「遞補過後來又退選」的歷史列不佔順位、也擋不到新排隊，先清掉再建
            Waitlist.objects.filter(user=user, section=section,
                                    promoted_at__isnull=False).delete()
            wait = Waitlist.objects.create(user=user, section=section)
            return Result("waitlisted",
                          f"{section.label_display}已額滿，已加入等待名單（第 {wait.position} 位），有人退選將自動遞補。")
        # 同一門課至多一個班別是 service 層規則；DB 允許 admin 手動造成同課兩班，故按課去重算學分
        if standing.credits + course.credits > settings.MAX_CREDITS:
            return Result("over_credits", f"超過學分上限 {settings.MAX_CREDITS}。")
        Enrollment.objects.create(user=user, section=section)
        # 選進了這門課，該課其他班的等待紀錄自動清掉
        Waitlist.objects.filter(user=user, section__course=course).delete()
        return Result("enrolled", f"已加選「{course.name} {section.label_display}」。")


def drop_enrollment(user, section):
    """退選一個班別；釋出的名額立即遞補等待名單第一位（同 transaction）。

    先鎖 Section（與 register() 同一把鎖、同樣先 Section 的順序），
    避免退選＋遞補與並發加選互相穿插造成超收（換 PostgreSQL 後生效）。
    """
    with transaction.atomic():
        Section.objects.select_for_update().get(pk=section.pk)
        deleted, _ = Enrollment.objects.filter(user=user, section=section).delete()
        if not deleted:
            return False
        _promote_next(section)
        return True


def _next_waiter(section, exclude=()):
    # 只鎖 waitlist 列本身（of=("self",)），不連帶鎖 User/Course，
    # 避免與 register() 的鎖順序不同造成 deadlock
    return (Waitlist.objects.filter(section=section, promoted_at__isnull=True)
            .exclude(pk__in=exclude)
            .select_for_update(of=("self",)).first())


def _promote_next(section):
    """該班等待名單第一位轉為正式加選（FIFO，不越序）。

    若該位「已選同課另一班」或「與已選班別衝堂」，該列移出名單、順延下一位。
    遞補不重查學分上限（見 docs 已知限制）。
    """
    now = timezone.now()
    seen = []
    while True:
        wait = _next_waiter(section, exclude=seen)
        if wait is None:
            return
        seen.append(wait.pk)
        course = wait.section.course
        standing = get_standing(wait.user, course.term)
        if any(s.course_id == course.pk for s in standing.sections):
            # 排隊後又選了同課另一班：不再符合等待條件，移出名單後看下一位
            wait.delete()
            continue
        if any(s.conflicts_with(wait.section) for s in standing.sections):
            # 與已選班別衝堂：同樣移出、順延（維持「不衝堂」不變式）
            wait.delete()
            continue
        if section.is_full:  # 建立前重查容量（正常退選後必有空位，純防禦）
            return
        Enrollment.objects.create(user=wait.user, section=section)
        wait.promoted_at = now
        wait.save(update_fields=["promoted_at"])
        # 人已遞補進這門課，該課其他班的等待紀錄同步清掉
        Waitlist.objects.filter(user=wait.user, section__course=course).exclude(pk=wait.pk).delete()
        return


def cancel_waitlist(user, section):
    """取消等待；回 True 表示真的有紀錄被取消。"""
    deleted, _ = Waitlist.objects.filter(user=user, section=section, promoted_at__isnull=True).delete()
    return deleted > 0
