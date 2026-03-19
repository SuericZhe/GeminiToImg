import os
import time
import sys
import threading
import mimetypes
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. 基础配置映射 & 全局环境变量加载
# ---------------------------------------------------------
# 加载 .env 文件中的所有配置
load_dotenv()

# 自动配置代理 (如果 .env 中有设置，保障网络连通性)
http_proxy = os.getenv("HTTP_PROXY")
https_proxy = os.getenv("HTTPS_PROXY")
if http_proxy: os.environ["HTTP_PROXY"] = http_proxy
if https_proxy: os.environ["HTTPS_PROXY"] = https_proxy

MODELS = {
    "banana2": "gemini-3.1-flash-image-preview",
    "pro": "gemini-3-pro-image-preview",
    "banana": "gemini-2.5-flash-image"
}

# ==========================================
# 生图凭证池 (API Key + Vertex JSON，懒加载)
# 文本任务不使用此池，图像任务统一用此池
# ==========================================
_img_pool = None

def _get_img_pool():
    """懒加载生图凭证池（API Key + Vertex JSON 联合池）。"""
    global _img_pool
    if _img_pool is None:
        from gemini_client import CredentialPool
        _img_pool = CredentialPool(for_image=True)
        print(f"🎰 生图凭证池已初始化: {_img_pool.summary()}")
    return _img_pool

def show_runtime(stop_event):
    """动态计时器"""
    start_time = time.time()
    try:
        while not stop_event.is_set():
            elapsed = time.time() - start_time
            sys.stdout.write(f"\r⏳ 处理中... 当前任务已等待: {elapsed:.1f}s")
            sys.stdout.flush()
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

def _compress_if_large(path, max_mb=2):
    """若图片超过 max_mb MB，压缩为 JPEG 后覆盖保存，返回最终路径。"""
    if not os.path.exists(path) or os.path.getsize(path) <= max_mb * 1024 * 1024:
        return path
    try:
        from PIL import Image
        import io
        img = Image.open(path).convert("RGB")
        jpg_path = os.path.splitext(path)[0] + ".jpg"
        for quality in range(85, 25, -10):
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= max_mb * 1024 * 1024:
                with open(jpg_path, "wb") as f:
                    f.write(buf.getvalue())
                if path != jpg_path:
                    os.remove(path)
                print(f"   📦 压缩至 {buf.tell()//1024}KB (JPEG q={quality})")
                return jpg_path
    except Exception:
        pass
    return path


def generate_my_image(prompt, model_alias="banana2", image_paths=None, num_images=1, seed=None, use_vertex=False, output_dir="generated_images", file_prefix=None):
    """
    终极融合版：完全由 .env 驱动的生成核心
    生图任务统一使用 API Key + Vertex JSON 联合凭证池，超时自动切换。
    use_vertex 参数保留向后兼容，但不影响凭证池行为。
    """
    model_id = MODELS.get(model_alias, model_alias)

    # ==========================================
    # [核心] 使用联合凭证池创建首个客户端
    # 规则: 图像任务 = API + Vertex 联合池；自动轮换
    # ==========================================
    pool   = _get_img_pool()
    client = pool.make_client()

    # ==========================================
    # 资源预加载与模式判定
    # ==========================================
    os.makedirs(output_dir, exist_ok=True)
    saved_paths = []

    paths = []
    if isinstance(image_paths, str): paths = [image_paths]
    elif isinstance(image_paths, list): paths = image_paths

    contents_to_send = []
    valid_paths = []
    
    for path in paths:
        if path and os.path.exists(path):
            mime_type, _ = mimetypes.guess_type(path)
            mime_type = mime_type or "image/png"
            with open(path, "rb") as f:
                img_data = f.read()
            contents_to_send.append(types.Part.from_bytes(data=img_data, mime_type=mime_type))
            valid_paths.append(path)
    
    contents_to_send.append(types.Part.from_text(text=prompt))

    mode = "txt2img" if not valid_paths else ("img2img" if len(valid_paths) == 1 else "multi_img2img")
    print(f"🚀 [{mode}] 正在调用模型: {model_id} | 图片数: {len(valid_paths)}")
    
    # ==========================================
    # 执行生成与结果解析
    # ==========================================
    # 重试 & 超时配置
    MAX_RETRIES      = 4
    REQUEST_INTERVAL = 12     # 每张图之间的固定间隔（秒）
    GEN_TIMEOUT      = 180    # 单次生成超时（秒）
    IMAGE_PER_CRED   = 10     # 每个凭证单次运行最多生成图片数

    try:
        for i in range(num_images):

            # ── 主动检查：当前凭证是否已达 10 张上限 ──
            if pool.at_image_limit(IMAGE_PER_CRED):
                print(f"\n📊 当前凭证已达 {IMAGE_PER_CRED} 张上限，主动切换下一个凭证…")
                cred   = pool.rotate()
                client = pool.make_client(cred)

            print(f"\n🎨 正在生成第 {i+1}/{num_images} 张...")

            if i > 0:
                for _ in range(REQUEST_INTERVAL * 10):
                    time.sleep(0.1)

            for attempt in range(MAX_RETRIES + 1):
                stop_event = threading.Event()
                timer_thread = threading.Thread(target=show_runtime, args=(stop_event,), daemon=True)
                overall_start = time.time()

                try:
                    timer_thread.start()

                    config = types.GenerateContentConfig(
                        candidate_count=1,
                        seed=seed if seed is not None else None,
                        response_modalities=[types.Modality.IMAGE]
                    )

                    _exec = ThreadPoolExecutor(max_workers=1)
                    try:
                        _fut = _exec.submit(
                            client.models.generate_content,
                            model=model_id,
                            contents=contents_to_send,
                            config=config
                        )
                        response = _fut.result(timeout=GEN_TIMEOUT)
                    finally:
                        _exec.shutdown(wait=False)

                    stop_event.set()
                    timer_thread.join()

                    duration = time.time() - overall_start
                    image_saved = False

                    if response.candidates and response.candidates[0].content.parts:
                        for part in response.candidates[0].content.parts:
                            raw_data = None
                            if hasattr(part, 'inline_data') and part.inline_data: raw_data = part.inline_data.data
                            elif hasattr(part, 'data'): raw_data = part.data

                            if raw_data:
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                ch = pool.current()["type"]
                                seed_str = f"seed{seed}" if seed is not None else "rnd"
                                name_prefix = file_prefix if file_prefix else f"{mode}_{ch}_{model_alias}"
                                file_name = f"{name_prefix}_{timestamp}_{seed_str}_{i+1}.jpg"
                                full_path = os.path.join(output_dir, file_name)

                                # 统一转为 JPEG 保存
                                try:
                                    from PIL import Image as _PIL_Image
                                    import io as _io
                                    img_obj = _PIL_Image.open(_io.BytesIO(raw_data)).convert("RGB")
                                    img_obj.save(full_path, format="JPEG", quality=90)
                                except Exception:
                                    # PIL 不可用时直接写原始数据（保留扩展名 .jpg 作标识）
                                    with open(full_path, "wb") as f:
                                        f.write(raw_data)

                                full_path = _compress_if_large(full_path, max_mb=2)
                                saved_paths.append(full_path)
                                pool.record_image()   # ← 记录本凭证成功生成一张
                                print(f"\n✅ 保存成功: {full_path} (耗时 {duration:.1f}s)")
                                image_saved = True
                                break

                    if not image_saved:
                        print(f"\n⚠️ 未获取到图片数据。原因: {response.candidates[0].finish_reason if response.candidates else '未知'}")
                    break  # 成功或无数据，跳出重试循环

                except (FuturesTimeoutError, TimeoutError):
                    stop_event.set()
                    if timer_thread.is_alive(): timer_thread.join()
                    if attempt < MAX_RETRIES:
                        print(f"\n⏳ 生成超时（>{GEN_TIMEOUT}s），切换凭证重试 ({attempt+1}/{MAX_RETRIES})…")
                        cred   = pool.rotate()
                        client = pool.make_client(cred)
                    else:
                        print(f"\n❌ 已耗尽所有凭证重试次数，跳过本张")
                        break

                except Exception as e:
                    stop_event.set()
                    if timer_thread.is_alive(): timer_thread.join()
                    if attempt < MAX_RETRIES:
                        # 任何错误（429/限流/SSL/服务不可用/认证失败等）统一切换凭证
                        # 若只有一个凭证且是 429，加等待避免立刻再被限流
                        err_str = str(e)
                        print(f"\n⚠️ 请求失败: {err_str[:120]}")
                        cred   = pool.rotate()
                        client = pool.make_client(cred)
                        if "429" in err_str and len(pool) == 1:
                            wait = 30 * (attempt + 1)
                            print(f"   只有一个凭证，等待 {wait}s 后重试…")
                            for _ in range(wait * 10):
                                time.sleep(0.1)
                    else:
                        print(f"\n❌ 已耗尽所有凭证重试次数，跳过本张: {e}")
                        break

    except KeyboardInterrupt:
        print(f"\n\n🛑 程序已由用户强制停止 (Ctrl+C)。")
        sys.exit(0)

    return saved_paths

if __name__ == "__main__":
    # ==========================================
    # 🌟 极简业务调用层
    # ==========================================
    
    # [核心改动] 从 .env 动态读取开关，并将字符串转换为真正的布尔值 True/False
    # 这样你以后切通道，连这行代码都不用碰，直接去改 .env 文件保存即可生效
    ENV_USE_VERTEX = os.getenv("USE_VERTEX_AI", "False").strip().lower() in ("true", "1", "yes")
    
    # 1. 生成数量
    COUNT = 1

    # 2. 提示词 (文生图或图生图指令)
    PRODUCT_DETAIL = "这是铝箔盒封口机，根据这个机器的特点进行重新设计，全英，不要水印，能作为亚马逊电商主图，极致细节，比例1:1"
    
    # 3. 风格追加词 (不需要则留空 "")
    STYLE_PROMPT = "" 

    # 4. 图片参数 (纯文生图请设为 [] 和 None)
    MY_MACHINES = ["local_images/功能2.png"] 
    STYLE_REF = None 

    # --- 组装与调用 ---
    all_imgs = (MY_MACHINES if MY_MACHINES else []) + ([STYLE_REF] if STYLE_REF else [])
    final_prompt = f"{PRODUCT_DETAIL} {STYLE_PROMPT}".strip()

    generate_my_image(
        prompt=final_prompt, 
        model_alias="pro",           # 调用 pro 模型
        image_paths=all_imgs, 
        num_images=COUNT,
        seed=None,                   
        use_vertex=ENV_USE_VERTEX    # 将 .env 解析出的布尔值传给核心函数
    )