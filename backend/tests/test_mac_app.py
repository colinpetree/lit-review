"""The macOS pieces of the tray: the menu-bar picture, and what the Dock, Cmd+Q and the
menu bar do. AppKit itself only exists on a Mac, so what is tested here is the picture
generation and `MacActions` (all the decisions), plus that the wiring calls them."""

import importlib.util
import sys

import pytest
from PIL import Image, ImageDraw

import bundle
import mac_app
import tray

REPO = bundle.resource_path("..").resolve()
PACKAGING_DIR = REPO / "packaging"


def load_make_icons():
    spec = importlib.util.spec_from_file_location("make_icons", PACKAGING_DIR / "make_icons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMenuTemplate:
    """The macOS menu-bar picture: a plain black cap, 36 px, nothing else."""

    @staticmethod
    def source():
        # A white tile with transparent corners (their RGB is black, as in the real logo)
        # and a dark shape that is wider than it is tall.
        image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((0, 0, 1023, 1023), radius=160, fill=(255, 255, 255, 255))
        draw.rectangle((200, 350, 800, 650), fill=(0, 0, 0, 255))
        return image

    def test_it_is_black_with_the_shape_as_opacity(self):
        image = load_make_icons().menu_template(self.source())
        assert image.size == (36, 36) and image.mode == "RGBA"
        pixels = [image.getpixel((x, y)) for x in range(36) for y in range(36)]
        assert {pixel[:3] for pixel in pixels if pixel[3]} == {(0, 0, 0)}
        for corner in ((0, 0), (35, 0), (0, 35), (35, 35)):
            assert image.getpixel(corner)[3] == 0

    def test_the_tile_is_dropped_and_the_shape_is_centred_at_the_set_width(self):
        icons = load_make_icons()
        image = icons.menu_template(self.source())
        left, top, right, bottom = image.getchannel("A").getbbox()
        assert right - left == icons.MENU_GLYPH_WIDTH_PX
        assert abs((left + right) - 36) <= 1 and abs((top + bottom) - 36) <= 1  # centred
        assert bottom - top < right - left  # wider than tall, like the source shape
        # the white tile did not become a filled square: the shape's box is mostly solid
        # because the shape is a solid rectangle, and nothing outside it is drawn
        outside = sum(
            1
            for x in range(36)
            for y in range(36)
            if not (left <= x < right and top <= y < bottom) and image.getpixel((x, y))[3]
        )
        assert outside == 0

    def test_a_picture_with_nothing_dark_is_refused(self):
        blank = Image.new("RGBA", (1024, 1024), (255, 255, 255, 255))
        with pytest.raises(ValueError):
            load_make_icons().menu_template(blank)

    def test_the_real_logo_gives_a_cap_of_the_set_width(self):
        icons = load_make_icons()
        image = icons.menu_template(Image.open(PACKAGING_DIR / "icon-source.png"))
        left, _top, right, _bottom = image.getchannel("A").getbbox()
        assert right - left == icons.MENU_GLYPH_WIDTH_PX
        assert image.getchannel("A").getextrema()[1] > 200  # solid enough to read


class Recorder:
    def __init__(self, confirm=True):
        self.calls = []
        self.confirm = confirm
        self.pending = []

    def open_app(self):
        self.calls.append("open_app")

    def open_logs(self):
        self.calls.append("open_logs")

    def confirm_quit(self):
        self.calls.append("confirm")
        if isinstance(self.confirm, Exception):
            raise self.confirm
        return self.confirm

    def stop(self):
        self.calls.append("stop")

    def defer(self, target):
        """Stands in for "run on another thread", under the test's control."""
        self.pending.append(target)


def make_actions(recorder, now):
    return mac_app.MacActions(
        recorder.open_app,
        recorder.open_logs,
        recorder.confirm_quit,
        recorder.stop,
        clock=lambda: now[0],
        start_thread=recorder.defer,
    )


class TestMacActions:
    def test_a_reopen_right_after_launch_is_ignored_then_opens_the_app(self):
        recorder, now = Recorder(), [100.0]
        actions = make_actions(recorder, now)
        actions.reopen()
        now[0] += mac_app.REOPEN_IGNORE_SECONDS - 0.1
        actions.reopen()
        assert recorder.calls == []
        now[0] += 0.2
        actions.reopen()
        assert recorder.calls == ["open_app"]

    def test_the_system_quitting_us_is_allowed_at_once_with_no_question(self):
        recorder = Recorder()
        actions = make_actions(recorder, [0.0])
        assert actions.terminate_requested(system_quit=True) == mac_app.TERMINATE_NOW
        assert recorder.calls == [] and recorder.pending == []

    def test_a_user_quit_is_cancelled_so_main_can_clean_up_and_asks_elsewhere(self):
        recorder = Recorder(confirm=True)
        actions = make_actions(recorder, [0.0])
        assert actions.terminate_requested(system_quit=False) == mac_app.TERMINATE_CANCEL
        assert recorder.calls == []  # nothing happened on the calling (main) thread
        recorder.pending.pop()()
        assert recorder.calls == ["confirm", "stop"]

    def test_declining_the_question_keeps_the_app_running(self):
        recorder = Recorder(confirm=False)
        actions = make_actions(recorder, [0.0])
        actions.terminate_requested(False)
        recorder.pending.pop()()
        assert recorder.calls == ["confirm"]

    def test_a_second_quit_while_a_question_is_open_does_not_ask_again(self):
        recorder = Recorder()
        actions = make_actions(recorder, [0.0])
        actions.terminate_requested(False)
        assert actions.terminate_requested(False) == mac_app.TERMINATE_CANCEL
        assert len(recorder.pending) == 1
        recorder.pending.pop()()
        actions.terminate_requested(False)  # answered, so asking works again
        assert len(recorder.pending) == 1

    def test_a_failing_question_still_lets_quit_ask_next_time(self):
        recorder = Recorder(confirm=RuntimeError("dialog failed"))
        actions = make_actions(recorder, [0.0])
        actions.terminate_requested(False)
        recorder.pending.pop()()
        recorder.confirm = True
        actions.terminate_requested(False)
        assert len(recorder.pending) == 1

    def test_installing_without_appkit_fails_quietly(self, monkeypatch):
        # With AppKit unavailable (forced, so this also holds on a Mac runner, where the real
        # one would install a delegate into the test process), install() must return None and
        # the caller then uses the older handler.
        monkeypatch.setitem(sys.modules, "AppKit", None)
        assert mac_app.install(object()) is None


class TestTrayOnMac:
    def test_the_menu_bar_quit_uses_the_same_path_as_cmd_q(self):
        asked = []

        class FakeActions:
            def terminate_requested(self, system_quit):
                asked.append(system_quit)

        icon = tray.Tray(lambda: None, lambda: None, lambda: pytest.fail("asked on the menu thread"))
        icon._mac_actions = FakeActions()
        icon._quit(object(), object())
        assert asked == [False]

    def test_the_menu_bar_picture_is_swapped_in_after_the_icon_is_visible(self, monkeypatch, tmp_path):
        image = tmp_path / "trayTemplate.png"
        image.write_bytes(b"png")
        placed = []
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(tray, "_menu_template_path", lambda: image)
        monkeypatch.setattr(mac_app, "set_menu_bar_image", lambda icon, path: placed.append((icon, path)))

        class FakeIcon:
            visible = False

        fake = FakeIcon()
        tray.Tray(lambda: None, lambda: None, lambda: True)._setup(fake)
        assert fake.visible and placed == [(fake, image)]

    def test_no_menu_bar_picture_work_off_a_mac(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")  # whatever this runs on
        monkeypatch.setattr(mac_app, "set_menu_bar_image", lambda *a: pytest.fail("macOS only"))

        class FakeIcon:
            visible = False

        tray.Tray(lambda: None, lambda: None, lambda: True)._setup(FakeIcon())


class TestMacBuildPieces:
    SPEC = bundle.resource_path("pyinstaller.spec").read_text(encoding="utf-8")
    WORKFLOW = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_the_spec_ships_the_menu_bar_picture(self):
        assert '"trayTemplate.png"' in self.SPEC

    def test_the_icon_key_is_only_named_when_the_compiled_icon_exists(self):
        assert "if ASSETS_CAR.is_file():" in self.SPEC and '"CFBundleIconName"' in self.SPEC

    def test_the_icon_is_in_the_app_before_it_is_signed(self):
        copy = self.WORKFLOW.index("Put the macOS 26 icon in the app")
        sign = self.WORKFLOW.index("Sign the macOS app ad hoc")
        assert copy < sign  # a file added after signing would break the signature

    def test_the_glyph_files_are_committed_as_filled_shapes(self):
        # Icon Composer's layer Fill colours a layer's shapes, so the cap must be a filled
        # shape with holes, not strokes (a stroke-only drawing got flooded and stopped
        # looking like a cap).
        for name, color in (("glyph-black.svg", "#000000"), ("glyph-white.svg", "#FFFFFF")):
            text = (PACKAGING_DIR / "macos" / name).read_text(encoding="utf-8")
            assert text.startswith("<svg") and text.count("<path") == 1
            assert f'fill="{color}"' in text and 'fill-rule="evenodd"' in text
            assert "stroke" not in text
            assert text.count(" Z") == 3  # the outside, the cap top's hole and the band's hole


class TestTallShape:
    def test_a_tall_shape_is_fitted_by_its_height_not_cut_off(self):
        icons = load_make_icons()
        image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1023, 1023), fill=(255, 255, 255, 255))
        draw.rectangle((450, 100, 574, 900), fill=(0, 0, 0, 255))  # tall and thin
        left, top, right, bottom = icons.menu_template(image).getchannel("A").getbbox()
        assert top >= 0 and bottom <= 36 and bottom - top == 36
        assert right - left < icons.MENU_GLYPH_WIDTH_PX
