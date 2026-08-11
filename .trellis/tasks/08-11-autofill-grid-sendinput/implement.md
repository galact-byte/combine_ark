# 执行计划：网格识别 + SendInput 注入 + 校准重构

遵循 Red → Green → Refactor。每步跑验证命令，全绿再进下一步。不碰真实游戏（CI 只覆盖纯函数与假驱动）。

## 验证命令
```bash
python -m pytest -q
python -m compileall -q ark_pixel_helper main.py
```

## 步骤

### S1 网格识别（grid_detect.py）— RED→GREEN
- [ ] RED：`tests/test_grid_detect.py`
  - 合成：在 300×300 画布上、已知偏移(ox,oy)与格边 s，画 25×25 网格线到更大底图。
  - 断言 `detect_grid(img, roi)` 返回 `GridResult`，`cells_bbox` 与真值误差 ≤1px，`cell_center(0,0)`/`cell_center(23,23)` 命中真值格心 ≤1px。
  - 断言纯色/无网格图返回 `None`（低置信度回退）。
- [ ] GREEN：实现 `grid_detect.py`：`viewport`辅助、`detect_grid`（投影梯度 + 等间距峰筛选）、`GridResult` dataclass 与 `cell_center`。
- [ ] 验证命令全绿。

### S2 坐标归一化 + 相对位移（win_input.py 纯函数）— RED→GREEN
- [ ] RED：`tests/test_win_input.py`
  - `to_absolute(x,y,virtual_rect)`：左上→(0,0) 附近、右下→65535 附近、越界裁剪。
  - `relative_delta(prev,cur)`：增量正确；prev=None 时返回(0,0) 或首帧策略。
  - `should_elevate(is_admin, already_tried)`：admin→False；非 admin 未试→True；非 admin 已试→False（防死循环）。
- [ ] GREEN：实现上述纯函数。
- [ ] 验证命令全绿。

### S3 SendInput 驱动 + Win32 壳（win_input.py）— GREEN（非 CI 实调）
- [ ] 实现 `SendInputMouse`（ctypes INPUT/MOUSEINPUT、双路 click、单刻度 scroll、PostMessage 兜底接口）、`is_admin`、`elevate_and_exit`、`f8_pressed`、`capture_client`。
- [ ] Win32 调用延迟导入 + 非 Windows 守卫。
- [ ] `compileall` 通过；纯函数测试仍绿。

### S4 autofill.py 接入 — RED→GREEN
- [ ] RED：扩展 `tests/test_autofill.py`
  - 假驱动记录调用序列：断言滚动被拆成 N 次单刻度且每次先定位（重锚）。
  - 断言 `should_abort` 命中时立即停止、不再发点击。
- [ ] GREEN：`MouseDriver` 加 `move_relative`；`run` 加 `should_abort`；滚动改单刻度重锚；默认驱动换 `SendInputMouse`（测试仍注入假驱动）。
- [ ] 保持既有 test_autofill 全绿（向后兼容默认参数）。

### S5 calibration.py 视口种子 — RED→GREEN
- [ ] RED：`tests/test_calibration.py` 加 `viewport_seed`：不同客户区（含非 16:9、带黑边）下画布框落在客户区内、居中、比例正确。
- [ ] GREEN：实现 `viewport_seed`；`suggested_layout` 复用它。保持 `Calibration.load/save` 既有格式与旧测试全绿。

### S6 ui.py / main.py — GREEN + 烟雾
- [ ] 校准弹窗去 19 框，改「捕获→识别→截图预览确认」；识别失败回退视口种子框 + 提示。
- [ ] 状态栏/确认弹窗文案更新（SendInput/管理员/F8）。
- [ ] `main.py` 启动提权：`should_elevate` + `elevate_and_exit`，非 Windows 跳过。
- [ ] 烟雾测试：主界面与校准弹窗构造不崩（沿用 test_ui_* 模式，Win32/截图 mock）。

### S7 全量验证 — Refactor
- [ ] `python -m pytest -q` 全绿、`python -m compileall -q ark_pixel_helper main.py` 通过。
- [ ] 一轮聚焦重构（命名/重复/错误处理），保持全绿。

### S8 收尾
- [ ] 更新 `.trellis/spec/`（后端注入/识别约定）与 `CHANGES.md`、`README.md`（自动填色章节改写）。
- [ ] 更新 journal；`task.py` 归档流程；提交。

## 审查门 / 回滚点
- S1、S4 后各是一个可回滚点（新模块 + 假驱动测试独立）。
- 真机注入无法在 CI 验证：交付时明确说明「已过单测/编译/烟雾，真实游戏注入需用户在管理员下实测」。
- 依赖不新增；若发现必须 pywin32 才能可靠截图/枚举，先停下与用户确认（违背约束需批准）。
