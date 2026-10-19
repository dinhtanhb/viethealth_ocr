# AGENTS.md — Hướng dẫn cho AI/engineer làm việc với repo này

Tài liệu này ghi lại **các quy ước và cạm bẫy thực tế** đã được kiểm chứng trong quá trình phát triển. Đọc trước khi sửa code.

## 1. Bối cảnh dự án

* Mục tiêu cốt lõi: **AI tự đọc > 90% ngày viết tay trên PDF chấm công can thiệp → tự điền → người dùng xác nhận/sửa → lưu → xuất Excel**, chạy **100% offline**.
* Stack: Python + Django (single-file app) + EasyOCR (CPU) + OpenCV + PyMuPDF + SQLite.
* Không có build system, không có test framework. Không thêm dependency trừ khi thật sự cần.

## 2. Môi trường & lệnh (Windows / PowerShell)

* **Phải dùng Python của venv**: `.\venv\Scripts\python.exe`. Python hệ thống không có `django` → `ModuleNotFoundError`.
* **Chạy với `-X utf8`** khi có tiếng Việt: `.\venv\Scripts\python.exe -X utf8 ...`.
* PowerShell **không hỗ trợ `&&`** → dùng `;`.
* Chạy server: `.\venv\Scripts\python.exe web_app.py runserver 127.0.0.1:8031 --noreload`
  * ⚠️ `--noreload` nghĩa là **sửa code xong phải restart server** thì thay đổi mới có hiệu lực.
  * Tìm/đóng tiến trình chiếm port: `Get-NetTCPConnection -LocalPort 8031 -State Listen` → `Stop-Process -Id <pid> -Force`.
* Kiểm tra hình học/kết quả: `bench_auto_read.py "<dir|file PDF>" [max_files]`.

## 3. Cạm bẫy đã từng gây lỗi (KHÔNG lặp lại)

### 3.1. Đường dẫn tiếng Việt
* Chuỗi tiếng Việt nhập/gõ trực tiếp thường **không khớp** do khác chuẩn Unicode (NFC/NFD) → `FileNotFoundError`.
* **Luôn lấy đường dẫn bằng `os.walk`** rồi dùng lại giá trị trả về, thay vì tự ghép/xuất.
* Trong `powershell -Command "..."` được gọi từ tool, ký tự `$` có thể bị loại bỏ làm hỏng script. → Dùng Python cho các phép kiểm tra file/thư mục.

### 3.2. Hai kiểu phiếu — đừng giả định chỉ có lưới 30 ô
* `process_pdf()` là **dispatcher**: phân tích hình học trang cuối, `v_lines >= 6` → **Kiểu A** (lưới 30 ô), ngược lại → **Kiểu B** (phiếu rời từng buổi, nhiều trang).
* Kiểu B: phải duyệt **tất cả các trang**, và **giới hạn vùng đọc ở 35% bề rộng bên trái** của khung bảng. Bỏ bước này sẽ đọc nhầm **chữ ký** thành ngày (sinh ra "buổi ảo").
* Mọi PDF trong dữ liệu thật đều là **ảnh scan thuần, không có text layer** — đừng thử đọc text layer.

### 3.3. Ngữ nghĩa `is_verified`
* `is_verified = 1` **chỉ** có nghĩa "con người đã xác nhận". AI **không bao giờ** được tự set giá trị này.
* Khi quét lại một file đã có kết quả, `save_document_and_sessions()` **phải giữ** các dòng `is_verified=1` (khớp theo `box_number`) thay vì ghi đè bằng giá trị AI. Đây là quy định chống mất dữ liệu đã duyệt.

### 3.4. Ngưỡng tin cậy
* `CONFIDENCE_HIGH = 0.45`, `CONFIDENCE_MED = 0.30`, `MIN_DATE_CONFIDENCE = 0.15` (trong `pdf_grid_ocr.py`).
* Chữ viết tay hiếm khi vượt 0.55 → **đừng nâng** `CONFIDENCE_HIGH` lên cao hơn, nếu không sẽ gần như không còn dòng 🟢.
* Ngày phải **suy đoán** (lấy tháng/năm theo tên kỳ) bị hạ xuống `< CONFIDENCE_MED` để buộc người dùng soát. Giữ nguyên hành vi này.
* Ngưỡng 🟢 cũng được lặp lại trong inline template của `web_app.py` — **sửa ở đây phải sửa ở đó**.

### 3.5. Django redirect & ký tự `&`
* Message redirect chứa query string: **luôn dùng `urllib.parse.urlencode({...})`**. Ký tự `&` thô sẽ làm cắt thông báo từ điểm có `&` (lỗi đã gặp với dòng "AI tự đọc & điền Ngày").

### 3.6. Công cụ sửa file
* Trong `web_app.py`, thao tác replace trên các dòng chứa cú pháp template Django `{% ... %}` / `{{ ... }}` có thể **thất bại dù chuỗi khớp hệt**. Workaround: neo vào chuỗi con ASCII ngắn, hoặc viết lại toàn bộ file (file nhỏ).
* Bộ đếm "+n/-n line" của tool edit **không đáng tin** — luôn Read lại để xác nhận trạng thái thật.

## 4. Cấu trúc & quy ước code

* `core_engine/` là lõi **độc lập với web**: không import Django ở đó. Mọi thứ qua `web_app.py`.
* `web_app.py` là **single-file app**: settings Django cấu hình in-process, HTML template nằm trong biến chuỗi `HTML_TEMPLATE`, URLconf là `urlpatterns` cuối file. Không tách thành package Django chuẩn.
* `core_engine` **không có `__init__.py`** (dùng implicit namespace package) — đừng thêm nếu chưa cần.
* Đường dẫn mặc định được hardcode tương đối so với `BASE_DIR`: `models_storage/easyocr` (model), `media_snippets` (ảnh cắt), `viethealth_ocr.sqlite3` (DB), `exports/` (Excel).
* Comment/docstring trong repo này viết **bằng tiếng Việt**, giữ nhất quán.

## 5. Dữ liệu runtime — không commit

Đã nằm trong `.gitignore`: `models_storage/`, `media_snippets/`, `local_models/`, `exports/`, `*.sqlite3`, `.qoder/`, ảnh `_debug_*` / `_clean_box_*` / `_verify_*.png`.

* `viethealth_ocr.sqlite3` **đã được untrack**: DB chỉ là kết quả chạy, app tự tạo lại bảng khi khởi động.
* `local_db._init_tables()` tự `ALTER TABLE` thêm cột mới — mọi migration phải **an toàn với DB đã có dữ liệu** (SQLite không có `ADD COLUMN IF NOT EXISTS`, phải kiểm tra qua `PRAGMA table_info`).
* Xóa file tạm/diagnostic trước khi kết thúc phiên làm việc.

## 6. Kiểm chứng trước khi báo "xong"

1. `python -m py_compile <các file đã sửa>` phải sạch lỗi.
2. Với thay đổi OCR: chạy `bench_auto_read.py` trên **dữ liệu thật** và báo con số cụ thể (tử số/mẫu số, %), không suy đoán.
3. Với thay đổi UI/luồng: gọi HTTP thật vào `/scan/`, `/save-all/` và **kiểm tra lại DB bằng SQL**, hoặc render trình duyệt + ảnh chụp.
4. Không rút gọn yêu cầu để cho "đỗ" dễ hơn — đặc biệt ngưỡng **> 90%** là yêu cầu cứng.

## 7. Dữ liệu mẫu (để kiểm thử)

Cấu trúc OneDrive thật, dùng để benchmark:

```
D:\VietHealth\INC3b - Documents\6. Bao cao\7. Ho so can thiep\2. Ho so theo ky\
├── 2026.10.20\Can thiep\N6\ABP0055 <Tên trẻ>\...pdf     # Kiểu A (lưới 30 ô), có tầng "Can thiep" + nhóm
└── 2024.09.15\GDDB\CBPxxxx <Tên>.pdf                    # Kiểu B (phiếu rời), KHÔNG có tầng cán bộ
```

* `path_parser.py` nhận diện **kỳ** bằng regex `^\d{4}[.\-/]\d{1,2}([.\-/]\d{1,2})?$` ở **bất kỳ tầng nào**, và cho phép **thiếu tầng cán bộ** (bố cục 2024).
* Tên kỳ cũng là "prior" năm/tháng cho suy đoán ngày bị thiếu nét.
