import os
import sys
import django
from urllib.parse import urlencode
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
            models_dir=os.path.join(BASE_DIR, "models_storage", "paddlex"),
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
        .badge-bad { background: #f8d7da; color: #842029; padding: 4px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
        .left { text-align: left !important; }
        .conf-pill { font-size: 11.5px; color: #1f4e78; font-weight: 700; }
        .chk-confirm { width: 17px; height: 17px; cursor: pointer; }
        .cand-box { margin-top: 4px; display: flex; flex-direction: column; gap: 3px; align-items: center; }
        .cand-box small { color: #777; font-size: 10.5px; }
        .cand-btn { padding: 3px 7px; font-size: 11.5px; border: 1px solid #1f4e78; background: #eef4fa;
                    color: #163a59; border-radius: 4px; cursor: pointer; font-weight: 600; }
        .cand-btn:hover { background: #1f4e78; color: #fff; }
        .cand-alt { border-style: dashed; background: #fff9e6; color: #856404; border-color: #b8860b; }
        .cand-alt:hover { background: #b8860b; color: #fff; }
        .btn-cal { margin-top: 4px; padding: 3px 8px; font-size: 11.5px; border: 1px solid #1f4e78;
                   background: #fff; color: #163a59; border-radius: 4px; cursor: pointer; font-weight: 600; }
        .btn-cal:hover { background: #eef4fa; }
        .btn-cal-empty { background: #b8860b; border-color: #b8860b; color: #fff; }
        .btn-cal-empty:hover { background: #8f6808; }
        .cal-pop { position: absolute; z-index: 2000; width: 262px; background: #fff; border: 1px solid #1f4e78;
                   border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,0.25); padding: 10px;
                   text-align: left; font-size: 12.5px; color: #222; }
        .cal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
        .cal-title { font-weight: 700; color: #1f4e78; }
        .cal-nav { border: 1px solid #99b8d9; background: #eef4fa; color: #163a59; border-radius: 4px;
                   padding: 3px 8px; cursor: pointer; font-weight: 600; font-size: 11.5px; }
        .cal-nav:hover { background: #1f4e78; color: #fff; }
        .cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
        .cal-dow { text-align: center; font-size: 10.5px; color: #666; font-weight: 700; padding: 2px 0; }
        .cal-day { text-align: center; padding: 4px 0; border: 1px solid transparent; border-radius: 4px;
                   cursor: pointer; background: #f7f9fb; }
        .cal-day:hover { background: #dce9f7; }
        .cal-blank { background: transparent; cursor: default; }
        .cal-sel { background: #1f4e78 !important; color: #fff; font-weight: 700; }
        .cal-today { border-color: #b8860b; }
        .cal-quick { display: flex; gap: 4px; margin-top: 7px; flex-wrap: wrap; }
        .cal-times { display: flex; gap: 8px; margin-top: 8px; }
        .cal-times label { font-size: 11px; color: #555; display: flex; flex-direction: column; gap: 2px; }
        .cal-times input { padding: 4px; border: 1px solid #aaa; border-radius: 4px; width: 88px; font-size: 12.5px; }
        .cal-actions { display: flex; gap: 6px; justify-content: flex-end; margin-top: 9px; }
        .cal-apply { padding: 6px 12px; font-size: 12.5px; }
        .cal-hint { font-size: 10.5px; color: #777; margin-top: 6px; }
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
            💡 <b>Mẹo:</b> AI tự đọc & điền Ngày vào từng dòng; nếu đọc ra nhiều phương án, bạn <b>bấm vào phương án đúng</b> bên dưới ô Ngày.
            Dòng <span class="badge-bad">🔴</span> (AI chưa đọc được ngày) → bấm <b>📅 Chọn ngày &amp; giờ</b> để mở <b>lịch</b>, chọn ngày rồi chọn <b>Giờ BĐ / Giờ KT</b> ngay trong lịch.
            Rê chuột vào <b>Ảnh cắt chữ viết tay</b> để phóng to 2.5x.
            Dòng <span class="badge-warn">🟡</span> / <span class="badge-bad">🔴</span> cần bạn kiểm tra kỹ.
            Tích ☑️ <b>Xác nhận</b> (hoặc sửa Ngày/Giờ) rồi nhấn <b>Lưu toàn bộ thay đổi</b> trước khi xuất Excel.
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
                    <th>Độ tin cậy AI</th>
                    <th>Trạng thái</th>
                    <th>Xác nhận</th>
                </tr>
            </thead>
            <tbody>
                {% for r in records %}
                <tr class="{% if not r.date or r.ocr_confidence < 0.4 %}row-warn{% endif %}">
                    <td>{{ forloop.counter }}</td>
                    <td><b>{{ r.period }}</b><br><span style="color:#555">{{ r.group }}</span></td>
                    <td class="left"><b>[{{ r.staff_id }}]</b><br>{{ r.staff_name }}</td>
                    <td class="left"><b>[{{ r.child_id }}]</b> {{ r.child_name }}<br><span class="badge-ok">{{ r.service }}</span></td>
                    <td>Buổi {{ r.session_order }}<br><small style="color:#666">(Ô/Trang #{{ r.box_number }})</small></td>
                    <td>
                        {% if r.snippet_name %}
                        <img src="/snippet/{{ r.snippet_name }}" class="snippet-img" alt="snippet"/>
                        {% endif %}
                    </td>
                    <td>
                        <input type="hidden" name="session_id" value="{{ r.session_id }}" />
                        <input type="text" name="date_{{ r.session_id }}" id="date_{{ r.session_id }}"
                               value="{{ r.date }}" class="inp-date" placeholder="DD/MM/YYYY" />
                        {% if r.candidates and r.candidates|length > 1 %}
                        <div class="cand-box">
                            <small>AI đọc ra {{ r.candidates|length }} phương án (bấm để chọn):</small>
                            {% for c in r.candidates %}
                            <button type="button" class="cand-btn{% if c.basis == 'confusable' %} cand-alt{% endif %}"
                                    title="{% if c.basis == 'confusable' %}⚠️ Phương án dự phòng: khả năng OCR nhầm nét chữ số (1/7, 8/9, 2/0) - chỉ bấm khi ảnh cắt rõ là số đó{% else %}Bấm để chọn Ngày này (đọc trực tiếp từ ảnh){% endif %}"
                                    onclick="pickDate('{{ r.session_id }}','{{ c.date }}')">{{ c.date }}{% if c.basis == 'confusable' %} <sup>?</sup>{% endif %}</button>
                            {% endfor %}
                        </div>
                        {% endif %}
                        <button type="button" class="btn-cal{% if not r.date %} btn-cal-empty{% endif %}"
                                title="Mở lịch chọn Ngày và Giờ (dùng khi AI chưa đọc được hoặc bạn cần sửa)"
                                onclick="openCal(this, '{{ r.session_id }}', '{{ r.period|escapejs }}')">📅 Chọn ngày &amp; giờ</button>
                    </td>
                    <td>
                        <input type="text" name="start_{{ r.session_id }}" id="start_{{ r.session_id }}" value="{{ r.start_time }}" class="inp-time" placeholder="08:00" />
                    </td>
                    <td>
                        <input type="text" name="end_{{ r.session_id }}" id="end_{{ r.session_id }}" value="{{ r.end_time }}" class="inp-time" placeholder="09:00" />
                    </td>
                    <td><small style="color:#666; font-family:monospace;">{{ r.raw_ocr }}</small></td>
                    <td>
                        {% if r.date %}<span class="conf-pill">{{ r.ocr_confidence|floatformat:2 }}</span>{% else %}—{% endif %}
                    </td>
                    <td id="status_{{ r.session_id }}">
                        {% if not r.date %}
                            <span class="badge-bad">🔴 Chưa đọc được – bấm 📅 chọn ngày &amp; giờ</span>
                        {% elif r.ocr_confidence >= 0.60 %}
                            <span class="badge-ok">🟢 AI tự đọc chắc chắn</span>
                        {% elif r.candidates and r.candidates|length > 1 %}
                            <span class="badge-warn">🟡 Nhiều phương án – bấm chọn</span>
                        {% else %}
                            <span class="badge-warn">🟡 Tin cậy thấp – cần soát</span>
                        {% endif %}
                    </td>
                    <td>
                        <input type="checkbox" name="confirm_{{ r.session_id }}" value="1" class="chk-confirm"
                               {% if r.is_verified and r.date %}checked{% endif %} title="Tích khi bạn đã đối chiếu ảnh và xác nhận Ngày này" />
                    </td>
                </tr>
                {% empty %}
                <tr>
                    <td colspan="13" style="padding: 30px; color: #777;">
                        Chưa có dữ liệu. Hãy dán đường dẫn File PDF hoặc Thư mục vào ô phía trên và bấm <b>Quét AI OCR</b>!
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </form>
</div>
<script>
function pickDate(sid, val) {
    var el = document.getElementById('date_' + sid);
    if (!el) return;
    el.value = val;
    el.style.background = '#dff0d8';
    // Bấm chọn = người dùng đã đối chiếu => tick sẵn ô Xác nhận
    var chk = document.querySelector('input[name="confirm_' + sid + '"]');
    if (chk) chk.checked = true;
}

/* =====================================================================
   LỊCH CHỌN NGÀY + GIỜ tự chứa (không thư viện ngoài, chạy 100% offline).
   Dùng cho dòng AI chưa đọc được ngày (🔴) và để sửa cả dòng AI đã đọc.
   ===================================================================== */
var CAL_DOW = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];
var CAL_MONTH = ['Tháng 1', 'Tháng 2', 'Tháng 3', 'Tháng 4', 'Tháng 5', 'Tháng 6',
                 'Tháng 7', 'Tháng 8', 'Tháng 9', 'Tháng 10', 'Tháng 11', 'Tháng 12'];
var _cal = null;

function calPad2(n) { return (n < 10 ? '0' : '') + n; }

/* Đọc chuỗi ngày DD/MM/YYYY (chấp nhận 1/8/2024, 01-08-2024, 8.9.24) */
function calParseVN(s) {
    var p = (s || '').replace(/[^0-9]+/g, ' ').trim().split(' ');
    if (p.length !== 3) return null;
    var d = parseInt(p[0], 10), mo = parseInt(p[1], 10), y = parseInt(p[2], 10);
    if (y < 100) y += 2000;
    if (!d || !mo || mo > 12 || d > 31) return null;
    var dt = new Date(y, mo - 1, d);
    if (dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
    return dt;
}

/* Thư mục Kỳ có dạng YYYY.M[.D] -> mở lịch đúng tháng của kỳ đó */
function calParsePeriod(s) {
    var p = (s || '').replace(/[^0-9]+/g, ' ').trim().split(' ');
    if (p.length < 2) return null;
    var y = parseInt(p[0], 10), mo = parseInt(p[1], 10);
    if (y < 1900 || y > 2100 || mo < 1 || mo > 12) return null;
    var d = p.length > 2 ? parseInt(p[2], 10) : 1;
    if (!d || d > 31) d = 1;
    return new Date(y, mo - 1, d);
}

function calNormTime(v) {
    v = (v || '').trim();
    if (!v) return '';
    var p = v.split(':');
    var h = parseInt(p[0], 10), mi = p.length > 1 ? parseInt(p[1], 10) : 0;
    if (isNaN(h) || isNaN(mi) || h > 23 || mi > 59) return v;
    return calPad2(h) + ':' + calPad2(mi);
}

function openCal(btn, sid, period) {
    closeCal();
    var dEl = document.getElementById('date_' + sid);
    if (!dEl) return;
    var sEl = document.getElementById('start_' + sid);
    var eEl = document.getElementById('end_' + sid);
    var sel = calParseVN(dEl.value);
    var periodDate = calParsePeriod(period);
    var anchor = sel || periodDate || new Date();
    _cal = {
        sid: sid,
        btn: btn,
        sel: sel,
        period: periodDate,
        periodLabel: period || '',
        view: new Date(anchor.getFullYear(), anchor.getMonth(), 1),
        start: sEl ? calNormTime(sEl.value) : '',
        end: eEl ? calNormTime(eEl.value) : ''
    };
    var pop = document.createElement('div');
    pop.className = 'cal-pop';
    pop.id = 'cal_pop';
    document.body.appendChild(pop);
    calRender();
    calPosition();
}

function calPosition() {
    var pop = document.getElementById('cal_pop');
    if (!pop || !_cal || !_cal.btn) return;
    var r = _cal.btn.getBoundingClientRect();
    var docW = document.documentElement.clientWidth;
    var docH = document.documentElement.clientHeight;
    var left = r.left + window.pageXOffset;
    var top = r.bottom + window.pageYOffset + 4;
    var maxLeft = window.pageXOffset + docW - pop.offsetWidth - 8;
    var maxTop = window.pageYOffset + docH - pop.offsetHeight - 8;
    if (left > maxLeft) left = Math.max(window.pageXOffset + 8, maxLeft);
    if (top > maxTop) top = maxTop;   /* không để lịch bị cắt đáy màn hình */
    if (top < window.pageYOffset + 8) top = window.pageYOffset + 8;
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
}

function calSyncTimes() {
    if (!_cal) return;
    var s = document.getElementById('cal_start');
    var e = document.getElementById('cal_end');
    if (s) _cal.start = calNormTime(s.value);
    if (e) _cal.end = calNormTime(e.value);
}

function calRender() {
    if (!_cal) return;
    calSyncTimes();
    var pop = document.getElementById('cal_pop');
    if (!pop) return;
    var y = _cal.view.getFullYear(), mo = _cal.view.getMonth();
    var firstDow = (new Date(y, mo, 1).getDay() + 6) % 7;
    var days = new Date(y, mo + 1, 0).getDate();
    var today = new Date();
    var html = '';
    html += '<div class="cal-head"><button type="button" class="cal-nav" onclick="calMove(-1)">&#9664;</button>';
    html += '<span class="cal-title">' + CAL_MONTH[mo] + ' ' + y + '</span>';
    html += '<button type="button" class="cal-nav" onclick="calMove(1)">&#9654;</button></div>';
    html += '<div class="cal-grid">';
    for (var i = 0; i < 7; i++) html += '<div class="cal-dow">' + CAL_DOW[i] + '</div>';
    for (var b = 0; b < firstDow; b++) html += '<div class="cal-day cal-blank"></div>';
    for (var d = 1; d <= days; d++) {
        var cls = 'cal-day';
        if (_cal.sel && _cal.sel.getFullYear() === y && _cal.sel.getMonth() === mo && _cal.sel.getDate() === d) {
            cls += ' cal-sel';
        } else if (d === today.getDate() && mo === today.getMonth() && y === today.getFullYear()) {
            cls += ' cal-today';
        }
        html += '<div class="' + cls + '" onclick="calPick(' + d + ')">' + d + '</div>';
    }
    html += '</div>';
    html += '<div class="cal-quick">';
    if (_cal.period) html += '<button type="button" class="cal-nav" onclick="calJump(&#39;p&#39;)">Tháng của kỳ ' + _cal.periodLabel + '</button>';
    html += '<button type="button" class="cal-nav" onclick="calJump(&#39;t&#39;)">Hôm nay</button>';
    html += '</div>';
    html += '<div class="cal-times"><label>Giờ bắt đầu<input type="time" id="cal_start" value="' + _cal.start + '"></label>';
    html += '<label>Giờ kết thúc<input type="time" id="cal_end" value="' + _cal.end + '"></label></div>';
    html += '<div class="cal-actions"><button type="button" class="cal-nav" onclick="closeCal()">Hủy</button>';
    html += '<button type="button" class="cal-nav cal-apply" onclick="calApply()">✅ Áp dụng</button></div>';
    html += '<div class="cal-hint">Chọn ngày trong lịch, chọn Giờ BĐ / Giờ KT rồi bấm Áp dụng. Ngày do bạn nhập tay sẽ được tick ☑️ Xác nhận; độ tin cậy AI không bị ghi đè điểm.</div>';
    pop.innerHTML = html;
}

function calMove(n) {
    if (!_cal) return;
    _cal.view = new Date(_cal.view.getFullYear(), _cal.view.getMonth() + n, 1);
    calRender();
}

function calPick(d) {
    if (!_cal) return;
    _cal.sel = new Date(_cal.view.getFullYear(), _cal.view.getMonth(), d);
    calRender();
}

function calJump(what) {
    if (!_cal) return;
    if (what === 'p' && _cal.period) {
        _cal.view = new Date(_cal.period.getFullYear(), _cal.period.getMonth(), 1);
    } else if (what === 't') {
        var now = new Date();
        _cal.sel = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        _cal.view = new Date(now.getFullYear(), now.getMonth(), 1);
    }
    calRender();
}

function calApply() {
    if (!_cal) return;
    if (!_cal.sel) { alert('Bạn chưa chọn ngày trên lịch.'); return; }
    calSyncTimes();
    var sid = _cal.sid;
    var dEl = document.getElementById('date_' + sid);
    var sEl = document.getElementById('start_' + sid);
    var eEl = document.getElementById('end_' + sid);
    if (!dEl) { closeCal(); return; }
    dEl.value = calPad2(_cal.sel.getDate()) + '/' + calPad2(_cal.sel.getMonth() + 1) + '/' + _cal.sel.getFullYear();
    dEl.style.background = '#dff0d8';
    if (sEl && _cal.start) sEl.value = _cal.start;
    if (eEl && _cal.end) eEl.value = _cal.end;
    var chk = document.querySelector('input[name="confirm_' + sid + '"]');
    if (chk) chk.checked = true;
    var cell = document.getElementById('status_' + sid);
    if (cell) cell.innerHTML = '<span class="badge-ok">📅 Ngày giờ do người dùng chọn</span>';
    closeCal();
}

function closeCal() {
    var pop = document.getElementById('cal_pop');
    if (pop && pop.parentNode) pop.parentNode.removeChild(pop);
    _cal = null;
}

document.addEventListener('click', function (ev) {
    var pop = document.getElementById('cal_pop');
    if (!pop) return;
    if (pop.contains(ev.target)) return;
    var cn = String(ev.target.className || '');
    if (cn.indexOf('btn-cal') >= 0) return; /* bấm nút 📅 dòng khác -> openCal tự mở lại */
    closeCal();
});
document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeCal(); });
window.addEventListener('scroll', function () { calPosition(); }, true);
window.addEventListener('resize', function () { calPosition(); });
</script>
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
            return redirect("/?" + urlencode({"msg": f"❌ Không tìm thấy đường dẫn: {target_path}", "path": target_path}))

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
        total_with_date = 0
        total_multi = 0
        for pdf_file in pdf_files:
            meta = VietHealthPathParser.parse(pdf_file)
            prefix = f"{meta.get('child_id') or 'DOC'}_{scanned_count + 1}"
            sessions = engine.process_pdf(pdf_file, prefix=prefix, period_folder=meta.get("period"))
            db.save_document_and_sessions(meta, sessions)
            scanned_count += 1
            total_sessions += len(sessions)
            total_with_date += sum(1 for s in sessions if s.get("date"))
            total_multi += sum(1 for s in sessions if len(s.get("candidates") or []) > 1)

        if total_sessions:
            pct = round(total_with_date * 100.0 / total_sessions)
            # Day ro: day la DO PHU (so o AI dien duoc), KHONG phai do CHINH XAC.
            coverage = (f" | 🤖 AI điền được Ngày ở {total_with_date}/{total_sessions} ô ({pct}% độ phủ, "
                        f"chưa phải độ chính xác)")
            if total_multi:
                coverage += f" | 🟡 {total_multi} ô AI đọc ra nhiều phương án - bạn bấm chọn 1 cái"
            coverage += " | ⚠️ Bắt buộc đối chiếu ảnh cắt trước khi tick Xác nhận"
        else:
            coverage = " | ⚠️ Không phát hiện ô chữ viết tay nào"

        return redirect("/?" + urlencode({
            "msg": f"✅ Đã quét xong {scanned_count} file PDF ({total_sessions} buổi can thiệp)!{coverage}",
            "path": target_path,
        }))
    return redirect("/")


def save_all_view(request):
    if request.method == "POST":
        session_ids = request.POST.getlist("session_id")
        for sid in session_ids:
            d_val = request.POST.get(f"date_{sid}", "")
            st_val = request.POST.get(f"start_{sid}", "")
            et_val = request.POST.get(f"end_{sid}", "")
            confirmed = request.POST.get(f"confirm_{sid}") == "1"
            db.update_session(int(sid), d_val, st_val, et_val, verified=confirmed)
        return redirect("/?msg=💾 Đã lưu thành công toàn bộ thông tin Ngày và Giờ (kèm trạng thái xác nhận)!")
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