import os
import re
from pathlib import Path
from typing import Dict, Optional


class VietHealthPathParser:
    r"""
    Bóc tách Metadata từ đường dẫn OneDrive thực tế của dự án I3b:
    VD: .../2026.9.20/Can thiep/N6/ABP0055 Nguyễn Thị Ngần/CBP0853 Trần An Khang_ NNTL.pdf
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
            "warning": None,
            "error": None
        }

        if len(parts) < 4:
            result["error"] = "Đường dẫn thiếu cấp thư mục cha (Cán bộ / Nhóm / Kỳ)."
            return result

        filename_stem = path_obj.stem.strip()

        # 0. Định vị thư mục Kỳ báo cáo bằng mẫu ngày YYYY.M[.D] ở BẤT KỲ cấp nào
        #    (hỗ trợ cả cấu trúc cũ 2024: .../2024.09.15/GDDB/file.pdf - không có cấp Cán bộ)
        period_idx = None
        for i, part in enumerate(parts[:-1]):
            if re.match(r"^\d{4}[.\-/]\d{1,2}([.\-/]\d{1,2})?$", part.strip()):
                period_idx = i

        staff_folder = None
        if period_idx is not None:
            result["period"] = parts[period_idx].strip()
            inter = [p.strip() for p in parts[period_idx + 1:-1]]
            inter = [p for p in inter if p.lower() not in ("can thiep", "can thiệp", "can_thiep")]
            if len(inter) >= 2:
                result["group"], staff_folder = inter[-2], inter[-1]
            elif len(inter) == 1:
                result["group"] = inter[0]
        else:
            # Cấu trúc cũ: .../Ky/Can thiep/Nhom/CB file.pdf
            staff_folder = parts[-2].strip()
            group_folder = parts[-3].strip()

            period_candidate = parts[-4].strip()
            if period_candidate.lower() in ["can thiep", "can thiệp", "can_thiep"] and len(parts) >= 5:
                period_folder = parts[-5].strip()
            else:
                period_folder = period_candidate

            result["period"] = period_folder
            result["group"] = group_folder

        # 1. Bóc tách Cán bộ (cho phép vắng mặt ở cấu trúc 2024)
        if staff_folder:
            staff_match = re.match(r"^([A-Za-z0-9]+)\s*(?:[-_]\s*|\s+)(.+)$", staff_folder)
            if staff_match:
                result["staff_id"] = staff_match.group(1).strip().upper()
                result["staff_name"] = staff_match.group(2).strip()
            else:
                result["warning"] = f"Thư mục Cán bộ không đúng định dạng: '{staff_folder}'"

        # 2. Bóc tách Trẻ & Dịch vụ (hỗ trợ cả tên file test như Test_doc_PDF_2.pdf
        #    và file 2024 dạng 'CBP0001 Tên Trẻ.pdf' không có mã dịch vụ)
        if "_" not in filename_stem:
            code_match = re.match(r"^([A-Za-z]{2,5}\d{2,6})[\s\-_]+(.+)$", filename_stem)
            if code_match:
                result["child_id"] = code_match.group(1).strip().upper()
                result["child_name"] = code_match.group(2).strip()
            else:
                result["child_id"] = "TEST"
                result["child_name"] = filename_stem
            result["service"] = "CHƯA_RÕ"
            result["warning"] = f"Tên file thiếu '_' ngăn cách Dịch vụ: '{path_obj.name}'"
            result["is_valid"] = True
            return result

        child_part, service_raw = filename_stem.rsplit("_", 1)
        service_clean = service_raw.strip().upper()

        if service_clean == "GDDB":
            service_clean = "GDĐB"
        elif service_clean == "HDTL":
            service_clean = "HĐTL"

        result["service"] = service_clean
        if service_clean not in cls.VALID_SERVICES:
            # Hỗ trợ tên file dạng 'CBP2083 Tên Trẻ GDĐB_1.pdf' (mã dịch vụ nằm trong tên, '_1' là số bản)
            words = child_part.strip().split()
            if len(words) >= 2:
                last_norm = words[-1].upper()
                last_norm = {"GDDB": "GDĐB", "HDTL": "HĐTL"}.get(last_norm, last_norm)
                if last_norm in cls.VALID_SERVICES:
                    service_clean = last_norm
                    result["service"] = service_clean
                    child_part = " ".join(words[:-1])

        if service_clean not in cls.VALID_SERVICES:
            result["warning"] = (
                f"Tên file là file thử nghiệm hoặc mã dịch vụ '{service_clean}' "
                f"không nằm trong chuẩn {sorted(cls.VALID_SERVICES)}"
            )

        child_match = re.match(r"^([A-Za-zĐđ0-9]+)\s*(?:[-_]\s*|\s+)(.+)$", child_part.strip())
        if child_match:
            result["child_id"] = child_match.group(1).strip().upper()
            result["child_name"] = child_match.group(2).strip()
        else:
            result["child_id"] = "TEST"
            result["child_name"] = filename_stem

        result["is_valid"] = True
        return result


OneDriveFolderParser = VietHealthPathParser