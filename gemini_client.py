"""
gemini_client.py
可复用的 Gemini 客户端封装 —— 其他模块统一从这里创建客户端和发送消息。
"""
import os
import io
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 0. 凭证池 — 多 Key / 多 Vertex JSON 自动轮换
# ==========================================

def _collect_api_keys() -> list:
    """收集 .env 中所有 GOOGLE_API_KEY* 变量（去重保序，主 key 排首位）。"""
    primary = os.getenv("GOOGLE_API_KEY", "").strip()
    seen, result = set(), []
    if primary:
        seen.add(primary)
        result.append(primary)
    for k in sorted(os.environ.keys()):
        if k.upper().startswith("GOOGLE_API_KEY") and k != "GOOGLE_API_KEY":
            v = os.environ[k].strip()
            if v and v not in seen:
                seen.add(v)
                result.append(v)
    return result


def _collect_vertex_creds(key_dir: str = None) -> list:
    """扫描 key/ 目录下所有 .json 文件，返回绝对路径列表（已排序）。"""
    if key_dir is None:
        key_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key")
    if not os.path.isdir(key_dir):
        return []
    return sorted(
        os.path.abspath(os.path.join(key_dir, f))
        for f in os.listdir(key_dir)
        if f.lower().endswith(".json")
    )


class CredentialPool:
    """
    凭证轮换池。
      for_image=False (文本/对话任务): 仅 API Key
      for_image=True  (图像生成任务): API Key + key/ 目录 Vertex JSON
    超时或限流时调用 rotate() 切换到下一个凭证。
    """

    def __init__(self, use_vertex: bool = True):
        api_keys     = _collect_api_keys()
        vertex_paths = _collect_vertex_creds() if use_vertex else []
        self._pool = (
            [{"type": "api",    "key":  k} for k in api_keys]
            + [{"type": "vertex", "path": p} for p in vertex_paths]
        )
        self._idx   = 0
        self._usage = [0] * len(self._pool)   # 每个凭证已生成图片数（生图专用）
        if not self._pool:
            raise ValueError("❌ 未找到任何 API Key 或 Vertex 凭证，请检查 .env 和 key/ 目录")

    def __len__(self) -> int:
        return len(self._pool)

    def current(self) -> dict:
        return self._pool[self._idx % len(self._pool)]

    def record_image(self, n: int = 1):
        """记录当前凭证成功生成了 n 张图（生图专用）。"""
        self._usage[self._idx % len(self._pool)] += n

    def at_image_limit(self, max_per_cred: int = 10) -> bool:
        """当前凭证是否已达单次运行生图上限。"""
        return self._usage[self._idx % len(self._pool)] >= max_per_cred

    def rotate(self) -> dict:
        """切换到下一个凭证，返回新凭证字典并打印提示。"""
        self._idx = (self._idx + 1) % len(self._pool)
        cred  = self.current()
        used  = self._usage[self._idx % len(self._pool)]
        tag   = (f"API Key ...{cred['key'][-6:]}" if cred["type"] == "api"
                 else f"Vertex [{os.path.basename(cred['path'])}]")
        print(f"   🔄 切换凭证 [{self._idx + 1}/{len(self._pool)}] → {tag}  (已用: {used} 张)")
        return cred

    def make_client(self, cred: dict = None) -> genai.Client:
        """根据凭证字典创建并返回 Gemini 客户端。"""
        if cred is None:
            cred = self.current()
        if cred["type"] == "api":
            os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
            client = genai.Client(api_key=cred["key"], http_options={"timeout": 600000})
            print(f"🔑 [API Key ...{cred['key'][-6:]}]")
            return client
        else:
            # 优先从 JSON 文件本身读取 project_id（service account JSON 自带）
            import json as _json
            try:
                with open(cred["path"], encoding="utf-8") as _f:
                    _sa = _json.load(_f)
                project_id = _sa.get("project_id", "") or os.getenv("GCP_PROJECT_ID", "")
            except Exception:
                project_id = os.getenv("GCP_PROJECT_ID", "")
            location   = os.getenv("GCP_LOCATION", "us-central1")
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred["path"]
            client = genai.Client(
                vertexai=True, project=project_id, location=location,
                http_options={"timeout": 600000},
            )
            print(f"🌐 [Vertex {os.path.basename(cred['path'])} | project={project_id}]")
            return client

    def summary(self) -> str:
        api_n = sum(1 for c in self._pool if c["type"] == "api")
        vtx_n = len(self._pool) - api_n
        return f"{api_n} 个 API Key + {vtx_n} 个 Vertex JSON，共 {len(self._pool)} 个凭证"


# ==========================================
# 1. 客户端创建
# ==========================================

def create_client(use_vertex: bool = None) -> genai.Client:
    """
    根据 .env 配置创建 Gemini 客户端。
    use_vertex=None 时自动读取 .env 中的 USE_VERTEX_AI 开关。
    """
    if use_vertex is None:
        use_vertex = os.getenv("USE_VERTEX_AI", "False").strip().lower() in ("true", "1", "yes")

    if use_vertex:
        project_id = os.getenv("GCP_PROJECT_ID", "")
        location   = os.getenv("GCP_LOCATION", "us-central1")
        cred_path  = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
        if cred_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            http_options={"timeout": 600000}
        )
        print(f"🌐 Gemini 客户端已初始化 [Vertex AI | project={project_id}]")
    else:
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            raise ValueError("❌ 请在 .env 中配置 GOOGLE_API_KEY")
        os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
        client = genai.Client(api_key=api_key, http_options={"timeout": 600000})
        print("🔑 Gemini 客户端已初始化 [API Key 通道]")

    return client


def create_chat(client: genai.Client, model: str, with_search: bool = False):
    """
    创建对话会话。
    model: 完整模型 ID，如 "gemini-2.5-pro"。
    with_search: 是否开启 Google Search 工具。
    """
    tools = [types.Tool(google_search=types.GoogleSearch())] if with_search else []
    config = types.GenerateContentConfig(tools=tools) if tools else None
    if config:
        return client.chats.create(model=model, config=config)
    return client.chats.create(model=model)


# ==========================================
# 2. 带动画 + 重试的消息发送
# ==========================================

def _loading_animation(start_time: float, stop_event: threading.Event):
    """在终端打印持续滚动的等待动画（在线程中运行）。"""
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = 0
    try:
        while not stop_event.is_set():
            elapsed = time.time() - start_time
            print(f"\r{spinner[idx % len(spinner)]} 思考中... {elapsed:.1f}s", end="", flush=True)
            idx += 1
            time.sleep(0.15)
    except Exception:
        pass


def safe_send(chat, message_parts, timeout: int = 120, retries: int = 2,
              pool: "CredentialPool" = None, model: str = None,
              with_search: bool = False):
    """
    安全发送消息到 Gemini，内置：
    - 终端等待动画
    - 超时控制（ThreadPoolExecutor）
    - 网络/SSL 错误自动重试
    - 超时时自动切换 API Key（需传入 pool + model）

    参数:
        chat:          client.chats.create() 返回的 chat 对象
        message_parts: 发送内容（文本字符串 或 types.Part 列表）
        timeout:       单次请求超时秒数
        retries:       超时/网络错误时的最大重试次数
        pool:          CredentialPool 实例；非 None 时超时自动切换 Key 并重建 chat
        model:         模型 ID，配合 pool 使用时重建 chat 需要
        with_search:   是否携带 Google Search 工具，配合 pool 使用

    返回: response 对象 或 None（全部失败时）
    """
    for attempt in range(retries + 1):
        stop_event = threading.Event()
        start_time = time.time()
        anim = threading.Thread(target=_loading_animation, args=(start_time, stop_event), daemon=True)
        anim.start()

        try:
            _exec = ThreadPoolExecutor(max_workers=1)
            try:
                future = _exec.submit(chat.send_message, message_parts)
                response = future.result(timeout=timeout)
            finally:
                _exec.shutdown(wait=False)

            stop_event.set()
            anim.join()
            elapsed = time.time() - start_time
            print(f"\r✅ 完成 ({elapsed:.1f}s)        ")
            return response

        except TimeoutError:
            stop_event.set()
            anim.join()
            print(f"\r⚠️  第 {attempt + 1} 次请求超时 ({timeout}s)")
            if attempt < retries:
                if pool is not None and model is not None:
                    cred = pool.rotate()
                    new_client = pool.make_client(cred)
                    chat = create_chat(new_client, model, with_search)
                    print("   ↳ 已切换凭证，重建会话，自动重试…")
                else:
                    print("   🔄 自动重试...")
            else:
                print("   ❌ 重试耗尽，跳过本次请求")
                return None

        except Exception as e:
            stop_event.set()
            anim.join()
            err_str = str(e)
            retryable_keywords = (
                "SSL", "UNEXPECTED_EOF", "ConnectionReset",
                "RemoteDisconnected", "IncompleteRead", "ConnectionError",
                "UNAVAILABLE", "503",
            )
            is_retryable = any(kw in err_str for kw in retryable_keywords)

            # 429 / RESOURCE_EXHAUSTED 也视为可轮换凭证的重试错误
            if any(kw in err_str.upper() for kw in ["429", "RESOURCE_EXHAUSTED", "QUOTA"]):
                is_retryable = True
            
            # 鉴权错误也触发轮换
            if any(kw in err_str.upper() for kw in ["401", "403", "API_KEY_INVALID", "PERMISSION_DENIED"]):
                is_retryable = True

            if is_retryable and attempt < retries:
                if pool is not None and model is not None:
                    cred = pool.rotate()
                    new_client = pool.make_client(cred)
                    chat = create_chat(new_client, model, with_search)
                    print(f"   ↳ 已切换凭证，自动重试…")
                else:
                    wait = 30 * (attempt + 1)
                    print(f"\r⚠️  请求受限(429)或服务暂时不可用，{wait}s 后重试 (第{attempt+1}/{retries}次)…")
                    time.sleep(wait)
            else:
                print(f"\r❌ API 请求失败: {e}")
                return None

    return None


# ==========================================
# 3. 图片工具
# ==========================================

def compress_image(path: str, max_side: int = 900, quality: int = 72) -> tuple[bytes, str]:
    """
    将图片压缩到 max_side px 并转为 JPEG，返回 (bytes, mime_type)。
    只在内存中处理，不修改原文件。
    """
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:
            ratio = max_side / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        with open(path, "rb") as f:
            return f.read(), _guess_mime(path)


def _guess_mime(path: str) -> str:
    import mimetypes
    mime, _ = mimetypes.guess_type(path)
    return mime or "image/png"


# ==========================================
# 4. 模型选择
# ==========================================

# ── 文本/对话模型 ──
TEXT_MODELS = {
    "1": "gemini-3.1-pro-preview",   # 默认：最新旗舰，推理能力强
    "2": "gemini-2.5-pro",           # 备选：稳定版 pro
}
DEFAULT_TEXT_MODEL = "gemini-3.1-pro-preview"

# ── 图像生成模型 ──
IMAGE_MODELS = {
    "1": "gemini-3.1-flash-image-preview",  # 默认：速度快，成本低
    "2": "gemini-3-pro-image-preview",       # 备选：质量更高
}
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image-preview"

# 向后兼容：保留 MODELS 引用
MODELS = TEXT_MODELS
DEFAULT_MODEL = DEFAULT_TEXT_MODEL


def select_model(
    prompt_text: str = "请选择对话/文本模型 (默认1 - 3.1-pro-preview): ",
    models: dict = None,
    default: str = None,
) -> str:
    from ui_utils import timed_choose
    if models is None:
        models = TEXT_MODELS
    if default is None:
        default = DEFAULT_TEXT_MODEL

    options = list(models.values())
    default_idx = next((i + 1 for i, v in enumerate(options) if v == default), 1)

    print("\n--- 🧠 选择文本模型 ---")
    for i, (key, name) in enumerate(models.items(), 1):
        default_mark = " (默认)" if name == default else ""
        print(f"  [{i}] {name}{default_mark}")
    idx = timed_choose(prompt_text, options, default=default_idx)
    selected = options[idx - 1] if 1 <= idx <= len(options) else default
    print(f"   ✅ 已选择: {selected}")
    return selected


def select_image_model(
    prompt_text: str = "请选择生图模型 (默认1 - flash): ",
) -> str:
    from ui_utils import timed_choose
    options = list(IMAGE_MODELS.values())
    default_idx = next((i + 1 for i, v in enumerate(options) if v == DEFAULT_IMAGE_MODEL), 1)

    print("\n--- 🎨 选择生图模型 ---")
    for i, (key, name) in enumerate(IMAGE_MODELS.items(), 1):
        default_mark = " (默认)" if name == DEFAULT_IMAGE_MODEL else ""
        print(f"  [{i}] {name}{default_mark}")
    idx = timed_choose(prompt_text, options, default=default_idx)
    selected = options[idx - 1] if 1 <= idx <= len(options) else DEFAULT_IMAGE_MODEL
    print(f"   ✅ 已选择: {selected}")
    return selected
