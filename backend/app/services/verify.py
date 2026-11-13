"""采集结果校验业务规则：状态流转、字段校验、统一门槛与规则版本管理。"""
from __future__ import annotations

from typing import Any

from app.services import policy
from app.store import store

MODULE = "verify"
REQUIRED_FIELDS = ["规则编号", "校验对象", "校验类型", "校验表达式", "采样比例", "阻断级别", "阻断上限"]
STATUS_ORDER = ["草稿", "运行中", "已暂停", "已归档"]
ACTION_RULES = {"启动校验": "运行中", "暂停校验": "已暂停", "归档规则": "已归档"}
NEGATIVE_ACTIONS = []
VERSION_FIELDS = ["校验对象", "校验类型", "校验表达式", "阈值配置", "采样比例", "阻断级别", "阻断上限"]


class VerifyService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("规则编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field
            for field in REQUIRED_FIELDS
            if field not in values or values.get(field) in (None, "") or str(values.get(field)).strip() == ""
        ]
        if missing:
            return None, [f"缺少必填字段：{field}" for field in missing]
        violations = policy.validate_rule_config(values)
        if violations:
            return None, violations
        rows = store.rows(MODULE)
        if any(str(row.get("规则编号")) == str(values.get("规则编号")).strip() for row in rows):
            return None, [f"规则编号 {values.get('规则编号')} 已存在，不允许重复保存"]
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ["规则编号", "校验对象", "校验类型", "校验表达式", "阈值配置"]:
            entry[field] = values.get(field)
        entry["采样比例"] = policy.as_int(values.get("采样比例"))
        entry["阻断上限"] = policy.as_int(values.get("阻断上限"))
        entry["阻断级别"] = str(values.get("阻断级别")).strip()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["当前版本号"] = 1
        entry["versions"] = [self._snapshot(entry, version_no=1)]
        entry["最近校验"] = "未试运行"
        rows.append(entry)
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """修改规则：统一门槛不过就拒绝保存；通过后追加新版本，历史版本原样保留。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [f"校验规则 {entry_id} 不存在或已归档"]
        merged = dict(entry)
        for field in VERSION_FIELDS:
            if field in values and str(values.get(field) or "").strip() != "":
                merged[field] = values.get(field)
        violations = policy.validate_rule_config(merged)
        if violations:
            return None, violations
        for field in ["校验对象", "校验类型", "校验表达式", "阈值配置"]:
            if field in values and str(values.get(field) or "").strip() != "":
                entry[field] = values.get(field)
        entry["采样比例"] = policy.as_int(merged["采样比例"])
        entry["阻断上限"] = policy.as_int(merged["阻断上限"])
        entry["阻断级别"] = str(merged["阻断级别"]).strip()
        new_version_no = int(entry.get("当前版本号", 1)) + 1
        entry["当前版本号"] = new_version_no
        entry.setdefault("versions", []).append(self._snapshot(entry, version_no=new_version_no))
        return entry, []

    def list_versions(self, entry_id: int) -> tuple[list[dict[str, Any]] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"校验规则 {entry_id} 不存在或已归档"
        return list(entry.get("versions", [])), ""

    def _snapshot(self, entry: dict[str, Any], *, version_no: int) -> dict[str, Any]:
        """冻结一版规则：试运行批次引用快照，规则后续修改不影响旧批次结论。"""
        snapshot = {"version_no": version_no}
        snapshot.update({field: entry.get(field) for field in VERSION_FIELDS})
        return snapshot

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"校验规则 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于采集结果校验可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"校验规则已{action}"
