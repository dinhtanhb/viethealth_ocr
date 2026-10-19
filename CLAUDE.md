# CLAUDE.md

Hướng dẫn cho Claude khi làm việc trong repo **viethealth_ocr**.

> 📌 **Nguồn sự thật duy nhất cho các quy ước và cạm bẫy chi tiết là [`AGENTS.md`](./AGENTS.md).**
> Đọc toàn bộ `AGENTS.md` trước khi sửa code. File này chỉ tóm tắt những điều bắt buộc phải nhớ.
> Nếu cập nhật quy ước, **sửa `AGENTS.md`** — không nhân bản nội dung sang đây.

## Mục tiêu sản phẩm (bất biến)

AI tự đọc **> 90%** ngày viết tay trên PDF chấm công can thiệp → **tự điền** vào bảng rà soát → người dùng **xác nhận / sửa** → **lưu** → xuất Excel. Chạy **100% offline**, dữ liệu không rời máy người dùng.

## Lệnh hay dùng (Windows / PowerShell)

```powershell
# PowerShell không có '&&' -> dùng ';'
.\venv\Scripts\python.exe web_app.py runserver 127.0.0.1:8031 --noreload   # UI: http://127.0.0.1:8031/
.\venv\Scripts\python.exe -X utf8 bench_auto_read.py "<dir|file PDF>" [max]  # do ty le AI tu doc
.\venv\Scripts\python.exe -X utf8 -m py_compile web_app.py core_engine\local_db.py
```

* **Bắt buộc dùng `.\venv\Scripts\python.exe`** — Python hệ thống không có `django`.
* Thêm `-X utf8` khi có tiếng Việt.
* `--noreload`: **sửa code xong phải restart server**.

## 6 điều không được làm sai

1. **`is_verified = 1` nghĩa là con người đã xác nhận.** AI không bao giờ được tự set. Quét lại PDF **không được ghi đè** ngày người dùng đã duyệt (giữ theo `box_number`).
2. **Có HAI kiểu phiếu.** `process_pdf()` tự branch: `v_lines >= 6` → Kiểu A (lưới 30 ô), ngược lại → Kiểu B (phiếu rời, duyệt mọi trang). Đừng giả định chỉ có lưới 30 ô.
3. **Kiểu B phải giới hạn vùng đọc ở 35% chiều rộng bên trái**, nếu không chữ ký bị đọc nhầm thành ngày → sinh "buổi ảo".
4. **Mọi PDF thật đều là scan thuần, không text layer.** Đường dẫn tiếng Việt phải lấy qua `os.walk` (không gõ tay — lệch Unicode NFC/NFD).
5. **Message redirect phải dùng `urllib.parse.urlencode({...})`.** Ký tự `&` thô làm cắt cụt thông báo.
6. **Ngưỡng tin cậy:** `CONFIDENCE_HIGH=0.45`, `CONFIDENCE_MED=0.30`, `MIN_DATE_CONFIDENCE=0.15`. Không nâng `CONFIDENCE_HIGH` (chữ viết tay hiếm khi > 0.55). Ngày suy đoán phải bị hạ dưới `CONFIDENCE_MED` để buộc soát lại. Ngưỡng 🟢 còn bị lặp trong `HTML_TEMPLATE` của `web_app.py` — sửa đồng bộ cả hai.

## Kiến trúc nhanh

* `web_app.py` — Django **single-file app**: settings in-process, template HTML trong biến chuỗi `HTML_TEMPLATE`, routes ở `urlpatterns`. Endpoint: `/`, `/scan/`, `/save-all/`, `/export-excel/`, `/snippet/<filename>`.
* `core_engine/` — lõi **không import Django**: `path_parser.py` (metadata từ đường dẫn OneDrive), `pdf_grid_ocr.py` (hình học + OCR + chuẩn hóa ngày giờ), `local_db.py` (SQLite + migration an toàn), `excel_exporter.py`, `batch_scanner.py`.
* `core_engine` không có `__init__.py` (implicit namespace package).
* Comment/docstring viết **bằng tiếng Việt**.

## Runtime artifacts — không commit, dọn sau khi chạy

`.gitignore` đã loại: `models_storage/`, `media_snippets/`, `local_models/`, `exports/`, `*.sqlite3`, `.qoder/`, `_debug_*`, `_clean_box_*`, `_verify_*.png`.
`viethealth_ocr.sqlite3` đã untrack — app tự tạo lại bảng khi khởi động. Migration phải an toàn với DB đã có dữ liệu (kiểm tra `PRAGMA table_info` trước khi `ALTER TABLE`).

## Tiêu chí "xong"

Không báo hoàn thành nếu thiếu bằng chứng thật:

* OCR thay đổi → chạy `bench_auto_read.py` trên **dữ liệu thật**, báo số cụ thể (tử số/mẫu số, %).
* UI/luồng thay đổi → gọi HTTP thật vào `/scan/` + `/save-all/` và **verify lại bằng SQL**, hoặc render trình duyệt kèm ảnh chụp.
* `py_compile` sạch lỗi.
* **Không rút gọn yêu cầu** để vượt mốc 90% dễ hơn — đó là yêu cầu cứng của đề bài.

## Công cụ sửa file (lưu ý thực tế)

* Replace trên dòng chứa `{% ... %}` / `{{ ... }}` trong `web_app.py` có thể thất bại dù chuỗi khớp hệt → neo vào chuỗi con ASCII ngắn hoặc viết lại file.
* Bộ đếm "+n/−n line" của tool edit không đáng tin → **Read lại để xác nhận**.
