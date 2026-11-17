# 计费规则（domain: fee）

> 以下内容全部依据 `backend/car_project/service/parkingService.py` 的 `calculate_fee` 实现核对。
> 修改计费逻辑时，本文件所有金额示例必须同批更新，否则会造成客服口径与系统不一致。

---

### KB-FEE-001 停车费怎么算
- domain: fee
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#calculate_fee
- confidence: 已核对代码

**答**：停车费按 **5 元/小时** 计收，按实际停留时长折算到分钟。计算方式是：满 1 小时的部分按 5 元/小时计，不足 1 小时的余下分钟按每分钟 5÷60 元计，两部分相加后四舍五入保留 2 位小数。

**示例**：停留 2 小时 30 分钟 = 2×5 + 30×(5÷60) = 10 + 2.5 = **12.50 元**。

**不适用**：如需免费时长、封顶价、夜间优惠，见 KB-FEE-007（当前系统未实现，需人工确认）。

**related**：KB-FEE-002、KB-FEE-003

---

### KB-FEE-002 不足一小时怎么收费
- domain: fee
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#calculate_fee
- confidence: 已核对代码

**答**：不足 1 小时按分钟折算，不是直接收 1 小时的钱。每分钟约 0.0833 元。

**示例**：停留 59 分钟 = 59 × (5÷60) ≈ **4.92 元**；停留 30 分钟 = **2.50 元**；停留 10 分钟 = **0.83 元**。

**补充**：系统按分钟向上取整计算时长，即不足 1 分钟的部分按 1 分钟计。所以极短停留（如 20 秒）会计为 1 分钟，约 0.08 元。

**related**：KB-FEE-001

---

### KB-FEE-003 金额为什么有小数点后两位
- domain: fee
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#calculate_fee
- confidence: 已核对代码

**答**：因为费用按分钟折算，结果会带小数，系统统一四舍五入保留 2 位小数后作为应付金额。

**示例**：停留 1 小时 1 分钟 = 5 + 0.0833 ≈ 5.08 元；停留 3 小时 20 分钟 = 15 + 1.6667 ≈ 16.67 元。

**补充**：金额四舍五入在最后一步进行，不是每分钟各自取整后相加，所以不会出现累加误差。

---

### KB-FEE-004 单价可以改吗、有没有折扣
- domain: fee
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#calculate_fee（rate 被强制固定为 5）
- confidence: 已核对代码

**答**：单价在系统中**固定为 5 元/小时**，页面上的单价输入框是灰化不可修改的，即使传入其他数值也会被系统按 5 元/小时重新计算。因此当前没有自助折扣或议价入口。

**补充**：如需月卡、储值、公务车等优惠，见 KB-FEE-007，需人工处理。

**不适用**：不要向车主承诺任何折扣比例或优惠金额。

---

### KB-FEE-005 出场时间填错了 / 提示“出场时间必须晚于入场时间”
- domain: fee
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#calculate_fee（out_time <= in_time 返回 400）
- confidence: 已核对代码

**答**：系统要求出场时间晚于入场时间，相等或更早都会直接拒绝计算并提示错误。请检查两个时间是否填反、日期是否跨天填错（例如出场日期仍是前一天）。

**补充**：时间格式需为 `YYYY-MM-DD HH:mm` 或 `YYYY-MM-DD HH:mm:ss`，格式不正确同样会提示“时间格式不正确”。

**不适用**：系统不支持负时长冲抵、不支持跨车场合并计费。

---

### KB-FEE-006 计费成功后是不是已经付款了
- domain: fee
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#calculate_fee（pay_status 初始为 unpaid）
- confidence: 已核对代码

**答**：不是。计费只生成订单，订单状态为**未付款**（unpaid），需要另外完成支付才会变成已付款。计费结果里也会显示“未付款”标签。

**补充**：支付方式见 KB-PAY-001。

**related**：KB-PAY-001

---

### KB-FEE-007 有没有免费时长、封顶价、月卡优惠
- domain: fee
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: 业务规则待确认（当前代码仅实现 5 元/小时线性计费）
- confidence: 待业务确认

**答**：当前系统只实现了“5 元/小时、按分钟折算”这一种计费方式，**没有**免费时长、24 小时封顶价、夜间费率、月卡/季卡/储值卡等功能。

**处理**：遇到车主询问免费时长、封顶、月卡、公务车或残疾人车优惠时，**不要给出任何数字**，说明“该政策需人工确认”，并转接现场岗亭或客服电话（见 KB-LOT-004）。

**不适用**：本条禁止由模型自行推算或参考其他停车场标准作答。

**related**：KB-FEE-004
