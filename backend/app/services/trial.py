"""校验规则试运行引擎。

职责边界：
- 从采集计划的结果样本批次中按规则采样比例确定性抽样；
- 对每条记录做表达式求值，区分通过 / 阻断 / 待人工确认（缺字段不判通过）；
- 按统一口径产出试运行结论，并把硬阻断/仅警告写入计划阻断台账；
- 同一规则 + 同一样本批次重复提交只保留一次结论（幂等），重复试运行不会重复阻断；
- 结论中冻结规则版本快照，规则修改只影响后续新批次，旧批次永远保留原结论。
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from app.services import policy
from app.services.policy import (
    FAILED_PREVIEW_LIMIT,
    HARD_BLOCK_RATE,
    MANUAL_REVIEW_RATE,
    MIN_SAMPLE_SIZE,
    RECORD_BLOCK,
    RECORD_MANUAL,
    RECORD_PASS,
    VERDICT_HARD_BLOCK,
    VERDICT_INSUFFICIENT,
    VERDICT_MANUAL,
    VERDICT_PASS,
    VERDICT_WARN,
    WARN_RATE,
)
from app.store import store

TRIAL_TABLE = "verify_trial"
GUARD_TABLE = "plan_guard"
SAMPLE_TABLE = "collect_sample"
VERIFY_MODULE = "verify"
TASKPLAN_MODULE = "taskplan"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def find_rule(rule_id: int) -> dict[str, Any] | None:
    return store.find(VERIFY_MODULE, rule_id)


def rule_latest_version(rule: dict[str, Any]) -> dict[str, Any]:
    """取规则当前版本；版本列表始终按版本号升序，末位即最新。"""
    versions = rule.get("versions") or []
    if not versions:
        raise ValueError("规则缺少版本快照，无法试运行")
    return versions[-1]


def list_sample_batches(plan_id: int | None = None) -> list[dict[str, Any]]:
    rows = store.rows(SAMPLE_TABLE)
    if plan_id is not None:
        rows = [row for row in rows if int(row.get("plan_id", 0)) == plan_id]
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("batch_no"))
        bucket = grouped.setdefault(
            key,
            {
                "batch_no": key,
                "plan_id": row.get("plan_id"),
                "plan_code": row.get("plan_code"),
                "total": 0,
                "fields": set(),
            },
        )
        bucket["total"] += 1
        bucket["fields"].update(row.get("payload", {}).keys())
    result = []
    for bucket in grouped.values():
        bucket["fields"] = sorted(bucket["fields"])
        result.append(bucket)
    return sorted(result, key=lambda item: item["batch_no"])


def list_trials(rule_id: int | None = None, plan_id: int | None = None) -> list[dict[str, Any]]:
    rows = store.rows(TRIAL_TABLE)
    if rule_id is not None:
        rows = [row for row in rows if int(row.get("rule_id", 0)) == rule_id]
    if plan_id is not None:
        rows = [row for row in rows if int(row.get("plan_id", 0)) == plan_id]
    return sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)


def get_trial(trial_id: int) -> dict[str, Any] | None:
    return store.find(TRIAL_TABLE, trial_id)


def _find_idempotent_trial(rule_id: int, plan_id: int, batch_no: str, version_no: int) -> dict[str, Any] | None:
    """同规则、同批次只保留一次结论：命中即复用，不重算、不重复阻断。"""
    for row in store.rows(TRIAL_TABLE):
        if (
            int(row.get("rule_id", 0)) == rule_id
            and int(row.get("plan_id", 0)) == plan_id
            and str(row.get("batch_no")) == batch_no
            and int(row.get("frozen_version", {}).get("version_no", 0)) == version_no
        ):
            return row
    return None


def _sample_records(records: list[dict[str, Any]], ratio: int, seed_key: str) -> list[dict[str, Any]]:
    """按采样比例确定性抽样：同批同样本多次提交抽中同批记录，保证结论可复现。"""
    target = round(len(records) * ratio / 100)
    target = max(0, min(target, len(records)))
    if target == len(records):
        return list(records)
    rng = random.Random(seed_key)
    indexes = sorted(rng.sample(range(len(records)), target)) if target else []
    return [records[index] for index in indexes]


def _classify_record(
    record: dict[str, Any],
    expression: str,
    required_fields: list[str],
) -> tuple[str, str | None, list[str]]:
    """单条记录判定：缺字段 => 待人工确认；满足表达式 => 通过，否则阻断。"""
    payload = record.get("payload", {})
    missing = [field for field in required_fields if field not in payload or payload[field] in (None, "")]
    if missing:
        return RECORD_MANUAL, f"缺少字段：{'、'.join(missing)}", missing
    passed, error = policy.evaluate_expression(expression, payload)
    if error:
        return RECORD_MANUAL, error, []
    return (RECORD_PASS if passed else RECORD_BLOCK), (None if passed else "不满足校验表达式"), []


def _upsert_guard(
    *,
    plan_id: int,
    plan_code: str,
    rule_id: int,
    rule_code: str,
    batch_no: str,
    trial_id: int,
    block_level: str,
    verdict: str,
    reason: str,
    blocked_count: int,
    manual_count: int,
) -> dict[str, Any]:
    """计划阻断台账按（计划+规则+批次）去重：重复试运行不会产生重复阻断/待处理项。"""
    rows = store.rows(GUARD_TABLE)
    existing = next(
        (
            row
            for row in rows
            if int(row.get("plan_id", 0)) == plan_id
            and int(row.get("rule_id", 0)) == rule_id
            and str(row.get("batch_no")) == batch_no
        ),
        None,
    )
    hard_blocked = block_level == "硬阻断" and verdict == VERDICT_HARD_BLOCK
    warning = verdict in (VERDICT_WARN, VERDICT_MANUAL)
    state = "硬阻断" if hard_blocked else ("待处理" if warning else "已通过")
    if existing is not None:
        existing.update(
            {
                "trial_id": trial_id,
                "block_level": block_level,
                "verdict": verdict,
                "reason": reason,
                "state": state,
                "blocked_count": blocked_count,
                "manual_count": manual_count,
                "updated_at": _now(),
                "resolved": False,
            }
        )
        return existing
    entry = {
        "id": _next_id(rows),
        "plan_id": plan_id,
        "plan_code": plan_code,
        "rule_id": rule_id,
        "rule_code": rule_code,
        "batch_no": batch_no,
        "trial_id": trial_id,
        "block_level": block_level,
        "verdict": verdict,
        "reason": reason,
        "state": state,
        "blocked_count": blocked_count,
        "manual_count": manual_count,
        "resolved": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    rows.append(entry)
    return entry


def run_trial(rule_id: int, plan_id: int, batch_no: str) -> tuple[dict[str, Any] | None, list[str]]:
    """执行一次试运行，返回（试运行批次记录, 错误原因）。"""
    rule = find_rule(rule_id)
    if rule is None:
        return None, [f"校验规则 {rule_id} 不存在"]
    plan = store.find(TASKPLAN_MODULE, plan_id)
    if plan is None:
        return None, [f"采集计划 {plan_id} 不存在"]
    if rule.get("status") not in policy.RULE_STATUSES_RUNNABLE:
        return None, [f"规则当前状态为「{rule.get('status')}」，只有运行中的规则允许试运行"]

    frozen = rule_latest_version(rule)
    version_no = int(frozen["version_no"])

    duplicate = _find_idempotent_trial(rule_id, plan_id, batch_no, version_no)
    if duplicate is not None:
        duplicate["reused"] = True
        return duplicate, []

    samples = [
        row
        for row in store.rows(SAMPLE_TABLE)
        if int(row.get("plan_id", 0)) == plan_id and str(row.get("batch_no")) == batch_no
    ]
    if not samples:
        return None, [f"采集计划在批次 {batch_no} 下没有结果样本，无法试运行"]

    expression = str(frozen["校验表达式"])
    ratio = int(frozen["采样比例"])
    block_limit = int(frozen["阻断上限"])
    block_level = str(frozen["阻断级别"])
    required_fields = policy.extract_expression_fields(expression)

    sampled = _sample_records(samples, ratio, f"{rule_id}:{plan_id}:{batch_no}:v{version_no}")
    details: list[dict[str, Any]] = []
    missing_field_summary: dict[str, int] = {}
    blocked_records: list[dict[str, Any]] = []
    pass_count = block_count = manual_count = 0

    for record in sampled:
        outcome, note, missing = _classify_record(record, expression, required_fields)
        for field in missing:
            missing_field_summary[field] = missing_field_summary.get(field, 0) + 1
        detail = {
            "record_id": record.get("record_id"),
            "outcome": outcome,
            "note": note,
            "missing_fields": missing,
            "payload": record.get("payload", {}),
        }
        details.append(detail)
        if outcome == RECORD_PASS:
            pass_count += 1
        elif outcome == RECORD_BLOCK:
            block_count += 1
            blocked_records.append(detail)
        else:
            manual_count += 1

    sampled_total = len(sampled)
    block_rate = (block_count / sampled_total) if sampled_total else 0.0
    manual_rate = (manual_count / sampled_total) if sampled_total else 0.0

    # 样本不足口径：抽样量不足或全部记录缺字段，必须说明缺少哪些字段，不得直接判通过。
    if sampled_total < MIN_SAMPLE_SIZE or (manual_count == sampled_total and sampled_total > 0):
        missing_desc = (
            "；".join(f"{field}（{count} 条记录缺失）" for field, count in sorted(missing_field_summary.items()))
            or "样本数量不足"
        )
        verdict = VERDICT_INSUFFICIENT
        reason = (
            f"样本不足：抽样 {sampled_total} 条，少于最少样本量 {MIN_SAMPLE_SIZE}；"
            if sampled_total < MIN_SAMPLE_SIZE
            else "样本不足：全部记录都缺少判定字段；"
        ) + f"缺少字段情况：{missing_desc}"
    elif block_rate > block_limit / 100.0 and block_level == "硬阻断" and block_rate > HARD_BLOCK_RATE:
        verdict = VERDICT_HARD_BLOCK
        reason = (
            f"阻断 {block_count}/{sampled_total}（{block_rate:.0%}）超过阻断上限 {block_limit}%，"
            f"硬阻断级别下计划不得进入下一批抓取"
        )
    elif block_rate > block_limit / 100.0 and block_level == "仅警告" and block_rate > WARN_RATE:
        verdict = VERDICT_WARN
        reason = (
            f"阻断 {block_count}/{sampled_total}（{block_rate:.0%}）超过阻断上限 {block_limit}%，"
            f"仅警告级别：允许继续抓取，但必须登记待处理项"
        )
    elif manual_rate > MANUAL_REVIEW_RATE:
        verdict = VERDICT_MANUAL
        reason = (
            f"待人工确认 {manual_count}/{sampled_total}（{manual_rate:.0%}）超过 {MANUAL_REVIEW_RATE:.0%}，"
            f"缺少字段：{'、'.join(sorted(missing_field_summary)) or '无'}"
        )
    else:
        verdict = VERDICT_PASS
        reason = f"通过 {pass_count}、阻断 {block_count}、待人工确认 {manual_count}，未触发阻断上限"

    trial_rows = store.rows(TRIAL_TABLE)
    trial = {
        "id": _next_id(trial_rows),
        "trial_no": f"TRL-{len(trial_rows) + 1:04d}",
        "rule_id": rule_id,
        "rule_code": rule.get("规则编号"),
        "plan_id": plan_id,
        "plan_code": plan.get("计划编号"),
        "batch_no": batch_no,
        "frozen_version": dict(frozen),
        "sample_size_total": len(samples),
        "sample_size_checked": sampled_total,
        "sample_ratio": ratio,
        "pass_count": pass_count,
        "block_count": block_count,
        "manual_count": manual_count,
        "block_rate": round(block_rate, 4),
        "verdict": verdict,
        "reason": reason,
        "required_fields": required_fields,
        "missing_fields": dict(sorted(missing_field_summary.items())),
        "failed_preview": blocked_records[:FAILED_PREVIEW_LIMIT],
        "record_details": details,
        "reused": False,
        "created_at": _now(),
    }
    store.rows(TRIAL_TABLE).append(trial)

    guard = _upsert_guard(
        plan_id=plan_id,
        plan_code=str(plan.get("计划编号")),
        rule_id=rule_id,
        rule_code=str(rule.get("规则编号")),
        batch_no=batch_no,
        trial_id=int(trial["id"]),
        block_level=block_level,
        verdict=verdict,
        reason=reason,
        blocked_count=block_count,
        manual_count=manual_count,
    )
    trial["guard_id"] = guard["id"]
    rule["最近校验"] = f"{verdict}｜批次 {batch_no}｜{_now()}"
    return trial, []


def list_guards(plan_id: int | None = None, only_open: bool = False) -> list[dict[str, Any]]:
    rows = store.rows(GUARD_TABLE)
    if plan_id is not None:
        rows = [row for row in rows if int(row.get("plan_id", 0)) == plan_id]
    if only_open:
        rows = [row for row in rows if not row.get("resolved") and row.get("state") != "已通过"]
    return sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)


def plan_guard_overview(plan_id: int) -> dict[str, Any]:
    """采集计划页的待处理清单口径：最近一次校验批次 + 阻断原因 + 下一批门禁。"""
    plan = store.find(TASKPLAN_MODULE, plan_id)
    guards = list_guards(plan_id=plan_id)
    open_guards = [row for row in guards if not row.get("resolved") and row.get("state") != "已通过"]
    hard = [row for row in open_guards if row.get("state") == "硬阻断"]
    warnings = [row for row in open_guards if row.get("state") == "待处理"]
    latest = guards[0] if guards else None
    batches = sorted({str(row.get("batch_no")) for row in store.rows(SAMPLE_TABLE) if int(row.get("plan_id", 0)) == plan_id})
    next_batch = f"BATCH-{len(batches) + 1:03d}"
    return {
        "plan_id": plan_id,
        "plan_code": plan.get("计划编号") if plan else None,
        "next_batch_no": next_batch,
        "hard_blocked": bool(hard),
        "allow_next_batch": not hard,
        "open_count": len(open_guards),
        "hard_block_count": len(hard),
        "warning_count": len(warnings),
        "latest_trial": {
            "batch_no": latest.get("batch_no"),
            "rule_code": latest.get("rule_code"),
            "verdict": latest.get("verdict"),
            "reason": latest.get("reason"),
            "updated_at": latest.get("updated_at"),
        }
        if latest
        else None,
        "pending_items": open_guards,
    }


def check_next_batch(plan_id: int) -> tuple[dict[str, Any], bool]:
    """下一批抓取门禁：仅未解除的硬阻断拦截；同批次重复试运行不会叠加阻断。"""
    overview = plan_guard_overview(plan_id)
    if overview["hard_blocked"]:
        hard_items = [
            f"批次 {item['batch_no']} 规则 {item['rule_code']}：{item['reason']}"
            for item in overview["pending_items"]
            if item.get("state") == "硬阻断"
        ]
        return (
            {
                "allowed": False,
                "next_batch_no": overview["next_batch_no"],
                "reason": "存在未解除的硬阻断，采集计划不能进入下一批抓取",
                "blockers": hard_items,
            },
            False,
        )
    return (
        {
            "allowed": True,
            "next_batch_no": overview["next_batch_no"],
            "reason": "无未解除硬阻断，可进入下一批；警告项继续保留为待处理清单",
            "warnings": overview["warning_count"],
        },
        True,
    )


def resolve_guard(guard_id: int) -> tuple[dict[str, Any] | None, str]:
    guard = store.find(GUARD_TABLE, guard_id)
    if guard is None:
        return None, f"待处理项 {guard_id} 不存在"
    if guard.get("resolved"):
        return guard, "该待处理项已处理，无需重复操作"
    guard["resolved"] = True
    guard["state"] = "已处理"
    guard["updated_at"] = _now()
    return guard, "待处理项已标记处理"
