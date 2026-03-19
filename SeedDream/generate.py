"""
SeedDream/generate.py
════════════════════════════════════════════════════════════════════════
对外统一生图入口。

特性：
  - 交互式模型选择（默认 4.5，可选 5.0 / 4.0）
  - 超量错误（429）触发模型降级：4.5 → 4.0 → 5.0
  - 任意异常触发 Key 轮换（凭证池）
  - 终端等待动画（spinner + 计时）
"""
import os
import sys
import time
import base64
import mimetypes
import threading
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

from .client import SeedreamClient

# ── 模型配置 ──────────────────────────────────────────────
MODELS = {
    "4.5": SeedreamClient.MODEL_4_5,
    "5.0": SeedreamClient.MODEL_5_0,
    "4.0": SeedreamClient.MODEL_4_0,
}
DEFAULT_MODEL_KEY = "4.5"

# 超量时的模型降级链：4.5 → 4.0 → 5.0 → 无
MODEL_FALLBACK = {
    SeedreamClient.MODEL_4_5: SeedreamClient.MODEL_4_0,
    SeedreamClient.MODEL_4_0: SeedreamClient.MODEL_5_0,
    SeedreamClient.MODEL_5_0: None,
}

# ── 凭证池（懒加载，进程级单例）─────────────────────────────
_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        from .credential_pool import SeedreamCredentialPool
        _pool = SeedreamCredentialPool(max_per_cred=10)
        print(f"🎰 Seedream 凭证池已初始化: {_pool.summary()}")
    return _pool


# ── 模型选择 ──────────────────────────────────────────────

def select_model() -> str:
    """
    交互式选择 Seedream 生图模型，10秒无操作默认选 4.5。
    返回完整模型 endpoint 字符串。
    """
    from ui_utils import timed_choose
    options = list(MODELS.values())
    default_idx = list(MODELS.keys()).index(DEFAULT_MODEL_KEY) + 1

    print("\n--- 🎨 选择 Seedream 生图模型 ---")
    for i, (k, v) in enumerate(MODELS.items(), 1):
        mark = " (默认)" if k == DEFAULT_MODEL_KEY else ""
        print(f"  [{i}] {v}  [{k}]{mark}")
    idx = timed_choose(
        f"请选择模型 (默认{default_idx} - {DEFAULT_MODEL_KEY}): ",
        options,
        default=default_idx,
    )
    selected = options[idx - 1] if 1 <= idx <= len(options) else MODELS[DEFAULT_MODEL_KEY]
    print(f"   ✅ 已选择: {selected}")
    return selected


# ── 等待动画 ──────────────────────────────────────────────

def _show_spinner(stop_event: threading.Event):
    """终端 spinner + 计时（在独立线程中运行）。"""
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    start = time.time()
    idx = 0
    try:
        while not stop_event.is_set():
            elapsed = time.time() - start
            print(f"\r{spinner[idx % len(spinner)]} Seedream 生成中... {elapsed:.1f}s",
                  end="", flush=True)
            idx += 1
            time.sleep(0.15)
    except Exception:
        pass


# ── 参考图预处理 ──────────────────────────────────────────

def _paths_to_base64(image_paths) -> List[str]:
    """将本地图片路径列表转为 Base64 字符串列表（统一 JPEG 编码）。"""
    result = []
    for path in image_paths:
        if not path or not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            raw = f.read()
        try:
            import io as _io
            from PIL import Image
            img = Image.open(_io.BytesIO(raw)).convert("RGB")
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            result.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        except Exception:
            result.append(base64.b64encode(raw).decode("ascii"))
    return result


# ── 核心生图函数 ──────────────────────────────────────────

def generate(
    prompt: str,
    image_paths: Optional[List[str]] = None,
    num_images: int = 1,
    seed: Optional[int] = None,
    model: Optional[str] = None,
    output_dir: str = "generated_images",
    file_prefix: Optional[str] = None,
) -> List[str]:
    """
    使用火山方舟 Seedream 生成图片。

    轮换策略：
      - 任意异常 → 立即轮换 Key（凭证池）
      - 超量错误（429）→ 额外触发模型降级：4.5 → 4.0 → 5.0

    参数:
        prompt:       生图提示词
        image_paths:  参考图本地路径列表；None / 空 = 文生图
        num_images:   生成数量
        seed:         兼容接口（暂不支持）
        model:        模型 endpoint；None 时读 .env SEEDREAM_MODEL，再兜底 4.5
        output_dir:   图片输出目录
        file_prefix:  文件名前缀
    """
    os.makedirs(output_dir, exist_ok=True)
    model_id = (
        model
        or os.getenv("SEEDREAM_MODEL", "").strip()
        or MODELS[DEFAULT_MODEL_KEY]
    )
    pool = _get_pool()
    saved = []

    print(f"🚀 [Seedream] 模型: {model_id} | 参考图: {len(image_paths or [])} 张 | 生成: {num_images} 张")

    b64_images = _paths_to_base64(image_paths or [])
    has_ref = bool(b64_images)

    for i in range(num_images):
        # 主动检查：当前 Key 是否达到生图上限
        if pool.at_limit():
            print(f"\n📊 当前 Key 已达 10 张上限，主动切换…")
            pool.rotate()

        print(f"\n🎨 正在生成第 {i+1}/{num_images} 张... (模型: {model_id})")

        # 启动 spinner
        stop_event = threading.Event()
        spinner_thread = threading.Thread(
            target=_show_spinner, args=(stop_event,), daemon=True
        )
        spinner_thread.start()
        start_time = time.time()

        try:
            client = SeedreamClient(api_key=pool.current())

            if has_ref:
                if len(b64_images) == 1:
                    paths = client.image_to_single_image(
                        prompt          = prompt,
                        reference_image = b64_images[0],
                        model_endpoint  = model_id,
                    )
                else:
                    paths = client.multi_images_to_single_image(
                        prompt           = prompt,
                        reference_images = b64_images,
                        model_endpoint   = model_id,
                    )
            else:
                paths = client.text_to_single_image(
                    prompt         = prompt,
                    model_endpoint = model_id,
                )

            stop_event.set()
            spinner_thread.join()
            elapsed = time.time() - start_time
            print(f"\r✅ 完成 ({elapsed:.1f}s)        ")

            if paths:
                for p in paths:
                    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
                    seed_str = f"seed{seed}" if seed is not None else "rnd"
                    prefix   = file_prefix or "seedream"
                    ext      = os.path.splitext(p)[1] or ".jpeg"
                    new_name = f"{prefix}_{ts}_{seed_str}_{i+1}{ext}"
                    new_path = os.path.join(output_dir, new_name)
                    if os.path.abspath(p) != os.path.abspath(new_path):
                        import shutil
                        shutil.move(p, new_path)
                    saved.append(new_path)
                    pool.record()
                print(f"   💾 已保存: {os.path.basename(new_path)}")
            else:
                print("   ⚠️  未返回任何图片数据")

        except Exception as e:
            stop_event.set()
            spinner_thread.join()
            err_str = str(e)
            is_quota = any(
                kw in err_str.upper()
                for kw in ["429", "QUOTA", "RATE_LIMIT", "RESOURCE_EXHAUSTED"]
            )
            print(f"\r   ⚠️  Seedream 请求失败: {err_str[:120]}")

            # Key 轮换（任意异常）
            pool.rotate()

            # 模型降级（仅超量错误）
            if is_quota:
                fallback = MODEL_FALLBACK.get(model_id)
                if fallback:
                    print(f"   📉 超量，模型降级: {model_id} → {fallback}")
                    model_id = fallback
                else:
                    print(f"   ⚠️  已是最后备用模型 ({model_id})，无法继续降级")

    print(f"\n💾 本次共保存 {len(saved)} 张到: {output_dir}")
    return saved


# 兼容别名
generate_my_image = generate
