import os
import sys
import re
import json
import math
import threading
from google.genai import types
import kb_manager
import product_manager
import gemini_client
import analyze_pdf
import listing_prompt_config

# ==========================================
# SOP 资产加载
# ==========================================
def load_sop_assets():
    """启动时加载标题库和关键词组，文件不存在或为空时自动降级"""
    title_lib = ""
    keywords = ""

    try:
        with open("assets/title_library.txt", "r", encoding="utf-8") as f:
            title_lib = f.read()
        real_lines = [l for l in title_lib.splitlines() if l.strip() and not l.strip().startswith('#')]
        if real_lines:
            print(f"📚 标题库已加载: {len(real_lines)} 条参考标题")
        else:
            print("⚠️  标题库文件存在但内容为空，将由 Gemini 基于产品分析自主生成标题")
    except FileNotFoundError:
        print("⚠️  标题库未找到 (assets/title_library.txt)，将由 Gemini 基于产品分析自主生成标题")

    try:
        with open("assets/keywords_food_machine.txt", "r", encoding="utf-8") as f:
            keywords = f.read()
        real_kws = [l for l in keywords.splitlines() if l.strip() and not l.strip().startswith('#')]
        if real_kws:
            print(f"🔑 关键词库已加载: {len(real_kws)} 个关键词")
        else:
            print("⚠️  关键词文件存在但内容为空，将由 Gemini 从 PDF 中提取关键词")
    except FileNotFoundError:
        print("⚠️  关键词库未找到 (assets/keywords_food_machine.txt)，将由 Gemini 从 PDF 中提取关键词")

    return title_lib, keywords


# ==========================================
# Prompt 构造
# ==========================================
def build_analysis_prompt(title_library, keywords):
    """构造产品分析首次提示词（结构化 JSON 输出）"""

    # 根据标题库和关键词是否存在，动态生成对应的指引段落
    title_count = len([l for l in title_library.splitlines() if l.strip() and not l.strip().startswith('#')])
    keyword_count = len([l for l in keywords.splitlines() if l.strip() and not l.strip().startswith('#')])

    if title_count >= 5:
        title_section = f"""3. A title reference library — {title_count} raw titles scraped from \
top-performing Alibaba International listings (one per line). Study their style, keyword \
density, sentence rhythm, and structure carefully. Use them as your primary style guide."""
        title_guidance = """- Learn rhythm and structure from the reference library titles
- Match the keyword density and natural flow of the best examples in the library"""
    elif title_count > 0:
        title_section = f"""3. A title reference library — only {title_count} reference title(s) available. \
Treat them as weak style hints only."""
        title_guidance = """- Only {title_count} reference titles available — treat as weak hints
- Apply Alibaba International SEO best practices directly from your own knowledge:
  · Front-load the most important product keyword in the first 30 characters
  · Use the pattern: [Modifier] + [Core Product Name] + [Key Spec/Feature] + [Application/Certification]
  · Avoid filler words (for, and, of, the) unless they add SEO or readability value
  · Study top-ranking food machinery listings on alibaba.com for this product category""".format(title_count=title_count)
    else:
        title_section = """3. Title reference library — NOT PROVIDED. You must generate titles \
purely from your expert knowledge of Alibaba International."""
        title_guidance = """- No reference titles provided — apply full Alibaba International SEO expertise:
  · Front-load the primary search keyword buyers would type (e.g. "Commercial Tray Sealer")
  · Follow this proven pattern: [Volume/Spec] + [Core Product Name] + [Key Differentiator] + [Target Use/Cert]
  · Use high-search-volume terms you know from the food machinery export category
  · Prioritize terms that global B2B buyers actually search: "commercial", "industrial", \
"stainless steel", "CE certified", "automatic", capacity specs (e.g. "500 cups/hour")
  · Avoid Chinese brand names, model numbers, or internal jargon buyers won't search"""

    if keyword_count >= 3:
        keyword_section = f"""4. A keyword list — {keyword_count} raw keywords from this category \
(one per line). Select and embed the most relevant ones naturally into titles and selling points."""
        keyword_guidance = "- Select the highest-relevance keywords from the provided list and embed naturally"
    else:
        keyword_section = """4. Keyword list — NOT PROVIDED or insufficient. \
Derive keywords from the PDF content and your knowledge of this product category on Alibaba."""
        keyword_guidance = """- No keyword list provided — extract your own from the PDF analysis:
  · Identify what buyers search when looking for this exact product type
  · Include: product function words, material specs, capacity/power specs, \
certifications (CE/ISO), and application industry terms"""

    return f"""You are an experienced Alibaba International (alibaba.com) store operator \
specializing in food machinery export. You have deep expertise in B2B export marketing, \
international buyer psychology, and Alibaba search SEO optimization.

I will provide you with:
1. A PDF file — 1688.com product listing (in Chinese). It contains product images embedded.
2. Several product reference photos sourced from 1688.com listings.
   ⚠️ IMPORTANT: These photos may contain Chinese text, company logos, watermarks, or Chinese
   branding overlays. Focus ONLY on the product's physical shape, structure, materials, components,
   and functional details. Completely ignore any text, logos, or watermarks in the photos.
{title_section}
{keyword_section}

---
[TITLE REFERENCE LIBRARY]
{title_library if title_library.strip() else "(none provided)"}

---
[KEYWORD LIST]
{keywords if keywords.strip() else "(none provided)"}

---

## STEP 1 — Discover 5 unique listing angles from the product itself

Read the PDF and photos carefully. Based on what THIS product actually is, identify 5 \
distinct buyer angles that would each appeal to a different type of international buyer \
or use scenario. Do NOT use preset angles — derive them from the product's real features, \
certifications, use cases, and target industries.

For each angle, generate one complete product listing in Amazon-style:

TITLE rules:
- Exactly 100-108 English characters (count every character including spaces)
{title_guidance}
{keyword_guidance}

SELLING POINTS rules (Amazon bullet-point style):
- Exactly 5 bullet points per listing
- Each bullet: ALL-CAPS short label (3-6 words) + colon + detailed benefit sentence
- Format: "LABEL: Detailed explanation of the benefit, how it works, and why it matters \
to the buyer. Include specific numbers/specs where possible."
- Each bullet 150-220 characters total
- Focus on buyer benefits, not just features
- Example style:
  "AUTO HEIGHT DETECTION: No manual adjustments needed. The built-in sensor automatically \
detects cup height, ensuring perfect alignment and sealing every time."

## STEP 2 — Deep feature extraction with PDF image mapping

Analyze every visual and textual feature in the PDF and photos. For each distinct \
product feature, identify which image(s) in the PDF best illustrate it \
(use rough descriptions like "the image showing the control panel" or \
"the close-up of the sealing head" — you cannot export PDF images directly, \
but describe them so we can match them to the reference photos provided).

## OUTPUT FORMAT

Return ONLY valid JSON, no markdown fences, no extra text:

{{
  "product_name_en": "English product name (3-6 words, professional)",
  "product_name_cn": "中文产品名",
  "listings": [
    {{
      "id": 1,
      "angle": "short angle label derived from product analysis",
      "angle_rationale": "1-sentence explanation of why this angle matters for this product",
      "title": "100-108 char title with keywords naturally embedded",
      "selling_points": [
        "LABEL ONE: Detailed benefit sentence with specific value to buyer, 150-220 chars total.",
        "LABEL TWO: ...",
        "LABEL THREE: ...",
        "LABEL FOUR: ...",
        "LABEL FIVE: ..."
      ],
      "scenario_tag": "describe the buyer type or use environment, e.g. milk-tea-shop"
    }}
  ],
  "features": [
    {{
      "id": "F1",
      "cn": "中文特点描述（简短）",
      "en": "English feature description (concise)",
      "category": "function | material | spec | certification | usage",
      "image_value": "high | medium | low",
      "pdf_page": 3
    }}
  ]
}}

STRICT RULES:
- listings: exactly 5 items, each angle must be genuinely different and product-specific
- title: count characters precisely — must be 100-108
- selling_points: exactly 5 per listing, ALL-CAPS label format required
- features: BE EXHAUSTIVE — extract EVERY distinct feature visible in images AND text.
  Include: materials, dimensions, power specs, capacity, motor type, blade/nozzle details,
  control panel elements, safety features, certifications, cleaning methods, noise level,
  adjustable parameters, accessories included, packaging details, warranty info, etc.
  MINIMUM 15 features required. Target 20-30. Do NOT omit anything visible or mentioned.
- image_value: high = visually compelling and worth showing in generated image,
               medium = partial visual value, low = text/number spec only
- pdf_page: the PDF page number (1-indexed integer) where this feature is most clearly
  shown or described. Required for every feature with image_value=high or medium.
  If a feature spans multiple pages, pick the page with the clearest visual.
- Output ONLY the JSON object, nothing else
"""


def build_image_prompts_prompt(product_name):
    """
    构造图片 Prompt 生成指令。
    同时返回从 pdf_pages/ 加载的图片 Parts 列表，供发送给 Gemini 做视觉参考。
    返回: (prompt_text, pdf_image_parts, data)
    """
    data = product_manager.load_product(product_name)
    if not data:
        return None, [], None

    visual_features = [
        f for f in data.get("features", [])
        if f.get("image_value") in ("high", "medium")
    ]
    features_text = "\n".join(
        f"- [{f.get('id','?')} | {f.get('category','').upper()} | {f.get('image_value','')}] {f.get('en','')}"
        for f in visual_features
    )

    listings_text = "\n".join(
        f"Listing {l['id']}: angle=\"{l['angle']}\" scenario=\"{l['scenario_tag']}\"\n"
        f"  Title: {l['title']}\n"
        f"  First selling point: {l['selling_points'][0][:120]}..."
        for l in data.get("listings", [])
    )

    # 只加载有产品价值的 PDF 页面（已经过 analyze_pdf_pages 过滤）
    # 发送前压缩到 900px，存档高清图不受影响，避免 payload 过大导致 SSL 断开
    pdf_image_paths = load_useful_page_paths(product_name)

    pdf_image_parts = []
    for p in pdf_image_paths:
        try:
            img_bytes, mime = compress_image_for_api(p, max_side=900)
            pdf_image_parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
        except Exception:
            pass

    if pdf_image_paths:
        # 提取每张图对应的实际页码，告诉 Gemini 真实页码而非序号
        page_nums = []
        for p in pdf_image_paths:
            m = re.search(r'page_(\d+)', p)
            page_nums.append(int(m.group(1)) if m else 0)
        pages_label = ", ".join(f"img_{i+1}=page{n}" for i, n in enumerate(page_nums))
        valid_page_nums = [n for n in page_nums if n > 0]
        ref_block = (
            f"I am providing {len(pdf_image_paths)} product images from the PDF.\n"
            f"Each image's actual PDF page number: {pages_label}\n"
            f"IMPORTANT: For ref_img, return the ACTUAL PDF PAGE NUMBER from this list: "
            f"{valid_page_nums}. Do NOT return a sequential index. Use 0 if no reference needed."
        )
    else:
        ref_block = "No PDF images available. Generate prompts based on product description only."

    prompt = f"""You are a professional product photography art director and AI image prompt \
engineer for Alibaba International B2B listings.

Product: {data.get('product_name_en', '')}

{ref_block}

## Product visual features (high/medium image value):
{features_text}

## 5 Listing angles:
{listings_text}

## TASK
Generate exactly 25 image generation prompts: 5 listings × 5 image types.
For each listing, also output which PDF image index to use as reference for each type.

IMAGE TYPE DEFINITIONS — CRITICAL: types 1/3/5 use EDIT MODE (preserve machine):

1. scene  — EDIT MODE. Start with the reference image. Keep the machine body COMPLETELY \
   UNCHANGED (same shape, color, size, proportions, every physical detail). \
   Remove any Chinese text or logos from the machine surface. \
   Replace ONLY the background with a commercial environment matching the scenario_tag \
   (e.g. milk-tea-shop → busy drink counter with customers; factory → production floor). \
   Add a person naturally interacting with the machine. Photorealistic, 8K.

2. detail — CLOSE-UP MODE. Look at the reference image for this listing's most important \
   physical feature. Zoom into that specific part: sealing head, control dial, heating \
   element, blade, stainless steel surface, etc. Extreme macro photography, studio lighting, \
   white or gradient background. Do not show the full machine. 8K.

3. real   — EDIT MODE. Start with the reference image. Keep the machine EXACTLY as shown. \
   Remove Chinese text/logos from machine surface. Replace background with an authentic \
   factory/restaurant back-of-house environment, natural imperfect lighting. \
   No CGI studio feel. Photorealistic, 8K.

4. spec   — GENERATE (no reference needed). Pure white background, full product body visible \
   from 3/4 front angle, professional studio lighting. Add English measurement/spec label \
   arrows pointing to key parts (dimensions, power, capacity, material). Technical style, 8K.

5. packaging — EDIT MODE. Start with the reference image. Keep the machine EXACTLY as shown. \
   Place it inside a heavy-duty export carton or wooden crate with foam padding visible \
   around it. Add a "FRAGILE" sticker and packing list label in English. \
   Warehouse or logistics dock background. 8K.

ABSOLUTE RULES FOR ALL 25 PROMPTS:
- 1:1 square aspect ratio
- For EDIT MODE types: machine shape, color, proportions, and ALL physical details are \
  FROZEN — only background, environment, and context change
- ALL visible text: ENGLISH ONLY — no Chinese characters, no Asian script anywhere
- No brand logos, watermarks, QR codes, or company names on machine or background
- Quality suffix for types 1/2/3/5: ", 1:1 square aspect ratio, photorealistic, 8K, \
  English text only, no Chinese text, no watermarks, no logos, no QR codes"
- spec suffix: ", 1:1 square aspect ratio, pure white background, English dimension \
  annotation arrows, technical diagram, 8K, no watermark, no Chinese text"

OUTPUT FORMAT — return ONLY valid JSON, no markdown:
{{
  "product_name_en": "{data.get('product_name_en', '')}",
  "image_prompts": [
    {{
      "listing_id": 1,
      "angle": "...",
      "scenario_tag": "...",
      "scene": [
        {{"prompt": "full English prompt v1...", "cn": "中文摘要1", "ref_img": 2, "focus": "morning rush in milk tea shop"}},
        {{"prompt": "full English prompt v2...", "cn": "中文摘要2", "ref_img": 3, "focus": "single operator close-up"}},
        {{"prompt": "full English prompt v3...", "cn": "中文摘要3", "ref_img": 2, "focus": "sealed containers output"}},
        {{"prompt": "full English prompt v4...", "cn": "中文摘要4", "ref_img": 4, "focus": "wide shot of the full workstation"}},
        {{"prompt": "full English prompt v5...", "cn": "中文摘要5", "ref_img": 2, "focus": "evening busy service"}}
      ],
      "detail": [
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 5, "feature_id": "F1", "focus": "sealing head mechanism"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 6, "feature_id": "F2", "focus": "temperature control dial"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 7, "feature_id": "F3", "focus": "stainless steel body texture"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 5, "feature_id": "F4", "focus": "pressure adjustment"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 8, "feature_id": "F5", "focus": "food-grade material surface"}}
      ],
      "real": [
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 2, "focus": "front 45-degree angle"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 3, "focus": "top-down view"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 2, "focus": "side profile view"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 4, "focus": "operator hand detail"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 2, "focus": "product-in-environment immersion"}}
      ],
      "spec": [
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 0, "focus": "overall dimensions"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 0, "focus": "power and electrical specs"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 0, "focus": "material and certification labels"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 0, "focus": "capacity and speed specs"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 0, "focus": "accessories and components"}}
      ],
      "packaging": [
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 2, "focus": "machine in wooden export crate"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 2, "focus": "foam padding visible around machine"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 3, "focus": "multiple units stacked for shipping"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 2, "focus": "FRAGILE label and packing list"}},
        {{"prompt": "...", "cn": "中文摘要", "ref_img": 2, "focus": "open box reveal shot"}}
      ]
    }}
  ]
}}

RULES:
- Generate all 5 listing entries (listing_id 1-5).
- Each type has EXACTLY 5 variations — 5 prompts per type per listing = 25 prompts per listing = 125 total.
- detail variations: each must focus on a DIFFERENT product feature from the features list above.
  Use the feature's pdf_page as ref_img if available. feature_id must match the feature list.
- scene variations: 5 genuinely different scenarios/moments in the same environment type.
- real/packaging variations: 5 different angles or compositions.
- spec variations: 5 different spec groupings (dimensions / power / material / capacity / accessories).
- ref_img = 0 for spec type (pure white background, no reference needed).
- ref_img = valid page number from the provided useful PDF pages for all other types.
- cn: one Chinese sentence summarizing what this specific image will show.
- Every prompt must be fully self-contained and visually distinct from all others.
"""
    return prompt, pdf_image_parts, data


# ==========================================
# 工具函数
# ==========================================


def get_pdf_page(product_name, page_num):
    """
    按实际页码取已渲染的 PDF 页面图路径（1-based）。
    会过滤 index.json 中 useful=false 的页，返回 None 表示不可用。
    """
    if not page_num or page_num < 1:
        return None
    path = os.path.join(
        product_manager.get_product_dir(product_name),
        "pdf_pages", f"page_{page_num:03d}.png"
    )
    if not os.path.exists(path):
        return None
    # 检查 index.json，过滤掉无意义的页
    index_path = os.path.join(
        product_manager.get_product_dir(product_name), "pdf_pages", "index.json"
    )
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            idx = json.load(f)
        page_info = {p["page"]: p for p in idx.get("pages", [])}
        if page_num in page_info and not page_info[page_num].get("useful", True):
            return None   # 明确标记为无价值，不使用
    return path


def analyze_pdf_pages(product_name, page_paths, chat):
    """
    把所有 PDF 页面图发给 Gemini，判断每页是否有产品价值。
    结果存为 pdf_pages/index.json，后续只把有价值的页发给生图 Prompt 生成。
    返回 {page_num: info_dict} 字典。
    """
    if not page_paths:
        return {}

    BATCH_SIZE = 7   # 每批最多 7 张，无论 PDF 有多少页都不会超限
    total = len(page_paths)
    total_batches = math.ceil(total / BATCH_SIZE)
    print(f"\n🔍 正在分析 {total} 张 PDF 页面（共 {total_batches} 批，每批最多 {BATCH_SIZE} 张）…")

    all_page_results = []

    for batch_idx in range(total_batches):
        batch_paths = page_paths[batch_idx * BATCH_SIZE: (batch_idx + 1) * BATCH_SIZE]
        start_page = batch_idx * BATCH_SIZE + 1          # 本批第一页的全局页码
        end_page   = start_page + len(batch_paths) - 1
        print(f"   📦 第 {batch_idx+1}/{total_batches} 批：页 {start_page}~{end_page}")

        parts = []
        for p in batch_paths:
            try:
                img_bytes, mime = compress_image_for_api(p, max_side=800)
                parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
            except Exception:
                pass

        prompt = f"""I am providing pages {start_page} to {end_page} (batch {batch_idx+1}/{total_batches}) \
from a product PDF listing (1688.com). Total PDF pages: {total}.

Images are in order, corresponding to page numbers {start_page} through {end_page}.

For EACH page, determine if it contains product-relevant visual content useful for
generating product images (e.g. product appearance, structure, features, usage, materials,
certifications, specs, packaging).

Mark as useful=TRUE if the page contains ANY of: product photos, product structure/parts,
usage demonstrations, spec tables, feature descriptions, certifications, materials info,
dimension diagrams — even if it's mostly text, as long as it's about the product.

Mark as useful=FALSE ONLY if: company intro/history with no product, pure contact/address
page, decorative border page, QR code only page, blank page, footer/header only.

Return ONLY valid JSON — page numbers must match the actual page numbers ({start_page}-{end_page}):
{{
  "pages": [
    {{
      "page": {start_page},
      "useful": false,
      "reason": "company logo and contact info only",
      "features_shown": [],
      "best_for": null
    }},
    {{
      "page": {start_page + 1},
      "useful": true,
      "reason": "shows sealing head close-up",
      "features_shown": ["sealing head", "heating element"],
      "best_for": "detail"
    }}
  ]
}}

best_for: scene / detail / real / spec / packaging / null
Analyze all {len(batch_paths)} pages in this batch. Be strict."""

        parts.append(types.Part.from_text(text=prompt))
        response = safe_send_message(chat, parts, timeout=120, retries=2)
        if not response:
            print(f"   ⚠️  第 {batch_idx+1} 批分析失败，该批页面将视为全部有效")
            for i, _ in enumerate(batch_paths):
                all_page_results.append({"page": start_page + i, "useful": True,
                                         "reason": "analysis failed, assumed useful",
                                         "features_shown": [], "best_for": None})
            continue

        result = extract_json(response.text)
        if result and "pages" in result:
            all_page_results.extend(result["pages"])
        else:
            print(f"   ⚠️  第 {batch_idx+1} 批解析失败，该批视为全部有效")
            for i, _ in enumerate(batch_paths):
                all_page_results.append({"page": start_page + i, "useful": True,
                                         "reason": "parse failed, assumed useful",
                                         "features_shown": [], "best_for": None})

    # 合并并保存 index.json
    merged = {"pages": all_page_results}
    index_path = os.path.join(
        product_manager.get_product_dir(product_name), "pdf_pages", "index.json"
    )
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    useful  = [p for p in all_page_results if p.get("useful")]
    useless = [p for p in all_page_results if not p.get("useful")]
    print(f"   ✅ 有价值页面: {len(useful)} 张  |  过滤掉: {len(useless)} 张")
    if useless:
        print(f"   🗑  过滤页码: {[p['page'] for p in useless]}")

    return {p["page"]: p for p in all_page_results}


def load_useful_page_paths(product_name, max_pages=10):
    """
    读取 index.json，按优先级返回最有价值的页面路径（最多 max_pages 张）。
    优先级：① features.json 里 image_value=high 的 pdf_page → ② best_for 不为 null → ③ 其余 useful
    如果 index.json 不存在，返回前 max_pages 张页面作为兜底。
    """
    pages_dir = os.path.join(product_manager.get_product_dir(product_name), "pdf_pages")
    index_path = os.path.join(pages_dir, "index.json")

    def page_path(num):
        return os.path.join(pages_dir, f"page_{num:03d}.png")

    # index.json 不存在：返回前 max_pages 张
    if not os.path.exists(index_path):
        all_pages = sorted([
            os.path.join(pages_dir, f)
            for f in os.listdir(pages_dir)
            if f.startswith("page_") and f.endswith(".png")
        ]) if os.path.isdir(pages_dir) else []
        return all_pages[:max_pages]

    with open(index_path, encoding="utf-8") as f:
        idx = json.load(f)

    useful_pages = {p["page"]: p for p in idx.get("pages", []) if p.get("useful")}
    if not useful_pages:
        return []

    # 优先级 1：features.json 里 image_value=high 对应的页码
    priority_pages = set()
    features_path = os.path.join(product_manager.get_product_dir(product_name), "features.json")
    if os.path.exists(features_path):
        with open(features_path, encoding="utf-8") as f:
            feat_data = json.load(f)
        for feat in feat_data.get("features", []):
            if feat.get("image_value") == "high" and feat.get("pdf_page"):
                priority_pages.add(feat["pdf_page"])

    # 优先级 2：best_for 不为 null 的页
    best_for_pages = {n for n, p in useful_pages.items() if p.get("best_for")}

    # 按优先级拼接，去重，限制数量
    ordered = []
    for num in sorted(priority_pages):
        if num in useful_pages and num not in ordered:
            ordered.append(num)
    for num in sorted(best_for_pages):
        if num not in ordered:
            ordered.append(num)
    for num in sorted(useful_pages.keys()):
        if num not in ordered:
            ordered.append(num)

    selected = ordered[:max_pages]
    result = [page_path(n) for n in selected if os.path.exists(page_path(n))]
    print(f"   📄 发送 {len(result)} 张参考页（共 {len(useful_pages)} 张有价值，优先高价值特点对应页）")
    return result


# 图片压缩 — 统一使用 gemini_client 中的实现
compress_image_for_api = gemini_client.compress_image


def scan_target_folder(folder_path, processed_files_set):
    parts = []
    image_paths = []
    if not folder_path or not os.path.exists(folder_path):
        return parts, image_paths
    for file_name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file_name)
        if os.path.isfile(file_path) and file_path not in processed_files_set:
            try:
                mime_type = gemini_client._guess_mime(file_path)
                with open(file_path, "rb") as f:
                    parts.append(types.Part.from_bytes(data=f.read(), mime_type=mime_type))
                if mime_type.startswith("image/"):
                    image_paths.append(file_path)
                processed_files_set.add(file_path)
                print(f"📦 已自动捕获新文件: {file_name}")
            except Exception as e:
                print(f"❌ 读取文件 {file_name} 失败: {e}")
    return parts, image_paths


def timed_input(prompt_text, timeout=10, default='y'):
    """带倒计时的输入，timeout 秒内无操作自动返回 default。"""
    result = [None]
    done = threading.Event()

    def _reader():
        try:
            result[0] = input('')
        except Exception:
            pass
        done.set()

    sys.stdout.write(prompt_text)
    sys.stdout.flush()
    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    for remaining in range(timeout, 0, -1):
        if done.wait(1.0):
            val = (result[0] or '').strip().lower()
            return val if val else default
        sys.stdout.write(f'\r{prompt_text}[{remaining-1}s 后自动生成] ')
        sys.stdout.flush()

    sys.stdout.write(f'\r{prompt_text}-> 自动: {default}\n')
    sys.stdout.flush()
    return default


def load_gen_progress(product_name):
    """读取生图进度，返回已完成的 key 集合。"""
    path = os.path.join(product_manager.get_product_dir(product_name), "generation_progress.json")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return set(json.load(f).get("completed", []))


def save_gen_progress(product_name, completed):
    """保存生图进度（每张图成功后立即调用）。"""
    path = os.path.join(product_manager.get_product_dir(product_name), "generation_progress.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"completed": sorted(completed)}, f, indent=2)


# 消息发送 — 统一使用 gemini_client 中的实现
safe_send_message = gemini_client.safe_send


def extract_json(text):
    """从 Gemini 回复中提取 JSON（处理可能的 markdown 包裹）"""
    # 去掉 ```json ... ``` 包裹
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    # 找第一个 { 到最后一个 }
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end+1])
    except json.JSONDecodeError:
        return None


def print_help():
    print("""
💡 【指令秘籍】:
  直接打字          正常对话（放入新文件会自动附带发送）

  ── SOP 产品分析（推荐顺序） ──
  Step 0  python analyze_pdf.py my_work_files
                     独立运行：PDF拆分+图片分析 → 生成 analysis_result.json
  /listings 产品名   基于 analysis_result.json 生成5组标题+卖点
                     → 5个角度覆盖不同客群/关键词簇，保存 listings.json
                     ✏️  如需调整生成策略，直接编辑 listing_prompt_config.py
  /prompts  产品名   基于分析数据生成 125 个图片Prompt (5组×5类型×5变体)
                     图类型: scene / detail / real / spec / packaging
  /images   产品名   批量生成 125 张图片（图生图，spec类型纯文生图，断点续跑）
  /analyze  产品名   （旧流程）综合分析 my_work_files/ 中的 PDF+图片
  /products          列出所有产品及当前进度

  ── 知识库 ──
  /list              查看知识库所有标签
  /find 关键词       模糊搜索知识库
  /save 标签名       保存内容到知识库
  /use 标签名 问题   带着知识库内容提问

  exit               退出程序
""")


# ==========================================
# SOP 指令处理函数
# ==========================================
def handle_analyze(product_name, chat, watch_folder, processed_files,
                   title_library, keywords, current_ref_images):
    """
    /analyze 产品名
    扫描文件夹 → 构造分析Prompt → 发给 Gemini → 解析JSON → 保存
    """
    print(f"\n🔍 开始分析产品: {product_name}")

    # ── 重复检测 ──────────────────────────────────────────────
    existing = product_manager.load_product(product_name)
    if existing:
        print(f"⚠️  产品 [{product_name}] 已有分析数据：")
        print(f"   英文名: {existing.get('product_name_en', '—')}")
        print(f"   特点数: {len(existing.get('features', []))} 条")
        print(f"   标题组: {len(existing.get('listings', []))} 组")
        choice = input("   [o] 重新分析并覆盖  /  [s] 跳过（保留现有数据）: ").strip().lower()
        if choice != 'o':
            print("✅ 已保留现有数据，跳过分析。")
            return

    # 扫描文件夹（包含PDF和图片）
    new_parts, new_image_paths = scan_target_folder(watch_folder, processed_files)
    current_ref_images.extend(new_image_paths)

    if not new_parts:
        print("⚠️  my_work_files/ 中没有新文件，请先把PDF和产品图放进去。")
        return

    analysis_prompt = build_analysis_prompt(title_library, keywords)
    message_parts = new_parts + [types.Part.from_text(text=analysis_prompt)]

    print("📤 正在发送分析请求（含PDF和图片），请稍等…")
    response = safe_send_message(chat, message_parts, timeout=180, retries=1)
    if not response:
        return

    data = extract_json(response.text)
    if not data:
        print("❌ Gemini 返回内容解析失败，原始回复如下：")
        print(response.text[:2000])
        return

    # 保存结果
    product_dir = product_manager.save_product_analysis(
        product_name, data, ref_images=current_ref_images
    )

    # 提取 PDF 内嵌图片（作为后续生图的精准参考图）
    pdf_files = [
        os.path.join(watch_folder, fn)
        for fn in os.listdir(watch_folder)
        if fn.lower().endswith('.pdf') and os.path.isfile(os.path.join(watch_folder, fn))
    ]
    if pdf_files:
        print(f"\n📄 正在渲染 PDF 页面（用于后续精准参考图）…")
        pdf_pages_dir = os.path.join(product_dir, "pdf_pages")
        page_paths = analyze_pdf.split_pdf(pdf_files[0], output_dir=pdf_pages_dir)
        if page_paths:
            analyze_pdf_pages(product_name, page_paths, chat)
    else:
        print("⚠️  未在 my_work_files/ 中找到 PDF，跳过图片提取")

    # 打印摘要
    print(f"\n✅ 分析完成！数据已保存至: {product_dir}")
    print(f"   产品英文名: {data.get('product_name_en', '—')}")
    print(f"   产品中文名: {data.get('product_name_cn', '—')}")
    print(f"   生成标题组: {len(data.get('listings', []))} 组")
    print(f"   产品特点数: {len(data.get('features', []))} 条")

    print("\n📋 5组标题+卖点预览：")
    for lst in data.get("listings", []):
        title = lst.get("title", "")
        char_count = len(title)
        angle = lst.get("angle", "")
        rationale = lst.get("angle_rationale", "")
        print(f"\n  [{lst['id']}] 角度: {angle} | {char_count} 字符")
        if rationale:
            print(f"       定位: {rationale}")
        print(f"       标题: {title}")
        for i, sp in enumerate(lst.get("selling_points", []), 1):
            print(f"       卖点{i}: {sp[:100]}…")

    high_feat = [f for f in data.get('features', []) if f.get('image_value') == 'high']
    print(f"\n📌 高图像价值特点 ({len(high_feat)} 条):")
    for f in high_feat:
        hint = f.get("pdf_image_hint", "")
        print(f"   [{f['id']}] {f['en']}")
        if hint:
            print(f"        PDF图: {hint[:80]}")
    print("\n💡 下一步: /prompts " + product_name)


def handle_gen_listings(product_name, chat, title_library="", keywords="",
                        work_folder="my_work_files"):
    """
    /listings 产品名
    读取 analyze_pdf 产出的 analysis_result.json → 构建标题/卖点Prompt
    → 发给 Gemini → 解析 → 保存 listings.json

    标题生成逻辑完全由 listing_prompt_config.py 控制，可直接编辑那个文件调整策略。
    """
    print(f"\n📝 生成5组标题+卖点: {product_name}")

    # ── 读取 analysis_result.json（analyze_pdf 的输出）──
    analysis_path = os.path.join(work_folder, "analysis_result.json")
    product_summary = {}
    if os.path.exists(analysis_path):
        with open(analysis_path, encoding="utf-8") as f:
            ar = json.load(f)
        product_summary = ar.get("product_summary", {})
        print(f"   📂 已加载: {analysis_path}")
        print(f"   产品: {product_summary.get('product_name_en', '—')} | "
              f"特点: {len(product_summary.get('key_features', []))} 条")
    else:
        print(f"⚠️  未找到 {analysis_path}，请先运行 analyze_pdf.py")
        print(f"   将仅凭关键词库生成，效果可能较差。")

    # ── 构建 Prompt ──
    prompt_text = listing_prompt_config.build_listing_prompt(
        product_summary=product_summary,
        title_library=title_library,
        keywords=keywords,
    )

    print("📤 正在请求 Gemini 生成5组标题+卖点…")
    response = safe_send_message(
        chat,
        [types.Part.from_text(text=prompt_text)],
        timeout=180,
        retries=2
    )
    if not response:
        return

    data = extract_json(response.text)
    if not data or "listings" not in data:
        print("❌ 解析失败，原始回复：")
        print(response.text[:2000])
        return

    # ── 保存到 products/[name]/listings.json ──
    product_dir = product_manager.get_product_dir(product_name)
    os.makedirs(product_dir, exist_ok=True)
    listings_path = os.path.join(product_dir, "listings.json")
    with open(listings_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 5组标题+卖点已保存: {listings_path}")

    # ── 打印预览 ──
    print(f"\n{'='*60}")
    print(f"产品: {data.get('product_name_en', '—')}")
    print(f"{'='*60}")
    for lst in data.get("listings", []):
        title      = lst.get("title", "")
        char_count = lst.get("title_char_count", len(title))
        angle      = lst.get("angle", "")
        rationale  = lst.get("angle_rationale", "")
        kw_focus   = ", ".join(lst.get("keyword_focus", []))
        print(f"\n  [{lst['id']}] {angle}  ({char_count} 字符)")
        if rationale:
            print(f"       定位: {rationale}")
        if kw_focus:
            print(f"       关键词: {kw_focus}")
        print(f"       标题: {title}")
        for i, sp in enumerate(lst.get("selling_points", []), 1):
            print(f"       卖点{i}: {sp[:110]}{'…' if len(sp)>110 else ''}")

    print(f"\n💡 下一步: /prompts {product_name}")


def handle_gen_prompts(product_name, chat):
    """
    /prompts 产品名
    读取 features.json + pdf_images → 发给 Gemini → 解析 → 保存 image_prompts.json
    """
    print(f"\n🎨 生成图片Prompt: {product_name}")

    prompt_text, pdf_image_parts, _ = build_image_prompts_prompt(product_name)
    if not prompt_text:
        print(f"❌ 找不到产品 [{product_name}] 的分析数据，请先执行 /analyze {product_name}")
        return

    if pdf_image_parts:
        print(f"📸 附带 {len(pdf_image_parts)} 张 PDF 提取图片发给 Gemini…")
    print("📤 正在请求 Gemini 生成25个图片Prompt…")

    message_parts = pdf_image_parts + [types.Part.from_text(text=prompt_text)]
    response = safe_send_message(chat, message_parts, timeout=300, retries=3)
    if not response:
        return

    prompts_data = extract_json(response.text)
    if not prompts_data:
        print("❌ Prompt 数据解析失败，原始回复：")
        print(response.text[:2000])
        return

    save_path = product_manager.save_image_prompts(product_name, prompts_data)
    print(f"\n✅ 25个图片Prompt已保存: {save_path}")

    IMAGE_TYPES = ["scene", "detail", "spec", "packaging", "real"]
    for item in prompts_data.get("image_prompts", []):
        print(f"\n  Listing {item['listing_id']} ({item['angle']}) - {item['scenario_tag']}:")
        for img_type in IMAGE_TYPES:
            preview = item.get(img_type, "")[:80]
            print(f"    [{img_type}] {preview}…")

    print("\n💡 下一步: /images " + product_name)


def handle_gen_images(product_name, use_vertex, model_alias="banana2"):
    """
    /images 产品名 [模型]
    读取 image_prompts.json → 批量生图 → 存入 products/[name]/images/

    参考图策略（按优先级）：
      PDF提取图（精准匹配特点） > 手动下载图（通用外形兜底）> 无参考（spec专用）
    每个 listing 先全部生完（5类型×5张=25张），再进下一个 listing。
    可用模型别名：banana2 (flash) / pro (高质量)
    """
    from image_generator import generate_my_image

    prompts_data = product_manager.load_image_prompts(product_name)
    if not prompts_data:
        print(f"❌ 找不到 [{product_name}] 的图片Prompt，请先执行 /prompts {product_name}")
        return

    # PDF 页面渲染图（首选参考图）
    pdf_pages_dir = os.path.join(product_manager.get_product_dir(product_name), "pdf_pages")
    pdf_imgs_available = os.path.isdir(pdf_pages_dir) and bool(os.listdir(pdf_pages_dir))

    # 手动下载图（兜底）
    fallback_refs = product_manager.get_ref_images(product_name)
    if pdf_imgs_available:
        print(f"📸 将使用 PDF 提取图作为参考图（精准匹配特点）")
    elif fallback_refs:
        print(f"📷 未找到PDF提取图，使用手动下载图作为兜底参考（{len(fallback_refs)} 张）")
    else:
        print("⚠️  没有任何参考图，spec 以外将使用纯文生图")

    NO_REF_TYPES = {"spec"}
    IMAGE_TYPES  = ["scene", "detail", "real", "spec", "packaging"]
    TYPE_CN = {
        "scene": "场景图", "detail": "细节图",
        "real":  "实拍图", "spec":   "参数图", "packaging": "打包图"
    }

    # 续传进度
    completed = load_gen_progress(product_name)

    total = 0
    failed = 0
    skipped = 0
    stop_all = False
    image_prompts = prompts_data.get("image_prompts", [])
    total_expected = len(image_prompts) * len(IMAGE_TYPES) * 5

    print(f"\n🚀 准备生成 {len(image_prompts)} 组 × {len(IMAGE_TYPES)} 类型 × 5 变体 = {total_expected} 张")
    if completed:
        print(f"   ♻️  发现进度记录，已完成 {len(completed)} 张，将自动跳过")
    print("   确认方式: 回车/y=生成  n=跳过  q=停止所有  (10s 无操作自动生成)\n")

    for item in image_prompts:
        if stop_all:
            break

        listing_id = item["listing_id"]
        output_dir = product_manager.get_images_output_dir(product_name, listing_id)
        angle = item.get("angle", "")
        print(f"\n{'='*55}")
        print(f"🗂  Listing {listing_id} ({angle})")
        print(f"{'='*55}")

        for img_type in IMAGE_TYPES:
            if stop_all:
                break

            variations = item.get(img_type, [])
            # 兼容旧格式（单字符串）
            if isinstance(variations, str):
                variations = [{"prompt": variations, "cn": "", "ref_img": 0, "focus": ""}]

            for var_idx, var in enumerate(variations, 1):
                if stop_all:
                    break

                progress_key = f"L{listing_id}_{img_type}_v{var_idx}"

                # 续传：已完成的直接跳过
                if progress_key in completed:
                    print(f"   ⏭  已完成，跳过: {progress_key}")
                    total += 1
                    continue

                prompt     = var.get("prompt", "")
                cn_summary = var.get("cn", "")
                ref_page   = var.get("ref_img", 0)
                focus      = var.get("focus", "")
                if not prompt:
                    continue

                # 确定参考图
                if img_type in NO_REF_TYPES:
                    ref = None
                else:
                    ref = get_pdf_page(product_name, ref_page)
                    if not ref and fallback_refs:
                        ref = fallback_refs[(listing_id - 1) % len(fallback_refs)]

                # ── 人工确认（10s 无操作自动生成）────────
                ref_label = os.path.basename(ref) if ref else "无参考图（纯文生图）"
                print(f"\n{'─'*55}")
                print(f"  Listing {listing_id} / {TYPE_CN.get(img_type, img_type)} 变体{var_idx}/5")
                if focus:
                    print(f"  聚焦: {focus}")
                print(f"{'─'*55}")
                print(f"📝 {cn_summary}" if cn_summary else "📝 （无中文摘要，请重新运行 /prompts）")
                print(f"📎 参考图: {ref_label}")
                print(f"🔤 Prompt:")
                for chunk in [prompt[i:i+80] for i in range(0, len(prompt), 80)]:
                    print(f"   {chunk}")

                choice = timed_input("\n   ▶ 回车/y=生成  n=跳过  q=停止所有: ", timeout=10, default='y')

                if choice == 'q':
                    stop_all = True
                    print("🛑 已停止所有后续生成。")
                    break
                if choice == 'n':
                    print("   ⏭  已跳过。")
                    skipped += 1
                    continue

                print(f"\n🎨 生成中…")
                try:
                    saved = generate_my_image(
                        prompt=prompt,
                        model_alias=model_alias,
                        image_paths=ref,
                        num_images=1,
                        use_vertex=use_vertex,
                        output_dir=output_dir,
                        file_prefix=progress_key
                    )
                    if saved:
                        total += 1
                        completed.add(progress_key)
                        save_gen_progress(product_name, completed)
                        print(f"   ✅ 已保存: {os.path.basename(saved[0])}")
                    else:
                        failed += 1
                except Exception as e:
                    print(f"   ❌ 生成失败: {e}")
                    failed += 1

        print(f"\n✔  Listing {listing_id} 完成，累计成功 {total} / {total_expected} 张")

    print(f"\n{'='*55}")
    print(f"✅ 生成结束！成功 {total} 张 / 跳过 {skipped} 张 / 失败 {failed} 张")
    print(f"📂 输出目录: products/{product_name}/images/")


def handle_list_products():
    products = product_manager.list_products()
    if not products:
        print("📭 还没有任何产品，使用 /analyze 产品名 开始分析")
        return
    print(f"\n📦 已分析产品列表 ({len(products)} 个):")
    for p in products:
        status = []
        if p["has_analysis"]: status.append("✅分析完成")
        if p["has_prompts"]:  status.append("✅Prompt就绪")
        if p["image_count"]:  status.append(f"🖼 {p['image_count']}张图")
        print(f"  [{p['name']}]  {' | '.join(status) or '空'}")


# ==========================================
# 主程序
# ==========================================
def start_chat_session(watch_folder):
    print("🚀 初始化 Gemini 客户端…")
    client = gemini_client.create_client()

    # 从 .env 读取是否使用 Vertex 图生图
    use_vertex = os.getenv("USE_VERTEX_AI", "False").strip().lower() in ("true", "1", "yes")

    # 加载 SOP 资产
    title_library, keywords = load_sop_assets()
    print(f"📚 标题库: {len(title_library)} 字符 | 关键词库: {len(keywords)} 字符")

    # 模型选择（2 选 1）
    selected_model = gemini_client.select_model()
    chat = gemini_client.create_chat(client, model=selected_model, with_search=True)

    processed_files = set()
    current_ref_images = []   # 本次会话中捕获到的产品参考图
    os.makedirs(watch_folder, exist_ok=True)

    print(f"\n✨ 已开启全新会话 (模型: {selected_model}，联网已开启)")
    print(f"📂 监听文件夹: {os.path.abspath(watch_folder)}")
    print_help()

    last_bot_response = ""

    while True:
        user_input = input("\n🧑 你: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ['quit', 'exit']:
            print("🛑 拜拜！")
            break

        # ── SOP 指令 ──────────────────────────────
        if user_input.startswith("/analyze "):
            product_name = user_input.split(" ", 1)[1].strip()
            handle_analyze(product_name, chat, watch_folder, processed_files,
                           title_library, keywords, current_ref_images)
            continue

        if user_input.startswith("/listings "):
            product_name = user_input.split(" ", 1)[1].strip()
            handle_gen_listings(product_name, chat, title_library, keywords, watch_folder)
            continue

        if user_input.startswith("/prompts "):
            product_name = user_input.split(" ", 1)[1].strip()
            handle_gen_prompts(product_name, chat)
            continue

        if user_input.startswith("/images "):
            parts = user_input.split(" ", 2)
            product_name = parts[1].strip() if len(parts) > 1 else ""
            img_model = parts[2].strip() if len(parts) > 2 else "banana2"
            handle_gen_images(product_name, use_vertex, model_alias=img_model)
            continue

        if user_input == "/products":
            handle_list_products()
            continue

        # ── 知识库指令 ────────────────────────────
        if user_input.startswith("/list"):
            kb = kb_manager.load_kb()
            print("📚 知识库标签: " + (", ".join(kb.keys()) if kb else "空空如也"))
            continue

        if user_input.startswith("/find "):
            keyword = user_input.split(" ", 1)[1].strip()
            results = kb_manager.search_content(keyword)
            if results:
                print(f"🔍 找到 {len(results)} 条相关记录：")
                for topic in results.keys():
                    print(f"  - [{topic}]")
            else:
                print("⚠️ 没有找到相关内容。")
            continue

        if user_input.startswith("/save "):
            topic = user_input.split(" ", 1)[1].strip()
            existing = kb_manager.get_content(topic)
            mode = 'replace'
            if existing:
                print(f"⚠️ 已存在标签 [{topic}]。")
                choice = input("输入 'a' 追加，输入 'r' 覆盖 (默认 r): ").strip().lower()
                mode = 'append' if choice == 'a' else 'replace'
            print("👇 粘贴要保存的内容 (直接回车则保存上一条 Gemini 回复):")
            content = input("> ") or last_bot_response
            if content:
                kb_manager.save_content(topic, content, mode)
                print(f"💾 已{'追加' if mode == 'append' else '保存'}至 [{topic}]。")
            else:
                print("⚠️ 没有可保存的内容。")
            continue

        if user_input == "/help":
            print_help()
            continue

        # ── 普通对话 ──────────────────────────────
        message_parts = []

        if user_input.startswith("/use "):
            try:
                _, topic, prompt = user_input.split(" ", 2)
                content = kb_manager.get_content(topic)
                if content:
                    message_parts.append(f"【参考背景资料】：\n{content}\n\n【我的要求】：{prompt}")
                    print(f"🔗 已挂载知识库 [{topic}]")
                else:
                    print(f"⚠️ 找不到标签 [{topic}]")
                    continue
            except ValueError:
                print("⚠️ 格式: /use 标签名 你的问题")
                continue
        else:
            message_parts.append(user_input)

        new_parts, new_imgs = scan_target_folder(watch_folder, processed_files)
        current_ref_images.extend(new_imgs)
        message_parts = new_parts + message_parts

        response = safe_send_message(chat, message_parts, timeout=120, retries=1)
        if response:
            last_bot_response = response.text
            print(f"🤖 Gemini:\n{response.text}")
            if response.candidates and response.candidates[0].grounding_metadata:
                print("\n🌐 (此回答参考了 Google 实时搜索结果)")


if __name__ == "__main__":
    MY_WORK_FOLDER = "./my_work_files"
    start_chat_session(MY_WORK_FOLDER)
