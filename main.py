"""
main.py — 一键重设计流水线
════════════════════════════════════════════════════════════════════════
Step 1  analyze_pdf            → 分析文件夹图片/PDF → analysis_result.json
Step 2  build_listings         → 生成5组标题+卖点  → listings.json
Step 3  build_redesign_prompts → 生成重设计Prompt  → redesign_prompts.json
Step 4  run_image_gen          → 批量生图          → images/redesign_lN/
Step 5  build_scene_images     → 生成场景图        → scene_images/listing_N/
                                  (主图×2 无文字 pro模型 + 副图×8 特点文字 flash模型)

用法:
  python main.py                          # 交互式
  python main.py 新铝箔盒封口机            # 指定产品，全部5组
  python main.py 新铝箔盒封口机 --listing 1
  python main.py 新铝箔盒封口机 --skip 1   # 跳过 Step 1（已有 analysis_result.json）
  python main.py 新铝箔盒封口机 --skip 12  # 跳过 Step 1 和 2
  python main.py 新铝箔盒封口机 --skip 1234  # 只跑 Step 5（场景图）
════════════════════════════════════════════════════════════════════════
"""
import os
import sys
import argparse
import json

import gemini_client
import analyze_pdf
import build_listings
import build_redesign_prompts
import run_image_gen
import build_scene_images
import product_manager

WORK_FOLDER = "my_work_files"


def run(
    product_name: str,
    listing_ids:  list,
    skip:         str  = "",
    text_model:   str  = None,
    image_model:  str  = None,
    engine:       str  = "gemini",
):
    print(f"\n{'═'*60}")
    print(f"  产品重设计流水线  |  {product_name}  |  组别: {listing_ids}")
    print(f"  生图引擎: {engine.upper()}")
    print(f"{'═'*60}\n")

    # 写入环境变量，让 image_generator 路由生效
    os.environ["IMAGE_GENERATOR"] = engine

    # ── Step 1 ─────────────────────────────────────────────────────
    if "1" not in skip:
        print("▶ Step 1/5  分析产品图片和PDF…")
        result1 = analyze_pdf.analyze_folder(
            folder_path = WORK_FOLDER,
            model       = text_model or gemini_client.DEFAULT_TEXT_MODEL,
        )
        # 失败批次数过多视为分析不可用，终止流水线
        bf = result1.get("batch_failures", 0)
        tb = result1.get("total_batches", 1)
        if bf > tb // 2 or not result1.get("product_summary"):
            print("\n🛑 Step 1 分析失败率过高或缺少产品摘要，流水线终止。")
            print("   请修复网络/API问题后重试，或跳过 Step 1 使用已有分析结果。")
            return
    else:
        # 跳过时，验证文件是否存在且有效
        analysis_path = os.path.join(WORK_FOLDER, "analysis_result.json")
        if not os.path.exists(analysis_path):
            print(f"\n🛑 缺少 {analysis_path}，无法跳过 Step 1，请先运行 Step 1。")
            return
        with open(analysis_path, encoding="utf-8") as _f:
            _data = json.load(_f)
        if not _data.get("product_summary"):
            print(f"\n🛑 analysis_result.json 中无有效产品摘要，请先重新运行 Step 1。")
            return
        print("⏭  Step 1/5  跳过（使用已有 analysis_result.json）")

    # ── Step 2 ─────────────────────────────────────────────────────
    if "2" not in skip:
        print("\n▶ Step 2/5  生成5组标题+卖点…")
        build_listings.run(
            product_name = product_name,
            work_folder  = WORK_FOLDER,
            text_model   = text_model,
        )
    else:
        # 跳过时验证
        listings_path = os.path.join("products", product_name, "listings.json")
        if not os.path.exists(listings_path):
            print(f"\n🛑 缺少 {listings_path}，无法跳过 Step 2。")
            return
        print("⏭  Step 2/5  跳过（使用已有 listings.json）")

    # ── Step 3 ─────────────────────────────────────────────────────
    if "3" not in skip:
        print("\n▶ Step 3/5  正在调用 Gemini Pro 视觉导演生成重设计方案…")
        build_redesign_prompts.run(
            product_name = product_name,
            listing_ids  = listing_ids,
            work_folder  = WORK_FOLDER,
            use_gemini   = True, # 强制开启视觉导演模式
        )
    else:
        prompts_path = os.path.join("products", product_name, "redesign_prompts.json")
        if not os.path.exists(prompts_path):
            print(f"\n🛑 缺少 {prompts_path}，无法跳过 Step 3。")
            return
        print("⏭  Step 3/5  跳过（使用已有 redesign_prompts.json）")

    # ── Step 4 ─────────────────────────────────────────────────────
    if "4" not in skip:
        print("\n▶ Step 4/5  批量生图…")
        run_image_gen.run(
            product_name = product_name,
            listing_ids  = listing_ids,
            image_model  = image_model,
            engine       = engine,
        )
    else:
        print("⏭  Step 4/5  跳过生图")

    # ── Step 5 ─────────────────────────────────────────────────────
    if "5" not in skip:
        print("\n▶ Step 5/5  生成场景图（主图×2 + 副图×8）…")
        all_five = set(listing_ids) == {1, 2, 3, 4, 5}
        if all_five:
            build_scene_images.build_scene_images(
                product_name   = product_name,
                work_folder    = WORK_FOLDER,
                listing_filter = None,
                engine         = engine,
            )
        else:
            for lid in listing_ids:
                build_scene_images.build_scene_images(
                    product_name   = product_name,
                    work_folder    = WORK_FOLDER,
                    listing_filter = lid,
                    engine         = engine,
                )
    else:
        print("⏭  Step 5/5  跳过场景图")

    print(f"\n🎉 完成！产品: {product_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="一键重设计流水线 Step 1~4")
    parser.add_argument("product_name", nargs="?", default=None)
    parser.add_argument("--listing", default=None, help="组号，逗号分隔，默认全部5组")
    parser.add_argument("--skip",    default=None,
                        help="跳过的步骤编号，如 --skip 12 跳过Step1和Step2，--skip 1234 只跑Step5")
    parser.add_argument("--engine",  default=None,
                        choices=["gemini", "seedream"],
                        help="生图引擎 (默认读 .env IMAGE_GENERATOR，未设置则用 gemini)")
    args = parser.parse_args()

    product_name = args.product_name or input("请输入产品名: ").strip()
    if not product_name:
        sys.exit(1)

    listing_ids = (
        [int(x) for x in args.listing.split(",") if x.strip().isdigit()]
        if args.listing else [1, 2, 3, 4, 5]
    )

    # ── 跳过步骤：命令行明确指定时直接用，否则交互检测 ──────────────────
    if args.skip is not None:
        skip = args.skip
    else:
        skip = ""

        # Step 1: analysis_result.json
        analysis_path = os.path.join(WORK_FOLDER, "analysis_result.json")
        if os.path.exists(analysis_path):
            ans = input(f"\n✅ 已检测到 {analysis_path}\n   是否跳过 Step 1（分析）？[Y/n]: ").strip().lower()
            if ans in ("", "y"):
                skip += "1"

        # Step 2: listings.json
        listings_path = os.path.join(product_manager.get_product_dir(product_name), "listings.json")
        if os.path.exists(listings_path):
            ans = input(f"\n✅ 已检测到 listings.json\n   是否跳过 Step 2（生成标题卖点）？[Y/n]: ").strip().lower()
            if ans in ("", "y"):
                skip += "2"

        # Step 3: redesign_prompts.json
        prompts_path = os.path.join(product_manager.get_product_dir(product_name), "redesign_prompts.json")
        if os.path.exists(prompts_path):
            ans = input(f"\n✅ 已检测到 redesign_prompts.json\n   是否跳过 Step 3（生成重设计Prompt）？[Y/n]: ").strip().lower()
            if ans in ("", "y"):
                skip += "3"

        # Step 4 & 5: 生图类，默认不自动跳过，保持每次可重新生成
        print(f"\n   将跳过步骤: [{skip or '无'}]")

    # 选择引擎
    engine = args.engine or os.getenv("IMAGE_GENERATOR", "gemini").strip().lower()

    # 选择模型
    text_model  = gemini_client.select_model() if ("1" not in skip or "2" not in skip or "3" not in skip) else None
    if "4" not in skip:
        if engine == "seedream":
            from SeedDream import select_model as _seedream_select
            image_model = _seedream_select()
        else:
            image_model = gemini_client.select_image_model()
    else:
        image_model = None

    try:
        run(
            product_name = product_name,
            listing_ids  = listing_ids,
            skip         = skip,
            text_model   = text_model,
            image_model  = image_model,
            engine       = engine,
        )
    except KeyboardInterrupt:
        print("\n\n🛑 已中断")
        sys.exit(0)
