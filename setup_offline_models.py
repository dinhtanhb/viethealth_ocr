from pathlib import Path

import fitz  # PyMuPDF
import cv2

BASE_DIR = Path(__file__).resolve().parent


def print_tree(root: Path) -> None:
    """Liệt kê toàn bộ file model đã đóng gói trong dự án kèm dung lượng."""
    total_mb = 0.0
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        size_mb = file_path.stat().st_size / (1024 * 1024)
        total_mb += size_mb
        print(f"   📦 {file_path.relative_to(root)} ({size_mb:.1f} MB)")
    print(f"   ➡️ Tổng cộng: {total_mb:.1f} MB")


def setup_environment():
    print("=" * 70)
    print("🚀 KHỞI TẠO HỆ THỐNG & ĐÓNG GÓI MODEL AI OFFLINE (100% LOCAL)")
    print("=" * 70)

    # Duong dan model PHAI trung voi mac dinh `models_dir` cua PDFGridOCREngine
    # (core_engine/pdf_grid_ocr.py) - app doc model tu day.
    model_dir = BASE_DIR / "models_storage" / "paddlex"
    snippet_dir = BASE_DIR / "media_snippets"

    model_dir.mkdir(parents=True, exist_ok=True)
    snippet_dir.mkdir(exist_ok=True)

    print(f"✅ 1. Kiểm tra PyMuPDF (Đọc PDF): Phiên bản {fitz.__doc__.splitlines()[0] if fitz.__doc__ else 'OK'}")
    print(f"✅ 2. Kiểm tra OpenCV (Xử lý ảnh): Phiên bản {cv2.__version__}")

    print("\n⏳ 3. Đang kiểm tra & lưu trữ Model AI (PaddleOCR PP-OCRv6) vào 'models_storage/paddlex/'...")
    print("   (Lưu ý: Chỉ lần đầu tiên này cần mạng để tải trọng số về ổ cứng.")
    print("    Từ các lần sau, App sẽ nạp trực tiếp từ 'models_storage/paddlex/' và chạy 100% Offline!)")

    try:
        # Khoi tao dung engine cua app: moi thu (cache dir, ngat kiem tra mang,
        # enable_mkldnn=False) duoc gui trong chinh PDFGridOCREngine,
        # nen khong the lech duong dan model giua script luc cai va app luc chay.
        import sys

        sys.path.insert(0, str(BASE_DIR))
        from core_engine.pdf_grid_ocr import PDFGridOCREngine

        PDFGridOCREngine()

        print("\n🎉 THÀNH CÔNG! Model AI đã được lưu trữ an toàn tại:")
        print_tree(model_dir)

        print("\n" + "=" * 70)
        print("✅ HỆ THỐNG ĐÃ SẴN SÀNG CHẠY 100% OFFLINE!")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Có lỗi khi khởi tạo Model AI: {str(e)}")
        print("   Kiểm tra: (1) 'paddlepaddle' + 'paddleocr' đã cài trong venv,")
        print("   (2) lần chạy đầu tiên có kết nối mạng để tải trọng số.")


if __name__ == "__main__":
    setup_environment()
