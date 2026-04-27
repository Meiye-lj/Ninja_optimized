#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import subprocess
import sys
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# -----------------------------
# Data model
# -----------------------------


@dataclass
class RuleRecord:
    name: str
    bindings_raw: Dict[str, str] = field(default_factory=dict)
    defined_in: str = ""


@dataclass
class EdgeRecord:
    edge_id: str
    manifest: str
    line_no: int
    explicit_outputs_raw: List[str] = field(default_factory=list)
    implicit_outputs_raw: List[str] = field(default_factory=list)
    rule: str = ""
    explicit_inputs_raw: List[str] = field(default_factory=list)
    implicit_inputs_raw: List[str] = field(default_factory=list)
    order_only_inputs_raw: List[str] = field(default_factory=list)
    validations_raw: List[str] = field(default_factory=list)
    bindings_raw: Dict[str, str] = field(default_factory=dict)
    scope_vars_raw: Dict[str, str] = field(default_factory=dict)
    rule_bindings_raw: Dict[str, str] = field(default_factory=dict)

    explicit_outputs: List[str] = field(default_factory=list)
    implicit_outputs: List[str] = field(default_factory=list)
    all_outputs: List[str] = field(default_factory=list)
    explicit_inputs: List[str] = field(default_factory=list)
    implicit_inputs: List[str] = field(default_factory=list)
    order_only_inputs: List[str] = field(default_factory=list)
    validations: List[str] = field(default_factory=list)
    bindings: Dict[str, str] = field(default_factory=dict)
    rule_bindings: Dict[str, str] = field(default_factory=dict)
    command: Optional[str] = None
    description: Optional[str] = None
    depfile: Optional[str] = None
    task_type: str = "unknown"
    source_features: Dict[str, float] = field(default_factory=dict)
    topo: Dict[str, int] = field(default_factory=dict)
    observed_time_ms: Optional[int] = None
    observed_time_output: Optional[str] = None

    @property
    def primary_output(self) -> str:
        return self.all_outputs[0] if self.all_outputs else (self.explicit_outputs[0] if self.explicit_outputs else "")

    @property
    def is_phony(self) -> bool:
        return self.rule == "phony"


@dataclass
class Scope:
    vars: Dict[str, str] = field(default_factory=dict)
    rules: Dict[str, RuleRecord] = field(default_factory=dict)

    def clone_for_subninja(self) -> "Scope":
        return Scope(vars=dict(self.vars), rules=dict(self.rules))


# -----------------------------
# Ninja parsing helpers
# -----------------------------


_COMMENT_RE = re.compile(r"^\s*#")
_BINDING_RE = re.compile(r"^\s*([^=\s]+)\s*=\s*(.*)$")
_VAR_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
_CYCLE_GUARD = object()


def norm_path(p: str) -> str:
    p = p.strip()
    if not p:
        return p
    if p == ".":
        return p
    if p.startswith("$"):
        return p
    if p.startswith("/"):
        return str(pathlib.PurePosixPath(p))
    return str(pathlib.PurePosixPath(p))


def trailing_unescaped_dollars(s: str) -> int:
    count = 0
    i = len(s) - 1
    while i >= 0 and s[i] == "$":
        count += 1
        i -= 1
    return count


def read_logical_lines(path: pathlib.Path) -> Iterable[Tuple[int, str]]:
    current: Optional[str] = None
    logical_start = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\n")
            if current is None:
                current = line
                logical_start = lineno
            else:
                current += "\n" + line

            # A trailing unescaped $ escapes the newline.
            last_physical = current.split("\n")[-1]
            if trailing_unescaped_dollars(last_physical) % 2 == 1:
                head = current.rsplit("\n", 1)[0] if "\n" in current else ""
                trimmed = last_physical[:-1]
                current = head + ("\n" if head else "") + trimmed
                continue

            logical = current.replace("\n", " ")
            current = None
            yield logical_start, logical

    if current is not None:
        yield logical_start, current.replace("\n", " ")


def split_ninja_words(text: str) -> List[str]:
    tokens: List[str] = []
    buf: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
            while i < n and text[i].isspace():
                i += 1
            continue
        if ch == "$":
            if i + 1 >= n:
                buf.append("$")
                i += 1
                continue
            nxt = text[i + 1]
            if nxt in "$ :":
                buf.append(nxt)
                i += 2
                continue
            if nxt == "{":
                end = text.find("}", i + 2)
                if end == -1:
                    buf.append(text[i:])
                    break
                buf.append(text[i:end + 1])
                i = end + 1
                continue
            m = _VAR_NAME_RE.match(text, i + 1)
            if m:
                buf.append("$" + m.group(0))
                i = m.end(0)
                continue
            buf.append(nxt)
            i += 2
            continue
        buf.append(ch)
        i += 1
    if buf:
        tokens.append("".join(buf))
    return tokens


def expand_vars(text: str, env: Dict[str, Any], depth: int = 0) -> str:
    if text is None:
        return ""
    if depth > 20:
        return text
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "$":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= n:
            out.append("$")
            i += 1
            continue
        nxt = text[i + 1]
        if nxt == "$":
            out.append("$")
            i += 2
            continue
        if nxt == " ":
            out.append(" ")
            i += 2
            continue
        if nxt == ":":
            out.append(":")
            i += 2
            continue
        if nxt == "\n":
            i += 2
            continue
        if nxt == "{":
            end = text.find("}", i + 2)
            if end == -1:
                out.append(text[i:])
                break
            name = text[i + 2:end]
            value = env.get(name, "")
            if value is _CYCLE_GUARD:
                value = ""
            elif isinstance(value, str):
                env[name] = _CYCLE_GUARD
                value = expand_vars(value, env, depth + 1)
                env[name] = value
            out.append(str(value))
            i = end + 1
            continue
        m = _VAR_NAME_RE.match(text, i + 1)
        if m:
            name = m.group(0)
            value = env.get(name, "")
            if value is _CYCLE_GUARD:
                value = ""
            elif isinstance(value, str):
                env[name] = _CYCLE_GUARD
                value = expand_vars(value, env, depth + 1)
                env[name] = value
            out.append(str(value))
            i = m.end(0)
            continue
        out.append(nxt)
        i += 2
    return "".join(out)


def parse_build_parts(rest: str) -> Tuple[List[str], List[str], str, List[str], List[str], List[str], List[str]]:
    try:
        out_part, rhs = rest.split(":", 1)
    except ValueError as e:
        raise ValueError(f"Malformed build statement: {rest}") from e

    out_tokens = split_ninja_words(out_part.strip())
    explicit_outputs: List[str] = []
    implicit_outputs: List[str] = []
    dst = explicit_outputs
    for tok in out_tokens:
        if tok == "|":
            dst = implicit_outputs
            continue
        dst.append(tok)

    rhs_tokens = split_ninja_words(rhs.strip())
    if not rhs_tokens:
        raise ValueError(f"Missing rule in build statement: {rest}")
    rule = rhs_tokens[0]
    explicit_inputs: List[str] = []
    implicit_inputs: List[str] = []
    order_only_inputs: List[str] = []
    validations: List[str] = []
    mode = "explicit"
    for tok in rhs_tokens[1:]:
        if tok == "|":
            mode = "implicit"
            continue
        if tok == "||":
            mode = "order_only"
            continue
        if tok == "|@":
            mode = "validation"
            continue
        if mode == "explicit":
            explicit_inputs.append(tok)
        elif mode == "implicit":
            implicit_inputs.append(tok)
        elif mode == "order_only":
            order_only_inputs.append(tok)
        else:
            validations.append(tok)

    return (
        explicit_outputs,
        implicit_outputs,
        rule,
        explicit_inputs,
        implicit_inputs,
        order_only_inputs,
        validations,
    )


class NinjaManifestParser:
    def __init__(self, build_dir: pathlib.Path, build_file: pathlib.Path):
        self.build_dir = build_dir
        self.build_file = build_file
        self.root_manifest = (build_dir / build_file).resolve()
        self.parsed_files: Set[pathlib.Path] = set()
        self.edges: List[EdgeRecord] = []
        self.rules_defined: Dict[str, RuleRecord] = {}
        self.defaults: List[str] = []
        self.include_graph: Dict[str, List[str]] = defaultdict(list)

    def parse(self) -> None:
        scope = Scope()
        self._parse_file(self.root_manifest, scope)

    def _resolve_manifest_path(self, value: str, current_file: pathlib.Path, scope: Scope) -> pathlib.Path:
        expanded = expand_vars(value, dict(scope.vars))
        p = pathlib.Path(expanded)
        if not p.is_absolute():
            p = (current_file.parent / p).resolve()
        return p

    def _parse_file(self, manifest_path: pathlib.Path, scope: Scope) -> None:
        manifest_path = manifest_path.resolve()
        if manifest_path in self.parsed_files:
            return
        self.parsed_files.add(manifest_path)

        current_kind: Optional[str] = None
        current_rule: Optional[RuleRecord] = None
        current_edge: Optional[EdgeRecord] = None

        for lineno, line in read_logical_lines(manifest_path):
            if not line.strip() or _COMMENT_RE.match(line):
                continue

            is_indented = bool(line[:1].isspace())
            if is_indented:
                m = _BINDING_RE.match(line)
                if not m:
                    continue
                key = m.group(1)
                value = m.group(2)
                if current_kind == "rule" and current_rule is not None:
                    current_rule.bindings_raw[key] = value
                elif current_kind == "build" and current_edge is not None:
                    current_edge.bindings_raw[key] = value
                else:
                    # Indented binding outside a rule/build block is invalid for our use;
                    # ignore instead of crashing.
                    pass
                continue

            current_kind = None
            current_rule = None
            current_edge = None
            stripped = line.strip()

            if stripped.startswith("rule "):
                name = stripped[len("rule "):].strip()
                rule = RuleRecord(name=name, defined_in=str(manifest_path))
                scope.rules[name] = rule
                self.rules_defined[name] = rule
                current_kind = "rule"
                current_rule = rule
                continue

            if stripped.startswith("build "):
                rest = stripped[len("build "):]
                (
                    explicit_outputs,
                    implicit_outputs,
                    rule_name,
                    explicit_inputs,
                    implicit_inputs,
                    order_only_inputs,
                    validations,
                ) = parse_build_parts(rest)
                edge = EdgeRecord(
                    edge_id=f"{manifest_path}:{lineno}:{len(self.edges)}",
                    manifest=str(manifest_path),
                    line_no=lineno,
                    explicit_outputs_raw=explicit_outputs,
                    implicit_outputs_raw=implicit_outputs,
                    rule=rule_name,
                    explicit_inputs_raw=explicit_inputs,
                    implicit_inputs_raw=implicit_inputs,
                    order_only_inputs_raw=order_only_inputs,
                    validations_raw=validations,
                    scope_vars_raw=dict(scope.vars),
                    rule_bindings_raw=dict(scope.rules.get(rule_name, RuleRecord(rule_name)).bindings_raw),
                )
                self.edges.append(edge)
                current_kind = "build"
                current_edge = edge
                continue

            if stripped.startswith("include "):
                child = self._resolve_manifest_path(stripped[len("include "):].strip(), manifest_path, scope)
                self.include_graph[str(manifest_path)].append(str(child))
                self._parse_file(child, scope)
                continue

            if stripped.startswith("subninja "):
                child = self._resolve_manifest_path(stripped[len("subninja "):].strip(), manifest_path, scope)
                self.include_graph[str(manifest_path)].append(str(child))
                self._parse_file(child, scope.clone_for_subninja())
                continue

            if stripped.startswith("default "):
                self.defaults.extend(split_ninja_words(stripped[len("default "):].strip()))
                continue

            # Variable assignment in the current scope.
            m = _BINDING_RE.match(stripped)
            if m:
                scope.vars[m.group(1)] = m.group(2)
                continue

            # pool / builddir / other top-level stanzas are not needed as first-class entities here.


# -----------------------------
# Post-processing
# -----------------------------


def dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


COMMAND_COMPILE_HINTS = (
    " -c ",
    " /c ",
    "clang ",
    "clang++ ",
    "gcc ",
    "g++ ",
    "cc ",
    "c++ ",
)


def detect_task_type(rule: str, command: Optional[str]) -> str:
    rule_l = (rule or "").lower()
    cmd_l = f" {(command or '').lower()} "
    if rule_l == "phony":
        return "phony"
    if rule_l == "rerun_cmake":
        return "regen"
    if any(k in rule_l for k in ["link", "ld"]) or (
        re.search(r"\b(ld|link|clang\+\+|g\+\+)\b", cmd_l) and " -c " not in cmd_l and " /c " not in cmd_l
    ):
        return "link"
    if any(k in rule_l for k in ["static_library", "archive", "ar"]) or re.search(r"\b(ar|llvm-ar|ranlib|lib\.exe)\b", cmd_l):
        return "archive"
    if any(k in rule_l for k in ["copy", "install", "package"]) or re.search(r"\b(cp|rsync|install|strip|tar|zip|cpack)\b", cmd_l):
        return "io"
    if any(tok in cmd_l for tok in COMMAND_COMPILE_HINTS) or "compiler" in rule_l:
        return "compile"
    if any(k in rule_l for k in ["gen", "codegen", "moc", "protobuf", "bison", "flex"]):
        return "codegen"
    if command:
        return "custom"
    return "unknown"


def read_text_safe(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def strip_comments_for_cpp(text: str) -> str:
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


def estimate_source_features(src_path: pathlib.Path) -> Dict[str, float]:
    text = read_text_safe(src_path)
    if not text:
        return {
            "file_size": 0,
            "loc": 0,
            "non_empty_loc": 0,
            "function_count": 0,
            "avg_function_length": 0,
            "max_function_length": 0,
            "include_count": 0,
            "template_count": 0,
            "class_count": 0,
            "max_nesting_depth": 0,
            "branch_keyword_count": 0,
            "max_cyclomatic_proxy": 0,
        }

    stripped = strip_comments_for_cpp(text)
    lines = text.splitlines()
    loc = len(lines)
    non_empty_loc = sum(1 for line in lines if line.strip())
    include_count = len(re.findall(r"^\s*#\s*include\b", text, flags=re.MULTILINE))
    template_count = len(re.findall(r"\btemplate\b", stripped))
    class_count = len(re.findall(r"\b(class|struct)\b", stripped))
    branch_keyword_count = len(re.findall(r"\b(if|for|while|case|catch|\?|&&|\|\|)\b", stripped))

    function_matches = list(
        re.finditer(
            r"^[^#\n]*?\b([A-Za-z_~][\w:]*)\s*\([^;{}]*\)\s*(const\s*)?(noexcept\s*)?(->\s*[^\s{]+\s*)?\{",
            stripped,
            flags=re.MULTILINE,
        )
    )
    function_lengths: List[int] = []
    max_nesting = 0
    current_nesting = 0
    for ch in stripped:
        if ch == "{":
            current_nesting += 1
            max_nesting = max(max_nesting, current_nesting)
        elif ch == "}":
            current_nesting = max(0, current_nesting - 1)

    for m in function_matches:
        start = m.end() - 1
        depth = 0
        end = start
        for i, ch in enumerate(stripped[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        function_lengths.append(max(1, stripped[start:end + 1].count("\n") + 1))

    return {
        "file_size": len(text.encode("utf-8", errors="ignore")),
        "loc": loc,
        "non_empty_loc": non_empty_loc,
        "function_count": len(function_matches),
        "avg_function_length": round(sum(function_lengths) / len(function_lengths), 3) if function_lengths else 0,
        "max_function_length": max(function_lengths) if function_lengths else 0,
        "include_count": include_count,
        "template_count": template_count,
        "class_count": class_count,
        "max_nesting_depth": max_nesting,
        "branch_keyword_count": branch_keyword_count,
        "max_cyclomatic_proxy": max(1, branch_keyword_count + 1) if stripped.strip() else 0,
    }


def parse_ninja_log(log_path: pathlib.Path) -> Dict[str, int]:
    if not log_path.exists():
        return {}
    result: Dict[str, int] = {}
    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError:
                continue
            output = norm_path(parts[3])
            result[output] = max(0, end - start)
    return result


def run_cmd(cmd: List[str], cwd: pathlib.Path, check: bool = True) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout


def parse_targets_all(text: str) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        target, rest = line.split(":", 1)
        rule = rest.strip().split()[0] if rest.strip() else ""
        items.append((norm_path(target.strip()), rule))
    return items


def parse_compdb_json(text: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except json.JSONDecodeError:
        return []
    return []


_QUERY_INPUT_RE = re.compile(r"^\s*(\|\||\||\|@)?\s*(.*?)\s*$")


def parse_query_output(text: str) -> Dict[str, Any]:
    section = None
    rule = None
    explicit_inputs: List[str] = []
    implicit_inputs: List[str] = []
    order_only_inputs: List[str] = []
    validations: List[str] = []
    outputs: List[str] = []

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("input:"):
            section = "inputs"
            rule = stripped.split(":", 1)[1].strip()
            continue
        if stripped == "outputs:":
            section = "outputs"
            continue
        if stripped == "validations:":
            section = "validations"
            continue
        if stripped.endswith(":"):
            continue
        m = _QUERY_INPUT_RE.match(line)
        if not m:
            continue
        label = (m.group(1) or "").strip()
        path = norm_path(m.group(2).strip())
        if not path:
            continue
        if section == "inputs":
            if label == "|":
                implicit_inputs.append(path)
            elif label == "||":
                order_only_inputs.append(path)
            elif label == "|@":
                validations.append(path)
            else:
                explicit_inputs.append(path)
        elif section == "outputs":
            outputs.append(path)
        elif section == "validations":
            validations.append(path)

    return {
        "rule": rule,
        "inputs": explicit_inputs,
        "implicit_inputs": implicit_inputs,
        "order_only_inputs": order_only_inputs,
        "validations": validations,
        "outputs": outputs,
    }


def resolve_edge(edge: EdgeRecord) -> None:
    scope_env = dict(edge.scope_vars_raw)
    edge.rule_bindings = {k: expand_vars(v, dict(scope_env)) for k, v in edge.rule_bindings_raw.items()}
    edge.bindings = {k: expand_vars(v, dict(scope_env)) for k, v in edge.bindings_raw.items()}

    edge.explicit_outputs = [norm_path(expand_vars(x, dict(scope_env))) for x in edge.explicit_outputs_raw]
    edge.implicit_outputs = [norm_path(expand_vars(x, dict(scope_env))) for x in edge.implicit_outputs_raw]
    edge.all_outputs = dedupe_keep_order(edge.explicit_outputs + edge.implicit_outputs)
    edge.explicit_inputs = [norm_path(expand_vars(x, dict(scope_env))) for x in edge.explicit_inputs_raw]
    edge.implicit_inputs = [norm_path(expand_vars(x, dict(scope_env))) for x in edge.implicit_inputs_raw]
    edge.order_only_inputs = [norm_path(expand_vars(x, dict(scope_env))) for x in edge.order_only_inputs_raw]
    edge.validations = [norm_path(expand_vars(x, dict(scope_env))) for x in edge.validations_raw]

    env = dict(scope_env)
    env.update(edge.rule_bindings)
    env.update(edge.bindings)
    env.update(
        {
            "in": " ".join(edge.explicit_inputs + edge.implicit_inputs),
            "in_newline": "\n".join(edge.explicit_inputs + edge.implicit_inputs),
            "out": " ".join(edge.all_outputs),
            "out_newline": "\n".join(edge.all_outputs),
        }
    )

    command_raw = edge.rule_bindings_raw.get("command")
    edge.command = expand_vars(command_raw, dict(env)) if command_raw else None
    edge.description = expand_vars(edge.rule_bindings_raw.get("description", ""), dict(env)) or None
    edge.depfile = expand_vars(edge.bindings_raw.get("DEP_FILE", ""), dict(env)) or None
    edge.task_type = detect_task_type(edge.rule, edge.command)


def enrich_compile_commands_with_compdb(
    build_dir: pathlib.Path,
    build_file: pathlib.Path,
    ninja_bin: str,
    edges: List[EdgeRecord],
) -> Dict[str, Any]:
    compile_rules = sorted({edge.rule for edge in edges if edge.task_type == "compile"})
    summary: Dict[str, Any] = {"attempted": False, "rules": compile_rules, "matched_edges": 0, "entries": 0}
    if not compile_rules:
        return summary

    try:
        text = run_cmd([ninja_bin, "-f", str(build_file), "-t", "compdb", *compile_rules], cwd=build_dir)
    except Exception as e:
        summary["error"] = str(e)
        return summary

    summary["attempted"] = True
    entries = parse_compdb_json(text)
    summary["entries"] = len(entries)
    by_output: Dict[str, Dict[str, Any]] = {}
    by_input: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        out = norm_path(str(entry.get("output", "")).strip())
        src = norm_path(str(entry.get("file", "")).strip())
        if out:
            by_output[out] = entry
        if src:
            by_input[src].append(entry)

    matched = 0
    for edge in edges:
        if edge.task_type != "compile":
            continue
        entry = None
        if edge.primary_output and edge.primary_output in by_output:
            entry = by_output[edge.primary_output]
        elif edge.explicit_inputs:
            candidates = by_input.get(edge.explicit_inputs[0], [])
            if len(candidates) == 1:
                entry = candidates[0]
        if entry:
            cmd = entry.get("command") or entry.get("arguments")
            if isinstance(cmd, list):
                cmd = " ".join(str(x) for x in cmd)
            if cmd:
                edge.command = str(cmd)
                matched += 1
    summary["matched_edges"] = matched
    return summary


def compute_topology(edges: List[EdgeRecord]) -> None:
    producers: Dict[str, str] = {}
    edge_by_id = {edge.edge_id: edge for edge in edges}
    for edge in edges:
        for out in edge.all_outputs:
            producers[out] = edge.edge_id

    pred: Dict[str, Set[str]] = defaultdict(set)
    succ: Dict[str, Set[str]] = defaultdict(set)
    for edge in edges:
        for inp in edge.explicit_inputs + edge.implicit_inputs + edge.order_only_inputs:
            p = producers.get(inp)
            if p and p != edge.edge_id:
                pred[edge.edge_id].add(p)
                succ[p].add(edge.edge_id)

    indeg: Dict[str, int] = {eid: len(pred[eid]) for eid in edge_by_id}
    q = deque([eid for eid, d in indeg.items() if d == 0])
    topo_order: List[str] = []
    while q:
        eid = q.popleft()
        topo_order.append(eid)
        for nxt in succ[eid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)

    longest: Dict[str, int] = {eid: 0 for eid in edge_by_id}
    for eid in reversed(topo_order):
        longest[eid] = max((1 + longest[s] for s in succ[eid]), default=0)

    for edge in edges:
        edge.topo = {
            "producer_dep_count": len(pred[edge.edge_id]),
            "consumer_count": len(succ[edge.edge_id]),
            "all_input_count": len(edge.explicit_inputs) + len(edge.implicit_inputs) + len(edge.order_only_inputs),
            "longest_remaining_hops": longest[edge.edge_id],
        }


def attach_observed_times(edges: List[EdgeRecord], ninja_log: Dict[str, int]) -> None:
    for edge in edges:
        found = None
        for out in edge.all_outputs:
            if out in ninja_log:
                found = out
                break
        if found is not None:
            edge.observed_time_ms = ninja_log[found]
            edge.observed_time_output = found


def attach_source_features(build_dir: pathlib.Path, edges: List[EdgeRecord]) -> None:
    for edge in edges:
        if edge.task_type != "compile":
            edge.source_features = {}
            continue
        src = None
        for inp in edge.explicit_inputs:
            if inp.endswith((".c", ".cc", ".cpp", ".cxx", ".C", ".m", ".mm")):
                src = inp
                break
        if not src:
            edge.source_features = {}
            continue
        src_path = pathlib.Path(src)
        if not src_path.is_absolute():
            src_path = build_dir / src_path
        edge.source_features = estimate_source_features(src_path.resolve())


def save_raw_tool_artifacts(
    build_dir: pathlib.Path,
    build_file: pathlib.Path,
    ninja_bin: str,
    out_dir: pathlib.Path,
    defaults: List[str],
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    graph_cmd = [ninja_bin, "-f", str(build_file), "-t", "graph", *defaults] if defaults else [ninja_bin, "-f", str(build_file), "-t", "graph"]
    commands_cmd = [ninja_bin, "-f", str(build_file), "-t", "commands", *defaults] if defaults else [ninja_bin, "-f", str(build_file), "-t", "commands"]
    try:
        dot = run_cmd(graph_cmd, cwd=build_dir)
        (out_dir / "ninja_tool_graph.dot").write_text(dot, encoding="utf-8")
        summary["graph_saved"] = True
    except Exception as e:
        summary["graph_error"] = str(e)
    try:
        cmds = run_cmd(commands_cmd, cwd=build_dir)
        (out_dir / "ninja_tool_commands.txt").write_text(cmds, encoding="utf-8")
        summary["commands_saved"] = True
        summary["commands_line_count"] = len([x for x in cmds.splitlines() if x.strip()])
    except Exception as e:
        summary["commands_error"] = str(e)
    return summary


def validate_with_targets_all(
    build_dir: pathlib.Path,
    build_file: pathlib.Path,
    ninja_bin: str,
    edges: List[EdgeRecord],
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"attempted": False}
    try:
        text = run_cmd([ninja_bin, "-f", str(build_file), "-t", "targets", "all"], cwd=build_dir)
    except Exception as e:
        summary["error"] = str(e)
        return summary

    summary["attempted"] = True
    tool_targets = {t for t, _ in parse_targets_all(text)}
    parser_outputs = {out for edge in edges for out in edge.all_outputs}
    summary.update(
        {
            "tool_target_count": len(tool_targets),
            "parser_output_count": len(parser_outputs),
            "missing_in_parser_count": len(tool_targets - parser_outputs),
            "missing_in_tool_count": len(parser_outputs - tool_targets),
            "missing_in_parser_examples": sorted(list(tool_targets - parser_outputs))[:20],
            "missing_in_tool_examples": sorted(list(parser_outputs - tool_targets))[:20],
        }
    )
    return summary


def validate_with_query(
    build_dir: pathlib.Path,
    build_file: pathlib.Path,
    ninja_bin: str,
    edges: List[EdgeRecord],
    mode: str,
    limit: int,
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"attempted": False, "mode": mode}
    if mode == "none":
        return summary

    candidates = [edge for edge in edges if edge.primary_output]
    if mode == "sample":
        candidates = sorted(candidates, key=lambda e: (e.manifest, e.line_no, e.primary_output))[:limit]

    mismatches: List[Dict[str, Any]] = []
    checked = 0
    for edge in candidates:
        try:
            text = run_cmd([ninja_bin, "-f", str(build_file), "-t", "query", edge.primary_output], cwd=build_dir)
        except Exception as e:
            mismatches.append({"target": edge.primary_output, "error": str(e)})
            continue
        checked += 1
        q = parse_query_output(text)
        local = {
            "rule": edge.rule,
            "outputs": edge.all_outputs,
            "inputs": edge.explicit_inputs,
            "implicit_inputs": edge.implicit_inputs,
            "order_only_inputs": edge.order_only_inputs,
        }
        remote = {
            "rule": q.get("rule"),
            "outputs": q.get("outputs", []),
            "inputs": q.get("inputs", []),
            "implicit_inputs": q.get("implicit_inputs", []),
            "order_only_inputs": q.get("order_only_inputs", []),
        }
        if any(local[k] != remote[k] for k in local):
            mismatches.append({"target": edge.primary_output, "parser": local, "query": remote})
            if mode == "sample" and len(mismatches) >= 20:
                break

    summary.update(
        {
            "attempted": True,
            "checked": checked,
            "mismatch_count": len(mismatches),
            "mismatch_examples": mismatches[:20],
        }
    )
    return summary


def write_outputs(out_dir: pathlib.Path, edges: List[EdgeRecord], summary: Dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "ninja_analysis.json"
    csv_path = out_dir / "ninja_tasks.csv"
    summary_path = out_dir / "ninja_analysis_summary.json"

    tasks_payload = []
    for edge in edges:
        tasks_payload.append(
            {
                "edge_id": edge.edge_id,
                "primary_output": edge.primary_output,
                "all_outputs": edge.all_outputs,
                "rule": edge.rule,
                "task_type": edge.task_type,
                "inputs": edge.explicit_inputs,
                "implicit_inputs": edge.implicit_inputs,
                "order_only_inputs": edge.order_only_inputs,
                "validations": edge.validations,
                "command": edge.command,
                "description": edge.description,
                "depfile": edge.depfile,
                "source_features": edge.source_features,
                "topo": edge.topo,
                "observed_time_ms": edge.observed_time_ms,
                "observed_time_output": edge.observed_time_output,
                "manifest": edge.manifest,
                "line_no": edge.line_no,
                "bindings": edge.bindings,
                "rule_bindings": edge.rule_bindings,
            }
        )

    json_path.write_text(json.dumps({"summary": summary, "tasks": tasks_payload}, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    fieldnames = [
        "edge_id",
        "primary_output",
        "rule",
        "task_type",
        "all_outputs",
        "inputs",
        "implicit_inputs",
        "order_only_inputs",
        "validations",
        "command",
        "description",
        "depfile",
        "source_features",
        "topo",
        "observed_time_ms",
        "observed_time_output",
        "manifest",
        "line_no",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for edge in edges:
            writer.writerow(
                {
                    "edge_id": edge.edge_id,
                    "primary_output": edge.primary_output,
                    "rule": edge.rule,
                    "task_type": edge.task_type,
                    "all_outputs": json.dumps(edge.all_outputs, ensure_ascii=False),
                    "inputs": json.dumps(edge.explicit_inputs, ensure_ascii=False),
                    "implicit_inputs": json.dumps(edge.implicit_inputs, ensure_ascii=False),
                    "order_only_inputs": json.dumps(edge.order_only_inputs, ensure_ascii=False),
                    "validations": json.dumps(edge.validations, ensure_ascii=False),
                    "command": edge.command or "",
                    "description": edge.description or "",
                    "depfile": edge.depfile or "",
                    "source_features": json.dumps(edge.source_features, ensure_ascii=False),
                    "topo": json.dumps(edge.topo, ensure_ascii=False),
                    "observed_time_ms": edge.observed_time_ms if edge.observed_time_ms is not None else "",
                    "observed_time_output": edge.observed_time_output or "",
                    "manifest": edge.manifest,
                    "line_no": edge.line_no,
                }
            )


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse Ninja manifests, recover full build edges, and validate with Ninja tools.")
    ap.add_argument("project_dir", help="Build directory containing build.ninja and .ninja_log")
    ap.add_argument("--build-file", default="build.ninja", help="Manifest file relative to project_dir")
    ap.add_argument("--ninja-bin", default="ninja", help="Path to ninja executable")
    ap.add_argument("--out-dir", default=None, help="Output directory; defaults to project_dir")
    ap.add_argument("--query-check", choices=["none", "sample", "all"], default="sample")
    ap.add_argument("--query-limit", type=int, default=50)
    ap.add_argument("--skip-tools", action="store_true")
    args = ap.parse_args()

    build_dir = pathlib.Path(args.project_dir).resolve()
    build_file = pathlib.Path(args.build_file)
    out_dir = pathlib.Path(args.out_dir).resolve() if args.out_dir else build_dir

    parser = NinjaManifestParser(build_dir=build_dir, build_file=build_file)
    parser.parse()

    edges = parser.edges
    for edge in edges:
        resolve_edge(edge)

    ninja_log = parse_ninja_log(build_dir / ".ninja_log")
    attach_observed_times(edges, ninja_log)
    compute_topology(edges)
    attach_source_features(build_dir, edges)

    summary: Dict[str, Any] = {
        "project_dir": str(build_dir),
        "build_file": str((build_dir / build_file).resolve()),
        "manifest_file_count": len(parser.parsed_files),
        "manifests": sorted(str(p) for p in parser.parsed_files),
        "default_targets": dedupe_keep_order([norm_path(x) for x in parser.defaults]),
        "edge_count": len(edges),
        "rule_count": len(parser.rules_defined),
        "observed_time_count": sum(1 for e in edges if e.observed_time_ms is not None),
        "task_type_breakdown": dict(sorted((k, sum(1 for e in edges if e.task_type == k)) for k in {e.task_type for e in edges})),
    }

    if not args.skip_tools:
        summary["targets_all_validation"] = validate_with_targets_all(build_dir, build_file, args.ninja_bin, edges)
        summary["compdb_enrichment"] = enrich_compile_commands_with_compdb(build_dir, build_file, args.ninja_bin, edges)
        # task type may improve after exact compile commands are injected.
        for edge in edges:
            edge.task_type = detect_task_type(edge.rule, edge.command)
        summary["tool_artifacts"] = save_raw_tool_artifacts(
            build_dir, build_file, args.ninja_bin, out_dir, dedupe_keep_order([norm_path(x) for x in parser.defaults])
        )
        summary["query_validation"] = validate_with_query(
            build_dir, build_file, args.ninja_bin, edges, args.query_check, args.query_limit
        )

    write_outputs(out_dir, edges, summary)
    print(f"[ok] edges={len(edges)}")
    print(f"[ok] json={out_dir / 'ninja_analysis.json'}")
    print(f"[ok] csv={out_dir / 'ninja_tasks.csv'}")
    print(f"[ok] summary={out_dir / 'ninja_analysis_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
