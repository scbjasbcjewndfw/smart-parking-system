# 申诉与隐私（domain: dispute / privacy）

> 依据 `service/plateService.py#recognize_only`（图片不落盘）、`service/parkingService.py#query_user_by_plate`（按 user_id 隔离）、`models/models.py` 字段范围核对。
> 申诉类条目只描述**可受理的动作**，不承诺处理结果与时限；隐私类条目不得暴露表结构、字段名与内部实现。

---

### KB-DIS-001 我觉得费用算多了
- domain: dispute
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#calculate_fee
- confidence: 已核对代码

**答**：请先核对订单上的入场时间、出场时间与实际是否一致。系统严格按这两个时间差计算：满 1 小时按 5 元，余下分钟按 5÷60 元折算，四舍五入保留 2 位小数。

**常见差异原因**：入场时间取的是入场登记那一刻的系统时间，出场时间取的是计费时填写的出场时间；若其中任一时间与实际不符，金额就会偏差。

**处理**：确认时间有误的，记录订单号、车牌、实际进出时间，转人工核查。**不要自行承诺减免金额**。

**related**：KB-FEE-001、KB-FEE-005

---

### KB-DIS-002 车牌识别错了，已经生成了订单 / 替别人缴了费
- domain: dispute
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: 业务规则待确认（无订单修改与撤销接口）
- confidence: 待业务确认

**答**：识别结果在确认入场前可以手工修正（见 KB-REC-003），但订单一旦生成，系统**没有**自助修改车牌或撤销订单的功能。

**处理**：请记录订单号、错误车牌、正确车牌、发生时间，转人工核查。若涉及误缴他人停车费，一并说明支付时间与金额。**不要承诺退款，也不要告知车主对方车辆的任何信息**。

**不适用**：禁止用“重新入场一次”来掩盖错误订单，会造成重复计费。

**related**：KB-REC-003、KB-PAY-005

---

### KB-DIS-003 同一次停车出现了两条订单
- domain: dispute
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v2
- source: backend/car_project/service/parkingService.py#calculate_fee（复用未出场订单）
- confidence: 已核对代码

**答**：系统在结算时会先查找该车牌最近一条**尚未出场**的订单：找到就更新这条订单的出场时间与金额，找不到才新建。因此正常情况下同一段停车只会有一条订单。

**可能出现两条的情况**：该车已经完成过一次出场结算（订单已有关闭时间），之后又对同一段停留时间重复提交计费，此时会被当作新的一次停车生成订单。请核对哪一条的进出时间与实际一致，另一条不要支付，并转人工清理。

**不适用**：系统不支持车主自助删除或合并订单；未支付的多余订单不会自动扣费。

**related**：KB-FEE-001

---

### KB-PRI-001 系统收集了我哪些信息
- domain: privacy
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/models/models.py（sys_user / parking_order / parking_record 字段范围）
- confidence: 已核对代码

**答**：系统收集三类信息：**账号信息**（用户名、加密后的密码、可选绑定的车牌号、注册时间）、**停车订单信息**（车牌号、入场时间、出场时间、应付金额、支付状态）、**出入场记录**（车牌号、入场时间、对应订单）。

**补充**：密码以加密形式保存，任何人员（包括客服）都无法查看明文。系统不采集身份证号、手机号、银行卡信息。

**不适用**：如后续新增采集项（如手机号用于通知），必须先更新本条再对外说明。

---

### KB-PRI-002 我上传的车牌照片会被保存吗
- domain: privacy
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/plateService.py#recognize_only（仅在内存处理，未写入磁盘）
- confidence: 已核对代码

**答**：不会。上传的图片只在识别过程中于服务器内存中处理，识别完成后直接返回结果（车牌号、置信度、带框效果图），**系统不保存原始照片，也不写入任何文件目录**。

**补充**：识别接口本身不需要登录，因此不会与账号关联。如需留存证据照片，需另行说明业务用途与留存期限。

**不适用**：本条仅描述当前实现，若后续启用图片留存（如举证需要），必须同步修改本条与隐私告知。

---

### KB-PRI-003 我的数据保存多久、能删除吗
- domain: privacy
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: 业务规则待确认（无数据留存期限配置，注销不级联删除订单）
- confidence: 待业务确认

**答**：目前系统没有设置自动清理期限，停车订单与出入场记录会长期保留用于对账与审计。注销账号只删除账号本身，**不会删除历史订单**（见 KB-ACC-004）。

**处理**：如需删除特定历史记录，请说明车牌、订单号与理由，转人工按流程处理。**不要承诺删除时限或删除范围**。

**不适用**：本条不得回答具体的保留年限，除非业务方已出具正式留存政策。

**related**：KB-ACC-004

---

### KB-PRI-004 能帮我查一下某个车牌的停车记录吗
- domain: privacy
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#query_user_by_plate（按 JWT 中的 user_id 强制过滤）
- confidence: 已核对代码

**答**：不能。系统只允许查询**当前登录账号本人**名下的订单，接口会按登录身份自动过滤，无法查询其他账号或未绑定车牌的记录。

**处理**：如车主确实需要查询家人车辆的记录，请说明需由车辆所属账号登录查询，或转人工核实关系后按流程处理。**不得因对方提供车牌号就返回任何订单信息**。

**不适用**：禁止应任何理由（包括“我是车主本人”“帮朋友问”）绕过身份校验。
