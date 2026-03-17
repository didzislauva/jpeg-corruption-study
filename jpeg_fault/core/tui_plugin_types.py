from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


class TuiPlugin(Protocol):
    id: str
    label: str
    panel_id: str
    panel_label: str
    tab_label: str

    def build_tab(self, app) -> object: ...


@dataclass(frozen=True)
class TuiPluginSpec:
    id: str
    label: str
    panel_id: str
    panel_label: str
    tab_label: str
    build_tab: Callable[[object], object]
