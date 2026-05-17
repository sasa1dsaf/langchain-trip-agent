"""高德地图工具模块 - LangChain工具封装"""

import json
from typing import List
from langchain_core.tools import tool, BaseTool
from ..services.amap_service import get_amap_service


@tool
def search_attractions(keywords: str, city: str) -> str:
    """
    搜索景点
    
    Args:
        keywords: 搜索关键词，如"历史文化"、"公园"、"景点"
        city: 城市名称
    
    Returns:
        JSON格式的景点列表
    """
    try:
        amap_service = get_amap_service()
        result = amap_service.search_poi_sync(keywords, city)
        return result
    except Exception as e:
        return json.dumps({"error": str(e), "data": []})


@tool
def search_hotels(city: str, keywords: str = "酒店") -> str:
    """
    搜索酒店
    
    Args:
        city: 城市名称
        keywords: 搜索关键词，默认为"酒店"
    
    Returns:
        JSON格式的酒店列表
    """
    try:
        amap_service = get_amap_service()
        result = amap_service.search_poi_sync(keywords, city)
        return result
    except Exception as e:
        return json.dumps({"error": str(e), "data": []})


@tool
def get_weather(city: str) -> str:
    """
    查询天气
    
    Args:
        city: 城市名称
    
    Returns:
        JSON格式的天气信息
    """
    try:
        amap_service = get_amap_service()
        result = amap_service.get_weather_sync(city)
        return result
    except Exception as e:
        return json.dumps({"error": str(e), "data": []})


def get_amap_tools() -> List[BaseTool]:
    """
    获取所有高德地图工具
    
    Returns:
        工具列表
    """
    return [
        search_attractions,
        search_hotels,
        get_weather
    ]