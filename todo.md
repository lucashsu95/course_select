# TODO

尚未處理的風險，依嚴重度排序。改完一項就刪一項。

## 併發

- [ ] **名額可能超收** — `courses/services.py` 的 `select_for_update()` 在 SQLite 無效，同時加選可超過 `capacity`。換 PostgreSQL 後才會真正生效。（程式碼已有 `shortcut:` 註記）

## 已知缺口

- [ ] **只有一個學期是「當前」** — `Term.current()` 取 `is_current=True` 的第一筆，沒有資料庫約束擋住兩個學期同時標成當前。多學期並行前要補 partial unique constraint。

## 效能

- [ ] **`is_full` 逐筆呼叫會 N+1** — `courses/models.py` 的 `enrolled_count` 在沒有 `annotate(enrolled=...)` 時會各發一次 `COUNT`。目前只有 `register()` 走這條，資料量小；列表頁若逐筆用就會爆。
