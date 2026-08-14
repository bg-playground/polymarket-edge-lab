from __future__ import annotations

from dataclasses import dataclass

from polymarket_edge_lab.collectors.windowed import WindowResult


@dataclass(frozen=True)
class CompletenessSummary:
    windows_attempted: int
    windows_complete: int
    windows_unresolved: int
    unresolved_windows: list[tuple[int, int]]

    @property
    def complete(self) -> bool:
        return self.windows_unresolved == 0


def summarize_window_completeness(results: list[WindowResult]) -> CompletenessSummary:
    unresolved = [
        (r.window_start, r.window_end) for r in results if r.ceiling_hit or not r.exhausted_normally
    ]
    return CompletenessSummary(
        windows_attempted=len(results),
        windows_complete=len(results) - len(unresolved),
        windows_unresolved=len(unresolved),
        unresolved_windows=unresolved,
    )
