"""Add the M11 synthetic dataset without replacing any existing data.

Run from the repository root with backend/.venv/Scripts/python.exe.
Images are AI-generated fixtures; API review records are explicitly synthetic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient
from PIL import Image
from app.config import AISettings, WechatConfig
from app.db import Database, database_path, utcnow
from app.main import create_app

ASSETS = BACKEND / "fixtures" / "navigation-m11"
ACCOUNTS = (
    ("m11-test-collector", "volunteer", "测试采集员 · 小林", 1, 0),
    ("m11-test-reviewer", "volunteer", "测试审核员 · 小周", 0, 1),
    ("m11-test-patient", "patient", "测试体验员 · 小安", 0, 0),
)
COLLECTOR, REVIEWER, PATIENT = (account[0] for account in ACCOUNTS)
SCENARIOS = (
    ("lab-published", "【测试】大厅导诊台 → 检验科", "lab", "published"),
    ("pharmacy-published", "【测试】大厅导诊台 → 西药房", "pharmacy", "published"),
    ("lab-pending", "【测试·待审核】检验科备选路线", "lab", "submitted"),
    ("pharmacy-returned", "【测试·补拍】药房标牌复核", "pharmacy", "changes_requested"),
    ("lab-draft", "【测试·草稿】检验科节点练习", "lab", "draft"),
    ("pharmacy-disabled", "【测试·停用】药房旧通道", "pharmacy", "disabled"),
    ("practice-open", "【测试·待领取】大厅至检验科采集练习", "lab", "open"),
)
REVIEW_NOTE = "【合成测试】脚本生成的独立账号审核记录，仅验证发布状态流转；未做现场实走，禁止用于真实院内找路。"


def nodes_for(destination):
    lab = destination == "lab"
    descriptions = (
        "【AI 场景】面对大厅导诊台，沿导诊台右侧的通道前往分岔口。",
        "【AI 场景】找到写有‘检验科 → / ← 西药房’的指示牌，" + ("向右转。" if lab else "向左转。"),
        "【AI 场景】到达‘检验科’门牌下的入口。" if lab else "【AI 场景】到达‘西药房’标牌下的 1—3 号窗口。",
    )
    return [
        {"node_key": key, "position": index, "kind": kind, "floor": "测试门诊楼 1F",
         "direction": direction, "description": descriptions[index]}
        for index, (key, kind, direction) in enumerate((
            ("start", "start", "沿导诊台右侧通道直行"),
            ("junction", "turn", "右转" if lab else "左转"),
            ("end", "end", "核对终点标牌"),
        ))
    ]


def backup_database(path: Path):
    if not path.exists():
        return None
    folder = BACKEND.parent / ".work" / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    backup = folder / ("before-m11-test-data-" + utcnow().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6] + ".db")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    return str(backup)


def seed(database: Database, assets: Path = ASSETS):
    # Validate every asset before writing anything. The application will strip
    # metadata and re-encode each uploaded image through its normal private API.
    for name in ("lobby.png", "junction.png", "laboratory.png", "pharmacy.png"):
        file = assets / name
        if file.stat().st_size > 5 * 1024 * 1024:
            raise ValueError(f"Image exceeds upload limit: {name}")
        with Image.open(file) as image:
            if image.width * image.height > 24_000_000:
                raise ValueError(f"Image dimensions exceed upload limit: {name}")
            image.verify()

    # Only new, dedicated synthetic accounts receive these permissions.
    with database.transaction(write=True) as c:
        for uid, role, name, collect, review in ACCOUNTS:
            existing = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if existing:
                membership = c.execute("SELECT * FROM navigation_memberships WHERE user_id=?", (uid,)).fetchone()
                if (existing["role"] != role or not existing["synthetic"] or not membership
                        or (membership["hospital_id"], membership["can_collect"], membership["can_review"])
                        != ("demo-hospital", collect, review)):
                    raise ValueError(f"Existing account conflicts with test account; left unchanged: {uid}")
                continue
            c.execute("INSERT INTO users(id,role,display_name,synthetic) VALUES(?,?,?,1)", (uid, role, name))
            c.execute("INSERT INTO navigation_memberships(user_id,hospital_id,can_collect,can_review) VALUES(?,'demo-hospital',?,?)",
                      (uid, collect, review))

    created, skipped, sessions = [], [], {}
    with TestClient(create_app(database, ai_settings=AISettings(), wechat_config=WechatConfig())) as client:
        def request(who, method, path, payload=None, *, expected=200, **kwargs):
            response = client.request(method, "/api/v1/navigation" + path,
                                      headers=sessions[who], json=payload, **kwargs)
            if response.status_code != expected:
                raise RuntimeError(f"{method} {path}: {response.status_code} {response.text}")
            return response.json()

        try:
            for uid, role, *_ in ACCOUNTS:
                response = client.post("/api/v1/auth/demo-login", json={"demo_alias": uid, "role": role})
                response.raise_for_status()
                sessions[uid] = {"Authorization": "Bearer " + response.json()["access_token"]}

            for key, title, destination, status in SCENARIOS:
                task_id = "m11-fixture-v1-" + key
                with database.transaction(write=True) as c:
                    if c.execute("SELECT 1 FROM navigation_tasks WHERE id=?", (task_id,)).fetchone():
                        skipped.append(task_id)
                        continue  # Preserve any user edits/reviews made since the first import.
                    c.execute("INSERT INTO navigation_tasks(id,title,description,hospital_id,floor,status,created_at) "
                              "VALUES(?,?,?,'demo-hospital',?,'open',?)", (
                                  task_id, title, "AI 生成场景，仅供功能测试；不是真实医院路线，也未现场实走。",
                                  "测试门诊楼 1F", utcnow().isoformat()))
                if status == "open":
                    created.append({"task_id": task_id, "status": status})
                    continue
                request(COLLECTOR, "POST", f"/tasks/{task_id}/claim")
                sub = request(COLLECTOR, "POST", "/submissions", {
                    "task_id": task_id, "title": title, "request_id": task_id}, expected=201)
                sid = sub["id"]
                sub = request(COLLECTOR, "PUT", f"/submissions/{sid}", {
                    "revision": sub["revision"], "title": title, "nodes": nodes_for(destination)})
                photos = ("lobby.png", "junction.png", "laboratory.png" if destination == "lab" else "pharmacy.png")
                for node, filename in zip(sub["nodes"], photos):
                    with (assets / filename).open("rb") as photo:
                        uploaded = request(COLLECTOR, "POST", f"/submissions/{sid}/media", expected=201,
                            data={"node_key": node["node_key"], "revision": str(sub["revision"]),
                                  "client_upload_id": task_id + "-" + node["node_key"]},
                            files={"file": (filename, photo, "image/png")})
                    sub["revision"] = uploaded["submission_revision"]
                if status != "draft":
                    sub = request(COLLECTOR, "POST", f"/submissions/{sid}/submit", {
                        "revision": sub["revision"], "privacy_confirmed": True})
                if status in {"published", "disabled", "changes_requested"}:
                    approve = status != "changes_requested"
                    sub = request(REVIEWER, "POST", f"/submissions/{sid}/review", {
                        "revision": sub["revision"], "decision": "approve" if approve else "request_changes",
                        "walkthrough_confirmed": approve,
                        "note": REVIEW_NOTE if approve else "【合成测试】请补拍分岔口标牌，并在说明中确认左转前往药房；此记录用于练习退回补拍。"})
                if status == "disabled":
                    sub = request(REVIEWER, "POST", f"/submissions/{sid}/disable", {
                        "revision": sub["revision"], "reason": "【合成测试】模拟通道封闭，验证患者列表与照片访问撤销。"})
                if key == "lab-published":
                    request(PATIENT, "POST", f"/routes/{sid}/feedback", {
                        "request_id": task_id + "-feedback", "category": "misdirected",
                        "note": "【合成测试】分岔口指示牌希望提供更近的照片，供审核工作台查看。"}, expected=201)
                created.append({"task_id": task_id, "submission_id": sid, "status": sub["status"]})
        finally:
            for headers in sessions.values():
                client.post("/api/v1/auth/logout", headers=headers)
    return {"database": str(database.path), "created": created, "skipped": skipped,
            "accounts": [{"id": uid, "name": name, "role": role} for uid, role, name, *_ in ACCOUNTS]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    target = (args.database or database_path()).resolve()
    backup = backup_database(target)
    result = seed(Database(target))
    result["backup"] = backup
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
