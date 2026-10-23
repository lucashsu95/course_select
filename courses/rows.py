"""班別列的動作判定：一個班別對一個使用者只有一個動作。

判定順序沿用既有按鈕語意：已選（drop）＞等待中（cancel_wait）＞
開放中（enroll）＞未開放／已截止（blocked）。
"""
from .models import Enrollment, Waitlist


def apply_actions(user, sections, window_state="open"):
    """為每個班別設定 s.action（cancel_wait 時另設 s.wait_position）。

    window_state 是 Term.enrollment_state 的三態；無時間窗的學期傳 "open"。
    """
    if user.is_authenticated:
        enrolled = set(Enrollment.objects.filter(user=user).values_list("section_id", flat=True))
        waiting = {w.section_id: w.position for w in
                   Waitlist.objects.filter(user=user, promoted_at__isnull=True)}
    else:
        enrolled, waiting = set(), {}
    for s in sections:
        if s.pk in enrolled:
            s.action = "drop"
        elif s.pk in waiting:
            s.action = "cancel_wait"
            s.wait_position = waiting[s.pk]
        elif window_state == "open":
            s.action = "enroll"
        elif window_state == "not_open":
            s.action = "blocked_not_open"
        else:
            s.action = "blocked_closed"
