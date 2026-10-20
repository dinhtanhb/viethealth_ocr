# VietHealth I3b — OCR Phiếu Can Thiệp PDF (100% Offline)

Phần mềm đọc **chữ viết tay trên phiếu chấm công can thiệp** (PDF scan), tự động điền **Ngày / Giờ** vào bảng rà soát, cho phép người dùng **xác nhận hoặc sửa trước khi lưu**, rồi **xuất file Excel**.

Toàn bộ chạy **cục bộ trên máy cá nhân**: không gửi ảnh, không gọi API, không cần Internet sau khi tải model AI một lần duy nhất.

---

## 1. Điểm nổi bật

| Khả năng | Mô tả |
| :--- | :--- |
| 🤖 **Đạt mốc > 90% tự điền trên dữ liệu đo** | `bench_accuracy.py` trên **3 ground truth / 32 ngày do người đọc**: AI **tự điền đúng 31/32 = 96.9%**, đáp án đúng nằm trong gợi ý **32/32 = 100%**, **0 ngày giả**, **0 ô điền sai ở điểm cao**. Chi tiết mục 1.1. |
| 🧾 **Tự nhận dạng 3 dạng phiếu** | Engine tự phân nhánh theo hình học trang: lưới 30 ô (Kiểu A), phiếu rời viết tay mực xanh (Kiểu B), phiếu rời **ngày in đen đánh máy** (Kiểu B in sẵn). Không cần cấu hình tay. |
| 🎯 **Hai lớp tiền xử lý trên cùng một clip** | Với phiếu Kiểu B, nếu lớp tách mực xanh chưa đọc chắc chắn, engine chạy thêm lớp Grayscale/Otsu **trên đúng clip đó** rồi **gộp** phương án của hai lớp — không sinh ngày mới, không tự điền phương án đoán. |
| 👀 **Rà soát trực quan** | Ảnh cắt chữ viết tay + độ tin cậy AI + tối đa 3 phương án Ngày để bấm chọn + nhãn trạng thái 🟢🟡 trên từng dòng. |
| ✅ **Xác nhận của người dùng là duy nhất** | AI không tự đánh dấu "đã xác nhận"; quét lại PDF **không ghi đè** ngày người dùng đã duyệt. |
| 🔒 **100% Local & Offline** | PaddleOCR (CPU) + PyMuPDF + OpenCV + SQLite, không phụ thuộc Tesseract/Poppler. |

### Ba dạng phiếu được hỗ trợ

Engine `PDFGridOCREngine.process_pdf()` phân tích hình học trang cuối để tự chọn luồng:

* **Kiểu A — Bảng chấm công 30 ô** (lưới 5×6): thường gặp ở hồ sơ kỳ mới (VD `2026.10.20`). Cắt 30 ô, đọc band y **10%–37%** của mỗi ô (đo bằng row-projection mực xanh) — chữ viết tay nằm ở đó, chữ ký phụ huynh bắt đầu từ ~46% nên không bị lẫn.
* **Kiểu B — Phiếu rời từng buổi** ("Buổi N ngày DD/MM/YYYY"): thường gặp ở hồ sơ kỳ cũ (VD `2024.09.15`). Quét **tất cả các trang**, định vị ngày viết tay ở cột trái ("THỜI GIAN"), giới hạn vùng đọc đến **chính đường kẻ dọc đầu tiên của bảng** (tìm trong khoảng 5%–35% bề rộng khung; đo trên `CBP0005` là x=575 = 16%). Trang nào không có kẻ dọc trong khoảng đó là **trang văn bản in** (MỤC TIÊU / TÓM TẮT / NHẬN ĐỊNH) → bỏ qua cả trang.
  * Đường kẻ dọc bị **đứt khi scan** (`CBP0007` trang 8) không qua được ngưỡng mặc định 0.45 → engine thử lại ở ngưỡng **0.35**; đo trên `CBP0005`/`CBP0007`, ngưỡng 0.35 chỉ **thêm** đúng đường kẻ thật (±1–2 px) và **không** sinh đường kẻ giả trên trang văn bản.
  * **Ngày in đen đánh máy** (`CBP0007`): bước tách mực xanh loại chữ in theo đúng thiết kế, nên trang này không còn nét viết tay. Engine chuyển sang **đường đọc riêng cho chữ in** (`_session_band_fallback`): OCR cả dải Grayscale/Otsu và chỉ nhận detection **đúng dạng một ngày đầy đủ** `dd/mm/yyyy` (match toàn bộ chuỗi), nên `Buổi 7`, `Ngày`, `Từ ngày 1-6:` không lọt.

### 1.1. Trạng thái đo thực tế theo từng dạng phiếu (20/10/2026)

| Dạng | Mẫu đo | Tự điền đúng (EXACT) | Đúng trong gợi ý (TOP-N) | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| A — lưới 30 ô | `Test_doc_PDF_2.pdf` (ABP0055), 10 ô | **10/10 = 100%** | **10/10 = 100%** | 4/10 ô tăng là nhờ **đính chính ground truth** có người xác nhận, không phải do sửa code (xem mục 1.3) |
| B — phiếu rời, viết tay mực xanh | `CBP0005` (kỳ `2024.09.15`), 10 ngày thật | **9/10 = 90%** | **10/10 = 100%** | Tìm đủ **10/10 ô**, **0 ngày giả**, 0 ô điền sai ở điểm cao. Tăng từ 5/10 nhờ lớp Grayscale thứ hai (mục 1.2) |
| B — phiếu rời, ngày **in đen** | `CBP0007` (kỳ `2024.09.15`), 12 buổi | **12/12 = 100%** | **12/12 = 100%** | Điểm 0.95–1.00. Trước bản này chỉ trả về **1 buổi**. Đã kiểm tra lại **qua HTTP thật** vào `/scan/`: 12 dòng, 12/12 đúng, **0 dòng `is_verified=1`**, điểm thấp nhất 0.9473; lưu xác nhận tay rồi quét lại → **giữ nguyên ngày và `is_verified=1`** |
| A — lưới 30 ô | `CBP2090` (kỳ `2026.9.20`), 12 buổi | 3/12 ô có ngày | — | 1 trong 3 ngày lấy từ chữ in chân trang → đã chặn bằng luật "chữ in" |

**Tổng hợp 3 ground truth** (`bench_accuracy.py`, 20/10/2026): **EXACT 31/32 = 96.9%**, **TOP-N 32/32 = 100%**, NGÀY 31/32, **NGUY HIỂM 0**, **GIẢ 0**, +0 ô AI không phát hiện.

### 1.2. Vì sao Kiểu B viết tay tăng từ 5/10 lên 9/10 (lớp tiền xử lý thứ hai)

Bốn ngày mà lớp mực xanh đọc **sai** trên `CBP0005` (`12/8`→`02/08`, `17/8`→`19/01`, `20/8`→`20/09`, `22/8`→`02/08`) thì lớp **Grayscale/Otsu chạy trên đúng clip đó** đọc **đúng cả bốn**, với điểm cao hơn (0.89–0.999 so với 0.71–0.88). Vì vậy engine:

1. chạy lớp mực xanh như cũ;
2. chỉ chạy thêm lớp Grayscale **khi lớp xanh không đủ chắc** (không ra ngày, hoặc phương án dẫn đầu bị đánh dấu `guessed` — tức phải tách/đoán hoặc nhầm nét);
3. **gộp** danh sách phương án của hai lớp theo thứ tự *vị trí trong lớp sinh ra nó, cùng vị trí thì điểm OCR cao hơn thắng*. Không có phương án nào được sinh ra từ ngoài ảnh OCR;
4. vẫn áp dụng nguyên các cổng chặn cũ trên **lớp đã sinh ra phương án chốt** (`_is_digit_dominant`, `printed_suspect`, `_drop_lettery_dets` loại detection lẫn ≥2 chữ cái ở lớp Grayscale).

**Chi phí thật** (đo trên `CBP0005`, 9 trang, cùng máy CPU): một lớp **156.4 s** (EXACT 5/10) → hai lớp **403.2 s** (EXACT 9/10). Lớp Grayscale chỉ chạy trên các clip mà lớp xanh chưa chắc chắn (37 clip trên `CBP0005`), nên phiếu mà lớp đọc xanh đã chắc sẽ gần như không chậm thêm.

### 1.3. Ground truth và các ô còn lại

* Ảnh bằng chứng từng ngày do người đọc: `benchmarks/evidence/` (Kiểu B `CBP0005`, `CBP0007`; Kiểu A `Test_doc_PDF_2_kieu_a_truth_3x.jpg` và các ảnh so sánh nét `so_sanh_net_*.jpg`).
* **Bốn ô Kiểu A đã được đính chính** (24/01→24/07, 30/01→30/07, 05/09→05/08, 26/08→06/08) sau khi người dùng đối chiếu nét viết tay trên ảnh phóng 6×. Số mới còn được xác nhận độc lập: sau đính chính, **cả hai cột ngày của bảng đều tăng dần đúng theo thứ tự buổi** (24/07, 30/07, 31/07, 05/08, 06/08 | 10/08…24/08) — ground truth cũ thì gãy chuỗi này. Đây là **sửa số đo, không phải sửa code**.
* **Ô còn sai duy nhất**: `CBP0005` ô#9. Bước cắt dải theo dòng (`_blue_ink_row_runs`) **cắt mất chữ số `2` đầu ngày**, ảnh cắt thực tế chỉ còn `4 18 / 2024` nên lớp nào cũng chỉ đọc ra 04/08; đáp án đúng `24/08` tồn tại dưới dạng phương án `confusable` trong gợi ý. Nới lề trái cụm cắt từng được thử và **làm hỏng các ô khác** → không dùng.
* **Bất biến được giữ** (theo yêu cầu của người dùng): phương án `confusable` (nhầm nét 1↔7, 8↔9, 0↔2) **không bao giờ được tự điền**, kể cả khi dùng prior "các buổi tăng dần theo thứ tự" để đẩy nó lên. Nên `24/08` vẫn chỉ là gợi ý.

Bốn lỗi định vị đã sửa trong đợt đo Kiểu B này:

1. **Lọc cụm theo tâm dải** → cắt theo **giao số** với cột ngày. Dải chứa cả "Ngày 5/8" lẫn cột ghi chú có tâm nằm ngoài ngưỡng từng bị bỏ nguyên dòng (mất 2 ngày ở trang 4 `CBP0005`).
2. **Giới hạn cột bằng đường kẻ dọc thật** của bảng thay vì 35% bề rộng: loại được mã số "PN-101031" và cột ghi chú — hai nguồn ngày giả đã đo được.
3. **Cổng cấp trang** (`_session_column_divider(...) is None` → bỏ trang): trang MỤC TIÊU in sẵn "Từ ngày 1-6:", "Từ ngày 7-15:" từng bị đọc thành `10/07/2024` (ngày giả).
4. **Nét sổ dính vào đầu hoặc cuối cụm số**: `27/8/2024` → `12718121`, `20/8/2024` → `2018120441`. Chỉ bỏ đúng **một** ký tự `1` và chỉ thử sau khi mẫu chuẩn đã thất bại, nên không đổi cách đọc các cụm đang đúng.

Tốc độ đo được (CPU, cùng máy): ~60–90s/file Kiểu A sau khi chặn `MAX_OCR_SIDE=1100px` (trước đây 55s/**ô** với bản scan 12MB); Kiểu B viết tay một lớp **156 s**/file, hai lớp **403 s**/file (`CBP0005` 9 trang); Kiểu B ngày in đen **~190 s**/file (`CBP0007` 10 trang, tính cả ~18 s nạp model — đo trực tiếp qua HTTP `POST /scan/`). Một kỳ 504 file ≈ **10–18 giờ** chạy một lần trên CPU (tăng so với 8–12 giờ trước đây vì Kiểu B viết tay đã chạy thêm lớp OCR thứ hai).

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
├── benchmarks/
│   ├── ground_truth.json     # Ngày do NGƯỜI đọc tay - thước đo cho bench_accuracy
│   └── evidence/             # Ảnh cắt bằng chứng cho từng dòng ground truth Kiểu B
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

* **Tách mực xanh:** lọc `b−r > 20 && b > 45` để cô lập chữ viết tay khỏi chữ in đen. Khi lớp xanh đọc không chắc trên phiếu Kiểu B, engine chạy thêm **lớp Grayscale/Otsu trên cùng một clip** (`_grayscale_fallback` + `_read_session_clip`) rồi gộp phương án — hai lớp chỉ khác nhau cách **tách ảnh**, không có ngày nào được sinh thêm.
* **Phương án gợi ý:** mọi cặp (Ngày, Tháng) phải đọc được từ ảnh (`separator`/`adjacent`), hoặc được tách
  ra từ cụm số dính (`split`/`prefix`). Ngoài cùng là các phương án **nhầm nét chữ số** (`confusable`: 1↔7, 8↔9,
  0↔2) – chỉ để người dùng bấm, **không bao giờ được tự điền** kể cả khi prior "buổi tăng dần" ủng hộ nó.
* **Năm chỉ lấy theo thư mục kỳ** khi ảnh OCR không đọc ra năm, và luôn kèm cảnh báo; Tháng **không** lấy từ kỳ.
* **Paddle trên CPU bắt buộc `enable_mkldnn=False`**, nếu không crash `ConvertPirAttribute2RuntimeAttribute`.
* **Migration an toàn:** `local_db` tự `ALTER TABLE` thêm cột mới (VD `ocr_confidence`) mà không mất dữ liệu cũ.
* **Unicode trên Windows:** đường dẫn tiếng Việt nên lấy qua `os.walk`; chạy Python với `-X utf8`.
