# 修改记录 — combine_ark

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
