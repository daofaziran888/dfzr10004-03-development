"""校验规则试运行的统一口径。

所有门槛只允许在这里定义一次，保存校验、试运行判定、越界提示都从这里取值，
避免不同接口各写一套标准导致口径漂移。

口径总览（统一门槛，越界一律不允许保存/受理）：
- 采样比例 sample_ratio：整数百分数，允许保存范围 [1, 100]，越界范围 <=0 或 >100；
- 阻断上限 block_limit：阻断条数占比（百分数），允许保存范围 [1, 100]，越界范围 <=0 或 >100；
- 单批最少样本量 min_sample_size：10，少于该值的批次判“样本不足”，不得直接判通过；
- 硬阻断率 hard_block_rate：阻断占比 > 20% 且阻断级别=硬阻断时，计划不得进入下一批；
- 告警率 warn_rate：阻断占比 > 20% 且阻断级别=仅警告时，允许继续但生成待处理项；
- 待人工确认率 manual_rate：缺字段记录占比 > 10% 时，结论置为待人工确认；
- 首批不满足记录展示条数 failed_preview_limit：10；
- 阻断级别仅允许：硬阻断 / 仅警告。
"""
from __future__ import annotations

import ast
import operator
from typing import Any

# ---- 统一门槛常量（采样阈值 / 阻断上限 / 判定标准 / 越界范围） ----
SAMPLE_RATIO_MIN = 1
SAMPLE_RATIO_MAX = 100
BLOCK_LIMIT_MIN = 1
BLOCK_LIMIT_MAX = 100
MIN_SAMPLE_SIZE = 10
HARD_BLOCK_RATE = 0.20
WARN_RATE = 0.20
MANUAL_REVIEW_RATE = 0.10
FAILED_PREVIEW_LIMIT = 10
BLOCK_LEVELS = ("硬阻断", "仅警告")
RULE_STATUSES_RUNNABLE = ("运行中",)

# 试运行结论口径
VERDICT_PASS = "通过"
VERDICT_WARN = "告警"
VERDICT_HARD_BLOCK = "硬阻断"
VERDICT_MANUAL = "待人工确认"
VERDICT_INSUFFICIENT = "样本不足"

# 单条记录判定口径
RECORD_PASS = "通过"
RECORD_BLOCK = "阻断"
RECORD_MANUAL = "待人工确认"

_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
}
_BOOL_OPS = {ast.And: all, ast.Or: any}
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_UNARY_OPS = {ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}


class ExpressionError(ValueError):
    """表达式不满足保存条件时抛出，信息直接回显给调用方。"""


def as_int(value: Any) -> int | None:
    """把入参收敛成 int；布尔、浮点小数、非数字串一律视为非法。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def validate_rule_config(values: dict[str, Any]) -> list[str]:
    """保存条件校验：返回不符合标准的配置原因列表，空列表表示允许保存。"""
    errors: list[str] = []

    ratio = as_int(values.get("采样比例"))
    if ratio is None:
        errors.append("采样比例必须是整数百分数")
    elif not (SAMPLE_RATIO_MIN <= ratio <= SAMPLE_RATIO_MAX):
        errors.append(
            f"采样比例越界：允许保存范围为 {SAMPLE_RATIO_MIN}~{SAMPLE_RATIO_MAX}（百分数），"
            f"收到 {ratio}，越界范围为 <=0 或 >100"
        )

    limit = as_int(values.get("阻断上限"))
    if limit is None:
        errors.append("阻断上限必须是整数百分数")
    elif not (BLOCK_LIMIT_MIN <= limit <= BLOCK_LIMIT_MAX):
        errors.append(
            f"阻断上限越界：允许保存范围为 {BLOCK_LIMIT_MIN}~{BLOCK_LIMIT_MAX}（百分数），"
            f"收到 {limit}，越界范围为 <=0 或 >100"
        )

    level = str(values.get("阻断级别") or "").strip()
    if level not in BLOCK_LEVELS:
        errors.append(f"阻断级别只允许 {' / '.join(BLOCK_LEVELS)}，收到 {level or '空值'}")

    expression = str(values.get("校验表达式") or "").strip()
    if not expression:
        errors.append("校验表达式不能为空")
    else:
        try:
            extract_expression_fields(expression)
        except ExpressionError as exc:
            errors.append(f"校验表达式不满足保存条件：{exc}")

    return errors


def extract_expression_fields(expression: str) -> list[str]:
    """解析表达式并取其中引用的字段名；出现非白名单语法直接拒绝保存。"""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"语法无法解析（{exc.msg}）") from exc

    fields: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in fields:
                fields.append(node.id)
        elif isinstance(
            node,
            (
                ast.Expression,
                ast.BoolOp,
                ast.UnaryOp,
                ast.BinOp,
                ast.Compare,
                ast.Constant,
                ast.Load,
            ),
        ):
            continue
        elif isinstance(node, (ast.operator, ast.boolop, ast.cmpop, ast.unaryop)):
            continue
        else:
            raise ExpressionError(f"包含不允许的语法节点：{type(node).__name__}")
    if not fields:
        raise ExpressionError("表达式未引用任何记录字段，无法用于判定")
    return fields


class _SafeEvaluator:
    """白名单 AST 求值器：只支持比较、布尔、算术与常量，禁止函数调用和属性访问。"""

    def __init__(self, variables: dict[str, Any]) -> None:
        self._variables = variables

    def eval(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return self.eval(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in self._variables:
                raise ExpressionError(f"字段 {node.id} 不存在")
            return self._variables[node.id]
        if isinstance(node, ast.BoolOp):
            values = (self.eval(value) for value in node.values)
            return _BOOL_OPS[type(node.op)](values)
        if isinstance(node, ast.UnaryOp):
            op = _UNARY_OPS.get(type(node.op))
            if op is None:
                raise ExpressionError("不支持的一元运算")
            return op(self.eval(node.operand))
        if isinstance(node, ast.BinOp):
            op = _BIN_OPS.get(type(node.op))
            if op is None:
                raise ExpressionError("不支持的二元运算")
            left, right = self.eval(node.left), self.eval(node.right)
            if isinstance(left, str) or isinstance(right, str):
                raise ExpressionError("文本字段不支持算术运算")
            return op(left, right)
        if isinstance(node, ast.Compare):
            left = self.eval(node.left)
            for op_node, comparator in zip(node.ops, node.comparators):
                op = _COMPARE_OPS.get(type(op_node))
                if op is None:
                    raise ExpressionError("不支持的比较运算")
                right = self.eval(comparator)
                try:
                    if not op(left, right):
                        return False
                except TypeError as exc:
                    raise ExpressionError("比较两端类型不兼容") from exc
                left = right
            return True
        raise ExpressionError(f"不允许的表达式节点：{type(node).__name__}")


def evaluate_expression(expression: str, record: dict[str, Any]) -> tuple[bool, str | None]:
    """对单条记录求值，返回（是否满足表达式, 错误说明）。

    字段缺失或类型不兼容不算“阻断”，交给调用方按待人工确认处理，绝不静默判通过。
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _SafeEvaluator(record).eval(tree)
    except ExpressionError as exc:
        return False, str(exc)
    except (SyntaxError, TypeError, ZeroDivisionError, KeyError) as exc:
        return False, f"表达式求值失败：{exc}"
    return bool(result), None


def policy_spec() -> dict[str, Any]:
    """给前端的统一口径说明，表单校验与提示都以此为准。"""
    return {
        "sample_ratio": {"min": SAMPLE_RATIO_MIN, "max": SAMPLE_RATIO_MAX, "unit": "百分数整数"},
        "block_limit": {"min": BLOCK_LIMIT_MIN, "max": BLOCK_LIMIT_MAX, "unit": "百分数整数"},
        "min_sample_size": MIN_SAMPLE_SIZE,
        "hard_block_rate": HARD_BLOCK_RATE,
        "warn_rate": WARN_RATE,
        "manual_review_rate": MANUAL_REVIEW_RATE,
        "failed_preview_limit": FAILED_PREVIEW_LIMIT,
        "block_levels": list(BLOCK_LEVELS),
        "out_of_range": "采样比例/阻断上限 <=0 或 >100 均属越界，禁止保存",
    }
