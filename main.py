"""奇象巡展像素拼豆助手入口。"""

import sys

from ark_pixel_helper.ui import run
from ark_pixel_helper.win_input import elevate_and_exit, is_admin, should_elevate

_ELEVATED_MARKER = "--elevated"


if __name__ == "__main__":
    # 自动填色需要管理员权限（否则合成鼠标输入会被游戏/UIPI 拦截）。
    # 启动时检测；非管理员则请求提权并重启，只尝试一次以防 UAC 拒绝后死循环。
    if should_elevate(is_admin(), _ELEVATED_MARKER in sys.argv):
        elevate_and_exit(marker=_ELEVATED_MARKER)
    run()
