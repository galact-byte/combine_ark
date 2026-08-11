# 修改记录 — combine_ark

## 2026-08-11 — 色板“认色”识别修复颜色错（UI 缩放免疫）

### 背景
- 上一步 SendInput+提权后自动填色**能画了**，但真机发现**颜色错**（大片绿+头发蓝紫未上色）。根因：游戏分辨率 1600×900 + **UI 缩放 90**，色板面板贴右边缘、随缩放内收，与按中心缩放的画布不同步（实测画布中心 45%% 不变、色板中心 85%%→82.5%%）；而色板之前只靠视口种子猜。

### 修复
- 新增 `ark_pixel_helper/palette_locate.py`：用已知 40 色精确 RGB 在截图**画布右侧**（用识别到的画布框排除画布）“认色板”：最近色归类得色块中心，按色号固定 `col=k%%4/row=k//4` 最小二乘拟合出色板矩形。对 UI 缩放/分辨率免疫。
- `calibration.py` 新增 `calibration_from_capture`：一张截图同时出画布+色板；底部色板=顶部矩形（面板同屏原地换内容），滚轮给足量（over-scroll 自然停在色号 17–40 可见）。
- `ui.py` 校准预览叠加色板框（蓝=识别、橙=回退）并提示。
- 两页模型经真机截图确认：顶页色号 1–24、底页滚到底色号 17–40（偏移 16，与现有 `palette_center` 的 color-16 一致）。

### 验证
- `python -m pytest -q`：64 项通过（新增色板识别矩形拟合、空图回退、画布+色板合成集成）。
- `python -m compileall`：通过。Windows 探针：calibration_from_capture 对合成编辑器图准确出画布(370,150,700,700)+色板(1200,330,320,456)，选色中心映射正确。
- 真机整图颜色正确性仍需用户管理员下实测。

## 2026-08-11 — 自动填色改用网格识别与 SendInput 注入

### 背景与目标
- 修复“自动填色跑完但游戏画布全空”：用户实测完全无反应。两个病因——① `pyautogui`（`mouse_event`）被 Unity Raw Input 吞且非管理员注入被 UIPI 拒；② 校准靠手填 19 个比例矩形，非 1280×720 下整体偏出格子。
- 方案取自参考项目（arknights-pixel-autofill、Arknights-Painter）的取舍：网格识别、SendInput 双路注入、启动提权、居中视口模型、单刻度滚动、F8 急停。

### 影响与兼容性
- `Pattern`、图像管线、图纸导出、`Calibration.load/save` 格式保持不变；旧校准文件仍可读。
- 自动填色现需管理员权限：`python main.py` 启动时非管理员会弹 UAC 重启（只尝试一次）。非 Windows 自动跳过提权与注入。
- 校准弹窗由“手填 19 框”改为“捕获→截图识别→预览确认”；失焦急停由“鼠标移左上角”改为 F8。

### 文件与实现
| 操作 | 路径 | 说明 |
|---|---|---|
| 新增 | `ark_pixel_helper/grid_detect.py` | 纯 PIL 投影式网格线识别，反推画布外框与每格中心，置信度不足返回 None。 |
| 新增 | `ark_pixel_helper/win_input.py` | ctypes SendInput 双路驱动、坐标归一化、管理员检测/提权、F8 轮询、客户区截图；`windll` 均 Windows 守卫。 |
| 修改 | `ark_pixel_helper/calibration.py` | 新增 `viewport_seed` 居中视口模型与 `detect_grid_rect`；`suggested_layout` 改为复用视口种子。 |
| 修改 | `ark_pixel_helper/autofill.py` | `run` 新增 `should_abort` 统一急停；滚动拆单刻度重锚；MouseDriver 支持相对位移。 |
| 修改 | `ark_pixel_helper/ui.py` | 校准弹窗改截图识别预览确认；worker 改用 SendInput 驱动 + F8/失焦统一急停。 |
| 修改 | `main.py` | 启动时管理员检测与 runas 提权（防 UAC 拒绝死循环）。 |
| 新增 | `tests/test_grid_detect.py`、`tests/test_win_input.py` | 网格识别反推/ROI/回退；坐标归一化/相对位移/提权决策。 |
| 修改 | `tests/test_autofill.py`、`tests/test_calibration.py`、`tests/test_ui_settings.py` | 单刻度滚动、should_abort、视口种子、校准弹窗无输入框烟雾。 |
| 修改 | `.trellis/spec/backend/quality-guidelines.md` | 固化注入双路/网格识别/提权/单刻度滚动/F8 契约与检查项。 |

### 验证
- `python -m pytest -q`：61 项通过（新增网格识别、win_input 纯函数、单刻度滚动/should_abort、视口种子、校准弹窗烟雾）。
- `python -m compileall -q ark_pixel_helper main.py`：通过。
- Windows 上实例化验证：INPUT 结构体 40 字节、SendInputMouse 初始化、虚拟桌面读取、`is_admin=False` 均正常；**未**在真实游戏中发送点击。

### 已知限制与后续
- 真实注入效果（SendInput 是否被游戏接受）需用户以**管理员**启动后在真实拼豆编辑器中实测；CI 不覆盖真实点击与提权。
- 色板色块仍用视口种子建议值 + 可视确认，未做全自动色彩识别；极端主题下网格识别可能回退种子几何。

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
