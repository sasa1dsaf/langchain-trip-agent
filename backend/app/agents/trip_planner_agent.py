"""旅行规划智能体 - LangGraph多Agent实现

架构:
  dispatch(并行分派)
    ├─ attraction_scout 景点侦察Agent  (LLM制定搜索策略 → 高德工具 → 去重排序)
    ├─ hotel_scout      酒店侦察Agent  (同上)
    ├─ food_scout       美食侦察Agent  (同上)
    └─ weather          天气(纯工具,无LLM)
      全部汇合
  builder 行程编排Builder Agent (LLM, 吸收review_feedback)
    └─ _should_retry: 规则校验未通过且retry_count<MAX → critic(LLM评审) → 回builder
       有界Replan,最多 MAX_PLAN_RETRIES 次
"""

import json
from datetime import datetime, timedelta
from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from ..models.schemas import TripRequest, TripPlan, DayPlan, Attraction, Meal, WeatherInfo, Location
from ..services.llm_service import get_llm
from ..tools.amap_tools import search_attractions, search_hotels, search_restaurants, get_weather

try:
    # langgraph 0.2+ 从 types 导出 Send; 旧版本从 constants 导出
    from langgraph.types import Send
except ImportError:
    from langgraph.constants import Send


class TripPlanningState(TypedDict):
    """旅行规划工作流状态"""
    request: TripRequest
    llm: ChatOpenAI
    attractions: str
    hotels: str
    foods: str
    weather: str
    trip_plan: TripPlan
    validation_issues: List[str]
    review_feedback: str
    retry_count: int
    error: Optional[str]


MAX_PLAN_RETRIES = 1        # 行程编排最多评审重跑次数(有界Replan)
SCOUT_TOP_N = 10            # 每个Scout最多返回的候选数
SCOUT_MAX_KEYWORDS = 3      # 每个Scout最多生成的高德搜索关键词数


# ============ Scout Agent 搜索策略 ============

def _scout_strategy_prompt(kind: str, request: TripRequest) -> str:
    """构造Scout搜索策略生成提示词: LLM决定搜什么关键词"""
    role_map = {
        "attractions": ("景点", "如'故宫''颐和园'等具体景点,或'历史文化''公园'等主题"),
        "hotels": ("酒店", "结合住宿偏好,如'经济型酒店''五星级酒店'"),
        "foods": ("餐厅", "如'本地特色美食''老字号''小吃街'"),
    }
    target, keyword_hint = role_map.get(kind, ("兴趣点", ""))
    prefs = ", ".join(request.preferences) if request.preferences else "无"
    free_text = request.free_text_input or "无"
    return (
        f"你是{request.city}的{target}侦察员(Scout Agent),负责制定POI搜索策略。\n"
        f"用户偏好: {prefs}\n额外要求: {free_text}\n"
        f"请制定最多{SCOUT_MAX_KEYWORDS}个高德地图搜索关键词,从不同侧面覆盖用户偏好({keyword_hint})。\n"
        f"只返回JSON,不要其他文字: {{\"keywords\": [\"关键词1\", \"关键词2\"], \"limit\": 10}}"
    )


def _default_keywords(kind: str, request: TripRequest) -> List[str]:
    """Scout策略生成失败时的兜底关键词(保持原有硬编码行为)"""
    if kind == "hotels":
        return [f"{request.accommodation}酒店"] if request.accommodation else ["酒店"]
    if kind == "foods":
        return ["美食", "当地特色"]
    return [request.preferences[0]] if request.preferences else ["景点"]


def _extract_json(text) -> Optional[dict]:
    """从LLM响应中稳健提取JSON对象,提取失败返回None"""
    if not text:
        return None
    text = text.strip()
    try:
        if "```json" in text:
            json_start = text.find("```json") + 7
            json_end = text.find("```", json_start)
            return json.loads(text[json_start:json_end].strip())
        if "```" in text:
            json_start = text.find("```") + 3
            json_end = text.find("```", json_start)
            return json.loads(text[json_start:json_end].strip())
        if "{" in text and "}" in text:
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            return json.loads(text[json_start:json_end])
        return json.loads(text)
    except Exception:
        return None


def _parse_poi_items(raw: str) -> List[dict]:
    """从高德搜索结果JSON字符串中提取POI列表"""
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("status") == "1":
            return data.get("pois") or []
        return []
    except Exception:
        return []


def _poi_rating(item: dict) -> float:
    """提取POI评分用于排序(无评分时按0处理)"""
    try:
        biz = item.get("biz_ext") or {}
        return float(biz.get("rating") or 0)
    except Exception:
        return 0.0


def _run_scout(request: TripRequest, llm, tool, kind: str) -> str:
    """Scout Agent: LLM制定搜索策略 → 执行高德工具搜索 → 去重排序筛选

    Returns:
        精选后的候选列表JSON字符串
    """
    keywords = None
    if llm is not None:
        try:
            strategy = _extract_json(llm.invoke([
                SystemMessage(content="你是高德POI搜索策略专家,只输出JSON。"),
                HumanMessage(content=_scout_strategy_prompt(kind, request)),
            ]).content)
            if isinstance(strategy, dict):
                raw_keywords = strategy.get("keywords") or []
                keywords = [str(k).strip() for k in raw_keywords if str(k).strip()][:SCOUT_MAX_KEYWORDS]
        except Exception as e:
            print(f"⚠️  {kind} Scout策略生成失败,回退默认关键词: {str(e)}")

    if not keywords:
        keywords = _default_keywords(kind, request)

    results: List[dict] = []
    seen = set()
    for kw in keywords:
        try:
            raw = tool.invoke({"keywords": kw, "city": request.city})
            for item in _parse_poi_items(raw):
                name = (item.get("name") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                results.append(item)
        except Exception as e:
            print(f"⚠️  搜索'{kw}'失败: {str(e)}")

    results.sort(key=lambda x: _poi_rating(x), reverse=True)
    top = results[:SCOUT_TOP_N]
    print(f"🔍 {kind} Scout 返回 {len(top)} 条候选(关键词: {', '.join(keywords)})")
    return json.dumps(top, ensure_ascii=False)


def attraction_scout_node(state: TripPlanningState) -> TripPlanningState:
    """景点侦察Agent节点"""
    print("📍 景点侦察...")
    try:
        return {"attractions": _run_scout(state["request"], state.get("llm"), search_attractions, "attractions")}
    except Exception as e:
        print(f"❌ 景点侦察失败: {str(e)}")
        return {"attractions": "", "error": str(e)}


def hotel_scout_node(state: TripPlanningState) -> TripPlanningState:
    """酒店侦察Agent节点"""
    print("🏨 酒店侦察...")
    try:
        return {"hotels": _run_scout(state["request"], state.get("llm"), search_hotels, "hotels")}
    except Exception as e:
        print(f"❌ 酒店侦察失败: {str(e)}")
        return {"hotels": "", "error": str(e)}


def food_scout_node(state: TripPlanningState) -> TripPlanningState:
    """美食侦察Agent节点"""
    print("🍜 美食侦察...")
    try:
        return {"foods": _run_scout(state["request"], state.get("llm"), search_restaurants, "foods")}
    except Exception as e:
        print(f"❌ 美食侦察失败: {str(e)}")
        return {"foods": "", "error": str(e)}


def search_weather_node(state: TripPlanningState) -> TripPlanningState:
    """天气查询节点(纯工具调用,无需LLM)"""
    print("🌤️  查询天气...")
    try:
        request = state["request"]
        result = get_weather.invoke({"city": request.city})
        print(f"天气查询结果获取成功")
        return {"weather": str(result)}
    except Exception as e:
        print(f"❌ 天气查询失败: {str(e)}")
        return {"weather": "", "error": str(e)}


# ============ Builder Agent: 行程编排 ============

PLANNER_AGENT_PROMPT = """你是专业的行程规划师。
请根据以下信息生成详细的旅行计划：

**基本信息:**
- 城市: {city}
- 日期: {start_date} 至 {end_date}
- 天数: {travel_days}天
- 交通方式: {transportation}
- 住宿: {accommodation}
- 偏好: {preferences}

**景点信息(真实候选,请从中挑选):**
{attractions}

**天气信息:**
{weather}

**酒店信息(真实候选,请从中挑选):**
{hotels}

**餐厅信息(真实候选,餐饮推荐请从中挑选):**
{foods}

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
3. 每天安排2-3个景点,且必须来自上面提供的"景点信息"真实候选
4. 考虑景点之间的距离和游览时间
5. 每天必须包含早中晚三餐,早餐/午餐/晚餐优先从"餐厅信息"真实候选中挑选
6. 推荐酒店必须来自上面提供的"酒店信息"真实候选
7. 提供实用的旅行建议
8. 必须包含预算信息
"""


def _build_plan_prompt(request: TripRequest, state: TripPlanningState) -> str:
    """构造行程编排提示词(含真实数据 + 评审反馈)"""
    prompt = PLANNER_AGENT_PROMPT.format(
        city=request.city,
        start_date=request.start_date,
        end_date=request.end_date,
        travel_days=request.travel_days,
        transportation=request.transportation,
        accommodation=request.accommodation,
        preferences=", ".join(request.preferences) if request.preferences else "无",
        attractions=state.get("attractions", "") or "无",
        weather=state.get("weather", "") or "无",
        hotels=state.get("hotels", "") or "无",
        foods=state.get("foods", "") or "无",
    )

    if request.free_text_input:
        prompt += f"\n**额外要求:** {request.free_text_input}"

    feedback = state.get("review_feedback") or ""
    if feedback:
        prompt += f"\n\n**上次评审未通过,请严格按以下要求修正后重新生成:**\n{feedback}"

    return prompt


def builder_node(state: TripPlanningState) -> TripPlanningState:
    """行程编排Builder Agent(带规则校验 + 有界Replan)"""
    print("📋 编排行程...")
    try:
        request = state["request"]
        llm = state["llm"]
        retry_count = state.get("retry_count", 0)

        messages = [
            SystemMessage(content="你是一位专业的旅行规划师，擅长根据用户需求制定详细的旅行计划。"),
            HumanMessage(content=_build_plan_prompt(request, state))
        ]

        response = llm.invoke(messages)
        trip_plan = _parse_response(response.content, request)

        issues = _validate_plan(trip_plan, request)
        if issues:
            print(f"⚠️  规则校验未通过,共{len(issues)}项问题")
            # 遇到问题即递增retry_count(=申请一次评审重跑), 边判断 retry_count <= MAX 放行
            return {
                "trip_plan": trip_plan,
                "retry_count": retry_count + 1,
                "validation_issues": issues,
            }

        print("✅ 行程编排完成")
        return {"trip_plan": trip_plan, "retry_count": retry_count, "validation_issues": []}

    except Exception as e:
        print(f"❌ 行程编排失败: {str(e)}")
        return {
            "trip_plan": _create_fallback_plan(state["request"]),
            "retry_count": state.get("retry_count", 0),
            "validation_issues": [],
        }


# ============ Critic Agent: 规则校验 + LLM评审 ============

def _validate_plan(plan: TripPlan, request: TripRequest) -> List[str]:
    """规则校验: 天数/天气覆盖/预算/每日景点与三餐,返回问题列表"""
    issues: List[str] = []
    if not plan:
        return ["行程为空"]

    days = plan.days or []
    if len(days) != request.travel_days:
        issues.append(f"行程天数应为{request.travel_days}天,实际生成了{len(days)}天")

    weather_info = plan.weather_info or []
    if len(weather_info) != request.travel_days:
        issues.append(f"天气信息应覆盖{request.travel_days}天,实际只有{len(weather_info)}天")

    if plan.budget is None:
        issues.append("缺少预算(budget)信息")

    for idx, day in enumerate(days):
        day_no = idx + 1
        if not (day.attractions or []):
            issues.append(f"第{day_no}天没有安排任何景点")
        meal_types = {m.type for m in (day.meals or [])}
        for meal_type, label in (("breakfast", "早餐"), ("lunch", "午餐"), ("dinner", "晚餐")):
            if meal_type not in meal_types:
                issues.append(f"第{day_no}天缺少{label}")

    return issues


def critic_node(state: TripPlanningState) -> TripPlanningState:
    """评审Critic Agent: 针对规则校验问题产出修改指令,回传Builder重跑"""
    print("🔎 LLM评审行程...")
    try:
        plan = state.get("trip_plan")
        request = state["request"]
        issues = state.get("validation_issues") or []
        llm = state.get("llm")

        if plan is None or llm is None or not issues:
            return {"review_feedback": "", "validation_issues": issues}

        plan_json = plan.model_dump_json(indent=2) if hasattr(plan, "model_dump_json") else str(plan)
        prompt = f"""你是资深旅行规划评审(Critic Agent)。以下是生成的行程、规则校验发现的问题、用户需求。

**用户需求:**
- 城市: {request.city}
- 天数: {request.travel_days}天
- 偏好: {", ".join(request.preferences) if request.preferences else "无"}
- 额外要求: {request.free_text_input or "无"}

**行程(JSON):**
{plan_json}

**规则校验发现的问题:**
{chr(10).join(f"- {i}" for i in issues)}

请给出精炼、可执行的修改指令,让行程规划师据此修正。不要自己重写完整行程,输出3-6条要点即可。"""

        feedback = str(llm.invoke([
            SystemMessage(content="你是资深旅行规划评审专家,只输出修改指令要点。"),
            HumanMessage(content=prompt)
        ]).content).strip()

        print(f"🔎 评审完成({len(feedback)}字反馈),回传Builder重跑")
        return {"review_feedback": feedback, "validation_issues": issues}

    except Exception as e:
        print(f"⚠️  LLM评审失败,跳过评审直接出结果: {str(e)}")
        return {"review_feedback": "", "validation_issues": []}


def _should_retry(state: TripPlanningState) -> str:
    """规则校验未通过且重试未超限 → 转Critic评审,否则结束

    retry_count 语义: 已申请的重试次数(builder遇问题时+1),
    因此 retry_count <= MAX_PLAN_RETRIES 时, 该次评审重跑尚未执行, 应放行。
    """
    if state.get("validation_issues") and state.get("retry_count", 0) <= MAX_PLAN_RETRIES:
        return "critic"
    return "end"


# ============ 响应解析与兜底 ============

def _parse_response(response: str, request: TripRequest) -> TripPlan:
    """解析LLM响应为TripPlan,失败回退到兜底计划"""
    try:
        data = _extract_json(response)
        if not data:
            raise ValueError("响应中未找到JSON数据")
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


# ============ 图构建 ============

def dispatch_node(state: TripPlanningState) -> TripPlanningState:
    """分派节点(coordinator): 仅打日志,实际fan-out由条件边返回Send完成"""
    print("🚦 并行分派数据采集任务...")
    return {}


def _dispatch_searches(state: TripPlanningState) -> List[Send]:
    """并行分派数据采集任务的条件边: 返回3个Scout + 天气的Send列表"""
    return [
        Send("attraction_scout", state),
        Send("hotel_scout", state),
        Send("food_scout", state),
        Send("weather_node", state),
    ]


class LangGraphTripPlanner:
    """基于LangGraph的多Agent旅行规划系统"""

    def __init__(self):
        """初始化工作流"""
        print("🔄 初始化LangGraph多Agent旅行规划系统...")
        try:
            self.llm = get_llm()
            self.graph = self._build_graph()
            print("✅ LangGraph多Agent旅行规划系统初始化成功")
        except Exception as e:
            print(f"❌ 初始化失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

    def _build_graph(self) -> StateGraph:
        """构建工作流图"""
        workflow = StateGraph(TripPlanningState)

        workflow.add_node("dispatch", dispatch_node)
        workflow.add_node("attraction_scout", attraction_scout_node)
        workflow.add_node("hotel_scout", hotel_scout_node)
        workflow.add_node("food_scout", food_scout_node)
        workflow.add_node("weather_node", search_weather_node)
        workflow.add_node("builder", builder_node)
        workflow.add_node("critic", critic_node)

        # 数据采集并行 fan-out,全部收敛到 builder
        workflow.set_entry_point("dispatch")
        workflow.add_conditional_edges(
            "dispatch",
            _dispatch_searches,
            ["attraction_scout", "hotel_scout", "food_scout", "weather_node"],
        )
        workflow.add_edge("attraction_scout", "builder")
        workflow.add_edge("hotel_scout", "builder")
        workflow.add_edge("food_scout", "builder")
        workflow.add_edge("weather_node", "builder")

        # 有界Replan: 规则校验失败 → Critic评审 → 带反馈重跑 builder
        workflow.add_conditional_edges(
            "builder",
            _should_retry,
            {"critic": "critic", "end": END},
        )
        workflow.add_edge("critic", "builder")

        return workflow.compile()

    def plan_trip(self, request: TripRequest) -> TripPlan:
        """执行旅行规划"""
        print(f"\n{'='*60}")
        print(f"🚀 开始多Agent旅行规划...")
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
                "hotels": "",
                "foods": "",
                "weather": "",
                "trip_plan": None,
                "validation_issues": [],
                "review_feedback": "",
                "retry_count": 0,
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
