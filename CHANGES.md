# 修改记录 — combine_ark

## 2026-08-11 — 手动头像式裁切与像素细节保留

### 背景与目标
- 修复人像和横幅插画直接居中构图时丢失脸部、双眼与发型的问题；导入图片改为先由用户确认原图正方形裁切区域。

### 影响与兼容性
- `Pattern`、24×24 网格、固定 40 色量化、图纸导出及自动填色接口均保持不变。
- 未确认裁切、取消裁切或裁切预览失败时保留当前图案、来源图片和目录；`crop_box=None` 时原有 crop/contain/stretch 管线仍可用。

### 文件与实现
| 操作 | 路径 | 说明 |
|---|---|---|
| 修改 | `ark_pixel_helper/image_pipeline.py` | 新增原图坐标 `CropBox` 校验与优先裁切，并在 24×24 量化前轻度增强明暗/饱和度分离。 |
| 修改 | `ark_pixel_helper/ui.py` | 新增可拖动、四角缩放、滚轮缩放的模态裁切器；导图确认提交、重新裁切和两种细节策略。 |
| 修改 | `tests/test_image_pipeline.py` | 覆盖 CropBox 边界、精确裁切、40 色输出与局部明暗增强。 |
| 新增 | `tests/test_crop_dialog.py`、`tests/conftest.py` | 覆盖画布映射、裁切框边界和 tkinter 裁切确认烟雾行为。 |
| 修改 | `tests/test_ui_settings.py` | 覆盖默认细节策略、取消/预览失败回滚、确认提交及重新裁切复用。 |
| 修改 | `README.md` | 更新“选图→框选→转换→修正/导出/自动填色”使用流程。 |
| 修改 | `.trellis/spec/backend/quality-guidelines.md` | 固化手动裁切的数据契约、错误矩阵及必测回归点。 |

### 验证
- `python -m pytest -q`：48 项通过，覆盖 CropBox 整数边界、精确裁切、取消和预览失败回滚、重开裁切、实时终局预览、40 色输出及既有自动填色安全测试。
- `python -m compileall -q ark_pixel_helper main.py`：通过。
- tkinter `CropDialog` create/confirm/destroy 烟雾脚本：通过；未运行真实游戏点击。

### 已知限制与后续
- 复现素材位于用户本地图片目录，未纳入仓库；已用它们进行裁切器的本地手工预览验证，但仍需要用户在实际窗口中最终选择最满意的框选区域。
- 24×24 和固定 40 色的物理限制仍然存在；用户需紧凑框选脸部和双眼以获得最有效的辨识特征。

## 2026-08-10 — 奇象巡展像素拼豆助手

### 背景与目标
- 新增 Windows 本地 Python 工具：将用户导入图片转换为奇象巡展编辑器可复现的 24×24 固定 40 色 Pattern。
- 提供可编辑网格、手工图纸/色号表导出，以及经用户确认和手动校准后执行的前台自动填色。

### 影响与兼容性
- 新增独立 Python 应用模块，不读取、修改游戏文件、账号或网络数据。
- 需要 Python 3.11+；图像处理依赖 Pillow，自动填色在 Windows 上按需使用 pyautogui。
- 自动填色依赖用户按当前游戏布局完成校准；窗口失焦或用户取消时停止后续点击。

### 文件与实现
| 操作 | 路径 | 说明 |
|---|---|---|
| 新增 | `ark_pixel_helper/palette.py` | 游戏固定 40 色、色号映射与 RGB/OKLab 匹配。 |
| 新增 | `ark_pixel_helper/pattern.py` | 受验证的 24×24 可编辑 Pattern 状态。 |
| 新增 | `ark_pixel_helper/image_pipeline.py` | 构图、透明白底合成、缩放、量化、降杂色与可选抖动。 |
| 新增 | `ark_pixel_helper/export.py` | 带网格 PNG 与 UTF-8 CSV 色号表导出。 |
| 新增 | `ark_pixel_helper/calibration.py`、`autofill.py` | 比例校准、持久化、按颜色分组且可取消的安全点击。 |
| 新增 | `ark_pixel_helper/ui.py`、`main.py` | 中文夏日活动风 tkinter 界面、实时进度条、设置和自动化操作编排。 |
| 新增 | `tests/` | 色板、Pattern、图像管线、导出、校准、自动填色和本地设置测试。 |
| 新增 | `requirements.txt`、`README.md` | 依赖、启动、校准、安全和隐私说明。 |

### 验证
- `python -m pytest -q`：31 项测试通过，覆盖量化、导出、缩放、校准边界、窗口/进程绑定、取消、进度与窗口失焦停止。
- `python -m compileall -q ark_pixel_helper main.py`：Python 编译检查通过。

### 已知限制与后续
- 校准会捕获游戏窗口、按实际客户区预填建议值；画布、顶部/底部色板与滚轮档数仍需用户对照当前游戏界面核对，游戏界面改版后需重新校准。
- 未在真实游戏窗口中执行自动点击验证；测试仅使用注入的假鼠标驱动，避免误操作。
