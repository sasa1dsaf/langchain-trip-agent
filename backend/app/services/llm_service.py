"""LLM服务模块 - LangChain封装"""

import os
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from ..config import get_settings

_llm_instance = None


def get_llm() -> BaseChatModel:
    """
    获取LLM实例(单例模式)
    
    Returns:
        LangChain BaseChatModel实例
    """
    global _llm_instance
    
    if _llm_instance is None:
        settings = get_settings()
        
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or settings.openai_api_key
        base_url = os.getenv("LLM_BASE_URL") or settings.openai_base_url
        model = os.getenv("LLM_MODEL_ID") or settings.openai_model
        
        if not api_key:
            raise ValueError("LLM_API_KEY或OPENAI_API_KEY未配置")
        
        _llm_instance = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.7
        )
        
        print(f"✅ LLM服务初始化成功")
        print(f"   模型: {_llm_instance.model_name}")
        print(f"   Base URL: {base_url}")
    
    return _llm_instance


def reset_llm():
    """重置LLM实例(用于测试或重新配置)"""
    global _llm_instance
    _llm_instance = None