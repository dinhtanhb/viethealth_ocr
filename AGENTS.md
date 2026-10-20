# AGENTS.md — Hướng dẫn cho AI/engineer làm việc với repo này

Tài liệu này ghi lại **các quy ước và cạm bẫy thực tế** đã được kiểm chứng trong quá trình phát triển. Đọc trước khi sửa code.

## 1. Bối cảnh dự án

* Mục tiêu cốt lõi: **AI tự đọc > 90% ngày ghi trên PDF chấm công can thiệp → tự điền → người dùng xác nhận/sửa → lưu → xuất Excel**, chạy **100% offline**.
  * **Đã đo đạt trên dữ liệu hiện có** (20/10/2026, 3 ground truth / 32 ngày do người đọc): **EXACT 31/32 = 96.9%**, TOP-N 32/32 = 100%, GIẢ 0, NGUY HIỂM 0. Con số này **chưa phải kết luận trên toàn bộ hồ sơ** — mới chỉ là 3 file; 4/32 ô tăng là nhờ đính chính ground truth (có người xác nhận), không phải nhờ code.
* Stack: Python + Django (single-file app) + PaddleOCR/PaddlePaddle (CPU, offline) + OpenCV + PyMuPDF + SQLite.
* Không có build system, không có test framework. Không thêm dependency trừ khi thật sự cần.

## 2. Môi trường & lệnh (Windows / PowerShell)

* **Phải dùng Python của venv**: `.\venv\Scripts\python.exe`. Python hệ thống không có `django` → `ModuleNotFoundError`.
* **Chạy với `-X utf8`** khi có tiếng Việt: `.\venv\Scripts\python.exe -X utf8 ...`.
* PowerShell **không hỗ trợ `&&`** → dùng `;`.
* Chạy server: `.\venv\Scripts\python.exe web_app.py runserver 127.0.0.1:8031 --noreload`
  * ⚠️ `--noreload` nghĩa là **sửa code xong phải restart server** thì thay đổi mới có hiệu lực.
  * Tìm/đóng tiến trình chiếm port: `Get-NetTCPConnection -LocalPort 8031 -State Listen` → `Stop-Process -Id <pid> -Force`.
* Kiểm tra độ chính xác: `bench_accuracy.py` (so với `benchmarks/ground_truth.json`) — in **EXACT** (tự điền đúng) và **TOP-N** (đúng nằm trong gợi ý) tách bạch.
  ⚠️ Benchmark cũ `bench_auto_read.py` đo **độ phủ** (đếm cả ô điền sai) đã bị xóa — đừng dùng lại kiểu đo đó.

## 3. Cạm bẫy đã từng gây lỗi (KHÔNG lặp lại)

### 3.1. Đường dẫn tiếng Việt
* Chuỗi tiếng Việt nhập/gõ trực tiếp thường **không khớp** do khác chuẩn Unicode (NFC/NFD) → `FileNotFoundError`.
* **Luôn lấy đường dẫn bằng `os.walk`** rồi dùng lại giá trị trả về, thay vì tự ghép/xuất.
* Trong `powershell -Command "..."` được gọi từ tool, ký tự `$` có thể bị loại bỏ làm hỏng script. → Dùng Python cho các phép kiểm tra file/thư mục.

### 3.2. Ba dạng phiếu — đừng giả định chỉ có lưới 30 ô
* `process_pdf()` là **dispatcher**: phân tích hình học trang cuối, `v_lines >= 6` → **Kiểu A** (lưới 30 ô), ngược lại → **Kiểu B** (phiếu rời, nhiều trang). Trong Kiểu B có **hai dạng bút tích**: viết tay mực xanh (`CBP0005`) và **ngày in đen đánh máy** (`CBP0007`).
* Kiểu B viết tay: phải duyệt **tất cả các trang**, và giới hạn vùng đọc đến **đường kẻ dọc đầu tiên của bảng** (`_session_column_divider`, tìm trong 5–35% bề rộng khung). Bỏ bước này sẽ đọc nhầm **chữ ký, số điện thoại, dòng "Mã số", cột "Nội dung"** thành ngày (đã đo trên CBP0005).
* **Cắt dải theo giao số, không lọc theo tâm**: một dòng chứa cả ngày (trái) lẫn ghi chú (phải) có tâm nằm ngoài cột ngày nhưng phần bên trái vẫn là ngày thật. Lọc theo tâm từng làm mất 2 ngày của CBP0005 trang 4.
* **Trang không có kẻ dọc trong 5–35% bề rộng là trang văn bản in** (MỤC TIÊU / TÓM TẮT / NHẬN ĐỊNH) → `continue` trước cả fallback. Trang MỤC TIÊU in sẵn "Từ ngày 1-6:", "Từ ngày 7-15:" từng bị đọc thành `10/07/2024` (ngày giả).
* **Đường kẻ dọc đứt khi scan** (`CBP0007` trang 8) không qua ngưỡng mặc định 0.45 → `_session_geometry()` thử lại với `line_threshold=0.35`. Đo trên CBP0005/CBP0007: ngưỡng 0.35 chỉ thêm đường kẻ thật (±1–2 px), **không** sinh kẻ giả trên trang văn bản (trang MỤC TIÊU vẫn trả `divider=None`).
* **Hai lớp tiền xử lý trên CÙNG một clip** (`_read_session_clip`): lớp mực xanh trước; chỉ chạy thêm lớp Grayscale/Otsu khi `_blue_read_is_weak()` (không ra ngày, hoặc phương án dẫn đầu `guessed`), rồi **gộp** phương án (`_merge_candidate_pools`). Đây là thay đổi đưa `CBP0005` từ **5/10 → 9/10 EXACT** (4 ô mà lớp xanh đọc sai thì lớp Grayscale đọc đúng với điểm cao hơn). Giá phải trả: `CBP0005` **156 s → 403 s/file**. Khi hợp nhất, các cổng chặn cũ phải được kiểm trên **lớp đã sinh ra phương án chốt** (`gate_raw`), không phải chuỗi thô của lớp xanh.
* **Đường đọc riêng cho ngày in đen** (`_session_band_fallback`): kích hoạt khi trang không còn nét viết tay xanh. Chỉ nhận detection **match toàn bộ chuỗi** theo `dd/mm/yyyy` (`_DATE_TOKEN_RE`, năm bắt buộc), không lọc `min_y_ratio` (ngày in của `CBP0007` nằm **trên cùng** dải, bộ lọc cũ từng xóa 11/12 ngày). Kết quả `CBP0007`: **12/12 EXACT** (trước bản này chỉ 1 buổi). `solid` (điểm ≥ `CONFIDENCE_HIGH`, không `guessed`/`printed_suspect`, không có ngày thứ hai mâu thuẫn trong cùng ô) → `needs_review=False`.
* **Đã đo và loại bỏ** (đừng thử lại): nới lề trái cụm cắt (hằng số cố định hay lan tới khoảng trắng đều kéo nét kẻ bảng vào crop, `10/8` → `04/01`), tách một dải cao theo dòng chữ in cho phiếu viết tay (không đổi kết quả), phóng to ảnh OCR lên 640px (không đổi chỉ số, chậm hơn), và **prior chuỗi buổi (DP) để đẩy phương án `confusable` lên đứng đầu** — người dùng **CHỐI** vì vi phạm bất biến mục 3.4.
* `process_pdf()` vẫn còn điểm yếu: `geo is None` ở *trang cuối* rơi vào nhánh Kiểu A.
* Mọi PDF trong dữ liệu thật đều là **ảnh scan thuần, không có text layer** — đừng thử đọc text layer.

### 3.3. Ngữ nghĩa `is_verified`
* `is_verified = 1` **chỉ** có nghĩa "con người đã xác nhận". AI **không bao giờ** được tự set giá trị này.
* Khi quét lại một file đã có kết quả, `save_document_and_sessions()` **phải giữ** các dòng `is_verified=1` (khớp theo `box_number`) thay vì ghi đè bằng giá trị AI. Đây là quy định chống mất dữ liệu đã duyệt.

### 3.4. Ngưỡng tin cậy
* `CONFIDENCE_HIGH = 0.60`, `CONFIDENCE_MED = 0.40` (trong `pdf_grid_ocr.py`) — thang điểm thật của PaddleOCR (0..1 trên cụm số), **khác** thang cũ của EasyOCR (0.45/0.30/0.15).
* Độ tin cậy chỉ tính trên **cụm số**; tuyệt đối không trung bình hóa toàn bộ detection (chữ ký/tên in sẵn sẽ kéo điểm lên ảo).
* Phương án phải **tách/đoán** (`split`, `prefix`) hoặc **nhầm nét chữ số** (`confusable`) bị đánh dấu `guessed` và hạ dưới `CONFIDENCE_MED` để buộc người dùng soát. `confusable` không bao giờ được đứng đầu danh sách → không bao giờ được tự điền.
  ⚠️ Bất biến này **giữ nguyên cả khi hợp nhất nhiều lớp tiền xử lý**, và **kể cả khi** dùng prior "các buổi tăng dần theo thứ tự" để biện minh cho đáp án (đã đo: prior chuỗi đẩy được `CBP0005` ô#9 lên `24/08` tức 10/10, nhưng người dùng **chối** vì đó là tự điền một ngày AI chỉ *đoán*).
* Phương án có `printed_suspect = True` (cả 2 số chỉ đến từ detection **lẫn ≥2 chữ cái** → nhiều khả năng là chữ in chân trang/đầu dòng) hoặc nằm trong cụm OCR **chủ yếu là chữ** (`_is_digit_dominant`) → `date = None`, chỉ còn gợi ý. Đây là luật chặn "bịa ngày từ chữ in", tuyệt đối không được nới.
* Chuỗi chỉ toàn số `1` (`'1 1'`, `'1111'`) = **viền bảng đứng** bị OCR thành chữ số → loại outright, không sinh phương án.
* Ngưỡng 🟢 cũng được lặp lại trong inline template của `web_app.py` — **sửa ở đây phải sửa ở đó**.

### 3.5. Django redirect, ký tự `&` và JS nhúng trong `HTML_TEMPLATE`
* Message redirect chứa query string: **luôn dùng `urllib.parse.urlencode({...})`**. Ký tự `&` thô sẽ làm cắt thông báo từ điểm có `&` (lỗi đã gặp với dòng "AI tự đọc & điền Ngày").
* `HTML_TEMPLATE` là chuỗi Python **không phải raw-string**, nên mọi backslash trong JS/CSS bên trong nó bị Python xử lý trước. Viết `\'` trong một chuỗi JS sẽ thành `'` → **lệch dấu nháy, chết cả khối `<script>`** (im lặng: trang vẫn tải 200, chỉ có mọi hàm JS là `undefined`). Muốn có `\'` trong JS phải viết `\\'`; an toàn hơn trong HTML attribute là dùng `&#39;`.
* Sau khi sửa JS trong template, **chạy `python -X utf8 test_ui_calendar.py`** (render template + kiểm parity dấu nháy từng dòng JS) rồi **mở trang thật bằng browser** — render thành công không có nghĩa là JS chạy được.
* **Nhập tay bằng lịch 📅** (dòng AI không đọc được ngày): `openCal`/`calRender`/`calApply` trong `HTML_TEMPLATE` — lịch tháng tiếng Việt + ô `Giờ bắt đầu`/`Giờ kết thúc`, tự nhảy đúng tháng của `period`. Chỉ ghi `date_str`/`start_time`/`end_time` và tick ☑️ Xác nhận; **không được sửa `ocr_confidence`** (không gán điểm giả cho ngày con người nhập).

### 3.6. Công cụ sửa file
* Trong `web_app.py`, thao tác replace trên các dòng chứa cú pháp template Django `{% ... %}` / `{{ ... }}` có thể **thất bại dù chuỗi khớp hệt**. Workaround: neo vào chuỗi con ASCII ngắn, hoặc viết lại toàn bộ file (file nhỏ).
* Bộ đếm "+n/-n line" của tool edit **không đáng tin** — luôn Read lại để xác nhận trạng thái thật.

## 4. Cấu trúc & quy ước code

* `core_engine/` là lõi **độc lập với web**: không import Django ở đó. Mọi thứ qua `web_app.py`.
* `web_app.py` là **single-file app**: settings Django cấu hình in-process, HTML template nằm trong biến chuỗi `HTML_TEMPLATE`, URLconf là `urlpatterns` cuối file. Không tách thành package Django chuẩn.
* `core_engine` **không có `__init__.py`** (dùng implicit namespace package) — đừng thêm nếu chưa cần.
* Đường dẫn mặc định được hardcode tương đối so với `BASE_DIR`: `models_storage/paddlex` (model), `media_snippets` (ảnh cắt), `viethealth_ocr.sqlite3` (DB), `exports/` (Excel).
* Comment/docstring trong repo này viết **bằng tiếng Việt**, giữ nhất quán.

## 5. Dữ liệu runtime — không commit

Đã nằm trong `.gitignore`: `models_storage/`, `media_snippets/`, `local_models/`, `exports/`, `*.sqlite3`, `.qoder/`, ảnh `_debug_*` / `_clean_box_*` / `_verify_*.png`.

* `viethealth_ocr.sqlite3` **đã được untrack**: DB chỉ là kết quả chạy, app tự tạo lại bảng khi khởi động.
* `local_db._init_tables()` tự `ALTER TABLE` thêm cột mới — mọi migration phải **an toàn với DB đã có dữ liệu** (SQLite không có `ADD COLUMN IF NOT EXISTS`, phải kiểm tra qua `PRAGMA table_info`).
* Xóa file tạm/diagnostic trước khi kết thúc phiên làm việc.

## 6. Kiểm chứng trước khi báo "xong"

1. `python -m py_compile <các file đã sửa>` phải sạch lỗi.
2. Với thay đổi OCR: chạy `bench_accuracy.py` trên **dữ liệu thật** và báo con số cụ thể (tử số/mẫu số, %), không suy đoán.
   ⚠️ Phải báo **EXACT trước, TOP-N sau**: EXACT mới là thước đo yêu cầu "AI tự đọc"; TOP-N (đúng trong gợi ý) **không được** dùng để tuyên bố đạt mốc >90% tự động.
   Chỉ số lấy từ 1 file duy nhất là **chưa đủ** để kết luận — phải đo trên nhiều file thật (cả Kiểu A lẫn Kiểu B).
   ⚠️ Nếu sửa `benchmarks/ground_truth.json` thì **phải nói rõ** ô nào tăng là nhờ sửa số đo, ô nào tăng là nhờ code. Không được im lặng sửa ground truth cho chỉ số "đẹp".
   Lần đo đa file gần nhất (20/10/2026, **3** ground truth trong `benchmarks/ground_truth.json`): Kiểu A `Test_doc_PDF_2` **EXACT 10/10, TOP-N 10/10** (4/10 nhờ đính chính GT); Kiểu B viết tay `CBP0005` **EXACT 9/10, TOP-N 10/10**; Kiểu B in đen `CBP0007` **EXACT 12/12**; tổng **31/32 = 96.9% EXACT**, **32/32 = 100% TOP-N**, GIẢ 0, NGUY HIỂM 0. Ô còn sai: `CBP0005` ô#9 — `2` đầu ngày bị **cắt mất ở công đoạn định vị** (ảnh cắt chỉ còn `4 18 / 2024`), không phải lỗi nhận dạng nét.
3. Với thay đổi UI/luồng: gọi HTTP thật vào `/scan/`, `/save-all/` và **kiểm tra lại DB bằng SQL**, hoặc render trình duyệt + ảnh chụp.
4. Không rút gọn yêu cầu để cho "đỗ" dễ hơn — đặc biệt ngưỡng **> 90%** là yêu cầu cứng.

## 7. Dữ liệu mẫu (để kiểm thử)

Cấu trúc OneDrive thật, dùng để benchmark:

```
D:\VietHealth\INC3b - Documents\6. Bao cao\7. Ho so can thiep\2. Ho so theo ky\
├── 2026.10.20\Can thiep\N6\ABP0055 <Tên trẻ>\...pdf     # Kiểu A (lưới 30 ô), có tầng "Can thiep" + nhóm
├── 2024.09.15\GDDB\CBPxxxx <Tên>.pdf                    # Kiểu B (phiếu rời), KHÔNG có tầng cán bộ
│   ├── CBP0005  # ngày VIẾT TAY mực xanh
│   └── CBP0007  # ngày IN đen đánh máy, đường kẻ dọc bị đứt ở trang 8
```

* `path_parser.py` nhận diện **kỳ** bằng regex `^\d{4}[.\-/]\d{1,2}([.\-/]\d{1,2})?$` ở **bất kỳ tầng nào**, và cho phép **thiếu tầng cán bộ** (bố cục 2024).
* Tên kỳ cũng là "prior" năm/tháng cho suy đoán ngày bị thiếu nét.
