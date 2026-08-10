# 导入即手动裁切与细节保留：实施计划

## 验证命令

```bash
python -m pytest -q
python -m compileall -q ark_pixel_helper main.py
```

## 任务 1：原图 CropBox 数据契约与转换管线

**文件**：修改 `ark_pixel_helper/image_pipeline.py`；修改 `tests/test_image_pipeline.py`。

1. 写失败测试：合法 `CropBox(100, 50, 400)` 只保留原图对应的正方形；负坐标、越界边长和零边长必须抛出 `ValueError`。
2. 写失败测试：带 crop_box 的 `convert_image()` 输出仍严格是 24×24、每个色号均在 0..39；无 crop_box 时旧 crop/contain/stretch 行为不变。
3. 实现 `CropBox` 与 `ImageOptions.crop_box`，在 `prepare_square()` 优先使用原图坐标框选。
4. 运行图像管线测试，确认旧测试及新增测试通过。

## 任务 2：头像式裁切对话框

**文件**：修改 `ark_pixel_helper/ui.py`；新建/修改 `tests/test_crop_dialog.py`。

1. 写失败测试：屏幕画布与原图 CropBox 坐标换算准确；拖动/缩放结果不会超出图像边界。
2. 实现 `CropDialog(Toplevel)`：原图缩略图、半透明遮罩、1:1 裁切框、框内拖动、四角拖放、滚轮缩放、取消/确认按钮；右侧实时绘制当前框选在当前取样/细节策略下的 24×24 固定40色终局预览。
3. 初始框为尽可能大的居中正方形；若已有 CropBox，重开时使用已有框。
4. 确认回调只传回验证后的 CropBox；取消回调不改变应用状态。
5. 构建对话框烟雾测试，确认不需要游戏窗口或自动化依赖。

## 任务 3：接入导图主流程与细节策略

**文件**：修改 `ark_pixel_helper/ui.py`、`README.md`；修改 `tests/test_ui_settings.py` / 新增测试。

1. 将 `import_image()` 改为：仅临时加载候选图片，打开裁切对话框；用户确认后才保存 source_path、记住目录、写入 CropBox 并调用转换。
2. 增加“重新裁切图片”按钮；无已导入图片时禁用或提示。
3. 默认关闭 `reduce_colors`；将 UI 文案改为“清晰轮廓（最多16主色）”，使保留细节成为默认。
4. 更新状态提示、按钮文案和 README：选图→裁切确认→转换→可修正/导出/自动绘制。
5. 运行 UI 设置测试和全量测试。

## 任务 4：复现素材效果验收与回归

**文件**：必要时增加 `tests/fixtures/` 或测试说明；修改 `CHANGES.md`。

1. 分别使用用户提供的竖幅、横幅人像，手动框选脸/眼睛区域生成 24×24 对比预览；确认角色特征不再被背景和服装主导。
2. 验证转换结果只含游戏 40 色、图纸 PNG/CSV 导出与自动绘制步骤生成仍可用。
3. 运行完整 pytest、compileall、主界面与裁切弹窗烟雾测试；记录真实结果。
4. 更新 Trellis 质量规范中的“导图必须先裁切确认”的可复用契约，并提交工作、规范和任务归档。

## 回滚点

- 若裁切对话框发生异常，保留当前 Pattern，用户仍可用旧图纸和自动绘制流程。
- `crop_box=None` 继续支持旧构图函数，便于修复或回退旧导入记录。
