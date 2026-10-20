import os
import re
import warnings
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import cv2
import numpy as np

try:
    import pymupdf as fitz
except ImportError:
    import fitz

# PaddleOCR duoc import tre (lazy) ben trong __init__ SAU khi da tro thu muc model
# ve models_storage/paddlex de chay 100% offline va cam theo thu muc project.


class PDFGridOCREngine:
    """
    Bộ lõi xử lý trang cuối PDF Bảng Chấm Công (Offline 100%):
    - Tự động bắt khung bảng 30 ô (5 hàng x 6 cột)
    - ROI dòng Ngày lấy đúng band mực viết tay (y 10%-37% của ô) - đo bằng row-projection
    - Lọc tách riêng mực bút xanh sang Grayscale mềm mại cho OCR
    - Engine: PaddleOCR PP-OCRv6 (CPU, offline) - do bang chinh xac hon EasyOCR tren chu viet tay nay
    - KHONG bao gio bia ngay: chi chap nhan cap (Ngay, Thang) hop le thu duoc tu chuoi OCR;
      moi phuong an khac deu tra ve dang "goi y" de nguoi dung bam chon.
    """

    # Ngưỡng phân loại độ tin cậy trên UI
    CONFIDENCE_HIGH = 0.60   # PaddleOCR cho điểm thật (0..1), khong cong gop nhu EasyOCR cu
    CONFIDENCE_MED = 0.40    # Thấp hơn mức này: UI bắt buộc người dùng soát

    # Band tọa độ tính theo tỷ lệ chiều cao/chiều rộng của MỘT Ô trong lưới 30 ô.
    # Do thuc te tren Test_doc_PDF_2.pdf: chu viet tay ngay nam o 0.10-0.35 cua o,
    # chu ky xanh bat dau tu ~0.46 (tuyen doi khong duoc de no nhiem vao ROI).
    DATE_BAND_Y = (0.10, 0.37)
    DATE_BAND_Y_ALT = (0.07, 0.42)   # Lưu phái cho ô viết lệch dòng
    DATE_BAND_X = (0.02, 0.98)
    SNIPPET_BAND_Y = (0.05, 0.44)    # Ảnh cắt cho người dùng đối chiếu

    # Năm/Tháng phải là số hợp lệ; ứng viên vi phạm bị loại outright
    MAX_DAY = 31
    MAX_MONTH = 12

    # Tran kich thuoc anh dua vao OCR. PaddleOCR tu no thu nho trong nuoc
    # (limit_side_len ~960), nen minh thu nho truoc thi buoc detect chay nhanh
    # hon rat nhieu ma khong mat net: bang scan 12 MB o 300 DPI co the sinh
    # vung 2000x1200 px -> mat ~55s/o (thay vi ~7s/o nhu bang thuong).
    MAX_OCR_SIDE = 1100

    # Cac so viet tay de nham lan nhau (buoc thu nhat la pair DA QUANSAT tren
    # Test_doc_PDF_2.pdf: '1'<->'7' (o 1, 7), '8'<->'9' (o 19), '2'<->'0' (o 25)).
    # Thu tu trong chuoi QUYET DINH thuong uu tien: chi dung de sap xep goi y,
    # khong dung de tu dong dien vao o.
    CONFUSABLE_DIGITS = {
        "0": "26",
        "1": "7",
        "2": "07",
        "3": "58",
        "4": "",
        "5": "38",
        "6": "05",
        "7": "12",
        "8": "936",
        "9": "8",
    }

    def __init__(self, models_dir: str = "models_storage/paddlex", snippets_dir: str = "media_snippets"):
        self.models_dir = models_dir
        self.snippets_dir = snippets_dir
        os.makedirs(self.models_dir, exist_ok=True)
        os.makedirs(self.snippets_dir, exist_ok=True)

        # Tro model ve thu muc cua project (mac dinh ~/.paddlex) va bo kiem tra ket mang
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", os.path.abspath(self.models_dir))
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

        from paddleocr import PaddleOCR

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # enable_mkldnn=False: BAT BUOC tren PaddlePaddle 3.x CPU, neu khong loi
            # "ConvertPirAttribute2RuntimeAttribute not support" khi chay buoc detect.
            self.reader = PaddleOCR(
                lang="en",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=False,
            )

    def render_last_page(self, pdf_path: str, dpi: int = 300) -> np.ndarray:
        """Đọc file PDF an toàn (try/finally) và trích xuất trang cuối cùng thành ảnh BGR 300 DPI."""
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Không tìm thấy file PDF: {pdf_path}")

        doc = fitz.open(pdf_path)
        try:
            if len(doc) == 0:
                raise ValueError("File PDF rỗng.")

            last_page = doc[-1]
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = last_page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)

            img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            return img_bgr
        finally:
            doc.close()

    def detect_30_cells_table(self, page_img: np.ndarray) -> np.ndarray:
        """Tự động tìm khung bảng lớn nhất (Bảng chấm công 30 ô) trên trang cuối."""
        h_page, w_page = page_img.shape[:2]
        horizontal, vertical = self._line_masks(page_img)
        best_rect = self._find_table_rect(horizontal, vertical, w_page, h_page)

        if best_rect:
            x, y, w, h = best_rect
            return page_img[y:y + h, x:x + w]

        return page_img[int(h_page * 0.16):int(h_page * 0.82), int(w_page * 0.04):int(w_page * 0.96)]

    def _line_masks(self, page_img: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Dựng 2 mặt nạ đường kẻ ngang/dọc của bảng biểu trên trang."""
        h_page, w_page = page_img.shape[:2]
        gray = cv2.cvtColor(page_img, cv2.COLOR_BGR2GRAY)
        thresh = cv2.adaptiveThreshold(
            ~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2
        )

        horizontal = thresh.copy()
        vertical = thresh.copy()

        h_Structure = cv2.getStructuringElement(cv2.MORPH_RECT, (max(1, w_page // 30), 1))
        horizontal = cv2.erode(horizontal, h_Structure)
        horizontal = cv2.dilate(horizontal, h_Structure)

        v_Structure = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(1, h_page // 30)))
        vertical = cv2.erode(vertical, v_Structure)
        vertical = cv2.dilate(vertical, v_Structure)
        return horizontal, vertical

    def _find_table_rect(self, horizontal: np.ndarray, vertical: np.ndarray,
                         w_page: int, h_page: int) -> Optional[Tuple[int, int, int, int]]:
        """Khung bảng lớn nhất chiếm >20% diện tích trang (nếu không có trả None)."""
        grid_mask = cv2.add(horizontal, vertical)
        contours, _ = cv2.findContours(grid_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_rect = None
        max_area = 0
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            if area > (w_page * h_page * 0.20) and area > max_area:
                max_area = area
                best_rect = (x, y, w, h)
        return best_rect

    @staticmethod
    def _group_line_positions(profile: np.ndarray, threshold: float, min_gap: int = 10) -> List[int]:
        """Gom các chỉ số liên tiếp vượt ngưỡng thành 1 đường kẻ, trả về tọa độ tâm."""
        idxs = np.where(profile > threshold)[0]
        groups: List[List[int]] = []
        for i in idxs:
            if groups and int(i) - groups[-1][-1] <= min_gap:
                groups[-1].append(int(i))
            else:
                groups.append([int(i)])
        return [int(np.mean(g)) for g in groups]

    def analyze_page_geometry(self, page_img: np.ndarray, line_threshold: float = 0.45) -> Optional[Dict]:
        """
        Phân tích hình học bảng trên 1 trang: khung bảng + tọa độ các đường kẻ ngang/dọc.
        Dùng để phân biệt 2 kiểu phiếu:
        - Kiểu A (Lưới 30 ô): >= 6 đường dọc (7 kẻ = 6 cột)
        - Kiểu B (Phiếu từng buổi 'Buổi N ngày'): chỉ 3-4 đường dọc
        """
        h_page, w_page = page_img.shape[:2]
        horizontal, vertical = self._line_masks(page_img)
        rect = self._find_table_rect(horizontal, vertical, w_page, h_page)
        if not rect:
            return None

        x, y, w, h = rect
        h_profile = horizontal[y:y + h, x:x + w].sum(axis=1) / 255.0
        v_profile = vertical[y:y + h, x:x + w].sum(axis=0) / 255.0
        h_lines = [p + y for p in self._group_line_positions(h_profile, w * line_threshold)]
        v_lines = [p + x for p in self._group_line_positions(v_profile, h * line_threshold)]

        # Bờ ngoài của khung đôi khi mờ/không liền mạch: nạp thêm cạnh trên/dưới của rect
        if h_lines and h_lines[0] - y > 60:
            h_lines.insert(0, y)
        if h_lines and y + h - h_lines[-1] > 60:
            h_lines.append(y + h)
        return {"rect": rect, "h_lines": h_lines, "v_lines": v_lines}

    def prepare_handwriting_roi(self, roi_bgr: np.ndarray) -> Tuple[bool, np.ndarray]:
        """
        Tách riêng lớp mực bút bi xanh trên dòng Ngày/Giờ:
        - Loại bỏ hoàn toàn chữ in màu đen ('Ngày:', 'tại Cơ sở GD/YT', dấu chấm '..../....')
        - Giữ nguyên độ mềm của nét bút viết tay giúp EasyOCR nhận diện chính xác từng con số.
        """
        b, g, r = cv2.split(roi_bgr)
        b_int = b.astype(np.int16)
        r_int = r.astype(np.int16)

        # Mực xanh có kênh Blue vượt trội so với kênh Red
        blue_diff = b_int - r_int
        blue_ink_mask = (blue_diff > 20) & (b_int > 45)
        blue_pixels = np.sum(blue_ink_mask)
        total_pixels = roi_bgr.shape[0] * roi_bgr.shape[1]
        blue_ratio = blue_pixels / float(total_pixels)

        # Nếu diện tích mực xanh < 0.5% -> Ô trống (không có chữ viết tay)
        if blue_ratio < 0.005:
            return False, r

        # Chuyển đổi độ chênh lệch mực xanh thành ảnh Grayscale nền trắng (255), chữ đen đậm (0..80)
        ink_strength = np.clip((blue_diff - 12) * 4.8, 0, 250).astype(np.uint8)

        # Khử các hạt nhiễu li ti độc lập nhưng giữ nguyên nét số
        kernel = np.ones((2, 2), np.uint8)
        ink_strength = cv2.morphologyEx(ink_strength, cv2.MORPH_CLOSE, kernel)

        clean_gray = 255 - ink_strength
        clean_gray = cv2.GaussianBlur(clean_gray, (3, 3), 0)

        # Phóng to 2.2 lần và thêm viền trắng rộng
        upscaled = cv2.resize(clean_gray, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
        padded = cv2.copyMakeBorder(upscaled, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)

        return True, padded

    def _paddle_dets(self, ocr_img: np.ndarray) -> List[Dict]:
        """
        Chạy PaddleOCR trên 1 ảnh đã tách mực.
        Trả về danh sách dict {x, y, text, score} đã sắp xếp trái -> phải.
        PaddleOCR chỉ nhận ảnh 3 kênh nên phải chuyển Grayscale -> BGR.
        """
        img = ocr_img
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = self.reader.predict(np.ascontiguousarray(img))

        dets: List[Dict] = []
        for page in res:
            texts = list(page.get("rec_texts", []) or [])
            scores = [float(s) for s in (page.get("rec_scores", []) or [])]
            polys = page.get("rec_polys", None)
            if polys is None:
                polys = page.get("dt_polys", None)
            for i, txt in enumerate(texts):
                x_left, y_top = 0.0, 0.0
                try:
                    if polys is not None and i < len(polys):
                        pts = np.asarray(polys[i], dtype=float)
                        x_left, y_top = float(pts[:, 0].min()), float(pts[:, 1].min())
                except Exception:
                    pass
                dets.append({
                    "x": x_left,
                    "y": y_top,
                    "text": str(txt),
                    "score": scores[i] if i < len(scores) else 0.0,
                })
        dets.sort(key=lambda d: d["x"])
        return dets

    def _cap_ocr_side(self, img: np.ndarray) -> np.ndarray:
        """Thu nho anh qua lon ve MAX_OCR_SIDE (giu ty le) de buoc detect chay nhanh.

        KHONG phong to anh be: do tren CBP0005 (phong toi MIN 640px), ket qua
        EXACT/TOP-N khong doi, chi lam '91913024' bi mat mot chu so thanh
        '9191304' va cham hon o moi o OCR.
        """
        h, w = img.shape[:2]
        longest = max(h, w)
        if longest <= self.MAX_OCR_SIDE:
            return img
        f = float(self.MAX_OCR_SIDE) / longest
        return cv2.resize(img, (max(1, int(w * f)), max(1, int(h * f))),
                          interpolation=cv2.INTER_AREA)

    def run_ocr_on_cell(
        self, clean_gray_img: np.ndarray, min_y_ratio: float = 0.0
    ) -> Tuple[str, List[Dict]]:
        """
        Đọc chữ từ ảnh đã làm sạch.
        Trả về (chuỗi thô nối theo trục X, danh sách detection kèm điểm THAT của PaddleOCR).
        min_y_ratio: chỉ giữ các cụm số nằm từ tỷ lệ chiều cao này trở xuống.
        """
        # Cap TRUOC khi detect de toa do dets va img_h tinh o cung mot he quy
        clean_gray_img = self._cap_ocr_side(clean_gray_img)
        dets = self._paddle_dets(clean_gray_img)

        if min_y_ratio > 0:
            img_h = clean_gray_img.shape[0]
            dets = [d for d in dets if d["y"] >= img_h * min_y_ratio]

        dets = [d for d in dets if d["score"] > 0.08 and d["text"].strip()]
        raw_text = " ".join(d["text"].strip() for d in dets)
        return raw_text, dets

    @classmethod
    def parse_period_prior(cls, period_folder: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
        """Suy ra (Năm, Tháng) mặc định từ tên thư mục Kỳ, VD: '2026.10.20' -> (2026, 10)."""
        if not period_folder:
            return None, None
        m = re.search(r'(20\d{2})[.\-/](\d{1,2})', str(period_folder).strip())
        if m:
            return int(m.group(1)), int(m.group(2))
        return None, None

    # Dac biet 'confusable' luon xep sau moi phuong an duoc doc truc tiep tu anh
    _BASIS_RANK = {"separator": 0, "adjacent": 1, "split": 2, "prefix": 3, "confusable": 4}

    @staticmethod
    def _is_year_token(g: str) -> bool:
        """'2026'/'2024' là Năm in sẵn hoặc viết tay -> không bao giờ được nhầm thành Tháng."""
        return len(g) == 4 and g.startswith("20") and 2000 <= int(g) <= 2099

    @classmethod
    def _split_merged_group(cls, g: str) -> List[Tuple[str, str]]:
        """
        Một cụm số DÍNH (OCR mất dấu gạch chéo) -> mọi cách cắt (dd, mm) có thể.
        VD '3107' -> [(31,07)]; '508' -> [(5,08), (50,8)...] chỉ giữ cặp hợp lệ.
        Thứ tự thử (2, 3, 1): phiếu viết theo kiểu DD/MM nên ưu tiên NGÀY 2 chữ số
        trước ('108.206' là 10/8/2026, không phải 1/08); cặp vẫn được lọc hợp lệ nên
        ngày một chữ số ('508' -> 5/08) không mất đi.
        """
        pairs: List[Tuple[str, str]] = []
        if len(g) < 3:
            return pairs
        for cut in (2, 3, 1):
            a, b = g[:cut], g[cut:cut + 2]
            if len(b) < 1:
                continue
            pairs.append((a, b))
        return pairs

    @staticmethod
    def _group_provenance(raw_text: str, dets: List[Dict]) -> List[bool]:
        """
        Với mỗi cụm số trong chuỗi OCR: cho biết nó NGHI LÀ chữ IN của trang
        (chân trang 'tại Cơ sở GD/YT', đầu dòng 'Ngày:') hay là nét viết tay.
        Một detection lẫn từ 2 chữ cái trở lên bên cạnh chữ số -> nghi vấn chữ IN.
        Không đọc bằng được thứ tự cụm số thì trả 'không nghi vấn' (an toàn).
        """
        cleaned = re.sub(r"[^0-9/.\-: ]", " ", raw_text)
        groups = [m.group(0) for m in re.finditer(r"\d+", cleaned)]
        flags = [False] * len(groups)
        k = 0
        for d in dets:
            gs = re.findall(r"\d+", d["text"])
            suspect = sum(1 for ch in d["text"] if ch.isalpha()) >= 2
            for j in range(len(gs)):
                if k + j < len(flags):
                    flags[k + j] = suspect
            k += len(gs)
        if k != len(groups):
            return [False] * len(groups)
        return flags

    def _build_candidates(self, raw_text: str, dets: List[Dict], default_year: int) -> List[Dict]:
        """
        Sinh toi da 3 phuong an Ngay tu chuoi OCR, theo thu tu dang tin GIAM DAN.
        Khong co buoc nao "tu che" Thang: moi cap (dd, mm) deu phai doc duoc tu anh.

        basis:
          'separator'  - 2 cum so co dau / . - phan cach ro rang  -> bang chung manh nhat
          'adjacent'   - 2 cum so dung canh nhau tren cung dong OCR
          'split'      - phai TACH mot cum so dinh nhau            -> suy doan, guessed
          'prefix'     - lay cho dau cua cum dai (VD '8206' -> Thang 8) -> guessed
          'confusable' - doi 1 chu so nham lan (1/7, 8/9, 2/0)      -> CHI GOI Y,
                          khong bao gio duoc tu dong dien vao o
        """
        cleaned = re.sub(r"[^0-9/.\-: ]", " ", raw_text)
        groups = [m.group(0) for m in re.finditer(r"\d+", cleaned)]
        # Viền bảng đứng được OCR đọc thành chuỗi '1 1' / '1111': không có ngày nào
        # chỉ gồm toàn số 1, nên coi là nét kẻ -> không sinh phương án nào cả.
        non_year = [g for g in groups if not self._is_year_token(g)]
        if non_year and all(set(g) <= {"1"} for g in non_year):
            return []
        group_suspect = self._group_provenance(raw_text, dets)
        clean_groups = [g for g, s in zip(groups, group_suspect) if not s]
        digit_scores = [d["score"] for d in dets if re.search(r"\d", d["text"])]
        base = float(np.mean(digit_scores)) if digit_scores else 0.0

        year = None
        for g in groups:
            if self._is_year_token(g):
                year = int(g)
                break
        if year is None:
            for g in groups:
                if len(g) in (2, 3) and g.lstrip("0") in ("24", "25", "26", "27", "28", "29"):
                    year = 2000 + int(g[-2:])
                    break
        year_from_prior = year is None
        if year is None:
            year = default_year

        found: Dict[Tuple[int, int, int], Dict] = {}

        def add(d_str: str, m_str: str, basis: str, factor: float):
            if not d_str.isdigit() or not m_str.isdigit():
                return
            d_i, m_i = int(d_str), int(m_str)
            if not (1 <= d_i <= self.MAX_DAY and 1 <= m_i <= self.MAX_MONTH):
                return
            key = (d_i, m_i, year)
            cand = {
                "day": d_i, "month": m_i, "year": year,
                "date": f"{d_i:02d}/{m_i:02d}/{year}",
                "basis": basis,
                "guessed": basis in ("split", "prefix", "confusable"),
                "year_from_period_prior": year_from_prior,
                "score": round(base * factor, 4),
                "src": (d_str, m_str),
            }
            if key not in found or cand["score"] > found[key]["score"]:
                found[key] = cand

        # 1) Có dấu phân cách rõ ràng giữa 2 cụm số
        sep = re.search(r"(\d{1,2})\s*[/\.\-]\s*(\d{1,2})", cleaned)
        if sep:
            add(sep.group(1), sep.group(2), "separator", 1.0)

        # 2) Hai cụm số đứng cạnh nhau (đã loại cụm Năm)
        seq = [g for g in groups if not self._is_year_token(g)]
        for i in range(len(seq) - 1):
            add(seq[i], seq[i + 1], "adjacent", 0.9)

        # 3) Chi khi 2 cach tren chua cho ket qua: tach cum so dinh / lay cho dau cum dai
        if not found:
            # Người viết dùng dấu '/', nhưng PaddleOCR đọc nét gạch chéo thành chữ số '1':
            # '10/8/2024' -> '10181229'. Nhận diện dạng (Ngày)1(Tháng)1 trước khi tách thô.
            sep1 = re.compile(r"^(\d{1,2})1(\d{1,2})1\d{2,4}$")
            for g in seq:
                ms = sep1.match(g)
                if not ms and len(g) > 5 and g[0] == "1":
                    # Nét sổ của '27/8' bị đọc thành '1' DÍNH vào đầu cụm: '12718121'.
                    # Chỉ thử sau khi mẫu chuẩn đã thất bại và chỉ bỏ đúng 1 ký tự,
                    # để không đổi cách đọc những cụm đang đọc đúng (đo trên CBP0005 p09).
                    ms = sep1.match(g[1:])
                if ms:
                    add(ms.group(1), ms.group(2), "split", 0.65)
            for g in seq:
                if self._is_year_token(g):
                    continue
                for a, b in self._split_merged_group(g):
                    add(a, b, "split", 0.6)
            # Vi du o #2: anh viet "10 8 2026" nhung OCR noi chay -> '10 8206'.
            # Lay chu dau cua cum dai lam Thang, van giu nguyen cum Ngay doc duoc.
            for i in range(len(seq) - 1):
                d_grp, nxt = seq[i], seq[i + 1]
                if len(d_grp) > 2 or len(nxt) < 3 or self._is_year_token(nxt):
                    continue
                for cut in (1, 2):
                    add(d_grp, nxt[:cut], "prefix", 0.55)

        # 4) Goi y nham lan chu so - chi chen vao cho con lai, khong bao gio dung dau danh sach
        evidence = sorted(
            (c for c in found.values() if c["basis"] != "confusable"),
            key=lambda c: (self._BASIS_RANK.get(c["basis"], 9), -c["score"]),
        )
        if evidence:
            seed = evidence[0]
            for d_s, m_s in self._confusable_alternates(
                f"{seed['day']:02d}", f"{seed['month']:02d}"
            ):
                add(d_s, m_s, "confusable", 0.35)

        by_strength = sorted(
            found.values(), key=lambda c: (self._BASIS_RANK.get(c["basis"], 9), -c["score"])
        )
        # Slot 2-3 uu tien bien the NHAM NET cua phuong an dan dau: do tren CBP0005,
        # loi that 100% la 'doc sai 1 chu so' ('20/8' -> '20/9', '22/8' -> '2/8'),
        # nen gia thiet sua 1 chu so gia tri hon mot cach tach so ngau nhien.
        ranked = by_strength[:1]
        alts = [c for c in by_strength[1:] if c["basis"] == "confusable"][:2]
        ranked += alts
        ranked += [c for c in by_strength[1:] if all(c is not a for a in alts)][: 3 - len(ranked)]
        # Cả 2 số của phương án chỉ đến từ đoạn OCR lẫn nhiều chữ IN -> đây là chữ in
        # (chân trang, đầu dòng), không phải nét viết tay: vẫn giữ làm gợi ý
        # nhưng tuyệt đối không tự điền vào ô.
        def _tu_chu_viet_tay(tok: str) -> bool:
            # Cụm số gốc có thể bị tách/prefix ('3007' -> 30/07) nên so sánh kiểu substring
            return any(tok in g for g in clean_groups)

        for c in ranked:
            d_src, m_src = c.pop("src")
            c["printed_suspect"] = not (_tu_chu_viet_tay(d_src) and _tu_chu_viet_tay(m_src))
        return ranked

    @classmethod
    def _confusable_alternates(cls, day_s: str, month_s: str) -> List[Tuple[str, str]]:
        """
        Sinh cac phuong an "nham net" tu mot cap (Ngay, Thang) DA DOC DUOC TU ANH,
        bang cach doi 1 chu so lấy sang chu so cung hay nham lan.
        Thu tu sinh: trai -> phai, Ngay va Thang xen ke nhau de ca hai loai loi
        deu con cho trong 3 goi y. Day la GOI Y cho nguoi dung bam chon,
        khong phai ket luan cua AI - ket luan van phai dua tren chuoi OCR goc.
        """
        def variants(field_s: str, is_day: bool) -> List[str]:
            """Chi giu bien the hop le ve Nguyen/Thang - bien vo nghia khong duoc chot cho goi y."""
            out: List[str] = []
            for pos in range(len(field_s)):
                for rep in cls.CONFUSABLE_DIGITS.get(field_s[pos], ""):
                    v = field_s[:pos] + rep + field_s[pos + 1:]
                    if v == field_s or v in out:
                        continue
                    val = int(v)
                    if is_day and not (1 <= val <= cls.MAX_DAY):
                        continue
                    if not is_day and not (1 <= val <= cls.MAX_MONTH):
                        continue
                    out.append(v)
            return out

        day_opts, month_opts = variants(day_s, True), variants(month_s, False)
        alts: List[Tuple[str, str]] = []
        for i in range(max(len(day_opts), len(month_opts))):
            if i < len(day_opts):
                alts.append((day_opts[i], month_s))
            if i < len(month_opts):
                alts.append((day_s, month_opts[i]))
        return alts

    def clean_and_parse_datetime(
        self, raw_text: str, default_year: int = 2026, dets: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Chuyển chuỗi OCR thành phương án Ngày (kèm tối đa 3 gợi ý cho UI).
        Không bao giờ điền Tháng/Năm suy đoán từ thư mục Kỳ vào ô trống.
        """
        dets = dets or []
        result = {
            "date": None,
            "candidates": [],
            "start_time": None,
            "end_time": None,
            "raw_ocr": raw_text.strip(),
            "warning": None,
            "confidence": 0.0,
        }
        if not raw_text or len(raw_text.strip()) < 2:
            return result

        cands = self._build_candidates(raw_text, dets, default_year)
        result["candidates"] = cands
        if not cands:
            return result

        best = cands[0]
        if best.get("printed_suspect"):
            # Chuỗi số nằm giữa đoạn chữ in (chân trang / đầu dòng) -> không có bằng chứng
            # viết tay: trả về gợi ý để người dùng tự bấm, tuyệt đối không điền vào ô.
            result["warning"] = ("Phát hiện chữ số trong đoạn chữ in, không chắc là viết tay "
                                 "- vui lòng bấm chọn nếu đúng")
            return result
        result["date"] = best["date"]
        result["confidence"] = best["score"]
        if best["guessed"]:
            result["warning"] = "Tháng/Ngày phải tách từ cụm số dính nhau - cần bạn bấm chọn lại nếu sai"
        elif best["year_from_period_prior"]:
            result["warning"] = f"Năm lấy từ thư mục Kỳ ({best['year']}), ảnh OCR không đọc được năm"
        if len(cands) > 1:
            others = ", ".join(c["date"] for c in cands[1:])
            result["warning"] = (result["warning"] + " | " if result["warning"] else "") \
                + f"Còn {len(cands) - 1} phương án khác: {others}"
        return result

    def _grayscale_fallback(self, roi_bgr: np.ndarray) -> np.ndarray:
        """Lớp tiền xử lý dự phòng: Grayscale + Otsu (dùng khi mực xanh không tách được nét)."""
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # Loại bỏ nét mảnh/nhiễu của chữ in đen còn sót lại
        kernel = np.ones((2, 2), np.uint8)
        otsu = cv2.morphologyEx(otsu, cv2.MORPH_OPEN, kernel)
        clean = 255 - otsu
        clean = cv2.GaussianBlur(clean, (3, 3), 0)
        upscaled = cv2.resize(clean, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
        return cv2.copyMakeBorder(upscaled, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)

    def read_date_from_cell(
        self, cell_img: np.ndarray, ch: int, cw: int, default_year: int
    ) -> Dict:
        """
        Đọc Ngày cho 1 ô chấm công, tối đa 2 lớp ROI:
        - Lớp 1: band chuẩn DATE_BAND_Y (0.10-0.37) + tách mực xanh -> đúng nhất cho bút xanh
        - Lớp 2: band rộng DATE_BAND_Y_ALT + Grayscale Otsu        -> cứu ô viết lệch dòng/mực đen
        Trả về dict: date / candidates / raw_ocr / confidence / warning.
        KHÔNG có tham số Tháng mặc định: thiếu Tháng thì ô đó thuộc diện cần người chọn.
        """
        bands = [
            (int(ch * self.DATE_BAND_Y[0]), int(ch * self.DATE_BAND_Y[1])),
            (int(ch * self.DATE_BAND_Y_ALT[0]), int(ch * self.DATE_BAND_Y_ALT[1])),
        ]
        rx1, rx2 = int(cw * self.DATE_BAND_X[0]), int(cw * self.DATE_BAND_X[1])

        best = {"date": None, "candidates": [], "start_time": None, "end_time": None,
                "raw_ocr": "", "warning": None, "confidence": 0.0}

        for band_idx, (ry1, ry2) in enumerate(bands):
            date_roi = cell_img[ry1:ry2, rx1:rx2]
            if date_roi.size == 0:
                continue

            if band_idx == 0:
                has_hw, ocr_img = self.prepare_handwriting_roi(date_roi)
                if not has_hw:
                    continue
            else:
                ocr_img = self._grayscale_fallback(date_roi)

            raw_text, dets = self.run_ocr_on_cell(ocr_img)
            if not re.search(r"\d", raw_text):
                continue

            parsed = self.clean_and_parse_datetime(raw_text, default_year, dets)
            if not parsed["date"]:
                # Chỉ giữ chuỗi thô để người dùng nhìn thấy OCR đọc ra gì
                if not best["candidates"] and len(raw_text) > len(best["raw_ocr"]):
                    best.update(parsed)
                continue

            # Lớp 2 dùng Otsu cả vùng rộng -> dễ ăn thêm nét chữ ký, phạt nhẹ điểm
            score = parsed["confidence"] * (1.0 if band_idx == 0 else 0.85)
            if score > best["confidence"]:
                best.update(parsed)
                best["confidence"] = round(score, 4)

            if best["confidence"] >= self.CONFIDENCE_HIGH:
                break  # Đã đọc chắc chắn, khỏi chạy lớp dự phòng cho nhanh

        # Bắt buộc tách cụm số dính -> kém chắc chắn: hạ điểm để UI buộc người dùng soát
        if best["candidates"] and best["candidates"][0].get("guessed"):
            best["confidence"] = min(best["confidence"], self.CONFIDENCE_MED - 0.01)

        return best

    def _blue_ink_row_runs(self, page_bgr: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Định vị mọi cụm nét mực xanh trên trang theo trục hàng (projection).
        Mỗi cụm = 1 ngày viết tay (chữ ký nằm ở hàng khác sẽ tách riêng và bị loại ở bước kiểm tra ngày).
        Trả về danh sách (y1, y2, x1, x2) đã nới lề.
        """
        b = page_bgr[:, :, 0].astype(np.int16)
        r = page_bgr[:, :, 2].astype(np.int16)
        mask = (((b - r) > 18) & (b > 45) & (b < 235)).astype(np.uint8) * 255
        # Khử nhiễu li ti của nền scan
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

        # Xóa nét KẺ BẢNG trước khi gom hàng: ở scan 300dpi, viền bảng đen ngả xanh
        # đủ mạnh để lọt mask -> PaddleOCR đọc 2 đường kẻ dọc thành '1 1' -> bịa ra
        # 01/01 cho ô TRỐNG. Đường kẻ có tỉ lệ rất dài/mỏng, chữ số viết tay thì không.
        mask = self._drop_rule_lines(mask)

        mask = cv2.dilate(mask, np.ones((5, 5), np.uint8))

        row_profile = (mask > 0).sum(axis=1)
        idxs = np.where(row_profile >= 12)[0]
        if len(idxs) == 0:
            return []

        runs = []
        start = prev = int(idxs[0])
        for i in idxs[1:]:
            if int(i) - prev <= 45:
                prev = int(i)
            else:
                runs.append((start, prev))
                start = prev = int(i)
        runs.append((start, prev))

        h_page, w_page = page_bgr.shape[:2]
        boxed = []
        for (ry1, ry2) in runs:
            ry1 = max(0, ry1 - 20)
            ry2 = min(h_page, ry2 + 20)
            if ry2 - ry1 < 40:  # quá thấp để là một ngày viết tay
                continue
            col_profile = (mask[ry1:ry2] > 0).sum(axis=0)
            xs = np.where(col_profile >= 2)[0]
            if len(xs) == 0:
                continue
            rx1 = max(0, int(xs.min()) - 20)
            rx2 = min(w_page, int(xs.max()) + 20)
            # KHONG nới thêm lề trái: do tren CBP0005, moi cach nới (hang so co dinh
            # 45-80px hay lan den khoang trang 60px) deu keo net ke bang vao vung cat
            # va lam giam EXACT ('10/8' -> '04/01', '20/8' -> '02/01').
            if rx2 - rx1 < 60:
                continue
            boxed.append((ry1, ry2, rx1, rx2))
        return boxed

    @staticmethod
    def _drop_rule_lines(mask: np.ndarray) -> np.ndarray:
        """Loại các connected component dạng đường thẳng (kẻ bảng, viền trang) khỏi mask mực xanh."""
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        keep = np.zeros_like(mask)
        for i in range(1, n):
            x, y, w, h = (int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]),
                          int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]))
            is_vline = w <= 14 and h >= max(60, 4 * w)
            is_hline = h <= 14 and w >= max(120, 4 * h)
            if not (is_vline or is_hline):
                keep[y:y + h, x:x + w] = mask[y:y + h, x:x + w]
        return keep

    @staticmethod
    def _session_column_divider(geo: Optional[Dict], from_offset: float = 0.05,
                                to_offset: float = 0.35) -> Optional[int]:
        """
        Đường kẻ dọc đầu tiên của bảng = ranh giới cột 'Thời gian' trên phiếu Kiểu B
        (đo trên CBP0005: x=575, tức 16% bề rộng bảng). Cắt sát tại đây loại được
        mã số 'PN-101031' và cột ghi chú - hai nguồn ngày giả đã đo được - mà vẫn
        giữ nguyên nét viết trong cột ngày.
        Trả None khi trang không có kẻ nào trong 5-35% bề rộng: đó là trang văn bản
        (MỤC TIÊU, TÓM TẮT, NHẬN ĐỊNH) chứ không phải phiếu buổi.
        """
        if not geo:
            return None
        gx, gy, gw, gh = geo["rect"]
        for x in geo.get("v_lines", []):
            off = (x - gx) / float(gw) if gw else 0.0
            if from_offset <= off <= to_offset:
                return int(x)
        return None

    @staticmethod
    def _is_digit_dominant(raw_text: str, min_ratio: float = 0.6) -> bool:
        """Chuỗi OCR có giống một ngày viết tay không: ký số phải chiếm áp đảo so với chữ cái."""
        digits = sum(1 for ch in raw_text if ch.isdigit())
        letters = sum(1 for ch in raw_text if ch.isalpha())
        if digits == 0:
            return False
        return digits / float(digits + letters) >= min_ratio

    @staticmethod
    def _looks_like_date_fragment(raw_text: str) -> bool:
        """Cụm số có dấu phân cách kiểu ngày/tháng (chưa đủ chuẩn vẫn ghi nhận để người dùng soát lại)."""
        return bool(re.search(r'\d{1,2}\s*[/\-.]\s*\d{1,2}', raw_text))

    def _process_session_sheets(
        self, pdf_path: str, prefix: str, default_year: int
    ) -> List[Dict]:
        """
        KIỂU B - Phiếu can thiệp từng buổi (mỗi trang 1-2 buổi, 'Buổi N ngày' + Ngày viết tay cột trái).
        Quét toàn bộ các trang: định vị cụm mực xanh theo hàng -> OCR từng cụm -> kiểm tra hợp lệ ngày.
        Trang không có mực xanh (viết bút đen): fallback theo dải dòng bảng + yêu cầu chuỗi ngày đầy đủ.
        """
        doc = fitz.open(pdf_path)
        extracted_sessions = []
        seq_no = 0   # mỗi trang có thể nhiều cụm -> đánh số thứ tự toàn file để không trùng nhau
        try:
            zoom = 300 / 72.0
            mat = fitz.Matrix(zoom, zoom)

            for page_idx in range(len(doc)):
                page = doc[page_idx]
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
                img = cv2.cvtColor(
                    np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3),
                    cv2.COLOR_RGB2BGR
                )

                # Ngày viết tay chỉ nằm trong cột 'Thời gian' - giới hạn bằng chính
                # đường kẻ dọc đầu tiên của bảng. Cột giữa/dưới (chữ ký, ghi chú) bị
                # loại khỏi mọi cụm đưa vào OCR.
                geo = self.analyze_page_geometry(img)
                divider = self._session_column_divider(geo)
                if divider is None:
                    # Trang không có kẻ dọc phân cách cột 'Thời gian' -> không phải
                    # phiếu buổi: bỏ qua. Đo trên CBP0005, trang MỤC TIÊU in sẵn
                    # 'Từ ngày 1-6:', 'Từ ngày 7-15:' bị đọc thành 10/07/2024 (ngày giả).
                    continue
                runs = self._blue_ink_row_runs(img)
                right_limit = divider
                clipped = []
                for (ry1, ry2, rx1, rx2) in runs:
                    # Cắt theo GIAO SỐ với cột ngày, KHÔNG lọc theo tâm cụm: một dòng
                    # chứa cả 'Ngày 5/8' (trái) lẫn ghi chú (phải) có tâm nằm ngoài
                    # ngưỡng, nhưng phần bên trái vẫn là ngày thật (mất 2 ngày của
                    # CBP0005 trang 4 đúng vì cách lọc tâm này).
                    x2 = min(rx2, right_limit)
                    if rx1 >= right_limit or x2 - rx1 < 60:
                        continue
                    clipped.append((ry1, ry2, rx1, x2))
                runs = clipped

                page_results = []
                for run_idx, (ry1, ry2, rx1, rx2) in enumerate(runs, start=1):
                    crop = img[ry1:ry2, rx1:rx2]
                    has_hw, clean_blue = self.prepare_handwriting_roi(crop)
                    if not has_hw:
                        continue
                    raw_text, dets = self.run_ocr_on_cell(clean_blue)
                    parsed = self.clean_and_parse_datetime(raw_text, default_year, dets)
                    if parsed["date"] and not self._is_digit_dominant(raw_text):
                        # Cụm mực xanh chủ yếu là CHỮ (ghi chú, đầu trang) -> vài số lọt
                        # vào không phải ngày: giữ gợi ý nhưng tuyệt đối không tự điền.
                        parsed["date"] = None
                        parsed["warning"] = ("Cụm viết chủ yếu là chữ, không đủ bằng chứng là ngày "
                                             "- bấm chọn nếu một trong các gợi ý đúng")
                    if not parsed["date"] and not self._looks_like_date_fragment(raw_text):
                        continue  # chữ ký/nét viết khác, không phải ngày
                    conf = parsed["confidence"]
                    if parsed["date"] and parsed["candidates"] and parsed["candidates"][0]["guessed"]:
                        conf = min(conf, self.CONFIDENCE_MED - 0.01)  # buộc UI yêu cầu soát lại

                    snippet_name = f"{prefix}_p{page_idx + 1:02d}_{run_idx}.jpg"
                    snippet_path = os.path.join(self.snippets_dir, snippet_name)
                    cv2.imwrite(snippet_path, crop)

                    page_results.append({
                        "box_number": (seq_no := seq_no + 1),
                        "page": page_idx + 1,
                        "date": parsed["date"],
                        "candidates": parsed["candidates"],
                        "start_time": parsed["start_time"],
                        "end_time": parsed["end_time"],
                        "raw_ocr": parsed["raw_ocr"],
                        "warning": parsed["warning"],
                        "confidence": round(float(conf), 4),
                        "snippet_path": snippet_path,
                        "needs_review": (parsed["date"] is None) or (parsed["warning"] is not None)
                                        or (conf < self.CONFIDENCE_MED)
                    })

                if not page_results:
                    page_results = self._session_band_fallback(
                        img, page_idx, prefix, default_year, start_no=seq_no
                    )
                    seq_no += len(page_results)
                extracted_sessions.extend(page_results)
        finally:
            doc.close()

        def sort_key(item):
            if item["date"]:
                try:
                    return (0, datetime.strptime(item["date"], "%d/%m/%Y"), item["box_number"])
                except ValueError:
                    pass
            return (1, datetime.max, item["box_number"])

        extracted_sessions.sort(key=sort_key)
        return extracted_sessions

    def _session_band_fallback(
        self, page_img: np.ndarray, page_idx: int, prefix: str, default_year: int,
        start_no: int = 0
    ) -> List[Dict]:
        """
        Dự phòng mực đen/xám: chia dải theo đường kẻ ngang, OCR Grayscale-Otsu cột 'Thời gian'.
        CHẤP NHẬN khi chuỗi đọc được là ngày đầy đủ DD/MM/YYYY (số 3 nhóm có dấu phân cách)
        để không bao giờ nhầm chữ in 'Từ ngày 1-6:' thành ngày thật.
        """
        results = []
        geo = self.analyze_page_geometry(page_img)
        if not geo or len(geo["v_lines"]) < 2 or len(geo["h_lines"]) < 2:
            return results

        x, y, w, h = geo["rect"]
        lx = max(0, x - int(0.08 * w))
        rx = None
        for vx in geo["v_lines"]:
            off = (vx - x) / float(w)
            if 0.06 <= off <= 0.30:
                rx = int(vx)
                break
        if rx is None:
            rx = x + int(w * 0.16)

        h_lines = geo["h_lines"]
        seen_dates = set()
        for band in range(len(h_lines) - 1):
            y1, y2 = h_lines[band] + 3, h_lines[band + 1] - 3
            if y2 - y1 < page_img.shape[0] * 0.08:
                continue
            strip = page_img[y1:y2, lx:rx]
            if strip.size == 0:
                continue

            gray_img = self._grayscale_fallback(strip)
            raw_text, dets = self.run_ocr_on_cell(gray_img, min_y_ratio=0.35)
            if not re.search(r'\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{2,4}', raw_text):
                continue
            parsed = self.clean_and_parse_datetime(raw_text, default_year, dets)
            if not parsed["date"] or parsed["date"] in seen_dates:
                continue
            seen_dates.add(parsed["date"])
            conf = parsed["confidence"]

            snippet_name = f"{prefix}_p{page_idx + 1:02d}_fb{band + 1}.jpg"
            snippet_path = os.path.join(self.snippets_dir, snippet_name)
            cv2.imwrite(snippet_path, strip)

            results.append({
                "box_number": start_no + len(results) + 1,
                "page": page_idx + 1,
                "date": parsed["date"],
                "candidates": parsed["candidates"],
                "start_time": parsed["start_time"],
                "end_time": parsed["end_time"],
                "raw_ocr": parsed["raw_ocr"],
                "warning": (parsed["warning"] or "") + " (bút đen, cần soát)",
                "confidence": round(float(conf), 4),
                "snippet_path": snippet_path,
                "needs_review": True
            })
        return results

    def process_pdf(self, pdf_path: str, prefix: str = "child", period_folder: Optional[str] = None) -> List[Dict]:
        """
        Điểm phân nhánh tự động 2 kiểu phiếu:
        - Trang cuối có lưới >=6 cột dọc -> KIỂU A (bảng chấm công 30 ô)
        - Ngược lại -> KIỂU B (phiếu can thiệp từng buổi, quét toàn bộ trang)
        """
        default_year, _default_month = self.parse_period_prior(period_folder)
        if default_year is None:
            default_year = datetime.now().year

        page_img = self.render_last_page(pdf_path, dpi=300)
        geo = self.analyze_page_geometry(page_img)
        if geo is None or len(geo["v_lines"]) >= 6:
            return self._process_grid_table(page_img, prefix, default_year)
        return self._process_session_sheets(pdf_path, prefix, default_year)

    def _process_grid_table(
        self, page_img: np.ndarray, prefix: str, default_year: int
    ) -> List[Dict]:
        table_img = self.detect_30_cells_table(page_img)
        t_h, t_w = table_img.shape[:2]

        grid_x = int(t_w * 0.048)
        grid_y = int(t_h * 0.115)
        grid_w = t_w - grid_x
        grid_h = t_h - grid_y

        rows, cols = 5, 6
        cell_w = grid_w / cols
        cell_h = grid_h / rows

        extracted_sessions = []
        debug_canvas = table_img.copy()

        for r in range(rows):
            for c in range(cols):
                box_num = r * cols + c + 1
                x1 = int(grid_x + c * cell_w)
                y1 = int(grid_y + r * cell_h)
                x2 = int(grid_x + (c + 1) * cell_w)
                y2 = int(grid_y + (r + 1) * cell_h)

                cell_img = table_img[y1:y2, x1:x2]
                ch, cw = cell_img.shape[:2]

                # Kiểm tra nhanh mực xanh đúng band dòng Ngày để bỏ ô trống (không tốn công OCR)
                probe_y1, probe_y2 = int(ch * self.DATE_BAND_Y[0]), int(ch * self.DATE_BAND_Y[1])
                probe_x1, probe_x2 = int(cw * self.DATE_BAND_X[0]), int(cw * self.DATE_BAND_X[1])
                has_handwriting, _ = self.prepare_handwriting_roi(cell_img[probe_y1:probe_y2, probe_x1:probe_x2])

                cv2.rectangle(debug_canvas, (x1, y1), (x2, y2), (230, 180, 0), 1)
                if has_handwriting:
                    cv2.rectangle(
                        debug_canvas,
                        (x1 + probe_x1, y1 + probe_y1),
                        (x1 + probe_x2, y1 + probe_y2),
                        (0, 200, 0),
                        2
                    )
                if not has_handwriting:
                    continue

                # TỌA ĐỘ DÒNG NGÀY ĐO THỰC TẾ + khửi đọc 2 lớp
                parsed = self.read_date_from_cell(cell_img, ch, cw, default_year=default_year)

                snippet_display = cell_img[int(ch * self.SNIPPET_BAND_Y[0]):int(ch * self.SNIPPET_BAND_Y[1]),
                                           int(cw * self.DATE_BAND_X[0]):int(cw * self.DATE_BAND_X[1])]
                snippet_name = f"{prefix}_box_{box_num:02d}.jpg"
                snippet_path = os.path.join(self.snippets_dir, snippet_name)
                cv2.imwrite(snippet_path, snippet_display)

                extracted_sessions.append({
                    "box_number": box_num,
                    "date": parsed["date"],
                    "candidates": parsed["candidates"],
                    "start_time": parsed["start_time"],
                    "end_time": parsed["end_time"],
                    "raw_ocr": parsed["raw_ocr"],
                    "warning": parsed["warning"],
                    "confidence": parsed["confidence"],
                    "snippet_path": snippet_path,
                    "needs_review": (parsed["date"] is None) or (parsed["confidence"] < self.CONFIDENCE_MED)
                })

        debug_grid_path = os.path.join(self.snippets_dir, "_debug_full_grid.jpg")
        cv2.imwrite(debug_grid_path, debug_canvas)

        def sort_key(item):
            if item["date"]:
                try:
                    return (0, datetime.strptime(item["date"], "%d/%m/%Y"), item["box_number"])
                except ValueError:
                    pass
            return (1, datetime.max, item["box_number"])

        extracted_sessions.sort(key=sort_key)
        return extracted_sessions