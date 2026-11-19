"""齐检门槛：不可变门槛文件是唯一齐检凭证来源。

齐印判定与放行落成共用同一个门槛身份（gate_id@version#digest），
文件摘要钉死在代码里，任何改动都会让放行动作立刻停止。
"""

import hashlib
import json
from pathlib import Path

from app.config import Config
from app.errors import ServiceError

# 现行齐检门槛的唯一凭证。改门槛必须同时改这里并走换版流程。
EXPECTED_GATE_ID = "qi-check-downstream"
EXPECTED_GATE_VERSION = 1
EXPECTED_GATE_SHA256 = (
    "aa23b829d3ff4631d06c9a5d290f8eefa107038f7ef9cdc55b4d44e893ba3db5"
)
EXPECTED_REQUIREMENT = "self_and_upstream_all_stamped"

LEGACY_HISTORY_FILE = "history/legacy_silent_release.json"


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_current_gate() -> dict:
    path = Path(Config.GATE_FILE)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ServiceError("齐检门槛文件缺失，已停止放行", 503)
    actual = _digest(raw)
    if actual != EXPECTED_GATE_SHA256:
        raise ServiceError("齐检门槛文件被改动，已停止放行", 503)
    try:
        gate = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ServiceError("齐检门槛文件无法解析，已停止放行", 503)
    if (
        gate.get("gate_id") != EXPECTED_GATE_ID
        or gate.get("gate_version") != EXPECTED_GATE_VERSION
        or gate.get("requirement") != EXPECTED_REQUIREMENT
        or gate.get("immutable") is not True
    ):
        raise ServiceError("齐检门槛身份不匹配，已停止放行", 503)
    gate = dict(gate)
    gate["sha256"] = actual
    gate["credential"] = credential_for(gate)
    gate["file_readonly"] = not bool(path.stat().st_mode & 0o222)
    return gate


def credential_for(gate: dict) -> str:
    return f"{gate['gate_id']}@{gate['gate_version']}#{gate['sha256'][:16]}"


def current_credential() -> str:
    return load_current_gate()["credential"]


def load_history() -> list[dict]:
    base = Path(Config.GATE_HISTORY_DIR)
    if not base.is_dir():
        return []
    items: list[dict] = []
    for path in sorted(base.glob("*.json")):
        try:
            raw = path.read_bytes()
            item = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        item["sha256"] = _digest(raw)
        item["file"] = path.name
        items.append(item)
    return items
