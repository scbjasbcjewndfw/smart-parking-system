<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/api/request'
import { assertPlate, isValidPlate, normalizePlate } from '@/utils/plate'
import CustomerService from '@/components/CustomerService.vue'

/* ========== 登录 ========== */
const isLoggedIn = ref(false)
const currentUser = ref('')
const loginForm = ref({ username: '', password: '' })
const loginLoading = ref(false)

/* 注册 */
const registerVisible = ref(false)
const registerLoading = ref(false)
const registerForm = ref({ username: '', password: '' })

async function handleLogin() {
  if (!loginForm.value.username || !loginForm.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loginLoading.value = true
  try {
    const res = await request.post('/user/login', {
      username: loginForm.value.username,
      password: loginForm.value.password,
    })
    if (res.data.code === 200) {
      const token = res.data.data.access_token
      localStorage.setItem('access_token', token)
      localStorage.setItem('username', res.data.data.username)
      currentUser.value = res.data.data.username
      isLoggedIn.value = true
      activeMenu.value = 'recognize'
      ElMessage.success('登录成功，欢迎回来！')
    } else {
      ElMessage.error(res.data.msg || '登录失败')
    }
  } catch (err) {
    const msg = err.response?.data?.msg || err.message
    ElMessage.error('登录失败：' + msg)
  } finally {
    loginLoading.value = false
  }
}

function handleLogout() {
  closeCamera()
  isLoggedIn.value = false
  currentUser.value = ''
  userProfile.value = null
  loginForm.value = { username: '', password: '' }
  localStorage.removeItem('access_token')
  localStorage.removeItem('username')
  resetSessionState()
  ElMessage.info('已退出登录')
}

async function handleRegister() {
  const { username, password } = registerForm.value
  if (!username || !password) {
    ElMessage.warning('请填写用户名和密码')
    return
  }
  registerLoading.value = true
  try {
    const res = await request.post('/user/register', { username, password })
    if (res.data.code === 200) {
      ElMessage.success('注册成功，请登录')
      registerVisible.value = false
      registerForm.value = { username: '', password: '' }
    } else {
      ElMessage.error(res.data.msg || '注册失败')
    }
  } catch (err) {
    const msg = err.response?.data?.msg || err.message
    ElMessage.error('注册失败：' + msg)
  } finally {
    registerLoading.value = false
  }
}

/* 页面加载时检查是否已登录 */
const savedToken = localStorage.getItem('access_token')
const savedUsername = localStorage.getItem('username')
if (savedToken && savedUsername) {
  currentUser.value = savedUsername
  isLoggedIn.value = true
}

/* ========== 注销账号 ========== */
const cancelVisible = ref(false)
const cancelLoading = ref(false)
const cancelForm = ref({ username: '', password: '' })

async function handleCancelAccount() {
  const { username, password } = cancelForm.value
  if (!username || !password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  if (username !== currentUser.value) {
    ElMessage.warning('只能注销当前登录账号')
    return
  }
  cancelLoading.value = true
  try {
    const res = await request.delete('/user/delete', { data: { username, password } })
    if (res.data.code === 200) {
      ElMessage.success('账号注销成功')
      cancelVisible.value = false
      cancelForm.value = { username: '', password: '' }
      handleLogout()
    } else {
      ElMessage.error(res.data.msg || '注销失败')
    }
  } catch (err) {
    const msg = err.response?.data?.msg || err.message
    ElMessage.error('注销失败：' + msg)
  } finally {
    cancelLoading.value = false
  }
}

/* ========== 侧边菜单切换 ========== */
const activeMenu = ref('recognize')

function handleMenuSelect(index) {
  activeMenu.value = index
  // 切换菜单时释放摄像头，否则视频流会一直占用设备
  if (index !== 'recognize' && cameraActive.value) closeCamera()
  if (index === 'profile' && !userProfile.value) {
    loadUserProfile()
  }
}


/* ========== 车牌识别（/plate/recognize） ========== */
const imageUrl = ref('')
const fileName = ref('')
const recognizeLoading = ref(false)
const detectResult = ref(null) // { plate, ocr_score, yolo_conf, result_image, plate_valid }
const recognizeTime = ref(null) // 图片上传/识别成功的时刻，作为入场时间默认值
const uploadFileList = ref([]) // el-upload 受控文件列表，替代 document.querySelector 取文件

function handleFileChange(file, files) {
  // 只保留最后选择的一张，避免多次拖拽后取到旧文件
  uploadFileList.value = files.slice(-1)
  const f = file.raw
  fileName.value = f.name
  detectResult.value = null
  const reader = new FileReader()
  reader.onload = (e) => { imageUrl.value = e.target.result }
  reader.readAsDataURL(f)
}

/* 清空与登录态绑定的业务数据，避免换账号后看到上一个账号的残留 */
function resetSessionState() {
  entryRecords.value = []
  detectResult.value = null
  imageUrl.value = ''
  fileName.value = ''
  uploadFileList.value = []
  queryResult.value = null
  queriedPlate.value = ''
  feeResult.value = null
  activeMenu.value = 'recognize'
}

/* 核心识别逻辑：上传图片 / 拍照 复用同一接口 */
async function recognizeImage(file) {
  if (!file) {
    ElMessage.warning('请先选择图片')
    return
  }
  const formData = new FormData()
  formData.append('image', file)

  recognizeLoading.value = true
  detectResult.value = null
  try {
    // 不手动设置 Content-Type：交给浏览器生成带 boundary 的 multipart 头，
    // 手动指定会导致部分环境下后端收不到文件
    const res = await request.post('/plate/recognize', formData)
    if (res.data.code === 200) {
      detectResult.value = res.data.data
      recognizeTime.value = new Date()
      ElMessage.success(res.data.msg || '识别成功')
    } else {
      ElMessage.error(res.data.msg || '识别失败')
    }
  } catch (err) {
    const msg = err.response?.data?.msg || err.message
    ElMessage.error('识别失败：' + msg)
  } finally {
    recognizeLoading.value = false
  }
}

async function handleRecognize() {
  // 从受控文件列表取，不再用 document.querySelector('input[type=file]')：
  // 页面上存在多个 file input 时会取错文件
  const file = uploadFileList.value[0]?.raw
  if (!file) {
    ElMessage.warning('请先选择图片')
    return
  }
  await recognizeImage(file)
}

/* ========== 拍照识别（复用 /plate/recognize） ========== */
const recognizeMode = ref('upload') // upload | camera
const videoRef = ref(null)
const cameraStream = ref(null)
const cameraActive = ref(false)
const cameraImgUrl = ref('')
const cameraLoading = ref(false)

async function openCamera() {
  if (cameraActive.value) return
  if (!navigator.mediaDevices?.getUserMedia) {
    ElMessage.error('当前浏览器不支持摄像头，需在 HTTPS 或 localhost 下访问')
    return
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' },
      audio: false,
    })
    cameraStream.value = stream
    cameraActive.value = true
    cameraImgUrl.value = ''
    // 等 DOM 渲染 video 后绑定流
    setTimeout(() => {
      if (videoRef.value) {
        videoRef.value.srcObject = stream
        videoRef.value.play().catch(() => {})
      }
    }, 50)
  } catch (err) {
    const msg = err.name === 'NotAllowedError' ? '已拒绝摄像头权限'
      : err.name === 'NotFoundError' ? '未检测到摄像头设备'
      : err.message
    ElMessage.error('打开摄像头失败：' + msg)
  }
}

function closeCamera() {
  if (cameraStream.value) {
    cameraStream.value.getTracks().forEach((t) => t.stop())
    cameraStream.value = null
  }
  cameraActive.value = false
  if (cameraImgUrl.value) {
    URL.revokeObjectURL(cameraImgUrl.value)
    cameraImgUrl.value = ''
  }
}

function onModeChange(val) {
  // 切换离开拍照模式时自动关闭摄像头
  if (val !== 'camera' && cameraActive.value) closeCamera()
}

async function takePhoto() {
  if (!videoRef.value || !cameraActive.value) {
    ElMessage.warning('请先打开摄像头')
    return
  }
  const video = videoRef.value
  if (!video.videoWidth) {
    ElMessage.warning('摄像头尚未就绪，请稍候')
    return
  }
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  const ctx = canvas.getContext('2d')
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
  cameraLoading.value = true
  canvas.toBlob(async (blob) => {
    if (!blob) {
      cameraLoading.value = false
      ElMessage.error('拍照失败')
      return
    }
    if (cameraImgUrl.value) URL.revokeObjectURL(cameraImgUrl.value)
    cameraImgUrl.value = URL.createObjectURL(blob)
    await recognizeImage(blob)
    cameraLoading.value = false
  }, 'image/jpeg', 0.92)
}

/* 把识别到的车牌带入入场登记 */
function usePlateForEntry() {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return
  }
  if (detectResult.value?.plate) {
    entryForm.value.plate = normalizePlate(detectResult.value.plate)
    activeMenu.value = 'entry'
    ElMessage.success('已带入车牌，请核对后确认入场')
  }
}

/* 识别后弹确认框 → 确认则自动入场并跳转计费界面 */
const confirmEntryVisible = ref(false)
const pendingPlate = ref('')

function confirmPlateAndEntry() {
  if (!detectResult.value?.plate) {
    ElMessage.warning('没有可用的识别车牌')
    return
  }
  pendingPlate.value = detectResult.value.plate
  confirmEntryVisible.value = true
}

async function doConfirmEntry() {
  let plate
  try {
    plate = assertPlate(pendingPlate.value)
  } catch (err) {
    ElMessage.warning(err.message)
    return
  }
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    confirmEntryVisible.value = false
    return
  }
  try {
    const res = await request.post('/plate/entry', { plate })
    if (res.data.code === 200) {
      const d = res.data.data
      entryRecords.value.unshift({
        record_id: d.record_id,
        plate: d.plate,
        in_time: d.in_time,
      })
      // 带入计费表单并跳转
      feeForm.value.plate = normalizePlate(d.plate)
      feeForm.value.in_time = formatPickerTime(d.in_time)
      feeForm.value.out_time = null
      feeResult.value = null
      activeMenu.value = 'fee'
      ElMessage.success('入场成功，已跳转计费界面')
      confirmEntryVisible.value = false
    } else {
      ElMessage.error(res.data.msg || '入场登记失败')
    }
  } catch (err) {
    const msg = err.response?.data?.msg || err.message
    ElMessage.error('入场登记失败：' + msg)
  }
}

/* ========== 入场登记（/plate/entry） ========== */
const entryForm = ref({ plate: '' })
const entryLoading = ref(false)
const entryRecords = ref([]) // 本次会话登记记录

async function handleEntry() {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return
  }
  let plate
  try {
    plate = assertPlate(entryForm.value.plate)
  } catch (err) {
    ElMessage.warning(err.message)
    return
  }
  entryLoading.value = true
  try {
    const res = await request.post('/plate/entry', { plate })
    if (res.data.code === 200) {
      const d = res.data.data
      entryRecords.value.unshift({
        record_id: d.record_id,
        plate: d.plate,
        in_time: d.in_time,
      })
      ElMessage.success('入场登记成功：' + d.plate)
      entryForm.value.plate = ''
    } else {
      ElMessage.error(res.data.msg || '入场登记失败')
    }
  } catch (err) {
    const msg = err.response?.data?.msg || err.message
    ElMessage.error('入场登记失败：' + msg)
  } finally {
    entryLoading.value = false
  }
}

function formatDateTime(t) {
  if (!t) return '--'
  const d = new Date(t)
  if (isNaN(d.getTime())) return t
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/* ========== 我的信息（/user/profile，需 JWT） ========== */
const userProfile = ref(null)
const profileLoading = ref(false)

async function loadUserProfile() {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return
  }
  profileLoading.value = true
  try {
    const res = await request.get('/user/profile')
    if (res.data.code === 200) {
      userProfile.value = res.data.data
    } else {
      ElMessage.error(res.data.msg || '获取用户信息失败')
    }
  } catch (err) {
    const msg = err.response?.data?.msg || err.message
    ElMessage.error('获取用户信息失败：' + msg)
  } finally {
    profileLoading.value = false
  }
}

/* ========== 停车计费（/parking/fee） ========== */
const feeForm = ref({
  plate: '',
  in_time: null,
  out_time: null,
})
const feeLoading = ref(false)
const feeResult = ref(null) // 计费返回结果

/* 禁用未来日期：出场时间不可能是未来（后端也有同样校验） */
function disableFutureDate(date) {
  return date.getTime() > Date.now()
}

/* el-date-picker 绑定的是 Date 对象，提交时格式化为后端要求的 YYYY-MM-DD HH:mm */
function formatPickerTime(d) {  if (!d) return null
  const date = d instanceof Date ? d : new Date(d)
  if (isNaN(date.getTime())) return null
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

async function handleCalculateFee() {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return
  }
  let plate
  try {
    plate = assertPlate(feeForm.value.plate)
  } catch (err) {
    ElMessage.warning(err.message)
    return
  }
  const in_time = formatPickerTime(feeForm.value.in_time)
  const out_time = formatPickerTime(feeForm.value.out_time)
  if (!in_time || !out_time) {
    ElMessage.warning('请选择入场和出场时间')
    return
  }
  // 与后端 CLOCK_TOLERANCE 对齐：允许 5 分钟时钟误差，其余视为填错
  if (new Date(out_time).getTime() > Date.now() + 5 * 60 * 1000) {
    ElMessage.warning('出场时间不能晚于当前时间')
    return
  }
  feeLoading.value = true
  feeResult.value = null
  try {
    const res = await request.post('/parking/fee', {
      plate,
      in_time,
      out_time,
    })
    if (res.data.code === 200) {
      feeResult.value = res.data.data
      ElMessage.success('计费成功：应付 ¥' + res.data.data.total_fee)
    } else {
      ElMessage.error(res.data.msg || '计费失败')
    }
  } catch (err) {
    const msg = err.response?.data?.msg || err.message
    ElMessage.error('计费失败：' + msg)
  } finally {
    feeLoading.value = false
  }
}

function clearFeeForm() {
  feeForm.value = { plate: '', in_time: null, out_time: null }
  feeResult.value = null
}

/* 从识别结果带入车牌到计费表单，入场时间默认为图片上传时刻 */
function usePlateForFee() {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return
  }
  if (detectResult.value?.plate) {
    feeForm.value.plate = normalizePlate(detectResult.value.plate)
    if (recognizeTime.value) {
      feeForm.value.in_time = formatPickerTime(recognizeTime.value)
    }
    activeMenu.value = 'fee'
    ElMessage.success('已带入车牌，入场时间已按图片上传时刻填写')
  }
}



/* ========== 车牌查询（/parking/query?plate=xxx） ========== */
const queryForm = ref({ plate: '', pay_status: 'all' })
const queryLoading = ref(false)
const queryResult = ref(null) // { user, orders, total }
const queriedPlate = ref('') // 本次查询实际使用的车牌，用于避免输入框变化导致提示错位
const payingOrderId = ref(null) // 正在支付的订单号，按行显示 loading

async function handlePay(orderId) {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return
  }
  payingOrderId.value = orderId
  try {
    const res = await request.put(`/parking/pay/${orderId}`)
    if (res.data.code === 200) {
      ElMessage.success('付款成功')
      // 刷新当前查询结果
      handleQueryByPlate()
    } else {
      ElMessage.error(res.data.msg || '付款失败')
    }
  } catch (err) {
    const msg = err.response?.data?.msg || err.message
    ElMessage.error('付款失败：' + msg)
  } finally {
    payingOrderId.value = null
  }
}

async function handleQueryByPlate() {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return
  }
  const plate = normalizePlate(queryForm.value.plate)
  if (plate && !isValidPlate(plate)) {
    ElMessage.warning('车牌号格式不正确，应为 省份简称+字母+5~6 位（如 皖AD03683）')
    return
  }
  queryLoading.value = true
  queryResult.value = null
  queriedPlate.value = plate
  try {
    const res = await request.get('/parking/query', {
      params: { plate, pay_status: queryForm.value.pay_status },
    })
    if (res.data.code === 200) {
      queryResult.value = res.data.data
      // 只有填了车牌却没匹配到车主时才提示；查全部时 user 为空属正常
      if (plate && !res.data.data.user) {
        ElMessage.warning('该车牌未绑定当前账号，仅显示本账号下的订单')
      }
    } else {
      ElMessage.error(res.data.msg || '查询失败')
    }
  } catch (err) {
    const msg = err.response?.data?.msg || err.message
    ElMessage.error('查询失败：' + msg)
  } finally {
    queryLoading.value = false
  }
}

onMounted(() => {
  // 已登录时默认加载一次用户信息
  if (isLoggedIn.value) {
    loadUserProfile()
  }
  // 监听 token 过期事件（request.js 响应拦截器触发）
  window.addEventListener('auth-expired', handleAuthExpired)
})

onUnmounted(() => {
  // 组件卸载时释放摄像头资源
  closeCamera()
  window.removeEventListener('auth-expired', handleAuthExpired)
})

function handleAuthExpired() {
  ElMessage.warning('登录已过期，请重新登录')
  isLoggedIn.value = false
  currentUser.value = ''
  userProfile.value = null
}
</script>

<template>
  <div class="page">
    <!-- 登录界面 -->
    <div v-if="!isLoggedIn" class="login-wrapper">
      <el-card class="login-card" shadow="always">
        <div class="login-title">车辆管理系统</div>
        <div class="login-subtitle">请登录后使用</div>
        <el-form :model="loginForm" label-width="80px" style="margin-top: 24px;">
          <el-form-item label="用户名">
            <el-input v-model="loginForm.username" placeholder="请输入用户名" clearable />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="loginForm.password" type="password" show-password placeholder="请输入密码" @keyup.enter="handleLogin" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" style="width: 100%;" :loading="loginLoading" @click="handleLogin">登 录</el-button>
          </el-form-item>
        </el-form>
        <div class="login-hint">
          还没有账号？
          <el-link type="primary" :underline="false" @click="registerVisible = true">立即注册</el-link>
        </div>
      </el-card>
    </div>

    <!-- 主界面 -->
    <el-container v-else class="main-layout">
      <el-header class="el-header">
        <span class="header-title">车辆管理系统</span>
        <span class="header-sub">车牌识别 · 入场登记</span>
        <span class="user-info">{{ currentUser }}</span>
        <el-button type="danger" size="small" @click="handleLogout">退出登录</el-button>
        <el-button type="warning" size="small" plain @click="cancelVisible = true">注销账号</el-button>
      </el-header>
      <el-container class="body-layout">
        <el-aside width="220px" class="el-aside">
          <el-menu :default-active="activeMenu" @select="handleMenuSelect">
            <el-menu-item index="recognize">车牌识别</el-menu-item>
            <el-menu-item index="entry">入场登记</el-menu-item>
            <el-menu-item index="fee">停车计费</el-menu-item>
            <el-menu-item index="query">车牌查询</el-menu-item>
            <el-menu-item index="kb">车主客服</el-menu-item>
            <el-menu-item index="profile">我的信息</el-menu-item>
          </el-menu>
        </el-aside>
        <el-main class="el-main">
          <!-- 车牌识别 -->
          <el-card v-show="activeMenu === 'recognize'">
            <template #header>车牌识别</template>
            <el-row :gutter="20">
              <el-col :xs="24" :md="12">
                <el-radio-group v-model="recognizeMode" style="margin-bottom: 16px;" @change="onModeChange">
                  <el-radio-button label="upload">上传图片</el-radio-button>
                  <el-radio-button label="camera">摄像头拍照</el-radio-button>
                </el-radio-group>

                <!-- 上传模式 -->
                <div v-if="recognizeMode === 'upload'">
                  <el-upload
                    v-model:file-list="uploadFileList"
                    drag
                    :auto-upload="false"
                    :show-file-list="false"
                    accept=".jpg,.jpeg,.png,.bmp"
                    :on-change="handleFileChange"
                  >
                    <img v-if="imageUrl" :src="imageUrl" class="preview-img" alt="preview" />
                    <div v-else class="upload-placeholder">
                      <div class="upload-text">将车辆图片拖到此处，或<em>点击上传</em></div>
                      <div class="upload-tip">支持 jpg / png / bmp，仅做识别不入库</div>
                    </div>
                  </el-upload>
                  <div style="margin-top: 12px;">
                    <el-button type="primary" :loading="recognizeLoading" @click="handleRecognize">开始识别</el-button>
                    <span v-if="fileName" style="margin-left: 12px; color: #888;">{{ fileName }}</span>
                  </div>
                </div>

                <!-- 拍照模式 -->
                <div v-else>
                  <div v-if="!cameraActive" class="camera-placeholder">
                    <el-button type="primary" @click="openCamera">打开摄像头</el-button>
                    <div class="upload-tip" style="margin-top: 12px;">需在 HTTPS 或 localhost 下访问浏览器才会授权摄像头</div>
                  </div>
                  <div v-else>
                    <video ref="videoRef" autoplay playsinline muted class="camera-video"></video>
                    <div style="margin-top: 12px;">
                      <el-button type="success" :loading="cameraLoading" @click="takePhoto">拍照并识别</el-button>
                      <el-button @click="closeCamera">关闭摄像头</el-button>
                    </div>
                  </div>
                  <div v-if="cameraImgUrl" style="margin-top: 12px;">
                    <div class="result-title" style="font-size: 13px; margin-bottom: 8px;">本次拍摄：</div>
                    <img :src="cameraImgUrl" class="preview-img" alt="shot" />
                  </div>
                </div>
              </el-col>
              <el-col :xs="24" :md="12">
                <div class="result-title">识别结果：</div>
                <el-empty v-if="!detectResult" description="尚未识别" />
                <div v-else class="result-box">
                  <div class="result-row">
                    <span class="result-label">车牌号</span>
                    <el-tag type="success" size="large">{{ detectResult.plate }}</el-tag>
                    <el-tag
                      :type="detectResult.plate_valid ? 'success' : 'warning'"
                      size="small"
                      style="margin-left: 8px;"
                    >{{ detectResult.plate_valid ? '格式合法' : '格式异常' }}</el-tag>
                  </div>
                  <div class="result-row">
                    <span class="result-label">OCR 置信度</span>
                    <span class="result-value">{{ (detectResult.ocr_score * 100).toFixed(2) }}%</span>
                  </div>
                  <div class="result-row">
                    <span class="result-label">YOLO 置信度</span>
                    <span class="result-value">{{ (detectResult.yolo_conf * 100).toFixed(2) }}%</span>
                  </div>
                  <div v-if="detectResult.result_image" class="result-row" style="flex-direction:column;align-items:flex-start;">
                    <span class="result-label">画框效果图</span>
                    <img :src="detectResult.result_image" class="result-img" alt="result" />
                  </div>
                  <div style="margin-top: 12px;">
                    <el-button type="primary" @click="confirmPlateAndEntry">确认车牌并入场</el-button>
                    <el-button plain @click="usePlateForEntry">手动入场</el-button>
                    <el-button type="success" plain @click="usePlateForFee">带入计费</el-button>
                  </div>
                </div>
              </el-col>
            </el-row>
          </el-card>

          <!-- 入场登记 -->
          <el-card v-show="activeMenu === 'entry'">
            <template #header>入场登记</template>
            <el-alert
              type="info"
              :closable="false"
              show-icon
              style="margin-bottom: 16px;"
              title="核对车牌号后点击确认入场，系统将写入停车订单并返回记录 ID"
            />
            <el-form :model="entryForm" label-width="100px" inline>
              <el-form-item label="车牌号">
                <el-input
                  v-model="entryForm.plate"
                  placeholder="如：皖AD03683"
                  style="width: 200px;"
                  @keyup.enter="handleEntry"
                />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="entryLoading" @click="handleEntry">确认入场</el-button>
              </el-form-item>
            </el-form>

            <div class="block-title">本次会话登记记录</div>
            <el-table :data="entryRecords" border>
              <el-table-column prop="record_id" label="记录ID" width="100" />
              <el-table-column prop="plate" label="车牌号" width="140" />
              <el-table-column label="入场时间">
                <template #default="{ row }">{{ formatDateTime(row.in_time) }}</template>
              </el-table-column>
            </el-table>
          </el-card>

          <!-- 停车计费 -->
          <el-card v-show="activeMenu === 'fee'">
            <template #header>停车计费</template>
            <el-alert
              type="info"
              :closable="false"
              show-icon
              style="margin-bottom: 16px;"
              title="填写车牌号与入场/出场时间，系统按 5 元/小时、按分钟折算自动结算并生成订单"
            />
            <el-form :model="feeForm" label-width="100px" inline>
              <el-form-item label="车牌号">
                <el-input v-model="feeForm.plate" placeholder="如：皖AD03683" style="width: 180px;" />
              </el-form-item>
              <el-form-item label="入场时间">
                <el-date-picker
                  v-model="feeForm.in_time"
                  type="datetime"
                  placeholder="选择入场时间"
                  format="YYYY-MM-DD HH:mm"
                  value-format="YYYY-MM-DD HH:mm"
                  style="width: 200px;"
                />
              </el-form-item>
              <el-form-item label="出场时间">
                <el-date-picker
                  v-model="feeForm.out_time"
                  type="datetime"
                  placeholder="选择出场时间"
                  format="YYYY-MM-DD HH:mm"
                  value-format="YYYY-MM-DD HH:mm"
                  :disabled-date="disableFutureDate"
                  style="width: 200px;"
                />
              </el-form-item>
              <el-form-item label="单价(元/时)">
                <el-tag type="info" size="large">¥5 / 小时</el-tag>
                <span style="margin-left: 8px; color: #909399; font-size: 12px;">系统统一单价，不可修改</span>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="feeLoading" @click="handleCalculateFee">计算费用</el-button>
                <el-button @click="clearFeeForm">清空</el-button>
              </el-form-item>
            </el-form>

            <div v-if="feeResult" class="fee-result-box">
              <div class="block-title">计费结果（订单 ID: {{ feeResult.order_id }}）</div>
              <el-descriptions :column="2" border>
                <el-descriptions-item label="车牌号">{{ feeResult.plate }}</el-descriptions-item>
                <el-descriptions-item label="订单状态">
                  <el-tag :type="feeResult.pay_status === 'paid' ? 'success' : 'warning'" size="small">
                    {{ feeResult.pay_status === 'paid' ? '已付款' : '未付款' }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="入场时间">{{ feeResult.in_time }}</el-descriptions-item>
                <el-descriptions-item label="出场时间">{{ feeResult.out_time }}</el-descriptions-item>
                <el-descriptions-item label="停车时长">
                  {{ feeResult.full_hours }} 小时 {{ feeResult.remain_minutes }} 分钟（共 {{ feeResult.duration_minutes }} 分钟）
                </el-descriptions-item>
                <el-descriptions-item label="单价">¥{{ feeResult.rate }}/小时（每分钟 ¥{{ feeResult.per_minute_fee }}）</el-descriptions-item>
                <el-descriptions-item label="应付金额">
                  <span style="color: #f56c6c; font-size: 18px; font-weight: bold;">¥{{ feeResult.total_fee }}</span>
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </el-card>



          <!-- 车牌查询 -->
          <el-card v-show="activeMenu === 'query'">
            <template #header>车牌查询</template>
            <el-form :model="queryForm" label-width="100px" inline>
              <el-form-item label="车牌号">
                <el-input
                  v-model="queryForm.plate"
                  placeholder="如：皖AD03683"
                  style="width: 180px;"
                  @keyup.enter="handleQueryByPlate"
                />
              </el-form-item>
              <el-form-item label="状态">
                <el-select v-model="queryForm.pay_status" style="width: 140px;">
                  <el-option label="全部" value="all" />
                  <el-option label="未付款" value="unpaid" />
                  <el-option label="已付款" value="paid" />
                </el-select>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="queryLoading" @click="handleQueryByPlate">查询</el-button>
              </el-form-item>
            </el-form>

            <div v-loading="queryLoading">
              <template v-if="queryResult">
                <template v-if="queryResult.user">
                  <div class="block-title">
                    账号信息（{{ queryResult.user.plate || '未绑定车牌' }} 已绑定当前账号）
                  </div>
                  <el-descriptions :column="2" border>
                    <el-descriptions-item label="用户ID">{{ queryResult.user.user_id }}</el-descriptions-item>
                    <el-descriptions-item label="用户名">{{ queryResult.user.username }}</el-descriptions-item>
                    <el-descriptions-item label="绑定车牌">{{ queryResult.user.plate || '未绑定' }}</el-descriptions-item>
                    <el-descriptions-item label="注册时间">{{ queryResult.user.create_time || '--' }}</el-descriptions-item>
                  </el-descriptions>
                </template>
                <el-alert v-else-if="queriedPlate" type="warning" :closable="false" show-icon style="margin-bottom:12px;">
                  该车牌未绑定当前账号，以下仅显示当前账号名下的订单
                </el-alert>

                <div class="block-title">订单列表（共 {{ queryResult.total }} 条，未付款排前）</div>
                <el-table :data="queryResult.orders" border style="width:100%;">
                  <el-table-column prop="order_id" label="订单ID" width="90" />
                  <el-table-column prop="plate" label="车牌号" width="130" />
                  <el-table-column prop="in_time" label="入场时间" width="170" />
                  <el-table-column prop="out_time" label="出场时间" width="170">
                    <template #default="{ row }">
                      <span v-if="row.out_time">{{ row.out_time }}</span>
                      <span v-else style="color:#c0c4cc;">未出场</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="费用" width="110">
                    <template #default="{ row }">
                      <span style="color:#f56c6c;font-weight:bold;">¥{{ row.total_fee }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="状态" width="100">
                    <template #default="{ row }">
                      <el-tag :type="row.pay_status === 'paid' ? 'success' : 'warning'" size="small">
                        {{ row.pay_status === 'paid' ? '已付款' : '未付款' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="120">
                    <template #default="{ row }">
                      <el-button
                        v-if="row.pay_status === 'unpaid' && row.out_time"
                        type="success" size="small" :loading="payingOrderId === row.order_id"
                        @click="handlePay(row.order_id)"
                      >支付</el-button>
                      <span v-else-if="!row.out_time" style="color:#909399;">未出场</span>
                      <span v-else style="color:#67c23a;">已结清</span>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
              <el-empty v-else description="请输入车牌号后查询" />
            </div>
          </el-card>

          <!-- 我的信息 -->
          <el-card v-show="activeMenu === 'profile'">
            <template #header>我的信息</template>
            <div v-loading="profileLoading">
              <el-descriptions v-if="userProfile" :column="1" border>
                <el-descriptions-item label="用户名">{{ userProfile.username }}</el-descriptions-item>
                <el-descriptions-item label="绑定车牌">{{ userProfile.plate }}</el-descriptions-item>
              </el-descriptions>
              <el-empty v-else description="暂无信息" />
              <div style="margin-top: 16px;">
                <el-button @click="loadUserProfile">刷新</el-button>
              </div>
            </div>
          </el-card>

          <!-- 车主客服问答 -->
          <el-card v-show="activeMenu === 'kb'">
            <template #header>车主客服</template>
            <CustomerService />
          </el-card>
        </el-main>
      </el-container>
    </el-container>

    <!-- 车牌确认弹窗 -->
    <el-dialog v-model="confirmEntryVisible" title="确认车牌" width="420px" :close-on-click-modal="false">
      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px;">
        请确认识别到的车牌号是否正确，确认后将自动入场并跳转计费界面。
      </el-alert>
      <el-form label-width="80px">
        <el-form-item label="车牌号">
          <el-input v-model="pendingPlate" placeholder="如：皖AD03683" clearable />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="confirmEntryVisible = false">取 消</el-button>
        <el-button type="primary" @click="doConfirmEntry">确认入场</el-button>
      </template>
    </el-dialog>

    <!-- 注册弹窗 -->
    <el-dialog v-model="registerVisible" title="用户注册" width="420px" :close-on-click-modal="false">
      <el-form :model="registerForm" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="registerForm.username" placeholder="请输入用户名" clearable />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="registerForm.password" type="password" show-password placeholder="请输入密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="registerVisible = false">取 消</el-button>
        <el-button type="primary" :loading="registerLoading" @click="handleRegister">注 册</el-button>
      </template>
    </el-dialog>

    <!-- 注销账号弹窗 -->
    <el-dialog v-model="cancelVisible" title="注销账号" width="420px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 16px;">
        注销后账号将被永久删除，无法恢复，请谨慎操作！
      </el-alert>
      <el-form :model="cancelForm" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="cancelForm.username" placeholder="请确认用户名" clearable />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="cancelForm.password" type="password" show-password placeholder="请输入密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cancelVisible = false">取 消</el-button>
        <el-button type="danger" :loading="cancelLoading" @click="handleCancelAccount">确认注销</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  height: 100vh;
}

/* 主界面撑满视口。
   el-container 默认 height:auto，只按内容高度撑开，页面下方会留出一大片空白；
   这里让外层占满 .page、内层占满剩余高度，并把 min-height 归零，
   否则 el-main 的内容会把父容器顶高，侧边栏和滚动条一起失效。 */
.main-layout {
  height: 100%;
}
.body-layout {
  flex: 1;
  min-height: 0;
}

/* 登录界面 */
.login-wrapper {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.login-card {
  width: 420px;
  padding: 20px 10px;
  border-radius: 12px;
}
.login-title {
  font-size: 26px;
  font-weight: bold;
  text-align: center;
  color: #303133;
}
.login-subtitle {
  text-align: center;
  color: #909399;
  margin-top: 8px;
  font-size: 14px;
}
.login-hint {
  text-align: center;
  color: #c0c4cc;
  font-size: 12px;
  margin-top: 8px;
}

/* 主界面 */
.el-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 8px 16px;
  min-height: 60px;
  height: auto;
  border-bottom: 1px solid #e6e6e6;
  background: #fff;
}
.header-title {
  font-size: 20px;
  font-weight: bold;
}
.header-sub {
  color: #909399;
  font-size: 13px;
  flex: 1;
}
.user-info {
  font-size: 14px;
  color: #606266;
  white-space: nowrap;
}
.el-aside {
  border-right: 1px solid #e6e6e6;
  background: #fafafa;
}
.el-main {
  background: #f5f7fa;
  overflow-y: auto;
  /* 让当前显示的卡片撑满主区：各页面内容都很少（一个表单 + 一张表），
     卡片只按内容高度撑开时，下半屏会留下一大片灰色空白，观感像"页面没加载出来" */
  display: flex;
  flex-direction: column;
}
.el-main > .el-card {
  flex: 1;
  min-height: 0;
}
.preview-img {
  max-width: 100%;
  max-height: 280px;
  display: block;
  margin: 0 auto;
}
/* 拖拽区默认只有内容高度（约 170px），整页会显得发空；
   抬高到 280px 并垂直居中，同时给上传后的预览图留出足够空间 */
:deep(.el-upload-dragger) {
  min-height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.upload-placeholder {
  padding: 40px 0;
  color: #909399;
  text-align: center;
}
.upload-text {
  font-size: 14px;
}
.upload-text em {
  color: #409eff;
  font-style: normal;
}
.upload-tip {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 8px;
}
.camera-placeholder {
  min-height: 280px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  text-align: center;
  background: #f5f7fa;
  border: 1px dashed #dcdfe6;
  border-radius: 4px;
}
.camera-video {
  width: 100%;
  max-height: 320px;
  display: block;
  background: #000;
  border-radius: 4px;
}
.result-title {
  font-weight: bold;
  margin-bottom: 12px;
  color: #303133;
}
.result-box {
  padding: 12px;
  background: #f5f7fa;
  border-radius: 4px;
}
.result-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.result-label {
  width: 90px;
  color: #909399;
  font-size: 13px;
}
.result-value {
  font-size: 16px;
  font-weight: bold;
  color: #303133;
}
.result-img {
  max-width: 100%;
  max-height: 240px;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  margin-top: 8px;
}
.block-title {
  font-weight: bold;
  color: #303133;
  margin: 16px 0 12px;
}
.fee-result-box {
  margin-top: 16px;
  padding: 16px;
  background: #f5f7fa;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
}

/* 窄屏适配：侧边栏改为顶部横向菜单，避免 220px 固定宽度挤占表单 */
@media (max-width: 900px) {
  .header-sub {
    display: none;
  }
  .el-aside {
    width: 100% !important;
    border-right: none;
    border-bottom: 1px solid #e6e6e6;
  }
  .el-aside :deep(.el-menu) {
    display: flex;
    overflow-x: auto;
    border-right: none;
  }
  .el-main {
    padding: 12px;
  }
}
</style>
