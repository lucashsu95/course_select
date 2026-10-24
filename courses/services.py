"""加退選的 commit 路徑。資格規則（為什麼能／不能加選）全在 verdict.evaluate。"""
from dataclasses import replace

from django.db import transaction
from django.utils import timezone

from .models import Enrollment, Section, Waitlist
from .standing import enrolled_sections, get_standing, waiting_position
from .verdict import conflicting_section, evaluate, same_course_section
from .window import window_gate


def register(user, section):
    """加選一個班別：在 transaction 內用新查出的 DB 狀態 evaluate，再 commit。

    額滿不再直接拒絕：改為加入該班等待名單（等有人退選自動遞補）。
    成功加選時，該課其他班的等待紀錄自動清掉。
    傳回的 Verdict 與班別列按鈕是同一個判定（verdict.evaluate）。

    standing 含等待順位掃描（多 1–2 筆查詢），舊版刻意省掉；
    現在按鈕與 POST 共用 evaluate，「已排隊第 N 位」的按鈕狀態
    需要它，接受這個成本換兩端語意一致。
    """
    with transaction.atomic():
        # shortcut: sqlite 不支援列鎖，名額在高併發下可能超收；換 PostgreSQL 時 select_for_update 才會生效
        # course__term 一起帶進來，時間窗與 standing 判斷永遠用新查出的 DB 狀態
        section = Section.objects.select_for_update().select_related("course__term").get(pk=section.pk)
        term = section.course.term
        standing = get_standing(user, term)
        verdict = evaluate(standing, section, window_gate(term))
        if verdict.code == "enrolled":
            Enrollment.objects.create(user=user, section=section)
            # 選進了這門課，該課其他班的等待紀錄自動清掉
            Waitlist.objects.filter(user=user, section__course=section.course).delete()
            return verdict
        if verdict.code == "waitlisted":
            # 「遞補過後來又退選」的歷史列不佔順位、也擋不到新排隊，先清掉再建
            Waitlist.objects.filter(user=user, section=section,
                                    promoted_at__isnull=False).delete()
            wait = Waitlist.objects.create(user=user, section=section)
            return replace(verdict,
                           message=f"{section.label_display}已額滿，已加入等待名單"
                                   f"（第 {waiting_position(wait)} 位），有人退選將自動遞補。")
        return verdict


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
        # 只取需要的 sections（同課與衝堂檢查），不在持鎖的迴圈裡掃描等待順位與已修課號
        sections = enrolled_sections(wait.user, course.term)
        if same_course_section(sections, course) is not None:
            # 排隊後又選了同課另一班：不再符合等待條件，移出名單後看下一位
            wait.delete()
            continue
        if conflicting_section(sections, wait.section) is not None:
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
