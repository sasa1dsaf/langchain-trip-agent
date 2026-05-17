// 1. 引入需要的工具（Vue自带功能）
import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'

// 2. 引入UI组件库（按钮、布局、卡片这些好看的样式）
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'

// 3. 引入3个核心文件
import App from './App.vue'      // 整个应用的外壳（你刚才看的那个）
import Home from './views/Home.vue'  // 首页
import Result from './views/Result.vue' // 结果页

// =============================================
// 4. 重点：创建路由表（网址 ↔ 页面 对应关系）
// =============================================
const router = createRouter({
  history: createWebHistory(),  // 使用浏览器网址模式
  routes: [
    // 网址是 /       → 显示首页 Home.vue
    { path: '/', name: 'Home', component: Home },
    
    // 网址是 /result → 显示结果页 Result.vue
    { path: '/result', name: 'Result', component: Result }
  ]
})

// 5. 创建Vue应用
const app = createApp(App)

// 6. 给应用安装功能
app.use(router)   // 安装路由（页面切换功能）
app.use(Antd)     // 安装UI库（好看的按钮、布局）

// 7. 把应用挂载到页面上 → 项目启动！
app.mount('#app')