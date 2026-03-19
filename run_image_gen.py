"""
run_image_gen.py
════════════════════════════════════════════════════════════════════════
独立模块：读取 redesign_prompts.json，逐张生成图片。

支持断点续跑：已标记 generated=true 的条目自动跳过。
每张图生成前有 10s 倒计时，无操作自动确认。

用法:
  python run_image_gen.py 新铝箔盒封口机
  python run_image_gen.py 新铝箔盒封口机 --listing 1
  python run_image_gen.py 新铝箔盒封口机 --listing 1,2
  python run_image_gen.py 新铝箔盒封口机 --all
  python run_image_gen.py 新铝箔盒封口机 --reset    # 清除进度，全部重跑
════════════════════════════════════════════════════════════════════════
"""
import os
import sys
import json
import argparse

from dotenv import load_dotenv
import product_manager
import gemini_client
from image_generator import generate_my_image
from ui_utils import timed_choose, timed_confirm

load_dotenv()


# ══════════════════════════════════════════════════════════════════════
# 进度持久化
# ══════════════════════════════════════════════════════════════════════

def _load_prompts(product_name: str) -> dict:
    path = os.path.join(product_manager.get_product_dir(product_name), "redesign_prompts.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_prompts(product_name: str, data: dict):
    path = os.path.join(product_manager.get_product_dir(product_name), "redesign_prompts.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════

def run(
    product_name: str,
    listing_ids:  list = None,
    image_model:  str  = None,
    reset:        bool = False,
):
    """
    读取 redesign_prompts.json，逐条生成图片。

    product_name: products/ 下的产品文件夹名
    listing_ids:  要处理的组号列表；None = 全部
    image_model:  生图模型 alias（对应 main.py 中的 MODELS 字典）
    reset:        True = 清除所有 generated 标记，全部重跑
    """
    data = _load_prompts(product_name)
    if not data:
        print(f"❌ 未找到 redesign_prompts.json")
        print(f"   请先运行: python build_redesign_prompts.py {product_name}")
        return

    if image_model is None:
        image_model = gemini_client.DEFAULT_IMAGE_MODEL

    # main.py 的 MODELS 用别名，而不是完整 model ID
    # 把完整 ID 反向映射回别名
    from image_generator import MODELS as IMG_ALIAS_MAP
    alias_reverse = {v: k for k, v in IMG_ALIAS_MAP.items()}
    model_alias = alias_reverse.get(image_model, "banana2")

    use_vertex = os.getenv("USE_VERTEX_AI", "False").strip().lower() in ("true", "1", "yes")

    product_name_en = data.get("product_name_en", product_name)
    all_listings    = data.get("listings", [])

    # 过滤组别
    if listing_ids:
        all_listings = [l for l in all_listings if l["listing_id"] in listing_ids]

    # 统计待生成数量
    pending = sum(
        1 for lst in all_listings
        for img in lst.get("images", [])
        if reset or not img.get("generated")
    )
    already_done = sum(
        1 for lst in data.get("listings", [])
        for img in lst.get("images", [])
        if img.get("generated")
    )

    print(f"\n{'═'*60}")
    print(f"产品: {product_name_en}")
    print(f"生图模型: {image_model}  (alias: {model_alias})")
    print(f"待生成: {pending} 张  |  已完成: {already_done} 张")
    if reset:
        print("⚠️  --reset 模式：所有图片将重新生成")
    print(f"{'═'*60}")

    total_done   = 0
    total_failed = 0

    for lst_entry in all_listings:
        listing_id = lst_entry["listing_id"]
        angle      = lst_entry.get("angle", "")
        style_cn   = lst_entry.get("style_cn", "")
        title      = lst_entry.get("title", "")[:70]

        output_dir = os.path.join(
            product_manager.get_product_dir(product_name),
            "images", f"redesign_l{listing_id}"
        )
        os.makedirs(output_dir, exist_ok=True)

        print(f"\n{'─'*60}")
        print(f"Listing {listing_id}: {angle} ({style_cn})")
        print(f"标题: {title}…")
        print(f"输出: {output_dir}")
        print(f"{'─'*60}")

        for img_entry in lst_entry.get("images", []):
            prompt_id  = img_entry.get("prompt_id", "")
            img_file   = img_entry.get("image_file", "")
            category   = img_entry.get("image_category", "")
            desc       = img_entry.get("image_description", "")[:55]
            full_path  = img_entry.get("image_full_path", "")
            prompt     = img_entry.get("prompt", "")

            # 跳过已完成
            if not reset and img_entry.get("generated"):
                print(f"  ⏭  [{prompt_id}] {img_file} — 已完成，跳过")
                continue

            print(f"\n  🖼  [{prompt_id}] {img_file}")
            print(f"       {category} | {desc}…")
            print(f"\n  ── Prompt 预览 (前3行) ─────────────────────────")
            preview = [l for l in prompt.split("\n") if l.strip()][:3]
            for ln in preview:
                print(f"  {ln[:90]}")
            print(f"  … ({len(prompt)} 字符)")
            print(f"  ───────────────────────────────────────────────")

            confirm = timed_confirm(
                f"\n  ▶ 生成此图? (y/n) ",
                timeout=10, default="y"
            )
            if confirm == "n":
                print("  ⏭  已跳过")
                continue

            # 确保图片路径有效
            if not full_path or not os.path.exists(full_path):
                alt = os.path.join("my_work_files", img_file)
                full_path = alt if os.path.exists(alt) else ""

            image_paths = [full_path] if full_path else []

            try:
                saved = generate_my_image(
                    prompt      = prompt,
                    model_alias = model_alias,
                    image_paths = image_paths,
                    num_images  = 1,
                    use_vertex  = use_vertex,
                    output_dir  = output_dir,
                    file_prefix = prompt_id,
                )
                if saved:
                    img_entry["generated"]   = True
                    img_entry["output_path"] = saved[0]
                    _save_prompts(product_name, data)   # 立即持久化进度
                    total_done += 1
                    print(f"  ✅ 已保存: {os.path.basename(saved[0])}")
                else:
                    total_failed += 1
                    print(f"  ⚠️  未获取到图片数据")
            except Exception as e:
                total_failed += 1
                print(f"  ❌ 生成失败: {e}")

    print(f"\n{'═'*60}")
    print(f"完成: 成功 {total_done} 张 | 失败 {total_failed} 张")
    print(f"{'═'*60}")


# ══════════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="读取 redesign_prompts.json，批量生成图片")
    parser.add_argument("product_name", nargs="?", default=None)
    parser.add_argument("--listing", default=None, help="组号，逗号分隔，如 1,2")
    parser.add_argument("--all",     action="store_true", help="全部组")
    parser.add_argument("--reset",   action="store_true", help="清除进度，全部重跑")
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

    # 选择生图模型
    image_model = gemini_client.select_image_model()

    # 组号
    if args.all:
        listing_ids = None   # None = 全部
    elif args.listing:
        listing_ids = [int(x.strip()) for x in args.listing.split(",") if x.strip().isdigit()]
    else:
        # 交互选组，10秒无操作自动选全部
        options = ["全部5组"] + [f"仅第 {i} 组" for i in range(1, 6)]
        print("\n📋 选择要生成的 listing 范围:")
        for i, opt in enumerate(options, 1):
            print(f"  [{i}] {opt}")
        choice = timed_confirm(
            f"\n请输入序号 (默认1-全部): ",
            timeout=10, default="1"
        )
        if choice.strip() == "1" or not choice.strip().isdigit() or int(choice.strip()) < 1 or int(choice.strip()) > len(options):
            listing_ids = None
            print("   ✅ 生成全部5组")
        else:
            group_num = int(choice.strip()) - 1   # 选项2=第1组, 选项3=第2组...
            listing_ids = [group_num]
            print(f"   ✅ 仅生成第 {group_num} 组")

    try:
        run(
            product_name = product_name,
            listing_ids  = listing_ids,
            image_model  = image_model,
            reset        = args.reset,
        )
    except KeyboardInterrupt:
        print("\n\n🛑 已中断（进度已自动保存）")
        sys.exit(0)
