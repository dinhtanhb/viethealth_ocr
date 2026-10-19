# VietHealth I3b — OCR Phiếu Can Thiệp PDF (100% Offline)

Phần mềm đọc **chữ viết tay trên phiếu chấm công can thiệp** (PDF scan), tự động điền **Ngày / Giờ** vào bảng rà soát, cho phép người dùng **xác nhận hoặc sửa trước khi lưu**, rồi **xuất file Excel**.

Toàn bộ chạy **cục bộ trên máy cá nhân**: không gửi ảnh, không gọi API, không cần Internet sau khi tải model AI một lần duy nhất.

---

## 1. Điểm nổi bật

| Khả năng | Mô tả |
| :--- | :--- |
| 🤖 **AI đọc > 90% ngày viết tay** | Benchmark trên dữ liệu thật: **41/45 ngày = 91.1%** tự đọc & điền. |
| 🧾 **Tự nhận dạng 2 kiểu phiếu** | Engine tự phân nhánh theo hình học trang, không cần cấu hình tay. |
| 👀 **Rà soát trực quan** | Ảnh cắt chữ viết tay + độ tin cậy AI + nhãn trạng thái 🟢🟡 trên từng dòng. |
| ✅ **Xác nhận của người dùng là duy nhất** | AI không tự đánh dấu "đã xác nhận"; quét lại PDF **không ghi đè** ngày người dùng đã duyệt. |
| 🔒 **100% Local & Offline** | EasyOCR (CPU) + PyMuPDF + OpenCV + SQLite, không phụ thuộc Tesseract/Poppler. |

### Hai kiểu phiếu được hỗ trợ

Engine `PDFGridOCREngine.process_pdf()` phân tích hình học trang cuối để tự chọn luồng:

* **Kiểu A — Bảng chấm công 30 ô** (lưới 5×6): thường gặp ở hồ sơ kỳ mới (VD `2026.10.20`). Cắt 30 ô, đọc 35% phần đỉnh mỗi ô để tránh chữ ký phụ huynh đè bên dưới.
* **Kiểu B — Phiếu rời từng buổi** ("Buổi N ngày DD/MM/YYYY"): thường gặp ở hồ sơ kỳ cũ (VD `2024.09.15`). Quét **tất cả các trang**, định vị ngày viết tay ở cột trái ("THỜI GIAN"), giới hạn vùng đọc trong 35% bề rộng bảng để loại trừ chữ ký.

---

## 2. Công nghệ

| Thành phần | Thư viện |
| :--- | :--- |
| Đọc PDF → ảnh (300 DPI) | `PyMuPDF` (`fitz`) |
| Xử lý ảnh, dò khung bảng, tách mực xanh | `OpenCV` + `numpy` |
| AI nhận diện chữ viết tay (offline, CPU) | `EasyOCR` — `craft_mlt_25k.pth` + `english_g2.pth` |
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

# 3. Tải model AI về máy (CHỈ lần đầu cần Internet, ~98 MB)
python setup_offline_models.py
```

Model được lưu tại `models_storage/easyocr/`. Sau bước này ứng dụng chạy hoàn toàn offline.

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
   | 🟢 AI tự đọc chắc chắn | `>= 0.45` | Có thể duyệt nhanh |
   | 🟡 Tin cậy thấp – cần soát | `0.30 – 0.45` | Đối chiếu ảnh trước khi tin |
   | 🔴 Chưa đọc được – nhập tay | `< 0.30` hoặc trống | Vui lòng nhập tay |

4. **Sửa** Ngày/Giờ nếu cần, **tích ☑️ Xác nhận** cho dòng đã đối chiếu.
5. Bấm **💾 Lưu toàn bộ thay đổi**, rồi **📥 Xuất File Excel (.xlsx)**.

> ⚠️ Ngày do AI *suy đoán* (thiếu tháng/năm, phải lấy theo kỳ thư mục) luôn bị hạ tin cậy xuống dưới ngưỡng 🟡 để bắt buộc người dùng soát lại.

### Đo độ chính xác tự động

```powershell
.\venv\Scripts\python.exe bench_auto_read.py "<đường dẫn thư mục hoặc file PDF>" [so_file_toi_da]
```

In tỷ lệ AI tự đọc được trên từng file và tổng, kèm cờ ✅ khi đạt > 90%.

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
│   ├── excel_exporter.py       # Xuất báo cáo .xlsx
│   └── batch_scanner.py        # Quét đệ quy thư mục PDF theo callback (API bổ trợ)
├── docs/                       # Tài liệu thiết kế & kế hoạch
├── bench_auto_read.py          # Đo tỷ lệ AI tự đọc ngày trên dữ liệu thật
├── test_step1_ocr.py           # Smoke test 1 file PDF
├── setup_offline_models.py     # Tải & đóng gói model EasyOCR
├── requirements.txt
│
├── models_storage/easyocr/     # [runtime, gitignored] Model AI .pth
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
* **Sửa lỗi mặt chữ:** bản đồ ký tự dễ nhầm (`O→0`, `l/I→1`, `S→5`, `B→8`…).
* **Suy đoán theo kỳ thư mục:** folder dạng `2026.10.20` cung cấp năm/tháng làm "prior" để cứu ngày bị thiếu nét.
* **Migration an toàn:** `local_db` tự `ALTER TABLE` thêm cột mới (VD `ocr_confidence`) mà không mất dữ liệu cũ.
* **Unicode trên Windows:** đường dẫn tiếng Việt nên lấy qua `os.walk`; chạy Python với `-X utf8`.
