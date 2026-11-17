# 支付与开票（domain: payment）

> 依据 `backend/car_project/service/parkingService.py#pay_order`、`controller/parkingController.py` 与前端 `Home.vue` 支付按钮条件核对。
> **重要事实**：当前支付动作是把订单状态从“未付款”改为“已付款”，未接入微信/支付宝等第三方支付渠道。对外话术不得表述为“已支持在线支付”。

---

### KB-PAY-001 怎么支付停车费
- domain: payment
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/controller/parkingController.py#pay_order；frontend/src/components/Home.vue#handlePay
- confidence: 已核对代码

**答**：登录后进入「车牌查询」，输入车牌号查询订单，在未付款且已出场的订单行点击「支付」按钮即可。支付成功后订单状态变为“已付款”，该行操作列显示“已结清”。

**补充**：支付只能由订单所属账号操作，无法替他人支付。

**不适用**：当前为记账式确认，未接入第三方支付渠道；如需真实线上支付，见 KB-PAY-005 转人工。

**related**：KB-PAY-002、KB-PAY-006

---

### KB-PAY-002 为什么我的订单没有「支付」按钮
- domain: payment
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: frontend/src/components/Home.vue（v-if: pay_status==='unpaid' && out_time）
- confidence: 已核对代码

**答**：只有同时满足“未付款”和“已填写出场时间”两个条件的订单才显示支付按钮。常见原因有三类：

1. **订单还没出场**：出场时间为空，操作列显示“未出场”。请先在「停车计费」填写出场时间完成计费。即使直接调用接口，服务端也会拒绝并提示“该订单尚未出场，请先完成出场计费”。
2. **已经付过了**：状态为“已付款”，操作列显示“已结清”。
3. **订单不属于当前账号**：登录账号与订单所属账号不一致，需用下单时的账号登录。

**补充**：如果确认未付款、已出场、账号也正确但仍无按钮，请转人工核查。

**related**：KB-PAY-001、KB-FEE-006

---

### KB-PAY-003 不小心点了两次支付 / 提示“无需重复支付”
- domain: payment
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#pay_order（已付款返回 400）
- confidence: 已核对代码

**答**：系统做了幂等保护，已付款订单再次支付会被拒绝并提示“订单已付款，无需重复支付”，不会产生第二笔扣费。请刷新订单列表确认状态。

**补充**：该提示属于正常保护机制，不是系统故障。

---

### KB-PAY-004 能开电子发票吗
- domain: payment
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: 业务规则待确认（系统无开票接口）
- confidence: 待业务确认

**答**：当前系统**未提供**自助开票功能，页面没有发票入口，也不支持下载电子发票。

**处理**：请记录车主的车牌号、订单号、开票金额与抬头信息，转交现场岗亭或客服人工开票。**不要承诺开票时限与发票类型**。

**不适用**：禁止回答“可在订单页申请开票”之类未实现的功能。

---

### KB-PAY-005 付错了 / 想退款怎么办
- domain: payment
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: 业务规则待确认（系统无退款接口）
- confidence: 待业务确认

**答**：系统没有自助退款入口，也无法在线撤销已付款订单。已付款订单只能由后台人工处理。

**处理**：请车主提供车牌号、订单号、付款时间与退款原因，转人工审核。**不要承诺退款金额、到账时间或成功率**。

**补充**：若因车牌识别错误导致替他人缴费，属于误缴，同样走人工核查流程（见 KB-DIS-002）。

**related**：KB-DIS-002

---

### KB-PAY-006 怎么查我的停车记录和欠费
- domain: payment
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/parkingService.py#query_user_by_plate
- confidence: 已核对代码

**答**：登录后进入「车牌查询」，车牌号可留空查询本人全部订单，也可填具体车牌；状态可筛选“全部 / 未付款 / 已付款”。结果按**未付款优先、再按入场时间倒序**排列，列表会显示订单号、车牌、入场出场时间、金额与状态。

**补充**：只能查询当前登录账号名下的订单，无法查询他人订单。若提示“未找到该车牌对应的用户”，说明该车牌未绑定到账户或在其他账号下。

**不适用**：不提供跨账号、跨车场的历史记录合并查询。
