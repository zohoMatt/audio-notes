"""Pure tray state machine: controller facts -> icon kind, tooltip and menu availability."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    mic_label: str = "Microphone"


def compute_state(recording: bool, error: str | None, downloading: bool) -> TrayState:
    """Priority: error > downloading > recording > idle."""
    if error:
        return TrayState.ERROR
    if downloading:
        return TrayState.DOWNLOADING
    if recording:
        return TrayState.RECORDING
    return TrayState.IDLE


def describe(state: TrayState, error: str | None = None, recording: bool = False) -> TrayView:
    """`recording` matters in the error state: a session can keep running while capture has a
    problem (e.g. re-binding a lost device), and the toggle must then still offer to stop it.

    The microphone can only be switched between sessions. While recording its item is disabled,
    so unticking it can never look like muting a microphone that is still being captured."""
    recording = recording or state is TrayState.RECORDING
    toggle = "Pause recording" if recording else "Start recording"
    if state is TrayState.RECORDING:
        view = TrayView(state, "Audio Notes: recording", toggle, True, False)
    elif state is TrayState.DOWNLOADING:
        view = TrayView(state, "Audio Notes: downloading speech model...", toggle, False, False)
    elif state is TrayState.ERROR:
        view = TrayView(state, f"Audio Notes: error - {error or 'unknown'}", toggle, True, not recording)
    else:
        view = TrayView(state, "Audio Notes: idle", toggle, True, True)
    if recording:
        view = replace(view, mic_label="Microphone (change after stopping)")
    if len(view.tooltip) > MAX_TOOLTIP:
        view = replace(view, tooltip=view.tooltip[: MAX_TOOLTIP - 3] + "...")
    return view
