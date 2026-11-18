from app.db import get_db
from app.services.policy import (
    CLOSE_MIN_OBJECTS,
    COUNT_MODE,
    COUNT_MODE_LABEL,
    empty_manifest_state,
    evaluate_close_gate,
)


def _row(r) -> dict:
    return dict(r) if r is not None else {}


def _decorate(conn, row) -> dict:
    """给批次行补上现场计数、门槛芯片与最近一次拦截记录。"""
    item = dict(row)
    n = conn.execute(
        "SELECT COUNT(*) AS c FROM landing_objects "
        "WHERE batch_id=? AND status='已登记'",
        (item["id"],),
    ).fetchone()["c"]
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM landing_objects WHERE batch_id=?",
        (item["id"],),
    ).fetchone()["c"]
    closed_n = conn.execute(
        "SELECT COUNT(*) AS c FROM landing_objects "
        "WHERE batch_id=? AND status='已闭合'",
        (item["id"],),
    ).fetchone()["c"]
    last = conn.execute(
        "SELECT * FROM close_attempts WHERE batch_id=? ORDER BY id DESC LIMIT 1",
        (item["id"],),
    ).fetchone()

    gate = evaluate_close_gate(item["status"], n)
    if item["status"] == "已闭合":
        # 已闭合但清单为空属异常状态：标拦截芯片并给出空清单原因
        empty = empty_manifest_state(item["status"], closed_n)
        if empty:
            gate = {**gate, **empty}

    item.update(
        {
            "registered_object_count": int(n),
            "object_count": int(total),
            "closed_object_count_actual": int(closed_n),
            "gate": gate,
            "gate_chip": gate["chip"],
            "gate_code": gate["code"],
            "gate_message": gate["message"],
            "threshold": CLOSE_MIN_OBJECTS,
            "count_mode": COUNT_MODE,
            "count_mode_label": COUNT_MODE_LABEL,
            "last_close_attempt": _row(last) or None,
        }
    )
    return item


def list_batches(db_path: str | None = None, status: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM landing_batches WHERE status=? ORDER BY id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM landing_batches ORDER BY id"
            ).fetchall()
        return [_decorate(conn, r) for r in rows]


def get_batch(batch_id: int, db_path: str | None = None) -> dict | None:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM landing_batches WHERE id=?", (batch_id,)
        ).fetchone()
        if row is None:
            return None
        return _decorate(conn, row)
