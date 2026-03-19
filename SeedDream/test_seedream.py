import os
from dotenv import load_dotenv
from SeedDream.SeedreamClient import SeedreamClient

# 1. 加载 .env 文件中的环境变量
load_dotenv()

# 2. 从环境变量获取 API Key
api_key = os.getenv("DOUBAO_API_KEY")
if not api_key:
    raise ValueError("未在 .env 文件中找到 DOUBAO_API_KEY，请检查配置！")

# 3. 实例化客户端 (不需要再传入模型了，因为模型选择移到了生成方法中)
client = SeedreamClient(api_key=api_key)

if __name__ == "__main__":
    prompt_text = "一只赛博朋克风格的柯基犬，带着发光的护目镜，霓虹灯背景，高画质，电影感光效"

    try:
        print("=== 测试 1: 使用默认的 4.5 模型生成单图 ===")
        # 不传 model_endpoint，默认就是 4.5 模型
        local_files_45 = client.text_to_single_image(prompt=prompt_text)
        print(f"✅ 成功！图片已保存至: {local_files_45[0]}")

        print("\n=== 测试 2: 切换到 5.0 Lite 模型生成组图 ===")
        # 显式传入 5.0 模型常量
        local_files_50 = client.text_to_group_images(
            prompt="一套现代极简风格的咖啡杯产品设计图，纯白背景，多角度展示", 
            max_images=2, 
            model_endpoint=SeedreamClient.MODEL_5_0
        )
        print("✅ 成功！组图已保存至:")
        for file in local_files_50:
            print(f" - {file}")

    except Exception as e:
        print(f"❌ 运行出错: {e}")