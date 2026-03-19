from create_feishu_excel import FeishuSheetManager
fm = FeishuSheetManager()
sheet_info = fm.create_spreadsheet("测试可见性表格")
print(f"表格URL: {sheet_info.get('url')}")
