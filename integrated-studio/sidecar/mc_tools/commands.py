"""commands.json(데이터 생성기가 만든 Brigadier 명령 트리)로 명령어 한 줄을 검사한다.

게임과 똑같은 파서는 아니다. 트리의 리터럴·인자 순서·실행 가능 여부는 그대로 따르고,
인자 하나하나는 형태(숫자 범위, 좌표 개수, 선택자, 괄호 짝, ID 존재)를 확인한다.
모르는 인자 종류는 괄호 짝만 맞으면 통과시킨다(거짓 오류보다 놓침을 택한다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
INT_RE = re.compile(r"[-+]?\d+")
NUM_RE = re.compile(NUM)
COORD_RE = re.compile(rf"(?:[~^](?:{NUM})?|{NUM})")
ID_RE = re.compile(r"#?(?:[a-z0-9_.\-]+:)?[a-z0-9_./\-]+")
UNQUOTED_RE = re.compile(r"[0-9A-Za-z_\-.+]+")
RANGE_RE = re.compile(rf"(?:{NUM})?\.\.(?:{NUM})?|{NUM}")
TIME_RE = re.compile(rf"{NUM}[dst]?")
UUID_RE = re.compile(r"[0-9a-fA-F]{1,8}-[0-9a-fA-F]{1,4}-[0-9a-fA-F]{1,4}-[0-9a-fA-F]{1,4}-[0-9a-fA-F]{1,12}")
SELECTOR_RE = re.compile(r"@[parsen]")
PLAYER_NAME_RE = re.compile(r"[^\s@\[\]{}\"']{1,40}")

# 인자 종류별 ID 검사에 쓸 레지스트리
ID_PARSERS = {
    "minecraft:dimension": "dimension",
    "minecraft:particle": "minecraft:particle_type",
}


class ParseError(Exception):
    def __init__(self, msg: str, pos: int):
        super().__init__(msg)
        self.msg = msg
        self.pos = pos


@dataclass
class Issue:
    col: int
    message: str
    severity: str = "error"   # error | warning


@dataclass
class Result:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    refs: list[tuple[str, str]] = field(default_factory=list)   # (종류, ID) — function, function_tag …


def _norm_id(raw: str) -> str:
    raw = raw.lstrip("#")
    return raw if ":" in raw else f"minecraft:{raw}"


def _balanced_end(s: str, pos: int, stop_at_space: bool = True) -> int:
    """괄호·따옴표 짝을 맞추며 토큰 끝을 찾는다. 짝이 안 맞으면 ParseError."""
    depth: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    i = pos
    quote: str | None = None
    while i < len(s):
        c = s[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in pairs:
            depth.append(pairs[c])
        elif c in ")]}":
            if not depth or depth[-1] != c:
                raise ParseError(f"닫는 괄호 '{c}'의 짝이 없습니다", i)
            depth.pop()
        elif c == " " and not depth and stop_at_space:
            break
        i += 1
    if quote:
        raise ParseError("따옴표가 닫히지 않았습니다", pos)
    if depth:
        raise ParseError(f"괄호가 닫히지 않았습니다('{depth[-1]}' 필요)", pos)
    return i


class CommandChecker:
    def __init__(self, tree: dict[str, Any], id_lookup: Callable[[str], set[str] | None] | None = None,
                 blocks: dict[str, Any] | None = None, tag_lookup: Callable[[str, str], bool] | None = None):
        """id_lookup(registry) → 그 레지스트리 ID 집합(모르면 None). tag_lookup(registry, id) → 태그가 있는지."""
        self.root = tree
        self.id_lookup = id_lookup or (lambda r: None)
        self.tag_lookup = tag_lookup or (lambda r, i: True)
        self.blocks = blocks or {}

    # ---------- 트리 ----------
    def node_at(self, path: list[str]) -> dict[str, Any]:
        n = self.root
        for p in path:
            n = n.get("children", {}).get(p)
            if n is None:
                raise KeyError(p)
        return n

    def next_nodes(self, node: dict[str, Any]) -> dict[str, Any]:
        if "children" in node:
            return node["children"]
        if "redirect" in node:
            return self.node_at(node["redirect"]).get("children", {})
        if node.get("type") == "literal" and not node.get("executable"):
            return self.root.get("children", {})  # execute … run → 루트로
        return {}

    def syntax(self, path: list[str]) -> list[dict[str, Any]]:
        """command_syntax 도구용: 경로 다음에 올 수 있는 것."""
        node = self.node_at(path) if path else self.root
        out = []
        for name, ch in self.next_nodes(node).items() if path else self.root.get("children", {}).items():
            item = {"name": name, "type": ch.get("type"), "executable": bool(ch.get("executable"))}
            if ch.get("type") == "argument":
                item["parser"] = ch.get("parser")
                if ch.get("properties"):
                    item["properties"] = ch["properties"]
            out.append(item)
        return out

    # ---------- 한 줄 검사 ----------
    def check(self, line: str) -> Result:
        """한 줄을 검사한다. 실패하면 가장 멀리 간 지점의 오류 하나를 돌려준다."""
        self._text = text = line.strip()
        self._best: ParseError | None = None
        self._ok_refs: list = []
        self._ok_warn: list = []
        if text.startswith("/"):
            return Result(False, [Issue(0, "함수 파일의 명령어 앞에는 '/'를 붙이지 않습니다")])
        if self._walk(self.root.get("children", {}), 0, [], [], ""):
            return Result(True, self._ok_warn, self._ok_refs)
        e = self._best or ParseError("명령어를 해석할 수 없습니다", 0)
        return Result(False, [Issue(e.pos, e.msg)])

    def _fail(self, e: ParseError) -> None:
        if self._best is None or e.pos > self._best.pos:
            self._best = e

    def _walk(self, children: dict[str, Any], pos: int, refs: list, warns: list, prev: str) -> bool:
        text = self._text
        literals = {k: v for k, v in children.items() if v.get("type") == "literal"}
        args = {k: v for k, v in children.items() if v.get("type") == "argument"}
        word_end = text.find(" ", pos)
        word = text[pos:] if word_end < 0 else text[pos:word_end]
        if word in literals and self._after(literals[word], pos + len(word), refs, warns, word):
            return True
        for name, node in args.items():
            try:
                end, r, w = self._arg(node, text, pos)
            except ParseError as e:
                self._fail(e)
                continue
            if self._after(node, end, refs + r, warns + w, f"<{name}>"):
                return True
        if not args and word not in literals:
            if prev == "":
                self._fail(ParseError(f"알 수 없는 명령어입니다: '{word}'", pos))
            else:
                opts = ", ".join(sorted(literals)[:12])
                self._fail(ParseError(f"'{prev}' 다음에 '{word}'는 올 수 없습니다(가능: {opts})", pos))
        return False

    def _after(self, node: dict[str, Any], pos: int, refs: list, warns: list, label: str) -> bool:
        text = self._text
        if pos >= len(text):
            if node.get("executable"):
                self._ok_refs, self._ok_warn = refs, warns
                return True
            want = ", ".join(sorted(self.next_nodes(node))[:8])
            self._fail(ParseError(f"명령어가 '{label}'에서 끝났습니다 — 더 필요합니다(다음: {want})", pos))
            return False
        if text[pos] != " ":
            self._fail(ParseError(f"'{label}' 뒤에 공백이 필요합니다", pos))
            return False
        if pos + 1 < len(text) and text[pos + 1] == " ":
            self._fail(ParseError("공백이 두 칸입니다", pos + 1))
            return False
        nxt = self.next_nodes(node)
        if not nxt:
            self._fail(ParseError(f"'{label}' 뒤에는 아무것도 올 수 없습니다", pos))
            return False
        return self._walk(nxt, pos + 1, refs, warns, label)

    # ---------- 인자 ----------
    def _arg(self, node: dict[str, Any], s: str, pos: int) -> tuple[int, list, list]:
        parser = node.get("parser", "")
        props = node.get("properties", {}) or {}
        refs: list[tuple[str, str]] = []
        warns: list[Issue] = []

        def token(p: int = pos) -> tuple[str, int]:
            end = _balanced_end(s, p)
            if end == p:
                raise ParseError("값이 비어 있습니다", p)
            return s[p:end], end

        def number(kind: str) -> int:
            tok, end = token()
            rx = INT_RE if kind in ("integer", "long") else NUM_RE
            if not rx.fullmatch(tok):
                raise ParseError(f"숫자가 와야 합니다: '{tok}'", pos)
            v = float(tok)
            if "min" in props and v < float(props["min"]):
                raise ParseError(f"{props['min']} 이상이어야 합니다: {tok}", pos)
            if "max" in props and v > float(props["max"]):
                raise ParseError(f"{props['max']} 이하여야 합니다: {tok}", pos)
            return end

        def coords(n: int) -> int:
            p = pos
            kinds = set()
            for i in range(n):
                end = s.find(" ", p)
                end = len(s) if end < 0 else end
                tok = s[p:end]
                if not COORD_RE.fullmatch(tok):
                    raise ParseError(f"좌표 {n}개가 와야 합니다(숫자·~·^): '{tok or '(없음)'}'", p)
                kinds.add("^" if tok.startswith("^") else "x")
                if len(kinds) > 1:
                    raise ParseError("^ 좌표는 다른 좌표(숫자·~)와 섞어 쓸 수 없습니다", p)
                p = end
                if i < n - 1:
                    if p >= len(s):
                        raise ParseError(f"좌표 {n}개가 와야 합니다", p)
                    p += 1
            if len(kinds) > 1:
                raise ParseError("^ 좌표는 다른 좌표(숫자·~)와 섞어 쓸 수 없습니다", pos)
            return p

        def resource_id(registry: str | None, allow_tag: bool, ref_kind: str | None = None) -> int:
            tok, end = token()
            m = ID_RE.match(tok)
            if not m or m.end() == 0:
                raise ParseError(f"ID 형식이 아닙니다(소문자·숫자·_ . - / 만): '{tok}'", pos)
            idpart = m.group(0)
            if idpart.startswith("#") and not allow_tag:
                raise ParseError(f"여기에는 태그(#)를 쓸 수 없습니다: '{tok}'", pos)
            nid = _norm_id(idpart)
            if ref_kind:
                refs.append((ref_kind + ("_tag" if idpart.startswith("#") else ""), nid))
            elif registry:
                self._check_id(registry, idpart, pos, warns)
            return end

        if parser == "brigadier:bool":
            tok, end = token()
            if tok not in ("true", "false"):
                raise ParseError(f"true 또는 false 가 와야 합니다: '{tok}'", pos)
            return end, refs, warns
        if parser in ("brigadier:integer", "brigadier:long"):
            return number("integer"), refs, warns
        if parser in ("brigadier:float", "brigadier:double"):
            return number("float"), refs, warns
        if parser == "brigadier:string":
            t = props.get("type", "word")
            if t == "greedy":
                return len(s), refs, warns
            if t == "phrase" and s[pos] in "\"'":
                return _balanced_end(s, pos), refs, warns
            tok, end = token()
            if not UNQUOTED_RE.fullmatch(tok):
                raise ParseError(f"따옴표 없는 단어에는 영문·숫자·_ - . + 만 쓸 수 있습니다: '{tok}'", pos)
            return end, refs, warns
        if parser == "minecraft:message":
            return len(s), refs, warns
        if parser in ("minecraft:entity", "minecraft:score_holder", "minecraft:game_profile"):
            return self._entity(s, pos, props, parser, warns), refs, warns
        if parser in ("minecraft:block_pos", "minecraft:vec3"):
            return coords(3), refs, warns
        if parser in ("minecraft:vec2", "minecraft:rotation", "minecraft:column_pos"):
            return coords(2), refs, warns
        if parser in ("minecraft:block_state", "minecraft:block_predicate"):
            return self._block(s, pos, parser == "minecraft:block_predicate", warns), refs, warns
        if parser in ("minecraft:item_stack", "minecraft:item_predicate"):
            return self._item(s, pos, parser == "minecraft:item_predicate", warns), refs, warns
        if parser == "minecraft:function":
            return resource_id(None, True, "function"), refs, warns
        if parser in ("minecraft:resource", "minecraft:resource_key"):
            return resource_id(props.get("registry"), False), refs, warns
        if parser in ("minecraft:resource_or_tag", "minecraft:resource_or_tag_key"):
            return resource_id(props.get("registry"), True), refs, warns
        if parser in ID_PARSERS:
            tok, end = token()
            self._check_id(ID_PARSERS[parser], re.split(r"[\[{]", tok, maxsplit=1)[0], pos, warns)
            return end, refs, warns
        if parser in ("minecraft:int_range", "minecraft:float_range"):
            tok, end = token()
            if not RANGE_RE.fullmatch(tok):
                raise ParseError(f"범위 형식(예: 1..5, ..3, 2)이 아닙니다: '{tok}'", pos)
            return end, refs, warns
        if parser == "minecraft:time":
            tok, end = token()
            if not TIME_RE.fullmatch(tok):
                raise ParseError(f"시간 형식(예: 20, 5s, 1d)이 아닙니다: '{tok}'", pos)
            return end, refs, warns
        if parser == "minecraft:uuid":
            tok, end = token()
            if not UUID_RE.fullmatch(tok):
                raise ParseError(f"UUID 형식이 아닙니다: '{tok}'", pos)
            return end, refs, warns
        if parser == "minecraft:entity_anchor":
            tok, end = token()
            if tok not in ("feet", "eyes"):
                raise ParseError(f"feet 또는 eyes 가 와야 합니다: '{tok}'", pos)
            return end, refs, warns
        if parser == "minecraft:swizzle":
            tok, end = token()
            if not re.fullmatch(r"[xyz]{1,3}", tok) or len(set(tok)) != len(tok):
                raise ParseError(f"x, y, z 조합이 와야 합니다: '{tok}'", pos)
            return end, refs, warns
        # 그 밖의 인자(NBT·텍스트 컴포넌트·경로·목표·팀·색 …): 괄호 짝만 확인
        _, end = token()
        return end, refs, warns

    def _check_id(self, registry: str, raw: str, pos: int, warns: list[Issue]) -> None:
        if not raw:
            return
        reg = registry if ":" in registry else f"minecraft:{registry}"
        is_tag = raw.startswith("#")
        nid = _norm_id(raw)
        if not nid.startswith("minecraft:"):
            return  # 다른 네임스페이스(데이터팩·모드)는 여기서 알 수 없다 — 참조 검사에서 따로 본다
        if is_tag:
            if not self.tag_lookup(reg, nid):
                raise ParseError(f"없는 태그입니다({reg.split(':')[1]}): #{nid}", pos)
            return
        ids = self.id_lookup(reg)
        if ids is not None and nid not in ids:
            raise ParseError(f"없는 ID 입니다({reg.split(':')[1]}): {nid}", pos)

    def _entity(self, s: str, pos: int, props: dict, parser: str, warns: list[Issue]) -> int:
        if s[pos] == "@":
            m = SELECTOR_RE.match(s, pos)
            if not m:
                raise ParseError(f"선택자는 @p @a @r @s @e @n 중 하나입니다: '{s[pos:pos + 2]}'", pos)
            end = m.end()
            args = ""
            if end < len(s) and s[end] == "[":
                close = _balanced_end(s, end)
                args = s[end + 1:close - 1]
                end = close
            if end < len(s) and s[end] != " ":
                raise ParseError("선택자 뒤에 공백이 필요합니다", end)
            sel = m.group(0)[1]
            pairs = self._selector_args(args, pos)
            for k, v in pairs:
                if k == "type":
                    raw = v.lstrip("!")
                    self._check_id("minecraft:entity_type", raw, pos, warns)
            single = props.get("amount") == "single"
            players = props.get("type") == "players"
            limit1 = any(k == "limit" and v.strip() == "1" for k, v in pairs)
            if single and sel in "ae" and not limit1:
                raise ParseError(f"여기에는 대상이 하나만 와야 합니다 — @{sel}[limit=1] 또는 @p·@s·@r·@n 을 쓰세요", pos)
            if players and sel in "en" and not any(k == "type" and v.strip() in ("player", "minecraft:player") for k, v in pairs):
                raise ParseError(f"여기에는 플레이어만 올 수 있습니다 — @{sel}[type=player] 또는 @a·@p 를 쓰세요", pos)
            return end
        end = _balanced_end(s, pos)
        tok = s[pos:end]
        if parser == "minecraft:score_holder" and tok == "*":
            return end
        if UUID_RE.fullmatch(tok) or PLAYER_NAME_RE.fullmatch(tok):
            return end
        raise ParseError(f"대상(선택자·이름·UUID)이 와야 합니다: '{tok}'", pos)

    @staticmethod
    def _selector_args(args: str, pos: int) -> list[tuple[str, str]]:
        out = []
        depth = 0
        cur = ""
        parts = []
        quote = None
        for c in args:
            if quote:
                cur += c
                if c == quote:
                    quote = None
                continue
            if c in "\"'":
                quote = c
            elif c in "[{(":
                depth += 1
            elif c in "]})":
                depth -= 1
            if c == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += c
        if cur.strip():
            parts.append(cur)
        for p in parts:
            if "=" not in p:
                raise ParseError(f"선택자 인자는 이름=값 형식입니다: '{p.strip()}'", pos)
            k, v = p.split("=", 1)
            out.append((k.strip(), v.strip()))
        return out

    def _block(self, s: str, pos: int, predicate: bool, warns: list[Issue]) -> int:
        end = _balanced_end(s, pos)
        tok = s[pos:end]
        m = ID_RE.match(tok)
        if not m or not m.group(0):
            raise ParseError(f"블록 ID 가 와야 합니다: '{tok}'", pos)
        raw = m.group(0)
        if raw.startswith("#") and not predicate:
            raise ParseError("setblock·fill 의 블록에는 태그(#)를 쓸 수 없습니다", pos)
        self._check_id("minecraft:block", raw, pos, warns)
        rest = tok[m.end():]
        if rest.startswith("[") and not raw.startswith("#"):
            close = _balanced_end(rest, 0)
            self._check_states(_norm_id(raw), rest[1:close - 1], pos)
            rest = rest[close:]
        elif rest.startswith("["):
            rest = rest[_balanced_end(rest, 0):]
        if rest and not rest.startswith("{"):
            raise ParseError(f"블록 ID 뒤에 올 수 없는 글자입니다: '{rest}'", pos)
        return end

    def _check_states(self, block: str, states: str, pos: int) -> None:
        info = self.blocks.get(block)
        if not info or not states.strip():
            return
        known = info.get("properties", {})
        for part in states.split(","):
            if not part.strip():
                continue
            if "=" not in part:
                raise ParseError(f"블록 상태는 이름=값 형식입니다: '{part}'", pos)
            k, v = (x.strip() for x in part.split("=", 1))
            if k not in known:
                raise ParseError(f"{block} 에는 '{k}' 상태가 없습니다(가능: {', '.join(sorted(known)) or '없음'})", pos)
            if v not in known[k]:
                raise ParseError(f"{block} 의 '{k}' 값으로 '{v}'는 쓸 수 없습니다(가능: {', '.join(known[k])})", pos)

    def _item(self, s: str, pos: int, predicate: bool, warns: list[Issue]) -> int:
        end = _balanced_end(s, pos)
        tok = s[pos:end]
        if predicate and tok.startswith("*"):
            return end
        m = ID_RE.match(tok)
        if not m or not m.group(0):
            raise ParseError(f"아이템 ID 가 와야 합니다: '{tok}'", pos)
        raw = m.group(0)
        if raw.startswith("#") and not predicate:
            raise ParseError("give·item 의 아이템에는 태그(#)를 쓸 수 없습니다", pos)
        self._check_id("minecraft:item", raw, pos, warns)
        rest = tok[m.end():]
        if rest and rest[0] not in "[{":
            raise ParseError(f"아이템 ID 뒤에 올 수 없는 글자입니다: '{rest}'", pos)
        return end

