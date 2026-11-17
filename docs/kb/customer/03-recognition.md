# 车牌识别与进出场（domain: recognize）

> 依据 `backend/car_project/service/plateService.py`、`service/plate_recognizer.py`、`controller/plateController.py` 与前端交互核对。
> 核心设计：**识别只是建议，必须人工核对后再入场**。任何回答都不能表述为“识别后自动放行”。

---

### KB-REC-001 怎么用拍照识别车牌
- domain: recognize
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: frontend/src/components/Home.vue#openCamera、#takePhoto
- confidence: 已核对代码

**答**：登录后进入「车牌识别」，选择「摄像头拍照」，允许浏览器使用摄像头后点击“拍照并识别”；也可以切到「上传图片」，拖入或选择车辆照片后点“开始识别”。识别结果会显示车牌号、OCR 置信度、YOLO 置信度，以及一张带框的效果图。

**补充**：摄像头需在 HTTPS 或 localhost 环境才能授权，通过 IP 访问的页面浏览器可能直接提示不支持。

**不适用**：识别本身不写数据库，不会自动产生订单。

---

### KB-REC-002 提示“未检测到车牌”怎么办
- domain: recognize
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/plateService.py#recognize_only（404 分支）
- confidence: 已核对代码

**答**：说明图片里没有找到可识别的车牌区域，或找到了区域但文字识别失败。常见原因按发生频率排序：

1. 车牌在画面中太小（建议车牌高度不低于 40 像素）；
2. 逆光、夜间噪点大、整体过暗或过曝；
3. 车牌被泥污、积雪、挂件遮挡；
4. 拍摄角度过斜，或车牌有明显弯折；
5. 图片本身模糊、抖动。

**建议**：正对车牌、距离 2～5 米、光线均匀时重拍；不要用截图二次压缩的图片。

**不适用**：系统不支持视频流识别，只接受单张静态图片。

---

### KB-REC-003 车牌认错了 / 有个字识别成别的字
- domain: recognize
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: frontend/src/components/Home.vue#confirmPlateAndEntry（可编辑后确认）
- confidence: 已核对代码

**答**：识别结果仅供参考，确认前可以直接修改。点击「确认车牌并入场」后会弹出确认框，在框内把车牌号改成正确值再提交即可，系统以您最终确认的号码为准。

**补充**：常见误识：`0/O`、`1/I`、`8/B`、`D/0`，以及省份简称混淆。新能源绿牌因底色特殊，已单独做增强处理，仍有误识时按上述方式手工修正。

**不适用**：如果订单已经生成后才发现车牌错了，系统没有自助修改入口，需转人工处理（见 KB-DIS-002）。

---

### KB-REC-004 支持哪些图片格式、有大小限制吗
- domain: recognize
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/plateService.py#ALLOWED_EXT
- confidence: 已核对代码

**答**：支持 **jpg / jpeg / png / bmp** 四种格式，其他格式会提示“不支持的图片格式”。当前对图片大小没有额外限制，但过大的图片会明显拖慢识别速度，建议单张控制在 5MB 以内。

**补充**：HEIC（iPhone 默认格式）不在支持范围内，请先转为 JPG 再上传。图片损坏或非图片文件会提示“图片解码失败”。

---

### KB-REC-005 识别完怎么入场
- domain: recognize
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/controller/plateController.py#entry（jwt_required）
- confidence: 已核对代码

**答**：识别后点「确认车牌并入场」，核对弹窗里的车牌号无误后提交，入场登记成功会生成一条记录（记录 ID + 车牌 + 入场时间），并自动跳到「停车计费」页面。也可以在「入场登记」里手工输入车牌后点“确认入场”。

**补充**：入场登记**必须登录**，未登录会提示“请先登录”；入场时间为提交那一刻的系统时间，不能手动指定。

**重复登记保护**：同一车牌如果已经有一条未出场的订单（说明车还在场内），再次登记会被拒绝，并提示上一次的入场时间。如需重新入场，请先完成上一次的出场计费。

**不适用**：入场不代表已缴费，订单初始状态为未付款。

**related**：KB-FEE-006

---

### KB-REC-006 怎么出场 / 为什么没有“出场”按钮
- domain: recognize
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#calculate_fee（出场通过计费提交完成）；后端无独立出场接口
- confidence: 已核对代码

**答**：当前系统没有单独的“出场”按钮，出场是通过「停车计费」完成的：填入车牌号、选择入场时间和出场时间，点“计算费用”，系统就会按出场时间结算并生成订单，订单的出场时间随之写入。

**补充**：只做计费但未支付时，订单状态仍是未付款，可在「车牌查询」里继续支付。

**不适用**：系统未与道闸联动，线上操作不会自动抬杆；实际放行以现场设备为准。

---

### KB-REC-007 新能源绿牌、黄牌、挂车能识别吗
- domain: recognize
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/plateService.py#PLATE_PATTERN
- confidence: 已核对代码

**答**：7 位普通号牌（蓝牌、黄牌）和 8 位新能源绿牌都支持，尾位为**挂、学、警、港**的号牌也能通过校验。识别时对绿牌会自动做底色处理以提高准确率。

**补充**：尾位为“澳”的澳门入出境车牌、以及“使/领”开头的使领馆车牌，目前入场校验会提示“车牌号格式不正确”，属于系统限制，请转人工登记。

**不适用**：军牌、临时号牌、拖拉机号牌不在支持范围内。

---

### KB-REC-008 识别结果里的“格式异常”是什么意思
- domain: recognize
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/plateService.py#recognize_only（plate_valid）；前端 plate_valid 标签
- confidence: 已核对代码

**答**：这是系统对识别结果做的格式自检，不是识别失败。“格式合法”表示符合国内车牌编码规则；“格式异常”说明识别出的字符组合不像合法车牌（例如只有 5 位、省份简称识别错、混入了无关字符）。

**建议**：看到“格式异常”时不要直接确认入场，先对照原图人工修正车牌号。

**不适用**：格式合法也不代表号码正确，仍需人工核对。
