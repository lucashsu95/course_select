"""選課時間窗：一個學期的狀態與 gate（policy 的單一擁有者）。

加選 gate（services）、狀態列標籤（views）、班別列動作（rows）
都讀同一個結果；not_open / open / closed 三態只在這裡產生。
"""
from django.utils import timezone


def window_gate(term, now=None):
    """選課時間窗 gate：回 (state, message)。

    - ("not_open", 訊息)：尚未開放
    - ("closed", 訊息)：已截止
    - ("open", None)：開放中，或兩欄皆空（＝不限，永遠 open）
    """
    now = now or timezone.now()
    if term.enroll_open and now < term.enroll_open:
        return "not_open", f"選課 {term.enroll_open:%Y/%m/%d %H:%M} 開放。"
    if term.enroll_close and now > term.enroll_close:
        return "closed", f"選課已截止（{term.enroll_close:%Y/%m/%d %H:%M} 截止）。"
    return "open", None
