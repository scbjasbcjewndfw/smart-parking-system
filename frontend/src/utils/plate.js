/**
 * 车牌号规范化与校验（前端唯一口径，须与后端 backend/car_project/utils/plate.py 保持一致）。
 *
 * 为什么要前端也校验：
 * 后端校验只能保证数据不脏，无法阻止用户提交后等 300ms 才看到错误。
 * 前端提前拦截可以显著改善填写体验，但**不能替代后端校验**。
 */

const PROVINCES = '京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼'
const SPECIAL_PREFIXES = '使领'
const SPECIAL_SUFFIXES = '挂学警港澳'

const PLATE_PATTERN = new RegExp(
  `^(?:[${PROVINCES}]|[${SPECIAL_PREFIXES}])[A-HJ-NP-Z][A-HJ-NP-Z0-9]{4,5}[A-HJ-NP-Z0-9${SPECIAL_SUFFIXES}]$`,
)

const NOISE_CHARS = ['·', '•', ' ', '-', '—', ':', '：', '．', '.', '[', ']', '(', ')', '（', '）']

/**
 * 规范化车牌：去分隔符、全角转半角、统一大写。
 *
 * @param {string} raw 用户输入或 OCR 结果
 * @returns {string} 规范化后的字符串，输入为空时返回空串
 */
export function normalizePlate(raw) {
  if (raw === null || raw === undefined) return ''
  let text = String(raw)
  NOISE_CHARS.forEach((ch) => {
    text = text.split(ch).join('')
  })
  return text
    .replace(/[\uFF01-\uFF5E]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) - 0xfee0))
    .trim()
    .toUpperCase()
}

/**
 * 判断是否为合法车牌号。
 *
 * @param {string} raw 待校验字符串
 * @returns {boolean}
 */
export function isValidPlate(raw) {
  return PLATE_PATTERN.test(normalizePlate(raw))
}

/**
 * 校验并返回规范化车牌，不合法时抛出可读错误。
 *
 * @param {string} raw 用户输入
 * @param {string} [label='车牌号'] 错误提示中使用的字段名
 * @returns {string} 规范化后的合法车牌
 * @throws {Error} 格式不合法
 */
export function assertPlate(raw, label = '车牌号') {
  const plate = normalizePlate(raw)
  if (!plate) throw new Error(`请输入${label}`)
  if (!isValidPlate(plate)) {
    throw new Error(`${label}格式不正确，应为 省份简称+字母+5~6 位（如 皖AD03683）`)
  }
  return plate
}
