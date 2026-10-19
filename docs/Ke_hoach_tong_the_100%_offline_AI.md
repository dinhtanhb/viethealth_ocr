# KẾ HOẠCH TỔNG THỂ XÂY DỰNG HỆ THỐNG "NHẬP LIỆU CAN THIỆP" (LÀM MỚI TỪ A-Z | 100% OFFLINE AI)

## 1. Mục Tiêu Cốt Lõi & Triết Lý Thiết Kế Mới
1. **Bảo mật tuyệt đối (100% Local & Offline):** Toàn bộ quá trình đọc PDF, AI nhận diện chữ viết tay, đối chiếu dữ liệu và xuất Excel đều diễn ra **bên trong máy tính cá nhân của bạn**, tuyệt đối không gửi bất kỳ hình ảnh hay dữ liệu nhạy cảm nào ra ngoài Internet.
2. **Không phụ thuộc phần mềm ngoài (Zero External Software):** Loại bỏ hoàn toàn Tesseract `.exe` và Poppler. Bạn chỉ cần Python và chạy `pip install -r requirements.txt` là hệ thống hoạt động 100%.
3. **Tự động hóa tối đa & Soát lỗi siêu tốc:**
   * Tự động lấy 100% thông tin hành chính (`Mã Trẻ`, `Tên Trẻ`, `Mã CB`, `Tên CB`, `Dịch Vụ`, `Nhóm`) từ cấu trúc thư mục OneDrive.
   * Tự động trích xuất **trang cuối cùng** của file PDF, cắt 30 ô chấm công, dùng AI đọc **Ngày, Giờ bắt đầu, Giờ kết thúc** viết tay.
   * Tự động điền vào giao diện kiểm duyệt kèm hình ảnh cắt thực tế (Snippet Review) và xuất thẳng vào file Excel của kỳ.

---

## 2. Bộ Công Cụ & Model AI Offline Được Lựa Chọn

| Thành phần | Thư viện / Model sử dụng | Lý do lựa chọn (Ưu điểm vượt trội) |
| :--- | :--- | :--- |
| **1. Đọc & Chuyển PDF sang Ảnh** | **`PyMuPDF` (`fitz`)** | Cài đặt 100% qua `pip`, không cần Poppler. Tốc độ lấy trang cuối PDF (`doc[-1]`) ở độ phân giải 300 DPI chỉ mất **0.1 giây/file**. |
| **2. Xử lý ảnh & Cắt 30 Ô** | **`OpenCV` (`cv2`)** | Tự động tìm khung bảng 30 ô (5 hàng x 6 cột), chỉ cắt **35% phần đỉnh của mỗi ô** (nơi viết Ngày & Giờ) để loại bỏ hoàn toàn chữ ký phụ huynh đè ở dưới. |
| **3. Model AI Đọc Chữ Viết Tay** | **`EasyOCR` (Local PyTorch)** | Sử dụng 2 model Deep Learning chạy Offline trên CPU/GPU: `craft_mlt_25k.pth` (phát hiện vùng chữ) + `english_g2.pth` (nhận diện nét chữ viết tay). Ép khuôn `allowlist="0123456789/.-:h "` giúp đọc số viết tay cực nhạy. Model lưu tại `models_storage/easyocr/`. |
| **4. Bộ lọc Chuẩn hóa Thời gian** | **`Rule-based Regex Engine`** | Tự động sửa lỗi chữ viết tay dễ nhầm (`O`->`0`, `l/I`->`1`, `S`->`5`, `B`->`8`) và chuẩn hóa mọi kiểu viết (`9h-10h`, `14h30-15h30`, `22/8/2026`) về chuẩn Excel `DD/MM/YYYY` và `HH:MM`. |
| **5. Xử lý Excel & Lưu lịch sử** | **`OpenPyXL` + `SQLite3`** | Đọc Sheet Phân công, kiểm tra trùng lịch, lưu vết các buổi đã nhập ở đợt trước và ghi trực tiếp vào Sheet Chấm công của file Excel kỳ. |
| **6. Giao diện Người dùng (UI)** | **`Django` (Local Web UI)** | Giao diện trực quan mở ngay trên trình duyệt máy cá nhân (hoặc chia sẻ qua mạng LAN nội bộ), hỗ trợ vừa nhìn ảnh cắt vừa bấm phím duyệt siêu tốc. |

---

## 3. Cấu Trúc Thư Mục Dự Án Mới (Tinh Gọn & Sạch Sẽ)

Thay vì chia quá nhiều thư mục con phức tạp, dự án mới (`viethealth_ocr`) được tổ chức cực kỳ gọn gàng, dễ quản lý:

```text
viethealth_ocr/                     # THƯ MỤC GỐC DỰ ÁN (trạng thái đã xây xong)
│
├── venv/                           # Môi trường ảo Python
├── models_storage/easyocr/         # Model AI offline (.pth) - NƠI APP ĐỌC MODEL (gitignored)
├── media_snippets/                 # Ảnh cắt chữ viết tay phục vụ giao diện rà soát (gitignored)
│
├── core_engine/                    # BỘ XỬ LÝ LÕI (Độc lập, không import Django)
│   ├── path_parser.py              # 1. Bóc tách metadata (kỳ/nhóm/CB/trẻ/dịch vụ) từ đường dẫn OneDrive
│   ├── pdf_grid_ocr.py             # 2. PyMuPDF + OpenCV + EasyOCR: phân tích hình học, 2 luồng Kiểu A/Kiểu B, chuẩn hóa Ngày/Giờ
│   ├── local_db.py                 # 3. SQLite: documents + sessions, migration an toàn, bảo toàn dữ liệu đã xác nhận
│   ├── excel_exporter.py           # 4. Xuất báo cáo .xlsx
│   └── batch_scanner.py            # 5. Quét đệ quy thư mục PDF theo callback (API bổ trợ)
│
├── web_app.py                      # GIAO DIỆN: Django single-file (settings in-process + HTML template inline)
├── docs/                           # Tài liệu thiết kế & kế hoạch
├── requirements.txt                # Danh sách thư viện cài đặt 1-click
├── setup_offline_models.py         # Script tải & đóng gói Model AI vào models_storage/easyocr/
├── test_step1_ocr.py               # Smoke test đọc 1 file PDF thực tế (truyền đường dẫn qua CLI)
└── bench_auto_read.py              # Đo tỷ lệ AI tự đọc Ngày trên dữ liệu thật (mục tiêu > 90%)
```

> 📌 **Cập nhật so với kế hoạch ban đầu:** `excel_handler.py` → `excel_exporter.py`; thư mục `web_app/` → một file `web_app.py` duy nhất; model lưu ở `models_storage/easyocr/` thay vì `local_models/`; `latin_g2.pth` → `english_g2.pth`. See [`AGENTS.md`](../AGENTS.md) for quy ước chi tiết.

---

## 4. Lộ Trình Xây Dựng Từ Đầu (4 Bước Rõ Ràng)

* **BƯỚC 1 (Ngay bây giờ): Khởi tạo dự án mới & Cài đặt Core AI Offline**
  * Tạo thư mục dự án mới hoàn toàn.
  * Cài đặt `PyMuPDF`, `OpenCV`, `EasyOCR`, `OpenPyXL`.
  * Chạy `setup_offline_models.py` để lưu Model AI về `models_storage/easyocr/` để từ sau chạy 100% không cần mạng.
* **BƯỚC 2: Chạy thử nghiệm Đọc File PDF Thực Tế (`pdf_grid_ocr.py`)**
  * Đưa 1 đường dẫn file PDF bất kỳ từ OneDrive của bạn vào (`test_step1_ocr.py <duong-dan>`).
  * Hệ thống tự phân tích hình học trang, cắt vùng chữ viết tay ra `media_snippets/` để bạn nhìn tận mắt ảnh cắt và kiểm tra kết quả AI đọc Ngày/Giờ.
  * ⚠️ **Phát hiện thực tế:** hồ sơ có **HAI kiểu phiếu** — Kiểu A (lưới 30 ô ở trang cuối) và Kiểu B (phiếu rời từng buổi, rải trên nhiều trang). Engine phải tự branch, không giả định chỉ có lưới 30 ô.
* **BƯỚC 3: Kết nối File Excel Kỳ (`excel_exporter.py`)**
  * Đọc danh sách phân công từ file Excel thực tế của bạn, đối chiếu dữ liệu AI vừa đọc được, lọc trùng và ghi thử vào Excel.
* **BƯỚC 4: Dựng Giao Diện Kiểm Duyệt Nhanh (UI) & Đóng Gói 1-Click**
  * Xây dựng màn hình chọn thư mục OneDrive, chọn file Excel, hiển thị bảng đối chiếu Ảnh cắt $\leftrightarrow$ Ô nhập liệu (Xanh / Vàng / Đỏ) và nút **Lưu vào Excel**.

---

## 5. Hướng Dẫn Thực Hiện BƯỚC 1 (Làm Từng Lệnh Từ Đầu)

### 5.1. Tạo thư mục mới và mở trong VSCode
1. Đóng dự án cũ lại. Mở **PowerShell** hoặc **Command Prompt** trên máy tính của bạn.
2. Chạy các lệnh sau để tạo một thư mục hoàn toàn mới tại ổ `D:\` (hoặc ổ đĩa bạn muốn):
   ```powershell
   D:
   mkdir D:\viethealth_ocr
   cd D:\viethealth_ocr
   code .
   ```

### 5.2. Tạo môi trường ảo (Virtual Environment) trong VSCode
Mở Terminal trong VSCode (`Ctrl + ~`) và chạy:
```powershell
python -m venv venv
.\venv\Scripts\activate
```
*(Đầu dòng lệnh xuất hiện chữ `(venv)` màu xanh là thành công).*

### 5.3. Tạo các file mã nguồn nền tảng
Bạn hãy tạo thư mục `core_engine` và copy các file dưới đây vào dự án:
```powershell
mkdir core_engine
mkdir models_storage\easyocr
mkdir media_snippets
```