"""
Benchmark DO CHINH XAC cua AI OCR - so voi ground truth do nguoi doc tay tren anh cat.

    python bench_accuracy.py                 # chay moi file trong benchmarks/ground_truth.json
    python bench_accuracy.py --only "<path>" # chi chay 1 file

Khac hoan toan voi benchmark cu (bench_auto_read.py): do PHU chi dem o AI dien duoc
ke ca khi dien SAI, nen bao 91% trong khi thuc te 0 ngay dung. O day doi lap:

  EXACT  = % o AI dien DUNG TUYET DOI ngay lap tuc (nguoi dung khong phai lam gi)
  TOP-N  = % o co dap an dung nam trong cac phuong an AI goi y (nguoi dung bam chon 1 cai)
  DAY    = % o doc dung rieng phần NGÀY (thường cao hơn MONTH, hữu ích để chẩn đoán)
  DANGEROUS = o AI dien SAI nhung do tin cay cao -> nguy hiem nhat vi nguoi dung de bo qua
"""
import json
import os
import sys
from collections import Counter

from core_engine.path_parser import VietHealthPathParser
from core_engine.pdf_grid_ocr import PDFGridOCREngine

GT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "benchmarks", "ground_truth.json")


def load_ground_truth(only: str = ""):
    with open(GT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    docs = data.get("docs", {})
    if only:
        docs = {k: v for k, v in docs.items() if os.path.normcase(k) == os.path.normcase(only)}
    return docs


def evaluate(engine: PDFGridOCREngine, pdf_path: str, truth: dict):
    meta = VietHealthPathParser.parse(pdf_path)
    sessions = engine.process_pdf(pdf_path, prefix=(meta.get("child_id") or "DOC"),
                                  period_folder=meta.get("period"))
    by_box = {str(s.get("box_number")): s for s in sessions}

    stats = Counter()
    details = []
    for box, want in sorted(truth.items(), key=lambda kv: int(kv[0])):
        s = by_box.get(str(box))
        if s is None:
            stats["miss_cell"] += 1
            details.append((box, want, "(AI không phát hiện ô này)", "-", "-"))
            continue

        got = s.get("date") or ""
        cands = [c.get("date") for c in (s.get("candidates") or [])]
        day_ok = bool(got) and got[:2] == want[:2]
        top_ok = (got == want) or (want in cands)
        conf = float(s.get("confidence") or 0.0)

        stats["total"] += 1
        stats["exact"] += (got == want)
        stats["top"] += top_ok
        stats["day"] += day_ok
        if got and got != want and conf >= engine.CONFIDENCE_MED:
            stats["dangerous"] += 1

        details.append((box, want, got or "(trống)", "DUNG" if top_ok else "SAI", f"{conf:.2f}"))
    return stats, details


def pct(part, whole):
    return round(part * 100.0 / whole, 1) if whole else 0.0


def main():
    only = ""
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    docs = load_ground_truth(only)
    if not docs:
        print(f"⚠️ Không có ground truth khả dụng trong {GT_PATH}")
        return 1

    engine = PDFGridOCREngine()
    grand = Counter()
    print("=" * 88)
    for pdf_path, info in docs.items():
        truth = info.get("sessions", {})
        print(f"📄 {os.path.basename(pdf_path)}  ({len(truth)} ô có ground truth)")
        if not os.path.exists(pdf_path):
            print("   ⚠️ BỎ QUA: không tìm thấy file trên máy này")
            continue

        stats, details = evaluate(engine, pdf_path, truth)
        grand.update(stats)
        for box, want, got, top, conf in details:
            mark = "✅" if got == want else ("🟡" if top == "DUNG" else "❌")
            print(f"   {mark} Ô#{box:>3}  người={want}  AI={got:<12}  conf={conf:<5} trong_gợi_ý={top}")
        print(f"   → EXACT {stats['exact']}/{stats['total']} ({pct(stats['exact'], stats['total'])}%)"
              f" | TOP-N {stats['top']}/{stats['total']} ({pct(stats['top'], stats['total'])}%)"
              f" | NGÀY {stats['day']}/{stats['total']} ({pct(stats['day'], stats['total'])}%)"
              f" | nguy hiểm {stats['dangerous']}")
        print("-" * 88)

    t = grand["total"]
    print("TỔNG KẾT TOÀN BỘ GROUND TRUTH")
    print(f"  Số ô có đáp án đúng (người đọc): {t}   (+{grand['miss_cell']} ô AI không phát hiện)")
    print(f"  EXACT  - AI tự điền đúng ngay:            {grand['exact']:>3}/{t} = {pct(grand['exact'], t)}%")
    print(f"  TOP-N  - đáp án đúng nằm trong gợi ý:     {grand['top']:>3}/{t} = {pct(grand['top'], t)}%")
    print(f"  NGÀY  - đọc đúng riêng phần ngày:         {grand['day']:>3}/{t} = {pct(grand['day'], t)}%")
    print(f"  NGUY HIỂM - điền SAI mà điểm >= {engine.CONFIDENCE_MED}: {grand['dangerous']} ô")
    print("\n  Lưu ý: EXACT là giới hạn của OCR với chữ viết tay này; TOP-N mới là thứ")
    print("  quyết định số lần người dùng phải tự gõ. Không có ô nào được đánh dấu")
    print("  'đã xác nhận' cho tới khi người dùng tích chọn trên UI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
