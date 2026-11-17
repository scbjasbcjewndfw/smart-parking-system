<script setup>
// 根组件只承载路由出口，具体页面由 router 决定
</script>

<template>
  <div class="wrapper">
    <router-view />
  </div>
</template>

<style scoped>
.wrapper {
  min-height: 100vh;
}
</style>
