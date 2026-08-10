from pathlib import Path
from PIL import Image

import ark_pixel_helper.ui as ui
from ark_pixel_helper.image_pipeline import CropBox
from ark_pixel_helper.ui import AppSettings, PixelHelperApp, initial_image_directory


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


def test_default_detail_strategy_keeps_more_color_information(root):
    app = PixelHelperApp(root)

    assert app.reduce_colors.get() is False
    assert app.detail_strategy.get() == "更多颜色细节（完整 40 色候选）"

    app.detail_strategy.set("清晰轮廓（最多 16 主色）")
    assert app._image_options().reduce_colors is True


def test_import_cancel_keeps_the_current_pattern_source_and_image_directory(root, monkeypatch, tmp_path):
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (100, 50), (211, 47, 54)).save(image_path)
    app = PixelHelperApp(root)
    previous_pattern = app.pattern
    previous_directory = app.settings.last_image_directory
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **_kwargs: str(image_path))
    monkeypatch.setattr(ui, "CropDialog", lambda *_args: None)

    app.import_image()

    assert app.source_image is None
    assert app.source_path is None
    assert app.pattern is previous_pattern
    assert app.settings.last_image_directory == previous_directory


def test_import_keeps_the_current_pattern_when_crop_dialog_cannot_open(root, monkeypatch, tmp_path):
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (100, 50), (211, 47, 54)).save(image_path)
    app = PixelHelperApp(root)
    previous_pattern = app.pattern
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **_kwargs: str(image_path))
    monkeypatch.setattr(ui, "CropDialog", lambda *_args: (_ for _ in ()).throw(ValueError("预览失败")))

    app.import_image()

    assert app.source_image is None
    assert app.pattern is previous_pattern
    assert "裁切确认页" in app.status.get()


def test_recrop_opens_with_the_current_crop_box(root, monkeypatch):
    app = PixelHelperApp(root)
    app.source_image = Image.new("RGB", (100, 50), (211, 47, 54))
    app.crop_box = CropBox(25, 0, 50)
    received: list[CropBox | None] = []
    monkeypatch.setattr(ui, "CropDialog", lambda _parent, _image, _on_confirm, crop_box, _options: received.append(crop_box))

    app.recrop_image()

    assert received == [CropBox(25, 0, 50)]


def test_import_commits_the_confirmed_crop_box_before_conversion(root, monkeypatch, tmp_path):
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (100, 50), (211, 47, 54)).save(image_path)
    app = PixelHelperApp(root)
    app.settings = AppSettings()
    monkeypatch.setattr(app.settings, "save", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **_kwargs: str(image_path))

    def confirm_crop(_parent, _image, on_confirm, _existing_crop, _options):
        on_confirm(CropBox(25, 0, 50))

    monkeypatch.setattr(ui, "CropDialog", confirm_crop)

    app.import_image()

    assert app.source_path == image_path
    assert app.crop_box == CropBox(25, 0, 50)
    assert app._image_options().crop_box == CropBox(25, 0, 50)
    assert app.pattern.non_white_count > 0
