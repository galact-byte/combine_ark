# 技术设计：网格识别 + SendInput 注入 + 校准重构

## 参考项目提炼（取其精华）

研究 JayJokerr 的 arknights-pixel-autofill 与 Arknights-Painter 后确认的病因与修法：

- 病因①（主因）坐标盲猜：`suggested_layout` 只按比例缩放写死的 1280×720 参考矩形，从不截图看真实画布。种子对，缺「网格线识别校正」这一步。
- 病因②点击被吞 + 权限：pyautogui 走 `mouse_event`，Unity 聚焦后走 Raw Input 忽略；游戏以管理员运行时非管理员注入被 UIPI 拒。

采纳 6 条：网格线识别、SendInput 双路注入、管理员权限、BASE 1280×720 居中视口模型、单刻度重锚滚动、F8 急停。舍弃：功能蔓延项、ADB/模拟器线、pywin32 依赖。

## 模块与边界

改动集中在 4 个源文件 + 测试；不碰 image_pipeline / export / palette / pattern。

| 文件 | 变更 |
|---|---|
| `ark_pixel_helper/grid_detect.py` **(新增)** | 纯函数网格识别：截图 → 投影梯度 → 反推画布 Rect 与格心。无 GUI、无 Win32，输入 PIL Image。 |
| `ark_pixel_helper/win_input.py` **(新增)** | ctypes 封装：SendInput 双路注入驱动、坐标归一化、管理员检测/提权、F8 轮询、窗口截图。 |
| `ark_pixel_helper/calibration.py` | 新增 `viewport_seed()`（BASE 1280×720 居中视口模型）；`suggested_layout` 基于视口种子；grid 由识别结果写入。 |
| `ark_pixel_helper/autofill.py` | `MouseDriver` 协议扩展 relative-move；`AutoFillRunner` 滚动改单刻度重锚；接受 `should_abort` 注入 F8。替换默认驱动为 SendInput。 |
| `ark_pixel_helper/ui.py` | 校准弹窗去 19 框，改「捕获→识别→截图预览确认」；F8 提示；启动提权衔接。 |
| `main.py` | 启动时提权：非管理员 → runas 重启。 |

## 1. 网格识别 `grid_detect.py`

### 视口种子模型（初始估计）
游戏按 16:9 居中渲染，多屏/信箱有黑边。`viewport_seed(client)`：在客户区内取最大 16:9 居中矩形作为「逻辑 1280×720 视口」，参考矩形（画布 295..856 / 119..680 等）映射到该视口，得到比裸比例更稳的 ROI 估计。

### 投影式网格线检测（核心，纯函数）
```
detect_grid(image, roi, expected_lines=25, tol=0.15) -> GridResult | None
```
1. 裁 ROI（视口种子画布框 + 边距），转灰度。
2. 竖线：对每列求相邻行梯度绝对值之和 → 得 x 方向 1D 能量信号；横线：对每行同理得 y 信号。
3. 在 1D 信号上做非极大抑制找峰值，筛出约 25 个**近等间距**峰（间距中位数的 ±tol 内）。
4. 25 竖线 + 25 横线 → 画布精确外框（首末线）+ 每格中心（相邻线中点）。
5. 置信度：实际等间距峰数接近 25 且间距方差小 → 返回 `GridResult(cells_bbox, x_lines, y_lines, confidence)`；否则返回 `None`（调用方回退视口种子几何并提示）。

`GridResult` 提供 `cell_center(row, col)`（直接用识别线中点，不再靠比例均分），可反写 `calibration.grid` Rect 兼容既有 ScaledCalibration。

**可测**：`tests/test_grid_detect.py` 用 PIL 合成——在已知偏移/缩放的画布上画 25×25 网格线，断言 `detect_grid` 反推的 bbox/格心与真值误差 ≤1px；再断言无网格的纯色图返回 `None`。

## 2. SendInput 双路注入 `win_input.py`

### 坐标归一化（纯函数，可测）
```
to_absolute(x, y, virtual_rect) -> (ax, ay)   # 0..65535，含 -1 偏移与四舍五入
```
`virtual_rect` = 虚拟桌面 (SM_XVIRTUALSCREEN/…)。单测覆盖左上角(0)、右下角(65535)、越界裁剪。

### 驱动 `SendInputMouse(MouseDriver)`
- `click(x,y)`：① `mouse_move_relative(dx,dy)` 发相对位移事件喂 Raw Input（dx/dy 由上次逻辑位置推算）→ ② `SendInput` 绝对坐标 move 校系统光标 → ③ down → up。三步之间 `PAUSE≈30ms`。
- `scroll(clicks,x,y)`：绝对定位后 `MOUSEEVENTF_WHEEL`，由 `AutoFillRunner` 拆成多次单刻度调用。
- `PostMessage` 兜底：`_post_click(hwnd,x,y)` 备用路径（当前默认走 SendInput，兜底保留接口）。
- 结构体 `INPUT/MOUSEINPUT` 用 ctypes 定义；`SendInput` 失败（返回 0）抛 `InputError`。

**可测**：`to_absolute` 与相对位移增量计算 `relative_delta(prev, cur)` 是纯函数单测；SendInput 实调不进 CI（假驱动覆盖 AutoFillRunner 时序，已有 test_autofill 模式）。

### 管理员 / 提权（决策纯函数 + 薄 Win32 壳）
```
is_admin() -> bool                      # ctypes shell32.IsUserAnAdmin
should_elevate(is_admin, already_tried) -> bool   # 纯函数，可测，防死循环
elevate_and_exit(argv)                  # ShellExecuteW runas；子进程带 --elevated 标记
```
`main.py`：`if should_elevate(is_admin(), "--elevated" in argv): elevate_and_exit(...)` 后 `sys.exit`。非 Windows 直接跳过。

### F8 急停（可测谓词）
```
f8_pressed() -> bool   # GetAsyncKeyState(0x77) 高位
```
`AutoFillRunner.run` 每步前调用注入的 `should_abort()`（默认组合 cancel_event / 前台核验 / f8_pressed），命中即安全停。去掉 pyautogui 的左上角 failsafe。

### 窗口截图
`capture_client(hwnd) -> PIL.Image`：优先 `PrintWindow`，回退 `ImageGrab.grab(bbox=客户区屏幕矩形)`。供网格识别使用。

## 3. calibration.py 变更
- 新增 `viewport_seed(client) -> Calibration`：居中视口模型生成种子（替代裸比例 `suggested_layout` 的内部实现，对外名保留兼容）。
- grid Rect 由 `detect_grid` 结果写入；识别失败回退视口种子 grid。
- 既有 `ScaledCalibration.grid_cell_center` 保留；当有 `GridResult` 时优先用识别线中点（新增可选覆盖），无则维持比例均分。数据模型/持久化格式尽量不破坏既有 `Calibration.load/save` 与 tests。

## 4. autofill.py 变更
- `MouseDriver` 协议加 `move_relative` 可选；`build_fill_steps` 不变。
- 滚动：`scroll` step 拆成 `scroll_clicks` 次单刻度、每次重锚定位（Unity 补偿）。
- `run` 增加 `should_abort: Callable[[], bool]`，替代分散的 cancel/前台判断为统一入口，保持向后兼容默认值。
- 默认驱动从 `PyAutoGuiMouse` 换 `SendInputMouse`；`PyAutoGuiMouse` 可暂留作回退但不再默认。

## 5. ui.py / main.py 变更
- 校准弹窗：删 19 个 Entry。新流程：捕获窗口 → `capture_client` 截图 → `detect_grid` → 在截图预览 Canvas 叠加识别网格与色板框 → 用户「确认使用」或「重新识别」。识别失败显示视口种子框并提示手动微调（保留极简回退，不回到 19 框）。
- 状态栏加 F8 急停说明；确认弹窗文案更新为 SendInput/管理员。
- `main.py` 启动提权衔接（见上）。

## 风险与权衡
- SendInput 仍是合成输入：若游戏有强反作弊可能仍被拒——但对方项目实测 PC 拼豆编辑器可用，且管理员+Raw Input 相对位移是已验证修法。真机验证需用户执行（CI 不覆盖真实注入）。
- 网格识别对极端主题/低对比度画布可能置信度不足 → 回退视口种子并提示，不静默用错坐标（AC4）。
- 提权后工作目录/相对路径可能变化：`elevate_and_exit` 传 `cwd` 与原 argv，应用数据目录用绝对路径（既有实现已如此）。

## 兼容 / 回滚
- 新增文件为主，旧 `calibration.load/save` 格式保持可读；回滚只需还原默认驱动与校准弹窗、删两个新模块。
- 非 Windows：`win_input` 内 Win32 调用延迟导入并守卫，导图/图纸/识别（纯 PIL）不受影响。
