"""
build_redesign_prompts.py
════════════════════════════════════════════════════════════════════════
独立模块：为每张可用图片 × 每个 Listing 生成重设计 Prompt，保存为 JSON。

两种生成模式：
  --template  纯 Python 模板，无需 API 调用，秒速生成（默认）
  --gemini    调用 Gemini 视觉模型，根据图片实际内容生成更精准的 Prompt

用法:
  python build_redesign_prompts.py 新铝箔盒封口机
  python build_redesign_prompts.py 新铝箔盒封口机 --listing 1,2
  python build_redesign_prompts.py 新铝箔盒封口机 --all --gemini
  python build_redesign_prompts.py 新铝箔盒封口机 --all --template
════════════════════════════════════════════════════════════════════════
"""
import os
import sys
import json
import argparse
from datetime import datetime

import product_manager
import gemini_client
from google.genai import types
from ui_utils import timed_choose

# ══════════════════════════════════════════════════════════════════════
# 五套视觉风格（与 listing_prompt_config.py 中的5个角度对应）
# ══════════════════════════════════════════════════════════════════════

VISUAL_STYLES = {
    "Core Function": {
        "cn_label":   "专业目录风",
        "palette":    "neutral white and steel gray, subtle silver metallic accents",
        "lighting":   "soft diffused studio lighting, even and shadowless, highlight stainless steel",
        "background": "pure white or very light gray gradient, no distractions",
        "mood":       "clean, technical, professional product catalog",
        "text_style": "minimal sans-serif label with thin rule line, bottom-center",
    },
    "Commercial Food Service": {
        "cn_label":   "暖调餐饮风",
        "palette":    "warm amber and cream tones, soft wood and brushed metal in scene",
        "lighting":   "warm ambient restaurant lighting with soft fill, golden hour feel",
        "background": "blurred modern restaurant kitchen or deli counter environment",
        "mood":       "inviting, appetizing, busy food-service atmosphere",
        "text_style": "bold warm-white text with semi-transparent dark bar, top or bottom strip",
    },
    "Small Business & Startup": {
        "cn_label":   "明快简洁风",
        "palette":    "clean white base with light pastel accent (soft green or sky blue)",
        "lighting":   "bright natural daylight, soft shadows, airy feel",
        "background": "minimalist light-toned surface (white marble or light wood)",
        "mood":       "approachable, easy, modern small-café or home-kitchen vibe",
        "text_style": "clean modern sans-serif, accent color matches pastel palette",
    },
    "Industrial Efficiency": {
        "cn_label":   "硬朗工业风",
        "palette":    "dark charcoal, industrial gray, bold stainless steel highlight",
        "lighting":   "dramatic directional spotlight from upper-left, strong contrast",
        "background": "dark factory floor or production-line environment, slightly blurred",
        "mood":       "powerful, robust, high-throughput production environment",
        "text_style": "bold white blocky text on dark overlay, engineering/spec style",
    },
    "Multi-Application Versatility": {
        "cn_label":   "多功能兼容风",
        "palette":    "vibrant but clean: white base with energetic accent colors",
        "lighting":   "bright even studio lighting with subtle colored gels, dynamic feel",
        "background": "clean white with small contextual props showing different food types",
        "mood":       "versatile, dynamic, multi-product compatibility showcase",
        "text_style": "varied callouts with arrows pointing to compatible container types",
    },
}

DEFAULT_STYLE = VISUAL_STYLES["Core Function"]


# ══════════════════════════════════════════════════════════════════════
# 模式 A：Python 模板直接生成 Prompt
# ══════════════════════════════════════════════════════════════════════

def build_prompt_template(image_info: dict, listing: dict,
                          product_name_en: str, style: dict) -> str:
    category = image_info.get("category", "产品图")
    desc     = image_info.get("description", "")
    angle    = listing.get("angle", "")
    target   = listing.get("target_customer", "")
    sps      = listing.get("selling_points", [])
    kw_focus = listing.get("keyword_focus", [])

    sp1 = sps[0][:90] if len(sps) > 0 else ""
    sp2 = sps[1][:90] if len(sps) > 1 else ""
    primary_kw = kw_focus[0] if kw_focus else product_name_en

    return (
        f'REDESIGN MODE: Transform this product image into a professional Alibaba International '
        f'listing image for the "{angle}" listing.\n\n'
        f'━━━ PRODUCT ━━━\n'
        f'Product: {product_name_en}\n'
        f'This image shows: [{category}] {desc}\n\n'
        f'━━━ PRESERVE EXACTLY ━━━\n'
        f'• Machine exact physical form, shape, all mechanical components and proportions\n'
        f'• All original product colors (stainless steel surface, aluminum molds, control panel)\n'
        f'• Do NOT scale, stretch, crop, add or remove any physical parts\n\n'
        f'━━━ REMOVE COMPLETELY ━━━\n'
        f'• ALL Chinese characters, Chinese text overlays, Chinese watermarks\n'
        f'• Brand logos, company names in Chinese, contact info, QR codes\n'
        f'• Cluttered or low-quality backgrounds\n\n'
        f'━━━ VISUAL STYLE: {angle} Edition ({style["cn_label"]}) ━━━\n'
        f'Color palette : {style["palette"]}\n'
        f'Lighting      : {style["lighting"]}\n'
        f'Background    : {style["background"]}\n'
        f'Mood          : {style["mood"]}\n'
        f'Text placement: {style["text_style"]}\n\n'
        f'━━━ ENGLISH CONTENT TO ADD ━━━\n'
        f'• Primary headline: "{primary_kw}"\n'
        f'• Feature callout 1: "{sp1}"\n'
        f'• Feature callout 2: "{sp2}"\n'
        f'• All text: English only, clean professional typography\n\n'
        f'━━━ TARGET ━━━\n'
        f'Audience: {target}\n\n'
        f'━━━ TECHNICAL ━━━\n'
        f'• Aspect ratio: 1:1 SQUARE (strictly square)\n'
        f'• Quality: photorealistic, professional commercial product photography, 2K\n'
        f'• Zero Chinese text anywhere in the final image\n'
        f'• No watermarks, no brand logos, no QR codes\n'
    )


# ══════════════════════════════════════════════════════════════════════
# 模式 B：Gemini 视觉辅助生成更精准的 Prompt (视觉导演模式)
# ══════════════════════════════════════════════════════════════════════

VISUAL_DIRECTOR_PROMPT = """\
You are an elite AI Visual Director for Alibaba International. Your mission is to redesign a product image so it PERFECTLY matches a specific marketing listing created in Step 2.

### MISSION:
Analyze the product photo and the specific "Marketing Angle" provided. Create a redesign prompt that isn't just "pretty," but is a "visual conversion machine" for that specific target audience.

### INPUTS FROM STEP 1 & 2:
- **Product**: {product_name_en}
- **Image Category**: {category}
- **Image Description**: {desc}
- **Chinese Texts detected**: {chinese_texts}
- **LISTING ANGLE (The Soul)**: {angle} ({cn_label})
- **TARGET AUDIENCE**: {target}
- **SPECIFIC SELLING POINTS TO HIGHLIGHT**:
{sp_block}

### MANDATORY DESIGN RULES:
1. **Visual Alignment**: The environment, lighting, and "mood" MUST be derived from the **Listing Angle**. (e.g., if the angle is "Industrial Efficiency," show a high-power, high-speed industrial vibe; if "Small Business," show a friendly, accessible, modern vibe).
2. **Product Fidelity**: KEEP the machine's exact physical form, shape, and color. Do not change the machine itself.
3. **"English-First" Transformation**: 
   - REMOVE ALL Chinese text/watermarks.
   - REPLACE them with the English terms provided or inferred.
   - INTEGRATE the Selling Points into the scene (e.g., as clean, professional text overlays or via visual storytelling).
4. **Cinematic Quality**: Use professional photography terms (e.g., "Depth of field," "8k resolution," "Ray tracing," "Clean composition").

### OUTPUT FORMAT:
Return ONLY a JSON object:
{{
  "design_reasoning": "用中文简述：你如何根据该组 Listing 的特定卖点和受众来设计这组视觉方案的。",
  "image_prompt": "A long, detailed English prompt (150-250 words) that describes the final redesigned image, ensuring it matches the Listing's marketing soul.",
  "english_texts": ["List of English terms used to replace Chinese ones"]
}}
JSON ONLY."""


def select_best_image(useful_images: list, angle: str) -> dict:
    """根据 Listing 角度从可用图片中挑选最合适的一张作为参考。"""
    # 简单的类别映射逻辑
    mapping = {
        "Core Function": ["产品外观", "整体图"],
        "Commercial Food Service": ["应用场景", "产品外观"],
        "Small Business & Startup": ["操作面板", "整体图"],
        "Industrial Efficiency": ["内部结构", "整体图"],
        "Multi-Application Versatility": ["产品外观", "整体图"],
    }
    
    preferred_categories = mapping.get(angle, ["产品外观", "整体图"])
    
    # 1. 尝试匹配首选类别
    for cat in preferred_categories:
        for img in useful_images:
            if img.get("category") == cat:
                return img
                
    # 2. 如果没匹配到，选第一张 useful 的
    return useful_images[0] if useful_images else {}


def build_prompt_gemini(image_info: dict, listing: dict,
                        product_name_en: str, style: dict,
                        chat, pool, model) -> dict:
    """使用 Gemini 视觉能力，担任“视觉导演”生成精准重设计方案。"""
    full_path = image_info.get("full_path", "")
    if not full_path or not os.path.exists(full_path):
        return {"error": "Image path not found"}

    sps      = listing.get("selling_points", [])
    kw_focus = listing.get("keyword_focus", [])
    sp_block = "\n".join(f"  • {sp}" for sp in sps[:3])
    primary_kw = kw_focus[0] if kw_focus else product_name_en
    chinese_texts = image_info.get("chinese_texts", [])

    prompt_text = VISUAL_DIRECTOR_PROMPT.format(
        product_name_en = product_name_en,
        category        = image_info.get("category", ""),
        desc            = image_info.get("description", ""),
        chinese_texts   = ", ".join(chinese_texts) if chinese_texts else "None identified",
        angle           = listing.get("angle", ""),
        target          = listing.get("target_customer", ""),
        sp_block        = sp_block,
        cn_label        = style["cn_label"],
    )

    try:
        img_bytes, mime = gemini_client.compress_image(full_path, max_side=1024)
        parts = [
            types.Part.from_bytes(data=img_bytes, mime_type=mime),
            types.Part.from_text(text=prompt_text),
        ]
        response = gemini_client.safe_send(
            chat, parts, timeout=120, 
            retries=len(pool) * 2 if pool else 2, 
            pool=pool, model=model
        )
        if response and response.text:
            import re
            # 提取 JSON 内容
            text = response.text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group())
    except Exception as e:
        print(f"   ⚠️  Gemini 视觉导演模式失败: {e}")

    return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════

def run(
    product_name: str,
    listing_ids:  list,
    work_folder:  str  = "my_work_files",
    use_gemini:   bool = False,
    text_model:   str  = None,
) -> str:
    """
    生成并保存所有重设计 Prompt。
    返回保存的 JSON 文件路径。

    product_name: products/ 目录下的产品文件夹名
    listing_ids:  要处理的组号列表
    work_folder:  含 analysis_result.json 的目录
    use_gemini:   True = 调用 Gemini 视觉辅助生成（更精准但慢）
    text_model:   Gemini 文本模型 ID（use_gemini=True 时有效）
    """
    # ── 检查是否已有 redesign_prompts.json ──
    out_dir  = product_manager.get_product_dir(product_name)
    out_path = os.path.join(out_dir, "redesign_prompts.json")
    if os.path.exists(out_path):
        ans = input(f"\n⚠️  已存在 {os.path.basename(out_path)}，[o]覆盖 / [s]跳过 (默认跳过): ").strip().lower()
        if ans != "o":
            print(f"   ⏭  跳过，使用已有数据: {out_path}")
            return out_path

    # ── 加载 analysis_result.json ──
    analysis_path = os.path.join(work_folder, "analysis_result.json")
    if not os.path.exists(analysis_path):
        print(f"❌ 未找到 {analysis_path}")
        print(f"   请先运行: python analyze_pdf.py {work_folder}")
        return ""
    with open(analysis_path, encoding="utf-8") as f:
        analysis = json.load(f)

    # ── 加载 listings.json ──
    listings_path = os.path.join(product_manager.get_product_dir(product_name), "listings.json")
    if not os.path.exists(listings_path):
        print(f"❌ 未找到 {listings_path}")
        print(f"   请先在 sop_chat.py 运行: /listings {product_name}")
        return ""
    with open(listings_path, encoding="utf-8") as f:
        listings_data = json.load(f)

    product_name_en = (
        analysis.get("product_summary", {}).get("product_name_en", "")
        or listings_data.get("product_name_en", product_name)
    )
    all_listings  = {lst["id"]: lst for lst in listings_data.get("listings", [])}
    useful_images = [img for img in analysis.get("images", []) if img.get("useful")]

    if not useful_images:
        print("⚠️  analysis_result.json 中没有 useful=true 的图片")
        return ""

    # ── 初始化 Gemini（仅 use_gemini 模式需要）──
    chat = None
    pool = None
    if use_gemini:
        if text_model is None:
            text_model = gemini_client.DEFAULT_TEXT_MODEL 
        print(f"\n🧠 Gemini 视觉导演模式开启（模型: {text_model}）")
        # 使用凭证轮换池
        pool   = gemini_client.CredentialPool(use_vertex=True)
        client = pool.make_client()
        chat   = gemini_client.create_chat(client, model=text_model)
    else:
        print("\n⚡ 模板模式（无需 API，秒速生成）")

    # ── 构建所有 Prompts ──
    print(f"\n产品: {product_name_en}")
    print(f"可用原图: {len(useful_images)} 张  |  处理组别: {listing_ids}\n")

    result = {
        "product_name":    product_name,
        "product_name_en": product_name_en,
        "generated_at":    datetime.now().isoformat(timespec="seconds"),
        "work_folder":     os.path.abspath(work_folder),
        "mode":            "gemini_pro" if use_gemini else "template",
        "listings":        [],
    }

    total = 0
    for listing_id in listing_ids:
        listing = all_listings.get(listing_id)
        if not listing:
            continue

        angle  = listing.get("angle", f"listing_{listing_id}")
        style  = VISUAL_STYLES.get(angle, DEFAULT_STYLE)

        print(f"{'═'*60}")
        print(f"🎬 Listing {listing_id}: {angle} ({style['cn_label']})")
        print(f"{'═'*60}")

        # 🎯 修改点：处理所有 useful 图片，而不仅仅是挑选一张
        to_process = useful_images 

        listing_entry = {
            "listing_id":      listing_id,
            "angle":           angle,
            "style_cn":        style["cn_label"],
            "title":           listing.get("title", ""),
            "target_customer": listing.get("target_customer", ""),
            "images":          [],
        }

        for idx, img_info in enumerate(to_process):
            img_file = img_info.get("file", "")
            category = img_info.get("category", "")
            print(f"  [{idx+1}/{len(to_process)}] 📸 处理原图: {img_file} ({category})")

            if use_gemini and chat:
                # 视觉导演会根据当前 Listing 的 angle 和 img_info 的内容实时构思
                director_plan = build_prompt_gemini(img_info, listing, product_name_en, style, chat, pool, text_model)
                if "error" in director_plan:
                    prompt_text = build_prompt_template(img_info, listing, product_name_en, style)
                    reasoning = "Gemini 请求失败，已回退到模板模式。"
                    english_texts = []
                else:
                    prompt_text = director_plan.get("image_prompt", "")
                    reasoning = director_plan.get("design_reasoning", "")
                    english_texts = director_plan.get("english_texts", [])
                    # print(f"    💡 设计思路: {reasoning[:60]}...")
            else:
                prompt_text = build_prompt_template(img_info, listing, product_name_en, style)
                reasoning = "使用预设模板生成。"
                english_texts = []

            prompt_id = f"l{listing_id}_img{idx+1:02d}"
            listing_entry["images"].append({
                "prompt_id":         prompt_id,
                "image_file":        img_file,
                "image_full_path":   img_info.get("full_path", ""),
                "image_category":    category,
                "image_description": img_info.get("description", ""),
                "design_reasoning":  reasoning,
                "english_texts":     english_texts,
                "prompt":            prompt_text,
                "generated":         False,
                "output_path":       None,
            })
            total += 1

        result["listings"].append(listing_entry)
        print()

    # ── 保存 JSON ──
    out_dir  = product_manager.get_product_dir(product_name)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "redesign_prompts.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ 共生成 {total} 条 Prompt，已保存: {out_path}")
    return out_path


# ══════════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成产品重设计 Prompt 并保存为 JSON")
    parser.add_argument("product_name", nargs="?", default=None)
    parser.add_argument("--listing",     default=None,
                        help="指定组号，逗号分隔，如 1,2 或 1")
    parser.add_argument("--all",         action="store_true", help="全部5组")
    parser.add_argument("--gemini",      action="store_true",
                        help="用 Gemini 视觉辅助生成（更精准，需 API）")
    parser.add_argument("--template",    action="store_true",
                        help="纯模板模式（无需 API，默认）")
    parser.add_argument("--work-folder", default="my_work_files")
    args = parser.parse_args()

    product_name = args.product_name
    if not product_name:
        existing = product_manager.list_products()
        if existing:
            options = [p['name'] for p in existing]
            print("\n📦 已有产品:")
            for i, name in enumerate(options, 1):
                print(f"  [{i}] {name}")
            
            idx = timed_choose(
                prompt="请选择产品序号 (默认1): ",
                options=options,
                default=1,
                timeout=10
            )
            if 1 <= idx <= len(options):
                product_name = options[idx-1]
            else:
                print(f"   ⚠️  无效选择，默认选择第一个产品: {options[0]}")
                product_name = options[0]
        else:
            product_name = input("\n请输入产品名: ").strip()
            if not product_name:
                sys.exit(1)

    # 组号解析
    if args.all:
        listing_ids = [1, 2, 3, 4, 5]
    elif args.listing:
        listing_ids = [int(x.strip()) for x in args.listing.split(",") if x.strip().isdigit()]
    else:
        choice = (input("请输入组号 (1-5，逗号分隔；0=全部；默认1): ").strip()
                  .replace(" ", ",").replace("，", ",")) # 增强容错
        if not choice or choice == "1":
            listing_ids = [1]
        elif "0" in choice.split(","):
            listing_ids = [1, 2, 3, 4, 5]
        else:
            listing_ids = [int(x.strip()) for x in choice.split(",") if x.strip().isdigit()] or [1]

    # 模式逻辑：默认使用 Gemini，除非指定 --template
    use_gemini = not args.template
    text_model = gemini_client.DEFAULT_TEXT_MODEL  # 统一默认模型

    try:
        run(
            product_name = product_name,
            listing_ids  = listing_ids,
            work_folder  = args.work_folder,
            use_gemini   = use_gemini,
            text_model   = text_model,
        )
    except KeyboardInterrupt:
        print("\n\n🛑 已中断")
        sys.exit(0)
