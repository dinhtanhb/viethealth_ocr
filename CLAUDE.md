# CLAUDE.md

Hướng dẫn cho Claude khi làm việc trong repo **viethealth_ocr**.

> 📌 **Nguồn sự thật duy nhất cho các quy ước và cạm bẫy chi tiết là [`AGENTS.md`](./AGENTS.md).**
> Đọc toàn bộ `AGENTS.md` trước khi sửa code. File này chỉ tóm tắt những điều bắt buộc phải nhớ.
> Nếu cập nhật quy ước, **sửa `AGENTS.md`** — không nhân bản nội dung sang đây.

## Mục tiêu sản phẩm (bất biến)

AI tự đọc **> 90%** ngày ghi trên PDF chấm công can thiệp (viết tay **hoặc** in đen) → **tự điền** vào bảng rà soát → người dùng **xác nhận / sửa** → **lưu** → xuất Excel. Chạy **100% offline**, dữ liệu không rời máy người dùng.

* Trạng thái đo gần nhất (20/10/2026, 3 ground truth / 32 ngày do người đọc): **EXACT 31/32 = 96.9%**, TOP-N 32/32 = 100%, GIẢ 0, NGUY HIỂM 0. Chỉ là **3 file** — chưa phải kết luận trên toàn bộ hồ sơ. Xem bảng phân bổ "tăng nhờ code / nhờ đính chính ground truth" trong `AGENTS.md` mục 6.

## Lệnh hay dùng (Windows / PowerShell)

```powershell
# PowerShell không có '&&' -> dùng ';'
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8031 --noreload   # UI: http://127.0.0.1:8031/
.\venv\Scripts\python.exe -X utf8 bench_accuracy.py              # do CHINH XAC: EXACT vs TOP-N (ground truth)
.\venv\Scripts\python.exe -X utf8 -m py_compile manage.py core_engine\local_db.py
```

* **Bắt buộc dùng `.\venv\Scripts\python.exe`** — Python hệ thống không có `django`.
* Thêm `-X utf8` khi có tiếng Việt.
* `--noreload`: **sửa code xong phải restart server**.

## 6 điều không được làm sai

1. **`is_verified = 1` nghĩa là con người đã xác nhận.** AI không bao giờ được tự set. Quét lại PDF **không được ghi đè** ngày người dùng đã duyệt (giữ theo `box_number`).
2. **Có HAI bố cục phiếu, và Kiểu B có HAI dạng bút tích.** `process_pdf()` tự branch: `v_lines >= 6` → Kiểu A (lưới 30 ô), ngược lại → Kiểu B (phiếu rời, duyệt mọi trang). Trong Kiểu B: ngày **viết tay mực xanh** (`CBP0005`) đọc bằng ensemble hai lớp trên cùng clip (`_read_session_clip`), ngày **in đen đánh máy** (`CBP0007`) đọc bằng đường riêng (`_session_band_fallback`, chỉ nhận detection nguyên vẹn `dd/mm/yyyy`). Đừng giả định chỉ có lưới 30 ô, cũng đừng giả định Kiểu B toàn là chữ viết tay.
3. **Kiểu B: giới hạn vùng đọc đến đường kẻ dọc đầu tiên của bảng** (5–35% bề rộng khung), cắt dải theo **giao số** chứ không lọc theo tâm, và **bỏ trang nào không có kẻ dọc** trong khoảng đó (trang văn bản in). Thiếu ba bước này thì chữ ký/cột ghi chú bị đọc thành ngày → "buổi ảo".
4. **Mọi PDF thật đều là scan thuần, không text layer.** Đường dẫn tiếng Việt phải lấy qua `os.walk` (không gõ tay — lệch Unicode NFC/NFD).
5. **Message redirect phải dùng `urllib.parse.urlencode({...})`.** Ký tự `&` thô làm cắt cụt thông báo.
6. **Ngưỡng tin cậy:** `CONFIDENCE_HIGH=0.60`, `CONFIDENCE_MED=0.40` (thang diem THAT cua PaddleOCR tren cum so; khong con `MIN_DATE_CONFIDENCE` cua EasyOCR). Phuong an `guessed` (tach cum so dinh / nho nham net chu so) bi ha xuong `CONFIDENCE_MED - 0.01` → UI bôi vàng dòng đó (`row-warn`) để bắt buộc người dùng soát; `confusable` không bao giờ được đứng slot 1 nên không bao giờ được tự điền. Do bang `bench_accuracy.py` voi ground truth do nguoi doc - khong do do phu. Ngưỡng 🟢 còn bị lặp trong `HTML_TEMPLATE` của `manage.py` — sửa đồng bộ cả hai.
7. **Ô không đọc được ngày phải có lịch nhập tay, không bắt gõ `DD/MM/YYYY`.** Nút **📅 Chọn ngày & giờ** (`openCal`/`calApply` trong `HTML_TEMPLATE`) mở lịch tháng tiếng Việt **kèm Giờ bắt đầu / Giờ kết thúc**, tự nhảy tới đúng tháng của thư mục kỳ. Lịch chỉ ghi ngày/giờ + tick ☑️ Xác nhận, **không sửa `ocr_confidence`**. Cảnh báo kỹ thuật: `HTML_TEMPLATE` **không phải raw-string** nên `\'` trong JS bị Python ăn mất và làm chết cả khối `<script>` (dùng `&#39;`); sau khi sửa JS phải chạy `test_ui_calendar.py` **và** mở trang thật bằng browser để xác nhận hàm JS tồn tại.

## Kiến trúc nhanh

* `manage.py` — Django **single-file app**: settings in-process, template HTML trong biến chuỗi `HTML_TEMPLATE`, routes ở `urlpatterns`. Endpoint: `/`, `/scan/`, `/save-all/`, `/export-excel/`, `/snippet/<filename>`.
* `core_engine/` — lõi **không import Django**: `path_parser.py` (metadata từ đường dẫn OneDrive), `pdf_grid_ocr.py` (hình học + OCR + chuẩn hóa ngày giờ), `local_db.py` (SQLite + migration an toàn), `excel_exporter.py` (xuất .xlsx).
* `core_engine` không có `__init__.py` (implicit namespace package).
* Comment/docstring viết **bằng tiếng Việt**.

## Runtime artifacts — không commit, dọn sau khi chạy

`.gitignore` đã loại: `models_storage/`, `media_snippets/`, `local_models/`, `exports/`, `*.sqlite3`, `.qoder/`, `_debug_*`, `_clean_box_*`, `_verify_*.png`.
`viethealth_ocr.sqlite3` đã untrack — app tự tạo lại bảng khi khởi động. Migration phải an toàn với DB đã có dữ liệu (kiểm tra `PRAGMA table_info` trước khi `ALTER TABLE`).

## Tiêu chí "xong"

Không báo hoàn thành nếu thiếu bằng chứng thật:

* OCR thay đổi → chạy `bench_accuracy.py` trên **dữ liệu thật**, báo số cụ thể (tử số/mẫu số, %). Ưu tiên **EXACT** (tự điền đúng); TOP-N (đúng trong gợi ý) là chỉ số phụ, không được thay EXACT để báo "đạt > 90%".
* Sửa `benchmarks/ground_truth.json` thì **phải báo rõ** ô nào tăng nhờ sửa số đo, ô nào tăng nhờ code, và phải có người xác nhận nét viết trên ảnh bằng chứng. Không im lặng sửa GT cho chỉ số đẹp.
* UI/luồng thay đổi → gọi HTTP thật vào `/scan/` + `/save-all/` và **verify lại bằng SQL**, hoặc render trình duyệt kèm ảnh chụp.
* `py_compile` sạch lỗi.
* **Không rút gọn yêu cầu** để vượt mốc 90% dễ hơn — đó là yêu cầu cứng của đề bài.

## Công cụ sửa file (lưu ý thực tế)

* Replace trên dòng chứa `{% ... %}` / `{{ ... }}` trong `manage.py` có thể thất bại dù chuỗi khớp hệt → neo vào chuỗi con ASCII ngắn hoặc viết lại file.
* Bộ đếm "+n/−n line" của tool edit không đáng tin → **Read lại để xác nhận**.
