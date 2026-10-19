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

import easyocr


class PDFGridOCREngine:
    """
    Bộ lõi xử lý trang cuối PDF Bảng Chấm Công (Offline 100%):
    - Tự động bắt khung bảng 30 ô (5 hàng x 6 cột)
    - Tọa độ ROI chuẩn xác (y: 19% -> 41%) lấy trọn dòng Ngày, loại bỏ 100% chữ ký Phụ huynh bên dưới
    - Lọc tách riêng mực bút xanh sang Grayscale mềm mại cho EasyOCR
    - Đa lớp tiền xử lý + khửi sai lệch OCR (nhiều ROI, nhiều ngưỡng) để đạt >90% số Ngày đọc tự động
    - Mượn Năm/Tháng từ tên thư mục Kỳ làm "prior" cứu các ô OCR thiếu nét
    """

    # Các cặp ký tự EasyOCR hay nhầm lẫn với chữ số trong bối cảnh chỉ cho phép số
    CONFUSION_MAP = {
        "O": "0", "o": "0", "Q": "0", "D": "0", "q": "0",
        "I": "1", "l": "1", "i": "1", "|": "1", "J": "1",
        "Z": "2", "z": "2", "r": "2",
        "S": "5", "s": "5",
        "B": "8", "b": "6",
        "g": "9", "C": "G",
        "t": "+",
    }

    CONFIDENCE_HIGH = 0.45   # Ngưỡng tin tưởng cao (tự điền, ít cần soát) - chữ viết tay khó đạt 0.55+
    CONFIDENCE_MED = 0.30    # Ngưỡng thấp nhất chấp nhận được

    MIN_DATE_CONFIDENCE = 0.15  # Chuỗi OCR quá nhỏ/nhiễu -> coi như ô trống

    def __init__(self, models_dir: str = "models_storage/easyocr", snippets_dir: str = "media_snippets"):
        self.models_dir = models_dir
        self.snippets_dir = snippets_dir
        os.makedirs(self.models_dir, exist_ok=True)
        os.makedirs(self.snippets_dir, exist_ok=True)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.reader = easyocr.Reader(
                ['en'],
                gpu=False,
                model_storage_directory=self.models_dir,
                download_enabled=True,
                verbose=False
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

    def _repair_confused_chars(self, raw_text: str) -> str:
        """Sửa các ký tự chữ cái bị EasyOCR nhận nhầm thành chữ số (O->0, l->1, S->5, B->8...)."""
        fixed_chars = []
        for ch in raw_text:
            if ch.isdigit() or ch in "/-:. ":
                fixed_chars.append(ch)
            elif ch in self.CONFUSION_MAP:
                repl = self.CONFUSION_MAP[ch]
                fixed_chars.append(repl if repl.isdigit() else " ")
            else:
                fixed_chars.append(" ")
        return "".join(fixed_chars)

    def run_ocr_on_cell(
        self, clean_gray_img: np.ndarray, min_y_ratio: float = 0.0
    ) -> Tuple[str, float]:
        """
        Đọc chuỗi số Ngày/Tháng/Năm từ ảnh đã làm sạch.
        Chỉ cho phép các ký tự số và dấu phân cách ngày/giờ để không bao giờ nhận nhầm thành chữ cái.
        min_y_ratio: chỉ giữ các cụm số nằm từ tỷ lệ chiều cao này trở xuống (lọc chữ in tiêu đề phía trên).
        Trả về (chuỗi thô, điểm trung bình confidence của EasyOCR).
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            dets = self.reader.readtext(
                clean_gray_img,
                detail=1,
                paragraph=False,
                allowlist='0123456789/.-:',
                text_threshold=0.30,
                low_text=0.20,
                link_threshold=0.20,
                width_ths=0.4,
                mag_ratio=1.5
            )

        if min_y_ratio > 0:
            img_h = clean_gray_img.shape[0]
            dets = [d for d in dets if np.mean([pt[1] for pt in d[0]]) >= img_h * min_y_ratio]

        # Sắp xếp từ trái qua phải theo trục X
        dets.sort(key=lambda item: item[0][0][0])
        valid = [item for item in dets if item[2] > 0.08 and item[1].strip()]
        raw_tokens = [item[1].strip() for item in valid]
        avg_conf = float(np.mean([item[2] for item in valid])) if valid else 0.0
        return " ".join(raw_tokens), avg_conf

    @classmethod
    def parse_period_prior(cls, period_folder: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
        """Suy ra (Năm, Tháng) mặc định từ tên thư mục Kỳ, VD: '2026.10.20' -> (2026, 10)."""
        if not period_folder:
            return None, None
        m = re.search(r'(20\d{2})[.\-/](\d{1,2})', str(period_folder).strip())
        if m:
            return int(m.group(1)), int(m.group(2))
        return None, None

    def clean_and_parse_datetime(
        self, raw_text: str, default_year: int = 2026,
        default_month: Optional[int] = None
    ) -> Dict[str, Optional[str]]:
        """
        Phân tích chuỗi số OCR từ dòng Ngày (Hỗ trợ chuẩn các dạng: 24.07.2026, 24/07/2026, 24 07 2026).
        Có khửi sửa nhầm lẫn ký tự và dùng Năm/Tháng "prior" từ thư mục Kỳ để cứu các trường hợp thiếu nét.
        """
        result = {
            "date": None,
            "start_time": None,
            "end_time": None,
            "raw_ocr": raw_text.strip(),
            "warning": None
        }
        if not raw_text or len(raw_text.strip()) < 2:
            return result

        # 0. Sửa các chữ cái bị nhận nhầm thành số/trước khi phân tích
        cleaned = self._repair_confused_chars(raw_text).strip()
        if len(cleaned) < 2:
            return result

        # 1. Tách phần Năm ở cuối chuỗi
        year = None
        year_match = re.search(r'[/\-\.\s]*(202[4-9]|20[0-9]{2})\s*$', cleaned)
        if not year_match:
            # Năm bị viết/cắt cụt: "26", "026", "206"
            year_match = re.search(r'[/\-\.\s]*(026|206|(?<=\D)(26|24|25))(?=\s*$)', cleaned)
        if year_match:
            y_token = re.sub(r'\D', '', year_match.group(1))
            if len(y_token) == 4 and y_token.startswith("202"):
                year = int(y_token)
            elif y_token in ("026", "206", "26"):
                year = 2026
            elif y_token in ("24", "25"):
                year = 2000 + int(y_token)
            cleaned = cleaned[:year_match.start()].strip()

        day, month = None, None

        # 2. Bắt dạng có dấu phân cách rõ ràng ( '/', '.', '-' )
        sep_match = re.search(r'(\d{1,2})\s*[/\-\.]+\s*(\d{1,2})', cleaned)
        if sep_match:
            d_cand, m_cand = int(sep_match.group(1)), int(sep_match.group(2))
            if 1 <= d_cand <= 31 and 1 <= m_cand <= 12:
                day, month = d_cand, m_cand
            elif 1 <= m_cand <= 31 and 1 <= d_cand <= 12 and m_cand > 12:
                # Người viết ghi Tháng trước Ngày hoặc OCR đảo 2 cụm số
                day, month = m_cand, d_cand

        # 3. Nếu không bắt được bằng dấu, gom các cụm số lại (hỗ trợ dấu chấm bị đọc thành khoảng trắng)
        if day is None:
            tokens = re.findall(r'\d+', cleaned)
            if len(tokens) >= 2:
                d_cand, m_cand = int(tokens[0]), int(tokens[1])
                if 1 <= d_cand <= 31 and 1 <= m_cand <= 12:
                    day, month = d_cand, m_cand
                elif 1 <= m_cand <= 31 and 1 <= d_cand <= 12 and m_cand > 12:
                    day, month = m_cand, d_cand
                else:
                    # Bỏ qua năm rò lại dưới dạng 2 số (VD: "24 07 26")
                    tail = m_cand if m_cand > 31 else (d_cand if d_cand > 31 else None)
                    head = m_cand if tail == d_cand else d_cand
                    if tail is not None and 1 <= head <= 31:
                        day, month = head, None
            elif len(tokens) == 1 and len(tokens[0]) >= 3:
                s = tokens[0]
                if len(s) >= 4:
                    d_cand, m_cand = int(s[:2]), int(s[2:4])
                elif len(s) == 3:
                    d_cand, m_cand = int(s[:1]), int(s[1:])
                if 1 <= d_cand <= 31 and 1 <= m_cand <= 12:
                    day, month = d_cand, m_cand
                elif len(s) == 3 and 1 <= d_cand <= 1:
                    # Dạng "DMM" bị nhòe dấu (VD: 1/11 -> 111)
                    d_cand2, m_cand2 = int(s[:1]), int(s[1:])
                    if 1 <= m_cand2 <= 12:
                        day, month = d_cand2, m_cand2

        # 3.5 Cứu tháng bị dính chữ số thừa (VD: '5/81 4' thực chất là '5/8/2024')
        if day is not None and month is None:
            tokens = re.findall(r'\d+', cleaned)
            for i in range(len(tokens) - 1):
                a = int(tokens[i])
                b_str = tokens[i + 1]
                if a == day and len(b_str) >= 2 and 13 <= int(b_str) <= 99:
                    m_trunc = int(b_str[0])
                    if 1 <= m_trunc <= 9:
                        month = m_trunc
                        result["warning"] = f"Tháng suy đoán từ '{b_str}', cần người dùng xác nhận"
                        break

        # 4. Cứu trường hợp chỉ đọc được Ngày (Tháng bị mờ/không viết):
        #    mượn Tháng từ prior thư mục Kỳ nếu ô nằm trong kỳ đó
        if day is not None and month is None and default_month:
            month = default_month
            result["warning"] = f"Tháng mượn từ kỳ ({default_month:02d}), cần người dùng xác nhận"
        if year is None:
            year = default_year

        if day is not None and month is not None:
            result["date"] = f"{day:02d}/{month:02d}/{year}"

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
        self, cell_img: np.ndarray, ch: int, cw: int,
        default_year: int, default_month: Optional[int]
    ) -> Dict:
        """
        Khửi đọc Ngày 2 lớp cho 1 ô chấm công:
        - Lớp 1: ROI chuẩn (y 19%-41%) + tách mực xanh (nhanh, chuẩn nhất cho bút xanh)
        - Lớp 2: ROI mở rộng (y 15%-50%) + Grayscale Otsu (cứu ô viết lệch dòng/mực đen)
        Trả về dict chứa date/raw_ocr/confidence/warning (lớp tốt nhất được chọn).
        """
        roi_variants = [
            (int(ch * 0.19), int(ch * 0.41), int(ch * 0.0)),
            (int(ch * 0.15), int(ch * 0.50), int(ch * 0.0)),
        ]
        rx1, rx2 = int(cw * 0.16), int(cw * 0.92)

        best = {"date": None, "start_time": None, "end_time": None,
                "raw_ocr": "", "warning": None, "confidence": 0.0}

        for idx, (ry1, ry2, _) in enumerate(roi_variants):
            date_roi = cell_img[ry1:ry2, rx1:rx2]
            if date_roi.size == 0:
                break

            if idx == 0:
                has_hw, ocr_img = self.prepare_handwriting_roi(date_roi)
                if not has_hw:
                    continue
            else:
                ocr_img = self._grayscale_fallback(date_roi)

            raw_text, conf = self.run_ocr_on_cell(ocr_img)
            if conf < self.MIN_DATE_CONFIDENCE and not re.search(r'\d', raw_text):
                continue

            parsed = self.clean_and_parse_datetime(raw_text, default_year, default_month)
            score = conf if parsed["date"] else -1.0

            if parsed["date"] and (best["date"] is None or score > best["confidence"]):
                best.update(parsed)
                best["confidence"] = round(float(conf), 4)
            elif best["date"] is None and raw_text:
                # Giữ lại chuỗi thô + confidence thấp nhất để báo cáo ô cần nhập tay
                if parsed["raw_ocr"] and len(parsed["raw_ocr"]) > len(best["raw_ocr"]):
                    best.update(parsed)
                    best["confidence"] = round(float(conf), 4)

            if best["date"] and best["confidence"] >= self.CONFIDENCE_HIGH:
                break  # Đã đọc chắc chắn, khỏi chạy lớp dự phòng cho nhanh

        # Ngày phải suy đoán (tháng mượn/dính nhiễu): hạ confidence để UI buộc người dùng soát
        if best["date"] and best["warning"]:
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
            if rx2 - rx1 < 60:
                continue
            boxed.append((ry1, ry2, rx1, rx2))
        return boxed

    @staticmethod
    def _looks_like_date_fragment(raw_text: str) -> bool:
        """Cụm số có dấu phân cách kiểu ngày/tháng (chưa đủ chuẩn vẫn ghi nhận để người dùng soát lại)."""
        return bool(re.search(r'\d{1,2}\s*[/\-.]\s*\d{1,2}', raw_text))

    def _process_session_sheets(
        self, pdf_path: str, prefix: str, default_year: int, default_month: Optional[int]
    ) -> List[Dict]:
        """
        KIỂU B - Phiếu can thiệp từng buổi (mỗi trang 1-2 buổi, 'Buổi N ngày' + Ngày viết tay cột trái).
        Quét toàn bộ các trang: định vị cụm mực xanh theo hàng -> OCR từng cụm -> kiểm tra hợp lệ ngày.
        Trang không có mực xanh (viết bút đen): fallback theo dải dòng bảng + yêu cầu chuỗi ngày đầy đủ.
        """
        doc = fitz.open(pdf_path)
        extracted_sessions = []
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

                # Ngày viết tay chỉ xuất hiện ở cột 'Thời gian' (left ~35% bảng);
                # chữ ký Phụ huynh ở cột giữa/dưới bị loại hoàn toàn khỏi danh sách cụm
                geo = self.analyze_page_geometry(img)
                runs = self._blue_ink_row_runs(img)
                if geo:
                    gx, gy, gw, gh = geo["rect"]
                    right_limit = gx + int(gw * 0.35)
                    clipped = []
                    for (ry1, ry2, rx1, rx2) in runs:
                        if (rx1 + rx2) / 2.0 > right_limit:
                            continue
                        clipped.append((ry1, ry2, rx1, min(rx2, right_limit)))
                    runs = clipped

                page_results = []
                for run_idx, (ry1, ry2, rx1, rx2) in enumerate(runs, start=1):
                    crop = img[ry1:ry2, rx1:rx2]
                    has_hw, clean_blue = self.prepare_handwriting_roi(crop)
                    if not has_hw:
                        continue
                    raw_text, conf = self.run_ocr_on_cell(clean_blue)
                    parsed = self.clean_and_parse_datetime(raw_text, default_year, default_month)
                    if not parsed["date"] and not self._looks_like_date_fragment(raw_text):
                        continue  # chữ ký/nét viết khác, không phải ngày
                    if parsed["date"] and parsed["warning"]:
                        conf = min(conf, self.CONFIDENCE_MED - 0.01)  # buộc UI yêu cầu soát lại

                    snippet_name = f"{prefix}_p{page_idx + 1:02d}_{run_idx}.jpg"
                    snippet_path = os.path.join(self.snippets_dir, snippet_name)
                    cv2.imwrite(snippet_path, crop)

                    page_results.append({
                        "box_number": page_idx + 1,
                        "date": parsed["date"],
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
                        img, page_idx, prefix, default_year, default_month
                    )
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
        self, page_img: np.ndarray, page_idx: int, prefix: str,
        default_year: int, default_month: Optional[int]
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
            raw_text, conf = self.run_ocr_on_cell(gray_img, min_y_ratio=0.35)
            if not re.search(r'\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{2,4}', raw_text):
                continue
            parsed = self.clean_and_parse_datetime(raw_text, default_year, default_month)
            if not parsed["date"] or parsed["date"] in seen_dates:
                continue
            seen_dates.add(parsed["date"])

            snippet_name = f"{prefix}_p{page_idx + 1:02d}_fb{band + 1}.jpg"
            snippet_path = os.path.join(self.snippets_dir, snippet_name)
            cv2.imwrite(snippet_path, strip)

            results.append({
                "box_number": page_idx + 1,
                "date": parsed["date"],
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
        default_year, default_month = self.parse_period_prior(period_folder)
        if default_year is None:
            default_year = datetime.now().year

        page_img = self.render_last_page(pdf_path, dpi=300)
        geo = self.analyze_page_geometry(page_img)
        if geo is None or len(geo["v_lines"]) >= 6:
            return self._process_grid_table(page_img, prefix, default_year, default_month)
        return self._process_session_sheets(pdf_path, prefix, default_year, default_month)

    def _process_grid_table(
        self, page_img: np.ndarray, prefix: str, default_year: int, default_month: Optional[int]
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

                # Kiểm tra nhanh mực xanh toàn ô để bỏ ô trống (không tốn công OCR)
                probe_y1, probe_y2 = int(ch * 0.19), int(ch * 0.41)
                probe_x1, probe_x2 = int(cw * 0.16), int(cw * 0.92)
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

                # TỌA ĐỘ CHUẨN XÁC CỦA DÒNG NGÀY TRÊN PHIẾU + khửi đọc 2 lớp
                parsed = self.read_date_from_cell(
                    cell_img, ch, cw, default_year=default_year, default_month=default_month
                )

                snippet_display = cell_img[int(ch * 0.16):int(ch * 0.46), int(cw * 0.02):int(cw * 0.96)]
                snippet_name = f"{prefix}_box_{box_num:02d}.jpg"
                snippet_path = os.path.join(self.snippets_dir, snippet_name)
                cv2.imwrite(snippet_path, snippet_display)

                extracted_sessions.append({
                    "box_number": box_num,
                    "date": parsed["date"],
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