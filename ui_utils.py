"""
ui_utils.py
═══════════════════════════════════════════════════════════════
终端交互工具 — 带倒计时的菜单选择与确认。

提供两个函数：
  timed_choose(prompt, options, default, timeout)
      显示数字菜单，timeout 秒内无操作自动选择 default。
      每秒在同一行更新倒计时，不跳行。
      返回所选序号（从 1 开始）。

  timed_confirm(prompt, timeout, default)
      显示 y/n 确认，timeout 秒内无操作自动选择 default。
      每秒在同一行更新倒计时，不跳行。
      返回 "y" 或 "n"。
═══════════════════════════════════════════════════════════════
"""
import sys
import time
import threading
import msvcrt


DEFAULT_TIMEOUT = 10


def timed_choose(
    prompt: str,
    options: list,
    default: int = 1,
    timeout: int = DEFAULT_TIMEOUT,
) -> int:
    """
    显示编号菜单，timeout 秒内无操作自动选择 default。
    每秒覆盖同一行更新倒计时（不跳行）。
    允许输入 0（若调用方有"创建新产品"等特殊选项）。

    返回: 所选序号（int，1-based；特殊情况可为 0）
    """
    buf      = ""
    deadline = time.time() + timeout
    last_sec = -1

    # 把 prompt 里的前导换行先单独输出，确保倒计时始终在同一行刷新
    prompt = prompt.lstrip("\n")
    sys.stdout.write("\n")
    sys.stdout.flush()

    while True:
        remaining = max(0.0, deadline - time.time())
        cur_sec   = int(remaining)

        if cur_sec != last_sec:
            sys.stdout.write(f"\r{prompt}[{cur_sec}s] {buf} ")
            sys.stdout.flush()
            last_sec = cur_sec

        if remaining <= 0:
            sys.stdout.write(f"\r{prompt}超时，自动选择 [{default}]              \n")
            sys.stdout.flush()
            return default

        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ('\r', '\n'):                  # 回车确认
                sys.stdout.write("\n")
                sys.stdout.flush()
                val = buf.strip()
                if val.isdigit():
                    n = int(val)
                    if 0 <= n <= len(options):
                        return n
                return default
            elif ch == '\x03':                      # Ctrl+C
                raise KeyboardInterrupt
            elif ch == '\x08':                      # Backspace
                buf = buf[:-1]
                # 立即刷新显示
                sys.stdout.write(f"\r{prompt}[{cur_sec}s] {buf}  ")
                sys.stdout.flush()
            elif ch.isprintable():
                buf += ch
                sys.stdout.write(f"\r{prompt}[{cur_sec}s] {buf} ")
                sys.stdout.flush()

        time.sleep(0.05)


def timed_confirm(
    prompt: str,
    timeout: int = DEFAULT_TIMEOUT,
    default: str = "y",
) -> str:
    """
    显示 y/n 确认提示，timeout 秒内无操作自动选择 default。
    每秒覆盖同一行更新倒计时（不跳行）。

    返回: "y" 或 "n"
    """
    result = [None]
    done   = threading.Event()

    # 把 prompt 里的前导换行先单独输出
    prompt = prompt.lstrip("\n")
    sys.stdout.write("\n")
    sys.stdout.flush()

    def _reader():
        try:
            result[0] = sys.stdin.readline().strip().lower()
        except Exception:
            pass
        done.set()

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    for remaining in range(timeout, 0, -1):
        sys.stdout.write(f"\r{prompt}[{remaining}s 后自动选择 {default}] ")
        sys.stdout.flush()
        if done.wait(1.0):
            val = result[0] or ""
            sys.stdout.write("\n")
            sys.stdout.flush()
            return val if val in ("y", "n") else default

    sys.stdout.write(f"\r{prompt}-> 自动: {default}                        \n")
    sys.stdout.flush()
    return default
