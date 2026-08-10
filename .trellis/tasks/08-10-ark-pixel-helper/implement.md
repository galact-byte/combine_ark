# 奇象巡展像素拼豆助手：实施计划

> 实施采用 TDD：每个纯逻辑模块先写失败测试，再实现最小代码并运行对应测试；界面与 Windows 自动化以可替换依赖和模拟坐标测试覆盖。

## 验证命令

```bash
python -m pytest -q
python -m compileall -q ark_pixel_helper main.py
```

## 任务 1：项目骨架、40 色调色板与 Pattern 模型

**文件**：新建 `requirements.txt`、`ark_pixel_helper/__init__.py`、`ark_pixel_helper/palette.py`、`ark_pixel_helper/pattern.py`、`tests/test_palette.py`、`tests/test_pattern.py`。

1. 写测试，断言色板恰有 40 个 RGB 三元组，用户色号 1/40 映射正确，OKLab 与 RGB 匹配均返回有效索引。
2. 写测试，断言 `Pattern` 拒绝非 24×24 或色号越界数据，单格修改和非白色统计正确。
3. 运行单元测试，确认在模块不存在时失败。
4. 实现不可变 40 色常量、色号转换、RGB/OKLab 最近色函数及验证过的 `Pattern` 数据类。
5. 重跑测试至通过。

**完成条件**：所有后续模块只通过 `Pattern` 读写 24×24 色号状态。

## 任务 2：图像构图、缩放、量化与降杂色

**文件**：新建 `ark_pixel_helper/image_pipeline.py`、`tests/test_image_pipeline.py`。

1. 创建小尺寸 Pillow 测试图片；为 crop/contain/stretch、透明白底合成、24×24 输出和最近邻模式写失败测试。
2. 为 OKLab 量化和“最多保留 16 种频率最高颜色”写测试；启用减少杂色时断言抖动配置被禁用。
3. 实现 `ImageOptions`、构图、缩放和量化函数，返回 `Pattern` 而非 UI 图像。
4. 对平滑和像素画两种输入运行测试，确认输出仅含 0..39 色号。
5. 重跑整个图像管线测试至通过。

**完成条件**：任一受支持图片都能本地转换成合法、可编辑的 24×24 `Pattern`。

## 任务 3：图纸和色号表导出

**文件**：新建 `ark_pixel_helper/export.py`、`tests/test_export.py`。

1. 写失败测试：图纸 PNG 放大后尺寸正确、每格为调色板颜色、网格线/色号开关生效。
2. 写失败测试：CSV 固定 24 行×24 列，内容为 1..40 的用户色号，使用 UTF-8 编码。
3. 实现 `export_pattern_png(pattern, path, cell_size, show_numbers)` 和 `export_pattern_csv(pattern, path)`，创建父目录并将 I/O 错误转换为用户可展示的异常。
4. 运行导出测试，打开生成的 PNG 回读像素确认颜色。

**完成条件**：用户可不依赖自动化功能，导出可靠的手工填色图纸。

## 任务 4：校准模型与自动填色执行器

**文件**：新建 `ark_pixel_helper/calibration.py`、`ark_pixel_helper/autofill.py`、`tests/test_calibration.py`、`tests/test_autofill.py`。

1. 写失败测试：针对至少两种不同客户区尺寸与 DPI 缩放，坐标能从当前校准数据正确换算；保存/加载校准 JSON 时拒绝缺失或非正尺寸。
2. 写失败测试：`build_fill_steps` 按色号分组、跳过白色索引 3、颜色 1..24 使用顶部色板、25..40 滚动后使用底部色板。
3. 通过注入的 `MouseDriver` 假实现测试点击序列、取消事件和异常停止；不得在测试中真实移动鼠标。
4. 实现 `Calibration`、默认比例坐标、手动校准持久化、`AutoFillRunner` 和 `MouseDriver` Windows/pyautogui 适配器。
5. 执行全套自动化逻辑测试。

**完成条件**：自动绘制算法可预测、可取消、可测试，并在校准后按当前 `Pattern` 实际点击游戏调色板和画布目标格；未校准时拒绝点击。

## 任务 5：简体中文 tkinter 界面与程序入口

**文件**：新建 `ark_pixel_helper/ui.py`、`main.py`、`README.md`。

1. 构建窗口：落地石墨深色“战术像素编辑器”三栏布局与统一视觉 token（细线框、微弱网格底纹、等宽数字、青绿主操作、琥珀自动化警告），并加入导图、构图/取样/降杂色控件、放大网格预览、色号表、单格颜色选择、导出、校准、自动填色与取消按钮。
2. 文件对话框首次通过 `Path.home()` 和系统 Pictures 候选目录动态确定位置，后续从用户应用数据配置读取上次成功选择目录；不得写入 `E:\pictures`、用户名或其他硬编码用户绝对路径。导入 PNG/JPG/JPEG 的异常在状态栏显示中文提示。
3. 每次选项/单格修改时从当前 `Pattern` 刷新预览、统计和色号；导出始终使用当前状态。
4. 自动填色入口显示明确确认，执行时禁用开始按钮、显示进度，完成/取消/异常均恢复界面；检查焦点态、文字状态、按钮禁用态和 44px 点击范围，确保不只用颜色传达状态。
5. 撰写 README：依赖安装、启动、图纸模式、校准、自动填色安全说明、已知限制和不收集数据声明。
6. 人工启动应用并完成一轮导图→修改格子→导出；不运行真实游戏点击。

**完成条件**：非技术用户可按 UI 文案导入图片、检查/修正图案并在有校准条件下启动自动绘制，使当前图案实际填入游戏画布；图纸流程作为可靠兜底。

## 任务 6：全量检查、规范沉淀与提交

1. 运行 `python -m pytest -q` 与 `python -m compileall -q ark_pixel_helper main.py`，逐项修复失败。
2. 检查 README 路径解析、动态初始目录、中文文案、离线处理、白格跳过及取消安全性与 PRD 对应；扫描代码确保没有预设用户绝对路径或单一分辨率运行假设。
3. 按 `trellis-check` 审查跨层数据流和规范；将可复用的 Python 桌面工具约定更新到 `.trellis/spec/`。
4. 检查 `.gitignore` 追加本地 AI 配置忽略项（仅在缺失时）并提交经验证的变更。

## 回滚点

- 自动化模块出现兼容性问题时，保持图像转换、手工编辑与图纸导出可用；自动填色按钮可禁用而不影响核心交付。
- 不写入游戏文件和账号数据；唯一持久化状态是可删除的本地校准 JSON。
