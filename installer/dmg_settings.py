"""dmgbuild settings for the macOS disk image: the app plus an Applications shortcut.

Used by installer/build_mac.sh:
    dmgbuild -s installer/dmg_settings.py -D app="dist/Audio Notes.app" "Audio Notes" out.dmg
`defines` (from -D) is injected by dmgbuild when it executes this file.
"""

import os.path

application = defines.get("app", "dist/Audio Notes.app")  # noqa: F821 (injected by dmgbuild)
appname = os.path.basename(application)

format = "UDZO"  # zlib-compressed, read-only
filesystem = "HFS+"
files = [application]
symlinks = {"Applications": "/Applications"}
badge_icon = None
icon_locations = {appname: (140, 160), "Applications": (400, 160)}

background = "builtin-arrow"
window_rect = ((200, 120), (540, 360))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
show_icon_preview = False
icon_size = 128
text_size = 13
arrange_by = None
