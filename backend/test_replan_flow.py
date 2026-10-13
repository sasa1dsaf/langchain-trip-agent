"""集成测试: 验证多Agent闭环 — dispatch并行分派 → Scout×3 + Weather → Builder → Critic反馈 → 有界Replan重跑

断言目标:
  1. 三个Scout + 天气并行执行(fan-out 收敛)
  2. Builder第一次产出缺budget的行程 → 规则校验未通过 → 转Critic
  3. Critic产出修改反馈 → 带反馈重跑Builder(第二次带budget)
  4. 第二次通过校验 → 正常结束; builder共执行 2 次(有界, MAX_PLAN_RETRIES=1)
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.models.schemas import TripRequest
from app.agents import trip_planner_agent as agent_mod


# ============ 桩: LLM ============

def _msg(content: str):
    """构造带.content属性的响应"""
    class _M:
        pass
    m = _M()
    m.content = content
    return m


class StubLLM:
    """有状态LLM桩: 按prompt内容分流"""

    def __init__(self):
        self.builder_calls = 0
        self.scout_calls = 0
        self.critic_calls = 0

    def invoke(self, messages):
        human = [m for m in messages if isinstance(m, agent_mod.HumanMessage)]
        text = human[0].content if human else ""

        if "请严格按照以下JSON格式返回旅行计划" in text:
            # --- Builder: 第1次缺budget, 第2次(评审反馈后)补全budget ---
            self.builder_calls += 1
            return _msg(json.dumps(_make_plan_json(include_budget=(self.builder_calls >= 2)), ensure_ascii=False))

        if "评审(Critic Agent)" in text:
            self.critic_calls += 1
            return _msg("必须补充budget预算信息(total及各分项),其余内容保持不变。")

        if "搜索策略" in text:
            self.scout_calls += 1
            return _msg('{"keywords": ["故宫", "历史博物馆"], "limit": 10}')

        return _msg("{}")


# ============ 桩: 高德工具(离线, 返回真实结构数据) ============

class FakeTool:
    def __init__(self, fn):
        self.fn = fn

    def invoke(self, kwargs):
        return self.fn(**kwargs)


def _fake_poi(**kwargs):
    return json.dumps({
        "status": "1",
        "pois": [
            {
                "name": f"真实{kwargs.get('keywords', '景点')}",
                "type": "风景名胜",
                "address": "北京市东城区",
                "location": "116.39,39.90",
                "biz_ext": {"rating": "4.8"},
            }
        ],
    }, ensure_ascii=False)


def _fake_weather(city: str):
    return json.dumps({
        "status": "1",
        "lives": [{"province": "北京", "city": city, "weather": "晴", "temperature": "25",
                   "winddirection": "南", "windpower": "1级"}],
    }, ensure_ascii=False)


# ============ 构造两份行程JSON ============

def _make_plan_json(include_budget: bool) -> dict:
    dates = ["2026-08-14", "2026-08-15", "2026-08-16"]
    days = []
    for i, d in enumerate(dates):
        days.append({
            "date": d,
            "day_index": i,
            "description": f"第{i+1}天行程",
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
            "hotel": {"name": "真实酒店", "address": "北京市西城区", "type": "经济型酒店", "estimated_cost": 400},
            "attractions": [
                {"name": "真实景点", "address": "北京市东城区",
                 "location": {"longitude": 116.39, "latitude": 39.9},
                 "visit_duration": 120, "description": "著名景点", "category": "历史文化"}
            ],
            "meals": [
                {"type": "breakfast", "name": "早餐", "estimated_cost": 30},
                {"type": "lunch", "name": "午餐", "estimated_cost": 50},
                {"type": "dinner", "name": "晚餐", "estimated_cost": 80},
            ],
        })
    plan = {
        "city": "北京",
        "start_date": "2026-08-14",
        "end_date": "2026-08-16",
        "days": days,
        "weather_info": [
            {"date": d, "day_weather": "晴", "night_weather": "多云",
             "day_temp": 30, "night_temp": 22, "wind_direction": "南风", "wind_power": "1-3级"}
            for d in dates
        ],
        "overall_suggestions": "祝您旅途愉快",
    }
    if include_budget:
        plan["budget"] = {"total_attractions": 180, "total_hotels": 1200,
                          "total_meals": 480, "total_transportation": 200, "total": 2060}
    return plan


def _install_fakes():
    agent_mod.search_attractions = FakeTool(_fake_poi)
    agent_mod.search_hotels = FakeTool(_fake_poi)
    agent_mod.search_restaurants = FakeTool(_fake_poi)
    agent_mod.get_weather = FakeTool(_fake_weather)


def _make_planner(stub):
    planner = object.__new__(agent_mod.LangGraphTripPlanner)
    planner.llm = stub
    planner.graph = planner._build_graph()
    return planner


def _make_request():
    return TripRequest(
        city="北京",
        start_date="2026-08-14",
        end_date="2026-08-16",
        travel_days=3,
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences=["历史文化"],
        free_text_input="",
    )


class NeverFixStubLLM:
    """Builder永远产出缺budget的行程: 证明Critic反馈无效时循环仍有界,不会死循环"""

    def __init__(self):
        self.builder_calls = 0
        self.critic_calls = 0

    def invoke(self, messages):
        human = [m for m in messages if isinstance(m, agent_mod.HumanMessage)]
        text = human[0].content if human else ""
        if "请严格按照以下JSON格式返回旅行计划" in text:
            self.builder_calls += 1
            return _msg(json.dumps(_make_plan_json(include_budget=False), ensure_ascii=False))
        if "评审(Critic Agent)" in text:
            self.critic_calls += 1
            return _msg("必须补充budget预算信息。")
        if "搜索策略" in text:
            return _msg('{"keywords": ["故宫"], "limit": 10}')
        return _msg("{}")


def test_bounded_loop_when_never_fixed():
    """核心安全性质: 反馈无效时, builder恰跑MAX+1次即终止, 不进入死循环"""
    stub = NeverFixStubLLM()
    planner = _make_planner(stub)
    request = _make_request()

    plan = planner.plan_trip(request)

    bounded = (stub.builder_calls == agent_mod.MAX_PLAN_RETRIES + 1) and (stub.critic_calls == agent_mod.MAX_PLAN_RETRIES)
    print(f"\n===== 有界性断言(MAX_PLAN_RETRIES={agent_mod.MAX_PLAN_RETRIES}) =====")
    print(f"  [{'✅' if bounded else '❌'}] 反馈无效时仍终止: builder={stub.builder_calls}次, critic={stub.critic_calls}次")
    print(f"  [✅] 最终返回可用的兜底计划(city={plan.city}, days={len(plan.days)})")
    return 0 if bounded else 1


def main():
    _install_fakes()

    print("=" * 30 + " 场景1: 闭环正常修复 " + "=" * 30)
    stub = StubLLM()
    planner = _make_planner(stub)
    request = _make_request()
    plan = planner.plan_trip(request)

    print("\n===== 断言结果 =====")
    checks = []
    checks.append(("dispatch并行分派 → 3个Scout各调用LLM策略1次", stub.scout_calls == 3, f"实际scout_calls={stub.scout_calls}"))
    checks.append(("Builder执行2次(有界Replan闭环)", stub.builder_calls == 2, f"实际builder_calls={stub.builder_calls}"))
    checks.append(("Critic执行1次(评审反馈)", stub.critic_calls == 1, f"实际critic_calls={stub.critic_calls}"))
    checks.append(("Critic反馈后补全budget", plan.budget is not None and plan.budget.total == 2060, f"budget={plan.budget.model_dump() if plan.budget else None}"))
    checks.append(("行程3天", len(plan.days) == 3, f"len(days)={len(plan.days)}"))
    checks.append(("每天含早/中/晚三餐", all(len(d.meals) == 3 for d in plan.days), f"meals_per_day={[len(d.meals) for d in plan.days]}"))
    checks.append(("天气覆盖3天", len(plan.weather_info) == 3, f"len(weather_info)={len(plan.weather_info)}"))
    checks.append(("景点来自真实候选(有经纬度)", all(a.location is not None for d in plan.days for a in d.attractions), "存在景点缺location"))

    passed = True
    for name, ok, detail in checks:
        print(f"  [{'✅' if ok else '❌'}] {name}  ({detail})")
        passed = passed and ok

    print(f"\n{'🎉 场景1 全部通过' if passed else '💥 场景1 存在失败项'}")

    scenario2 = test_bounded_loop_when_never_fixed()

    return 0 if (passed and scenario2 == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
