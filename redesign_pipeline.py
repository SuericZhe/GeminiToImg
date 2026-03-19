"""
redesign_pipeline.py
════════════════════════════════════════════════════════════════════════
自动化流水线：串联所有独立模块，一键完成完整重设计流程。

流程:
  Step 1  analyze_pdf.py        → 分析文件夹图片/PDF → analysis_result.json
  Step 2  sop_chat.py → /listings 产品名   → listings.json
          （Step 2 需手动在 sop_chat.py 中运行，或使用 main.py 自动运行）
  Step 3  build_redesign_prompts.py → 生成重设计 Prompt → redesign_prompts.json
  Step 4  run_image_gen.py          → 读取 Prompt 批量生图 → images/redesign_lN/

用法:
  python redesign_pipeline.py 新铝箔盒封口机                    # 全部5组
  python redesign_pipeline.py 新铝箔盒封口机 --listing 1        # 仅第1组
  python redesign_pipeline.py 新铝箔盒封口机 --skip-prompts     # 跳过生成Prompt（用已有的）
  python redesign_pipeline.py 新铝箔盒封口机 --prompts-only     # 只生成Prompt不生图
  python redesign_pipeline.py 新铝箔盒封口机 --gemini-prompts   # 用Gemini增强Prompt
════════════════════════════════════════════════════════════════════════
"""
import os
import sys
import argparse

import product_manager
import gemini_client
import build_redesign_prompts
import run_image_gen

from dotenv import load_dotenv
load_dotenv()


def run_pipeline(
    product_name:    str,
    listing_ids:     list = None,
    skip_prompts:    bool = False,
    prompts_only:    bool = False,
    use_gemini_prompts: bool = False,
    work_folder:     str  = "my_work_files",
    text_model:      str  = None,
    image_model:     str  = None,
    reset_images:    bool = False,
):
    """
    完整流水线入口。

    listing_ids=None 表示全部5组。
    """
    ids = listing_ids or [1, 2, 3, 4, 5]

    print(f"\n{'═'*60}")
    print(f"🚀 重设计流水线启动")
    print(f"   产品: {product_name}")
    print(f"   组别: {ids}")
    print(f"   工作目录: {work_folder}")
    print(f"{'═'*60}")

    # ── Step 3: 生成 Prompt ──────────────────────────────────────────
    if not skip_prompts:
        print(f"\n{'─'*60}")
        print(f"Step 3 / 4  ▶  生成重设计 Prompt")
        print(f"{'─'*60}")
        out = build_redesign_prompts.run(
            product_name = product_name,
            listing_ids  = ids,
            work_folder  = work_folder,
            use_gemini   = use_gemini_prompts,
            text_model   = text_model,
        )
        if not out:
            print("❌ Prompt 生成失败，流水线中止")
            return
        print(f"\n✅ Prompt 已保存: {out}")
    else:
        print("\n⏭  跳过 Prompt 生成（使用已有 redesign_prompts.json）")

    if prompts_only:
        print("\n✅ --prompts-only 模式，已完成 Prompt 生成，不进行生图")
        return

    # ── Step 4: 生图 ─────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"Step 4 / 4  ▶  批量生图")
    print(f"{'─'*60}")
    run_image_gen.run(
        product_name = product_name,
        listing_ids  = ids,
        image_model  = image_model,
        reset        = reset_images,
    )

    print(f"\n🎉 流水线完成！产品: {product_name}")
    print(f"   输出目录: {product_manager.get_product_dir(product_name)}/images/redesign_lN/")


# ══════════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重设计完整流水线")
    parser.add_argument("product_name",    nargs="?", default=None)
    parser.add_argument("--listing",       default=None, help="组号，逗号分隔")
    parser.add_argument("--all",           action="store_true")
    parser.add_argument("--skip-prompts",  action="store_true",
                        help="跳过 Prompt 生成，直接进行生图（用已有 redesign_prompts.json）")
    parser.add_argument("--prompts-only",  action="store_true",
                        help="只生成 Prompt，不生图")
    parser.add_argument("--gemini-prompts", action="store_true",
                        help="用 Gemini 视觉辅助生成更精准的 Prompt")
    parser.add_argument("--reset",         action="store_true",
                        help="清除生图进度，全部重跑")
    parser.add_argument("--work-folder",   default="my_work_files")
    args = parser.parse_args()

    # ── 产品名 ──
    product_name = args.product_name
    if not product_name:
        existing = product_manager.list_products()
        if existing:
            print("\n📦 已有产品:")
            for p in existing:
                has_listings = os.path.exists(
                    os.path.join(product_manager.get_product_dir(p["name"]), "listings.json")
                )
                has_prompts = os.path.exists(
                    os.path.join(product_manager.get_product_dir(p["name"]), "redesign_prompts.json")
                )
                flags = []
                if has_listings: flags.append("✅ listings")
                if has_prompts:  flags.append("✅ prompts")
                print(f"  [{' | '.join(flags) or '—'}] {p['name']}")
        product_name = input("\n请输入产品名: ").strip()
        if not product_name:
            sys.exit(1)

    # ── 组别 ──
    if args.all or (not args.listing):
        listing_ids = None   # 全部
    else:
        listing_ids = [int(x.strip()) for x in args.listing.split(",") if x.strip().isdigit()]

    # ── 模型选择 ──
    text_model  = None
    image_model = None

    if args.gemini_prompts and not args.skip_prompts:
        text_model = gemini_client.select_model(
            prompt_text="请选择用于 Prompt 生成的文本模型 (默认1): "
        )

    if not args.prompts_only:
        image_model = gemini_client.select_image_model()

    try:
        run_pipeline(
            product_name        = product_name,
            listing_ids         = listing_ids,
            skip_prompts        = args.skip_prompts,
            prompts_only        = args.prompts_only,
            use_gemini_prompts  = args.gemini_prompts,
            work_folder         = args.work_folder,
            text_model          = text_model,
            image_model         = image_model,
            reset_images        = args.reset,
        )
    except KeyboardInterrupt:
        print("\n\n🛑 已中断（进度已自动保存）")
        sys.exit(0)
