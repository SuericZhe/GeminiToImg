# kb_manager.py
import json
import os

KB_FILE = "my_knowledge.json"

def load_kb():
    if not os.path.exists(KB_FILE):
        return {}
    with open(KB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_kb(data):
    with open(KB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_content(topic, content, mode='replace'):
    """保存内容：支持 'replace' (覆盖) 或 'append' (追加)"""
    kb = load_kb()
    if mode == 'append' and topic in kb:
        kb[topic] += f"\n\n--- 追加内容 ---\n{content}"
    else:
        kb[topic] = content
    save_kb(kb)
    return True

def search_content(keyword):
    """模糊搜索：支持搜索主题名或具体内容"""
    kb = load_kb()
    results = {}
    keyword_lower = keyword.lower()
    for topic, content in kb.items():
        if keyword_lower in topic.lower() or keyword_lower in content.lower():
            results[topic] = content
    return results

def get_content(topic):
    """精准获取某个主题的内容"""
    kb = load_kb()
    return kb.get(topic, None)