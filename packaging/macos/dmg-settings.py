# dmgbuild settings for the Mac disk image: the app on the left, the Applications link on the
# right (Finder would otherwise sort Applications first). Run as:
#   dmgbuild -s packaging/macos/dmg-settings.py -D app="dist/Lit Review.app" "Lit Review" out.dmg
import os

app = defines["app"]  # noqa: F821 (dmgbuild injects `defines`)
app_name = os.path.basename(app)

format = "UDZO"
files = [app]
symlinks = {"Applications": "/Applications"}
icon_locations = {app_name: (130, 125), "Applications": (370, 125)}
window_rect = ((200, 120), (500, 290))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
icon_size = 192
text_size = 14
arrange_by = None
