import os
import time
import base64
import requests
from typing import List, Optional, Union
from dotenv import load_dotenv


class SeedreamClient:
    """
    火山方舟 Seedream 图片生成工具类 (支持本地直存)
    """
    # 预定义模型常量，方便调用
    MODEL_5_0 = "doubao-seedream-5-0-260128"
    MODEL_4_5 = "doubao-seedream-4-5-251128"
    MODEL_4_0 = "doubao-seedream-4-0-250828"

    def __init__(self, api_key: str):
        """
        :param api_key: 火山方舟 API Key
        """
        self.api_key = api_key
        self.url = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        # 确保图片保存目录存在
        self.output_dir = os.path.join(os.getcwd(), "generate_image")
        os.makedirs(self.output_dir, exist_ok=True)

    def _generate(self,
                  prompt: str,
                  model_endpoint: str = MODEL_4_5,  # 默认使用 4.5 模型
                  reference_images: Optional[Union[str, List[str]]] = None,
                  is_group: bool = False,
                  max_images: int = 1,
                  **kwargs) -> List[str]:
        """核心内部方法：处理 API 请求并落盘保存图片，返回本地文件路径列表"""

        payload = {
            "model": model_endpoint,
            "prompt": prompt,
            "response_format": "b64_json",  # 强制要求返回 Base64 数据，而非 URL
            **kwargs
        }

        # 处理参考图 (支持单图字符串或多图列表)
        if reference_images:
            if isinstance(reference_images, str):
                payload["image"] = [reference_images]
            else:
                payload["image"] = reference_images

        # 处理组图/单图逻辑与数量校验
        if is_group:
            payload["sequential_image_generation"] = "auto"
            ref_count = len(payload.get("image", []))

            # 校验规则：输入的参考图数量 + 最终生成的图片数量 ≤ 15张
            if ref_count + max_images > 15:
                allowed_max = max(1, 15 - ref_count)
                print(f"⚠️ 警告: 参考图({ref_count}张) + 请求生成({max_images}张) 超过上限 15。已自动调整生成数量为 {allowed_max}。")
                max_images = allowed_max

            payload["sequential_image_generation_options"] = {"max_images": max_images}
        else:
            payload["sequential_image_generation"] = "disabled"

        # 发送请求
        response = requests.post(self.url, headers=self.headers, json=payload)

        if response.status_code == 200:
            result = response.json()
            saved_filepaths = []

            # 解析 Base64 数据并保存为本地文件
            for idx, img_data in enumerate(result.get('data', [])):
                b64_data = img_data.get('b64_json')
                if b64_data:
                    # 使用时间戳和索引生成唯一文件名
                    filename = f"img_{int(time.time() * 1000)}_{idx}.jpeg"
                    filepath = os.path.join(self.output_dir, filename)

                    # 解码并写入文件
                    with open(filepath, "wb") as f:
                        f.write(base64.b64decode(b64_data))
                    saved_filepaths.append(filepath)

            return saved_filepaths
        else:
            raise Exception(f"API 请求失败: HTTP {response.status_code} - {response.text}")

    # ==========================================
    # 对外暴露的方法：所有方法都可以通过 model_endpoint 切换模型
    # ==========================================
    def text_to_single_image(self, prompt: str, model_endpoint: str = MODEL_4_5, **kwargs) -> List[str]:
        return self._generate(prompt=prompt, model_endpoint=model_endpoint, is_group=False, **kwargs)

    def image_to_single_image(self, prompt: str, reference_image: str, model_endpoint: str = MODEL_4_5, **kwargs) -> List[str]:
        return self._generate(prompt=prompt, model_endpoint=model_endpoint, reference_images=reference_image, is_group=False, **kwargs)

    def multi_images_to_single_image(self, prompt: str, reference_images: List[str], model_endpoint: str = MODEL_4_5, **kwargs) -> List[str]:
        if not (2 <= len(reference_images) <= 14):
            raise ValueError("多图生图需提供 2-14 张参考图！")
        return self._generate(prompt=prompt, model_endpoint=model_endpoint, reference_images=reference_images, is_group=False, **kwargs)

    def text_to_group_images(self, prompt: str, max_images: int = 4, model_endpoint: str = MODEL_4_5, **kwargs) -> List[str]:
        if max_images > 15:
             max_images = 15
        return self._generate(prompt=prompt, model_endpoint=model_endpoint, is_group=True, max_images=max_images, **kwargs)

    def image_to_group_images(self, prompt: str, reference_image: str, max_images: int = 4, model_endpoint: str = MODEL_4_5, **kwargs) -> List[str]:
        return self._generate(prompt=prompt, model_endpoint=model_endpoint, reference_images=reference_image, is_group=True, max_images=max_images, **kwargs)

    def multi_images_to_group_images(self, prompt: str, reference_images: List[str], max_images: int = 4, model_endpoint: str = MODEL_4_5, **kwargs) -> List[str]:
        if not (2 <= len(reference_images) <= 14):
            raise ValueError("多图生组图需提供 2-14 张参考图！")
        return self._generate(prompt=prompt, model_endpoint=model_endpoint, reference_images=reference_images, is_group=True, max_images=max_images, **kwargs)
