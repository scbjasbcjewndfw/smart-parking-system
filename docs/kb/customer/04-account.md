# 账号与绑定（domain: account）

> 依据 `controller/userController.py`、`service/userService.py`、`frontend/src/api/request.js` 核对。
> **重要事实**：系统**没有**修改密码、找回密码、换绑车牌的功能。相关诉求一律转人工，不得承诺。

---

### KB-ACC-001 怎么注册账号
- domain: account
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/controller/userController.py#register
- confidence: 已核对代码

**答**：在登录页点“立即注册”，填写用户名和密码即可，**车牌号可以不填**。注册成功后回到登录页用刚注册的账号登录。

**补充**：密码由系统加密存储，客服与管理员都无法查看明文。注册时若填写车牌，需符合 7～8 位车牌格式（省份简称 + 字母 + 5～6 位），否则会提示“车牌号格式错误”。

**不适用**：不支持手机号验证码注册、不支持第三方账号（微信/支付宝）登录。

---

### KB-ACC-002 提示“该用户名已经注册”
- domain: account
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/userService.py#register
- confidence: 已核对代码

**答**：用户名是唯一的，已被他人或您自己注册过。请换一个用户名，或直接用该用户名登录。

**补充**：用户名区分大小写，`Zhang` 与 `zhang` 视为两个不同账号，请留意注册时的大小写。

---

### KB-ACC-003 用着用着提示“登录已过期，请重新登录”
- domain: account
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: frontend/src/api/request.js（401 拦截 → auth-expired）；backend/car_project/__init__.py JWT 未设置过期时间
- confidence: 已核对代码

**答**：这是登录凭证到期的正常保护机制，不是账号异常。重新输入用户名和密码登录即可，**已生成的订单、入场记录都不会丢失**。

**补充**：登录凭证有效期默认为 120 分钟（可通过环境变量 `CARPARK_JWT_EXPIRES_MIN` 调整），长时间停留在一个页面未操作后再点按钮，就可能触发该提示。建议操作前先刷新页面确认登录状态。

**不适用**：凭证过期不影响已提交的计费与支付结果。

---

### KB-ACC-004 注销账号会怎样、订单还在吗
- domain: account
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/userService.py#delete（仅删除 sys_user 记录）
- confidence: 已核对代码

**答**：在页面右上角点“注销账号”，需再次输入**用户名和密码**确认。注销后账号被永久删除、**无法恢复**，该用户名可以重新注册。

**补充**：注销只删除账号本身，**历史停车订单不会随之删除**，仍保留在系统记录中用于对账与审计。如需一并处理历史数据，请转人工。

**不适用**：不支持注销后恢复账号或找回历史绑定关系。

---

### KB-ACC-005 注册时没填车牌，现在能补吗 / 想换绑车牌
- domain: account
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: 业务规则待确认（无更新车牌的接口）
- confidence: 待业务确认

**答**：当前系统的车牌绑定只在注册时写入一次，**页面没有补填或换绑车牌的入口**，系统也不提供自助修改。

**处理**：请记录车主的用户名、原车牌、目标车牌，转人工处理。**不要指引车主“重新注册一个账号”来绕过**，否则会造成历史订单分散在两个账号下、对账困难。

**不适用**：禁止承诺“可以随时修改绑定车牌”。

---

### KB-ACC-006 忘记密码了怎么办
- domain: account
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: 业务规则待确认（系统无找回密码/改密接口，无短信与邮箱通道）
- confidence: 待业务确认

**答**：系统目前**没有**“忘记密码”和“修改密码”功能，也没有绑定手机号或邮箱，因此无法自助重置。

**处理**：请转人工核实身份后处理。**不要索要车主密码**，也不要建议车主把密码发给任何人。

**不适用**：禁止回答“点忘记密码按提示重置”之类不存在的流程。

---

### KB-ACC-007 密码输错多次会被锁定吗
- domain: account
- visibility: public
- lot_scope: all
- valid_from: 2026-11-01
- valid_to: 长期有效
- version: v1
- source: backend/car_project/service/userService.py#login（无失败计数与锁定逻辑）
- confidence: 已核对代码

**答**：系统没有登录失败次数限制，也不会锁定账号。密码错误只会提示“用户名或密码错误”，可以继续重试。

**补充**：如果确认密码正确仍无法登录，请检查用户名大小写、输入法全角字符，或联系人工核查账号状态。

**不适用**：本条不构成安全建议；如需启用失败锁定，属于产品改造范围。
