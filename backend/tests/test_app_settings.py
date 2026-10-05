"""Server-side settings: defaults, round trip, and damaged files."""

import pytest

import app_settings
import credentials


def test_default_is_off_when_nothing_is_saved():
    assert app_settings.load() == {"auto_apply": False}
    assert app_settings.auto_apply() is False


def test_round_trip():
    assert app_settings.save(auto_apply=True) == {"auto_apply": True}
    assert app_settings.auto_apply() is True
    app_settings.save(auto_apply=False)
    assert app_settings.auto_apply() is False


@pytest.mark.parametrize("content", ["", "{not json", "[]", '"x"', '{"auto_apply": "yes"}', '{"auto_apply": 1}'])
def test_a_damaged_file_means_the_default(content):
    credentials.CONFIG_DIR.mkdir(parents=True)
    (credentials.CONFIG_DIR / "settings.json").write_text(content, encoding="utf-8")
    assert app_settings.auto_apply() is False


def test_a_bad_value_or_name_is_refused_and_nothing_is_written():
    with pytest.raises(ValueError):
        app_settings.save(auto_apply="yes")
    with pytest.raises(ValueError):
        app_settings.save(other=True)
    assert not (credentials.CONFIG_DIR / "settings.json").exists()


def test_saving_leaves_no_temp_file():
    app_settings.save(auto_apply=True)
    assert [p.name for p in credentials.CONFIG_DIR.iterdir()] == ["settings.json"]
