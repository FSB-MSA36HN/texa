"""Derived numbers: arithmetic the writer asks for over existing facts, computed here, never by the model.

The model may declare `calculations` like {"id": "c_x", "expr": "f_a / u_rate", ...}. Each expression may use only
numbers, fact ids (f_*), user-given values (u_*), earlier calculations (c_*), + - * / and parentheses. Python
evaluates it; the result becomes a fact the text cites as [[c_x]], shown with its formula. User-given values come
from `assumptions`: numbers the user typed in the question (e.g. an exchange rate), kept only if that number
literally appears in what the user wrote."""
import ast
import operator
import re

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
ID = re.compile(r"^[cu]_[a-z0-9_]{1,40}$")
MAX_CALCS = 8
MAX_EXPR = 200


class DeriveError(ValueError):
    pass


def _eval(node, values: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body, values)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise DeriveError(f"unknown value {node.id}")
        return values[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = _eval(node.left, values), _eval(node.right, values)
        if isinstance(node.op, ast.Div) and right == 0:
            raise DeriveError("division by zero")
        return OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand, values)
        return -v if isinstance(node.op, ast.USub) else v
    raise DeriveError("only numbers, value ids, + - * / and parentheses are allowed")


def evaluate(expr: str, values: dict[str, float]) -> float:
    if len(expr) > MAX_EXPR:
        raise DeriveError("expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise DeriveError(f"not an expression: {e.msg}") from None
    return _eval(tree, values)


def _numbers_in(text: str) -> set[float]:
    """Every number a user could have meant in `text`, read with either decimal convention (5,2 / 5.2 / 1.234,5)."""
    out = set()
    for tok in re.findall(r"\d[\d.,]*", text):
        tok = tok.rstrip(".,")
        for cand in (tok.replace(",", ""), tok.replace(".", "").replace(",", "."), tok.replace(",", ".")):
            try:
                out.add(round(float(cand), 9))
            except ValueError:
                pass
    return out


def user_values(assumptions: list[dict], user_text: str) -> tuple[list[dict], list[str]]:
    """Facts for numbers the user stated. A value the user never typed is rejected: the model may not supply one."""
    said = _numbers_in(user_text)
    facts, rejected = [], []
    for a in assumptions[:MAX_CALCS]:
        if not ID.match(a.get("id", "")) or not a["id"].startswith("u_"):
            rejected.append(a.get("id", "?"))
            continue
        if round(float(a["value"]), 9) not in said:
            rejected.append(a["id"])
            continue
        facts.append({"id": a["id"], "label": a.get("label") or a["id"], "value": float(a["value"]),
                      "unit": a.get("unit") or "number", "currency": a.get("currency") or None, "source": "user"})
    return facts, rejected


def calculate(calcs: list[dict], facts: list[dict]) -> tuple[list[dict], list[str]]:
    """Evaluate calculations in order (later ones may use earlier ones). Returns new facts and the ids that failed."""
    values = {f["id"]: float(f["value"]) for f in facts if isinstance(f.get("value"), (int, float)) and f["unit"] != "text"}
    new, failed = [], []
    for c in calcs[:MAX_CALCS]:
        cid = c.get("id", "")
        if not ID.match(cid) or not cid.startswith("c_") or cid in values:
            failed.append(cid or "?")
            continue
        try:
            value = evaluate(c["expr"], values)
        except DeriveError:
            failed.append(cid)
            continue
        values[cid] = value
        new.append({"id": cid, "label": c.get("label") or cid, "value": value, "unit": c.get("unit") or "number",
                    "currency": c.get("currency") or None, "formula": c["expr"], "source": "calculation"})
    return new, failed


if __name__ == "__main__":
    facts = [{"id": "f_a", "value": 10.0, "unit": "currency"}, {"id": "f_b", "value": 4.0, "unit": "currency"}]
    assert evaluate("(f_a - f_b) / f_b", {"f_a": 10, "f_b": 4}) == 1.5
    for bad in ("__import__('os')", "f_a ** 2", "f_a.real", "[1]", "f_zz + 1", "f_a / 0"):
        try:
            evaluate(bad, {"f_a": 10})
            raise SystemExit(f"accepted {bad}")
        except DeriveError:
            pass
    us, rej = user_values([{"id": "u_rate", "value": 5.2}, {"id": "u_made_up", "value": 3.9}], "giả sử 1 USD = 5,2 BRL")
    assert [u["id"] for u in us] == ["u_rate"] and rej == ["u_made_up"]
    new, failed = calculate([{"id": "c_usd", "expr": "f_a / u_rate"}, {"id": "c_twice", "expr": "c_usd * 2"}], facts + us)
    assert [round(n["value"], 4) for n in new] == [1.9231, 3.8462] and not failed
    print("derive ok")
