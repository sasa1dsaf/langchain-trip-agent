// 引入 axios：前端专门用来发送网络请求的工具（给后端发消息、拿数据）
import axios from 'axios'

// 引入数据类型：旅行表单数据、旅行计划返回结果的格式
import type { TripFormData, TripPlanResponse } from '@/types'

// 后端接口地址：前端要找的后端服务器地址
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// 创建一个请求客户端：统一配置发请求的规则
const apiClient = axios.create({
  baseURL: API_BASE_URL,   // 后端地址
  timeout: 720000,        // 请求超时时间（2分钟）
  headers: {
    'Content-Type': 'application/json'  // 数据格式用JSON
  }
})

// ==================== 请求拦截器 ====================
// 作用：发请求之前，打印日志（方便看前端有没有发请求）
apiClient.interceptors.request.use(
  (config) => {
    console.log('发送请求:', config.method?.toUpperCase(), config.url)
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// ==================== 响应拦截器 ====================
// 作用：后端返回数据后，打印日志（方便看有没有拿到数据）
apiClient.interceptors.response.use(
  (response) => {
    console.log('收到响应:', response.status, response.config.url)
    return response
  },
  (error) => {
    console.error('响应错误:', error.response?.status, error.message)
    return Promise.reject(error)
  }
)

// ==================== 对外提供的接口方法 ====================

/**
 * 生成旅行计划（核心功能！）
 * 作用：前端把用户填的旅行需求 → 发给后端 → 后端返回AI旅行规划
 */
export async function generateTripPlan(formData: TripFormData): Promise<TripPlanResponse> {
  try {
    // 向后端发送POST请求，地址是 /api/trip/plan
    const response = await apiClient.post<TripPlanResponse>('/api/trip/plan', formData)
    // 返回后端给的旅行计划数据
    return response.data
  } catch (error: any) {
    console.error('生成旅行计划失败:', error)
    throw new Error(error.response?.data?.detail || error.message || '生成旅行计划失败')
  }
}

/**
 * 健康检查
 * 作用：检查后端服务器是否正常运行
 */
export async function healthCheck(): Promise<any> {
  try {
    const response = await apiClient.get('/health')
    return response.data
  } catch (error: any) {
    console.error('健康检查失败:', error)
    throw new Error(error.message || '健康检查失败')
  }
}

// 默认导出客户端，供其他文件使用
export default apiClient