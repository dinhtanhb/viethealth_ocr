import os
from datetime import datetime
from typing import List, Dict
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


class VietHealthExcelExporter:
    """
    Xuất dữ liệu chấm công can thiệp từ PDF/Web App ra file Excel (.xlsx) chuẩn báo cáo.
    """

    HEADERS = [
        "STT",
        "Kỳ báo cáo",
        "Nhóm / Đơn vị",
        "Mã Cán bộ",
        "Họ và tên Cán bộ",
        "Mã Trẻ",
        "Họ và tên Trẻ",
        "Dịch vụ",
        "Buổi thứ",
        "Ô số (Bảng 30 ô)",
        "Ngày can thiệp",
        "Giờ bắt đầu",
        "Giờ kết thúc",
        "Trạng thái kiểm duyệt",
        "Tên file PDF gốc"
    ]

    @classmethod
    def export_records(cls, records: List[Dict], output_path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Du_Lieu_Can_Thiep"

        # Định dạng Style
        header_font = Font(name="Times New Roman", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        data_font = Font(name="Times New Roman", size=11)
        warn_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")

        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9")
        )

        # Ghi Header
        ws.append(cls.HEADERS)
        for col_num in range(1, len(cls.HEADERS) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border
        ws.row_dimensions[1].height = 28

        # Ghi từng dòng dữ liệu buổi can thiệp
        row_idx = 2
        for item in records:
            is_verified = item.get("is_verified", False)
            date_val = item.get("date") or ""
            status_text = "Đã duyệt" if is_verified else ("Đủ Ngày" if date_val else "Cần kiểm tra")

            row_data = [
                row_idx - 1,
                item.get("period", ""),
                item.get("group", ""),
                item.get("staff_id", ""),
                item.get("staff_name", ""),
                item.get("child_id", ""),
                item.get("child_name", ""),
                item.get("service", ""),
                item.get("session_order", ""),
                f"Ô #{item.get('box_number', '')}",
                date_val,
                item.get("start_time") or "",
                item.get("end_time") or "",
                status_text,
                os.path.basename(item.get("file_path", ""))
            ]
            ws.append(row_data)

            for col_num in range(1, len(cls.HEADERS) + 1):
                c = ws.cell(row=row_idx, column=col_num)
                c.font = data_font
                c.border = thin_border
                if col_num in (1, 2, 3, 4, 6, 8, 9, 10, 11, 12, 13, 14):
                    c.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    c.alignment = Alignment(horizontal="left", vertical="center")

                if not date_val:
                    c.fill = warn_fill

            ws.row_dimensions[row_idx].height = 22
            row_idx += 1

        # Tự động căn chỉnh độ rộng cột
        col_widths = [6, 13, 16, 13, 24, 13, 24, 10, 10, 15, 15, 13, 13, 18, 35]
        for idx, width in enumerate(col_widths, start=1):
            ws.column_dimensions[get_column_letter(idx)].width = width

        ws.auto_filter.ref = ws.dimensions
        ws.freeze_panes = "A2"

        wb.save(output_path)
        return os.path.abspath(output_path)