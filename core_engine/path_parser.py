import os
import re
from pathlib import Path
from typing import Dict, Optional


class VietHealthPathParser:
    r"""
    Bóc tách Metadata chuẩn xác 100% từ đường dẫn OneDrive thực tế của dự án:
    VD: .../2026.9.20/Can thiep/N6/CB001 Cán Bộ Mẫu/TE001 Trẻ Mẫu_ NNTL.pdf
    """

    VALID_SERVICES = {"VLTL", "HDTL", "HĐTL", "NNTL", "GDDB", "GDĐB", "CSXH", "CSYT"}

    @classmethod
    def parse(cls, pdf_path: str) -> Dict[str, Optional[str]]:
        norm_path = os.path.normpath(pdf_path)
        path_obj = Path(norm_path)
        parts = path_obj.parts

        result = {
            "period": None,
            "group": None,
            "staff_id": None,
            "staff_name": None,
            "child_id": None,
            "child_name": None,
            "service": None,
            "file_path": norm_path,
            "is_valid": False,
            "error": None
        }

        if len(parts) < 4:
            result["error"] = "Đường dẫn thiếu cấp thư mục cha (Cán bộ / Nhóm / Kỳ)."
            return result

        filename_stem = path_obj.stem.strip()
        staff_folder = parts[-2].strip()
        group_folder = parts[-3].strip()

        # Xác định folder Kỳ (bỏ qua folder trung gian 'Can thiep' nếu có)
        period_candidate = parts[-4].strip()
        if period_candidate.lower() in ["can thiep", "can thiệp", "can_thiep"] and len(parts) >= 5:
            period_folder = parts[-5].strip()
        else:
            period_folder = period_candidate

        result["period"] = period_folder
        result["group"] = group_folder

        # 1. Bóc tách Cán bộ: "CB001 Cán Bộ Mẫu" hoặc "CB002 - Người Dùng Mẫu"
        staff_match = re.match(r"^([A-Za-z0-9]+)\s*(?:[-_]\s*|\s+)(.+)$", staff_folder)
        if staff_match:
            result["staff_id"] = staff_match.group(1).strip().upper()
            result["staff_name"] = staff_match.group(2).strip()
        else:
            result["error"] = f"Thư mục Cán bộ không đúng định dạng: '{staff_folder}'"
            return result

        # 2. Bóc tách Trẻ & Dịch vụ: "TE001 Trẻ Mẫu_ NNTL"
        if "_" not in filename_stem:
            result["error"] = f"Tên file thiếu dấu '_' ngăn cách Dịch vụ: '{path_obj.name}'"
            return result

        child_part, service_raw = filename_stem.rsplit("_", 1)
        service_clean = service_raw.strip().upper()

        # Chuẩn hóa mã dịch vụ
        if service_clean == "GDDB":
            service_clean = "GDĐB"
        elif service_clean == "HDTL":
            service_clean = "HĐTL"
        result["service"] = service_clean

        child_match = re.match(r"^([A-Za-zĐđ0-9]+)\s*(?:[-_]\s*|\s+)(.+)$", child_part.strip())
        if child_match:
            result["child_id"] = child_match.group(1).strip().upper()
            result["child_name"] = child_match.group(2).strip()
        else:
            result["error"] = f"Tên file không tách được Mã trẻ & Tên trẻ: '{child_part}'"
            return result

        result["is_valid"] = True
        return result


OneDriveFolderParser = VietHealthPathParser
