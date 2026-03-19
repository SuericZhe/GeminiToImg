"""
listing_prompt_config.py
═══════════════════════════════════════════════════════════════════════
5组标题 + 卖点生成 Prompt 配置文件

修改这里的 LISTING_PROMPT_TEMPLATE 即可调整 Gemini 的生成逻辑。
占位符说明（由代码自动填入，请勿手动修改占位符名称）：
  {product_summary_block}  ← analyze_pdf 的 analysis_result.json 产品摘要
  {title_library_block}    ← assets/title_library.txt 内容（可为空）
  {keywords_block}         ← assets/keywords_food_machine.txt 内容（可为空）
═══════════════════════════════════════════════════════════════════════
"""

# ──────────────────────────────────────────────────────────────────────
# 五个强制角度（修改这里可以改变5组的切入方向）
# ──────────────────────────────────────────────────────────────────────
LISTING_ANGLES = [
    {
        "id": 1,
        "angle": "Core Function",
        "cn_label": "核心功能角",
        "description": "直接突出产品的核心机械功能和主要应用场景，面向全球采购商",
        "target_customer": "Global wholesale buyers and distributors",
    },
    {
        "id": 2,
        "angle": "Commercial Food Service",
        "cn_label": "餐饮商业角",
        "description": "面向餐厅、外卖连锁、快餐店、餐饮供应商，强调商业使用价值",
        "target_customer": "Restaurants, takeout chains, food service operators",
    },
    {
        "id": 3,
        "angle": "Small Business & Startup",
        "cn_label": "小商户入门角",
        "description": "面向创业者、小型食品企业，突出易操作、体积小、入门成本低",
        "target_customer": "Small business owners, food startups, home-based catering",
    },
    {
        "id": 4,
        "angle": "Industrial Efficiency",
        "cn_label": "工厂产能角",
        "description": "面向食品生产线、工厂采购，强调高效率、耐用、连续作业能力",
        "target_customer": "Food manufacturers, production line managers, factories",
    },
    {
        "id": 5,
        "angle": "Multi-Application Versatility",
        "cn_label": "多功能兼容角",
        "description": "突出产品的多场景兼容性：不同容器材质、食品类型、行业通用",
        "target_customer": "Multi-product food businesses, catering equipment resellers",
    },
]

# ──────────────────────────────────────────────────────────────────────
# 主 Prompt 模板（可自由编辑，但保留三个 {占位符}）
# ──────────────────────────────────────────────────────────────────────
LISTING_PROMPT_TEMPLATE = """\
You are a professional B2B product listing specialist for Alibaba International (alibaba.com).
Your job: generate 5 complete listing groups that together maximize keyword coverage
across all major buyer segments for this product.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRODUCT ANALYSIS (from product images & PDF)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{product_summary_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REFERENCE TITLE LIBRARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{title_library_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KEYWORD POOL (distribute strategically across 5 listings)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{keywords_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ALIBABA INTERNATIONAL PLATFORM RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE RULES:
- Length: 100–110 characters (HARD LIMIT — count carefully; shorter allows adaptation to other languages)
- Language: English only, no Chinese characters
- Open with the most searchable product noun + key spec or application modifier
- Do NOT start with: "High Quality", "Good", "Cheap", "Best", "Top", "Factory"
- Pack 3–5 high-search keywords naturally into the title
- No commas between product nouns (use spaces or slashes)
- Format pattern examples:
    [Product Noun] [Key Spec/Material] [Application] [Form Factor/Feature] [Use Case]
    [Adj+Product Noun] [For Use Case] [Key Feature] [Scale/Capacity]

SELLING POINT RULES:
- 5 selling points per listing
- Each selling point: ALL-CAPS LABEL (2–4 words) + colon + 1–2 sentences
- B2B focus: mention MOQ, OEM/ODM options, certifications, factory-direct, after-sales
- Use concrete numbers where possible (power wattage, sealing time, dimensions, temp range)
- Label examples: PRECISION SEALING, FAST OPERATION, FOOD-GRADE MATERIALS,
  OEM CUSTOMIZATION, WIDE COMPATIBILITY, LOW MAINTENANCE, DURABLE CONSTRUCTION,
  ENERGY EFFICIENT, COMPACT DESIGN, EASY OPERATION

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5 LISTING ANGLES (MUST cover all 5 — no two listings share the same angle)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{angles_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KEYWORD DISTRIBUTION RULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Each listing should use a DIFFERENT primary keyword cluster from the keyword pool
- Together, the 5 titles must cover the broadest possible search term surface
- No single keyword should appear in more than 2 listing titles
- Each listing's selling points should reinforce the keyword theme of that listing

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT — return ONLY valid JSON, no markdown fences, no explanations
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "product_name_en": "...",
  "product_name_cn": "...",
  "listings": [
    {{
      "id": 1,
      "angle": "Core Function",
      "target_customer": "Global wholesale buyers and distributors",
      "keyword_focus": ["keyword1", "keyword2", "keyword3"],
      "title": "100–115 char English title packed with keywords",
      "title_char_count": 115,
      "selling_points": [
        "PRECISION SEALING: The servo-driven sealing head delivers...",
        "FAST OPERATION: Seals one container in under 3 seconds...",
        "FOOD-GRADE MATERIALS: All contact parts are 304 stainless steel...",
        "OEM CUSTOMIZATION: Factory supports custom mold sizes, voltage...",
        "WIDE COMPATIBILITY: Works with round, square, and rectangular...",
      ],
      "angle_rationale": "One sentence: why this angle reaches a unique buyer segment"
    }},
    {{ ... listing 2 ... }},
    {{ ... listing 3 ... }},
    {{ ... listing 4 ... }},
    {{ ... listing 5 ... }}
  ]
}}

FINAL CHECKS before outputting:
1. Count every title's characters — must be 100–115 chars
2. Verify each listing has exactly 5 selling points
3. Confirm no two listings share the same primary keyword in the title
4. Confirm all 5 angles are covered
5. All text is English only — zero Chinese characters in output
"""


# ──────────────────────────────────────────────────────────────────────
# 渲染函数（由 sop_chat.py 或 build_listings.py 调用）
# ──────────────────────────────────────────────────────────────────────

def build_listing_prompt(
    product_summary: dict,
    title_library: str = "",
    keywords: str = ""
) -> str:
    """
    将产品摘要、标题库、关键词库填入模板，返回最终 Prompt 字符串。

    参数:
        product_summary: analysis_result.json 中的 product_summary 字典
        title_library:   assets/title_library.txt 的文本内容（可为空字符串）
        keywords:        assets/keywords_food_machine.txt 的文本内容（可为空字符串）
    """
    # ── 产品摘要块 ──
    if product_summary:
        lines = []
        lines.append(f"Product Name (EN): {product_summary.get('product_name_en', 'N/A')}")
        lines.append(f"Product Name (CN): {product_summary.get('product_name_cn', 'N/A')}")
        lines.append(f"Product Type: {product_summary.get('product_type', 'N/A')}")
        lines.append(f"Core Function: {product_summary.get('core_function', 'N/A')}")
        lines.append(f"Materials: {product_summary.get('materials', 'N/A')}")
        lines.append(f"Specs Summary: {product_summary.get('specs_summary', 'N/A')}")

        features = product_summary.get("key_features", [])
        if features:
            lines.append(f"\nKey Features ({len(features)} total):")
            for f in features:
                lines.append(f"  • {f}")

        scenarios = product_summary.get("applicable_scenarios", [])
        if scenarios:
            lines.append(f"\nApplicable Scenarios:")
            for s in scenarios:
                lines.append(f"  • {s}")

        certs = product_summary.get("certifications", [])
        if certs:
            lines.append(f"\nCertifications: {', '.join(certs)}")

        lines.append(f"\nTarget Customers: {product_summary.get('target_customers', 'N/A')}")
        product_summary_block = "\n".join(lines)
    else:
        product_summary_block = "(No product analysis available — infer from context)"

    # ── 标题库块 ──
    real_titles = [
        line.strip()
        for line in title_library.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ] if title_library else []

    if real_titles:
        title_library_block = (
            f"The following {len(real_titles)} reference titles are from real Alibaba listings.\n"
            "Study their keyword choice, structure, and character density.\n"
            "DO NOT copy them — use as style/keyword inspiration only:\n\n"
            + "\n".join(f"  [{i+1}] {t}" for i, t in enumerate(real_titles))
        )
    else:
        title_library_block = (
            "No reference titles provided.\n"
            "Generate titles based on the product analysis and keyword pool above.\n"
            "Follow Alibaba International best practices: keyword-dense, specific, "
            "action-oriented, 100–140 characters."
        )

    # ── 关键词块 ──
    real_kws = [
        line.strip()
        for line in keywords.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ] if keywords else []

    if real_kws:
        keywords_block = (
            f"Use and distribute these {len(real_kws)} keywords strategically across 5 listings:\n\n"
            + "\n".join(f"  • {kw}" for kw in real_kws)
        )
    else:
        keywords_block = (
            "No keyword pool provided.\n"
            "Generate relevant B2B search keywords based on the product analysis above.\n"
            "Think like a buyer: what would they search on Alibaba International?"
        )

    # ── 角度块 ──
    angle_lines = []
    for a in LISTING_ANGLES:
        angle_lines.append(
            f"Listing {a['id']} — {a['angle']} ({a['cn_label']})\n"
            f"  Focus: {a['description']}\n"
            f"  Target: {a['target_customer']}"
        )
    angles_block = "\n\n".join(angle_lines)

    # ── 组装最终 Prompt ──
    return LISTING_PROMPT_TEMPLATE.format(
        product_summary_block=product_summary_block,
        title_library_block=title_library_block,
        keywords_block=keywords_block,
        angles_block=angles_block,
    )
