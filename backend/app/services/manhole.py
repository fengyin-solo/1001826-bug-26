"""检查井业务规则：状态口径、深度限值归类、筛选统计、历史版本与催办清单。

状态流转（列表、详情、统计、催办全部以同一套口径取值，不再各算各的）：
    安排清掏 -> 待清掏
    确认正常 -> 正常使用
    上报缺失 -> 井盖缺失
    废弃井室 -> 已废弃

重点清掏归类（按口径给井室深度限值，超限自动归入重点清掏）：
    口径 <= 1000mm：深度限值 2.0m
    口径 >  1000mm：深度限值 3.0m
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "manhole"
REQUIRED_FIELDS = ["井编号", "所在道路", "井盖类别"]
OPTIONAL_FIELDS = ["井室深度", "井室尺寸", "上次清掏日", "责任班组"]
BUSINESS_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

STATUS_PENDING = "待清掏"
STATUS_NORMAL = "正常使用"
STATUS_MISSING = "井盖缺失"
STATUS_DISCARDED = "已废弃"
STATUS_ORDER = [STATUS_PENDING, STATUS_NORMAL, STATUS_MISSING, STATUS_DISCARDED]

# 动作与目标状态必须一一对应：确认正常就是正常使用，上报缺失才是井盖缺失。
ACTION_RULES = {
    "安排清掏": STATUS_PENDING,
    "确认正常": STATUS_NORMAL,
    "上报缺失": STATUS_MISSING,
    "废弃井室": STATUS_DISCARDED,
}
NEGATIVE_ACTIONS = {"上报缺失"}

# 按口径划分的井室深度限值（米）：小口径 2m，大口径 3m。
DEPTH_LIMITS_M = (1000.0, 2.0, 3.0)  # (口径分界mm, 小口径限值m, 大口径限值m)

OWNERSHIP_FIELD = "责任班组"

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _to_meters(raw: Any) -> float | None:
    """把 '2.5m'、'2500mm'、'2.5' 之类的取值统一成米。"""
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    if match is None:
        return None
    value = float(match.group())
    if "mm" in text or "毫米" in text:
        return value / 1000.0
    if "m" in text or "米" in text:
        return value
    # 裸数字：深度/口径的米制取值一般不超过个位数，大于 50 按毫米理解。
    return value / 1000.0 if value > 50 else value


def _caliber_mm(row: dict[str, Any]) -> float | None:
    """口径取井室尺寸里的第一个数字（Φ1200、1000×1000 等都能识别）。"""
    value = _to_meters(row.get("井室尺寸"))
    return value * 1000.0 if value is not None else None


def _depth_limit_m(caliber: float | None) -> float:
    boundary, small_limit, large_limit = DEPTH_LIMITS_M
    return small_limit if caliber is None or caliber <= boundary else large_limit


def _snapshot(row: dict[str, Any], version: int) -> dict[str, Any]:
    """留档一版：当时的业务取值与状态原样保存，后续覆盖不冲掉旧版。"""
    return {
        "version": version,
        "status": row.get("status"),
        "values": {field: row.get(field) for field in BUSINESS_FIELDS},
    }


def _ensure_history(row: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(row.get("history"), list):
        row["history"] = [_snapshot(row, 1)]
    return row["history"]


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    """给记录补齐派生口径。列表、详情、催办清单都走这里，保证看到的是同一套结果。"""
    depth = _to_meters(row.get("井室深度"))
    caliber = _caliber_mm(row)
    limit = _depth_limit_m(caliber)
    row["口径mm"] = caliber
    row["深度限值m"] = limit
    row["重点清掏"] = depth is not None and depth > limit
    # 展示字段与内部状态严格同步，避免列表一个状态、详情另一个状态。
    row["检查井状态"] = row.get("status")
    row["pending"] = row.get("status") in (STATUS_PENDING, STATUS_MISSING)
    row["abnormal"] = row.get("status") == STATUS_MISSING
    _ensure_history(row)
    return row


def _matches(row: dict[str, Any], *, keyword: str | None, road: str | None,
             cover: str | None, status: str | None, key_only: bool,
             urgent_only: bool) -> bool:
    if keyword and keyword not in str(row.get("井编号", "")):
        return False
    if road and road not in str(row.get("所在道路", "")):
        return False
    if cover and cover not in str(row.get("井盖类别", "")):
        return False
    if status and row.get("status") != status:
        return False
    if key_only and not row.get("重点清掏"):
        return False
    if urgent_only and not _reminder_reasons(row):
        return False
    return True


def _reminder_reasons(row: dict[str, Any]) -> list[str]:
    """检查井结论落到催办清单的判定口径；已废弃的井不再催办。"""
    if row.get("status") == STATUS_DISCARDED:
        return []
    reasons: list[str] = []
    if row.get("status") == STATUS_MISSING:
        reasons.append("井盖缺失，需尽快补盖处置")
    if row.get("重点清掏"):
        reasons.append(
            f"井室深度超限（口径{int(row['口径mm'])}mm，限值{row['深度限值m']:.1f}m），列入重点清掏"
        )
    if row.get("status") == STATUS_PENDING:
        reasons.append("井室待清掏")
    return reasons


class ManholeService:
    def _query(
        self,
        *,
        keyword: str | None = None,
        road: str | None = None,
        cover: str | None = None,
        status: str | None = None,
        key_only: bool = False,
        urgent_only: bool = False,
    ) -> list[dict[str, Any]]:
        rows = [_decorate(dict(row)) for row in store.rows(MODULE)]
        return [
            row for row in rows
            if _matches(
                row,
                keyword=keyword,
                road=road,
                cover=cover,
                status=status,
                key_only=key_only,
                urgent_only=urgent_only,
            )
        ]

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        road: str | None = None,
        cover: str | None = None,
        status: str | None = None,
        key_only: bool = False,
        urgent_only: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._query(
            keyword=keyword, road=road, cover=cover, status=status,
            key_only=key_only, urgent_only=urgent_only,
        )
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def list_reminders(
        self,
        *,
        keyword: str | None = None,
        road: str | None = None,
        cover: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """催办清单：只装有待办结论的井，条数随筛选与状态实时重算。"""
        rows = self._query(keyword=keyword, road=road, cover=cover, urgent_only=True)
        items = []
        for row in rows:
            item = {field: row.get(field) for field in BUSINESS_FIELDS}
            item["id"] = row["id"]
            item["检查井状态"] = row["检查井状态"]
            item["重点清掏"] = row["重点清掏"]
            item["催办理由"] = "；".join(_reminder_reasons(row))
            items.append(item)
        return items, len(items)

    def stats(
        self,
        *,
        keyword: str | None = None,
        road: str | None = None,
        cover: str | None = None,
        status: str | None = None,
        key_only: bool = False,
        urgent_only: bool = False,
    ) -> list[dict[str, Any]]:
        """统计与列表同一份筛选口径，筛出几条就照几条算。"""
        rows = self._query(
            keyword=keyword, road=road, cover=cover, status=status,
            key_only=key_only, urgent_only=urgent_only,
        )
        return [
            {"key": "total", "label": "在册检查井", "value": len(rows)},
            {"key": "pending", "label": "待清掏井室",
             "value": sum(1 for row in rows if row.get("status") == STATUS_PENDING)},
            {"key": "missing", "label": "井盖缺失",
             "value": sum(1 for row in rows if row.get("status") == STATUS_MISSING)},
            {"key": "key", "label": "重点检查井",
             "value": sum(1 for row in rows if row.get("重点清掏"))},
            {"key": "urgent", "label": "催办条数",
             "value": sum(1 for row in rows if _reminder_reasons(row))},
        ]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return _decorate(dict(row)) if row is not None else None

    def upsert_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        """登记或更新检查井：同井编号以后到的一份覆盖，旧取值进入历史版本。

        返回 (记录, 缺失字段, 是否新建)。
        """
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False

        rows = store.rows(MODULE)
        code = str(values.get("井编号")).strip()
        existing = next((row for row in rows if str(row.get("井编号")) == code), None)

        if existing is None:
            entry: dict[str, Any] = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            }
            for field in BUSINESS_FIELDS:
                entry[field] = str(values.get(field)).strip() if values.get(field) is not None else None
            entry["status"] = STATUS_ORDER[0]
            entry["history"] = [_snapshot(entry, 1)]
            rows.append(entry)
            return _decorate(dict(entry)), [], True

        # 后到覆盖：先把当时那版留档，再用新值整体覆盖业务字段，状态不被登记动作冲掉。
        history = _ensure_history(existing)
        history.append(_snapshot(existing, len(history) + 1))
        for field in BUSINESS_FIELDS:
            if values.get(field) is not None:
                existing[field] = str(values.get(field)).strip()
        return _decorate(dict(existing)), [], False

    def change_ownership(self, entry_id: int, owner: str) -> tuple[dict[str, Any] | None, str]:
        """调整检查井归属（责任班组）；归属变更同样保留旧版。"""
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"检查井 {entry_id} 不存在或已归档"
        owner = owner.strip()
        if not owner:
            return None, "归属班组不能为空"
        if row.get(OWNERSHIP_FIELD) == owner:
            return _decorate(dict(row)), f"检查井归属已是{owner}，无需重复调整"
        history = _ensure_history(row)
        history.append(_snapshot(row, len(history) + 1))
        row[OWNERSHIP_FIELD] = owner
        return _decorate(dict(row)), f"检查井归属已调整为{owner}"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"检查井 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于检查井可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        # 重复确认同一结论时幂等处理：结果保持不变，不会把状态改回去。
        if row.get("status") == target:
            return _decorate(dict(row)), f"检查井结论已是「{target}」，无需重复确认"
        history = _ensure_history(row)
        history.append(_snapshot(row, len(history) + 1))
        row["status"] = target
        return _decorate(dict(row)), f"检查井已{action}"
