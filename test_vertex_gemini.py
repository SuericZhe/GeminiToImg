import os
import sys
import re
import json
import time
import threading
import itertools
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from google import genai
from google.genai import types
import kb_manager
import product_manager
from dotenv import load_dotenv

load_dotenv()

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
LOCATION = "global"

AVAILABLE_MODELS = {
    "1": "gemini-2.5-flash",
    "2": "gemini-2.5-pro",
    "3": "gemini-2.0-flash-exp",
}

done_thinking = False

# ==========================================
# SOP 资产加载
# ==========================================
def load_sop_assets():
    """启动时加载标题库和关键词组，失败时给空字符串"""
    title_lib = ""
    keywords = ""
    try:
        with open("assets/title_library.txt", "r", encoding="utf-8") as f:
            title_lib = f.read()
    except FileNotFoundError:
        print("⚠️  assets/title_library.txt 不存在，标题库为空")
    try:
        with open("assets/keywords_food_machine.txt", "r", encoding="utf-8") as f:
            keywords = f.read()
    except FileNotFoundError:
        print("⚠️  assets/keywords_food_machine.txt 不存在，关键词库为空")
    return title_lib, keywords


# ==========================================
# Prompt 构造
# ==========================================
def build_analysis_prompt(title_library, keywords):
    """构造产品分析首次提示词（结构化 JSON 输出）"""
    return f"""You are an experienced Alibaba International (alibaba.com) store operator \
specializing in food machinery export. You have deep expertise in B2B export marketing, \
international buyer psychology, and Alibaba search SEO optimization.

I will provide you with:
1. A PDF file — 1688.com product listing (in Chinese). It contains product images embedded.
2. Several product reference photos.
3. A title reference library — raw titles scraped from top-performing Alibaba listings \
(one title per line, no categories). Study their style, keyword density, and structure.
4. A keyword list — raw keywords scraped from the same category (one per line). \
Select and embed the most relevant ones naturally into titles.

---
[TITLE REFERENCE LIBRARY]
{title_library}

---
[KEYWORD LIST]
{keywords}

---

## STEP 1 — Discover 5 unique listing angles from the product itself

Read the PDF and photos carefully. Based on what THIS product actually is, identify 5 \
distinct buyer angles that would each appeal to a different type of international buyer \
or use scenario. Do NOT use preset angles — derive them from the product's real features, \
certifications, use cases, and target industries.

For each angle, generate one complete product listing in Amazon-style:

TITLE rules:
- Exactly 100-108 English characters (count every character including spaces)
- Keywords from the list embedded naturally — never stuffed
- Learn rhythm and structure from the reference library titles

SELLING POINTS rules (Amazon bullet-point style):
- Exactly 5 bullet points per listing
- Each bullet: ALL-CAPS short label (3-6 words) + colon + detailed benefit sentence
- Format: "LABEL: Detailed explanation of the benefit, how it works, and why it matters \
to the buyer. Include specific numbers/specs where possible."
- Each bullet 150-220 characters total
- Focus on buyer benefits, not just features
- Example style:
  "AUTO HEIGHT DETECTION: No manual adjustments needed. The built-in sensor automatically \
detects cup height, ensuring perfect alignment and sealing every time."

## STEP 2 — Deep feature extraction with PDF image mapping

Analyze every visual and textual feature in the PDF and photos. For each distinct \
product feature, identify which image(s) in the PDF best illustrate it \
(use rough descriptions like "the image showing the control panel" or \
"the close-up of the sealing head" — you cannot export PDF images directly, \
but describe them so we can match them to the reference photos provided).

## OUTPUT FORMAT

Return ONLY valid JSON, no markdown fences, no extra text:

{{
  "product_name_en": "English product name (3-6 words, professional)",
  "product_name_cn": "中文产品名",
  "listings": [
    {{
      "id": 1,
      "angle": "short angle label derived from product analysis",
      "angle_rationale": "1-sentence explanation of why this angle matters for this product",
      "title": "100-108 char title with keywords naturally embedded",
      "selling_points": [
        "LABEL ONE: Detailed benefit sentence with specific value to buyer, 150-220 chars total.",
        "LABEL TWO: ...",
        "LABEL THREE: ...",
        "LABEL FOUR: ...",
        "LABEL FIVE: ..."
      ],
      "scenario_tag": "describe the buyer type or use environment, e.g. milk-tea-shop"
    }}
  ],
  "features": [
    {{
      "id": "F1",
      "cn": "中文特点描述（简短）",
      "en": "English feature description (concise)",
      "category": "function | material | spec | certification | usage",
      "image_value": "high | medium | low",
      "pdf_image_hint": "describe which image in the PDF best shows this feature, \
e.g. 'the diagram showing the dual-temperature control panel on page 3'"
    }}
  ]
}}

STRICT RULES:
- listings: exactly 5 items, each angle must be genuinely different and product-specific
- title: count characters precisely — must be 100-108
- selling_points: exactly 5 per listing, ALL-CAPS label format required
- features: list ALL distinct features, not just obvious ones
- image_value: high = visually compelling for image generation, medium = partial, low = text-only
- pdf_image_hint: required for every feature with image_value=high or medium
- Output ONLY the JSON object, nothing else
"""


def build_image_prompts_prompt(product_name):
    """根据已保存的特点+pdf_image_hint，构造25个图片Prompt生成指令"""
    data = product_manager.load_product(product_name)
    if not data:
        return None, None

    # 所有高/中价值特点，附带PDF图片线索
    visual_features = [
        f for f in data.get("features", [])
        if f.get("image_value") in ("high", "medium")
    ]
    features_text = "\n".join(
        f"- [F{f['id']} | {f['category'].upper()} | {f['image_value']}] EN: {f['en']}\n"
        f"  PDF image hint: {f.get('pdf_image_hint', 'N/A')}"
        for f in visual_features
    )

    listings_text = "\n".join(
        f"Listing {l['id']}: angle=\"{l['angle']}\" scenario=\"{l['scenario_tag']}\"\n"
        f"  Title: {l['title']}\n"
        f"  Key selling points summary: {l['selling_points'][0][:80]}..."
        for l in data.get("listings", [])
    )

    ref_images = product_manager.get_ref_images(product_name)
    ref_hint = (
        f"Reference photos available: {len(ref_images)} image(s) — "
        f"{', '.join(os.path.basename(r) for r in ref_images)}"
        if ref_images else "No reference photos available — use text-only prompts."
    )

    prompt = f"""You are a professional product photography art director and AI image \
prompt engineer, specializing in B2B e-commerce product visuals for Alibaba International.

Product: {data.get('product_name_en', '')}
{ref_hint}

## Visual features extracted from the product PDF:
{features_text}

## 5 Listing angles to generate images for:
{listings_text}

## Your task

Generate exactly 25 image generation prompts: 5 listings × 5 image types.

IMAGE TYPE DEFINITIONS:
1. scene — Product in a realistic commercial environment. Show it in active use. \
   Match the listing's scenario_tag (e.g. milk-tea-shop → busy drink counter). \
   Include people interacting with the machine. Photorealistic, 8K, commercial photography.

2. detail — Extreme macro close-up of the single most impressive physical feature \
   for that listing angle (e.g. for material angle → 304 stainless steel surface texture; \
   for automation angle → sensor/control panel). Use the pdf_image_hint to identify \
   which part to focus on. Studio lighting, white or gradient background, 8K.

3. real — Authentic "factory floor" or "kitchen back-of-house" feel. Natural lighting, \
   slightly imperfect environment (real space, not CGI studio). Product is the hero. \
   Similar style to the reference photos provided. Photorealistic, 8K.

4. spec — Technical product diagram. Pure white background. The machine shown from \
   the most informative angle (usually 3/4 front view). English dimension/spec labels \
   as arrows pointing to key parts. Clean, professional, blueprint-inspired. \
   NO Chinese text. 8K.

5. packaging — Professional export packaging presentation. Wooden crate or heavy-duty \
   carton, foam padding visible, machine partially shown inside. Add packing list label \
   and "FRAGILE" sticker. Warehouse or logistics dock background. 8K.

PROMPT WRITING RULES:
- Every prompt must be self-contained (include product name, key visual elements, \
  lighting, background, camera angle, quality suffix)
- For detail and real types: reference the pdf_image_hint to ensure the correct \
  product part is focused on
- Each of the 25 prompts must be visually distinct — vary camera angle, environment \
  details, lighting setup, and featured product attribute across listings
- Quality suffix for all: ", photorealistic, ultra-detailed, 8K resolution, \
  no watermark, no Chinese text, no logos"
- spec type suffix: ", white background, English annotation labels, \
  technical product diagram, professional, 8K, no watermark"

Return ONLY valid JSON, no markdown, no extra text:
{{
  "product_name_en": "{data.get('product_name_en', '')}",
  "image_prompts": [
    {{
      "listing_id": 1,
      "angle": "...",
      "scenario_tag": "...",
      "scene":      "full prompt text...",
      "detail":     "full prompt text...",
      "real":       "full prompt text...",
      "spec":       "full prompt text...",
      "packaging":  "full prompt text..."
    }}
  ]
}}

Generate all 5 listing entries (listing_id 1-5). No placeholders.
"""
    return prompt, data


# ==========================================
# 工具函数
# ==========================================
def get_mime_type(file_path):
    ext = file_path.lower().split('.')[-1]
    if ext in ['jpg', 'jpeg']: return "image/jpeg"
    if ext == 'png': return "image/png"
    if ext == 'pdf': return "application/pdf"
    return "application/octet-stream"


def scan_target_folder(folder_path, processed_files_set):
    parts = []
    image_paths = []
    if not folder_path or not os.path.exists(folder_path):
        return parts, image_paths
    for file_name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file_name)
        if os.path.isfile(file_path) and file_path not in processed_files_set:
            try:
                mime_type = get_mime_type(file_path)
                with open(file_path, "rb") as f:
                    parts.append(types.Part.from_bytes(data=f.read(), mime_type=mime_type))
                if mime_type.startswith("image/"):
                    image_paths.append(file_path)
                processed_files_set.add(file_path)
                print(f"📦 已自动捕获新文件: {file_name}")
            except Exception as e:
                print(f"❌ 读取文件 {file_name} 失败: {e}")
    return parts, image_paths


def loading_animation():
    spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
    while not done_thinking:
        sys.stdout.write(f'\r⏳ 思考中 {next(spinner)} ')
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write('\r\033[K')


def safe_send_message(chat, message_parts, timeout=120, retries=1):
    global done_thinking
    for attempt in range(retries + 1):
        done_thinking = False
        anim_thread = threading.Thread(target=loading_animation)
        anim_thread.start()
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(chat.send_message, message_parts)
                response = future.result(timeout=timeout)
            done_thinking = True
            anim_thread.join()
            return response
        except TimeoutError:
            done_thinking = True
            anim_thread.join()
            print(f"\n⚠️ 第 {attempt + 1} 次请求超时 ({timeout}s)！")
            if attempt < retries:
                print("🔄 正在自动重试...")
            else:
                print("❌ 重试失败，请检查网络。")
                return None
        except Exception as e:
            done_thinking = True
            anim_thread.join()
            print(f"\n❌ API 请求发生错误: {e}")
            return None


def extract_json(text):
    """从 Gemini 回复中提取 JSON（处理可能的 markdown 包裹）"""
    # 去掉 ```json ... ``` 包裹
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    # 找第一个 { 到最后一个 }
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end+1])
    except json.JSONDecodeError:
        return None


def print_help():
    print("""
💡 【指令秘籍】:
  直接打字          正常对话（放入新文件会自动附带发送）

  ── SOP 产品分析 ──
  /analyze 产品名    分析 my_work_files/ 中的 PDF+图片
                     → 5组标题(100-108字符) + 5条亚马逊风格卖点 + 产品特点+PDF图片映射
  /prompts 产品名    基于分析数据生成 25 个图片Prompt (5组×5类型)
                     图类型: scene / detail / real / spec / packaging
  /images  产品名    批量生成 25 张图片（图生图，spec类型纯文生图）
  /products          列出所有产品及当前进度

  ── 知识库 ──
  /list              查看知识库所有标签
  /find 关键词       模糊搜索知识库
  /save 标签名       保存内容到知识库
  /use 标签名 问题   带着知识库内容提问

  exit               退出程序
""")


# ==========================================
# SOP 指令处理函数
# ==========================================
def handle_analyze(product_name, chat, watch_folder, processed_files,
                   title_library, keywords, current_ref_images):
    """
    /analyze 产品名
    扫描文件夹 → 构造分析Prompt → 发给 Gemini → 解析JSON → 保存
    """
    print(f"\n🔍 开始分析产品: {product_name}")

    # 扫描文件夹（包含PDF和图片）
    new_parts, new_image_paths = scan_target_folder(watch_folder, processed_files)
    current_ref_images.extend(new_image_paths)

    if not new_parts:
        print("⚠️  my_work_files/ 中没有新文件，请先把PDF和产品图放进去。")
        return

    analysis_prompt = build_analysis_prompt(title_library, keywords)
    message_parts = new_parts + [types.Part.from_text(text=analysis_prompt)]

    print("📤 正在发送分析请求（含PDF和图片），请稍等…")
    response = safe_send_message(chat, message_parts, timeout=180, retries=1)
    if not response:
        return

    data = extract_json(response.text)
    if not data:
        print("❌ Gemini 返回内容解析失败，原始回复如下：")
        print(response.text[:2000])
        return

    # 保存结果
    product_dir = product_manager.save_product_analysis(
        product_name, data, ref_images=current_ref_images
    )

    # 打印摘要
    print(f"\n✅ 分析完成！数据已保存至: {product_dir}")
    print(f"   产品英文名: {data.get('product_name_en', '—')}")
    print(f"   产品中文名: {data.get('product_name_cn', '—')}")
    print(f"   生成标题组: {len(data.get('listings', []))} 组")
    print(f"   产品特点数: {len(data.get('features', []))} 条")

    print("\n📋 5组标题+卖点预览：")
    for lst in data.get("listings", []):
        title = lst.get("title", "")
        char_count = len(title)
        angle = lst.get("angle", "")
        rationale = lst.get("angle_rationale", "")
        print(f"\n  [{lst['id']}] 角度: {angle} | {char_count} 字符")
        if rationale:
            print(f"       定位: {rationale}")
        print(f"       标题: {title}")
        for i, sp in enumerate(lst.get("selling_points", []), 1):
            print(f"       卖点{i}: {sp[:100]}…")

    high_feat = [f for f in data.get('features', []) if f.get('image_value') == 'high']
    print(f"\n📌 高图像价值特点 ({len(high_feat)} 条):")
    for f in high_feat:
        hint = f.get("pdf_image_hint", "")
        print(f"   [{f['id']}] {f['en']}")
        if hint:
            print(f"        PDF图: {hint[:80]}")
    print("\n💡 下一步: /prompts " + product_name)


def handle_gen_prompts(product_name, chat):
    """
    /prompts 产品名
    读取 features.json → 构造Prompt → 发给 Gemini → 解析 → 保存 image_prompts.json
    """
    print(f"\n🎨 生成图片Prompt: {product_name}")

    prompt_text, _ = build_image_prompts_prompt(product_name)
    if not prompt_text:
        print(f"❌ 找不到产品 [{product_name}] 的分析数据，请先执行 /analyze {product_name}")
        return

    print("📤 正在请求 Gemini 生成25个图片Prompt…")
    response = safe_send_message(chat, [types.Part.from_text(text=prompt_text)], timeout=180)
    if not response:
        return

    prompts_data = extract_json(response.text)
    if not prompts_data:
        print("❌ Prompt 数据解析失败，原始回复：")
        print(response.text[:2000])
        return

    save_path = product_manager.save_image_prompts(product_name, prompts_data)
    print(f"\n✅ 25个图片Prompt已保存: {save_path}")

    IMAGE_TYPES = ["scene", "detail", "spec", "packaging", "real"]
    for item in prompts_data.get("image_prompts", []):
        print(f"\n  Listing {item['listing_id']} ({item['angle']}) - {item['scenario_tag']}:")
        for img_type in IMAGE_TYPES:
            preview = item.get(img_type, "")[:80]
            print(f"    [{img_type}] {preview}…")

    print("\n💡 下一步: /images " + product_name)


def handle_gen_images(product_name, use_vertex):
    """
    /images 产品名
    读取 image_prompts.json → 批量调用 generate_my_image → 存入 products/[name]/images/

    参考图策略：
      spec      → 纯文生图（白底技术图，参考图会干扰）
      detail    → 用参考图（需要真实零件外观）
      real      → 用参考图（追求真实感）
      scene     → 用参考图（保持机器外观一致）
      packaging → 用参考图（需要真实机器尺寸感）
    多张参考图时：每个 listing 循环轮换使用不同参考图，增加多样性
    """
    from main import generate_my_image

    prompts_data = product_manager.load_image_prompts(product_name)
    if not prompts_data:
        print(f"❌ 找不到 [{product_name}] 的图片Prompt，请先执行 /prompts {product_name}")
        return

    ref_images = product_manager.get_ref_images(product_name)
    if not ref_images:
        print("⚠️  没有找到参考图，spec以外的图类型将使用纯文生图（效果可能不稳定）")
    else:
        print(f"📷 找到 {len(ref_images)} 张参考图: {[os.path.basename(r) for r in ref_images]}")

    # spec 固定不用参考图；其余类型用参考图（如有）
    NO_REF_TYPES = {"spec"}

    IMAGE_TYPES = ["scene", "detail", "real", "spec", "packaging"]
    total = 0
    failed = 0

    image_prompts = prompts_data.get("image_prompts", [])
    print(f"\n🚀 开始批量生成 {len(image_prompts) * len(IMAGE_TYPES)} 张图片…")

    for item in image_prompts:
        listing_id = item["listing_id"]
        output_dir = product_manager.get_images_output_dir(product_name, listing_id)

        # 每个 listing 轮换选取参考图，增加跨组多样性
        ref_for_listing = ref_images[(listing_id - 1) % len(ref_images)] if ref_images else None

        for img_type in IMAGE_TYPES:
            prompt = item.get(img_type, "")
            if not prompt:
                continue

            print(f"\n🎨 Listing {listing_id} / {img_type}…")
            file_prefix = f"L{listing_id}_{img_type}"

            ref = None if img_type in NO_REF_TYPES else ref_for_listing

            try:
                saved = generate_my_image(
                    prompt=prompt,
                    model_alias="sop",
                    image_paths=ref,
                    num_images=1,
                    use_vertex=use_vertex,
                    output_dir=output_dir,
                    file_prefix=file_prefix
                )
                if saved:
                    total += 1
                    print(f"   ✅ 已保存: {os.path.basename(saved[0])}")
                else:
                    failed += 1
            except Exception as e:
                print(f"   ❌ 生成失败: {e}")
                failed += 1

    print(f"\n✅ 批量生成完成！成功 {total} 张 / 失败 {failed} 张")
    print(f"📂 输出目录: products/{product_name}/images/")


def handle_list_products():
    products = product_manager.list_products()
    if not products:
        print("📭 还没有任何产品，使用 /analyze 产品名 开始分析")
        return
    print(f"\n📦 已分析产品列表 ({len(products)} 个):")
    for p in products:
        status = []
        if p["has_analysis"]: status.append("✅分析完成")
        if p["has_prompts"]:  status.append("✅Prompt就绪")
        if p["image_count"]:  status.append(f"🖼 {p['image_count']}张图")
        print(f"  [{p['name']}]  {' | '.join(status) or '空'}")


# ==========================================
# 主程序
# ==========================================
def start_chat_session(watch_folder):
    print("🚀 初始化 Vertex AI 客户端…")
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    # 从 .env 读取是否使用 Vertex 图生图
    use_vertex = os.getenv("USE_VERTEX_AI", "False").strip().lower() in ("true", "1", "yes")

    # 加载 SOP 资产
    title_library, keywords = load_sop_assets()
    print(f"📚 标题库: {len(title_library)} 字符 | 关键词库: {len(keywords)} 字符")

    # 模型选择
    print("\n--- 🧠 选择模型 ---")
    for key, name in AVAILABLE_MODELS.items():
        print(f"  [{key}] {name}")
    model_choice = input("请选择模型序号 (默认2 - pro): ").strip() or "2"
    selected_model = AVAILABLE_MODELS.get(model_choice, "gemini-2.5-pro")

    search_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(tools=[search_tool])
    chat = client.chats.create(model=selected_model, config=config)

    processed_files = set()
    current_ref_images = []   # 本次会话中捕获到的产品参考图
    os.makedirs(watch_folder, exist_ok=True)

    print(f"\n✨ 已开启全新会话 (模型: {selected_model}，联网已开启)")
    print(f"📂 监听文件夹: {os.path.abspath(watch_folder)}")
    print_help()

    last_bot_response = ""

    while True:
        user_input = input("\n🧑 你: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ['quit', 'exit']:
            print("🛑 拜拜！")
            break

        # ── SOP 指令 ──────────────────────────────
        if user_input.startswith("/analyze "):
            product_name = user_input.split(" ", 1)[1].strip()
            handle_analyze(product_name, chat, watch_folder, processed_files,
                           title_library, keywords, current_ref_images)
            continue

        if user_input.startswith("/prompts "):
            product_name = user_input.split(" ", 1)[1].strip()
            handle_gen_prompts(product_name, chat)
            continue

        if user_input.startswith("/images "):
            product_name = user_input.split(" ", 1)[1].strip()
            handle_gen_images(product_name, use_vertex)
            continue

        if user_input == "/products":
            handle_list_products()
            continue

        # ── 知识库指令 ────────────────────────────
        if user_input.startswith("/list"):
            kb = kb_manager.load_kb()
            print("📚 知识库标签: " + (", ".join(kb.keys()) if kb else "空空如也"))
            continue

        if user_input.startswith("/find "):
            keyword = user_input.split(" ", 1)[1].strip()
            results = kb_manager.search_content(keyword)
            if results:
                print(f"🔍 找到 {len(results)} 条相关记录：")
                for topic in results.keys():
                    print(f"  - [{topic}]")
            else:
                print("⚠️ 没有找到相关内容。")
            continue

        if user_input.startswith("/save "):
            topic = user_input.split(" ", 1)[1].strip()
            existing = kb_manager.get_content(topic)
            mode = 'replace'
            if existing:
                print(f"⚠️ 已存在标签 [{topic}]。")
                choice = input("输入 'a' 追加，输入 'r' 覆盖 (默认 r): ").strip().lower()
                mode = 'append' if choice == 'a' else 'replace'
            print("👇 粘贴要保存的内容 (直接回车则保存上一条 Gemini 回复):")
            content = input("> ") or last_bot_response
            if content:
                kb_manager.save_content(topic, content, mode)
                print(f"💾 已{'追加' if mode == 'append' else '保存'}至 [{topic}]。")
            else:
                print("⚠️ 没有可保存的内容。")
            continue

        if user_input == "/help":
            print_help()
            continue

        # ── 普通对话 ──────────────────────────────
        message_parts = []

        if user_input.startswith("/use "):
            try:
                _, topic, prompt = user_input.split(" ", 2)
                content = kb_manager.get_content(topic)
                if content:
                    message_parts.append(f"【参考背景资料】：\n{content}\n\n【我的要求】：{prompt}")
                    print(f"🔗 已挂载知识库 [{topic}]")
                else:
                    print(f"⚠️ 找不到标签 [{topic}]")
                    continue
            except ValueError:
                print("⚠️ 格式: /use 标签名 你的问题")
                continue
        else:
            message_parts.append(user_input)

        new_parts, new_imgs = scan_target_folder(watch_folder, processed_files)
        current_ref_images.extend(new_imgs)
        message_parts = new_parts + message_parts

        response = safe_send_message(chat, message_parts, timeout=120, retries=1)
        if response:
            last_bot_response = response.text
            print(f"🤖 Gemini:\n{response.text}")
            if response.candidates and response.candidates[0].grounding_metadata:
                print("\n🌐 (此回答参考了 Google 实时搜索结果)")


if __name__ == "__main__":
    MY_WORK_FOLDER = "./my_work_files"
    start_chat_session(MY_WORK_FOLDER)
