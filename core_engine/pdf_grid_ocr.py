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
    """

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

        if best_rect:
            x, y, w, h = best_rect
            return page_img[y:y + h, x:x + w]

        return page_img[int(h_page * 0.16):int(h_page * 0.82), int(w_page * 0.04):int(w_page * 0.96)]

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

    def run_ocr_on_cell(self, clean_gray_img: np.ndarray) -> str:
        """
        Đọc chuỗi số Ngày/Tháng/Năm từ ảnh mực xanh đã làm sạch.
        Chỉ cho phép các ký tự số và dấu phân cách ngày/giờ để không bao giờ nhận nhầm thành chữ cái.
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

        # Sắp xếp từ trái qua phải theo trục X
        dets.sort(key=lambda item: item[0][0][0])
        raw_tokens = [item[1].strip() for item in dets if item[2] > 0.08 and item[1].strip()]
        return " ".join(raw_tokens)

    def clean_and_parse_datetime(
        self, raw_text: str, default_year: int = 2026
    ) -> Dict[str, Optional[str]]:
        """
        Phân tích chuỗi số OCR từ dòng Ngày (Hỗ trợ chuẩn các dạng: 24.07.2026, 24/07/2026, 24 07 2026).
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

        cleaned = raw_text.strip()

        # 1. Tách phần Năm ở cuối chuỗi
        year = default_year
        year_match = re.search(r'[/\-\.\s]*(202[4-9]|20[0-9]{2}|026|206|26)\s*$', cleaned)
        if year_match:
            y_token = re.sub(r'\D', '', year_match.group(1))
            if len(y_token) == 4 and y_token.startswith("202"):
                year = int(y_token)
            cleaned = cleaned[:year_match.start()].strip()

        day, month = None, None

        # 2. Bắt dạng có dấu phân cách rõ ràng ( '/', '.', '-' )
        sep_match = re.search(r'(\d{1,2})\s*[/\-\.]+\s*(\d{1,2})', cleaned)
        if sep_match:
            d_cand, m_cand = int(sep_match.group(1)), int(sep_match.group(2))
            if 1 <= d_cand <= 31 and 1 <= m_cand <= 12:
                day, month = d_cand, m_cand

        # 3. Nếu không bắt được bằng dấu, gom các cụm số lại (hỗ trợ dấu chấm bị đọc thành khoảng trắng)
        if day is None:
            tokens = re.findall(r'\d+', cleaned)
            if len(tokens) >= 2:
                d_cand, m_cand = int(tokens[0]), int(tokens[1])
                if 1 <= d_cand <= 31 and 1 <= m_cand <= 12:
                    day, month = d_cand, m_cand
            elif len(tokens) == 1 and len(tokens[0]) >= 3:
                s = tokens[0]
                if len(s) >= 4:
                    d_cand, m_cand = int(s[:2]), int(s[2:4])
                elif len(s) == 3:
                    d_cand, m_cand = int(s[:1]), int(s[1:])
                if 1 <= (day or d_cand) <= 31 and 1 <= (month or m_cand) <= 12:
                    day, month = d_cand, m_cand

        if day is not None and month is not None:
            result["date"] = f"{day:02d}/{month:02d}/{year}"

        return result

    def process_pdf(self, pdf_path: str, prefix: str = "child") -> List[Dict]:
        page_img = self.render_last_page(pdf_path, dpi=300)
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

                # TỌA ĐỘ CHUẨN XÁC CỦA DÒNG NGÀY TRÊN PHIẾU (y: 19% -> 41%)
                roi_y1, roi_y2 = int(ch * 0.19), int(ch * 0.41)
                roi_x1, roi_x2 = int(cw * 0.16), int(cw * 0.92)
                date_roi = cell_img[roi_y1:roi_y2, roi_x1:roi_x2]

                has_handwriting, clean_ocr_img = self.prepare_handwriting_roi(date_roi)

                cv2.rectangle(debug_canvas, (x1, y1), (x2, y2), (230, 180, 0), 1)
                if has_handwriting:
                    cv2.rectangle(
                        debug_canvas,
                        (x1 + roi_x1, y1 + roi_y1),
                        (x1 + roi_x2, y1 + roi_y2),
                        (0, 200, 0),
                        2
                    )
                if not has_handwriting:
                    continue

                raw_text = self.run_ocr_on_cell(clean_ocr_img)
                parsed = self.clean_and_parse_datetime(raw_text)

                snippet_display = cell_img[int(ch * 0.16):int(ch * 0.46), int(cw * 0.02):int(cw * 0.96)]
                snippet_name = f"{prefix}_box_{box_num:02d}.jpg"
                snippet_path = os.path.join(self.snippets_dir, snippet_name)
                cv2.imwrite(snippet_path, snippet_display)

                clean_debug_path = os.path.join(self.snippets_dir, f"_clean_box_{box_num:02d}.jpg")
                cv2.imwrite(clean_debug_path, clean_ocr_img)

                extracted_sessions.append({
                    "box_number": box_num,
                    "date": parsed["date"],
                    "start_time": parsed["start_time"],
                    "end_time": parsed["end_time"],
                    "raw_ocr": parsed["raw_ocr"],
                    "warning": parsed["warning"],
                    "snippet_path": snippet_path,
                    "needs_review": (parsed["date"] is None)
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