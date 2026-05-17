# LangChain智能旅行助手 🌍✈️

基于LangChain和LangGraph框架构建的智能旅行规划助手,集成高德地图API服务,提供个性化的旅行计划生成。

## ✨ 功能特点

- 🤖 **AI驱动的旅行规划**: 基于LangGraph工作流引擎,智能生成详细的多日旅程
- 🗺️ **高德地图集成**: 通过HTTP API接入高德地图服务,支持景点搜索、路线规划、天气查询
- 🧠 **智能工具调用**: Agent自动调用高德地图工具,获取实时POI、路线和天气信息
- 🎨 **现代化前端**: Vue3 + TypeScript + Vite,响应式设计,流畅的用户体验
- 📱 **完整功能**: 包含住宿、交通、餐饮和景点游览时间推荐

## 🏗️ 技术栈

### 后端

- **框架**: LangChain + LangGraph
- **API**: FastAPI
- **地图服务**: 高德地图HTTP API
- **LLM**: 支持多种LLM提供商(OpenAI, DeepSeek等)

### 前端

- **框架**: Vue 3 + TypeScript
- **构建工具**: Vite
- **UI组件库**: Ant Design Vue
- **地图服务**: 高德地图 JavaScript API
- **HTTP客户端**: Axios

## 📁 项目结构

```
helloagents-trip-planner/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── agents/            # Agent实现
│   │   │   └── trip_planner_agent.py
│   │   ├── api/               # FastAPI路由
│   │   │   ├── main.py
│   │   │   └── routes/
│   │   │       ├── trip.py
│   │   │       └── map.py
│   │   ├── services/          # 服务层
│   │   │   ├── amap_service.py
│   │   │   └── llm_service.py
│   │   ├── models/            # 数据模型
│   │   │   └── schemas.py
│   │   └── config.py          # 配置管理
│   ├── requirements.txt
│   ├── .env.example
│   └── .gitignore
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── components/        # Vue组件
│   │   ├── services/          # API服务
│   │   ├── types/             # TypeScript类型
│   │   └── views/             # 页面视图
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

## 🚀 快速开始

### 前提条件

- Python 3.10+
- Node.js 16+
- 高德地图API密钥 (Web服务API和Web端(JS API))
- LLM API密钥 (OpenAI/DeepSeek等)

### 后端安装

1. 进入后端目录

```bash
cd backend
```

1. 创建虚拟环境

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

1. 安装依赖

```bash
pip install -r requirements.txt
```

1. 配置环境变量

```bash
cp .env.example .env
# 编辑.env文件,填入你的API密钥
```

1. 启动后端服务

```bash
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端安装

1. 进入前端目录

```bash
cd frontend
```

1. 安装依赖

```bash
npm install
```

1. 配置环境变量

```bash
# 创建.env文件, 填入高德地图Web API Key 和 Web端JS API Key
cp .env.example .env
```

1. 启动开发服务器

```bash
npm run dev
```

1. 打开浏览器访问 `http://localhost:5173`

## 📝 使用指南

1. 在首页填写旅行信息:
   - 目的地城市
   - 旅行日期和天数
   - 交通方式偏好
   - 住宿偏好
   - 旅行风格标签
2. 点击"生成旅行计划"按钮
3. 系统将:
   - 调用LangGraph工作流生成初步计划
   - Agent自动调用高德地图工具搜索景点
   - Agent获取天气信息和路线规划
   - 整合所有信息生成完整行程
4. 查看结果:
   - 每日详细行程
   - 景点信息与地图标记
   - 交通路线规划
   - 天气预报
   - 餐饮推荐

## 🔧 核心实现

### LangGraph工作流集成

```python
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph import StateGraph, END

class TripPlanningState(TypedDict):
    city: str
    days: int
    attractions: list
    weather: dict
    hotels: list
    plan: str

@tool
def search_attractions(keywords: str, city: str) -> str:
    """搜索景点"""
    amap_service = AmapService()
    return amap_service.search_poi_sync(keywords, city)

workflow = StateGraph(TripPlanningState)
workflow.add_node("search_attractions", search_attractions_node)
workflow.add_node("search_weather", search_weather_node)
workflow.add_node("search_hotels", search_hotels_node)
workflow.add_node("generate_plan", generate_plan_node)
workflow.set_entry_point("search_attractions")
workflow.add_edge("search_attractions", "search_weather")
workflow.add_edge("search_weather", "search_hotels")
workflow.add_edge("search_hotels", "generate_plan")
workflow.add_edge("generate_plan", END)

app = workflow.compile()
```

### LangChain工具调用

Agent可以自动调用以下高德地图工具:

- `search_attractions`: 搜索景点POI
- `search_weather`: 查询天气
- `search_hotels`: 搜索酒店
- `search_restaurants`: 搜索餐厅

## 📄 API文档

启动后端服务后,访问 `http://localhost:8000/docs` 查看完整的API文档。

主要端点:

- `POST /api/trip/plan` - 生成旅行计划
- `GET /api/map/poi` - 搜索POI
- `GET /api/map/weather` - 查询天气
- `POST /api/map/route` - 规划路线

## 🤝 贡献指南

欢迎提交Pull Request或Issue!

## 📜 开源协议

CC BY-NC-SA 4.0

## 🙏 致谢

- [LangChain](https://github.com/langchain-ai/langchain) - 大语言模型应用开发框架
- [LangGraph](https://github.com/langchain-ai/langgraph) - 工作流引擎
- [高德地图开放平台](https://lbs.amap.com/) - 地图服务
- [Unsplash](https://unsplash.com/) - 图片服务

***

**LangChain智能旅行助手** - 让旅行计划变得简单而智能 🌈
