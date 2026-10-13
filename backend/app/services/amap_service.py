"""高德地图服务封装 - 直接调用HTTP API"""

import json
import time
from typing import List, Dict, Any, Optional
import httpx
from ..config import get_settings
from ..models.schemas import Location, POIInfo, WeatherInfo


class AmapService:
    """高德地图服务封装类"""
    
    def __init__(self):
        """初始化服务"""
        settings = get_settings()
        if not settings.amap_api_key:
            raise ValueError("高德地图API Key未配置,请在.env文件中设置AMAP_API_KEY")
        
        self.api_key = settings.amap_api_key
        self.base_url = "https://restapi.amap.com/v3"
        self.client = httpx.AsyncClient(timeout=30)

        # 工具结果内存缓存: key -> (缓存时间戳, JSON字符串); 失败结果不入缓存
        self._cache: Dict[str, tuple] = {}
        # 各操作的缓存有效期(秒)
        self._cache_ttl: Dict[str, int] = {
            "poi": 3600,      # POI数据变化慢,缓存1小时
            "weather": 1800,  # 天气数据更新快,缓存30分钟
        }

        print(f"✅ 高德地图服务初始化成功")

    def _cache_get(self, key: str, ttl: int) -> Optional[str]:
        """读取缓存, 过期则清除并返回None"""
        item = self._cache.get(key)
        if item is None:
            return None
        cached_at, value = item
        if time.time() - cached_at > ttl:
            del self._cache[key]
            return None
        return value

    def _cache_set(self, key: str, value: str) -> None:
        """写入缓存"""
        self._cache[key] = (time.time(), value)

    async def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> List[POIInfo]:
        """
        搜索POI
        
        Args:
            keywords: 搜索关键词
            city: 城市
            citylimit: 是否限制在城市范围内
            
        Returns:
            POI信息列表
        """
        try:
            url = f"{self.base_url}/place/text"
            params = {
                "keywords": keywords,
                "city": city,
                "citylimit": "true" if citylimit else "false",
                "key": self.api_key,
                "output": "json"
            }
            
            response = await self.client.get(url, params=params)
            result = response.json()
            
            print(f"POI搜索结果: {json.dumps(result)[:200]}...")
            
            if result.get("status") == "1":
                return [POIInfo(**poi) for poi in result.get("pois", [])]
            return []
            
        except Exception as e:
            print(f"❌ POI搜索失败: {str(e)}")
            return []
    
    async def get_weather(self, city: str) -> List[WeatherInfo]:
        """
        查询天气
        
        Args:
            city: 城市名称
            
        Returns:
            天气信息列表
        """
        try:
            url = f"{self.base_url}/weather/weatherInfo"
            params = {
                "city": city,
                "key": self.api_key,
                "output": "json"
            }
            
            response = await self.client.get(url, params=params)
            result = response.json()
            
            print(f"天气查询结果: {json.dumps(result)[:200]}...")
            
            if result.get("status") == "1":
                return [WeatherInfo(**weather) for weather in result.get("lives", [])]
            return []
            
        except Exception as e:
            print(f"❌ 天气查询失败: {str(e)}")
            return []
    
    def search_poi_sync(self, keywords: str, city: str, citylimit: bool = True) -> str:
        """
        同步搜索POI（用于同步工具调用, 带结果缓存）
        """
        cache_key = f"poi|{keywords}|{city}|{citylimit}"
        cached = self._cache_get(cache_key, self._cache_ttl["poi"])
        if cached is not None:
            print(f"⚡ POI缓存命中: {keywords} {city}")
            return cached
        try:
            url = f"{self.base_url}/place/text"
            params = {
                "keywords": keywords,
                "city": city,
                "citylimit": "true" if citylimit else "false",
                "key": self.api_key,
                "output": "json"
            }
            
            with httpx.Client(timeout=30) as client:
                response = client.get(url, params=params)
                result = response.json()
            
            print(f"POI搜索结果: {json.dumps(result)[:200]}...")
            json_str = json.dumps(result)
            self._cache_set(cache_key, json_str)
            return json_str

        except Exception as e:
            print(f"❌ POI搜索失败: {str(e)}")
            return json.dumps({"error": str(e), "data": []})
    
    def get_weather_sync(self, city: str) -> str:
        """
        同步查询天气（用于同步工具调用, 带结果缓存）
        """
        cache_key = f"weather|{city}"
        cached = self._cache_get(cache_key, self._cache_ttl["weather"])
        if cached is not None:
            print(f"⚡ 天气缓存命中: {city}")
            return cached
        try:
            url = f"{self.base_url}/weather/weatherInfo"
            params = {
                "city": city,
                "key": self.api_key,
                "output": "json"
            }
            
            with httpx.Client(timeout=30) as client:
                response = client.get(url, params=params)
                result = response.json()
            
            print(f"天气查询结果: {json.dumps(result)[:200]}...")
            json_str = json.dumps(result)
            self._cache_set(cache_key, json_str)
            return json_str

        except Exception as e:
            print(f"❌ 天气查询失败: {str(e)}")
            return json.dumps({"error": str(e), "data": []})
    
    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking"
    ) -> Dict[str, Any]:
        """
        规划路线
        
        Args:
            origin_address: 起点地址
            destination_address: 终点地址
            origin_city: 起点城市
            destination_city: 终点城市
            route_type: 路线类型 (walking/driving/transit)
            
        Returns:
            路线信息
        """
        try:
            url_map = {
                "walking": f"{self.base_url}/direction/walking",
                "driving": f"{self.base_url}/direction/driving",
                "transit": f"{self.base_url}/direction/transit/integrated"
            }
            
            url = url_map.get(route_type, url_map["walking"])
            params = {
                "origin": origin_address,
                "destination": destination_address,
                "key": self.api_key,
                "output": "json"
            }
            
            if origin_city:
                params["origin_city"] = origin_city
            if destination_city:
                params["destination_city"] = destination_city
            
            with httpx.Client(timeout=30) as client:
                response = client.get(url, params=params)
                result = response.json()
            
            print(f"路线规划结果: {json.dumps(result)[:200]}...")
            return result
            
        except Exception as e:
            print(f"❌ 路线规划失败: {str(e)}")
            return {}
    
    def geocode(self, address: str, city: Optional[str] = None) -> Optional[Location]:
        """
        地理编码(地址转坐标)

        Args:
            address: 地址
            city: 城市

        Returns:
            经纬度坐标
        """
        try:
            url = f"{self.base_url}/geocode/geo"
            params = {
                "address": address,
                "key": self.api_key,
                "output": "json"
            }
            if city:
                params["city"] = city

            with httpx.Client(timeout=30) as client:
                response = client.get(url, params=params)
                result = response.json()

            print(f"地理编码结果: {json.dumps(result)[:200]}...")

            if result.get("status") == "1" and result.get("geocodes"):
                geocode = result["geocodes"][0]
                location = geocode.get("location", "").split(",")
                if len(location) == 2:
                    return Location(longitude=float(location[0]), latitude=float(location[1]))

            return None

        except Exception as e:
            print(f"❌ 地理编码失败: {str(e)}")
            return None

    def get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        """
        获取POI详情

        Args:
            poi_id: POI ID

        Returns:
            POI详情信息
        """
        try:
            url = f"{self.base_url}/place/detail"
            params = {
                "id": poi_id,
                "key": self.api_key,
                "output": "json"
            }

            with httpx.Client(timeout=30) as client:
                response = client.get(url, params=params)
                result = response.json()

            print(f"POI详情结果: {json.dumps(result)[:200]}...")
            return result

        except Exception as e:
            print(f"❌ 获取POI详情失败: {str(e)}")
            return {}


_amap_service = None


def get_amap_service() -> AmapService:
    """获取高德地图服务实例(单例模式)"""
    global _amap_service
    
    if _amap_service is None:
        _amap_service = AmapService()
    
    return _amap_service