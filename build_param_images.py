"""
build_param_images.py
═══════════════════════════════════════════════════════════════
参数图批量生成工具

流程:
  1. 选择产品目录（交互式，10s 倒计时默认第一个）
  2. 读取 my_work_files/analysis_result.json
  3. 从分析结果中挑选最佳产品外观图
  4. 读取 参数图参考/ 文件夹中的 N 张参考样式图
  5. 为每张参考图各生成一张当前产品参数图
  6. 结果保存到 products/{name}/images/（与 redesign_lN 同级）

调用方式:
  python build_param_images.py
  python build_param_images.py my_work_files
  python build_param_images.py my_work_files --ref 参数图参考
═══════════════════════════════════════════════════════════════
"""
import os
import sys
import json
import argparse

import gemini_client
import image_generator
import product_manager
from ui_utils import timed_choose

# ==========================================
# 配置
# ==========================================

DEFAULT_WORK_FOLDER = "my_work_files"
DEFAULT_REF_FOLDER  = "参数图参考"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

APPEARANCE_PRIORITY = ["产品外观", "产品结构", "产品特点", "机器参数"]


# ==========================================
# Prompt 模板
# ==========================================

PARAM_IMAGE_PROMPT = """\
This is a product spec/parameter image editing task.

IMAGE 1 is the LAYOUT TEMPLATE ONLY — use it solely for layout, background color, \
number of sections, icon positions, divider lines, font style, and image-to-text ratio. \
The machine shown in IMAGE 1 is a DIFFERENT product and must be completely discarded. \
Do NOT copy, keep, or reference the machine from IMAGE 1 in any way.

IMAGE 2 (and IMAGE 3 if provided) show the ACTUAL PRODUCT that must appear in the output. \
This is the only machine that should be rendered in the product photo zone.

━━━━━━━━━━━━━━━━━━━━━━━━
YOUR ONLY TWO TASKS
━━━━━━━━━━━━━━━━━━━━━━━━
1. Place the product from IMAGE 2/3 into the photo zone of the IMAGE 1 layout.
   The machine from IMAGE 1 must be COMPLETELY REPLACED — zero trace of it remaining.
2. Replace every text block in the IMAGE 1 layout with the product information below,
   keeping the same number of blocks, same positions, same font style.

━━━━━━━━━━━━━━━━━━━━━━━━
PRODUCT INFORMATION
━━━━━━━━━━━━━━━━━━━━━━━━
Product Name: {product_name_en}
Specifications: {specs_summary}
Key Features:
{key_features}

━━━━━━━━━━━━━━━━━━━━━━━━
STRICT CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━
- MACHINE INTEGRITY (non-negotiable): The machine from IMAGE 2/3 must appear COMPLETE \
and UNCUT — all sides fully visible, nothing cropped or truncated. \
If the machine is wide or long, scale it down proportionally to fit inside the photo zone. \
NEVER remove the middle section or compress the two ends together.
- Do NOT add any new section, icon, label, or text block that is not already in the reference.
- Do NOT remove any section that exists in the reference.
- Do NOT increase the amount of text. Each text zone must contain roughly the same \
  number of words/lines as the reference — summarize if needed.
- Text capitalization: use normal Title Case or sentence case. Do NOT write entire \
  sentences or phrases in ALL CAPS — it reduces readability.
- All text must be in English only — no Chinese characters in the output image.
- NO watermarks, NO brand logos, NO copyright symbols.
"""


# ==========================================
# 工具函数
# ==========================================

def load_analysis(work_folder: str) -> dict:
    json_path = os.path.join(work_folder, "analysis_result.json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(
            f"找不到分析结果文件: {json_path}\n"
            "请先运行: python analyze_pdf.py <文件夹>"
        )
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_product_images(analysis: dict, max_count: int = 2) -> list:
    images = analysis.get("images", [])
    useful = [img for img in images if img.get("useful") and img.get("full_path")]
    selected = []
    for category in APPEARANCE_PRIORITY:
        for img in useful:
            if img.get("category") == category and img["full_path"] not in selected:
                if os.path.exists(img["full_path"]):
                    selected.append(img["full_path"])
            if len(selected) >= max_count:
                return selected
    for img in useful:
        if img["full_path"] not in selected and os.path.exists(img["full_path"]):
            selected.append(img["full_path"])
        if len(selected) >= max_count:
            break
    return selected


def list_ref_images(ref_folder: str) -> list:
    if not os.path.isdir(ref_folder):
        raise FileNotFoundError(f"参考图文件夹不存在: {ref_folder}")
    paths = []
    for fname in sorted(os.listdir(ref_folder)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            paths.append(os.path.join(ref_folder, fname))
    if not paths:
        raise ValueError(f"参考图文件夹中没有找到图片: {ref_folder}")
    return paths


def build_prompt(product_summary: dict) -> str:
    features = product_summary.get("key_features", [])
    # 只取前4条，避免撑爆文字区域
    features_str = "\n".join(f"  • {f}" for f in features[:4]) if features else "  N/A"
    return PARAM_IMAGE_PROMPT.format(
        product_name_en=product_summary.get("product_name_en", "Unknown"),
        specs_summary=product_summary.get("specs_summary", "—"),
        key_features=features_str,
    )


# ==========================================
# 主流程
# ==========================================

def build_param_images(
    product_name: str,
    work_folder: str,
    ref_folder: str = None,
    model_alias: str = None,
    use_vertex: bool = None,
) -> list:
    work_folder = os.path.abspath(work_folder)

    # ── 输出目录：products/{name}/images/ 根层
    output_dir = os.path.join(product_manager.get_product_dir(product_name), "images")

    # ── 确定参考图路径 ──
    if ref_folder is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        ref_folder = os.path.join(script_dir, DEFAULT_REF_FOLDER)
    else:
        ref_folder = os.path.abspath(ref_folder)

    # ── 读取分析结果 ──
    print(f"\n📂 工作文件夹: {work_folder}")
    analysis = load_analysis(work_folder)
    product_summary = analysis.get("product_summary", {})

    name_cn = product_summary.get("product_name_cn", "（未知产品）")
    name_en = product_summary.get("product_name_en", "Unknown")
    print(f"📦 产品: {name_cn} / {name_en}")

    # ── 挑选产品外观图 ──
    product_imgs = pick_product_images(analysis, max_count=2)
    if product_imgs:
        print(f"🖼  产品外观图: {[os.path.basename(p) for p in product_imgs]}")
    else:
        print("⚠️  未找到产品外观图，将仅凭文字描述生成")

    # ── 读取参考图 ──
    ref_images = list_ref_images(ref_folder)
    print(f"📐 参考图 ({len(ref_images)} 张): {[os.path.basename(p) for p in ref_images]}")

    # ── 选择生图模型 ──
    if model_alias is None:
        model_alias = gemini_client.select_image_model()

    # ── Vertex 开关 ──
    if use_vertex is None:
        use_vertex = os.getenv("USE_VERTEX_AI", "False").strip().lower() in ("true", "1", "yes")

    # ── 构建 Prompt ──
    base_prompt = build_prompt(product_summary)

    os.makedirs(output_dir, exist_ok=True)
    all_saved = []

    print(f"\n🚀 开始生成参数图（共 {len(ref_images)} 张）…\n")
    print(f"   输出目录: {output_dir}\n")

    for idx, ref_img in enumerate(ref_images):
        ref_name = os.path.basename(ref_img)
        prefix = f"param_{idx+1:02d}"
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"[{idx+1}/{len(ref_images)}] 参考图: {ref_name}")

        existing = [f for f in os.listdir(output_dir) if f.startswith(prefix)]
        if existing:
            print(f"   ⏭  已存在，跳过: {existing[0]}")
            all_saved.append(os.path.join(output_dir, existing[0]))
            continue

        image_list = [ref_img] + product_imgs
        print(f"   传入图片顺序:")
        for i, p in enumerate(image_list):
            label = "参考排版图" if i == 0 else f"产品图{i}"
            print(f"     [{i+1}] {label}: {os.path.basename(p)}")

        saved = image_generator.generate_my_image(
            prompt=base_prompt,
            model_alias=model_alias,
            image_paths=image_list,
            num_images=1,
            seed=None,
            use_vertex=use_vertex,
            output_dir=output_dir,
            file_prefix=prefix,
        )
        all_saved.extend(saved)

    print(f"\n✅ 参数图生成完成！共 {len(all_saved)} 张")
    print(f"   保存位置: {output_dir}")
    for p in all_saved:
        print(f"   · {os.path.basename(p)}")

    return all_saved


# ==========================================
# CLI 入口
# ==========================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量生成产品参数图")
    parser.add_argument("work_folder", nargs="?", default=None)
    parser.add_argument("--ref", default=None, dest="ref_folder")
    parser.add_argument("--vertex", action="store_true", default=False)
    args = parser.parse_args()

    print("\n" + "═" * 60)
    print("  参数图生成工具")
    print("═" * 60)

    try:
        # ── 选择产品 ──
        all_products = [p["name"] for p in product_manager.list_products()]

        if not all_products:
            print("\n⚠️  未找到任何产品目录。")
            product_name = input("请输入新产品名称以创建产品目录: ").strip()
            if not product_name:
                sys.exit(1)
            os.makedirs(product_manager.get_product_dir(product_name), exist_ok=True)
        else:
            print("\n📦 选择产品:")
            for i, name in enumerate(all_products, 1):
                print(f"  [{i}] {name}")
            idx = timed_choose("\n请输入序号 (默认1): ", all_products, default=1)
            product_name = all_products[idx - 1]
            print(f"   ✅ 已选择: {product_name}")

        # ── 工作文件夹 ──
        work_folder = args.work_folder or DEFAULT_WORK_FOLDER

        build_param_images(
            product_name=product_name,
            work_folder=work_folder,
            ref_folder=args.ref_folder,
            model_alias=None,
            use_vertex=args.vertex if args.vertex else None,
        )

    except KeyboardInterrupt:
        print("\n\n🛑 已中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        raise
