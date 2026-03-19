"""
test_redesign.py
════════════════════════════════════════════════════════════════════════
产品图片整组重设计工具

核心思路:
  - 原始图 → 保留产品形态 + 去除中文水印 → 套用Listing风格重设计
  - 每个Listing = 一套独立视觉语言（颜色/质感/排版统一）
  - 5个Listing = 5条链接 = 5套视觉体系

数据来源:
  - my_work_files/analysis_result.json  → 可用图列表 + 每张图的描述
  - products/[name]/listings.json       → 各组标题/卖点/角度

用法:
  python test_redesign.py                          # 交互式选产品+组别
  python test_redesign.py 新铝箔盒封口机            # 指定产品，交互选组别
  python test_redesign.py 新铝箔盒封口机 --listing 1 # 指定产品+第1组
  python test_redesign.py 新铝箔盒封口机 --all       # 跑全部5组
  python test_redesign.py 新铝箔盒封口机 --dry-run   # 只预览Prompt不生图
════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import argparse

from dotenv import load_dotenv
import product_manager
from image_generator import generate_my_image
from ui_utils import timed_confirm

load_dotenv()

# ══════════════════════════════════════════════════════════════════════
# 配置区：5套视觉风格（与 listing_prompt_config.py 中的5个角度一一对应）
# 可自由修改每套的 palette / lighting / background / mood
# ══════════════════════════════════════════════════════════════════════

VISUAL_STYLES = {
    "Core Function": {
        "cn_label":    "核心功能 — 专业目录风",
        "palette":     "neutral white and steel gray, with subtle silver metallic accents",
        "lighting":    "soft diffused studio lighting, even and shadowless, highlight the stainless steel surface",
        "background":  "pure white or very light gray gradient background, no distractions",
        "mood":        "clean, technical, professional product catalog",
        "text_style":  "minimal sans-serif label with a thin rule line, positioned bottom-center",
    },
    "Commercial Food Service": {
        "cn_label":    "商业餐饮 — 暖调餐厅风",
        "palette":     "warm amber and cream tones, soft wood and brushed metal details in scene",
        "lighting":    "warm ambient restaurant lighting with a soft fill, golden hour feel",
        "background":  "blurred modern restaurant kitchen or deli counter environment",
        "mood":        "inviting, appetizing, busy food-service atmosphere",
        "text_style":  "bold warm-white text with a semi-transparent dark bar, top or bottom strip",
    },
    "Small Business & Startup": {
        "cn_label":    "小商户入门 — 明快简洁风",
        "palette":     "clean white base with light pastel accent (soft green or sky blue)",
        "lighting":    "bright natural daylight, soft shadows, airy feel",
        "background":  "minimalist light-toned surface (white marble or light wood)",
        "mood":        "approachable, easy, modern small-café or home-kitchen vibe",
        "text_style":  "clean modern sans-serif, accent color matches the pastel palette",
    },
    "Industrial Efficiency": {
        "cn_label":    "工厂产能 — 硬朗工业风",
        "palette":     "dark charcoal, industrial gray, with bold stainless steel highlight",
        "lighting":    "dramatic directional spotlight from upper-left, strong contrast",
        "background":  "dark factory floor or production-line environment, slightly blurred",
        "mood":        "powerful, robust, high-throughput production environment",
        "text_style":  "bold white blocky text on dark overlay, engineering/spec style",
    },
    "Multi-Application Versatility": {
        "cn_label":    "多功能兼容 — 动感多用风",
        "palette":     "vibrant but clean: white base with energetic accent colors per use case",
        "lighting":    "bright even studio lighting with subtle colored gels, dynamic feel",
        "background":  "clean white with small contextual prop elements showing different food types",
        "mood":        "versatile, dynamic, multi-product compatibility showcase",
        "text_style":  "varied callouts with arrows pointing to compatible container types",
    },
}

# 如果 listings.json 中的 angle 不在上表，用此默认风格
DEFAULT_STYLE = VISUAL_STYLES["Core Function"]

# ══════════════════════════════════════════════════════════════════════
# Prompt 构建
# ══════════════════════════════════════════════════════════════════════

def build_redesign_prompt(
    image_info: dict,
    listing: dict,
    product_name_en: str,
    style: dict,
) -> str:
    """
    为单张图片构建重设计Prompt。

    image_info: analysis_result.json 中的单条 image 记录
    listing:    listings.json 中的单条 listing 记录
    """
    category    = image_info.get("category", "产品图")
    description = image_info.get("description", "")
    angle       = listing.get("angle", "")
    target      = listing.get("target_customer", "")
    title       = listing.get("title", "")
    sps         = listing.get("selling_points", [])
    kw_focus    = listing.get("keyword_focus", [])

    # 取前2条卖点作为画面文字素材（截短避免prompt过长）
    sp1 = sps[0][:90] if len(sps) > 0 else ""
    sp2 = sps[1][:90] if len(sps) > 1 else ""

    # 关键词（用于图面英文文字）
    primary_kw = kw_focus[0] if kw_focus else product_name_en

    return f"""\
REDESIGN MODE: Transform this product image into a professional Alibaba International listing \
image for the "{angle}" listing.

━━━ PRODUCT INFO ━━━
Product: {product_name_en}
This image shows: [{category}] {description}

━━━ ABSOLUTE PRESERVATION RULES (DO NOT CHANGE) ━━━
• Keep the machine's EXACT physical form, shape, all mechanical components, and proportions
• Keep all original product colors (stainless steel surface, aluminum molds, control panel)
• Keep the machine's size relationships — do NOT scale, stretch, or crop the machine itself
• Do NOT add, remove, or rearrange any physical parts of the machine

━━━ WHAT TO REMOVE ━━━
• ALL Chinese characters and Chinese text overlays — remove every single one
• ALL Chinese watermarks, brand names in Chinese, Chinese logos
• Company contact info, WeChat QR codes, Chinese pricing text
• Cluttered or low-quality backgrounds

━━━ APPLY VISUAL STYLE: {angle} Edition ━━━
Color palette : {style['palette']}
Lighting      : {style['lighting']}
Background    : {style['background']}
Overall mood  : {style['mood']}
Text placement: {style['text_style']}

━━━ ENGLISH CONTENT TO ADD ━━━
• Primary headline (large): "{primary_kw}"
• Feature callout 1: "{sp1}"
• Feature callout 2 (smaller): "{sp2}"
• All text: English only, clean professional typography
• Do NOT add any Chinese characters in the text overlays

━━━ TARGET AUDIENCE ━━━
This image is for: {target}
It should feel like: a premium product listing photo for international B2B buyers

━━━ TECHNICAL REQUIREMENTS ━━━
• Aspect ratio: 1:1 SQUARE (strictly square — both sides equal)
• Quality: photorealistic, professional commercial product photography, 8K
• Zero Chinese text anywhere in the final image
• No watermarks, no brand logos, no QR codes, no company names
• No AI-generated artifacts, no blurry text
"""


# ══════════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════════

def load_analysis(work_folder: str = "my_work_files") -> dict:
    """加载 analysis_result.json，返回完整数据。"""
    path = os.path.join(work_folder, "analysis_result.json")
    if not os.path.exists(path):
        print(f"❌ 未找到 {path}")
        print(f"   请先运行: python analyze_pdf.py {work_folder}")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_listings(product_name: str) -> dict:
    """加载 products/[name]/listings.json。"""
    path = os.path.join(product_manager.get_product_dir(product_name), "listings.json")
    if not os.path.exists(path):
        print(f"❌ 未找到 {path}")
        print(f"   请先在 test_vertex_gemini.py 中运行: /listings {product_name}")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_useful_images(analysis: dict) -> list[dict]:
    """从分析结果中提取 useful=true 的图片列表。"""
    return [img for img in analysis.get("images", []) if img.get("useful")]


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════

def run_redesign(
    product_name: str,
    listing_ids: list[int],
    work_folder:  str  = "my_work_files",
    dry_run:      bool = False,
    model_alias:  str  = "pro",
):
    """
    对指定的 listing_ids，逐张图片生成重设计版本。

    product_name: 与 products/ 目录下的文件夹名对应
    listing_ids:  要处理的组号列表，如 [1] 或 [1,2,3,4,5]
    dry_run:      True=只打印Prompt不调用API
    model_alias:  生图模型别名（参考 main.py 中的 MODELS 字典）
    """
    # ── 加载数据 ──
    analysis = load_analysis(work_folder)
    if not analysis:
        return

    listings_data = load_listings(product_name)
    if not listings_data:
        return

    product_name_en = (
        analysis.get("product_summary", {}).get("product_name_en", "")
        or listings_data.get("product_name_en", product_name)
    )
    all_listings    = {lst["id"]: lst for lst in listings_data.get("listings", [])}
    useful_images   = get_useful_images(analysis)
    use_vertex      = os.getenv("USE_VERTEX_AI", "False").strip().lower() in ("true", "1", "yes")

    if not useful_images:
        print("⚠️  analysis_result.json 中没有 useful=true 的图片")
        return

    print(f"\n{'═'*60}")
    print(f"产品: {product_name_en}")
    print(f"可用图片: {len(useful_images)} 张")
    print(f"处理组别: Listing {listing_ids}")
    print(f"模式: {'[DRY RUN - 仅预览Prompt]' if dry_run else f'生图 (model={model_alias})'}")
    print(f"{'═'*60}")

    total_generated = 0
    total_failed    = 0

    for listing_id in listing_ids:
        listing = all_listings.get(listing_id)
        if not listing:
            print(f"\n⚠️  Listing {listing_id} 不存在，跳过")
            continue

        angle  = listing.get("angle", f"listing_{listing_id}")
        style  = VISUAL_STYLES.get(angle, DEFAULT_STYLE)
        cn_lbl = style.get("cn_label", angle)

        # 输出目录
        output_dir = os.path.join(
            product_manager.get_product_dir(product_name),
            "images", f"redesign_l{listing_id}"
        )
        os.makedirs(output_dir, exist_ok=True)

        print(f"\n{'─'*60}")
        print(f"📦 Listing {listing_id}: {angle}")
        print(f"   风格: {cn_lbl}")
        print(f"   目标客户: {listing.get('target_customer', '')}")
        print(f"   标题: {listing.get('title', '')[:80]}…")
        print(f"   输出目录: {output_dir}")
        print(f"{'─'*60}")

        for idx, img_info in enumerate(useful_images):
            img_file  = img_info.get("file", "")
            full_path = img_info.get("full_path", "")
            category  = img_info.get("category", "")
            desc      = img_info.get("description", "")[:60]

            # 确保图片路径存在
            if not full_path or not os.path.exists(full_path):
                # 尝试从 work_folder 拼接
                alt = os.path.join(work_folder, img_file)
                if os.path.exists(alt):
                    full_path = alt
                else:
                    print(f"\n  ⚠️  [{idx+1}/{len(useful_images)}] 跳过 {img_file} (文件不存在)")
                    continue

            prompt = build_redesign_prompt(img_info, listing, product_name_en, style)

            print(f"\n  🖼  [{idx+1}/{len(useful_images)}] {img_file}")
            print(f"      分类: {category} | {desc}…")
            print(f"\n  ── 生成Prompt预览 ──────────────────────────────────")
            # 打印 Prompt 前5行
            preview_lines = [l for l in prompt.split("\n") if l.strip()][:6]
            for ln in preview_lines:
                print(f"  {ln}")
            print(f"  … (共 {len(prompt)} 字符)")
            print(f"  ─────────────────────────────────────────────────")

            if dry_run:
                print(f"  [DRY RUN] 跳过生图")
                continue

            confirm = timed_confirm(
                f"\n  ▶ 生成此图? (y/n) ",
                timeout=10, default="y"
            )
            if confirm.lower() == "n":
                print("  ⏭  已跳过")
                continue

            file_prefix = f"redesign_l{listing_id}_{idx+1:02d}"
            try:
                saved = generate_my_image(
                    prompt       = prompt,
                    model_alias  = model_alias,
                    image_paths  = [full_path],   # 原图作为改图基础
                    num_images   = 1,
                    use_vertex   = use_vertex,
                    output_dir   = output_dir,
                    file_prefix  = file_prefix,
                )
                if saved:
                    total_generated += 1
                    print(f"  ✅ 已保存: {os.path.basename(saved[0])}")
                else:
                    total_failed += 1
                    print(f"  ⚠️  未获取到图片数据")
            except Exception as e:
                total_failed += 1
                print(f"  ❌ 生成失败: {e}")

        print(f"\n  ✅ Listing {listing_id} 完成")

    if not dry_run:
        print(f"\n{'═'*60}")
        print(f"全部完成: 成功 {total_generated} 张 | 失败 {total_failed} 张")
        print(f"{'═'*60}")


# ══════════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="基于 analysis_result.json + listings.json 对每张可用图片重设计"
    )
    parser.add_argument(
        "product_name",
        nargs="?",
        default=None,
        help="产品名（与 products/ 目录下的文件夹名一致）"
    )
    parser.add_argument(
        "--listing",
        type=int,
        default=None,
        help="指定单组组号 (1-5)，不指定则交互选择"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="跑全部5组"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览Prompt，不调用生图API"
    )
    parser.add_argument(
        "--model",
        default="pro",
        help="生图模型别名，默认 pro (参考 main.py MODELS 字典)"
    )
    parser.add_argument(
        "--work-folder",
        default="my_work_files",
        help="包含 analysis_result.json 的文件夹，默认 my_work_files"
    )
    args = parser.parse_args()

    # ── 交互式选产品 ──
    product_name = args.product_name
    if not product_name:
        # 列出已有产品
        existing = product_manager.list_products()
        if existing:
            print("\n📦 已有产品:")
            for p in existing:
                has_l = "✅" if os.path.exists(
                    os.path.join(product_manager.get_product_dir(p["name"]), "listings.json")
                ) else "❌"
                print(f"  [{has_l} listings] {p['name']}")
        product_name = input("\n请输入产品名: ").strip()
        if not product_name:
            print("❌ 未输入产品名，退出")
            sys.exit(1)

    # ── 确定要跑哪几组 ──
    if args.all:
        listing_ids = [1, 2, 3, 4, 5]
    elif args.listing:
        listing_ids = [args.listing]
    else:
        print("\n请选择要生成的Listing组别:")
        print("  [1-5] 单组  |  [0] 全部5组")
        choice = input("组号 (默认1): ").strip() or "1"
        if choice == "0":
            listing_ids = [1, 2, 3, 4, 5]
        else:
            try:
                listing_ids = [int(choice)]
            except ValueError:
                listing_ids = [1]

    try:
        run_redesign(
            product_name = product_name,
            listing_ids  = listing_ids,
            work_folder  = args.work_folder,
            dry_run      = args.dry_run,
            model_alias  = args.model,
        )
    except KeyboardInterrupt:
        print("\n\n🛑 已中断")
        sys.exit(0)
