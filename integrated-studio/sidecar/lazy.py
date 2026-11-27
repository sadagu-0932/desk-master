"""무거운 라이브러리를 처음 쓸 때 불러온다(사이드카 시작을 빠르게).

`mll = lazy_module("minecraft_launcher_lib")` 처럼 쓰면 `mll.install...` 을 처음 부를 때 import 한다.
시험의 monkeypatch.setattr(모듈.mll, "이름", 가짜) 도 그대로 동작한다(대신 넣은 값이 먼저 보인다).
"""
from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any


class _LazyModule:
    def __init__(self, name: str) -> None:
        self.__dict__["_name"] = name

    def _load(self) -> ModuleType:
        return importlib.import_module(self.__dict__["_name"])

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._load(), attr)

    def __repr__(self) -> str:
        return f"<lazy module {self.__dict__['_name']}>"


def lazy_module(name: str) -> Any:
    return _LazyModule(name)
