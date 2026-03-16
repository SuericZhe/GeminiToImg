# main_chat.py
import os
import sys
import time
import threading
import itertools
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from google import genai
from google.genai import types
import kb_manager

# ==========================================
# 1. 基础配置
# ==========================================
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"E:\GeminiToImg\key\gcp-key.json"
PROJECT_ID = "celtic-park-270114"
LOCATION = "global" # 使用 global 以支持最新模型

# 模型选项菜单
AVAILABLE_MODELS = {
    "1": "gemini-2.5-flash",
    "2": "gemini-2.5-pro",
    "3": "gemini-3.1-pro-preview" 
}

# 全局变量控制加载动画
done_thinking = False

# ==========================================
# 2. 核心功能函数
# ==========================================
def get_mime_type(file_path):
    ext = file_path.lower().split('.')[-1]
    if ext in ['jpg', 'jpeg']: return "image/jpeg"
    if ext == 'png': return "image/png"
    if ext == 'pdf': return "application/pdf"
    return "application/octet-stream"

def scan_target_folder(folder_path, processed_files_set):
    """极简监听：只读取没读过的新文件"""
    parts = []
    if not folder_path or not os.path.exists(folder_path):
        return parts

    for file_name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file_name)
        if os.path.isfile(file_path) and file_path not in processed_files_set:
            try:
                mime_type = get_mime_type(file_path)
                with open(file_path, "rb") as f:
                    parts.append(types.Part.from_bytes(data=f.read(), mime_type=mime_type))
                processed_files_set.add(file_path)
                print(f"📦 已自动捕获新文件: {file_name}")
            except Exception as e:
                print(f"❌ 读取文件 {file_name} 失败: {e}")
    return parts

def loading_animation():
    """终端动态等待动画"""
    spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
    while not done_thinking:
        sys.stdout.write(f'\r⏳ 思考中 {next(spinner)} ')
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write('\r\033[K') # 清除本行

def safe_send_message(chat, message_parts, timeout=60, retries=1):
    """带超时限制和重试机制的消息发送"""
    global done_thinking
    for attempt in range(retries + 1):
        done_thinking = False
        anim_thread = threading.Thread(target=loading_animation)
        anim_thread.start()

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(chat.send_message, message_parts)
                response = future.result(timeout=timeout)
                
            done_thinking = True
            anim_thread.join()
            return response
            
        except TimeoutError:
            done_thinking = True
            anim_thread.join()
            print(f"\n⚠️ 第 {attempt + 1} 次请求超时 ({timeout}s)！")
            if attempt < retries:
                print("🔄 正在自动重试...")
            else:
                print("❌ 重试失败，请检查网络。")
                return None
        except Exception as e:
            done_thinking = True
            anim_thread.join()
            print(f"\n❌ API 请求发生错误: {e}")
            return None

# ==========================================
# 3. 主程序交互循环
# ==========================================
def start_chat_session(watch_folder):
    print(f"🚀 初始化 Vertex AI 客户端...")
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    # 模型选择逻辑
    print("\n--- 🧠 选择模型 ---")
    for key, name in AVAILABLE_MODELS.items():
        print(f"[{key}] {name}")
    model_choice = input("请选择模型序号 (默认3): ") or "3"
    selected_model = AVAILABLE_MODELS.get(model_choice, "gemini-3.1-pro-preview")

    # 挂载联网搜索能力
    search_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(tools=[search_tool])

    # 创建会话
    chat = client.chats.create(model=selected_model, config=config)
    
    # 文件夹状态初始化
    processed_files = set()
    os.makedirs(watch_folder, exist_ok=True)
    
    print(f"\n✨ 已开启全新会话 (当前模型: {selected_model}，已开启联网)")
    print(f"📂 正在监听文件夹: {os.path.abspath(watch_folder)}")
    print("""
💡 【指令秘籍】:
   直接打字：正常聊天（如放入新文件会自动一起发送）
   /list ：查看知识库所有标签
   /find 关键词 ：模糊搜索知识库内容 (例如: /find 安防摄像头)
   /save 标签名 ：保存/追加内容到知识库
   /use 标签名 你的问题 ：带着知识库内容提问
   exit ：退出程序
""")

    last_bot_response = ""

    while True:
        user_input = input("\n🧑 你: ").strip()
        if not user_input: continue
        if user_input.lower() in ['quit', 'exit']: 
            print("🛑 拜拜！")
            break

        # ----------------------------------------
        # 知识库指令系统
        # ----------------------------------------
        if user_input.startswith("/list"):
            kb = kb_manager.load_kb()
            print("📚 你的知识库标签: " + (", ".join(kb.keys()) if kb else "空空如也"))
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
            existing_content = kb_manager.get_content(topic)
            mode = 'replace'
            if existing_content:
                print(f"⚠️ 发现已存在标签 [{topic}]。")
                choice = input("输入 'a' 追加内容，输入 'r' 覆盖原内容 (默认 r): ").strip().lower()
                mode = 'append' if choice == 'a' else 'replace'

            print("👇 请粘贴要保存的内容 (回车则自动保存上一条 Gemini 的完整回复):")
            content_to_save = input("> ") or last_bot_response
            
            if content_to_save:
                kb_manager.save_content(topic, content_to_save, mode)
                print(f"💾 已成功{ '追加' if mode == 'append' else '保存' }至 [{topic}]。")
            else:
                print("⚠️ 没有可保存的内容。")
            continue

        # ----------------------------------------
        # 正常对话逻辑装配
        # ----------------------------------------
        message_parts = []
        
        # 1. 如果有 /use 指令，提取并挂载知识库
        if user_input.startswith("/use "):
            try:
                _, topic, prompt = user_input.split(" ", 2)
                content = kb_manager.get_content(topic)
                if content:
                    message_parts.append(f"【参考背景资料】：\n{content}\n\n【我的要求】：{prompt}")
                    print(f"🔗 已成功挂载知识库内容 [{topic}]")
                else:
                    print(f"⚠️ 找不到标签 [{topic}]，请用 /find 搜一下。")
                    continue
            except ValueError:
                print("⚠️ /use 指令格式错误。正确格式: /use 标签名 你的问题")
                continue
        else:
            message_parts.append(user_input)

        # 2. 扫描文件夹，加入新文件
        new_files = scan_target_folder(watch_folder, processed_files)
        # 注意组装顺序：文件最好放在 prompt 文本的前面
        message_parts = new_files + message_parts 

        # 3. 发送请求 (带动画和超时)
        response = safe_send_message(chat, message_parts, timeout=60, retries=1)
        
        if response:
            last_bot_response = response.text
            print(f"🤖 Gemini:\n{response.text}")
            if response.candidates and response.candidates[0].grounding_metadata:
                 print("\n🌐 (此回答参考了 Google 实时搜索结果)")

if __name__ == "__main__":
    # 在这里指定你要监听的工作文件夹，代码会自动在同级目录下创建它
    MY_WORK_FOLDER = "./my_work_files" 
    start_chat_session(MY_WORK_FOLDER)