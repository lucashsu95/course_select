"""加選資格判定：「一個使用者對一個班別能做什麼」的規則單一來源。

register()（POST 加選的判定與 commit）與班別列按鈕（列表／詳情顯示）
都跨同一條 seam 讀 evaluate()，按鈕顯示什麼，POST 就回什麼。
規則順序與 docs/business-rules.md §5 一致：
選課時間窗 → 同課不重複 → 先修已修 → 不衝堂 → 額滿轉等待 → 不超學分。
新規則只加這裡一個分支。
"""
from dataclasses import dataclass

from django.conf import settings

from .standing import total_credits


def missing_prereqs(course, passed):
    """使用者還沒修的先修課。「已修」＝課號在 passed（過去學期有同課號加選紀錄）。"""
    return [c for c in course.prerequisites.all() if c.code not in passed]


def same_course_section(sections, course):
    """sections 中同課程的已選班別；沒有回 None。（加選／遞補共用的資格規則）"""
    return next((s for s in sections if s.course_id == course.pk), None)


def conflicting_section(sections, section):
    """sections 中與 section 衝堂的已選班別；沒有回 None。（加選／遞補共用的資格規則）"""
    return next((s for s in sections if s.conflicts_with(section)), None)


@dataclass(frozen=True)
class Verdict:
    """一個使用者對一個班別的資格判定。

    code：現在 POST 加選會得到 register() 回傳的結果
        （enrolled / already / prereq / conflict / waitlisted /
          already_waitlisted / over_credits / not_open / closed）
    action：班別列按鈕要顯示的動作
        （drop / cancel_wait / enroll / waitlist / blocked_*）
    severity：register 回傳時 django messages 的等級
        （success / info / warning / error）
    position：等待名單順位（action=cancel_wait 時）
    """
    code: str
    message: str
    action: str
    severity: str
    position: int | None = None


def evaluate(standing, section, window):
    """使用者加選一個班別的資格判定（純函數，不查 DB）。

    standing 是該使用者在本學期的 Standing（standing.get_standing）；
    window 是 window_gate 的傳回值 (state, message)。
    三態之外的 window state 丟 ValueError（vocabulary 只由 window_gate 產生）。

    注意：waitlisted 的 message 是預佔的；register commit 出等待列後
    才補上真實的「第 N 位」。
    """
    state, window_message = window
    if state not in ("not_open", "open", "closed"):
        raise ValueError(f"未知的選課時間窗狀態：{state!r}")
    course = section.course
    sections = standing.sections

    if state == "not_open":
        return Verdict("not_open", window_message, "blocked_not_open", "warning")
    if state == "closed":
        return Verdict("closed", window_message, "blocked_closed", "warning")
    if (current := same_course_section(sections, course)):
        # 已選的就是這個班別 → 動作是退選（退選不受時間窗影響）；
        # 選了同課另一班 → 置灰，要換班先退
        action = "drop" if current.pk == section.pk else "blocked_same_course"
        return Verdict("already", f"你已經加選這門課（{current.label_display}）了。", action, "info")
    if missing := missing_prereqs(course, standing.passed):
        names = "、".join(f"{c.code} {c.name}" for c in missing)
        return Verdict("prereq", f"還缺先修課：{names}。", "blocked_prereq", "error")
    if (clash := conflicting_section(sections, section)):
        return Verdict("conflict",
                       f"衝堂：和「{clash.course.name} {clash.label_display}」時間重疊。",
                       "blocked_conflict", "error")
    if section.is_full:
        if section.pk in standing.waiting:
            position = standing.waiting[section.pk]
            return Verdict("already_waitlisted",
                           f"{section.label_display}已額滿，你已在等待名單（第 {position} 位）。",
                           "cancel_wait", "info", position=position)
        return Verdict("waitlisted", f"{section.label_display}已額滿。", "waitlist", "info")
    if total_credits(sections) + course.credits > settings.MAX_CREDITS:
        return Verdict("over_credits", f"超過學分上限 {settings.MAX_CREDITS}。", "blocked_credits", "error")
    return Verdict("enrolled", f"已加選「{course.name} {section.label_display}」。", "enroll", "success")
