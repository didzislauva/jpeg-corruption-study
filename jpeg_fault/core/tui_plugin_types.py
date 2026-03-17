from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol


class TuiPlugin(Protocol):
    id: str
    label: str
    panel_id: str
    panel_label: str
    tab_label: str
    analysis_plugin_id: str | None

    def build_tab(self, app) -> object: ...


@dataclass(frozen=True)
class TuiPluginSpec:
    id: str
    label: str
    panel_id: str
    panel_label: str
    tab_label: str
    analysis_plugin_id: Optional[str] = None
    build_tab: Optional[Callable[[object], object]] = None
