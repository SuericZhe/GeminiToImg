import os
import json
import requests
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class FeishuSheetManager:
    """
    飞书表格管理器
    提供创建表格、读取内容、写入内容和追加内容的便捷接口。
    """
    def __init__(self, app_id=None, app_secret=None):
        self.app_id = app_id or os.getenv("FEISHU_APP_ID")
        self.app_secret = app_secret or os.getenv("FEISHU_APP_SECRET")
        self.tenant_access_token = None
        
        if not self.app_id or not self.app_secret:
            raise ValueError("FEISHU_APP_ID 和 FEISHU_APP_SECRET 不能为空，请在 .env 中配置或传入参数。")
        
        self.base_url = "https://open.feishu.cn/open-apis"
        self._refresh_token()

    def _refresh_token(self):
        """获取或刷新 tenant_access_token"""
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        headers = {
            "Content-Type": "application/json; charset=utf-8"
        }
        
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") == 0:
            self.tenant_access_token = data.get("tenant_access_token")
        else:
            raise Exception(f"获取 Token 失败: {data}")

    def _get_headers(self):
        """获取请求标头"""
        if not self.tenant_access_token:
            self._refresh_token()
        return {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }

    def create_spreadsheet(self, title: str, folder_token: str = None):
        """
        创建飞书电子表格
        :param title: 表格标题
        :param folder_token: 文件夹 token（可选，不填默认在根目录）
        :return: dict 包含 spreadsheet_token, url 等信息
        """
        url = f"{self.base_url}/sheets/v3/spreadsheets"
        payload = {"title": title}
        if folder_token:
            payload["folder_token"] = folder_token

        response = requests.post(url, json=payload, headers=self._get_headers())
        data = response.json()
        if data.get("code") == 0:
            return data.get("data", {}).get("spreadsheet")
        else:
            raise Exception(f"创建表格失败: {data}")

    def get_sheets(self, spreadsheet_token: str):
        """
        获取电子表格中的所有工作表信息
        :param spreadsheet_token: 表格 token
        :return: list 工作表信息列表
        """
        url = f"{self.base_url}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query"
        response = requests.get(url, headers=self._get_headers())
        data = response.json()
        if data.get("code") == 0:
            return data.get("data", {}).get("sheets", [])
        else:
            raise Exception(f"获取工作表列表失败: {data}")

    def read_sheet(self, spreadsheet_token: str, range_addr: str):
        """
        读取表格内容
        :param spreadsheet_token: 表格 token
        :param range_addr: 数据范围，如 "sheetId!A1:D10" 或 "sheetId"
        :return: list 嵌套列表形式的数据
        """
        url = f"{self.base_url}/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range_addr}"
        
        response = requests.get(url, headers=self._get_headers())
        data = response.json()
        if data.get("code") == 0:
            return data.get("data", {}).get("valueRange", {}).get("values", [])
        else:
            raise Exception(f"读取表格失败: {data}")

    def write_sheet(self, spreadsheet_token: str, range_addr: str, values: list):
        """
        覆盖写入表格内容
        :param spreadsheet_token: 表格 token
        :param range_addr: 写入范围，如 "sheetId!A1:D10"
        :param values: 嵌套列表数据，如 [["A1数据", "B1数据"], ["A2", "B2"]]
        :return: dict 操作结果
        """
        url = f"{self.base_url}/sheets/v2/spreadsheets/{spreadsheet_token}/values"
        payload = {
            "valueRange": {
                "range": range_addr,
                "values": values
            }
        }

        response = requests.put(url, json=payload, headers=self._get_headers())
        data = response.json()
        if data.get("code") == 0:
            return data.get("data")
        else:
            raise Exception(f"写入表格失败: {data}")

    def find_spreadsheet_in_folder(self, title: str, folder_token: str) -> str:
        """
        在指定文件夹中查找同名表格，返回 spreadsheet_token；未找到返回空字符串。
        避免重复创建同名表格。
        """
        url = f"{self.base_url}/drive/v1/files"
        params = {"parent_node": folder_token, "type": "sheet"}
        response = requests.get(url, headers=self._get_headers(), params=params)
        data = response.json()
        if data.get("code") == 0:
            for f in data.get("data", {}).get("files", []):
                if f.get("name") == title:
                    return f.get("token", "")
        return ""

    def add_sheet(self, spreadsheet_token: str, title: str) -> str:
        """
        新增一个工作表（Sheet Tab），使用 V3 单独创建接口。
        :return: 新 sheet 的 sheet_id
        """
        url = f"{self.base_url}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets"
        payload = {"title": title}
        response = requests.post(url, json=payload, headers=self._get_headers())
        data = response.json()
        if data.get("code") == 0:
            return data["data"]["sheet"]["sheet_id"]
        else:
            raise Exception(f"新增工作表失败: {data}")

    def get_or_create_sheet(self, spreadsheet_token: str, title: str) -> str:
        """
        查找指定名称的工作表，存在则返回其 sheet_id，不存在则新建并返回。
        :return: sheet_id
        """
        sheets = self.get_sheets(spreadsheet_token)
        for s in sheets:
            if s.get("title") == title:
                return s["sheet_id"]   # V3 返回 snake_case: sheet_id
        return self.add_sheet(spreadsheet_token, title)

    def append_sheet(self, spreadsheet_token: str, range_addr: str, values: list):
        """
        追加数据到表格
        :param spreadsheet_token: 表格 token
        :param range_addr: 数据范围，如 "sheetId!A1:E" 或 "sheetId"
        :param values: 嵌套列表数据
        :return: dict 操作结果
        """
        url = f"{self.base_url}/sheets/v2/spreadsheets/{spreadsheet_token}/values_append"
        payload = {
            "valueRange": {
                "range": range_addr,
                "values": values
            }
        }

        response = requests.post(url, json=payload, headers=self._get_headers())
        data = response.json()
        if data.get("code") == 0:
            return data.get("data")
        else:
            raise Exception(f"追加数据失败: {data}")


if __name__ == "__main__":
    # 使用示例 (请确保 .env 中填写了真实的 APP_ID 和 APP_SECRET)
    print("飞书表格管理器模块加载成功")
    print("使用方法: ")
    print("from create_feishu_excel import FeishuSheetManager")
    print("fm = FeishuSheetManager()")
    
    # 取消下面代码的注释以进行实际测试（需要先在 .env 中配置好 KEY）
    fm = FeishuSheetManager()
    
    # 1. 创建表格: 
    sheet_info = fm.create_spreadsheet("测试表格", folder_token="VTV4fJoIFlcZKydb6QIcgiM2nm1")
    token = sheet_info["spreadsheet_token"]
    
    # 2. 获取工作表 ID:
    sheets = fm.get_sheets(token)
    first_sheet_id = sheets[0]["sheet_id"] # 通常是第一个 sheet 的 ID
    print(f"第一个工作表 ID 为: {first_sheet_id}")
    
    # 3. 写入内容: 
    fm.write_sheet(token, f"{first_sheet_id}!A1:B2", [["Name", "Age"], ["Alice", 25]])
    
    # 4. 追加内容: 
    fm.append_sheet(token, f"{first_sheet_id}!A3:B3", [["Bob", 30]])
    
    # 5. 读取内容: 
    data = fm.read_sheet(token, f"{first_sheet_id}!A1:B3")
    print(data)


