import os
from typing import List, Dict, Callable, Optional
from core_engine.path_parser import VietHealthPathParser


class BatchPDFScanner:
    """
    Quét toàn bộ cây thư mục OneDrive của dự án I3b:
    - Tự động lọc tất cả các file PDF chấm công
    - Bóc tách metadata từ đường dẫn và gọi OCR engine xử lý từng file
    """

    @staticmethod
    def scan_directory(
        root_dir: str,
        ocr_process_callback: Callable[[str, Dict], List[Dict]],
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Dict]:
        """
        Quét đệ quy thư mục root_dir, tìm mọi file PDF và chạy OCR.
        - ocr_process_callback: Hàm nhận (pdf_path, metadata) và trả về danh sách session.
        - progress_callback: Hàm nhận (current_index, total_files, current_filename).
        """
        if not os.path.exists(root_dir):
            raise FileNotFoundError(f"Không tìm thấy thư mục: {root_dir}")

        pdf_files = []
        for root, _, files in os.walk(root_dir):
            for file in files:
                if file.lower().endswith(".pdf"):
                    pdf_files.append(os.path.join(root, file))

        total_files = len(pdf_files)
        all_results = []

        for idx, pdf_path in enumerate(pdf_files, start=1):
            filename = os.path.basename(pdf_path)
            if progress_callback:
                progress_callback(idx, total_files, filename)

            # 1. Bóc tách thông tin từ đường dẫn OneDrive
            meta = VietHealthPathParser.parse(pdf_path)
            if not meta["is_valid"]:
                continue

            # 2. Chạy OCR bóc tách 30 ô chấm công
            try:
                sessions = ocr_process_callback(pdf_path, meta)
                all_results.append({
                    "meta": meta,
                    "sessions": sessions,
                    "file_path": pdf_path,
                    "success": True
                })
            except Exception as e:
                all_results.append({
                    "meta": meta,
                    "sessions": [],
                    "file_path": pdf_path,
                    "success": False,
                    "error": str(e)
                })

        return all_results