"""
Đánh giá tỉ lệ AI TỰ ĐỌC & ĐIỀN được Ngày trên các phiếu chấm công thật (mục tiêu >90%):
    python bench_auto_read.py "duong/dan/thu_muc/pdf" [so_file]
"""
import sys
from core_engine.path_parser import VietHealthPathParser
from core_engine.pdf_grid_ocr import PDFGridOCREngine


def main():
    root_dir = sys.argv[1] if len(sys.argv) > 1 else r"D:\VietHealth\INC3b - Documents\6. Bao cao\7. Ho so can thiep\2. Ho so theo ky\2024.09.15\GDDB"
    max_files = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    import os
    if os.path.isfile(root_dir) and root_dir.lower().endswith(".pdf"):
        pdf_files = [root_dir]
    else:
        pdf_files = []
        for r, _, fs in os.walk(root_dir):
            for f in fs:
                if f.lower().endswith(".pdf"):
                    pdf_files.append(os.path.join(r, f))
    pdf_files = pdf_files[:max_files]
    if not pdf_files:
        print(f"⚠️ Không có file PDF nào trong: {root_dir}")
        return

    engine = PDFGridOCREngine()
    total_hw = total_date = total_solid = 0

    for pdf in pdf_files:
        meta = VietHealthPathParser.parse(pdf)
        sessions = engine.process_pdf(pdf, prefix=(meta.get("child_id") or "DOC"), period_folder=meta.get("period"))
        hw = len(sessions)
        got = sum(1 for s in sessions if s["date"])
        solid = sum(1 for s in sessions if s["date"] and s.get("confidence", 0) >= engine.CONFIDENCE_HIGH)
        total_hw += hw
        total_date += got
        total_solid += solid
        miss = [f"Ô#{s['box_number']}('{s['raw_ocr']}')" for s in sessions if not s["date"]]
        print(f"📄 {meta.get('child_id') or pdf}: {got}/{hw} ngày tự điền ({solid} chắc chắn)" +
              (f" | ❌ Lỗi: {', '.join(miss)}" if miss else ""))

    pct = round(total_date * 100.0 / total_hw, 1) if total_hw else 0
    flag = "✅ ĐẠT" if pct > 90 else "⚠️ CHƯA ĐẠT 90%"
    print("=" * 80)
    print(f"TỔNG KẾT {len(pdf_files)} file: AI tự đọc & điền {total_date}/{total_hw} ngày = {pct}% {flag}")
    print(f"   Trong đó {total_solid}/{total_date} ngày có độ tin cậy cao (>= {engine.CONFIDENCE_HIGH})")


if __name__ == "__main__":
    main()
