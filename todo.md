# TODO

尚未處理的風險，依嚴重度排序。改完一項就刪一項。

## 併發

- [ ] **名額可能超收** — `courses/views.py` 的 `select_for_update()` 在 SQLite 無效，同時加選可超過 `capacity`。換 PostgreSQL 後才會真正生效。（程式碼已有 `shortcut:` 註記）

## 領域模型

- [ ] **沒有「學期」** — `Enrollment` 只綁 `user + course`，學分上限變成終身累計、同一門課不能重選、課表沒有學期視角。要加 `Term` 或 `semester` 欄位，唯一約束改成 `(user, course, term)`。**需要決定：這是不是單學期 demo** — 若是，本項可直接關閉。

## 結構

- [ ] **`enroll()` 仍是 shallow** — 衝堂／額滿／學分三條規則、交易、訊息、轉址都在 `courses/views.py` 一個 view 裡，只能靠 HTTP 測試。建議抽 `courses/services.py: register(user, course)` 回傳結果物件。
- [ ] **學分總和算兩次** — `enroll()` 與 `my_schedule()` 各算一次；抽 `services.py` 時一起收斂。
- [ ] **`Course` 的「同老師其他課程」context 沒人用** — `courses/views.py` 的 `related` 已查好但 `detail.html` 沒有對應區塊，目前是死 context（可能是未完成的編輯）。

## 效能

- [ ] **`is_full` 逐筆呼叫會 N+1** — `courses/models.py` 的 `enrolled_count` 在沒有 `annotate(enrolled=...)` 時會各發一次 `COUNT`。目前只有 `enroll()` 走這條，資料量小；列表頁若逐筆用就會爆。
- [ ] **後台 `EnrollmentAdmin` 沒有 `list_select_related`** — `courses/admin.py`，`list_display` 顯示 user 與 course 時逐筆查詢。

## 清理

- [ ] `courses/views.py` 匯入的 `Sum` 沒用到。
