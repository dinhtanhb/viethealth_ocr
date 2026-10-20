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
     Tách mực xanh → OCR từng vùng → (Kiểu B: nếu chưa chắc, OCR thêm lớp Grayscale trên
     CÙNG clip rồi gộp phương án) → clean_and_parse_datetime()
                   ▼
     Danh sách session {box_number, date, candidates, start_time, end_time, raw_ocr, confidence, snippet_path}
                   ▼
     local_db.save_document_and_sessions()  →  SQLite
                   ▼
     web_app.py: bảng rà soát → người dùng xác nhận/sửa → save-all → export Excel
```

---

## 2. Ba dạng phiếu (phát hiện quan trọng nhất)

Toàn bộ PDF trong dữ liệu thật là **ảnh scan thuần, không có text layer**. Có **hai bố cục khác nhau**, và trong bố cục Kiểu B có **hai dạng bút tích**:

| | **Kiểu A — Lưới chấm công** | **Kiểu B — Phiếu rời từng buổi** |
| :--- | :--- | :--- |
| Nhận dạng | Trang cuối có **≥ 6 đường kẻ dọc** | Ít đường dọc hơn → không phải lưới |
| Bố cục | 1 bảng 5×6 = **30 ô** ở **trang cuối** | **1–2 buổi mỗi trang**, rải trên **mọi trang** |
| Vị trí ngày | 35% phần **đỉnh mỗi ô** | Cột trái ("THỜI GIAN") của bảng |
| `box_number` | Số ô 1–30 | Số trang (`page_idx + 1`) |
| Ví dụ dữ liệu | `.../2026.10.20/Can thiep/N6/ABP0055 …/x.pdf` | `.../2024.09.15/GDDB/CBPxxxx ….pdf` |
| Dạng bút tích của Kiểu B | — | **viết tay mực xanh** (`CBP0005`) hoặc **ngày in đen đánh máy** (`CBP0007`) → hai đường đọc khác nhau ở mục 3 |

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

## 3. Tách chữ viết tay khỏi chữ in — và hai lớp tiền xử lý trên cùng một clip

* **Lọc mực xanh:** `b − r > 20 và b > 45` → cô lập bút xanh, loại bỏ chữ in đen của form.
* **Fallback grayscale Otsu** (`_grayscale_fallback`): gray → Otsu(INV) → OPEN 2×2 → invert → blur → phóng 2.2× + pad 24px. Khác với lọc xanh, lớp này **giữ lại chữ in đen**.
* **`_blue_ink_row_runs()`**: projection theo hàng trên mask mực xanh của **cả trang**, gom các dải chữ viết tay liền kề.
* **`_read_session_clip()` — ensemble hai lớp trên PHIẾU VIẾT TAY** (Kiểu B): chạy lớp xanh trước; nếu `_blue_read_is_weak()` (không ra ngày, hoặc phương án dẫn đầu bị `guessed`) thì chạy thêm lớp Grayscale **trên đúng clip đó**, bỏ detection lẫn ≥2 chữ cái (`_drop_lettery_dets`), rồi `_merge_candidate_pools()` gộp hai danh sách theo *(vị trí trong lớp sinh ra nó, −điểm OCR)*.
  * **Không sinh ngày mới**: mọi phương án đều do OCR đọc ra từ chính ảnh; ensemble chỉ mở rộng **candidate pool**.
  * `votes` (số lớp đọc trùng ngày) được ghi nhận nhưng **chưa dùng để xếp hạng**.
  * cổng chặn `_is_digit_dominant` được áp trên **chuỗi thô của lớp đã sinh ra phương án chốt** (`gate_raw`), không phải chuỗi của lớp xanh.
  * Đo trên `CBP0005`: EXACT **5/10 → 9/10**, thời gian **156 s → 403 s**/file (9 trang).
* **`_session_band_fallback()` — đường đọc RIÊNG cho NGÀY IN ĐEN đánh máy** (`CBP0007`), kích hoạt khi trang không còn nét viết tay xanh:
  * OCR cả dải Grayscale và chỉ nhận detection **match toàn bộ chuỗi** theo `dd/mm/yyyy` (`_DATE_TOKEN_RE`, năm bắt buộc), nên `Buổi 7`, `Ngày`, `Từ ngày 1-6:`, `2024.09.15` không lọt.
  * **Không lọc `min_y_ratio`**: ngày in của `CBP0007` nằm ở **đỉnh** dải (y ≈ 130–200 trên bảng cao 1542–1699 px), bộ lọc 0.35 cũ đã xóa 11/12 ngày.
  * `solid` = điểm ≥ `CONFIDENCE_HIGH` và phương án chốt không `guessed`/`printed_suspect` và không có ngày thứ hai mâu thuẫn trong cùng ô → `needs_review=False`; ngược lại kèm cảnh báo "(ngày in sẵn, cần soát)".
  * Đo trên `CBP0007`: **12/12 EXACT**, điểm 0.95–1.00 (trước khi có đường đọc này chỉ trả về 1 buổi). `needs_review` chỉ tắt khi `solid` — với phiếu in đen sạch thì cả 12 ô đều `solid`.
* **Ngưỡng nhận diện đường kẻ:** `_session_geometry()` dùng chung một ngưỡng cho `geo` và `divider`; nếu không thấy kẻ dọc, thử lại với `line_threshold=0.35` (nét kẻ bị **đứt khi scan** — `CBP0007` trang 8). Đã đo: 0.35 không sinh đường kẻ giả trên trang văn bản in.

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
* Bất biến này **giữ nguyên khi hợp nhất nhiều lớp tiền xử lý** (mục 3): `guessed`/`confusable` không bao giờ được đứng đầu và không bao giờ được tự điền, **kể cả khi** một prior bên ngoài (vd "các buổi phải tăng dần theo thứ tự") biện minh cho đáp án đó. Prior kiểu này đã đo được và **bị người dùng chối**.

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
3. Với dòng 🔴 (**AI chưa đọc được ngày**) — và cả dòng đã có ngày cần sửa — bấm **📅 Chọn ngày & giờ** để mở **lịch nhập tay** (xem 6.4), thay vì phải gõ `DD/MM/YYYY`.
4. `POST /save-all/` → ghi Ngày/Giờ + trạng thái xác nhận.
5. `GET /export-excel/` → xuất `.xlsx` từ `excel_exporter`.

**Mọi message redirect phải đi qua `urllib.parse.urlencode({...})`** — ký tự `&` thô làm cắt cụt thông báo từ điểm có `&`.

### 6.4. Lịch nhập tay Ngày + Giờ (`openCal` / `calRender` / `calApply` trong `HTML_TEMPLATE`)

* **Tự chứa, không thư viện ngoài, không gọi mạng** (đúng định hướng 100% offline): lưới tháng tiếng Việt
  bắt đầu từ **T2**, tiêu đề `Tháng N YYYY`, nút ◀ ▶ đổi tháng, hai nút nhảy nhanh
  *Tháng của kỳ …* (đọc `period` dạng `YYYY.M[.D]`) và *Hôm nay*.
* **Lịch có cả giờ**: hai ô `Giờ bắt đầu` / `Giờ kết thúc` dùng `input[type=time]` của trình duyệt; giá trị được
  chuẩn hóa về `HH:MM` (24 giờ) trước khi ghi vào bảng — trùng định dạng ô Giờ BĐ/KT và cột giờ trong Excel.
* Mở lịch ở dòng đã có ngày thì **ngày đó được chọn sẵn**; dòng 🔴 mở ở **tháng của kỳ** và chưa chọn ngày nào.
  Bấm *✅ Áp dụng* khi chưa chọn ngày sẽ bị chặn bằng thông báo — không ghi dữ liệu rỗng xuống DB.
* Bất biến khi áp dụng: chỉ ghi `date_str` / `start_time` / `end_time` và tick ☑️ Xác nhận (hành động của con
  người); **không đụng `ocr_confidence`** — dòng AI không đọc được vẫn hiển thị điểm cũ (thường là `—`), còn nhãn
  Trạng thái đổi thành *“📅 Ngày giờ do người dùng chọn”*. Không bao giờ gán điểm giả cho ngày nhập tay.
* Popover được kẹp trong viewport cả ngang lẫn dọc nên lịch không bị cắt đáy với dòng cuối bảng; đóng bằng `Esc`,
  bấm ra ngoài, hoặc *Hủy*.
* **Cạm bẫy đã gặp**: `HTML_TEMPLATE` là chuỗi Python **không phải raw-string**, nên `\'` trong JS bị Python biến
  thành `'` → lệch nháy, **chết cả khối `<script>`** (kể cả hàm `pickDate` của nút gợi ý cũ). Trong JS sinh HTML phải
  dùng `&#39;`. `test_ui_calendar.py` render template và kiểm tra parity dấu nháy đơn từng dòng JS để chặn hồi quy này.

---

## 7. Đo lường & kiểm chứng (bài học độ phủ ≠ độ chính xác)

* `bench_accuracy.py` — so kết quả AI với **ground truth do người đọc tay** (`benchmarks/ground_truth.json`), in tách bạch:
  * `EXACT` = % ô AI **tự điền đúng tuyệt đối** (đây mới là thước đo yêu cầu "AI tự đọc");
  * `TOP-N` = % ô có đáp án đúng **nằm trong gợi ý** (người dùng bấm chọn);
  * `NGÀY` = đọc đúng riêng phần ngày; `NGUY HIỂM` = điền SAI mà điểm ≥ `CONFIDENCE_MED`;
  * `GIẢ` = ô AI tự điền ngày trong khi phiếu **không ghi ngày nào** (nguồn sai hại nhất, phải bằng 0).
* ⚠️ Con số **`41/45 = 91.1%`** từng ghi ở đây là **độ phủ** do `bench_auto_read.py` (đã xóa) tính ra: nó đếm cả ô AI điền **sai**, nên thực tế 0 ngày đúng mà vẫn báo 91%. Không dùng lại kiểu đo đó.
* Số liệu đa file gần nhất (20/10/2026, **3** ground truth trong `benchmarks/ground_truth.json`):

  | Mẫu | EXACT | TOP-N | NGÀY | NGUY HIỂM | GIẢ |
  | :--- | :--- | :--- | :--- | :--- | :--- |
  | Kiểu A `Test_doc_PDF_2.pdf` (ABP0055, kỳ `2026.10.20`, 10 ô) | **10/10 = 100%** | 10/10 = 100% | 10/10 | 0 | 0 |
  | Kiểu B viết tay `CBP0005` (kỳ `2024.09.15`, 10 buổi) | **9/10 = 90%** | 10/10 = 100% | 9/10 | 0 | 0 |
  | Kiểu B ngày in đen `CBP0007` (kỳ `2024.09.15`, 12 buổi) | **12/12 = 100%** | 12/12 = 100% | 12/12 | 0 | 0 |
  | **Tổng** | **31/32 = 96.9%** | **32/32 = 100%** | 31/32 | **0** | **0** |

  Phân bổ tăng số **minh bạch** (bắt buộc báo riêng, không gộp một con số):
  * **Nhờ code**: Kiểu B viết tay `CBP0005` **5/10 → 9/10** (ensemble hai lớp tiền xử lý, mục 3); Kiểu B in đen `CBP0007` **1 buổi → 12/12** (đường đọc chữ in + thử lại ngưỡng kẻ 0.35).
  * **Nhờ đính chính ground truth** (người dùng đối chiếu nét trên ảnh phóng 6×, không phải code): 4 ô Kiểu A `Test_doc_PDF_2` 24/01→24/07, 30/01→30/07, 05/09→05/08, 26/08→06/08. Bằng chứng độc lập: sau đính chính, **cả hai cột ngày của bảng đều tăng dần** theo thứ tự buổi — GT cũ thì gãy chuỗi này.
  * Ô còn sai duy nhất: `CBP0005` ô#9. Đây **không phải lỗi nhận dạng nét** mà là lỗi **định vị**: `_blue_ink_row_runs` cắt mất chữ số `2` đầu ngày (ảnh cắt chỉ còn `4 18 / 2024`), nên `24/08` chỉ còn là phương án `confusable` trong gợi ý. Prior chuỗi buổi (DP) từng đẩy được ô này lên đúng (10/10) nhưng **đã bị người dùng chối** vì vi phạm bất biến "`confusable` không bao giờ tự điền" (mục 5).
* Chi phí thật trên CPU: init engine ~18 s, **quét 1 file Kiểu A ~60–70 s**, Kiểu B viết tay **một lớp 156 s → hai lớp 403 s**/file (`CBP0005` 9 trang), Kiểu B ngày in đen **~190 s**/file (`CBP0007` 10 trang, đo trực tiếp qua `POST /scan/`, tính cả nạp model). Một kỳ ~500 file ⇒ **10–18 giờ**, phải quét nền/từng phần.
* Kiem chứng end‑to‑end qua HTTP that (20/10/2026, server `--noreload` chay bang engine moi): `POST /scan/` file `CBP0007` → DB **12 dòng**, **12/12 ngày đúng ground truth**, **0 dòng `is_verified=1`**, diem thap nhat **0.9473**. Sau do `POST /save-all/` xac nhan tay o#5 (`05/09/2024`) roi **quet lai**: van giu `05/09/2024` + `is_verified=1` (bất biến chống mất dữ liệu đã duyệt vẫn đúng với đường đọc chữ in mới).
* Kiem chứng **lịch nhập tay** (20/10/2026) bang trinh duyet that (Chrome + CDP, khong phai render tinh):
  * `test_ui_calendar.py` → 9/9 PASS (markup + parity dau nhay JS).
  * Dong 🔴 gia lap (xoa ngay o dong #21): lich mo **dung thang cua ky** (`Tháng 10 2026`), khong co ngay chon san;
    bam *Áp dụng* khi chua chon ngay → bao *“Bạn chưa chọn ngày trên lịch.”* va khong dong; `Esc` va click ngoai deu dong lich.
  * Dong #54: doi thang ◀ → chon ngay **12** → `Giờ BĐ 07:30`, `Giờ KT 09:15` → *Áp dụng* → o Ngay `12/08/2024`,
    hai o gio duyen gia tri, ☑️ Xac nhon duoc tick, nhan Trang thai doi mau, **diem AI giu nguyen 0.9473**.
    Bam *Lưu toàn bộ* → `POST /save-all/` → SQLite: `date_str=12/08/2024`, `start_time=07:30`, `end_time=09:15`, `is_verified=1`, `ocr_confidence=0.9473`.
    (Hai dong dung trong test da duoc **hoi dung** ve gia tri AI ban dau sau khi do.)

---

## 8. Ghi chú SQLite & migration

* `pdf_documents` (1 file PDF ↔ metadata) và `intervention_sessions` (nhiều buổi ↔ 1 document, `ON DELETE CASCADE`).
* SQLite **không có** `ADD COLUMN IF NOT EXISTS` → migration phải kiểm tra `PRAGMA table_info(intervention_sessions)` trước rồi mới `ALTER TABLE` (cách cột `ocr_confidence` được thêm mà không mất dữ liệu cũ).
* File `viethealth_ocr.sqlite3` là **runtime artifact**, đã untrack — app tự tạo bảng khi khởi động.
