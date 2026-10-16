import os
from core_engine.path_parser import VietHealthPathParser
from core_engine.pdf_grid_ocr import PDFGridOCREngine


def run_test():
    print("=" * 95)
    print("🔍 CHẠY THỬ NGHIỆM BÓC TÁCH METADATA & AI ĐỌC CHỮ VIẾT TAY TRÊN FILE PDF")
    print("=" * 95)

    sample_pdf = r"D:\VietHealth\INC3b - Documents\6. Bao cao\7. Ho so can thiep\2. Ho so theo ky\2026.10.20\Can thiep\N6\ABP0055 Nguyễn Thị Ngần\Test_doc_PDF_2.pdf"

    print("\n1️⃣ BÓC TÁCH THÔNG TIN TỪ ĐƯỜNG DẪN:")
    meta = VietHealthPathParser.parse(sample_pdf)
    if meta["is_valid"]:
        print(f"   ✅ Kỳ báo cáo : {meta['period']} | Nhóm: {meta['group']}")
        print(f"   ✅ Cán bộ CT  : [{meta['staff_id']}] {meta['staff_name']}")
        print(f"   ✅ Trẻ        : [{meta['child_id']}] {meta['child_name']}")
        print(f"   ✅ Dịch vụ    : {meta['service']}")
        if meta.get("warning"):
            print(f"   ℹ️ Ghi chú    : {meta['warning']}")
    else:
        print(f"   ⚠️ Lưu ý đường dẫn: {meta['error']}")

    if not os.path.exists(sample_pdf):
        print(f"\n⚠️ Không tìm thấy file PDF tại:\n   {sample_pdf}")
        return

    print("\n2️⃣ ĐANG CHẠY AI ĐỌC 30 Ô BẢNG CHẤM CÔNG Ở TRANG CUỐI PDF...")
    ocr_engine = PDFGridOCREngine()
    sessions = ocr_engine.process_pdf(sample_pdf, prefix=meta.get("child_id") or "TEST")

    print(f"\n✅ Tìm thấy {len(sessions)} buổi có chữ viết tay trên Bảng chấm công:")
    print("-" * 95)
    print(f"{'Buổi':<6} | {'Ô số':<6} | {'Ngày CT':<11} | {'Giờ BĐ':<7} | {'Giờ KT':<7} | {'Chuỗi thô AI đọc (Raw OCR)':<24} | {'Trạng thái'}")
    print("-" * 95)
    for idx, s in enumerate(sessions, start=1):
        d_str = s['date'] or "??/??/????"
        st_str = s['start_time'] or "--:--"
        et_str = s['end_time'] or "--:--"
        raw_str = (s['raw_ocr'][:22] + "..") if len(s['raw_ocr']) > 24 else s['raw_ocr']

        if s['date'] and s['start_time']:
            status = "🟢 Đủ Ngày & Giờ"
        elif s['date'] and not s['start_time']:
            status = "🟢 Đã đọc Ngày (Phiếu ko ghi giờ)"
        else:
            status = "🟡 Cần kiểm tra lại"

        print(f"{idx:<6} | Ô #{s['box_number']:<3} | {d_str:<11} | {st_str:<7} | {et_str:<7} | {raw_str:<24} | {status}")
    print("-" * 95)
    print(f"🖼️ ẢNH KIỂM TRA KHUNG CẮT 30 Ô: {os.path.abspath('media_snippets/_debug_full_grid.jpg')}")
    print("📁 Ảnh cắt từng ô & ảnh lọc mực (_clean_box_XX.jpg) đã lưu tại: 'media_snippets/'")


if __name__ == "__main__":
    run_test()