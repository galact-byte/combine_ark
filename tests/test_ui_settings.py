from pathlib import Path

from ark_pixel_helper.ui import AppSettings, initial_image_directory


def test_settings_remember_last_successful_image_directory_without_hard_coded_user_paths(tmp_path):
    settings_path = tmp_path / "config" / "settings.json"
    settings = AppSettings.load(settings_path)
    assert settings.last_image_directory is None

    settings.last_image_directory = tmp_path / "chosen"
    settings.last_image_directory.mkdir()
    settings.save(settings_path)

    loaded = AppSettings.load(settings_path)
    assert loaded.last_image_directory == tmp_path / "chosen"


def test_initial_image_directory_prefers_existing_pictures_directory(monkeypatch, tmp_path):
    pictures = tmp_path / "Pictures"
    pictures.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert initial_image_directory() == pictures
