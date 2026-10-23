# 領域名詞

> 行為細節與完整規則見 `docs/business-rules.md`；這裡只記名稱與一句話定義。
> 新名詞（含重構後的新 module 名）定案時加進來。

| 名詞 | 定義 |
| --- | --- |
| 學期 Term | 一組課程的容器（如 114-1）；全系統同一時刻一個「當前學期」 |
| 課程 Course | 學期內的一門課：課號、課名、老師、學分、大綱、先修課 |
| 班別 Section | 課程下的一個班：星期、節次、教室、名額；**加選的對象是班別，不是課程** |
| 加選紀錄 Enrollment | 某使用者選了某班別；(使用者, 班別) 最多一筆 |
| 等待名單 Waitlist | 額滿班別的排隊；依 `queued_at` FIFO，退選自動遞補 |
| 學期 standing（Standing） | 使用者在一個學期的狀態：已選班別、等待順位、總學分、已修課號（`courses/standing.py`） |
| 選課時間窗（window gate） | 學期加選開放的三態 not_open／open／closed；vocabulary 只由 `window_gate()` 產生（`courses/window.py`） |
| 資格判定（Verdict） | 一個使用者對一個班別的判定：code（POST 結果）＋action（按鈕）＋severity（訊息等級）＋position（等待順位）；加選規則與班別列按鈕的規則單一來源（`courses/verdict.py`） |
