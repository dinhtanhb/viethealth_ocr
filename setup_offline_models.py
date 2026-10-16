import os
from pathlib import Path
import easyocr
import fitz  # PyMuPDF
import cv2

def setup_environment():
    print("=" * 70)
    print("🚀 KHỞI TẠO HỆ THỐNG & ĐÓNG GÓI MODEL AI OFFLINE (100% LOCAL)")
    print("=" * 70)

    base_dir = Path(__file__).resolve().parent
    model_dir = base_dir / "local_models"
    snippet_dir = base_dir / "media_snippets"

    # Tạo các thư mục lưu trữ local
    model_dir.mkdir(exist_ok=True)
    snippet_dir.mkdir(exist_ok=True)

    print(f"✅ 1. Kiểm tra PyMuPDF (Đọc PDF): Phiên bản {fitz.__doc__.splitlines()[0] if fitz.__doc__ else 'OK'}")
    print(f"✅ 2. Kiểm tra OpenCV (Xử lý ảnh): Phiên bản {cv2.__version__}")

    print("\n⏳ 3. Đang kiểm tra & lưu trữ Model AI (EasyOCR) vào thư mục 'local_models/'...")
    print("   (Lưu ý: Chỉ lần đầu tiên này cần mạng để tải file trọng số ~80MB về ổ cứng.")
    print("    Từ các lần sau, App sẽ nạp trực tiếp từ 'local_models/' và chạy 100% Offline!)")

    try:
        # Khởi tạo EasyOCR và chỉ định lưu thẳng model vào thư mục local_models của dự án
        reader = easyocr.Reader(
            ['en'],  # Bộ ký tự Latin/Số (đọc số và giờ viết tay tốt nhất)
            gpu=False,  # Tự động chạy mượt trên CPU mọi máy tính văn phòng
            model_storage_directory=str(model_dir),
            download_enabled=True
        )
        print("\n🎉 THÀNH CÔNG! Model AI đã được lưu trữ an toàn tại:")
        for file in os.listdir(model_dir):
            file_path = model_dir / file
            size_mb = file_path.stat().st_size / (1024 * 1024)
            print(f"   📦 {file} ({size_mb:.1f} MB)")

        print("\n" + "=" * 70)
        print("✅ HỆ THỐNG ĐÃ SẴN SÀNG CHẠY 100% OFFLINE!")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Có lỗi khi khởi tạo Model AI: {str(e)}")

if __name__ == "__main__":
    setup_environment()