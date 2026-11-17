"""Pure tray state machine: controller facts -> icon kind, tooltip and menu availability."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

MAX_TOOLTIP = 120  # Windows notification-area tooltips are limited to 127 chars


class TrayState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    ERROR = "error"
    DOWNLOADING = "downloading-model"


@dataclass(frozen=True)
class TrayView:
    state: TrayState
    tooltip: str
    toggle_label: str  # label of the start / pause / continue item
    toggle_enabled: bool
    mic_enabled: bool  # whether the microphone item can be clicked
    mic_label: str = "Microphone"
    stop_visible: bool = False  # the "Stop recording" item: shown while a session is open


def compute_state(recording: bool, error: str | None, downloading: bool, paused: bool = False) -> TrayState:
    """Priority: error > downloading > paused > recording > idle."""
    if error:
        return TrayState.ERROR
    if downloading:
        return TrayState.DOWNLOADING
    if recording:
        return TrayState.PAUSED if paused else TrayState.RECORDING
    return TrayState.IDLE


def describe(
    state: TrayState, error: str | None = None, recording: bool = False, paused: bool = False
) -> TrayView:
    """`recording` / `paused` matter in the error state: a session can stay open while capture
    has a problem (e.g. re-binding a lost device), and the menu must then still offer to pause,
    continue or stop it.

    The microphone can only be switched between sessions. While a session is open its item is
    disabled, so unticking it can never look like muting a microphone that is still captured."""
    paused = paused or state is TrayState.PAUSED
    recording = recording or paused or state is TrayState.RECORDING
    toggle = "Start recording" if not recording else "Continue recording" if paused else "Pause recording"
    if state is TrayState.RECORDING:
        view = TrayView(state, "Audio Notes: recording", toggle, True, False)
    elif state is TrayState.PAUSED:
        view = TrayView(state, "Audio Notes: paused", toggle, True, False)
    elif state is TrayState.DOWNLOADING:
        view = TrayView(state, "Audio Notes: downloading speech model...", toggle, False, False)
    elif state is TrayState.ERROR:
        view = TrayView(state, f"Audio Notes: error - {error or 'unknown'}", toggle, True, not recording)
    else:
        view = TrayView(state, "Audio Notes: idle", toggle, True, True)
    if recording:
        view = replace(view, mic_label="Microphone (change after stopping)", stop_visible=True)
    if len(view.tooltip) > MAX_TOOLTIP:
        view = replace(view, tooltip=view.tooltip[: MAX_TOOLTIP - 3] + "...")
    return view
