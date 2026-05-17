"""旅行规划智能体 - LangGraph实现"""

import json
from datetime import datetime, timedelta
from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from ..models.schemas import TripRequest, TripPlan, DayPlan, Attraction, Meal, WeatherInfo, Location, Hotel
from ..config import get_settings
from ..services.llm_service import get_llm
from ..tools.amap_tools import search_attractions, search_hotels, get_weather


class TripPlanningState(TypedDict):
    """旅行规划工作流状态"""
    request: TripRequest
    llm: ChatOpenAI
    attractions: str
    weather: str
    hotels: str
    trip_plan: TripPlan
    error: Optional[str]


ATTRACTION_AGENT_PROMPT = """你是景点搜索专家。
根据用户的旅行请求，使用 search_attractions 工具搜索目的地城市的景点。
关键词应根据用户偏好选择，如果没有偏好则使用"景点"作为关键词。
返回搜索结果即可。
"""

WEATHER_AGENT_PROMPT = """你是天气查询专家。
根据用户的旅行请求，使用 get_weather 工具查询目的地城市的天气信息。
返回天气查询结果即可。
"""

HOTEL_AGENT_PROMPT = """你是酒店推荐专家。
根据用户的旅行请求，使用 search_hotels 工具搜索目的地城市的酒店。
关键词应根据用户住宿偏好选择，如"经济型酒店"、"豪华酒店"等。
返回搜索结果即可。
"""

PLANNER_AGENT_PROMPT = """你是专业的行程规划师。
请根据以下信息生成详细的旅行计划：

**基本信息:**
- 城市: {city}
- 日期: {start_date} 至 {end_date}
- 天数: {travel_days}天
- 交通方式: {transportation}
- 住宿: {accommodation}
- 偏好: {preferences}

**景点信息:**
{attractions}

**天气信息:**
{weather}

**酒店信息:**
{hotels}

请严格按照以下JSON格式返回旅行计划:
```json
{{
  "city": "城市名称",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "day_index": 0,
      "description": "第1天行程概述",
      "transportation": "交通方式",
      "accommodation": "住宿类型",
      "hotel": {{
        "name": "酒店名称",
        "address": "酒店地址",
        "location": {{"longitude": 116.397128, "latitude": 39.916527}},
        "price_range": "300-500元",
        "rating": "4.5",
        "distance": "距离景点2公里",
        "type": "经济型酒店",
        "estimated_cost": 400
      }},
      "attractions": [
        {{
          "name": "景点名称",
          "address": "详细地址",
          "location": {{"longitude": 116.397128, "latitude": 39.916527}},
          "visit_duration": 120,
          "description": "景点详细描述",
          "category": "景点类别",
          "ticket_price": 60
        }}
      ],
      "meals": [
        {{"type": "breakfast", "name": "早餐推荐", "description": "早餐描述", "estimated_cost": 30}},
        {{"type": "lunch", "name": "午餐推荐", "description": "午餐描述", "estimated_cost": 50}},
        {{"type": "dinner", "name": "晚餐推荐", "description": "晚餐描述", "estimated_cost": 80}}
      ]
    }}
  ],
  "weather_info": [
    {{
      "date": "YYYY-MM-DD",
      "day_weather": "晴",
      "night_weather": "多云",
      "day_temp": 25,
      "night_temp": 15,
      "wind_direction": "南风",
      "wind_power": "1-3级"
    }}
  ],
  "overall_suggestions": "总体建议",
  "budget": {{
    "total_attractions": 180,
    "total_hotels": 1200,
    "total_meals": 480,
    "total_transportation": 200,
    "total": 2060
  }}
}}
```

**要求:**
1. weather_info数组必须包含每一天的天气信息
2. 温度必须是纯数字(不要带°C等单位)
3. 每天安排2-3个景点
4. 考虑景点之间的距离和游览时间
5. 每天必须包含早中晚三餐
6. 提供实用的旅行建议
7. 必须包含预算信息
"""


def search_attractions_node(state: TripPlanningState) -> TripPlanningState:
    """搜索景点节点"""
    print("📍 搜索景点...")
    try:
        request = state["request"]
        keywords = request.preferences[0] if request.preferences else "景点"
        result = search_attractions.invoke({"keywords": keywords, "city": request.city})
        print(f"景点搜索结果获取成功")
        return {"attractions": str(result)}
    except Exception as e:
        print(f"❌ 景点搜索失败: {str(e)}")
        return {"attractions": "", "error": str(e)}


def search_weather_node(state: TripPlanningState) -> TripPlanningState:
    """查询天气节点"""
    print("🌤️  查询天气...")
    try:
        request = state["request"]
        result = get_weather.invoke({"city": request.city})
        print(f"天气查询结果获取成功")
        return {"weather": str(result)}
    except Exception as e:
        print(f"❌ 天气查询失败: {str(e)}")
        return {"weather": "", "error": str(e)}


def search_hotels_node(state: TripPlanningState) -> TripPlanningState:
    """搜索酒店节点"""
    print("🏨 搜索酒店...")
    try:
        request = state["request"]
        keywords = f"{request.accommodation}酒店" if request.accommodation else "酒店"
        result = search_hotels.invoke({"city": request.city, "keywords": keywords})
        print(f"酒店搜索结果获取成功")
        return {"hotels": str(result)}
    except Exception as e:
        print(f"❌ 酒店搜索失败: {str(e)}")
        return {"hotels": "", "error": str(e)}


def generate_plan_node(state: TripPlanningState) -> TripPlanningState:
    """生成行程计划节点"""
    print("📋 生成行程计划...")
    try:
        request = state["request"]
        llm = state["llm"]

        prompt = PLANNER_AGENT_PROMPT.format(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            travel_days=request.travel_days,
            transportation=request.transportation,
            accommodation=request.accommodation,
            preferences=", ".join(request.preferences) if request.preferences else "无",
            attractions=state["attractions"],
            weather=state["weather"],
            hotels=state["hotels"]
        )

        if request.free_text_input:
            prompt += f"\n**额外要求:** {request.free_text_input}"

        messages = [
            SystemMessage(content="你是一位专业的旅行规划师，擅长根据用户需求制定详细的旅行计划。"),
            HumanMessage(content=prompt)
        ]

        response = llm.invoke(messages)
        result = response.content

        trip_plan = _parse_response(result, request)
        print(f"✅ 行程计划生成成功")
        return {"trip_plan": trip_plan}

    except Exception as e:
        print(f"❌ 生成行程计划失败: {str(e)}")
        return {"trip_plan": _create_fallback_plan(request), "error": str(e)}


def _parse_response(response: str, request: TripRequest) -> TripPlan:
    """解析LLM响应"""
    try:
        if "```json" in response:
            json_start = response.find("```json") + 7
            json_end = response.find("```", json_start)
            json_str = response[json_start:json_end].strip()
        elif "```" in response:
            json_start = response.find("```") + 3
            json_end = response.find("```", json_start)
            json_str = response[json_start:json_end].strip()
        elif "{" in response and "}" in response:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            json_str = response[json_start:json_end]
        else:
            raise ValueError("响应中未找到JSON数据")

        data = json.loads(json_str)
        return TripPlan(**data)

    except Exception as e:
        print(f"⚠️  解析响应失败: {str(e)}")
        return _create_fallback_plan(request)


def _create_fallback_plan(request: TripRequest) -> TripPlan:
    """创建备用计划"""
    start_date = datetime.strptime(request.start_date, "%Y-%m-%d")

    days = []
    for i in range(request.travel_days):
        current_date = start_date + timedelta(days=i)

        day_plan = DayPlan(
            date=current_date.strftime("%Y-%m-%d"),
            day_index=i,
            description=f"第{i+1}天行程",
            transportation=request.transportation,
            accommodation=request.accommodation,
            attractions=[
                Attraction(
                    name=f"{request.city}景点{j+1}",
                    address=f"{request.city}市",
                    location=Location(longitude=116.4 + i*0.01 + j*0.005, latitude=39.9 + i*0.01 + j*0.005),
                    visit_duration=120,
                    description=f"这是{request.city}的著名景点",
                    category="景点"
                )
                for j in range(2)
            ],
            meals=[
                Meal(type="breakfast", name=f"第{i+1}天早餐", description="当地特色早餐"),
                Meal(type="lunch", name=f"第{i+1}天午餐", description="午餐推荐"),
                Meal(type="dinner", name=f"第{i+1}天晚餐", description="晚餐推荐")
            ]
        )
        days.append(day_plan)

    return TripPlan(
        city=request.city,
        start_date=request.start_date,
        end_date=request.end_date,
        days=days,
        weather_info=[],
        overall_suggestions=f"这是为您规划的{request.city}{request.travel_days}日游行程,建议提前查看各景点的开放时间。"
    )


class LangGraphTripPlanner:
    """基于LangGraph的旅行规划系统"""

    def __init__(self):
        """初始化工作流"""
        print("🔄 初始化LangGraph旅行规划系统...")
        try:
            self.llm = get_llm()
            self.graph = self._build_graph()
            print("✅ LangGraph旅行规划系统初始化成功")
        except Exception as e:
            print(f"❌ 初始化失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

    def _build_graph(self) -> StateGraph:
        """构建工作流图"""
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

        return workflow.compile()

    def plan_trip(self, request: TripRequest) -> TripPlan:
        """执行旅行规划"""
        print(f"\n{'='*60}")
        print(f"🚀 开始LangGraph旅行规划...")
        print(f"目的地: {request.city}")
        print(f"日期: {request.start_date} 至 {request.end_date}")
        print(f"天数: {request.travel_days}天")
        print(f"偏好: {', '.join(request.preferences) if request.preferences else '无'}")
        print(f"{'='*60}\n")

        try:
            initial_state = {
                "request": request,
                "llm": self.llm,
                "attractions": "",
                "weather": "",
                "hotels": "",
                "trip_plan": None,
                "error": None
            }

            result = self.graph.invoke(initial_state)
            trip_plan = result.get("trip_plan")

            if not trip_plan:
                trip_plan = _create_fallback_plan(request)

            print(f"{'='*60}")
            print(f"✅ 旅行计划生成完成!")
            print(f"{'='*60}\n")

            return trip_plan

        except Exception as e:
            print(f"❌ 旅行规划失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return _create_fallback_plan(request)


_multi_agent_planner = None


def get_trip_planner_agent() -> LangGraphTripPlanner:
    """获取旅行规划智能体实例(单例模式)"""
    global _multi_agent_planner

    if _multi_agent_planner is None:
        _multi_agent_planner = LangGraphTripPlanner()
        
    return _multi_agent_planner