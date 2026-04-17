"""Server-side undo/redo stack using deltas (not full snapshots)."""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UndoEntry:
    sheet_name: str
    action_type: str  # "cell_edit", "row_insert", "row_delete", "bulk_edit"
    timestamp: float
    forward_delta: dict  # data to apply this action
    reverse_delta: dict  # data to undo this action


class UndoManager:
    def __init__(self, max_depth: int = 50):
        self._undo_stacks: dict[str, list[UndoEntry]] = defaultdict(list)
        self._redo_stacks: dict[str, list[UndoEntry]] = defaultdict(list)
        self._max_depth = max_depth

    def push(self, entry: UndoEntry) -> None:
        stack = self._undo_stacks[entry.sheet_name]
        stack.append(entry)

        # Clear redo stack — new action invalidates redo history
        self._redo_stacks[entry.sheet_name] = []

        # Enforce max depth
        if len(stack) > self._max_depth:
            stack.pop(0)

    def undo(self, sheet_name: str) -> UndoEntry | None:
        stack = self._undo_stacks.get(sheet_name, [])
        if not stack:
            return None

        entry = stack.pop()
        self._redo_stacks[sheet_name].append(entry)
        return entry

    def redo(self, sheet_name: str) -> UndoEntry | None:
        stack = self._redo_stacks.get(sheet_name, [])
        if not stack:
            return None

        entry = stack.pop()
        self._undo_stacks[sheet_name].append(entry)
        return entry

    def clear(self, sheet_name: str) -> None:
        self._undo_stacks[sheet_name] = []
        self._redo_stacks[sheet_name] = []

    def can_undo(self, sheet_name: str) -> bool:
        return len(self._undo_stacks.get(sheet_name, [])) > 0

    def can_redo(self, sheet_name: str) -> bool:
        return len(self._redo_stacks.get(sheet_name, [])) > 0


_manager: UndoManager | None = None


def get_undo_manager() -> UndoManager:
    global _manager
    if _manager is None:
        _manager = UndoManager()
    return _manager


def init_undo_manager(max_depth: int = 50) -> UndoManager:
    global _manager
    _manager = UndoManager(max_depth=max_depth)
    return _manager
