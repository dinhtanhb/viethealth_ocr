import os
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional


class LocalOCRDatabase:
    """
    Quản lý cơ sở dữ liệu SQLite cục bộ (100% Offline):
    - Lưu thông tin Hồ sơ PDF (Metadata lấy từ đường dẫn OneDrive)
    - Lưu từng buổi can thiệp (30 ô), kèm đường dẫn ảnh cắt snippet để đối chiếu trên Web
    """

    def __init__(self, db_path: str = "viethealth_ocr.sqlite3"):
        self.db_path = db_path
        self._init_tables()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pdf_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE,
                    period TEXT,
                    group_name TEXT,
                    staff_id TEXT,
                    staff_name TEXT,
                    child_id TEXT,
                    child_name TEXT,
                    service TEXT,
                    total_sessions INTEGER DEFAULT 0,
                    scanned_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS intervention_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id INTEGER,
                    session_order INTEGER,
                    box_number INTEGER,
                    date_str TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    raw_ocr TEXT,
                    snippet_path TEXT,
                    is_verified INTEGER DEFAULT 0,
                    FOREIGN KEY(doc_id) REFERENCES pdf_documents(id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    def save_document_and_sessions(self, meta: Dict, sessions: List[Dict]) -> int:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO pdf_documents (
                    file_path, period, group_name, staff_id, staff_name,
                    child_id, child_name, service, total_sessions, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    period=excluded.period,
                    group_name=excluded.group_name,
                    staff_id=excluded.staff_id,
                    staff_name=excluded.staff_name,
                    child_id=excluded.child_id,
                    child_name=excluded.child_name,
                    service=excluded.service,
                    total_sessions=excluded.total_sessions,
                    scanned_at=excluded.scanned_at
            """, (
                meta.get("file_path"),
                meta.get("period"),
                meta.get("group"),
                meta.get("staff_id"),
                meta.get("staff_name"),
                meta.get("child_id"),
                meta.get("child_name"),
                meta.get("service"),
                len(sessions),
                now_str
            ))

            cur.execute("SELECT id FROM pdf_documents WHERE file_path = ?", (meta.get("file_path"),))
            doc_id = cur.fetchone()["id"]

            # Xóa các phiên cũ của file này trước khi ghi mới
            cur.execute("DELETE FROM intervention_sessions WHERE doc_id = ?", (doc_id,))

            for idx, s in enumerate(sessions, start=1):
                cur.execute("""
                    INSERT INTO intervention_sessions (
                        doc_id, session_order, box_number, date_str,
                        start_time, end_time, raw_ocr, snippet_path, is_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_id,
                    idx,
                    s.get("box_number"),
                    s.get("date") or "",
                    s.get("start_time") or "",
                    s.get("end_time") or "",
                    s.get("raw_ocr") or "",
                    s.get("snippet_path") or "",
                    1 if s.get("date") else 0
                ))
            conn.commit()
            return doc_id

    def get_all_sessions_joined(self, period_filter: Optional[str] = None) -> List[Dict]:
        query = """
            SELECT
                s.id AS session_id,
                s.session_order,
                s.box_number,
                s.date_str AS date,
                s.start_time,
                s.end_time,
                s.raw_ocr,
                s.snippet_path,
                s.is_verified,
                d.id AS doc_id,
                d.file_path,
                d.period,
                d.group_name AS "group",
                d.staff_id,
                d.staff_name,
                d.child_id,
                d.child_name,
                d.service
            FROM intervention_sessions s
            JOIN pdf_documents d ON s.doc_id = d.id
        """
        params = []
        if period_filter:
            query += " WHERE d.period = ?"
            params.append(period_filter)
        query += " ORDER BY d.period DESC, d.group_name, d.staff_id, d.child_id, s.session_order"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def update_session(self, session_id: int, date_str: str, start_time: str, end_time: str):
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE intervention_sessions
                SET date_str = ?, start_time = ?, end_time = ?, is_verified = 1
                WHERE id = ?
            """, (date_str.strip(), start_time.strip(), end_time.strip(), session_id))
            conn.commit()