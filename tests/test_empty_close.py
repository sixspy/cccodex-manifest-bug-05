import threading

import pytest

from app.db import connect, get_db
from app.services.close import close_batch
from app.services.objects import ServiceError


def _open_batch(client, zone="bronze_payments"):
    items = client.get("/api/batches", params={"status": "收集中"}).json()["items"]
    return next(b for b in items if b["zone_code"] == zone)


def _attempts(db_path, batch_id=None):
    with get_db(str(db_path)) as conn:
        if batch_id is None:
            rows = conn.execute(
                "SELECT * FROM close_attempts ORDER BY id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM close_attempts WHERE batch_id=? ORDER BY id",
                (batch_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def _pulls(db_path):
    with get_db(str(db_path)) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM manifest_pulls ORDER BY id")]


def test_empty_batch_close_rejected_with_reason_and_counts(authed, tmp_path):
    batch = _open_batch(authed)
    assert batch["status"] == "收集中"
    assert batch["registered_object_count"] == 0
    assert batch["gate_chip"] == "拦截"
    assert batch["gate_code"] == "empty_batch"

    r = authed.post(f"/api/batches/{batch['id']}/close", json={})
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert body["code"] == "empty_batch"
    assert body["object_count"] == 0
    assert body["threshold"] == 1
    assert body["count_mode"] == "live_recount_at_submit"
    assert "空批" in body["error"]

    # 现场未变：仍收集中，不得留下已闭合
    after = authed.get(f"/api/batches/{batch['id']}").json()
    assert after["batch"]["status"] == "收集中"
    assert after["batch"]["closed_object_count"] is None
    assert all(o["status"] != "已闭合" for o in after["objects"])

    # 拦截原因与计数值落本机库
    attempts = _attempts(tmp_path / "test.db", batch["id"])
    assert attempts, "拦截记录必须落库"
    last = attempts[-1]
    assert last["accepted"] == 0
    assert last["code"] == "empty_batch"
    assert last["object_count"] == 0
    assert last["threshold"] == 1
    assert last["count_mode"] == "live_recount_at_submit"
    assert "空批" in last["message"]


def test_empty_close_does_not_write_close_run(authed, tmp_path):
    batch = _open_batch(authed)
    authed.post(f"/api/batches/{batch['id']}/close", json={})
    with get_db(str(tmp_path / "test.db")) as conn:
        runs = conn.execute(
            "SELECT * FROM close_runs WHERE batch_id=?", (batch["id"],)
        ).fetchall()
    assert runs == []


def test_count_mode_is_single_and_live(authed):
    meta = authed.get("/api/meta").json()
    assert meta["count_mode"] == "live_recount_at_submit"
    assert meta["count_mode_label"] == "提交瞬间现场重数"
    assert meta["close_threshold"] == 1

    batch = _open_batch(authed)
    # 登记后立即重数，面板计数随现场变化，不是打开时的冻结快照
    authed.post(
        f"/api/batches/{batch['id']}/objects",
        json={"object_key": "k1", "content_hash": "h1", "byte_size": 1},
    )
    detail = authed.get(f"/api/batches/{batch['id']}").json()["batch"]
    assert detail["registered_object_count"] == 1
    assert detail["gate"]["can_close"] is True
    assert detail["gate_chip"] == "可闭合"


def test_closed_batch_pull_manifest_ok(authed, tmp_path):
    batch = _open_batch(authed, "bronze_events")
    authed.post(
        f"/api/batches/{batch['id']}/objects",
        json={"object_key": "e1", "content_hash": "h1", "byte_size": 1},
    )
    close = authed.post(f"/api/batches/{batch['id']}/close", json={})
    assert close.status_code == 200
    assert close.json()["object_count"] == 1

    pull = authed.post(f"/api/batches/{batch['id']}/manifest-pull", json={})
    assert pull.status_code == 200
    assert pull.json()["manifest"]["object_count"] == 1
    assert len(pull.json()["manifest"]["objects"]) == 1


def test_empty_closed_manifest_is_rejected(authed, tmp_path):
    """构造“空已闭合”历史脏数据：列表/面板/验收台/拉清单四处都要拦截。"""
    db_path = str(tmp_path / "test.db")
    batch = _open_batch(authed)
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE landing_batches SET status='已闭合', closed_object_count=0 WHERE id=?",
            (batch["id"],),
        )

    items = authed.get("/api/batches").json()["items"]
    row = next(b for b in items if b["id"] == batch["id"])
    assert row["gate_code"] == "empty_manifest"
    assert row["gate_chip"] == "空清单拦截"

    detail = authed.get(f"/api/batches/{batch['id']}").json()
    assert detail["batch"]["gate_code"] == "empty_manifest"
    assert detail["objects"] == []

    acc = authed.get("/api/close-acceptance").json()
    acc_row = next(b for b in acc["batches"] if b["batch_id"] == batch["id"])
    assert acc_row["empty_manifest"] is True
    assert acc["empty_closed_batch_count"] >= 1

    pull = authed.post(f"/api/batches/{batch['id']}/manifest-pull", json={})
    assert pull.status_code == 422
    assert pull.json()["code"] == "empty_manifest"
    assert pull.json()["object_count"] == 0
    pulls = _pulls(db_path)
    assert pulls and pulls[-1]["accepted"] == 0
    assert pulls[-1]["code"] == "empty_manifest"


def test_unclosed_batch_pull_manifest_rejected(authed):
    batch = _open_batch(authed)
    r = authed.post(f"/api/batches/{batch['id']}/manifest-pull", json={})
    assert r.status_code == 409
    assert r.json()["code"] == "batch_not_closed"


def test_acceptance_shows_threshold_and_counts(authed, tmp_path):
    batch = _open_batch(authed)
    authed.post(f"/api/batches/{batch['id']}/close", json={})  # 被拦截
    acc = authed.get("/api/close-acceptance").json()
    assert acc["threshold"] == 1
    assert acc["count_mode"] == "live_recount_at_submit"
    assert acc["empty_open_batch_count"] >= 1
    row = next(b for b in acc["batches"] if b["batch_id"] == batch["id"])
    assert row["registered_object_count"] == 0
    assert row["threshold"] == 1
    assert row["would_block_empty"] is True
    assert row["last_close_attempt"]["code"] == "empty_batch"
    assert row["last_close_attempt"]["object_count"] == 0


def test_concurrent_empty_close_never_succeeds(authed, tmp_path):
    db_path = str(tmp_path / "test.db")
    batch = _open_batch(authed)
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        try:
            close_batch(batch["id"], db_path)
            results.append("ok")
        except ServiceError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["empty_batch", "empty_batch"]
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status, closed_object_count FROM landing_batches WHERE id=?",
            (batch["id"],),
        ).fetchone()
        runs = conn.execute(
            "SELECT COUNT(*) AS c FROM close_runs WHERE batch_id=?", (batch["id"],)
        ).fetchone()["c"]
    assert row["status"] == "收集中"
    assert row["closed_object_count"] is None
    assert runs == 0


def test_concurrent_close_on_nonempty_batch_single_success(authed, tmp_path):
    db_path = str(tmp_path / "test.db")
    batch = _open_batch(authed)
    authed.post(
        f"/api/batches/{batch['id']}/objects",
        json={"object_key": "z1", "content_hash": "h1", "byte_size": 1},
    )
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        try:
            close_batch(batch["id"], db_path)
            results.append("ok")
        except ServiceError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["already_closed", "ok"]
    with get_db(db_path) as conn:
        runs = conn.execute(
            "SELECT COUNT(*) AS c FROM close_runs WHERE batch_id=?", (batch["id"],)
        ).fetchone()["c"]
    assert runs == 1


def test_visibility_report_flags_empty_closed(authed, tmp_path):
    db_path = str(tmp_path / "test.db")
    batch = _open_batch(authed)
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE landing_batches SET status='已闭合', closed_object_count=0 WHERE id=?",
            (batch["id"],),
        )
    report = authed.post(
        "/api/visibility-reports", json={"as_of_date": "2026-11-16"}
    ).json()["report"]
    assert report["empty_closed_batch_count"] >= 1
    assert "空已闭合" in report["summary"]


def test_migration_adds_empty_closed_column(tmp_path):
    """老库（无 empty_closed_batch_count 列）启动后自动补列。"""
    db_path = str(tmp_path / "legacy.db")
    from app.db import init_db

    conn = connect(db_path)
    conn.execute(
        "CREATE TABLE visibility_reports ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, as_of_date TEXT NOT NULL, "
        "closed_batch_count INTEGER NOT NULL, open_batch_count INTEGER NOT NULL, "
        "object_count INTEGER NOT NULL, orphan_object_count INTEGER NOT NULL, "
        "mismatch_count INTEGER NOT NULL, summary TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.commit()
    conn.close()
    init_db(db_path)
    with get_db(db_path) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(visibility_reports)")}
    assert "empty_closed_batch_count" in cols
