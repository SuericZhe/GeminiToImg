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
# 模式 B：Gemini 视觉辅助生成更精准的 Prompt
# ══════════════════════════════════════════════════════════════════════

META_PROMPT_TEMPLATE = """\
You are an AI image generation prompt engineer for Alibaba International product listings.
Your task: write an image generation prompt that will REDESIGN the attached product photo.

PRODUCT: {product_name_en}
THIS IMAGE SHOWS: [{category}] {desc}

TARGET LISTING ANGLE: {angle}
TARGET CUSTOMER: {target}
LISTING TITLE: {title}
KEY SELLING POINTS:
{sp_block}

VISUAL STYLE TO APPLY ({cn_label}):
  Color palette : {palette}
  Lighting      : {lighting}
  Background    : {background}
  Mood          : {mood}
  Text placement: {text_style}

Write a detailed, specific image generation prompt (100–200 words) that:
1. References specific visual elements you observe in the attached image
2. Clearly instructs to KEEP the machine's exact physical form, shape, color, all parts
3. Clearly instructs to REMOVE all Chinese text, watermarks, brand logos from the image
4. Applies the visual style above precisely
5. Adds English text overlays: headline "{primary_kw}", plus 1-2 feature callouts
6. Specifies 1:1 square aspect ratio, photorealistic, 2K quality
7. States "zero Chinese characters anywhere"

Return ONLY the prompt text — no explanation, no preamble, no markdown.
"""


def build_prompt_gemini(image_info: dict, listing: dict,
                        product_name_en: str, style: dict,
                        chat) -> str:
    """使用 Gemini 视觉能力，根据图片实际内容生成精准 Prompt。"""
    full_path = image_info.get("full_path", "")
    if not full_path or not os.path.exists(full_path):
        # fallback to template
        return build_prompt_template(image_info, listing, product_name_en, style)

    sps      = listing.get("selling_points", [])
    kw_focus = listing.get("keyword_focus", [])
    sp_block = "\n".join(f"  • {sp[:100]}" for sp in sps[:3])
    primary_kw = kw_focus[0] if kw_focus else product_name_en

    meta = META_PROMPT_TEMPLATE.format(
        product_name_en = product_name_en,
        category        = image_info.get("category", ""),
        desc            = image_info.get("description", ""),
        angle           = listing.get("angle", ""),
        target          = listing.get("target_customer", ""),
        title           = listing.get("title", "")[:120],
        sp_block        = sp_block,
        cn_label        = style["cn_label"],
        palette         = style["palette"],
        lighting        = style["lighting"],
        background      = style["background"],
        mood            = style["mood"],
        text_style      = style["text_style"],
        primary_kw      = primary_kw,
    )

    try:
        img_bytes, mime = gemini_client.compress_image(full_path, max_side=800)
        parts = [
            types.Part.from_bytes(data=img_bytes, mime_type=mime),
            types.Part.from_text(text=meta),
        ]
        response = gemini_client.safe_send(
            chat, parts, timeout=60, 
            retries=len(pool) * 2 if pool else 2, 
            pool=pool, model=text_model
        )
        if response and response.text.strip():
            return response.text.strip()
    except Exception as e:
        print(f"   ⚠️  Gemini 增强失败，回退到模板: {e}")

    return build_prompt_template(image_info, listing, product_name_en, style)


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
        print(f"\n🧠 Gemini 增强模式（模型: {text_model}）")
        # 使用凭证轮换池
        pool   = gemini_client.CredentialPool(use_vertex=True)
        client = pool.make_client()
        chat   = gemini_client.create_chat(client, model=text_model)
    else:
        print("\n⚡ 模板模式（无需 API，秒速生成）")

    # ── 构建所有 Prompts ──
    print(f"\n产品: {product_name_en}")
    print(f"可用图片: {len(useful_images)} 张  |  处理组别: {listing_ids}\n")

    result = {
        "product_name":    product_name,
        "product_name_en": product_name_en,
        "generated_at":    datetime.now().isoformat(timespec="seconds"),
        "work_folder":     os.path.abspath(work_folder),
        "mode":            "gemini" if use_gemini else "template",
        "listings":        [],
    }

    total = 0
    for listing_id in listing_ids:
        listing = all_listings.get(listing_id)
        if not listing:
            print(f"⚠️  Listing {listing_id} 不存在，跳过")
            continue

        angle  = listing.get("angle", f"listing_{listing_id}")
        style  = VISUAL_STYLES.get(angle, DEFAULT_STYLE)

        print(f"{'─'*50}")
        print(f"Listing {listing_id}: {angle} ({style['cn_label']})")
        print(f"{'─'*50}")

        listing_entry = {
            "listing_id":      listing_id,
            "angle":           angle,
            "style_cn":        style["cn_label"],
            "title":           listing.get("title", ""),
            "target_customer": listing.get("target_customer", ""),
            "images":          [],
        }

        for idx, img_info in enumerate(useful_images):
            img_file = img_info.get("file", "")
            category = img_info.get("category", "")
            desc60   = img_info.get("description", "")[:55]
            print(f"  [{idx+1:02d}/{len(useful_images):02d}] {img_file} | {category}")

            if use_gemini and chat:
                prompt_text = build_prompt_gemini(img_info, listing, product_name_en, style, chat)
            else:
                prompt_text = build_prompt_template(img_info, listing, product_name_en, style)

            prompt_id = f"l{listing_id}_img{idx+1:02d}"
            listing_entry["images"].append({
                "prompt_id":         prompt_id,
                "image_file":        img_file,
                "image_full_path":   img_info.get("full_path", ""),
                "image_category":    category,
                "image_description": img_info.get("description", ""),
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
            print("\n📦 已有产品:")
            for p in existing:
                print(f"  {p['name']}")
        product_name = input("\n请输入产品名: ").strip()
        if not product_name:
            sys.exit(1)

    # 组号解析
    if args.all:
        listing_ids = [1, 2, 3, 4, 5]
    elif args.listing:
        listing_ids = [int(x.strip()) for x in args.listing.split(",") if x.strip().isdigit()]
    else:
        choice = input("请输入组号 (1-5，逗号分隔；0=全部；默认1): ").strip() or "1"
        if choice == "0":
            listing_ids = [1, 2, 3, 4, 5]
        else:
            listing_ids = [int(x.strip()) for x in choice.split(",") if x.strip().isdigit()] or [1]

    # 模式
    use_gemini = args.gemini and not args.template
    text_model = None
    if use_gemini:
        text_model = gemini_client.select_model(
            prompt_text="请选择用于 Prompt 生成的文本模型 (默认1): "
        )

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
