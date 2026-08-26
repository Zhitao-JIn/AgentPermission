## 2026-08-26（其二）—— 拆出 `runtime.py`，import 不再有副作用

**改了什么**：
- 新增 `agent_permission/runtime.py`，装走原本住在 `__init__.py` 里的全部运行时状态：
  `PermissionContext` / `_current_context` / `runtime_roles` / `runtime_policies` /
  `approval_store` / `_load_runtime` / `initialize` / `requires_initialization`。
  `__init__.py` 收回成纯粹的门面，只做 re-export。
- **删掉模块级的 `runtime_context = _load_runtime()`**，连同 `runtime_context` 这个导出。
- `decorator.py` 两处函数体内的延迟 import 改回顶层 import；未初始化时抛
  `RuntimeError` 而不是退化成 anonymous。
- `runtime_roles` / `runtime_policies` 改成私有全局 + `get_runtime_roles()` /
  `get_runtime_policies()` 两个 getter；`rbac.py` 改用 getter，import 也回到顶层。

**为什么这么改**：

*循环依赖*。`__init__.py` 同时在当门面和当状态宿主，于是 `decorator.py` 要用状态就得
反向 import 自己的包，形成 包 → 子模块 → 包 的循环 —— 那两处延迟 import 不是什么讲究
写法，是绕开循环的补丁，注释里「执行到第 9 行时还没定义」正是在描述补丁为何必须存在。
状态搬出去之后依赖单向：`__init__` → `decorator` → `runtime`，补丁自然消失。

*import 副作用*。`runtime_context = _load_runtime()` 是模块级调用，意味着
`import agent_permission` 会去读 **cwd 下**的 `config/`。从别的目录 import、在测试里
import、`python -c "import agent_permission"` 全都直接炸。而这个变量零调用方 ——
它和 `set_current_context`、`new_episode`、`ApprovalStore.get()` 是同一类：写好了没接线。

*不退化成 anonymous*。删掉 import 时的初始化后，第一次 `@initialize` 之前 context 是
None。原来的写法会退化成 `anonymous` + 空 roles，结果是所有权限被拒 —— 症状说「没权限」，
真因是「没初始化」，查的人会去翻 `permissions.json`。现在直接抛 RuntimeError 并点名
「wrap the entry point with @initialize」。

**取舍**：
- `runtime_roles` / `runtime_policies` 用 getter 取值，不直接导出全局。它们会被
  `_load_runtime()` **整个重新绑定**，`from agent_permission import runtime_roles` 绑的是
  当时那个对象 —— 拿到初始空字典且永不更新，症状是「改了 permissions.json 不生效」。
  getter 每次读当前值，和 `get_current_context()` 同一个模式；顺带 `rbac.py` 里那个
  为了绕重绑而写在函数体内的 import 也能回到顶层了。
- `runtime.py` 而不是 `context.py`：装的不只是身份，还有角色表、策略表和审批存储。

**影响面**：**破坏性变更。** `runtime_context` 从公开 API 消失；
`runtime_roles` / `runtime_policies` 两个全局换成 `get_runtime_roles()` /
`get_runtime_policies()`。`import agent_permission` 不再自动初始化 —— **必须**有一个
`@initialize` 入口，否则第一次守卫调用抛 RuntimeError（此前是静默退化成 anonymous 被拒）。
`ApprovalRejected` / `ApprovalExpired` 补进 `__all__`（调用方要 catch 它们，之前得从
`.errors` 里挖）。

## 2026-08-26 —— 审计事件补上关联键，审批存储改原子写

**改了什么**：
- `audit.py`：删掉 `decision`；`episode_id` / `trace_id` 从「永远为 null 的预留位」
  变成必填字段，语义重新定义为三层嵌套的自生成 ID（见下）。
- `decorator.py`：每次守卫调用生成一个 `trace_id`，本次调用的所有 record 共用；
  审批分支的四条记录带上 `approval_id`；denied / rejected / expired 填 `reason`。
- `__init__.py`：`PermissionContext` 增加 `episode_id`，由 `_load_runtime()` 显式铸新；
  `set_current_context()` 直接删掉，赋值内联进 `_load_runtime()`（只有一个调用方）；
  `@initialize` 嵌套调用直接 assert 报错。
- `approval.py`：控制台输入改成 `approve|reject [理由]` 单行解析，理由落进 `request.reason`；
  超时时长从硬编码的 10 秒改成 `ApprovalRequest.timeout_seconds`；`store` 参数标上
  `ApprovalStore` Protocol；出入口加契约 assert。
- `stores/`：`LocalFileApprovalStore` 整个删掉，换成 `InMemoryApprovalStore`。
  `get()` 一并删掉（零调用方），`ApprovalStore` Protocol 同步收成 `create` + `save`。
  `get_approval_store(permission)` 换成全进程唯一的 `approval_store` 实例。

**为什么这么改**：`trace_id` / `episode_id` / `approval_id` / `reason` 之前全是「schema 上是
一等公民、运行时永远是 null」——decorator 一个都没传。这比没有字段更糟：读日志的人以为数据丢了，
写代码的人以为已经有人在填。判据是「这个字段有没有一个现在就说得清的来源和消费方」：
`decision` 和 `event` 完全冗余（`permission_allowed` 已经把决策编码进事件类型），删；
其余三个的来源就在本库自己身上，只是之前没人去生成。

**三个 ID 是一个三层嵌套，全部自生成，不接受调用方注入**：
`episode_id`（一次 `@initialize` 到下一次之间）⊃ `trace_id`（一次守卫调用的完整链路，
审批分支是 checked → created → approved → allowed 四条）⊃ `event_id`（一条记录）。

`approval_id` 是横切的第四个，只在审批分支存在，生命周期比上面三个都短：
request → approve / reject / expire，之后那个请求对象就没用了（存储纯内存实现也成立）。
它进日志**不是**为了做 join —— 四条审批记录本来就被同一个 `trace_id` 串着 ——
而是因为它是控制台打给人看的那个字符串：不记它，日志这一侧就和操作员当时看到的对不上。

**边界要由动作定义，不能由「谁碰巧构造了一个对象」定义。** 上一版把生成逻辑写成
`field(default_factory=...)`，于是任何 `PermissionContext` 构造都会铸新编号 ——
「试一下另一个 subject」会静默把一次 run 的审计流切成两段。现在铸新编号只发生在一处：`_load_runtime()`，
而它就是「开新一轮」这个动作本身 —— `@initialize` 是唯一的边界。
同理，嵌套 `@initialize` 会让外层剩下的部分落到新编号上而且换不回来
（`_current_context` 是普通全局、没有栈），所以直接 assert 拦掉，不留给约定。

`set_current_context()` 一并删掉，赋值内联进唯一的调用方 `_load_runtime()`。
它是 `42cf055`（`_current_context` 从 ContextVar
改成普通全局）时顺手导出的赋值助手，两个仓库里外部零调用，而库本身从来没有
「运行中换 subject」的意图（进程级全局，不支持并发多 subject）。它公开着的唯一作用
就是多一个能让 `episode_id` 漂移的入口。删掉之后 `episode_id` 从有默认值改回**必填** ——
没有默认值，就没有「谁碰巧构造了一个 context」这种边界。
**审批请求不落盘。** 它的生命周期是 request → approve / reject / expire，秒级，
决策就在 `check_permission()` 的同一个作用域里当场做完 —— 没有任何理由活过进程。
落盘换来的是一份永远不清理、永远没人读的历史，外加原子写和并发覆盖两个本来不存在的问题。
`approval_id` 仍然进 `audit.jsonl`（那是审计，不是状态存储）。

**取舍**：
- **不接受调用方注入坐标**（步号、任务号之类）。曾经考虑过让调用方把它自己的
  episode/step 喂进来当 join 键，那是把依赖方向搞反了：库会因此需要认识调用方的
  函数签名，而调用方也得为权限流的编号负责。正确的方向是调用方读
  `get_current_context().episode_id`，在它自己的事件流里记一次映射 —— 耦合为零，
  而 `@initialize` 天然就是 run 的边界，两边一一对应。
- 理由不另起一次 `input()`：第二次读取要单独算超时预算，让人按完回车再等一个不确定的
  窗口，比拿不到理由更糟。所以跟决策同一行解析。
- **删掉零调用方的东西，而不是留着「以后可能用」**：`get()`、`set_current_context()`
  都是写好了没接线的公开 API。留着的代价不是那几行代码，是下一个人会以为它在被用。
  真要做异步审批（进程 A 发起、人在别处批、A 轮询），需要的是一个能跨进程的存储实现，
  不是现在这份文件读写 —— `ApprovalStore` 这个 Protocol 就是为那天留的。
- **不按 permission 分库。** key 是 `approval_id`（uuid4，全局唯一），分库带不来任何东西 ——
  那是文件存储时代的产物，分的是文件名（一个 permission 一个 `data_*.json`）。
  照搬到内存实现上，它唯一的效果是制造一个「实例拿错就找不到请求」的洞，
  然后还得为这个自造的洞加一层按 permission 的实例缓存。全局一个实例就够。

**已知行为**：包被 import 时模块级那句 `runtime_context = _load_runtime()` 就已经铸了一个
编号，所以任何 `@initialize` 跑之前就存在一个「第 0 号 episode」。这是刻意保留的 ——
它保证任何时刻都有编号，审计记录不会出现 `episode_id` 为空。

**影响面**：**破坏性变更。** `audit.record()` 的 `episode_id` / `trace_id` 是必填 keyword，
任何直接调 `record()` 的地方都要改；`decision` 从 `AuditEvent` 消失，
下游按它解析 `audit.jsonl` 的会读不到，而 `trace_id` 从「永远 null」变成有值。
`@initialize` 的嵌套调用从「静默换编号」变成抛 AssertionError。
`LocalFileApprovalStore` 与 `ApprovalStore.get()` 从 API 中消失；`log/data_*.json` 不再产生
（旧文件可以直接删）。
`set_current_context` 从 API 中消失，`PermissionContext(...)` 现在必须传 `episode_id`
（外部本来就不该自己构造它，读用 `get_current_context()`）。旧的 `audit.jsonl` 与新记录 schema 不同，
建议直接归档旧文件另起一份。`ApprovalRequest` 新增 `timeout_seconds` 字段，
旧存档 `from_dict()` 时走默认值，兼容。
