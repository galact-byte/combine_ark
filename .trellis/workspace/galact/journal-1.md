# Journal - galact (Part 1)

> AI development session journal
> Started: 2026-08-10

---

## 2026-08-11 — 选色改实时认色块，修复第二页错位

- 真机再测：轮廓对了但颜色错。裁两边画布逐格比对 → 深紫/藏蓝头发（第二页）画成橄榄绿土黄。根因：底页靠固定偏移16算位置，但滚动没停在假设位置。
- 修：`autofill.run` 加 `select_color`，填每色前当场截图用该色 RGB 在色板 ROI 里找实际色块（swatch_centers），找不到就滚再找，彻底不靠滚动偏移。
- 子问题：面板深灰底色(58,58,60)离藏蓝色号很近 → 背景拖偏质心。取 ROI 众数色为底色，丢弃离底色更近的像素。探针：色号28精确到(1240,596)。
- 验证：pytest 66 passed；compileall 通过。真机整图仍待用户实测。

## 2026-08-11 — 色板“认色”识别修复颜色错

- 真机反馈：SendInput+提权后能画了（主修复成功），但颜色错。用户依次给了游戏截图、设置页（分辨率 1600×900 + UI 缩放 90）、两页色板图。
- 从截图量坐标定位根因：色板面板贴右边缘、UI 缩放下内收（中心 85%→82.5%），与按中心缩放的画布（45% 不变）不同步 → 不能锚定画布也不能固定比例。
- 新增 `palette_locate.py`：用已知 40 色“认色板”（最近色归类 + 按 col=k%4/row=k//4 最小二乘拟合），对 UI 缩放免疫；`calibration_from_capture` 一张图出画布+色板，底部色板=顶部矩形、滚轮足量。两页模型真机确认（顶 1–24/底 17–40 偏移16）。
- 验证：`pytest -q` 64 passed；`compileall` 通过；Windows 探针确认合成图识别准确。真机整图颜色仍待用户实测。

## 2026-08-11 — 自动填色改网格识别 + SendInput 注入 + 启动提权

- 回看早期会话（`trellis mem` 检索 019fecf2-074）找回参考项目“取精华去糟粕”的原始判断，先把 PRD/design/implement 三件套补齐并对齐，再 `task.py start`。
- 病因确认：① `suggested_layout` 只按比例缩放写死矩形从不看真实画布（点击偏出格）；② pyautogui `mouse_event` 被 Unity Raw Input 吞 + 非管理员被 UIPI 拒（用户实测完全无反应）。
- 新增 `grid_detect.py`（纯 PIL 投影式网格线识别）与 `win_input.py`（ctypes SendInput 双路注入/坐标归一化/提权/F8/截图）；`calibration` 加视口种子与 `detect_grid_rect`；`autofill` 加 `should_abort` 与单刻度滚动；`ui` 校准弹窗改截图识别预览确认；`main` 启动提权。
- TDD：先写失败测试再实现。验证：`python -m pytest -q`（61 passed）、`python -m compileall -q ark_pixel_helper main.py`、Windows 上实例化验证 INPUT/驱动/虚拟桌面/is_admin；**未**在真实游戏中发送点击（需用户管理员下实测）。

## 2026-08-11 — 完成手动裁切与像素细节修复

- 导图改为先打开头像式正方形裁切确认页：可拖动、拖四角缩放、滚轮缩放；取消不改变当前图案，确认后的原图 CropBox 才进入转换管线。
- 裁切器右侧实时显示当前框选、当前取样/细节策略下的最终 24×24 游戏40色预览；默认保留完整40色细节，可选16主色清晰轮廓。
- 验证：`python -m pytest -q`（48 passed）、`python -m compileall -q ark_pixel_helper main.py`、裁切器实时预览烟雾测试通过；未运行真实游戏点击。

## 2026-08-10 — 完成奇象巡展像素拼豆助手

- 新建 Windows 本地 Python 工具：图片量化为明日方舟活动 24×24 固定 40 色图案，支持手工图纸和确认后的 PC 客户端自动绘制。
- 自动化校准绑定游戏窗口句柄与进程 ID，记录顶部/底部色板与滚轮档数；取消、失焦或窗口不匹配时停止后续点击。
- UI 调整为用户确认的夏日活动工坊风，含色号开关和自动绘制进度条。
- 验证：`python -m pytest -q`（31 passed）、`python -m compileall -q ark_pixel_helper main.py`、主界面/校准弹窗烟雾测试通过。

