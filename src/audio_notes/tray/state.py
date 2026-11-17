"""Pure tray state machine: controller facts -> icon kind, tooltip and menu availability."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MAX_TOOLTIP = 120  # Windows notification-area tooltips are limited to 127 chars


class TrayState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    ERROR = "error"
    DOWNLOADING = "downloading-model"


@dataclass(frozen=True)
class TrayView:
    state: TrayState
    tooltip: str
    toggle_label: str  # label of the start/pause item
    toggle_enabled: bool
    mic_enabled: bool  # whether the microphone item can be clicked


def compute_state(recording: bool, error: str | None, downloading: bool) -> TrayState:
    """Priority: error > downloading > recording > idle."""
    if error:
        return TrayState.ERROR
    if downloading:
        return TrayState.DOWNLOADING
    if recording:
        return TrayState.RECORDING
    return TrayState.IDLE


def describe(state: TrayState, error: str | None = None) -> TrayView:
    if state is TrayState.RECORDING:
        view = TrayView(state, "Audio Notes: recording", "Pause recording", True, True)
    elif state is TrayState.DOWNLOADING:
        view = TrayView(state, "Audio Notes: downloading speech model...", "Start recording", False, False)
    elif state is TrayState.ERROR:
        view = TrayView(state, f"Audio Notes: error - {error or 'unknown'}", "Start recording", True, True)
    else:
        view = TrayView(state, "Audio Notes: idle", "Start recording", True, True)
    if len(view.tooltip) > MAX_TOOLTIP:
        view = TrayView(
            view.state, view.tooltip[: MAX_TOOLTIP - 3] + "...", view.toggle_label, view.toggle_enabled, view.mic_enabled
        )
    return view
