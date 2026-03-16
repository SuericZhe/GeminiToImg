"""
product_manager.py
产品数据管理模块 —— 负责所有产品分析结果的读写、结构化存储。
"""
import os
import json
import shutil

PRODUCTS_DIR = "products"


def get_product_dir(product_name):
    """将产品名转换为安全的文件夹路径"""
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in product_name).strip()
    return os.path.join(PRODUCTS_DIR, safe_name)


def save_product_analysis(product_name, data, ref_images=None):
    """
    保存产品分析结果：
    - analysis.json  完整数据
    - listings.json  5组标题+卖点
    - features.json  产品特点（后续生成图片Prompt用）
    - ref_images/    复制过来的产品参考图
    """
    product_dir = get_product_dir(product_name)
    os.makedirs(product_dir, exist_ok=True)

    # 复制参考图到产品文件夹，方便后续生图时调用
    if ref_images:
        ref_dir = os.path.join(product_dir, "ref_images")
        os.makedirs(ref_dir, exist_ok=True)
        for src in ref_images:
            if os.path.exists(src):
                dst = os.path.join(ref_dir, os.path.basename(src))
                shutil.copy2(src, dst)

    # 保存完整分析
    with open(os.path.join(product_dir, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 保存 listings（标题+卖点）
    with open(os.path.join(product_dir, "listings.json"), "w", encoding="utf-8") as f:
        json.dump({
            "product_name_en": data.get("product_name_en", ""),
            "product_name_cn": data.get("product_name_cn", ""),
            "listings": data.get("listings", [])
        }, f, ensure_ascii=False, indent=2)

    # 保存 features（产品特点）
    with open(os.path.join(product_dir, "features.json"), "w", encoding="utf-8") as f:
        json.dump({
            "product_name_en": data.get("product_name_en", ""),
            "features": data.get("features", [])
        }, f, ensure_ascii=False, indent=2)

    return product_dir


def save_image_prompts(product_name, prompts):
    """保存25个图片生成Prompt"""
    product_dir = get_product_dir(product_name)
    path = os.path.join(product_dir, "image_prompts.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prompts, f, ensure_ascii=False, indent=2)
    return path


def load_product(product_name):
    """读取产品完整分析数据"""
    path = os.path.join(get_product_dir(product_name), "analysis.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_image_prompts(product_name):
    """读取已生成的图片Prompt"""
    path = os.path.join(get_product_dir(product_name), "image_prompts.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_ref_images(product_name):
    """获取产品参考图列表"""
    ref_dir = os.path.join(get_product_dir(product_name), "ref_images")
    if not os.path.exists(ref_dir):
        return []
    return [
        os.path.join(ref_dir, f)
        for f in os.listdir(ref_dir)
        if f.lower().endswith(('.jpg', '.jpeg', '.png'))
    ]


def get_images_output_dir(product_name, listing_id):
    """获取某组listing的图片输出目录，不存在则创建"""
    img_dir = os.path.join(get_product_dir(product_name), "images", f"listing_{listing_id}")
    os.makedirs(img_dir, exist_ok=True)
    return img_dir


def list_products():
    """列出所有已分析的产品及其状态"""
    if not os.path.exists(PRODUCTS_DIR):
        return []
    result = []
    for d in os.listdir(PRODUCTS_DIR):
        full_path = os.path.join(PRODUCTS_DIR, d)
        if not os.path.isdir(full_path):
            continue
        has_analysis = os.path.exists(os.path.join(full_path, "analysis.json"))
        has_prompts = os.path.exists(os.path.join(full_path, "image_prompts.json"))
        images_dir = os.path.join(full_path, "images")
        image_count = 0
        if os.path.exists(images_dir):
            for listing_dir in os.listdir(images_dir):
                ldir = os.path.join(images_dir, listing_dir)
                if os.path.isdir(ldir):
                    image_count += len([f for f in os.listdir(ldir) if f.endswith('.png')])
        result.append({
            "name": d,
            "has_analysis": has_analysis,
            "has_prompts": has_prompts,
            "image_count": image_count
        })
    return result
