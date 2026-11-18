"""解析任务拉清单：只认已闭合且清单非空的批次，空清单一律拒收。"""

from app.db import get_db
from app.services.objects import ServiceError
from app.services.policy import (
    BATCH_NOT_CLOSED_CODE,
    EMPTY_MANIFEST_CODE,
    MANIFEST_MISMATCH_CODE,
)


def _record_pull(
    conn, batch_id: int, accepted: bool, object_count: int, code: str, message: str
) -> None:
    conn.execute(
        "INSERT INTO manifest_pulls(batch_id, accepted, object_count, code, message) "
        "VALUES (?,?,?,?,?)",
        (batch_id, 1 if accepted else 0, object_count, code, message),
    )


def pull_manifest(batch_id: int, db_path: str | None = None) -> dict:
    """解析任务拉取清单。

    拒收条件（任一）：
    - 批次不存在 / 未闭合；
    - 已闭合但实有清单对象为 0（空清单）；
    - 固化数与会实有清单数不一致。
    """
    with get_db(db_path, immediate=True) as conn:
        batch = conn.execute(
            "SELECT * FROM landing_batches WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch:
            raise ServiceError("批次不存在", 404, code="batch_not_found")

        objects = conn.execute(
            "SELECT * FROM landing_objects WHERE batch_id=? AND status='已闭合' "
            "ORDER BY id",
            (batch_id,),
        ).fetchall()
        n = len(objects)

        if batch["status"] != "已闭合":
            msg = "批次未闭合，解析任务拒收空清单。"
            _record_pull(conn, batch_id, False, n, BATCH_NOT_CLOSED_CODE, msg)
            conn.commit()
            raise ServiceError(
                msg,
                409,
                code=BATCH_NOT_CLOSED_CODE,
                details={"batch_id": batch_id, "object_count": n},
            )

        if n == 0:
            msg = f"空清单拒收：该批实有对象 {n} 个，解析任务需要至少 1 个对象。"
            _record_pull(conn, batch_id, False, n, EMPTY_MANIFEST_CODE, msg)
            conn.commit()
            raise ServiceError(
                msg,
                422,
                code=EMPTY_MANIFEST_CODE,
                details={
                    "batch_id": batch_id,
                    "object_count": n,
                    "closed_object_count": batch["closed_object_count"],
                },
            )

        frozen = batch["closed_object_count"]
        if frozen is None or int(frozen) != n:
            msg = (
                f"清单计数错位：固化数 {frozen}，实有清单 {n} 个，解析任务拒收。"
            )
            _record_pull(conn, batch_id, False, n, MANIFEST_MISMATCH_CODE, msg)
            conn.commit()
            raise ServiceError(
                msg,
                409,
                code=MANIFEST_MISMATCH_CODE,
                details={
                    "batch_id": batch_id,
                    "object_count": n,
                    "closed_object_count": frozen,
                },
            )

        _record_pull(conn, batch_id, True, n, "", f"清单 {n} 个对象")
        return {
            "batch_id": batch_id,
            "object_count": n,
            "closed_object_count": frozen,
            "objects": [dict(o) for o in objects],
        }


def list_pulls(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM manifest_pulls ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
