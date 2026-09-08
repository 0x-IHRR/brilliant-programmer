"""Only syntax facts are confirmed; model interpretations remain unverified."""

import ast
import json
from pathlib import PurePosixPath

from app.project.schema import Finding, Fragment, Location, ProjectMap


def syntax_map(fragments: list[Fragment]) -> ProjectMap:
    findings: list[Finding] = []
    missing: list[str] = []
    for fragment in fragments:
        path = fragment.path
        lines = fragment.text.splitlines()

        def add(
            kind: str,
            subject: str,
            relation: str,
            target: str,
            first: int,
            last: int,
            *,
            lines: list[str] = lines,
            path: str = path,
            fragment: Fragment = fragment,
        ) -> None:
            # A bounded exact quote, not an arbitrary claim that merely mentions a filename.
            last = min(last, first + 4, len(lines))
            quote = "\n".join(lines[first - 1 : last])
            if len(quote) > 6000 or not quote.strip():
                return
            evidence = Location(
                path=path,
                start=fragment.start + first - 1,
                end=fragment.start + last - 1,
                quote=quote,
            )
            findings.append(
                Finding.model_validate(
                    {
                        "kind": kind,
                        "subject": subject[:6000],
                        "relation": relation,
                        "target": target[:6000],
                        "evidence": [evidence.model_dump()],
                    }
                )
            )

        if not lines:
            continue
        add(
            "module",
            path,
            "已读取文本范围",
            f"行 {fragment.start}–{fragment.end}；不代表全文件/模块读透",
            1,
            1,
        )
        if path.endswith(".py"):
            try:
                tree = ast.parse(fragment.text)
            except SyntaxError, ValueError, RecursionError:
                missing.append(
                    f"{path}：片段无法完整解析 Python 语法，调用/状态/存储关系未核实"
                )
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.If) and ast.dump(node.test) == ast.dump(
                    ast.parse('__name__ == "__main__"', mode="eval").body
                ):
                    add(
                        "entry",
                        path,
                        "声明 Python 主入口保护",
                        "__main__（未执行）",
                        node.lineno,
                        node.lineno,
                    )
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = ", ".join(alias.name for alias in node.names)
                    target = (
                        ("." * node.level + (node.module or "") + ": ")
                        if isinstance(node, ast.ImportFrom)
                        else ""
                    ) + names
                    add(
                        "call",
                        path,
                        "源码声明导入（运行时解析未核实）",
                        target,
                        node.lineno,
                        node.end_lineno or node.lineno,
                    )
                elif isinstance(node, ast.Call):
                    try:
                        target = ast.unparse(node.func)
                    except RecursionError:
                        continue
                    add(
                        "call",
                        path,
                        "源码调用表达式（实际运行时目标未核实）",
                        target,
                        node.lineno,
                        node.end_lineno or node.lineno,
                    )
                    if isinstance(node.func, ast.Name) and node.func.id == "open":
                        add(
                            "storage",
                            path,
                            "源码调用 open（路径/效果未执行验证）",
                            ast.unparse(node.args[0]) if node.args else "路径未提供",
                            node.lineno,
                            node.end_lineno or node.lineno,
                        )
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                    for target_node in targets:
                        if isinstance(target_node, ast.Attribute):
                            add(
                                "state",
                                path,
                                "源码赋值到属性（生命周期未核实）",
                                ast.unparse(target_node),
                                node.lineno,
                                node.end_lineno or node.lineno,
                            )
                        elif (
                            isinstance(target_node, ast.Name)
                            and target_node.id == "__tablename__"
                        ):
                            add(
                                "storage",
                                path,
                                "声明表名（数据库实际映射未核实）",
                                ast.unparse(node.value) if node.value else "未赋值",
                                node.lineno,
                                node.end_lineno or node.lineno,
                            )
                if len(findings) >= 160:
                    missing.append("语法事实展示达到 160 项范围，其他关系未核实")
                    return ProjectMap(confirmed=findings, missing=missing)
        elif PurePosixPath(path).name == "package.json":
            try:
                manifest = json.loads(fragment.text)
                for key in ("main", "module", "bin", "scripts"):
                    if key in manifest:
                        for index, line in enumerate(lines, 1):
                            if f'"{key}"' in line:
                                add(
                                    "entry",
                                    path,
                                    f"清单声明 {key}（只读，未执行命令）",
                                    json.dumps(manifest[key], ensure_ascii=False),
                                    index,
                                    index,
                                )
                                break
            except ValueError, TypeError, RecursionError:
                missing.append(f"{path}：清单片段不完整，入口未核实")
        else:
            missing.append(
                f"{path}：已保留文本；该语言/格式的调用、状态、存储语义尚未验证"
            )
    kinds = {finding.kind for finding in findings}
    missing.extend(
        f"尚无已核实的 {kind} 证据"
        for kind in ("entry", "call", "state", "storage")
        if kind not in kinds
    )
    return ProjectMap(confirmed=findings, missing=missing)
