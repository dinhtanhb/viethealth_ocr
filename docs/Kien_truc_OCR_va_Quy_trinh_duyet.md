# Kiến Trúc OCR & Quy Trình Duyệt Liệu

Tài liệu mô tả **cách engine hoạt động thực tế** và **các bất biến cần bảo vệ**.
Bổ trợ cho [`Ke_hoach_tong_the_100%_offline_AI.md`](./Ke_hoach_tong_the_100%_offline_AI.md) (kế hoạch gốc) và [`AGENTS.md`](../AGENTS.md) (quy ước làm việc).

---

## 1. Luồng xử lý tổng thể

```text
Đường dẫn OneDrive
      │
      ▼  path_parser.VietHealthPathParser.parse()
Metadata (kỳ, nhóm, cán bộ, trẻ, dịch vụ) ──► also cung cấp "prior" năm/tháng
      │
      ▼  pdf_grid_ocr.PDFGridOCREngine.process_pdf()
PyMuPDF render 300 DPI ──► analyze_page_geometry() ──► PHÂN NHÁNH KIỂU PHIẾU
      │                                  │
      │  v_lines >= 6                    │  còn lại
      ▼                                  ▼
  KIỂU A: _process_grid_table      KIỂU B: _process_session_sheets
  (lưới 30 ô, trang cuối)          (phiếu rời, mọi trang)
      │                                  │
      └────────────┬─────────────────────┘
                   ▼
     Tách mực xanh → OCR từng vùng → clean_and_parse_datetime()
                   ▼
     Danh sách session {box_number, date, candidates, start_time, end_time, raw_ocr, confidence, snippet_path}
                   ▼
     local_db.save_document_and_sessions()  →  SQLite
                   ▼
     web_app.py: bảng rà soát → người dùng xác nhận/sửa → save-all → export Excel
```

---

## 2. Hai kiểu phiếu (phát hiện quan trọng nhất)

Toàn bộ PDF trong dữ liệu thật là **ảnh scan thuần, không có text layer**. Có **hai bố cục khác hẳn nhau**:

| | **Kiểu A — Lưới chấm công** | **Kiểu B — Phiếu rời từng buổi** |
| :--- | :--- | :--- |
| Nhận dạng | Trang cuối có **≥ 6 đường kẻ dọc** | Ít đường dọc hơn → không phải lưới |
| Bố cục | 1 bảng 5×6 = **30 ô** ở **trang cuối** | **1–2 buổi mỗi trang**, rải trên **mọi trang** |
| Vị trí ngày | 35% phần **đỉnh mỗi ô** | Cột trái ("THỜI GIAN") của bảng |
| `box_number` | Số ô 1–30 | Số trang (`page_idx + 1`) |
| Ví dụ dữ liệu | `.../2026.10.20/Can thiep/N6/ABP0055 …/x.pdf` | `.../2024.09.15/GDDB/CBPxxxx ….pdf` |

### Cách phát hiện hình học
`analyze_page_geometry()` trả về `{"rect", "h_lines", "v_lines"}`:
* `_line_masks()` — adaptive threshold + morphology tách đường kẻ ngang/dọc.
* `_find_table_rect()` — contour lớn nhất có diện tích đủ dung tích (`line_threshold = 0.45`).
* `_group_line_positions()` — gom vị trí theo projection hàng/cột.
* Bơm cạnh trên/dưới của `rect` vào `h_lines` nếu khoảng trống > 60px (khung bảng thiếu nét).

### Cạm bẫy "buổi ảo" do chữ ký
Ban đầu Kiểu B đọc nhầm **chữ ký phụ huynh** thành ngày (25/29 buổi là giả).
**Khắc phục:** lọc và **cắt run mực xanh về 35% bề rộng bên trái** của khung bảng:

```python
right_limit = gx + int(gw * 0.35)
# chỉ giữ run có tâm <= right_limit, và rx2 = min(rx2, right_limit)
```

---

## 3. Tách chữ viết tay khỏi chữ in

* **Lọc mực xanh:** `b − r > 20 và b > 45` → cô lập bút xanh, loại bỏ chữ in đen của form.
* **Fallback grayscale Otsu** (`_grayscale_fallback`) khi vùng gần như không có mực xanh.
* **`_blue_ink_row_runs()`**: projection theo hàng trên mask mực xanh của **cả trang**, gom các dải chữ viết tay liền kề.
* **`_session_band_fallback()`**: dự phòng bằng mực đen, **bắt buộc khớp regex ngày đầy đủ `DD/MM/YYYY`** và đánh dấu `needs_review=True` (để tránh ăn nhầm dòng in sẵn "Từ ngày 1-6:").

---

## 4. Chuẩn hóa & phục hồi ngày hỏng

`clean_and_parse_datetime(raw_text, default_year, dets)` tra ve `{date, candidates, confidence, warning, raw_ocr}`.
Chi co **duong dan khong dan**: moi cap (Ngay, Thang) deu phai doc duoc tu anh hoac tach ra tu cum so dinh.

Thu tu bang chung (`basis`), gan da 3 phuong an tra ve cho UI bam chon:

| `basis` | Cach sinh | Tu dong dien? |
| :--- | :--- | :--- |
| `separator` | 2 cum so co dau `/ . -` chen giua | ✅ Co |
| `adjacent` | 2 cum so dung canh nhau tren cung dong OCR | ✅ Co |
| `split` | Tach mot cum so dinh (VD `3007` -> `30/07`) | ⚠️ Co, nhung bi ha diem (`guessed`) |
| `prefix` | Lay cho dau cua cum dai (VD `10 8206` -> `10/08`) | ⚠️ Co, `guessed` |
| `confusable` | Doi 1 chu so nham lan (1↔7, 8↔9, 0↔2, 3↔5/8, 6↔0/5) | ❌ **KHONG BAO GIO** - xep cuoi danh sach, chi de nguoi dung bam |

Da bi go bo (nguoc dong da gay ra loi "0/10 ngay dung"): `CONFUSION_MAP` sira mat chu, ghep bia
"2 cum so bat ky", va **muon Thang tu ten thu muc ky** (`2026.10.20` -> thang 10). Thu muc ky gio chi
co the cung **Nam** khi anh khong doc ra nam, va luon gan `warning`.

`run_ocr_on_cell()` tra `(raw_text, dets)` voi `dets = [{x, y, text, score}]` lay tu `PaddleOCR.predict()`
(sap theo truc x). Diem tin cay = trung binh diem cua **rieng cac cum so**, khong tính chữ ký/tên in sẵn.

---

## 5. Phân tầng độ tin cậy

| Hằng số | Giá trị | Ý nghĩa |
| :--- | :--- | :--- |
| `CONFIDENCE_HIGH` | **0.60** | Ngưỡng 🟢 "AI tự đọc chắc chắn" |
| `CONFIDENCE_MED` | **0.40** | Ngưỡng 🟡 "Tin cậy thấp – cần soát" |

* Diem cua PaddleOCR la xac suat that (0..1) tren cuong so, cao hon thang EasyOCR cu (0.45/0.30/0.15).
* **Bất biến quan trọng:** ngày phải *tách/đoán* (`guessed`) luôn bị hạ xuống `CONFIDENCE_MED - 0.01` để **buộc** người dùng soát:

```python
if best["date"] and best["warning"]:
    best["confidence"] = min(best["confidence"], self.CONFIDENCE_MED - 0.01)
```

* Ngưỡng 🟢 bị **lặp lại trong `HTML_TEMPLATE`** của `web_app.py` — đổi hằng số phải đổi cả template.

---

## 6. Quy trình xác nhận của người dùng (bất biến chống mất dữ liệu)

### 6.1. Ngữ nghĩa `is_verified`

| Tác nhân | `is_verified` |
| :--- | :--- |
| AI mới đọc về (có ngày đi nữa) | **0** — người dùng **phải tự tích** ☑️ |
| Người dùng tích ☑️ / sửa rồi **Lưu toàn bộ** | **1** |

> `is_verified = 1` **chỉ** có nghĩa "con người đã đối chiếu và xác nhận". AI không bao giờ được set.

### 6.2. Quét lại không được ghi đè

`save_document_and_sessions()` **trước khi** `DELETE` phải chốt các dòng đã xác nhận theo `box_number`, rồi khôi phục khi chèn lại:

```python
SELECT box_number, date_str, start_time, end_time
FROM intervention_sessions WHERE doc_id = ? AND is_verified = 1
```

Nếu `box_number` của session mới khớp một dòng đã xác nhận → giữ **ngày/giờ của con người** và `is_verified=1`;
ngược lại → ghi giá trị AI với `is_verified=0`.

### 6.3. Luồng UI

1. `POST /scan/` → quét file/thư mục, lưu AI kết quả, redirect kèm **% phủ sóng**.
2. `GET /` → bảng rà soát: ảnh cắt (rê chuột phóng to 2.4×), ô sửa Ngày/Giờ, `ocr_confidence`, nhãn 🟢🟡, ☑️ Xác nhận.
3. `POST /save-all/` → ghi Ngày/Giờ + trạng thái xác nhận.
4. `GET /export-excel/` → xuất `.xlsx` từ `excel_exporter`.

**Mọi message redirect phải đi qua `urllib.parse.urlencode({...})`** — ký tự `&` thô làm cắt cụt thông báo từ điểm có `&`.

---

## 7. Đo lường & kiểm chứng (bài học độ phủ ≠ độ chính xác)

* `bench_accuracy.py` — so kết quả AI với **ground truth do người đọc tay** (`benchmarks/ground_truth.json`), in tách bạch:
  * `EXACT` = % ô AI **tự điền đúng tuyệt đối** (đây mới là thước đo yêu cầu "AI tự đọc");
  * `TOP-N` = % ô có đáp án đúng **nằm trong gợi ý** (người dùng bấm chọn);
  * `NGÀY` = đọc đúng riêng phần ngày; `NGUY HIỂM` = điền SAI mà điểm ≥ `CONFIDENCE_MED`.
* ⚠️ Con số **`41/45 = 91.1%`** từng ghi ở đây là **độ phủ** do `bench_auto_read.py` (đã xóa) tính ra: nó đếm cả ô AI điền **sai**, nên thực tế 0 ngày đúng mà vẫn báo 91%. Không dùng lại kiểu đo đó.
* Số liệu hiện tại, **trên 1 file** `Test_doc_PDF_2.pdf` (10 ô viết tay, kỳ `2026.10.20`, Kiểu A):
  **EXACT 6/10 = 60%** | **TOP-N 10/10 = 100%** | NGÀY 9/10 | NGUY HIỂM 2 ô.
  Chưa phải kết luận tổng thể — cần thêm ground truth cho nhiều file Kiểu A/Kiểu B khác.
* Chi phí thật trên CPU: init engine ~18 s, **quét 1 file Kiểu A ~60–70 s** (`_debug_perf` 19/10/2026). Một kỳ ~500 file ⇒ nhiều giờ, phải quét nền/từng phần.

---

## 8. Ghi chú SQLite & migration

* `pdf_documents` (1 file PDF ↔ metadata) và `intervention_sessions` (nhiều buổi ↔ 1 document, `ON DELETE CASCADE`).
* SQLite **không có** `ADD COLUMN IF NOT EXISTS` → migration phải kiểm tra `PRAGMA table_info(intervention_sessions)` trước rồi mới `ALTER TABLE` (cách cột `ocr_confidence` được thêm mà không mất dữ liệu cũ).
* File `viethealth_ocr.sqlite3` là **runtime artifact**, đã untrack — app tự tạo bảng khi khởi động.
