"""
build_scene_images.py
════════════════════════════════════════════════════════════════════════
场景图批量生成工具

流程:
  1. 读取 my_work_files/analysis_result.json 获取产品特点 + 参考图
  2. 读取 products/{product_name}/listings.json 获取5组标题+卖点
  3. 针对每组 listing 生成10张场景图:
     ├─ 2张「纯产品+场景」主图 (无文字, gemini-3-pro-image-preview)
     └─ 8张「产品+特点」副图 (含英文特点文字, gemini-3.1-flash-image-preview)

输出目录: products/{product_name}/images/redesign_l{id}/

用法:
  python build_scene_images.py 新铝箔盒封口机
  python build_scene_images.py 新铝箔盒封口机 --work-folder my_work_files
  python build_scene_images.py 新铝箔盒封口机 --listing 2        # 仅生成第2组
  python build_scene_images.py 新铝箔盒封口机 --skip-main        # 只生成副图
  python build_scene_images.py 新铝箔盒封口机 --skip-feature     # 只生成主图
════════════════════════════════════════════════════════════════════════
"""
import os
import sys
import json
import gemini_client
import image_generator
import product_manager
from ui_utils import timed_choose


# ══════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════

DEFAULT_WORK_FOLDER   = "my_work_files"
MAIN_MODEL_ALIAS      = "banana2"       # gemini-3-pro-image-preview，用于主图（2张），改为pro即可用最高模型
FEATURE_MODEL_ALIAS   = "banana2"  # gemini-3.1-flash-image-preview，用于副图（8张）

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# 产品外观图优先类别（与 build_param_images 一致）
APPEARANCE_PRIORITY = ["产品外观", "产品结构", "产品特点"]

# 每组生成数量
MAIN_COUNT    = int(os.getenv("MAIN_COUNT", 2))   # 主图：纯产品+场景，无文字
FEATURE_COUNT = int(os.getenv("FEATURE_COUNT", 5))   # 副图：产品+特点文字


# ══════════════════════════════════════════════════════════════════════
# Prompt 模板
# ══════════════════════════════════════════════════════════════════════

# ── 主图 Prompt（无文字）──
MAIN_SCENE_PROMPT_TEMPLATE = """\
You are a professional Amazon product photographer. Recreate the product shown in the \
reference image(s) as a polished e-commerce hero shot.

PRODUCT: {product_name_en}
USE CONTEXT: {angle} — {target_customer}

━━━━━━━━━━━━━━━━━━━━━━━━
COMPOSITION INSTRUCTION
━━━━━━━━━━━━━━━━━━━━━━━━
{composition_hint}

━━━━━━━━━━━━━━━━━━━━━━━━
PRODUCT PROMINENCE RULES (highest priority)
━━━━━━━━━━━━━━━━━━━━━━━━
• The product is the SOLE subject. It must occupy at least 70% of the frame.
• Place the product dead-center or slightly forward of center.
• All background elements (surfaces, objects, environment) must be \
SOFT, BLURRED, and LOW-CONTRAST — they exist only to hint at context, never to compete.
• NO people, NO hands, NO cluttered surroundings, NO busy scenes.
• Studio-quality, even lighting on the product; background may have gentle color gradient.
• Reproduce the product's shape, color, and details faithfully from the reference.

━━━━━━━━━━━━━━━━━━━━━━━━
HARD CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━
• MACHINE INTEGRITY (non-negotiable): The machine must be shown COMPLETE and UNCUT — \
all four sides fully visible, nothing cropped or truncated. If the machine is wide or long, \
scale it down proportionally so the entire machine fits inside the frame with margin on all sides. \
NEVER remove the middle section, compress ends together, or show only part of the machine.
• The product is the SOLE subject. It must occupy at least 60% of the frame (scaled down if needed to stay whole).
• Place the product dead-center or slightly forward of center.
• All background elements must be SOFT, BLURRED, and LOW-CONTRAST.
• NO people, NO hands, NO cluttered surroundings.
• Studio-quality, even lighting on the product; background may have gentle color gradient.
• Reproduce the product's shape, color, and details faithfully from the reference.
• ZERO added text — no extra captions, watermarks, brand name overlays, or any\
 typography that is NOT already physically on the machine itself.
• Chinese text that is physically printed or displayed on the machine (control panel,\
 body labels, digital screen) should be reproduced faithfully — do NOT erase, blur, or translate it.
• 1:1 square aspect ratio.
"""

# 按机器尺寸分级的构图提示（每级2条，差异化主图构图）
COMPOSITION_HINTS_BY_SIZE = {
    # 桌面小机器：可放在桌/台面上拍摄
    "desktop": [
        "3/4 front-angle view, product sitting on a clean matte desk or countertop. "
        "Background: very softly blurred office or kitchen environment in warm neutral tones. "
        "Depth of field: sharp product, everything else fades to near-invisible.",

        "Slightly elevated straight-on hero shot on a white or light-gray tabletop. "
        "Background: pure gradient from light gray to off-white, or a single blurred "
        "contextual prop placed far behind and out of focus. "
        "Lighting: soft box front-left key light, gentle fill from right, subtle drop shadow below product.",
    ],
    # 工作台机器：放在结实工作台或操作台上
    "benchtop": [
        "3/4 front-angle view, machine sitting on a sturdy stainless-steel workbench in a clean workshop. "
        "Background: softly blurred industrial workbench environment, muted cool tones. "
        "Product occupies at least 70% of frame; bench surface visible only at bottom edge.",

        "Straight-on hero shot, machine centered on a heavy-duty workbench or production table. "
        "Background: very gently blurred factory interior with soft ambient lighting. "
        "Lighting: bright even front lighting to highlight machine details, subtle shadow beneath.",
    ],
    # 落地中型机器：站在地面，工厂/车间环境
    "floor_small": [
        "3/4 front-angle view, machine standing on a clean epoxy factory floor. "
        "Background: softly blurred modern food-processing or packaging workshop, cool neutral tones. "
        "Camera angle: slightly below eye level to convey the machine's real-world scale. "
        "Product occupies 70%+ of frame; floor visible at bottom to anchor it in space.",

        "Straight-on shot, machine on factory floor with subtle perspective. "
        "Background: blurred production line environment, industrial lighting from above. "
        "No tabletop or desk — the machine stands freely on the ground. "
        "Lighting: bright key light from upper-front, gentle fill from sides.",
    ],
    # 大型工业机器：整线/大型设备，工厂全景
    "floor_large": [
        "Wide 3/4 front-angle view of the full machine on a factory floor. "
        "Background: softly blurred large-scale industrial production hall, high ceiling, cool tones. "
        "Camera placed at machine mid-height to show its imposing scale naturally. "
        "Product fills 65%+ of frame; floor and minimal surrounding space hint at the industrial setting.",

        "Straight-on hero shot of the entire machine line, standing on factory floor. "
        "Background: blurred modern manufacturing facility with overhead industrial lighting. "
        "Convey scale: the machine should look large, powerful, and floor-anchored — "
        "never floating or placed on furniture. Subtle drop shadow on floor.",
    ],
}

# 兜底：旧分析结果没有 machine_size_class 时，尝试从 specs_summary 推断
def _infer_size_class(product_summary: dict) -> str:
    """从 specs_summary 中解析最大尺寸维度，推断 size_class。"""
    specs = product_summary.get("specs_summary", "")
    size_class = product_summary.get("machine_size_class", "")
    if size_class in COMPOSITION_HINTS_BY_SIZE:
        return size_class

    # 尝试从 specs_summary 里找最大的数字（毫米或厘米）
    import re
    nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*(?:mm|MM)", specs)]
    if not nums:
        # 没有单位，尝试裸数字（可能是 cm 或 m）
        nums = [float(x) for x in re.findall(r"\b(\d{3,5})\b", specs)]

    if nums:
        max_dim = max(nums)  # 最大维度（mm）
        weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|KG|公斤)", specs, re.I)
        weight = float(weight_match.group(1)) if weight_match else 0
        if max_dim > 2000 or weight > 500:
            return "floor_large"
        elif max_dim > 800 or weight > 80:
            return "floor_small"
        elif max_dim > 400 or weight > 10:
            return "benchtop"
        else:
            return "desktop"

    # 完全无法判断，默认 floor_small（工业机器偏多）
    return "floor_small"


# ── 副图 Prompt（含特点文字）──
FEATURE_SCENE_PROMPT_TEMPLATE = """\
You are a professional Amazon listing designer. Create a secondary infographic image \
for the product shown in the reference image(s).

PRODUCT: {product_name_en}
SCENE CONTEXT: {angle} — {scene_description}

━━━━━━━━━━━━━━━━━━━━━━━━
FEATURE TEXT TO DISPLAY ON THE IMAGE
━━━━━━━━━━━━━━━━━━━━━━━━
{feature_text}

━━━━━━━━━━━━━━━━━━━━━━━━
DESIGN REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━
• Show the product prominently (≥60% of frame) in a clean scene that suits the context.
• Overlay the feature text above as a bold English callout, badge, or label on the image.
• Use clean sans-serif typography; high contrast against the background.
• One short callout line or a label+arrow pointing to the relevant product part is ideal.
• The feature text is the ONLY copy needed — do not add extra text or bullet points.

━━━━━━━━━━━━━━━━━━━━━━━━
LANGUAGE RULES
━━━━━━━━━━━━━━━━━━━━━━━━
• All ADDED text (callouts, badges, labels, arrows, annotations) MUST be in English only.
• Chinese text that is physically part of the machine — printed on the control panel,
  body, or digital screen — should be reproduced faithfully. Do NOT erase, blur, or
  replace it with English. It is an authentic feature of the product.
• Do NOT add any Chinese text as new overlays or annotations.

━━━━━━━━━━━━━━━━━━━━━━━━
OTHER CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━
• MACHINE INTEGRITY (non-negotiable): The machine must be shown COMPLETE and UNCUT — \
all four sides fully visible, nothing cropped or truncated. If the machine is wide or long, \
scale it down proportionally so the ENTIRE machine fits inside the frame. \
NEVER remove the middle section or show only part of the machine.
• NO watermarks, NO brand logos, NO copyright symbols.
• 1:1 square aspect ratio.
• Professional Amazon secondary image quality.
"""


# ══════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════

def load_analysis(work_folder: str) -> dict:
    path = os.path.join(work_folder, "analysis_result.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"找不到分析结果: {path}\n"
            "请先运行: python analyze_pdf.py <文件夹>"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_listings(product_name: str) -> dict:
    listings_path = os.path.join(
        product_manager.get_product_dir(product_name), "listings.json"
    )
    if not os.path.exists(listings_path):
        raise FileNotFoundError(
            f"找不到 listings.json: {listings_path}\n"
            "请先运行: python build_listings.py {product_name}"
        )
    with open(listings_path, encoding="utf-8") as f:
        return json.load(f)


def pick_product_images(analysis: dict, max_count: int = 2) -> list:
    """挑选最能代表产品外观的参考图。"""
    images  = analysis.get("images", [])
    useful  = [img for img in images if img.get("useful") and img.get("full_path")]
    selected = []
    for category in APPEARANCE_PRIORITY:
        for img in useful:
            if img.get("category") == category and img["full_path"] not in selected:
                if os.path.exists(img["full_path"]):
                    selected.append(img["full_path"])
            if len(selected) >= max_count:
                return selected
    for img in useful:
        p = img["full_path"]
        if p not in selected and os.path.exists(p):
            selected.append(p)
        if len(selected) >= max_count:
            break
    return selected


def build_feature_list(product_summary: dict, listing: dict) -> list:
    """
    组合8条用于副图的特点文字：
    - 优先使用 analysis 中的 key_features（最多7条）
    - 第8条使用 listing 的第1条卖点的核心短语
    """
    features = list(product_summary.get("key_features", []))

    # 如果不足8条，从 listing selling_points 补充
    selling_points = listing.get("selling_points", [])
    idx = 0
    while len(features) < FEATURE_COUNT and idx < len(selling_points):
        sp = selling_points[idx]
        # 取冒号后面的描述部分作为简洁特点文字
        if ":" in sp:
            short = sp.split(":", 1)[1].strip()
        else:
            short = sp.strip()
        features.append(short)
        idx += 1

    return features[:FEATURE_COUNT]


def angle_to_scene(angle: str, target_customer: str, applicable_scenarios: list) -> str:
    """根据 listing 角度生成场景描述文字。"""
    # 优先使用 applicable_scenarios
    if applicable_scenarios:
        scenarios_str = " / ".join(applicable_scenarios[:3])
        return f"{angle} setting (e.g., {scenarios_str})"
    return f"{angle} environment for {target_customer}"


# ══════════════════════════════════════════════════════════════════════
# 主生成逻辑
# ══════════════════════════════════════════════════════════════════════

def build_scene_images(
    product_name:   str,
    work_folder:    str  = DEFAULT_WORK_FOLDER,
    listing_filter: int  = None,    # 仅生成指定 id 的 listing
    skip_main:      bool = False,   # 跳过主图（无文字）
    skip_feature:   bool = False,   # 跳过副图（含特点文字）
    use_vertex:     bool = None,
) -> dict:
    """
    执行完整的场景图生成流程。
    返回 {listing_id: [saved_paths]} 字典。
    """
    work_folder = os.path.abspath(work_folder)

    # ── 读取数据 ──
    print(f"\n📂 工作文件夹: {work_folder}")
    analysis = load_analysis(work_folder)
    product_summary = analysis.get("product_summary", {})
    name_en = product_summary.get("product_name_en", "Unknown Product")
    name_cn = product_summary.get("product_name_cn", "")
    applicable_scenarios = product_summary.get("applicable_scenarios", [])

    print(f"📦 产品: {name_cn} / {name_en}")

    # ── 推断机器尺寸级别，选对应构图模板 ──
    size_class = _infer_size_class(product_summary)
    composition_hints = COMPOSITION_HINTS_BY_SIZE[size_class]
    print(f"📐 机器尺寸级别: {size_class}  (构图方案已匹配)")

    listings_data = load_listings(product_name)
    listings = listings_data.get("listings", [])
    if not listings:
        print("❌ listings.json 中没有找到任何 listing，请检查文件。")
        return {}

    # ── 挑选产品参考图 ──
    product_imgs = pick_product_images(analysis, max_count=2)
    if product_imgs:
        print(f"🖼  参考图: {[os.path.basename(p) for p in product_imgs]}")
    else:
        print("⚠️  未找到产品外观图，将仅凭 Prompt 文字生图（效果可能较差）")

    # ── Vertex 开关 ──
    if use_vertex is None:
        use_vertex = os.getenv("USE_VERTEX_AI", "False").strip().lower() in ("true", "1", "yes")

    all_results = {}

    # ── 遍历5组 listing ──
    for listing in listings:
        listing_id = listing.get("id")
        if listing_filter is not None and listing_id != listing_filter:
            continue

        angle           = listing.get("angle", "General")
        target_customer = listing.get("target_customer", "")
        title           = listing.get("title", "")
        scene_desc      = angle_to_scene(angle, target_customer, applicable_scenarios)
        output_dir      = os.path.join(
            product_manager.get_product_dir(product_name),
            "images",
            f"redesign_l{listing_id}",
        )
        os.makedirs(output_dir, exist_ok=True)

        print(f"\n{'═'*60}")
        print(f"📋 Listing [{listing_id}] — {angle}")
        print(f"   标题: {title[:70]}{'…' if len(title)>70 else ''}")
        print(f"   场景: {scene_desc}")
        print(f"   输出: {output_dir}")

        saved_all = []

        # ────────────────────────────────────────
        # ① 生成2张主图（无文字，pro 模型，失败自动降级）
        # ────────────────────────────────────────
        if not skip_main:
            print(f"\n  🖼  主图 ({MAIN_COUNT}张) | 模型: {image_generator.MODELS[MAIN_MODEL_ALIAS]}")
            for i, composition_hint in enumerate(composition_hints, start=1):
                prefix = f"main_L{listing_id:02d}_{i:02d}"
                existing = [f for f in os.listdir(output_dir) if f.startswith(prefix)]
                if existing:
                    print(f"     ⏭  主图{i} 已存在，跳过: {existing[0]}")
                    saved_all.append(os.path.join(output_dir, existing[0]))
                    continue
                prompt = MAIN_SCENE_PROMPT_TEMPLATE.format(
                    product_name_en  = name_en,
                    angle            = angle,
                    target_customer  = target_customer,
                    scene_description= scene_desc,
                    composition_hint = composition_hint,
                )
                saved = image_generator.generate_my_image(
                    prompt       = prompt,
                    model_alias  = MAIN_MODEL_ALIAS,
                    image_paths  = product_imgs,
                    num_images   = 1,
                    seed         = None,
                    use_vertex   = use_vertex,
                    output_dir   = output_dir,
                    file_prefix  = prefix,
                )
                # 主图模型失败 → 自动降级到副图模型重试
                if not saved:
                    fallback_model = image_generator.MODELS[FEATURE_MODEL_ALIAS]
                    print(f"     ⚠️  主图模型失败，降级至 {fallback_model} 重试…")
                    saved = image_generator.generate_my_image(
                        prompt       = prompt,
                        model_alias  = FEATURE_MODEL_ALIAS,
                        image_paths  = product_imgs,
                        num_images   = 1,
                        seed         = None,
                        use_vertex   = use_vertex,
                        output_dir   = output_dir,
                        file_prefix  = f"{prefix}_fallback",
                    )
                saved_all.extend(saved)
                if saved:
                    print(f"     ✅ 主图{i}: {os.path.basename(saved[0])}")

        # ────────────────────────────────────────
        # ② 生成8张副图（含特点文字，flash 模型）
        # ────────────────────────────────────────
        if not skip_feature:
            features = build_feature_list(product_summary, listing)
            print(f"\n  📝 副图 ({FEATURE_COUNT}张) | 模型: {image_generator.MODELS[FEATURE_MODEL_ALIAS]}")
            print(f"     特点列表 ({len(features)}条):")
            for fi, ft in enumerate(features, 1):
                print(f"     [{fi}] {ft[:80]}{'…' if len(ft)>80 else ''}")

            for fi, feature_text in enumerate(features, start=1):
                prefix = f"feat_L{listing_id:02d}_{fi:02d}"
                existing = [f for f in os.listdir(output_dir) if f.startswith(prefix)]
                if existing:
                    print(f"     ⏭  副图{fi} 已存在，跳过: {existing[0]}")
                    saved_all.append(os.path.join(output_dir, existing[0]))
                    continue
                prompt = FEATURE_SCENE_PROMPT_TEMPLATE.format(
                    product_name_en  = name_en,
                    angle            = angle,
                    target_customer  = target_customer,
                    scene_description= scene_desc,
                    feature_text     = feature_text,
                )
                saved = image_generator.generate_my_image(
                    prompt       = prompt,
                    model_alias  = FEATURE_MODEL_ALIAS,
                    image_paths  = product_imgs,
                    num_images   = 1,
                    seed         = None,
                    use_vertex   = use_vertex,
                    output_dir   = output_dir,
                    file_prefix  = prefix,
                )
                saved_all.extend(saved)
                if saved:
                    print(f"     ✅ 副图{fi}: {os.path.basename(saved[0])}")

        all_results[listing_id] = saved_all
        total = len(saved_all)
        print(f"\n  📊 Listing [{listing_id}] 完成: {total} 张图片保存至 {output_dir}")

    # ── 汇总 ──
    grand_total = sum(len(v) for v in all_results.values())
    print(f"\n{'═'*60}")
    print(f"✅ 全部完成！共生成 {grand_total} 张场景图")
    for lid, paths in all_results.items():
        out = os.path.join(
            product_manager.get_product_dir(product_name),
            "images", f"redesign_l{lid}"
        )
        print(f"   Listing [{lid}]: {len(paths)} 张 → {out}")

    return all_results


# ══════════════════════════════════════════════════════════════════════
# CLI 入口（全交互菜单）
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "═" * 60)
    print("  场景图生成工具  (主图×2 + 副图×8 / 每组listing)")
    print("═" * 60)

    try:
        # ── ① 选择产品 ──────────────────────────────────────────
        existing = product_manager.list_products()
        products_with_listings = []
        products_without = []
        for p in existing:
            has = os.path.exists(
                os.path.join(product_manager.get_product_dir(p["name"]), "listings.json")
            )
            if has:
                products_with_listings.append(p["name"])
            else:
                products_without.append(p["name"])

        all_products = products_with_listings + products_without

        if not all_products:
            # 没有任何产品目录，让用户输入名称创建
            print("\n⚠️  未找到任何产品目录。")
            product_name = input("请输入新产品名称以创建产品目录: ").strip()
            if not product_name:
                sys.exit(1)
            os.makedirs(product_manager.get_product_dir(product_name), exist_ok=True)
            print(f"   ✅ 已创建产品目录: {product_manager.get_product_dir(product_name)}")
            if not os.path.exists(os.path.join(product_manager.get_product_dir(product_name), "listings.json")):
                print(f"⚠️  请先运行: python build_listings.py {product_name}")
                sys.exit(1)
        else:
            print("\n📦 选择产品:")
            for i, name in enumerate(all_products, 1):
                tag = "  ✓ listings" if name in products_with_listings else "  ✗ 无listings"
                print(f"  [{i}] {name}{tag}")
            print(f"  [0] 输入新产品名称（创建）")
            idx = timed_choose(f"\n请输入序号 (默认1): ", all_products, default=1)
            if idx == 0:
                product_name = input("请输入新产品名称: ").strip()
                if not product_name:
                    sys.exit(1)
                os.makedirs(product_manager.get_product_dir(product_name), exist_ok=True)
                print(f"   ✅ 已创建产品目录: {product_manager.get_product_dir(product_name)}")
            else:
                product_name = all_products[idx - 1]
                print(f"   ✅ 已选择: {product_name}")

        if not os.path.exists(os.path.join(product_manager.get_product_dir(product_name), "listings.json")):
            print(f"⚠️  该产品暂无 listings.json，请先运行: python build_listings.py {product_name}")
            sys.exit(1)

        # ── ② 生成哪些 listing ──────────────────────────────────
        listings_path = os.path.join(
            product_manager.get_product_dir(product_name), "listings.json"
        )
        with open(listings_path, encoding="utf-8") as f:
            listings_data = json.load(f)
        listings = listings_data.get("listings", [])

        print("\n📋 生成范围:")
        range_options = ["全部5组 (共50张)"] + [
            f"仅第 {lst['id']} 组 — {lst.get('angle','')}" for lst in listings
        ]
        for i, opt in enumerate(range_options, 1):
            print(f"  [{i}] {opt}")
        range_idx = timed_choose(f"\n请输入序号 (默认1): ", range_options, default=1)
        if range_idx == 1:
            listing_filter = None
            print("   ✅ 生成全部5组")
        else:
            listing_filter = listings[range_idx - 2]["id"]
            print(f"   ✅ 仅生成第 {listing_filter} 组")

        # ── ③ 生成内容选择 ──────────────────────────────────────
        print("\n🎨 生成内容:")
        content_options = [
            "主图 + 副图  (2张无文字主图 + 8张特点副图，共10张/组)",
            "仅主图       (2张无文字纯场景图/组，gemini-3-pro-image-preview)",
            "仅副图       (8张特点文字副图/组，gemini-3.1-flash-image-preview)",
        ]
        for i, opt in enumerate(content_options, 1):
            print(f"  [{i}] {opt}")
        content_idx = timed_choose(f"\n请输入序号 (默认1): ", content_options, default=1)
        skip_main    = (content_idx == 3)
        skip_feature = (content_idx == 2)
        print(f"   ✅ {content_options[content_idx - 1].split('(')[0].strip()}")

        # ── ④ 执行 ──────────────────────────────────────────────
        build_scene_images(
            product_name   = product_name,
            work_folder    = DEFAULT_WORK_FOLDER,
            listing_filter = listing_filter,
            skip_main      = skip_main,
            skip_feature   = skip_feature,
        )

    except KeyboardInterrupt:
        print("\n\n🛑 已中断")
        sys.exit(0)
    except FileNotFoundError as e:
        print(f"\n❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        raise
