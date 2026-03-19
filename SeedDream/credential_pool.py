"""
SeedDream/credential_pool.py
════════════════════════════════════════════════════════════════════════
火山方舟多 Key 凭证池 —— 任意异常触发轮换，支持 RPM/TPM 限制感知。
"""
import os
import threading

from dotenv import load_dotenv

load_dotenv()


def _collect_keys() -> list:
    """
    扫描 .env 中所有 DOUBAO_API_KEY* 变量（去重保序，主 key 排首位）。
    变量名递增写法：DOUBAO_API_KEY, DOUBAO_API_KEY_1, DOUBAO_API_KEY_2 ...
    """
    primary = os.getenv("DOUBAO_API_KEY", "").strip()
    seen, result = set(), []
    if primary:
        seen.add(primary)
        result.append(primary)
    for k in sorted(os.environ.keys()):
        if k.upper().startswith("DOUBAO_API_KEY") and k != "DOUBAO_API_KEY":
            v = os.environ[k].strip()
            if v and v not in seen:
                seen.add(v)
                result.append(v)
    return result


class SeedreamCredentialPool:
    """
    火山方舟多 Key 凭证池。

    行为规则：
      - 扫描 .env 中所有 DOUBAO_API_KEY* 变量，主 key 排首位。
      - 任意异常（429 / 403 / 网络错误 / API 报错 ...）均触发 rotate() 轮换。
      - 单个 key 生图超过 max_per_cred 张后，主动提前切换（避免触发平台限流）。
      - 完全线程安全（使用 threading.Lock）。
    """

    def __init__(self, max_per_cred: int = 10):
        self._pool = _collect_keys()
        self._idx  = 0
        self._usage = [0] * len(self._pool)
        self._lock  = threading.Lock()
        self._max   = max_per_cred

        if not self._pool:
            raise ValueError(
                "❌ 未找到任何 DOUBAO_API_KEY，请检查 .env 配置"
            )

    def __len__(self) -> int:
        return len(self._pool)

    # ── 查询 ───────────────────────────────────────────

    def current(self) -> str:
        """返回当前有效的 Key 字符串。"""
        with self._lock:
            return self._pool[self._idx % len(self._pool)]

    def at_limit(self) -> bool:
        """当前 Key 是否已达到单次运行生图上限。"""
        with self._lock:
            return self._usage[self._idx % len(self._pool)] >= self._max

    def summary(self) -> str:
        with self._lock:
            return f"{len(self._pool)} 个 Doubao Key，当前 index={self._idx}"

    # ── 轮换 ───────────────────────────────────────────

    def rotate(self) -> str:
        """
        切换到下一个 Key，返回新 Key 字符串。
        打印切换提示，供外层日志使用。
        """
        with self._lock:
            self._idx = (self._idx + 1) % len(self._pool)
            key = self._pool[self._idx]
            used = self._usage[self._idx]
            tag  = f"Key ...{key[-6:]}"
            print(f"   🔄 [Seedream] 切换凭证 [{self._idx + 1}/{len(self._pool)}] → {tag}  (已用: {used} 张)")
            return key

    # ── 计数 ───────────────────────────────────────────

    def record(self, n: int = 1):
        """记录当前 Key 成功生成了 n 张图。"""
        with self._lock:
            self._usage[self._idx % len(self._pool)] += n
