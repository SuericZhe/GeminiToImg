"""
SeedDream/__init__.py
════════════════════════════════════════════════════════════════════════
对外导出统一生图函数。
流水线只从此模块导入，不直接引用 client / credential_pool。
"""
from .generate import generate, generate_my_image, select_model

__all__ = ["generate", "generate_my_image", "select_model"]
