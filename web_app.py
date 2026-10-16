import os
import sys
import django
from django.conf import settings
from django.core.management import execute_from_command_line
from django.http import HttpResponse, JsonResponse, FileResponse, Http404
from django.urls import path
from django.shortcuts import render, redirect

from core_engine.path_parser import VietHealthPathParser
from core_engine.pdf_grid_ocr import PDFGridOCREngine
from core_engine.local_db import LocalOCRDatabase
from core_engine.excel_exporter import VietHealthExcelExporter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY="viethealth-offline-local-secret-key",
        ALLOWED_HOSTS=["*"],
        ROOT_URLCONF=__name__,
        MIDDLEWARE=[
            "django.middleware.common.CommonMiddleware",
        ],
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [os.path.join(BASE_DIR, "templates")],
                "APP_DIRS": True,
            }
        ],
    )
    django.setup()

db = LocalOCRDatabase(os.path.join(BASE_DIR, "viethealth_ocr.sqlite3"))
ocr_engine = None


def get_ocr_engine():
    global ocr_engine
    if ocr_engine is None:
        ocr_engine = PDFGridOCREngine(
            models_dir=os.path.join(BASE_DIR, "models_storage", "easyocr"),
            snippets_dir=os.path.join(BASE_DIR, "media_snippets")
        )
    return ocr_engine


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>VietHealth I3b - Hệ thống OCR Chấm Công Can Thiệp (100% Offline)</title>
    <style>
        body { font-family: 'Segoe UI', Arial, sans-serif; background: #f4f6f9; margin: 0; padding: 20px; color: #222; }
        .container { max-width: 1450px; margin: 0 auto; background: #fff; padding: 24px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }
        h1 { margin-top: 0; color: #1f4e78; font-size: 22px; display: flex; justify-content: space-between; align-items: center; }
        .scan-box { background: #eef4fa; padding: 16px; border-radius: 8px; border: 1px solid #c5d9ed; margin-bottom: 20px; }
        .scan-form { display: flex; gap: 10px; align-items: center; }
        .scan-form input[type="text"] { flex: 1; padding: 10px 14px; font-size: 14px; border: 1px solid #99b8d9; border-radius: 6px; }
        .btn { padding: 10px 18px; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-block; }
        .btn-primary { background: #1f4e78; color: #fff; }
        .btn-primary:hover { background: #163a59; }
        .btn-success { background: #217346; color: #fff; }
        .btn-success:hover { background: #185935; }
        .msg { padding: 10px 14px; background: #d4edda; color: #155724; border-radius: 6px; margin-bottom: 16px; font-weight: 500; }
        table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
        th { background: #1f4e78; color: #fff; padding: 10px 8px; text-align: center; position: sticky; top: 0; }
        td { padding: 8px; border-bottom: 1px solid #e1e6eb; vertical-align: middle; text-align: center; }
        tr:hover { background: #f8fbff; }
        .row-warn { background: #fff9e6; }
        .snippet-img { height: 48px; border: 1px solid #ccc; border-radius: 4px; background: #fff; transition: transform 0.15s; cursor: zoom-in; }
        .snippet-img:hover { transform: scale(2.4); z-index: 999; position: relative; box-shadow: 0 4px 16px rgba(0,0,0,0.3); }
        .inp-date { width: 105px; padding: 6px; text-align: center; font-weight: bold; border: 1px solid #aaa; border-radius: 4px; font-size: 13.5px; }
        .inp-time { width: 68px; padding: 6px; text-align: center; border: 1px solid #aaa; border-radius: 4px; font-size: 13.5px; }
        .badge-ok { background: #d4edda; color: #155724; padding: 4px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
        .badge-warn { background: #fff3cd; color: #856404; padding: 4px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
        .left { text-align: left !important; }
    </style>
</head>
<body>
<div class="container">
    <h1>
        <span>🏥 VIETHEALTH I3b - PHẦN MỀM ĐỌC PHIẾU CAN THIỆP PDF & XUẤT EXCEL (100% OFFLINE)</span>
        <a href="/export-excel/" class="btn btn-success">📥 Xuất File Excel (.xlsx)</a>
    </h1>

    <div class="scan-box">
        <form method="POST" action="/scan/" class="scan-form">
            <input type="text" name="target_path" value="{{ last_path }}"
                   placeholder="Dán đường dẫn 1 file PDF hoặc cả Thư mục Kỳ OneDrive (VD: D:\\VietHealth\\...\\2026.9.20\\Can thiep)" required />
            <button type="submit" class="btn btn-primary">🔍 Quét AI OCR (PDF / Thư mục)</button>
        </form>
        <div style="margin-top:6px; font-size:12.5px; color:#555;">
            💡 <b>Mẹo:</b> Rê chuột vào <b>Ảnh cắt chữ viết tay</b> để phóng to 2.5x. Sau khi sửa Ngày/Giờ trên bảng, nhấn <b>Lưu toàn bộ thay đổi</b> trước khi xuất Excel.
        </div>
    </div>

    {% if message %}
    <div class="msg">{{ message }}</div>
    {% endif %}

    <form method="POST" action="/save-all/">
        <div style="margin-bottom: 12px; display:flex; justify-content:space-between; align-items:center;">
            <b>Tổng số buổi can thiệp đã bóc tách: {{ records|length }} buổi</b>
            <button type="submit" class="btn btn-primary">💾 Lưu toàn bộ thay đổi Ngày / Giờ</button>
        </div>

        <table>
            <thead>
                <tr>
                    <th>STT</th>
                    <th>Kỳ / Nhóm</th>
                    <th>Cán bộ Can thiệp</th>
                    <th>Trẻ & Dịch vụ</th>
                    <th>Buổi (Ô)</th>
                    <th>Ảnh chữ viết tay trên PDF (Rê chuột phóng to)</th>
                    <th>Ngày CT (DD/MM/YYYY)</th>
                    <th>Giờ BĐ</th>
                    <th>Giờ KT</th>
                    <th>Raw OCR</th>
                    <th>Trạng thái</th>
                </tr>
            </thead>
            <tbody>
                {% for r in records %}
                <tr class="{% if not r.date %}row-warn{% endif %}">
                    <td>{{ forloop.counter }}</td>
                    <td><b>{{ r.period }}</b><br><span style="color:#555">{{ r.group }}</span></td>
                    <td class="left"><b>[{{ r.staff_id }}]</b><br>{{ r.staff_name }}</td>
                    <td class="left"><b>[{{ r.child_id }}]</b> {{ r.child_name }}<br><span class="badge-ok">{{ r.service }}</span></td>
                    <td>Buổi {{ r.session_order }}<br><small style="color:#666">(Ô #{{ r.box_number }})</small></td>
                    <td>
                        {% if r.snippet_name %}
                        <img src="/snippet/{{ r.snippet_name }}" class="snippet-img" alt="snippet"/>
                        {% endif %}
                    </td>
                    <td>
                        <input type="hidden" name="session_id" value="{{ r.session_id }}" />
                        <input type="text" name="date_{{ r.session_id }}" value="{{ r.date }}" class="inp-date" placeholder="DD/MM/YYYY" />
                    </td>
                    <td>
                        <input type="text" name="start_{{ r.session_id }}" value="{{ r.start_time }}" class="inp-time" placeholder="08:00" />
                    </td>
                    <td>
                        <input type="text" name="end_{{ r.session_id }}" value="{{ r.end_time }}" class="inp-time" placeholder="09:00" />
                    </td>
                    <td><small style="color:#666; font-family:monospace;">{{ r.raw_ocr }}</small></td>
                    <td>
                        {% if r.date %}
                            <span class="badge-ok">🟢 Đã có Ngày</span>
                        {% else %}
                            <span class="badge-warn">🟡 Cần nhập/kiểm tra</span>
                        {% endif %}
                    </td>
                </tr>
                {% empty %}
                <tr>
                    <td colspan="11" style="padding: 30px; color: #777;">
                        Chưa có dữ liệu. Hãy dán đường dẫn File PDF hoặc Thư mục vào ô phía trên và bấm <b>Quét AI OCR</b>!
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </form>
</div>
</body>
</html>
"""


def dashboard_view(request):
    from django.template import Engine, Context
    records = db.get_all_sessions_joined()
    for r in records:
        r["snippet_name"] = os.path.basename(r["snippet_path"]) if r.get("snippet_path") else ""

    msg = request.GET.get("msg", "")
    last_path = request.GET.get(
        "path",
        r"D:\VietHealth\INC3b - Documents\6. Bao cao\7. Ho so can thiep\2. Ho so theo ky\2026.10.20\Can thiep\N6\ABP0055 Nguyễn Thị Ngần\Test_doc_PDF_2.pdf"
    )
    engine = Engine.get_default()
    template = engine.from_string(HTML_TEMPLATE)
    html = template.render(Context({"records": records, "message": msg, "last_path": last_path}))
    return HttpResponse(html)


def scan_view(request):
    if request.method == "POST":
        target_path = request.POST.get("target_path", "").strip().strip('"')
        if not os.path.exists(target_path):
            return redirect(f"/?msg=❌ Không tìm thấy đường dẫn: {target_path}&path={target_path}")

        pdf_files = []
        if os.path.isfile(target_path) and target_path.lower().endswith(".pdf"):
            pdf_files.append(target_path)
        elif os.path.isdir(target_path):
            for root, _, files in os.walk(target_path):
                for f in files:
                    if f.lower().endswith(".pdf"):
                        pdf_files.append(os.path.join(root, f))

        engine = get_ocr_engine()
        scanned_count = 0
        total_sessions = 0
        for pdf_file in pdf_files:
            meta = VietHealthPathParser.parse(pdf_file)
            prefix = f"{meta.get('child_id') or 'DOC'}_{scanned_count + 1}"
            sessions = engine.process_pdf(pdf_file, prefix=prefix)
            db.save_document_and_sessions(meta, sessions)
            scanned_count += 1
            total_sessions += len(sessions)

        return redirect(f"/?msg=✅ Đã quét xong {scanned_count} file PDF ({total_sessions} buổi can thiệp)!&path={target_path}")
    return redirect("/")


def save_all_view(request):
    if request.method == "POST":
        session_ids = request.POST.getlist("session_id")
        for sid in session_ids:
            d_val = request.POST.get(f"date_{sid}", "")
            st_val = request.POST.get(f"start_{sid}", "")
            et_val = request.POST.get(f"end_{sid}", "")
            db.update_session(int(sid), d_val, st_val, et_val)
        return redirect("/?msg=💾 Đã lưu thành công toàn bộ thông tin Ngày & Giờ!")
    return redirect("/")


def export_excel_view(request):
    records = db.get_all_sessions_joined()
    out_dir = os.path.join(BASE_DIR, "exports")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "Bao_Cao_Can_Thiep_VietHealth.xlsx")
    VietHealthExcelExporter.export_records(records, out_file)
    return FileResponse(open(out_file, "rb"), as_attachment=True, filename="Bao_Cao_Can_Thiep_VietHealth.xlsx")


def snippet_image_view(request, filename):
    img_path = os.path.join(BASE_DIR, "media_snippets", os.path.basename(filename))
    if not os.path.exists(img_path):
        raise Http404("Không tìm thấy ảnh snippet")
    return FileResponse(open(img_path, "rb"), content_type="image/jpeg")


urlpatterns = [
    path("", dashboard_view),
    path("scan/", scan_view),
    path("save-all/", save_all_view),
    path("export-excel/", export_excel_view),
    path("snippet/<str:filename>", snippet_image_view),
]

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv += ["runserver", "0.0.0.0:8000", "--noreload"]
    execute_from_command_line(sys.argv)