# -*- coding: utf-8 -*-
"""
Smoke test giao diện lịch chọn Ngày + Giờ (KHÔNG cần OCR, không cần browser).

Render HTML_TEMPLATE của web_app.py với 2 dòng giả (1 dòng AI chưa đọc được ngày,
1 dòng AI đã đọc) rồi kiểm tra:
  1) Nút 📅 có mặt trên mọi dòng, nổi bật ở dòng trống ngày;
  2) JS lịch nằm nguyên vẹn trong trang (hàm mở lịch, ô giờ BĐ/KT, tháng tiếng Việt);
  3) Không có dấu hiệu escaped-quote bị Python ăn mất làm hỏng <script>
     (số dấu nháy đơn trên mỗi dòng JS phải chẵn - lỗi này từng làm chết cả khối script).

Cách dùng:
    python test_ui_calendar.py
"""
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import web_app  # cấu hình Django in-process (settings.configure)

from django.template import Engine, Context


def fake_records():
    return [
        {
            "session_id": 101, "period": "2026.10.20", "group": "N6", "staff_id": "ABP0055",
            "staff_name": "Nguyễn Thị Ngắn", "child_id": "C01", "child_name": "Trẻ A",
            "service": "AM", "session_order": 1, "box_number": 1, "snippet_name": "",
            "date": "", "start_time": "", "end_time": "", "raw_ocr": "",
            "ocr_confidence": 0.0, "is_verified": 0, "candidates": [],
        },
        {
            "session_id": 102, "period": "2024.09.15", "group": "N1", "staff_id": "CBP0007",
            "staff_name": "Trần Văn B", "child_id": "C02", "child_name": "Trẻ B",
            "service": "OT", "session_order": 5, "box_number": 5, "snippet_name": "",
            "date": "05/09/2024", "start_time": "08:00", "end_time": "09:30", "raw_ocr": "x",
            "ocr_confidence": 0.95, "is_verified": 0,
            "candidates": [{"date": "05/09/2024", "basis": "separator", "guessed": False},
                           {"date": "25/09/2024", "basis": "confusable", "guessed": True}],
        },
    ]


def script_blocks(html):
    return re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S)


def main():
    html = Engine.get_default().from_string(web_app.HTML_TEMPLATE).render(
        Context({"records": fake_records(), "message": "", "last_path": ""}))

    checks = {
        "mọi dòng đều có nút 📅 mở lịch": html.count('onclick="openCal(') == 2,
        "dòng chưa có ngày dùng nút nổi bật": 'class="btn-cal btn-cal-empty"' in html,
        "dòng đã có ngày vẫn có nút sửa": 'class="btn-cal"' in html,
        "có id để JS ghi ngược Giờ BĐ/KT": 'id="start_101"' in html and 'id="end_101"' in html,
        "có id ô Trạng thái để đổi nhãn": 'id="status_101"' in html,
        "nhãn 🔴 chỉ dẫn tới lịch": "bấm 📅 chọn ngày" in html,
        "JS lịch tự chứa đã nhúng": all(s in html for s in (
            "function openCal(", "function calRender(", "function calApply(",
            'id="cal_start"', 'id="cal_end"', "var CAL_MONTH")),
        "lịch có tháng + thứ tiếng Việt": ("'Tháng 1', 'Tháng 2'" in html
                                    and "'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'" in html),
    }

    # Bắt lỗi escaped-quote: mỗi dòng JS phải có số dấu nháy đơn chẵn.
    bad_lines = []
    for block in script_blocks(html):
        for no, line in enumerate(block.splitlines(), start=1):
            if line.count("'") % 2 != 0:
                bad_lines.append((no, line.strip()[:90]))
    checks["không có dòng JS nào lệch nháy đơn (hỏng <script>)"] = not bad_lines

    ok = True
    for name, passed in checks.items():
        print(("PASS  " if passed else "FAIL  ") + name)
        ok = ok and passed
    for no, line in bad_lines:
        print(f"      dòng JS lệch nháy: {no}: {line}")

    print("\nKẾT LUẬN:", "OK - lịch Ngày+Giờ đã nằm trong UI" if ok else "CÓ LỖI - xem FAIL ở trên")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
