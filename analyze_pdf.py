"""
analyze_pdf.py
PDF + 图片批量分析工具。

使用方式:
    python analyze_pdf.py                        # 交互式，选择文件夹
    python analyze_pdf.py my_work_files          # 直接指定文件夹
    python analyze_pdf.py my_work_files --model gemini-2.5-pro

功能:
    1. 扫描指定文件夹，找到 PDF 文件和图片
    2. 将 PDF 每页渲染成 PNG（保存到同目录）
    3. 批量发给 Gemini 分析：哪些有价值、是什么内容
    4. 输出整体产品摘要 + 每张图的标签/描述
    5. 结果保存为 analysis_result.json
"""
import os
import re
import sys
import json
import math

import gemini_client  # 从 gemini_client.py 导入可复用封装
from google.genai import types

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

# ==========================================
# 配置
# ==========================================

DEFAULT_MODEL    = "gemini-2.5-pro"
BATCH_SIZE       = 7       # 每批发送的图片数（防止 SSL 超时）
MAX_SIDE_PIXELS  = 800     # 发给 API 前的压缩尺寸

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
PDF_EXTENSIONS   = {".pdf"}

# 图片分类标签（中文）
CATEGORY_LABELS = [
    "产品外观",
    "产品结构",
    "机器参数",
    "产品特点",
    "使用场景",
    "操作说明",
    "包装展示",
    "认证资质",
    "厂家服务",
    "其他有效信息",
]


# ==========================================
# PDF 拆分
# ==========================================

def split_pdf(pdf_path: str, output_dir: str = None) -> list[str]:
    """
    将 PDF 每页渲染为 PNG，保存到 output_dir（默认与 PDF 同目录）。
    返回所有渲染出的图片路径列表。
    """
    if not PYMUPDF_AVAILABLE:
        print("⚠️  未安装 PyMuPDF，跳过 PDF 拆分。安装命令: pip install pymupdf")
        return []

    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(pdf_path))

    os.makedirs(output_dir, exist_ok=True)

    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    doc = fitz.open(pdf_path)
    saved = []
    mat = fitz.Matrix(2.0, 2.0)  # 2× 提高清晰度

    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat)
        # 文件名: 原PDF名_page_001.png，避免多个PDF混淆
        out_path = os.path.join(output_dir, f"{pdf_name}_page_{i+1:03d}.png")
        pix.save(out_path)
        saved.append(out_path)

    doc.close()
    print(f"   📄 {os.path.basename(pdf_path)}: {len(saved)} 页已渲染 → {output_dir}")
    return saved


# ==========================================
# 文件夹扫描
# ==========================================

def scan_folder(folder_path: str) -> tuple[list[str], list[str]]:
    """
    扫描文件夹，返回 (pdf_list, image_list)。
    只扫描顶层，不递归。
    """
    pdfs   = []
    images = []
    for fname in sorted(os.listdir(folder_path)):
        fpath = os.path.join(folder_path, fname)
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext in PDF_EXTENSIONS:
            pdfs.append(fpath)
        elif ext in IMAGE_EXTENSIONS:
            images.append(fpath)
    return pdfs, images


# ==========================================
# JSON 提取
# ==========================================

def extract_json(text: str):
    """从 Gemini 回复中提取第一个 JSON 对象或数组。"""
    if not text:
        return None
    # 优先提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*([\[\{].*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        # 找第一个 { 或 [
        start = min(
            (text.find("{") if "{" in text else len(text)),
            (text.find("[") if "[" in text else len(text))
        )
        if start < len(text):
            text = text[start:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试修复常见问题（末尾逗号）
        fixed = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            return json.loads(fixed)
        except Exception:
            return None


# ==========================================
# 核心分析逻辑
# ==========================================

def _build_batch_prompt(batch_files: list[str], batch_idx: int, total_batches: int,
                        start_num: int) -> str:
    """构建单批次分析 Prompt。"""
    end_num = start_num + len(batch_files) - 1
    labels_str = " / ".join(CATEGORY_LABELS)

    return f"""I am providing images {start_num} to {end_num} (batch {batch_idx+1}/{total_batches}).
These images come from a product listing folder (1688.com / Alibaba supplier).
Images are in order, numbered {start_num} through {end_num}.

For EACH image, determine:
1. Whether it contains product-relevant content worth keeping
2. If useful: assign a category label and write a brief Chinese description

Mark useful=false ONLY for: company/factory intro with no product, pure contact/address info,
blank pages, decorative borders, QR code only, footer/header only.

Mark useful=true for ANY image containing: product photos, product structure or parts,
usage demonstrations, spec tables, feature descriptions, certifications, dimensions,
materials, packaging, operation instructions — even if mostly text.

Return ONLY valid JSON:
{{
  "images": [
    {{
      "index": {start_num},
      "file": "(original filename)",
      "useful": true,
      "category": "产品外观",
      "description": "展示机器整体外观，左侧为操作面板，右侧为封口压臂"
    }},
    {{
      "index": {start_num + 1},
      "file": "(original filename)",
      "useful": false,
      "category": null,
      "description": "公司联系方式页，无产品信息"
    }}
  ]
}}

category must be one of: {labels_str}
Analyze all {len(batch_files)} images. Be thorough."""


def _build_summary_prompt(useful_images: list[dict]) -> str:
    """基于有效图片的分析结果，构建整体产品摘要 Prompt。"""
    image_list = "\n".join(
        f"- [{img['category']}] {img['description']}"
        for img in useful_images
    )
    return f"""Based on the following image analysis results from a product listing:

{image_list}

Please provide a comprehensive product summary in JSON format:
{{
  "product_name_cn": "中文产品名",
  "product_name_en": "English Product Name",
  "product_type": "产品类型（如：食品机械 / 包装设备）",
  "core_function": "核心功能一句话描述",
  "key_features": ["特点1", "特点2", "特点3", "...（尽量多列）"],
  "applicable_scenarios": ["适用场景1", "场景2"],
  "target_customers": "目标客户群体",
  "certifications": ["认证1", "认证2"],
  "materials": "主要材质",
  "specs_summary": "参数摘要（如有）",
  "machine_size_class": "desktop | benchtop | floor_small | floor_large"
}}

machine_size_class rules (pick exactly one):
- desktop   : fits on a standard desk/countertop; footprint < 40×40 cm AND weight < 10 kg (e.g. label printer, small sealer)
- benchtop  : sits on a workbench or heavy table; footprint 40–80 cm on any side OR weight 10–80 kg (e.g. small filling machine, bag sealer)
- floor_small: stands on the factory floor; footprint/height > 80 cm on any side OR weight 80–500 kg (e.g. 1–2 m long conveyor, mid-size packaging machine)
- floor_large: large industrial machine; length/width > 2 m OR weight > 500 kg (e.g. full-line packaging machine, large sealing line)
If dimensions/weight are not mentioned, infer from the product type and typical industry use.

Be concise but comprehensive. key_features should have at least 5 items."""


def analyze_folder(
    folder_path: str,
    model: str = DEFAULT_MODEL,
    output_file: str = None
) -> dict:
    """
    主函数：分析整个文件夹的产品图片。

    参数:
        folder_path: 包含 PDF 和/或图片的文件夹路径
        model:       Gemini 模型 ID
        use_vertex:  True=Vertex AI, False=API Key, None=从 .env 读取
        output_file: 结果保存路径（默认 folder_path/analysis_result.json）

    返回:
        {
          "folder": ...,
          "product_summary": {...},
          "images": [{"file":..., "useful":..., "category":..., "description":...}, ...]
        }
    """
    folder_path = os.path.abspath(folder_path)
    if not os.path.isdir(folder_path):
        raise ValueError(f"文件夹不存在: {folder_path}")

    if output_file is None:
        output_file = os.path.join(folder_path, "analysis_result.json")

    print(f"\n📂 分析文件夹: {folder_path}")

    # ── Step 1: 扫描文件夹 ──
    pdfs, existing_images = scan_folder(folder_path)
    print(f"   发现 PDF: {len(pdfs)} 个  |  图片: {len(existing_images)} 张")

    # ── Step 2: 拆分 PDF ──
    pdf_page_images = []
    for pdf_path in pdfs:
        pages = split_pdf(pdf_path, output_dir=folder_path)
        pdf_page_images.extend(pages)

    # ── Step 3: 汇总所有图片（原始图片在前，PDF 页面在后）──
    all_images = existing_images + pdf_page_images
    # 去重（同名文件不重复）
    seen = set()
    unique_images = []
    for img in all_images:
        norm = os.path.normcase(os.path.abspath(img))
        if norm not in seen:
            seen.add(norm)
            unique_images.append(img)

    all_images = unique_images
    total = len(all_images)
    print(f"\n📊 共 {total} 张图片待分析（含 PDF 拆分页）")

    if total == 0:
        print("⚠️  文件夹中没有找到任何图片或 PDF，退出。")
        return {}

    # ── Step 4: 初始化 Gemini 客户端 + 凭证池（支持 API/Vertex 自动轮换）──
    pool   = gemini_client.CredentialPool(use_vertex=True)
    client = pool.make_client()
    chat   = gemini_client.create_chat(client, model=model)
    print(f"   凭证池: {pool.summary()}")

    # ── Step 5: 分批分析 ──
    total_batches = math.ceil(total / BATCH_SIZE)
    print(f"\n🔍 开始分批分析（共 {total_batches} 批，每批 ≤{BATCH_SIZE} 张）…\n")

    all_image_results = []
    batch_failures    = 0   # 累计失败批次数

    for batch_idx in range(total_batches):
        batch_files = all_images[batch_idx * BATCH_SIZE : (batch_idx + 1) * BATCH_SIZE]
        start_num   = batch_idx * BATCH_SIZE + 1
        end_num     = start_num + len(batch_files) - 1

        print(f"📦 第 {batch_idx+1}/{total_batches} 批：图片 {start_num}~{end_num}")

        # 构建消息 parts
        parts = []
        for fp in batch_files:
            try:
                img_bytes, mime = gemini_client.compress_image(fp, max_side=MAX_SIDE_PIXELS)
                parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
            except Exception as ex:
                print(f"   ⚠️  无法读取图片 {os.path.basename(fp)}: {ex}")

        parts.append(types.Part.from_text(
            text=_build_batch_prompt(batch_files, batch_idx, total_batches, start_num)
        ))

        response = gemini_client.safe_send(
            chat, parts, timeout=120, 
            retries=len(pool) * 2,
            pool=pool, model=model
        )

        if not response:
            print(f"   ⚠️  第 {batch_idx+1} 批分析失败（全部重试耗尽）")
            for i, fp in enumerate(batch_files):
                all_image_results.append({
                    "index":       start_num + i,
                    "file":        os.path.basename(fp),
                    "full_path":   fp,
                    "useful":      True,
                    "category":    "其他有效信息",
                    "description": "（分析失败，需人工确认）"
                })
            batch_failures += 1
            continue

        result = extract_json(response.text)
        if result and "images" in result:
            for img_data in result["images"]:
                idx = img_data.get("index", start_num)
                # 将实际文件路径补充进去（Gemini 返回的是文件名）
                local_idx = idx - start_num
                if 0 <= local_idx < len(batch_files):
                    img_data["full_path"] = batch_files[local_idx]
                    img_data["file"]      = os.path.basename(batch_files[local_idx])
                all_image_results.append(img_data)
            useful_cnt  = sum(1 for r in result["images"] if r.get("useful"))
            useless_cnt = len(result["images"]) - useful_cnt
            print(f"   ✅ 有效: {useful_cnt} 张  |  过滤: {useless_cnt} 张")
        else:
            print(f"   ⚠️  第 {batch_idx+1} 批 JSON 解析失败，原始回复:")
            print(f"   {response.text[:300]}…")
            for i, fp in enumerate(batch_files):
                all_image_results.append({
                    "index":       start_num + i,
                    "file":        os.path.basename(fp),
                    "full_path":   fp,
                    "useful":      True,
                    "category":    "其他有效信息",
                    "description": "（解析失败，需人工确认）"
                })
            batch_failures += 1

    # ── Step 6: 生成整体摘要 ──
    useful_images = [r for r in all_image_results if r.get("useful")]
    print(f"\n📝 共 {len(useful_images)} 张有效图片，正在生成整体产品摘要…")

    product_summary = {}
    if useful_images:
        summary_parts = [types.Part.from_text(text=_build_summary_prompt(useful_images))]
        summary_resp  = gemini_client.safe_send(
            chat, summary_parts, timeout=120, 
            retries=len(pool) * 2,
            pool=pool, model=model
        )
        if summary_resp:
            product_summary = extract_json(summary_resp.text) or {}
        if not product_summary:
            print("⚠️  摘要生成失败，跳过")

    # ── Step 7: 组装结果并保存 ──
    # 失败批次数过多（超过 50%）视为分析不可用
    analysis_ok = (batch_failures == 0) or (batch_failures <= total_batches // 2)
    result = {
        "folder":          folder_path,
        "total_images":    total,
        "useful_count":    len(useful_images),
        "filtered_count":  total - len(useful_images),
        "batch_failures":  batch_failures,
        "total_batches":   total_batches,
        "product_summary": product_summary,
        "images":          all_image_results,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if analysis_ok:
        print(f"\n✅ 分析完成（失败 {batch_failures}/{total_batches} 批）！结果已保存: {output_file}")
    else:
        print(f"\n❌ 分析失败率过高（{batch_failures}/{total_batches} 批失败），结果已保存: {output_file}")
        print("   请检查网络或 API Key 配额后重试")
    _print_summary(result)
    return result


# ==========================================
# 结果打印
# ==========================================

def _print_summary(result: dict):
    summary = result.get("product_summary", {})
    images  = result.get("images", [])

    print("\n" + "=" * 60)
    print("📦 产品摘要")
    print("=" * 60)
    if summary:
        print(f"  名称:     {summary.get('product_name_cn', '—')} / {summary.get('product_name_en', '—')}")
        print(f"  类型:     {summary.get('product_type', '—')}")
        print(f"  核心功能: {summary.get('core_function', '—')}")
        features = summary.get("key_features", [])
        if features:
            print(f"  主要特点: ({len(features)} 项)")
            for f in features[:8]:
                print(f"    · {f}")
            if len(features) > 8:
                print(f"    · …共 {len(features)} 项，详见 analysis_result.json")
    else:
        print("  （摘要不可用）")

    print("\n" + "=" * 60)
    print("🖼  图片分析清单")
    print("=" * 60)
    for img in images:
        status = "✅" if img.get("useful") else "🗑 "
        cat    = img.get("category") or "—"
        desc   = img.get("description", "")[:60]
        print(f"  {status} [{cat}] {img['file']}")
        if img.get("useful") and desc:
            print(f"       {desc}")
    print()


# ==========================================
# CLI 入口
# ==========================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="分析文件夹中的 PDF 和图片，生成产品分析报告"
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=None,
        help="要分析的文件夹路径（不填则交互式输入）"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini 模型 ID（默认: {DEFAULT_MODEL}）"
    )
    args = parser.parse_args()

    folder = args.folder
    if not folder:
        folder = input("请输入要分析的文件夹路径（默认 my_work_files）: ").strip()
        if not folder:
            folder = "my_work_files"

    # 如果没有通过命令行指定 model，交互式选择
    model = args.model
    if model == DEFAULT_MODEL and not any(a.startswith("--model") for a in sys.argv[1:]):
        model = gemini_client.select_model()

    try:
        analyze_folder(
            folder_path=folder,
            model=model,
        )
    except KeyboardInterrupt:
        print("\n\n🛑 已中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        sys.exit(1)

