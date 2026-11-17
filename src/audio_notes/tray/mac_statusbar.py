"""macOS menu bar shell for `TrayApp`: an NSStatusItem with an NSMenu, through PyObjC.

- Accessory activation policy: no Dock icon, no app menu (a menu bar utility).
- Template icon (tray/icons.py `menubar_icon`), so macOS tints it for light / dark / tinted menu
  bars; the recording icon keeps a red dot and picks a black or white pencil from the menu bar's
  appearance, re-checked twice a second.
- The menu is rebuilt from `mac_menu.build_menu` each time it opens (NSMenuDelegate), so it never
  shows stale state. Item actions run on background threads, like the pystray backend: starting a
  recording can load the model for seconds.
- While a session is capturing, an NSProcessInfo activity (user initiated) keeps App Nap and idle
  sleep away; it is released when recording pauses or stops.
- Notifications go through `osascript` (UNUserNotificationCenter needs a signed app bundle).

All PyObjC imports are inside functions, so this module imports on Windows (for tests).
"""

from __future__ import annotations

import io
import logging
import signal
import subprocess
import threading
from typing import TYPE_CHECKING, Any, Callable, Sequence

from audio_notes.tray import first_run, mac_menu
from audio_notes.tray.icons import MENUBAR_PT, app_icon, menubar_icon
from audio_notes.tray.state import TrayState

if TYPE_CHECKING:
    from audio_notes.capture.mac_tap import Permissions
    from audio_notes.tray.app import TrayApp
    from audio_notes.tray.state import TrayView

log = logging.getLogger(__name__)

TICK_S = 0.5  # appearance check; also lets Python run its SIGINT / SIGTERM handlers
ACTIVITY_REASON = "Audio Notes is recording and transcribing"
MENUBAR_HINT = "Audio Notes is in the menu bar, at the top right of the screen."

_app_ready = False


# ---- AppKit helpers --------------------------------------------------------------------------
def _ensure_app() -> Any:
    """The shared NSApplication as a menu bar utility (no Dock icon), with our app icon (alerts)."""
    global _app_ready
    import AppKit

    app = AppKit.NSApplication.sharedApplication()
    if not _app_ready:
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        try:
            app.setApplicationIconImage_(pil_to_nsimage([app_icon(256)], 256))
        except Exception:  # noqa: BLE001 - cosmetic
            log.debug("could not set the application icon", exc_info=True)
        _app_ready = True
    return app


def pil_to_nsimage(images: Sequence[Any], size_pt: float, template: bool = False) -> Any:
    """PIL images of one picture at several scales -> one NSImage of `size_pt` points."""
    import AppKit
    import Foundation

    ns = AppKit.NSImage.alloc().initWithSize_((size_pt, size_pt))
    for im in images:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        png = buf.getvalue()
        rep = AppKit.NSBitmapImageRep.imageRepWithData_(Foundation.NSData.dataWithBytes_length_(png, len(png)))
        rep.setSize_((size_pt, size_pt))
        ns.addRepresentation_(rep)
    ns.setTemplate_(template)
    return ns


def run_on_main(fn: Callable[[], Any]) -> Any:
    """Run `fn` on the main thread and return its result (AppKit UI must run there). From a
    background thread this needs the main run loop to be running (it is, once the menu is up)."""
    from Foundation import NSThread

    if NSThread.isMainThread():
        return fn()
    from PyObjCTools import AppHelper

    done = threading.Event()
    box: dict[str, Any] = {}

    def call() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = e
        finally:
            done.set()

    AppHelper.callAfter(call)
    done.wait()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def alert(title: str, message: str, buttons: Sequence[str] = ("OK",), warning: bool = False) -> int:
    """Modal NSAlert; returns the index of the button pressed (0 = first)."""

    def show() -> int:
        import AppKit

        app = _ensure_app()
        a = AppKit.NSAlert.alloc().init()
        a.setMessageText_(title)
        a.setInformativeText_(message)
        a.setAlertStyle_(AppKit.NSAlertStyleWarning if warning else AppKit.NSAlertStyleInformational)
        for b in buttons:
            a.addButtonWithTitle_(b)
        app.activateIgnoringOtherApps_(True)  # an accessory app is not frontmost by itself
        return int(a.runModal()) - int(AppKit.NSAlertFirstButtonReturn)

    return run_on_main(show)


def notify_osascript(message: str, title: str) -> None:
    """Notification Center banner. The text goes in as arguments, never into the script source."""
    subprocess.Popen(
        ["osascript", "-e", "on run argv", "-e",
         "display notification (item 1 of argv) with title (item 2 of argv)", "-e", "end run",
         message, title],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def open_with_system(url: str) -> None:
    subprocess.run(["open", url], check=False)


_delegate_class: Any = None


def _menu_delegate_class() -> Any:
    """NSObject subclass bridging NSMenu callbacks to the backend (registered with the ObjC
    runtime once per process, hence the cache)."""
    global _delegate_class
    if _delegate_class is None:
        import objc
        from Foundation import NSObject

        class AudioNotesMenuDelegate(NSObject):
            def initWithBackend_(self, backend):  # noqa: N802 - ObjC selector
                self = objc.super(AudioNotesMenuDelegate, self).init()
                if self is None:
                    return None
                self.backend = backend
                return self

            def menuNeedsUpdate_(self, menu):  # noqa: N802 - NSMenuDelegate
                self.backend.populate(menu)

            def itemClicked_(self, sender):  # noqa: N802 - menu item action
                self.backend.clicked(int(sender.tag()))

        _delegate_class = AudioNotesMenuDelegate
    return _delegate_class


def _version() -> str:
    from audio_notes import __version__

    return __version__


# ---- backend ---------------------------------------------------------------------------------
class MacStatusBarBackend:
    def __init__(
        self,
        *,
        check_permissions: Callable[[], "Permissions"] | None = None,
        request_permissions: Callable[[], object] | None = None,
        open_url: Callable[[str], object] = open_with_system,
        dialog: first_run.Dialog | None = None,
    ) -> None:
        self._check_permissions = check_permissions
        self._request_permissions = request_permissions
        self._open_url = open_url
        self._dialog = dialog
        self._app: TrayApp | None = None
        self._item: Any = None
        self._menu: Any = None
        self._delegate: Any = None
        self._timer: Any = None
        self._actions: list[Callable[[], None] | None] = []
        self._perms: Permissions | None = None
        self._perms_lock = threading.Lock()
        self._perms_busy = False
        self._activity: Any = None
        self._dark = False
        self._images: dict[tuple[TrayState, bool], Any] = {}
        self._view: TrayView | None = None

    # -- TrayBackend -----------------------------------------------------------------------------
    def run(self, app: "TrayApp", on_ready: Callable[[], None]) -> None:
        import AppKit
        import Foundation

        self._app = app
        nsapp = _ensure_app()
        first_launch = first_run.ensure_permissions_explained(
            self._dialog or first_run.native_confirm, self._request_permissions or self._default_request,
        )
        self._item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        self._menu = AppKit.NSMenu.alloc().init()
        self._menu.setAutoenablesItems_(False)
        self._delegate = _menu_delegate_class().alloc().initWithBackend_(self)
        self._menu.setDelegate_(self._delegate)
        self._item.setMenu_(self._menu)
        self._dark = self._menubar_is_dark()
        self._apply(app.view())
        self._timer = Foundation.NSTimer.scheduledTimerWithTimeInterval_repeats_block_(TICK_S, True, self._tick)
        previous = {sig: signal.signal(sig, self._on_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
        self.refresh_permissions()
        if first_launch:
            self.notify(MENUBAR_HINT, "Audio Notes")
        on_ready()
        try:
            nsapp.run()  # returns after stop()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if self._timer is not None:
                self._timer.invalidate()
            self._set_activity(False)
            AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self._item)
            self._item = None

    def update(self, view: "TrayView", mic_on: bool) -> None:
        from PyObjCTools import AppHelper

        AppHelper.callAfter(self._apply, view)
        self.refresh_permissions()  # state changed (e.g. a capture error): re-check in the background

    def notify(self, message: str, title: str) -> None:
        notify_osascript(message, title)

    def stop(self) -> None:
        from PyObjCTools import AppHelper

        AppHelper.callAfter(self._stop_on_main)

    def refresh_key(self) -> object:
        return self._dark

    # -- menu ------------------------------------------------------------------------------------
    def menu_entries(self) -> list[mac_menu.MenuEntry]:
        app = self._app
        assert app is not None
        actions = mac_menu.MenuActions(
            toggle_recording=app.toggle_recording,
            stop_recording=app.stop_recording,
            toggle_mic=app.toggle_mic,
            open_panel=app.open_panel,
            open_transcripts=app.open_transcripts,
            connect_to_claude=app.connect_to_claude,
            open_url=self._open_url,
            check_for_updates=self.check_for_updates,
            about=self.about,
            quit=app.quit,
        )
        return mac_menu.build_menu(app.view(), mic_on=app.controller.mic_enabled(),
                                   error=app.controller.last_error(), perms=self._perms, actions=actions)

    def populate(self, menu: Any) -> None:
        """NSMenuDelegate.menuNeedsUpdate: (main thread)."""
        import AppKit

        menu.removeAllItems()
        self._actions = []
        for entry in self.menu_entries():
            if entry.separator:
                menu.addItem_(AppKit.NSMenuItem.separatorItem())
                continue
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                entry.title, "itemClicked:" if entry.action else None, entry.key)
            item.setTarget_(self._delegate)
            item.setTag_(len(self._actions))
            item.setEnabled_(entry.enabled and entry.action is not None)
            item.setState_(AppKit.NSControlStateValueOn if entry.checked else AppKit.NSControlStateValueOff)
            if entry.symbol:
                image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(entry.symbol, None)
                if image is not None:
                    item.setImage_(image)
            menu.addItem_(item)
            self._actions.append(entry.action)
        self.refresh_permissions()  # for the next time the menu opens

    def clicked(self, tag: int) -> None:
        action = self._actions[tag] if 0 <= tag < len(self._actions) else None
        if action is not None:
            threading.Thread(target=self._safely, args=(action,), daemon=True, name="menu-action").start()

    @staticmethod
    def _safely(action: Callable[[], None]) -> None:
        try:
            action()
        except Exception:  # noqa: BLE001
            log.exception("menu action failed")

    def check_for_updates(self) -> None:
        if alert("Check for Updates", mac_menu.updates_message(_version()),
                 buttons=("Open Releases Page", "Close")) == 0:
            self._open_url(mac_menu.RELEASES_URL)

    def about(self) -> None:
        alert("Audio Notes", mac_menu.about_message(_version()))

    # -- permissions -----------------------------------------------------------------------------
    def _default_request(self) -> object:
        from audio_notes.capture import mac_tap

        return mac_tap.permissions(request=True)

    def refresh_permissions(self) -> None:
        """Re-read the permission status in the background (spawns the helper; never on the UI
        thread). The menu uses the last known value."""
        with self._perms_lock:
            if self._perms_busy:
                return
            self._perms_busy = True

        def work() -> None:
            try:
                if self._check_permissions is not None:
                    perms = self._check_permissions()
                else:
                    from audio_notes.capture import mac_tap

                    perms = mac_tap.permissions()
                self._perms = perms
            except Exception as e:  # noqa: BLE001 - helper missing etc.: keep the last value
                log.debug("permission check failed: %s", e)
            finally:
                with self._perms_lock:
                    self._perms_busy = False

        threading.Thread(target=work, daemon=True, name="permission-check").start()

    # -- main-thread internals -------------------------------------------------------------------
    def _apply(self, view: "TrayView") -> None:
        self._view = view
        if self._item is None:
            return
        button = self._item.button()
        button.setImage_(self._image(view.state))
        button.setToolTip_(view.tooltip)
        app = self._app
        capturing = bool(app and app.controller.is_recording() and not app.controller.is_paused())
        self._set_activity(capturing)

    def _image(self, state: TrayState) -> Any:
        key = (state, self._dark and state is TrayState.RECORDING)
        if key not in self._images:
            imgs = [menubar_icon(state, scale, key[1]) for scale in (1, 2)]
            self._images[key] = pil_to_nsimage([im for im, _ in imgs], MENUBAR_PT, template=imgs[0][1])
        return self._images[key]

    def _menubar_is_dark(self) -> bool:
        import AppKit

        try:
            appearance = self._item.button().effectiveAppearance()
            best = appearance.bestMatchFromAppearancesWithNames_(
                [AppKit.NSAppearanceNameAqua, AppKit.NSAppearanceNameDarkAqua])
            return best == AppKit.NSAppearanceNameDarkAqua
        except Exception:  # noqa: BLE001
            return False

    def _tick(self, _timer: Any) -> None:
        dark = self._menubar_is_dark()
        if dark != self._dark:
            self._dark = dark
            if self._view is not None and self._view.state is TrayState.RECORDING:
                self._apply(self._view)

    def _set_activity(self, on: bool) -> None:
        import Foundation

        info = Foundation.NSProcessInfo.processInfo()
        if on and self._activity is None:
            # User initiated = no App Nap and no idle system sleep while capturing.
            self._activity = info.beginActivityWithOptions_reason_(Foundation.NSActivityUserInitiated,
                                                                   ACTIVITY_REASON)
        elif not on and self._activity is not None:
            info.endActivity_(self._activity)
            self._activity = None

    def _on_signal(self, signum: int, _frame: Any) -> None:
        log.info("signal %d: quitting", signum)
        app = self._app
        threading.Thread(target=app.quit if app else self.stop, daemon=True, name="quit").start()

    def _stop_on_main(self) -> None:
        """NSApp.stop_ only takes effect after the next event, so post a dummy one."""
        import AppKit

        nsapp = AppKit.NSApplication.sharedApplication()
        nsapp.stop_(None)
        event = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(  # noqa: E501
            AppKit.NSEventTypeApplicationDefined, (0.0, 0.0), 0, 0.0, 0, None, 0, 0, 0)
        nsapp.postEvent_atStart_(event, True)
