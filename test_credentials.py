import os
import time
from dotenv import load_dotenv
from google.genai import types
import gemini_client

def test_all_credentials():
    """
    遍历并测试 CredentialPool 中所有的 API Key 和 Vertex 凭证。
    """
    print("🚀 开始测试凭证池中的所有凭证...\n")
    
    # 初始化凭证池
    try:
        pool = gemini_client.CredentialPool(use_vertex=True)
        print(f"📊 {pool.summary()}\n")
    except Exception as e:
        print(f"❌ 初始化凭证池失败: {e}")
        return

    num_creds = len(pool)
    results = []

    for i in range(num_creds):
        cred = pool.current()
        
        # 仅测试 vertex 相关的凭证
        if cred["type"] != "vertex":
            if i < num_creds - 1:
                pool.rotate()
            continue

        tag = f"Vertex [{os.path.basename(cred['path'])}]"
        print(f"--- 正在测试 [{i + 1}/{num_creds}]: {tag} ---")
        
        success = False
        error_msg = ""
        full_error = ""
        
        try:
            # 1. 创建客户端
            client = pool.make_client(cred)
            
            # 2. 发送简单文本请求测试
            model = gemini_client.DEFAULT_TEXT_MODEL
            response = client.models.generate_content(
                model=model,
                contents="Hello, please respond with 'OK' if you can hear me."
            )
            
            if response and response.text:
                print(f"✅ 测试通过！回复内容: {response.text.strip()}")
                success = True
            else:
                error_msg = "收到空回复"
                print(f"❌ 测试失败: {error_msg}")
        
        except Exception as e:
            full_error = str(e)
            error_msg = "API 请求异常"
            # 提取关键简短错误信息
            if "401" in full_error or "API_KEY_INVALID" in full_error:
                error_msg = "无效凭证 (401)"
            elif "403" in full_error or "PERMISSION_DENIED" in full_error:
                error_msg = "权限不足 (403)"
            elif "429" in full_error or "RESOURCE_EXHAUSTED" in full_error:
                error_msg = "配额耗尽/限流 (429)"
            
            print(f"❌ 测试失败: {error_msg}")
            print(f"🔍 详细错误信息:\n{full_error}")

        results.append({
            "tag": tag,
            "success": success,
            "error": error_msg if not success else "",
            "full_error": full_error
        })
        
        # 切换到下一个凭证
        if i < num_creds - 1:
            pool.rotate()
        print("\n")

    # 汇总打印
    print("="*50)
    print("📋 最终测试结果汇总：")
    print("="*50)
    pass_count = 0
    for r in results:
        status = "✅ OK" if r["success"] else f"❌ FAIL ({r['error']})"
        if r["success"]: pass_count += 1
        print(f"{r['tag']:<40} | {status}")
    
    print("="*50)
    print(f"🎉 测试结束: {pass_count}/{num_creds} 通过")

if __name__ == "__main__":
    load_dotenv()
    test_all_credentials()
