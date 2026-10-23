"""班別列的動作判定：一個班別對一個使用者只有一個動作。

判定順序沿用既有按鈕語意：已選（drop）＞等待中（cancel_wait）＞
開放中（enroll）＞未開放／已截止（blocked）。
"""


def apply_actions(standing, sections, window_state="open"):
    """為每個班別設定 s.action（cancel_wait 時另設 s.wait_position）。

    standing 是該使用者在本學期的 Standing；window_state 是
    Term.enrollment_state 的三態，無時間窗的學期傳 "open"。
    """
    enrolled = standing.section_ids
    for s in sections:
        if s.pk in enrolled:
            s.action = "drop"
        elif s.pk in standing.waiting:
            s.action = "cancel_wait"
            s.wait_position = standing.waiting[s.pk]
        elif window_state == "open":
            s.action = "enroll"
        elif window_state == "not_open":
            s.action = "blocked_not_open"
        else:
            s.action = "blocked_closed"
