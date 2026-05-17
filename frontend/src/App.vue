<!-- 整个页面的结构部分（相当于 HTML） -->
<template>
  <!-- 整个应用的根容器 -->
  <div id="app">
    <!-- 页面整体布局：顶部栏 + 内容区 + 底部栏 -->
    <a-layout style="min-height: 100vh">

      <!-- 顶部导航栏（深蓝色背景） -->
      <a-layout-header style="background: #001529; padding: 0 50px">
        <!-- 顶部标题：智能旅行助手名称 -->
        <div style="color: white; font-size: 24px; font-weight: bold">
          🌍 HelloAgents智能旅行助手
        </div>
      </a-layout-header>

      <!-- 中间内容区域（所有页面都在这里显示） -->
      <a-layout-content style="padding: 24px">
        <!-- 页面切换容器：首页/结果页在这里切换显示 -->
        <router-view />
      </a-layout-content>

      <!-- 页面底部版权信息 -->
      <a-layout-footer style="text-align: center">
        HelloAgents智能旅行助手 ©2025 基于HelloAgents框架
      </a-layout-footer>

    </a-layout>
  </div>
</template>

<!-- 脚本逻辑部分（这里是空的，暂时没有功能代码） -->
<script setup lang="ts">
</script>

<!-- 页面样式（字体、排版设置） -->
<style>
#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans', sans-serif;
}
</style>