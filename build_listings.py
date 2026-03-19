"""
build_listings.py
════════════════════════════════════════════════════════════════════════
独立模块：基于 analysis_result.json + 标题库 + 关键词库，
调用 Gemini 生成5组标题+卖点，保存 listings.json。

Prompt 策略完全由 listing_prompt_config.py 控制，可直接编辑调整。

用法:
  python build_listings.py 新铝箔盒封口机
  python build_listings.py 新铝箔盒封口机 --work-folder my_work_files
════════════════════════════════════════════════════════════════════════
"""
import os
import sys
import json
import re
import argparse

import gemini_client
import product_manager
import listing_prompt_config
from dotenv import load_dotenv
from google.genai import types

load_dotenv()


def _load_asset(path: str) -> str:
    """读取资产文件，不存在则返回空字符串。"""
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def _extract_json(text: str):
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        return None


def run(
    product_name: str,
    work_folder:  str = "my_work_files",
    text_model:   str = None,
) -> str:
    """
    生成5组标题+卖点并保存。
    返回保存路径（失败返回空字符串）。
    """
    if text_model is None:
        text_model = gemini_client.DEFAULT_TEXT_MODEL

    # ── 检查是否已有 listings.json ──
    product_dir   = product_manager.get_product_dir(product_name)
    listings_path = os.path.join(product_dir, "listings.json")
    if os.path.exists(listings_path):
        ans = input(f"\n⚠️  已存在 listings.json，[o]覆盖 / [s]跳过 (默认跳过): ").strip().lower()
        if ans != "o":
            print("   ⏭  跳过，使用已有数据。")
            with open(listings_path, encoding="utf-8") as f:
                data = json.load(f)
            _export_to_feishu(product_name, data)
            return listings_path

    # ── 读取 analysis_result.json ──
    analysis_path = os.path.join(work_folder, "analysis_result.json")
    product_summary = {}
    if os.path.exists(analysis_path):
        with open(analysis_path, encoding="utf-8") as f:
            ar = json.load(f)
        product_summary = ar.get("product_summary", {})
        print(f"   📂 已加载分析结果: {analysis_path}")
        print(f"   产品: {product_summary.get('product_name_en', '—')} | "
              f"特点: {len(product_summary.get('key_features', []))} 条")
    else:
        print(f"⚠️  未找到 {analysis_path}，请先运行: python analyze_pdf.py {work_folder}")
        print("   将仅依据关键词库生成，效果可能较差。")

    # ── 读取资产 ──
    title_library = _load_asset("assets/title_library.txt")
    keywords      = _load_asset("assets/keywords_food_machine.txt")
    title_lines   = [l for l in title_library.splitlines() if l.strip() and not l.startswith("#")]
    kw_lines      = [l for l in keywords.splitlines()      if l.strip() and not l.startswith("#")]
    print(f"   标题库: {len(title_lines)} 条  |  关键词: {len(kw_lines)} 条")

    # ── 构建 Prompt ──
    prompt_text = listing_prompt_config.build_listing_prompt(
        product_summary = product_summary,
        title_library   = title_library,
        keywords        = keywords,
    )

    # ── 初始化 Gemini ──
    print(f"\n🧠 文本模型: {text_model}")
    # 使用凭证轮换池，支持 API Key 和 Vertex 自动切换
    pool   = gemini_client.CredentialPool(use_vertex=True)
    client = pool.make_client()
    chat   = gemini_client.create_chat(client, model=text_model)

    print("📤 正在请求 Gemini 生成5组标题+卖点…")
    response = gemini_client.safe_send(
        chat,
        [types.Part.from_text(text=prompt_text)],
        timeout=180,
        retries=len(pool) * 2,  # 确保每个凭证至少有重试机会
        pool=pool,
        model=text_model
    )

    # 主模型失败时自动降级到备选模型 (此时 safe_send 已经处理了凭证轮换)
    if not response:
        fallback_model = "gemini-2.5-pro"  # 备选模型
        if text_model != fallback_model:
            print(f"⚠️  主模型失败，自动降级到 {fallback_model} 重试…")
            # 重新从当前池子里的有效凭证开始
            fallback_chat = gemini_client.create_chat(client, model=fallback_model)
            response = gemini_client.safe_send(
                fallback_chat,
                [types.Part.from_text(text=prompt_text)],
                timeout=180,
                retries=len(pool),
                pool=pool,
                model=fallback_model
            )

    if not response:
        print("❌ Gemini 请求失败")
        return ""

    data = _extract_json(response.text)
    if not data or "listings" not in data:
        print("❌ 解析失败，原始回复:")
        print(response.text[:2000])
        return ""

    # ── 保存 listings.json ──
    os.makedirs(product_dir, exist_ok=True)
    with open(listings_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 5组标题+卖点已保存: {listings_path}")

    # ── 预览 ──
    print(f"\n{'='*60}")
    for lst in data.get("listings", []):
        title  = lst.get("title", "")
        chars  = lst.get("title_char_count", len(title))
        angle  = lst.get("angle", "")
        print(f"\n  [{lst['id']}] {angle}  ({chars} 字符)")
        print(f"       标题: {title}")
        for i, sp in enumerate(lst.get("selling_points", [])[:2], 1):
            print(f"       卖点{i}: {sp[:100]}{'…' if len(sp)>100 else ''}")

    # ── 导出到飞书（失败不中断主流程）──
    _export_to_feishu(product_name, data)

    return listings_path


# ══════════════════════════════════════════════════════════════════════
# 飞书导出
# ══════════════════════════════════════════════════════════════════════

_FEISHU_CACHE = "feishu_cache.json"


def _load_feishu_cache() -> dict:
    if os.path.exists(_FEISHU_CACHE):
        with open(_FEISHU_CACHE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_feishu_cache(cache: dict):
    with open(_FEISHU_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _get_or_create_spreadsheet(fm) -> str:
    """
    返回汇总表的 spreadsheet_token。
    优先级：.env FEISHU_SPREADSHEET_TOKEN > feishu_cache.json > 新建
    """
    title        = os.getenv("FEISHU_SPREADSHEET_TITLE", "食品机械产品标题库")
    folder_token = os.getenv("FEISHU_TARGET_FOLDER", "")

    # 1. .env 中手动配置的 token（适合表格已存在的情况）
    token = os.getenv("FEISHU_SPREADSHEET_TOKEN", "").strip()
    if token:
        print(f"   📋 使用 .env 中配置的表格 token")
        return token

    # 2. 本地缓存
    cache = _load_feishu_cache()
    token = cache.get("spreadsheet_token", "").strip()
    if token:
        try:
            fm.get_sheets(token)
            return token
        except Exception:
            print("   ⚠️  缓存 token 已失效，重新创建…")

    # 3. 新建
    print(f"   📄 正在创建汇总表「{title}」…")
    info  = fm.create_spreadsheet(title, folder_token=folder_token or None)
    # 飞书 API 返回 snake_case: spreadsheet_token
    token = info.get("spreadsheet_token") or info.get("spreadsheetToken", "")
    if not token:
        raise Exception(f"创建成功但未找到 token，完整返回: {info}")
    cache["spreadsheet_token"] = token
    cache["spreadsheet_title"] = title
    _save_feishu_cache(cache)
    print(f"   ✅ 已创建: {info.get('url', '')}  token: {token}")
    print(f"   💡 可将 token 写入 .env: FEISHU_SPREADSHEET_TOKEN={token}")
    return token


def _export_to_feishu(product_name: str, data: dict):
    """
    将5组标题+卖点写入飞书汇总表。
    - 汇总表不存在 → 自动创建并缓存 token
    - Sheet 以产品名命名，存在则覆盖
    """
    try:
        from create_feishu_excel import FeishuSheetManager
        fm    = FeishuSheetManager()
        token = _get_or_create_spreadsheet(fm)

        # 获取或创建以产品名命名的 Sheet
        sheet_id = fm.get_or_create_sheet(token, product_name)
        print(f"   📋 Sheet「{product_name}」id: {sheet_id}")

        # 构建表头 + 数据行
        header = ["#", "角度", "目标客户", "关键词", "标题", "字符数",
                  "卖点1", "卖点2", "卖点3", "卖点4", "卖点5"]
        rows = [header]
        for lst in data.get("listings", []):
            sps = lst.get("selling_points", [])
            rows.append([
                str(lst.get("id", "")),
                lst.get("angle", ""),
                lst.get("target_customer", ""),
                ", ".join(lst.get("keyword_focus", [])),
                lst.get("title", ""),
                str(lst.get("title_char_count", len(lst.get("title", "")))),
                sps[0] if len(sps) > 0 else "",
                sps[1] if len(sps) > 1 else "",
                sps[2] if len(sps) > 2 else "",
                sps[3] if len(sps) > 3 else "",
                sps[4] if len(sps) > 4 else "",
            ])

        total_rows = len(rows)
        range_addr = f"{sheet_id}!A1:K{total_rows}"
        fm.write_sheet(token, range_addr, rows)
        print(f"   ✅ 已写入飞书表格「{product_name}」，共 {total_rows-1} 组数据")

    except Exception as e:
        print(f"   ⚠️  飞书导出失败（不影响主流程）: {e}")


# ══════════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成5组标题+卖点")
    parser.add_argument("product_name", nargs="?", default=None)
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

    text_model = gemini_client.select_model()

    try:
        run(product_name, work_folder=args.work_folder, text_model=text_model)
    except KeyboardInterrupt:
        print("\n\n🛑 已中断")
        sys.exit(0)
