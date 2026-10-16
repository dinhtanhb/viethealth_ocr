import os
import re
import warnings
from datetime import datetime
from typing import List, Dict, Optional
import cv2
import numpy as np

# Tắt các cảnh báo (warnings) của PyTorch và PyMuPDF
warnings.filterwarnings("ignore")

try:
    import pymupdf as fitz
except ImportError:
    import fitz

import easyocr


class PDFGridOCREngine:
    """
    Bộ lõi xử lý trang cuối PDF Bảng Chấm Công (Offline 100%):
    - Tự động bắt khung bảng 30 ô (5 hàng x 6 cột)
    - Khung cắt (ROI) tinh chỉnh chính xác vào dòng Ngày (tránh hoàn toàn chữ ký phụ huynh)
    - Xử lý tách nét chữ viết tay sạch sẽ trước khi đưa vào EasyOCR
    """

    def __init__(self, models_dir: str = "local_models", snippets_dir: str = "media_snippets"):
        self.models_dir = models_dir
        self.snippets_dir = snippets_dir
        os.makedirs(self.models_dir, exist_ok=True)
        os.makedirs(self.snippets_dir, exist_ok=True)

        self.reader = easyocr.Reader(
            ['en'],
            gpu=False,
            model_storage_directory=self.models_dir,
            download_enabled=True,
            verbose=False
        )

    def render_last_page(self, pdf_path: str, dpi: int = 300) -> np.ndarray:
        """Đọc file PDF và chỉ trích xuất trang cuối cùng thành ảnh OpenCV BGR."""
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Không tìm thấy file PDF: {pdf_path}")

        doc = fitz.open(pdf_path)
        try:
            if len(doc) == 0:
                raise ValueError("File PDF rỗng.")

            last_page = doc[-1]
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = last_page.get_pixmap(matrix=mat, alpha=False)

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

    def extract_handwriting_layer(self, roi_bgr: np.ndarray) -> tuple[bool, np.ndarray]:
        """Tách riêng lớp chữ viết tay (mực xanh), loại bỏ hoàn toàn chữ in đen và dấu chấm."""
        hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)

        # Dải màu mực bút bi xanh
        lower_blue = np.array([85, 30, 30])
        upper_blue = np.array([155, 255, 255])
        blue_mask = cv2.inRange(hsv, lower_blue, upper_blue)

        kernel_clean = np.ones((2, 2), np.uint8)
        blue_mask = cv2.morphologyEx(blue_mask, cv2.MORPH_OPEN, kernel_clean)

        blue_pixels = cv2.countNonZero(blue_mask)
        total_pixels = roi_bgr.shape[0] * roi_bgr.shape[1]
        blue_ratio = blue_pixels / float(total_pixels)

        # Ngưỡng nhận diện có chữ viết tay trong ô ngày
        if blue_ratio > 0.004:
            dilated = cv2.dilate(blue_mask, np.ones((2, 2), np.uint8), iterations=1)
            clean_ocr_img = 255 - dilated
            clean_ocr_img = cv2.resize(clean_ocr_img, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
            clean_ocr_img = cv2.copyMakeBorder(clean_ocr_img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            return True, clean_ocr_img

        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        _, binary_inv = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY_INV)
        stroke_mask = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        stroke_ratio = cv2.countNonZero(stroke_mask) / float(total_pixels)

        if stroke_ratio > 0.035:
            clean_ocr_img = 255 - binary_inv
            clean_ocr_img = cv2.resize(clean_ocr_img, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
            clean_ocr_img = cv2.copyMakeBorder(clean_ocr_img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            return True, clean_ocr_img

        return False, gray

    def clean_and_parse_datetime(self, raw_text: str, default_year: int = 2026, default_month: int = 9) -> Dict[str, Optional[str]]:
        """Làm sạch chuỗi OCR và bóc tách Ngày, Giờ chính xác."""
        result = {
            "date": None,
            "start_time": None,
            "end_time": None,
            "raw_ocr": raw_text.strip(),
            "warning": None
        }
        if not raw_text or len(raw_text.strip()) < 1:
            return result

        char_map = {
            'O': '0', 'o': '0', 'D': '0',
            'I': '1', 'l': '1', '|': '1',
            'Z': '2', 'z': '2',
            'S': '5', 's': '5',
            'B': '8',
            'g': '9', 'q': '9',
        }
        cleaned = "".join(char_map.get(c, c) for c in raw_text)

        found_date = False
        day, month, year = None, None, default_year

        # 1. Bắt dạng chuẩn DD/MM/YYYY hoặc DD.MM.YYYY hoặc DD-MM
        date_pattern_sep = r'(\d{1,2})\s*[/\-\.]\s*(\d{1,2})(?:\s*[/\-\.\s]\s*(202\d|\d{2,4}))?'
        m = re.search(date_pattern_sep, cleaned)
        if m:
            d_val = int(m.group(1))
            m_val = int(m.group(2))
            y_val = m.group(3)
            if 1 <= d_val <= 31 and 1 <= m_val <= 12:
                day, month = d_val, m_val
                if y_val:
                    y_clean = re.sub(r'\D', '', y_val)
                    if len(y_clean) == 2:
                        year = 2000 + int(y_clean)
                    elif len(y_clean) == 4 and y_clean.startswith("202"):
                        year = int(y_clean)
                found_date = True

        # 2. Bắt dạng các cụm số rời nhau do nét viết tay đứt quãng
        if not found_date:
            nums = [int(n) for n in re.findall(r'\d+', cleaned)]
            if len(nums) >= 2:
                d_val, m_val = nums[0], nums[1]
                if len(nums) >= 3 and nums[2] > 2020:
                    year = nums[2]
                elif len(nums) >= 3 and 20 <= nums[2] <= 30:
                    year = 2000 + nums[2]

                if 1 <= d_val <= 31 and 1 <= m_val <= 12:
                    day, month = d_val, m_val
                    found_date = True
            elif len(nums) == 1 and len(str(nums[0])) >= 3:
                s = str(nums[0])
                if len(s) == 4:
                    day, month = int(s[:2]), int(s[2:])
                elif len(s) == 3:
                    day, month = int(s[:1]), int(s[1:])
                if 1 <= (day or 0) <= 31 and 1 <= (month or 0) <= 12:
                    found_date = True

        # 3. Bóc Giờ bắt đầu / Giờ kết thúc: "9h-10h", "14h30-15h30", "HH:MM-HH:MM" hoặc "HH-HH"
        time_pattern = r'(\d{1,2})\s*[:hH]\s*(\d{2})?\s*[-–—]\s*(\d{1,2})\s*[:hH]\s*(\d{2})?'
        mt = re.search(time_pattern, cleaned)
        if mt:
            h1, m1 = int(mt.group(1)), int(mt.group(2) or 0)
            h2, m2 = int(mt.group(3)), int(mt.group(4) or 0)
            if 0 <= h1 <= 24 and 0 <= h2 <= 24 and 0 <= m1 <= 59 and 0 <= m2 <= 59:
                result["start_time"] = f"{h1:02d}:{m1:02d}"
                result["end_time"] = f"{h2:02d}:{m2:02d}"

        if found_date and day:
            if not month or not (1 <= month <= 12):
                month = default_month
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

                # 👉 ĐIỀU CHỈNH VÙNG ROI TẬP TRUNG CHÍNH XÁC VÀO DÒNG NGÀY (TRÁNH CHỮ KÝ PHÍA DƯỚI)
                roi_y1, roi_y2 = int(ch * 0.34), int(ch * 0.52)
                roi_x1, roi_x2 = int(cw * 0.15), int(cw * 0.95)
                date_roi = cell_img[roi_y1:roi_y2, roi_x1:roi_x2]

                has_handwriting, clean_ocr_img = self.extract_handwriting_layer(date_roi)

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

                ocr_results = self.reader.readtext(
                    clean_ocr_img,
                    detail=0,
                    allowlist='0123456789/:-.',
                    width_ths=0.8,
                    mag_ratio=2.0
                )
                raw_text = " ".join(ocr_results).strip()
                parsed = self.clean_and_parse_datetime(raw_text)

                snippet_display = cell_img[int(ch * 0.28):int(ch * 0.58), int(cw * 0.02):int(cw * 0.98)]
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
