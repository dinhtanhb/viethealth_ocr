# VietHealth I3b — OCR Phiếu Can Thiệp PDF (100% Offline)

Phần mềm đọc **chữ viết tay trên phiếu chấm công can thiệp** (PDF scan), tự động điền **Ngày / Giờ** vào bảng rà soát, cho phép người dùng **xác nhận hoặc sửa trước khi lưu**, rồi **xuất file Excel**.

Toàn bộ chạy **cục bộ trên máy cá nhân**: không gửi ảnh, không gọi API, không cần Internet sau khi tải model AI một lần duy nhất.

---

## 1. Điểm nổi bật

| Khả năng | Mô tả |
| :--- | :--- |
| 🤖 **Kiểu A: AI tự điền đúng 60%, gợi ý đúng 100%** | Benchmark đối chiếu người đọc trên `Test_doc_PDF_2.pdf` (10 ô có ngày viết tay): AI tự điền đúng **6/10**; đáp án đúng nằm trong 3 phương án gợi ý **10/10** → người dùng chỉ bấm chọn, không phải gõ lại. |
| ⚠️ **Kiểu B: chưa đạt** | Đo trên `CBP0005` (kỳ `2024.09.15`): tìm được **2/4** ngày thật, cả 2 đều cần người bấm chọn thêm. Chi tiết ở mục 1.1. |
| 🧾 **Tự nhận dạng 2 kiểu phiếu** | Engine tự phân nhánh theo hình học trang, không cần cấu hình tay. |
| 👀 **Rà soát trực quan** | Ảnh cắt chữ viết tay + độ tin cậy AI + tối đa 3 phương án Ngày để bấm chọn + nhãn trạng thái 🟢🟡 trên từng dòng. |
| ✅ **Xác nhận của người dùng là duy nhất** | AI không tự đánh dấu "đã xác nhận"; quét lại PDF **không ghi đè** ngày người dùng đã duyệt. |
| 🔒 **100% Local & Offline** | PaddleOCR (CPU) + PyMuPDF + OpenCV + SQLite, không phụ thuộc Tesseract/Poppler. |

### Hai kiểu phiếu được hỗ trợ

Engine `PDFGridOCREngine.process_pdf()` phân tích hình học trang cuối để tự chọn luồng:

* **Kiểu A — Bảng chấm công 30 ô** (lưới 5×6): thường gặp ở hồ sơ kỳ mới (VD `2026.10.20`). Cắt 30 ô, đọc band y **10%–37%** của mỗi ô (đo bằng row-projection mực xanh) — chữ viết tay nằm ở đó, chữ ký phụ huynh bắt đầu từ ~46% nên không bị lẫn.
* **Kiểu B — Phiếu rời từng buổi** ("Buổi N ngày DD/MM/YYYY"): thường gặp ở hồ sơ kỳ cũ (VD `2024.09.15`). Quét **tất cả các trang**, định vị ngày viết tay ở cột trái ("THỜI GIAN"), giới hạn vùng đọc trong 35% bề rộng bảng (hoặc 32% bề rộng trang khi không nhận dạng được khung bảng) để loại trừ chữ ký.

### 1.1. Trạng thái đo thực tế theo từng kiểu (20/10/2026)

| Kiểu | Mẫu đo | Tự điền đúng (EXACT) | Đúng trong gợi ý (TOP-N) | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| A — lưới 30 ô | `Test_doc_PDF_2.pdf` (ABP0055), 10 ô | **6/10 = 60%** | **10/10 = 100%** | Đã có ground truth trong `benchmarks/` |
| A — lưới 30 ô | `CBP2090` (kỳ `2026.9.20`), 12 buổi | 3/12 ô có ngày | — | 1 trong 3 ngày lấy từ chữ in chân trang → đã chặn bằng luật "chữ in" |
| B — phiếu rời | `CBP0005` (kỳ `2024.09.15`), ≥4 ngày thật | **0/4** | **2/4** (`10/8` đúng, `22/8` ra `02/8`) | 2 ngày ở trang 4 **không được phát hiện** |

Nguyên nhân còn lại ở Kiểu B (chưa sửa):

1. **Ngày nhỏ, sát nhau bị gom thành một cụm** — row-projection với khe 45px gộp "Buổi 1 / 5/8" và "Buổi 2 / 7/8" thành dải mực cao ~700px, gộp cả chữ in → cụm vượt `right_limit` hoặc không tách được ngày.
2. **Nét gạch chéo viết tay bị đọc thành chữ số `1`** — `22/8/2024` → `21812029`; đã có luật nhận diện `(Ngày)1(Tháng)1` cho đa số trường hợp nhưng vẫn mất chữ số đầu khi nét viết liền.
3. **Nhánh phân phối `geo is None` hiện rơi vào Kiểu A** — `process_pdf()` render *trang cuối* để đo hình học; trang không có khung bảng bị coi là lưới 30 ô.

Tốc độ đo được: ~60–90s/file sau khi chặn `MAX_OCR_SIDE=1100px` (trước đây 55s/**ô** với bản scan 12MB). Một kỳ 504 file ≈ 8–10 giờ chạy một lần trên CPU.

---

## 2. Công nghệ

| Thành phần | Thư viện |
| :--- | :--- |
| Đọc PDF → ảnh (300 DPI) | `PyMuPDF` (`fitz`) |
| Xử lý ảnh, dò khung bảng, tách mực xanh | `OpenCV` + `numpy` |
| AI nhận diện chữ viết tay (offline, CPU) | `PaddleOCR` 3.7 (PP-OCRv6 det+rec) trên `paddlepaddle` 3.3 |
| Chuẩn hóa Ngày/Giờ, sửa lỗi mặt chữ | Regex rule-based engine |
| Lưu trữ lịch sử | `SQLite3` |
| Xuất báo cáo | `pandas` + `OpenPyXL` |
| Giao diện web cục bộ | `Django` |

---

## 3. Cài đặt

```powershell
cd D:\viethealth_ocr

# 1. Tạo và kích hoạt môi trường ảo
python -m venv venv
.\venv\Scripts\activate

# 2. Cài thư viện
pip install -r requirements.txt

# 3. Tải model AI về máy (CHỈ lần đầu cần Internet)
python setup_offline_models.py
```

Model được lưu tại `models_storage/paddlex/`. Sau bước này ứng dụng chạy hoàn toàn offline.

---

## 4. Sử dụng

### Chạy giao diện web

```powershell
.\venv\Scripts\python.exe web_app.py runserver 127.0.0.1:8031 --noreload
```

Mở trình duyệt: <http://127.0.0.1:8031/>

### Quy trình rà soát

1. Dán **đường dẫn 1 file PDF** hoặc **cả thư mục kỳ OneDrive** vào ô "Quét".
2. Bấm **🔍 Quét AI OCR** — AI bóc tách metadata từ đường dẫn và tự điền Ngày/Giờ.
3. Bảng kết quả hiện **ảnh cắt chữ viết tay** (rê chuột phóng to 2.4×), **độ tin cậy AI** và **nhãn trạng thái**:

   | Nhãn | Ngưỡng tin cậy | Ý nghĩa |
   | :--- | :--- | :--- |
   | 🟢 AI tự đọc chắc chắn | `>= 0.60` | Có thể duyệt nhanh |
   | 🟡 Tin cậy thấp – cần soát | `0.40 – 0.60` | Đối chiếu ảnh trước khi tin |
   | 🔴 Chưa đọc được – nhập tay | `< 0.40` hoặc trống | Vui lòng nhập tay |

4. Nếu AI đọc ra nhiều phương án, bảng hiện các **nút gợi ý** dưới ô Ngày: bấm chọn phương án đúng
   (nút nét đứt có dấu `?` là phương án **dự phòng do khả năng nhầm nét chữ số** – chỉ bấm khi ảnh cắt rõ là số đó).
   Bấm chọn đồng nghĩa đã đối chiếu nên ô **☑️ Xác nhận** được tick sẵn.
5. **Sửa** Ngày/Giờ nếu cần, **tích ☑️ Xác nhận** cho dòng đã đối chiếu.
6. Bấm **💾 Lưu toàn bộ thay đổi**, rồi **📥 Xuất File Excel (.xlsx)**.

> ⚠️ AI **không còn bịa ngày**: không mượn tháng từ tên thư mục kỳ, không ghép bừa hai cụm số bất kỳ,
> độ tin cậy chỉ tính trên cụm số (không tính chữ ký). Ngày phải *tách/đoán* từ cụm số dính nhau luôn bị
> hạ dưới ngưỡng 🟡 để bắt buộc người dùng soát lại.

### Đo độ chính xác thật (không phải độ phủ)

```powershell
.\venv\Scripts\python.exe -X utf8 bench_accuracy.py            # moi file trong benchmarks/ground_truth.json
.\venv\Scripts\python.exe -X utf8 bench_accuracy.py --only "<path PDF>"
```

So kết quả AI với **ground truth do người đọc tay** (`benchmarks/ground_truth.json`) và in hai chỉ số tách bạch:

* `EXACT` – % ô AI **tự điền đúng tuyệt đối** (người dùng không phải làm gì);
* `TOP-N` – % ô có **đáp án đúng nằm trong gợi ý** (người dùng bấm chọn);
* `NGÀY` – đọc đúng riêng phần ngày; `NGUY HIỂM` – ô điền SAI mà điểm ≥ `CONFIDENCE_MED` (dễ bị bỏ qua nhất).

### Kiểm thử nhanh core engine

```powershell
.\venv\Scripts\python.exe test_step1_ocr.py "<duong-dan-file-PDF>"
```

---

## 5. Cấu trúc dự án

```text
viethealth_ocr/
├── web_app.py                  # Django app 1-file: routes + inline HTML template + views
├── core_engine/
│   ├── path_parser.py          # Bóc tách metadata (kỳ/nhóm/CB/trẻ/dịch vụ) từ đường dẫn OneDrive
│   ├── pdf_grid_ocr.py         # Lõi OCR: phân tích hình học, 2 luồng Kiểu A / Kiểu B, chuẩn hóa ngày giờ
│   ├── local_db.py             # SQLite: documents + sessions, migration, bảo toàn dữ liệu đã xác nhận
│   └── excel_exporter.py       # Xuất báo cáo .xlsx
├── docs/                       # Tài liệu thiết kế & kế hoạch
├── benchmarks/ground_truth.json # Ngày do NGƯỜI đọc tay - thước đo cho bench_accuracy
├── bench_accuracy.py           # Đo ĐỘ CHÍNH XÁC (EXACT / TOP-N) so với ground truth
├── test_step1_ocr.py           # Smoke test 1 file PDF
├── setup_offline_models.py     # Tải & đóng gói model PaddleOCR
├── requirements.txt
│
├── models_storage/paddlex/     # [runtime, gitignored] Model AI PaddleOCR
├── media_snippets/             # [runtime, gitignored] Ảnh cắt chữ viết tay
└── viethealth_ocr.sqlite3      # [runtime, gitignored] Cơ sở dữ liệu kết quả
```

## 6. API / Routes

| Method | Đường dẫn | Chức năng |
| :--- | :--- | :--- |
| GET | `/` | Dashboard bảng rà soát (`?msg=`, `?path=`) |
| POST | `/scan/` | Quét file/thư mục PDF → lưu kết quả AI |
| POST | `/save-all/` | Lưu Ngày/Giờ + trạng thái xác nhận của người dùng |
| GET | `/export-excel/` | Tải file báo cáo `.xlsx` |
| GET | `/snippet/<filename>` | Ảnh cắt chữ viết tay của một ô/buổi |

## 7. Ghi chú kỹ thuật

* **Tách mực xanh:** lọc `b−r > 20 && b > 45` để cô lập chữ viết tay khỏi chữ in đen, kèm fallback Otsu grayscale.
* **Phương án gợi ý:** mọi cặp (Ngày, Tháng) phải đọc được từ ảnh (`separator`/`adjacent`), hoặc được tách
  ra từ cụm số dính (`split`/`prefix`). Ngoài cùng là các phương án **nhầm nét chữ số** (`confusable`: 1↔7, 8↔9,
  0↔2) – chỉ để người dùng bấm, không bao giờ được tự điền.
* **Năm chỉ lấy theo thư mục kỳ** khi ảnh OCR không đọc ra năm, và luôn kèm cảnh báo; Tháng **không** lấy từ kỳ.
* **Paddle trên CPU bắt buộc `enable_mkldnn=False`**, nếu không crash `ConvertPirAttribute2RuntimeAttribute`.
* **Migration an toàn:** `local_db` tự `ALTER TABLE` thêm cột mới (VD `ocr_confidence`) mà không mất dữ liệu cũ.
* **Unicode trên Windows:** đường dẫn tiếng Việt nên lấy qua `os.walk`; chạy Python với `-X utf8`.
