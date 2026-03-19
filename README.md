# GeminiToImg: 智能化产品营销图重设计流水线

本项旨在利用 **Gemini 2.5/3.1** 和 **火山方舟 Seedream** 等多模态大模型，实现从产品文档/图片到电商营销图（Listing）的全自动生成。

---

## 🌟 核心能力

1.  **产品深度分析 (Step 1)**: 自动扫描文件夹中的 PDF 说明书和实拍图片，提取产品核心卖点、参数、适用场景及客户群体。
2.  **多策略 Listing 生成 (Step 2)**: 基于产品分析结果，结合预设的标题库和关键词库，生成 5 组针对不同营销角度的标题与卖点（Listing）。
3.  **AI 重设计 Prompt 构建 (Step 3)**: 将 Listing 转化为专业的 AI 绘图提示词，支持多种视觉风格（极简、科技感、生活化等）。
4.  **大规模图像生成 (Step 4 & 5)**: 
    *   **Seedream 渲染**: 使用火山方舟 Seedream 4.5/5.0 模型进行产品主图重绘。
    *   **Gemini 场景图**: 利用 Gemini 3.1 强大的视觉生成能力，自动合成带场景和文案的副图。
5.  **自动化协同**: 所有生成的 Listing 自动导出到 **飞书多维表格**，方便团队协作与审核。
6.  **高可用鉴权路由**: 内置 `CredentialPool`，支持多 API Key 和 Vertex AI 自动轮换，自动处理 429 (限流) 和 403 (权限) 错误。

---

## 🏗 项目架构

### 核心模块
*   `main.py`: 流水线总入口，串联五个核心步骤。
*   `gemini_client.py`: 统一的 Gemini 访问接口，包含自动重试、等待动画及**凭证路由切换**。
*   `SeedreamClient.py`: 火山方舟图像生成客户端，支持本地直存。
*   `analyze_pdf.py`: PDF 拆分、图片压缩与多模态内容识别。
*   `build_listings.py`: 文案策略核心，控制生成逻辑。
*   `create_feishu_excel.py`: 飞书 API 集成，实现数据云端同步。

### 目录结构
*   `/my_work_files/`: 存放待处理的原始 PDF 和图片。
*   `/products/`: 存放生成的结果（listings, prompts, images）。
*   `/key/`: 存放 Google Cloud (Vertex AI) 的服务账号 JSON。
*   `/assets/`: 标题库、关键词库等资产。

---

## 🚀 快速开始

### 1. 环境准备
```powershell
pip install -r requirements.txt
cp .env.example .env  # 配置您的 API Key
```

### 2. 运行测试
*   **测试凭证有效性**: `python test_credentials.py`
*   **测试图像生成**: `python test_seedream.py`

### 3. 启动全流程
将您的产品资料放入 `my_work_files` 文件夹，然后运行：
```powershell
python main.py "您的产品名称"
```

---

## 🛠 高级配置

*   **.gitignore**: 已预设忽略 `assets/`、`key/` 及生成的图片目录，确保数据安全。
*   **鉴权切换**: 系统会自动在 `GOOGLE_API_KEY` (API 模式) 和 `key/*.json` (Vertex 模式) 之间切换，优先保证任务成功率。

---

## 📅 开发状态
*   [x] 多 API Key 轮换
*   [x] Vertex AI 集成
*   [x] Seedream 5.0 适配
*   [x] 飞书自动化导出
*   [ ] 自动排版文案图层
