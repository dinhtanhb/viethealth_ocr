# -*- coding: utf-8 -*-
"""
Smoke test lõi bóc tách metadata + AI đọc chữ viết tay trên 1 file PDF thật.

Cách dùng:
    python test_step1_ocr.py "<duong-dan-file-PDF>"
    python test_step1_ocr.py "<thu-muc-chua-PDF>" [index]

Lưu ý: đường dẫn tiếng Việt nên lấy bằng os.walk (xem AGENTS.md mục 3.1),
vì vậy truyền THƯ MỤC thường an toàn hơn truyền tên file gõ tay.
"""
import os
import sys

from core_engine.path_parser import VietHealthPathParser
from core_engine.pdf_grid_ocr import PDFGridOCREngine


def resolve_pdf_path(arg: str, index: int = 0) -> str:
    """Trả về đường dẫn 1 file PDF: dùng thẳng nếu là file, hoặc tìm trong thư mục."""
    if os.path.isfile(arg):
        return arg

    if os.path.isdir(arg):
        pdfs = [
            os.path.join(root, f)
            for root, _, files in os.walk(arg)
            for f in files
            if f.lower().endswith(".pdf")
        ]
        if not pdfs:
            raise FileNotFoundError(f"Không tìm thấy file PDF nào trong: {arg}")
        if index >= len(pdfs):
            raise IndexError(f"index {index} vượt số file tìm thấy ({len(pdfs)})")
        return pdfs[index]

    raise FileNotFoundError(f"Không tìm thấy đường dẫn: {arg}")


def run_test(sample_pdf: str):
    print("=" * 95)
    print("🔍 CHẠY THỬ NGHIỆM BÓC TÁCH METADATA & AI ĐỌC CHỮ VIẾT TAY TRÊN FILE PDF")
    print("=" * 95)
    print(f"\n📄 File PDF: {sample_pdf}")

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

    print("\n2️⃣ ĐANG CHẠY AI ĐỌC CHỮ VIẾT TAY (tự nhận diện Kiểu A / Kiểu B)...")
    ocr_engine = PDFGridOCREngine()
    sessions = ocr_engine.process_pdf(
        sample_pdf,
        prefix=meta.get("child_id") or "TEST",
        period_folder=meta.get("period"),
    )

    total_hw = len(sessions)
    total_date = sum(1 for s in sessions if s["date"])
    total_multi = sum(1 for s in sessions
                      if len([c for c in (s.get("candidates") or [])
                              if c.get("basis") != "confusable"]) > 1)
    pct = round(total_date * 100.0 / total_hw) if total_hw else 0
    print(f"\n✅ Tìm thấy {total_hw} buổi có chữ viết tay | "
          f"🤖 AI điền Ngày vào {total_date}/{total_hw} ô ({pct}% ĐỘ PHỦ - chưa phải độ CHÍNH XÁC; "
          f"muốn biết đọc đúng hay sai phải chạy bench_accuracy.py với ground truth)")
    if total_multi:
        print(f"   🟡 {total_multi} ô AI đọc ra nhiều phương án - xem cột 'Gợi ý' để biết ô nào cần người bấm chọn")
    print("-" * 95)
    print(f"{'Buổi':<6} | {'Ô số':<6} | {'Ngày CT':<11} | {'Giờ BĐ':<7} | {'Giờ KT':<7} | {'Gợi ý':<7} | {'Chuỗi thô AI đọc (Raw OCR)':<24} | {'Trạng thái'}")
    print("-" * 110)
    for idx, s in enumerate(sessions, start=1):
        d_str = s['date'] or "??/??/????"
        st_str = s['start_time'] or "--:--"
        et_str = s['end_time'] or "--:--"
        raw_str = (s['raw_ocr'][:22] + "..") if len(s['raw_ocr']) > 24 else s['raw_ocr']
        conf = s.get('confidence', 0.0)
        cands = s.get('candidates') or []
        cand_str = " | ".join(c["date"][:5] for c in cands[1:3]) or "-"
        # Chi phuong an dua tren bang chung anh (khong tinh nham net) moi lam can 🟢/🟡
        evidence = [c for c in cands if c.get("basis") != "confusable"]
        is_guessed = bool(evidence) and evidence[0].get("guessed")

        if s['date'] and conf >= ocr_engine.CONFIDENCE_HIGH and len(evidence) <= 1 and not is_guessed:
            status = f"🟢 Tự điền (tin cậy {conf:.2f})"
        elif s['date']:
            status = f"🟡 Điền xong nhưng cần soát (tin cậy {conf:.2f})"
        else:
            status = "🔴 Chưa đọc được - nhập tay"

        print(f"{idx:<6} | Ô #{s['box_number']:<3} | {d_str:<11} | {st_str:<7} | {et_str:<7} | {cand_str:<7} | {raw_str:<24} | {status}")
    print("-" * 110)
    if total_hw and total_date < total_hw:
        print(f"⚠️ AI còn bỏ {total_hw - total_date} ô chưa điền được - đối chiếu ảnh cắt từng ô.")
    print("📁 Ảnh cắt chữ viết tay đã lưu tại: 'media_snippets/'")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("❌ Thiếu đường dẫn. Truyền vào 1 file PDF hoặc 1 thư mục chứa PDF.")
        sys.exit(1)

    try:
        target = resolve_pdf_path(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    except (FileNotFoundError, IndexError) as exc:
        print(f"❌ {exc}")
        sys.exit(1)

    run_test(target)
