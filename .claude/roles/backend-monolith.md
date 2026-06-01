# ===== Spring Boot 后端规范（单体架构） =====

> 适用场景：单个 Spring Boot 应用，不涉及服务拆分、服务注册、网关等微服务概念

## 技术栈（必须遵守）

| 组件 | 版本 | 说明 |
|------|------|------|
| Java | 1.8 | 不用 17+ |
| Spring Boot | 2.7.18 | Java 8 最后稳定版 |
| MyBatis-Plus | 3.5.5 | 不用 4.0+（要 Java 17） |
| MySQL Connector | 8.0.33 | `mysql:mysql-connector-java`，不用 8.2.0+（改名且要 Java 11） |
| Druid | 1.2.21 | `druid-spring-boot-starter`，不用 `boot-3-starter` |
| Redis | Lettuce（BOM 管理） | `spring-boot-starter-data-redis` |
| Elasticsearch | 7.17.x（BOM 管理） | 按需引入，不用 8.x |
| Knife4j | 4.3.0 | `knife4j-openapi2-spring-boot-starter`，不用 `openapi3-jakarta` |
| MapStruct | 1.5.5.Final | 必须配合 `lombok-mapstruct-binding:0.2.0` |
| Lombok | 1.18.36 | |
| Hutool | 5.8.33 | 不用 6.x（要 Java 17） |
| Sa-Token | 1.37.0 | 认证授权，不用 1.38.0+（要 Java 17） |

> 单体架构不需要：Spring Cloud、Nacos、Sentinel、Gateway、RocketMQ

## 避坑清单

- MySQL Connector 必须用 `mysql:mysql-connector-java:8.0.33`，8.2.0+ 改名且要 Java 11
- Knife4j 必须用 `openapi2-spring-boot-starter`，不是 `openapi3-jakarta`
- Druid 必须用 `druid-spring-boot-starter`，不是 `druid-spring-boot-3-starter`
- MyBatis-Plus 3.5.5 止步，4.0+ 要 Java 17
- Sa-Token 必须用 1.37.0 + `sa-token-spring-boot-starter`，1.38.0+ 要 Java 17
- MapStruct + Lombok 必须加 `lombok-mapstruct-binding:0.2.0`，否则编译字段丢失
- `application.yml` 必须加 `spring.mvc.pathmatch.matching-strategy: ant_path_matcher`

## 开发命令
- `./mvnw spring-boot:run` — 启动应用（端口 8080）
- `./mvnw test` — 运行单元测试
- `./mvnw clean package` — 打包

## 项目结构（单体，按功能模块划分）

```
src/main/java/com/example/club
├── common/                      # 公共模块
│   ├── core/                    # R.java、BaseEntity、常量
│   ├── exception/               # GlobalExceptionHandler
│   ├── annotation/              # @Log 操作日志
│   └── utils/                   # 工具类
├── config/                      # SaTokenConfig、MybatisPlusConfig 等
├── modules/                     # 业务模块（按功能拆分，不是按层）
│   └── xxx/
│       ├── controller/          # Controller 层
│       ├── service/             # Service 接口
│       │   └── impl/            # Service 实现
│       ├── mapper/              # Mapper（MyBatis-Plus）
│       ├── domain/
│       │   ├── entity/          # 数据库实体
│       │   ├── dto/             # 入参对象
│       │   └── vo/              # 返回视图对象
│       └── enums/               # 业务枚举
└── ClubApplication.java         # 启动类
```

## 分层规范（严格遵守，参考 RuoYi/eladmin 模式）

### Controller 层
- 只负责：接收请求 → 参数校验 → 调用 Service → 返回结果
- **禁止写任何业务逻辑**
- 使用 `@RestController` + `@RequestMapping`
- 参数校验使用 `@Validated` + JSR-303（`@NotBlank`、`@Size`、`@Email`）
- 返回统一响应体 `R<T>`

```java
@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class UserController {

    private final IUserService userService;

    @GetMapping("/list")
    public R<PageResult<UserVO>> list(UserQueryDTO query) {
        return R.ok(userService.listUsers(query));
    }

    @PostMapping
    public R<Void> add(@Validated @RequestBody UserDTO dto) {
        userService.createUser(dto);
        return R.ok();
    }
}
```

### Service 层
- **接口 + 实现**：`IUserService` + `UserServiceImpl`
- 所有业务逻辑在此层，核心业务编排层
- `@Transactional` 加在实现方法上，查询加 `readOnly = true`
- 禁止处理 HTTP 相关逻辑

```java
public interface IUserService {
    PageResult<UserVO> listUsers(UserQueryDTO query);
    void createUser(UserDTO dto);
}

@Service
@RequiredArgsConstructor
public class UserServiceImpl implements IUserService {

    private final UserMapper userMapper;

    @Override
    @Transactional(readOnly = true)
    public PageResult<UserVO> listUsers(UserQueryDTO query) {
        // 1. 查询数据
        // 2. 转换为 VO
        // 3. 返回分页结果
    }
}
```

### Mapper 层
- 只负责数据库操作，**禁止写业务判断**
- 继承 `BaseMapper<Entity>`
- 复杂 SQL 放 `resources/mapper/xxx/*.xml`

### Entity / DTO / VO
- **Entity**：继承 `BaseEntity`，字段与表一一对应
- **DTO**：接口入参加 JSR-303 校验注解
- **VO**：返回给前端，**禁止直接返回 Entity**
- 转换用 MapStruct 或 `BeanUtil.copyProperties`

## 统一响应体 R<T>
```json
{ "code": 200, "msg": "操作成功", "data": {} }
```
- 成功：`R.ok()` / `R.ok(data)`
- 失败：`R.fail("错误信息")` / `R.fail(ErrorCode.XXX)`

## 全局异常处理

```java
@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    public R<Void> handleBiz(BusinessException e) {
        log.warn("业务异常: {}", e.getMessage());
        return R.fail(e.getCode(), e.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public R<Void> handleValidation(MethodArgumentNotValidException e) {
        String msg = e.getBindingResult().getFieldErrors().stream()
            .map(FieldError::getDefaultMessage)
            .collect(Collectors.joining("; "));
        return R.fail(msg);
    }

    @ExceptionHandler(Exception.class)
    public R<Void> handleException(Exception e) {
        log.error("系统异常", e);
        return R.fail("系统繁忙，请稍后重试");
    }
}
```

## 参数校验规范
- Controller 入参加 `@Validated`
- DTO 内部用 JSR-303：`@NotBlank`、`@NotNull`、`@Size`、`@Email`、`@Pattern`
- 分组校验：`@Validated(CreateGroup.class)`
- 自定义校验注解放 `common/annotation/`

## 代码注入规范
- **优先构造器注入**，`@RequiredArgsConstructor`（final 字段）
- 禁止 `@Autowired` 字段注入

## 安全规范
- 使用 Sa-Token 1.37.0（`sa-token-spring-boot-starter`，不用 `sa-token-spring-boot3-starter`）
- Token 存 Redis，支持登录/注销/权限校验/路由拦截
- 方法级权限：`@SaCheckPermission` / `@SaCheckRole`
- 敏感信息用环境变量，禁止明文配置
- 生产环境关闭 Knife4j

## 日志规范
- 使用 `@Slf4j`，禁止 `System.out.println`
- 操作日志：`@Log` 注解 + AOP（谁在什么时间做了什么）
- 异常日志：`log.error("描述", e)`，必须带完整堆栈
- 生产环境用 JSON 格式日志

## 事务规范

### 基本规则
- `@Transactional` 加在 Service 实现方法上，禁止在 Controller 层加事务
- 只读查询加 `readOnly = true`，减少数据库锁开销
- 必须指定 `rollbackFor = Exception.class`（Spring 默认只回滚 `RuntimeException`）
- 禁止在循环内开事务，应在循环外包裹一个大事务或分批提交

### 事务粒度控制（声明式事务的核心）

**原则：事务范围 = 业务原子操作的边界，不多不少**

```java
// ❌ 事务粒度过粗：整个方法包在一个事务里，非事务操作（发消息、调外部接口）也在里面
//    问题：长事务锁表、外部调用超时拖垮事务、回滚范围太大
@Transactional(rollbackFor = Exception.class)
public void createOrderAndNotify(OrderDTO dto) {
    orderService.create(dto);           // 需要事务
    inventoryService.deduct(dto);       // 需要事务
    smsService.send(dto.getPhone());    // 不需要事务，且失败不应回滚订单
}

// ✅ 正确拆分：核心业务在事务内，外部调用放到事务外
public void createOrderAndNotify(OrderDTO dto) {
    doCreateOrder(dto);          // 事务方法
    smsService.send(dto.getPhone()); // 事务外，失败不回滚
}

@Transactional(rollbackFor = Exception.class)
public void doCreateOrder(OrderDTO dto) {
    orderService.create(dto);
    inventoryService.deduct(dto);
}
```

### 精确控制的典型场景

| 场景 | 做法 |
|------|------|
| 只读查询 | `@Transactional(readOnly = true)`，走读库/减少锁 |
| 多表写入 | 同一方法内统一提交，保持原子性 |
| 写入 + 发 MQ / 调第三方 | 事务内只包写入，MQ/外部调用放事务外（或用事务消息） |
| 批量插入（大量数据） | 分批提交：每 500 条 `flush + clear`，避免长事务撑爆 undo log |
| 嵌套调用 | 同类内调用 `@Transactional` 方法不生效（AOP 代理限制），需注入自身或抽到另一个 Service |
| 部分回滚 | 不支持，用 `savepoint` 思路拆成多个小事务方法组合调用 |

### 事务失效的常见陷阱（必须规避）

```java
// ❌ 陷阱1：同类内部调用，事务不生效
public void outer() {
    this.inner(); // 直接调用，不走代理，@Transactional 无效
}

// ✅ 解决：注入自身代理，或拆到另一个 Bean
@Autowired private UserService self;
public void outer() {
    self.inner();
}

// ❌ 陷阱2：private 方法加事务不生效
@Transactional
private void inner() { ... } // Spring AOP 代理无法拦截 private

// ✅ 事务方法必须是 public

// ❌ 陷阱3：吞掉异常导致不回滚
@Transactional(rollbackFor = Exception.class)
public void doSomething() {
    try {
        save(data);
    } catch (Exception e) {
        log.error("保存失败", e); // 异常被吞，事务不会回滚
    }
}

// ✅ 让异常抛出，或手动标记回滚
@Transactional(rollbackFor = Exception.class)
public void doSomething() {
    try {
        save(data);
    } catch (Exception e) {
        log.error("保存失败", e);
        throw new BizException("保存失败"); // 抛出异常触发回滚
    }
}
```

## 接口规范
- RESTful：`GET /api/users/{id}`、`POST`、`PUT`、`DELETE`
- 分页：`pageNum` + `pageSize`，返回 `PageResult<T>`（含 total、list）
- 批量：`POST /api/users/batch`

## Knife4j 接口文档规范

> 参考来源：ruoyi-vue-pro（12k+ star）、eladmin、pig 等主流开源项目

### 基本配置
- 使用 `knife4j-openapi2-spring-boot-starter`，不用 `openapi3-jakarta`（要 Java 17）
- 注解包：`io.swagger.annotations`（OpenAPI 2）
- 访问地址：`http://localhost:8080/doc.html`
- 生产环境必须关闭：`knife4j.enable: false`

### application.yml 标准配置

```yaml
knife4j:
  enable: true
  openapi:
    # 项目整体描述，按实际项目填写，不要写默认占位文字
    title: Club 社团活动管理系统
    description: 提供社团活动发布、成员管理、签到打卡、财务记录等全部后台管理功能的 API
    version: 1.0.0
    concat:
      name: Club 团队
      email: club@example.com
    license: MIT
    license-url: https://github.com/yourname/club/blob/main/LICENSE
    group:
      default:
        group-name: 社团管理后台
        api-rule: package
        api-rule-resources:
          - { name: 活动管理, package-path: club.activity.controller }
          - { name: 成员管理, package-path: club.member.controller }
          - { name: 财务管理, package-path: club.finance.controller }
          - { name: 签到管理, package-path: club.checkin.controller }
          - { name: 通知公告, package-path: club.notice.controller }
    # 全局请求头：所有接口自动携带，不用每个方法单独写
    global-parameters:
      - name: satoken
        description: 用户登录凭证（登录接口返回，后续请求放在 Header 中）
        required: true
        in: header
        parameter:
          type: string
```

**description 写法原则**：写清楚系统是做什么的、覆盖哪些业务，不要写"前后端分离 API 文档"这种无信息量的文字。

---

### 注解使用规范

#### 1. Controller 层 — `@Api` + `@ApiOperation`

**分组命名格式：`@Api(tags = "{系统端} - {业务模块}")`**

```java
@Api(tags = "管理后台 - 活动管理")
@RestController
@RequestMapping("/api/activity")
public class ActivityController {

    @ApiOperation(
        value = "分页查询活动列表",
        notes = "支持按活动名称、状态、时间范围筛选，返回分页结果，用于管理后台活动列表页"
    )
    @GetMapping("/list")
    public Result<PageResult<ActivityVO>> list(ActivityPageReqVO query) {
        // ...
    }

    @ApiOperation(
        value = "获取活动详情",
        notes = "包含活动基本信息、已报名人数、签到统计，用于活动详情页展示"
    )
    @ApiImplicitParam(name = "id", value = "活动ID", required = true, dataType = "Long")
    @GetMapping("/{id}")
    public Result<ActivityVO> detail(@PathVariable Long id) {
        // ...
    }

    @ApiOperation(
        value = "创建活动",
        notes = "创建后状态默认为"未发布"，需手动发布后成员才可见"
    )
    @PostMapping
    public Result<Long> create(@RequestBody @Valid ActivitySaveReqVO dto) {
        // ...
    }

    @ApiOperation(
        value = "删除活动",
        notes = "已有人报名的活动不允许直接删除，需先取消报名"
    )
    @ApiImplicitParam(name = "id", value = "活动ID", required = true, dataType = "Long")
    @DeleteMapping("/{id}")
    public Result<Void> delete(@PathVariable Long id) {
        // ...
    }

    @ApiOperation(
        value = "导出活动列表",
        notes = "按当前筛选条件导出 Excel，最多导出 500 条，超出请缩小筛选范围"
    )
    @GetMapping("/export")
    public void export(ActivityPageReqVO query, HttpServletResponse response) {
        // ...
    }
}
```

**notes 写法原则**：
- `value`：动词 + 名词，简洁概括（是什么）
- `notes`：写使用场景、业务约束、返回内容说明（什么时候用、有什么限制）
- 不要写"查询活动列表"这种和 value 重复的话

**分组命名示例**（按实际项目调整）：

| tags | 适用场景 |
|------|---------|
| `管理后台 - 活动管理` | 后台管理员操作活动 |
| `管理后台 - 成员管理` | 后台管理员管理社团成员 |
| `用户端 - 我的活动` | 普通用户查看自己报名的活动 |
| `用户端 - 签到打卡` | 普通用户签到相关接口 |

如果项目只有管理后台，直接写 `活动管理`、`成员管理` 即可，不需要前缀。

---

#### 2. VO / DTO 层 — `@ApiModel` + `@ApiModelProperty`

**原则：每个 VO 只暴露当前场景需要的字段，不直接注解实体类。**

```java
/**
 * 创建/修改活动 — 请求参数
 */
@Data
@ApiModel("活动保存参数（创建/修改共用）")
public class ActivitySaveReqVO {

    @ApiModelProperty(value = "活动ID", hidden = true)
    private Long id;   // 创建时不用传，修改时必传，隐藏避免混淆

    @ApiModelProperty(
        value = "活动名称",
        required = true,
        example = "2026年春季社团招新"
    )
    @NotBlank(message = "活动名称不能为空")
    private String name;

    @ApiModelProperty(
        value = "活动类型，见 ActivityTypeEnum 枚举",
        required = true,
        example = "1",
        allowableValues = "1,2,3"   // 1=线下活动, 2=线上活动, 3=混合活动
    )
    @NotNull(message = "活动类型不能为空")
    private Integer type;

    @ApiModelProperty(
        value = "开始时间",
        required = true,
        example = "2026-06-15 09:00:00"
    )
    @NotNull
    private LocalDateTime startTime;

    @ApiModelProperty(
        value = "结束时间，必须晚于开始时间",
        required = true,
        example = "2026-06-15 17:00:00"
    )
    @NotNull
    private LocalDateTime endTime;

    @ApiModelProperty(
        value = "参与人数上限，0 表示不限制",
        example = "50"
    )
    @Max(value = 999, message = "人数上限不能超过999")
    private Integer maxParticipants;

    @ApiModelProperty(
        value = "活动封面图 URL",
        example = "https://cdn.example.com/activity-cover.jpg"
    )
    private String coverUrl;

    @ApiModelProperty(
        value = "活动详情（富文本）",
        example = "<p>欢迎大家参加本次社团招新活动</p>"
    )
    private String content;
}

/**
 * 活动列表查询 — 请求参数
 */
@Data
@ApiModel("活动分页查询参数")
public class ActivityPageReqVO extends PageParam {

    @ApiModelProperty(value = "活动名称（模糊搜索）", example = "招新")
    private String name;

    @ApiModelProperty(value = "活动状态，见 ActivityStatusEnum", example = "1")
    private Integer status;

    @ApiModelProperty(value = "开始时间-起", example = "2026-06-01 00:00:00")
    private LocalDateTime startTimeBegin;

    @ApiModelProperty(value = "开始时间-止", example = "2026-06-30 23:59:59")
    private LocalDateTime startTimeEnd;
}

/**
 * 活动详情 — 响应参数
 */
@Data
@ApiModel("活动详情响应")
public class ActivityVO {

    @ApiModelProperty(value = "活动ID", example = "1001")
    private Long id;

    @ApiModelProperty(value = "活动名称", example = "2026年春季社团招新")
    private String name;

    @ApiModelProperty(value = "活动状态，见 ActivityStatusEnum", example = "2")
    private Integer status;

    @ApiModelProperty(value = "已报名人数", example = "32")
    private Integer enrolledCount;

    @ApiModelProperty(value = "创建时间", example = "2026-06-01 10:30:00")
    private LocalDateTime createTime;
}
```

---

### 字段描述写作标准

| 场景 | 差（信息量低） | 好（一看就懂） |
|------|---------------|---------------|
| 活动名称 | `value = "名称"` | `value = "活动名称，不超过 50 字"` |
| 状态字段 | `value = "状态"` | `value = "活动状态，见 ActivityStatusEnum 枚举（1=未发布 2=报名中 3=已结束）"` |
| 时间字段 | `value = "时间"` | `value = "活动开始时间，不能早于当前时间"` |
| 金额字段 | `value = "金额"` | `value = "活动经费预算，单位：元，最多两位小数"` |
| 外键字段 | `value = "用户ID"` | `value = "发起人的用户ID，关联 member 表"` |
| 枚举/下拉 | `value = "类型"` | `value = "活动类型"，allowableValues = "1,2,3"` |

**example 写法原则**：
- 用真实业务数据，不用 `"string"`、`"null"`、`"0"`
- 时间字段：`"2026-06-15 09:00:00"`
- 枚举字段：填一个合法的枚举值，如 `"1"` 而不是空
- ID 字段：用合理的数字，如 `"1001"` 而不是 `"0"`

---

### 规则清单

**必须遵守**：
- `@Api(tags)` — 每个 Controller 必加，按业务模块命名
- `@ApiOperation(value, notes)` — 每个接口方法必加，notes 写使用场景和业务约束
- `@ApiModelProperty(value, example)` — VO/DTO 每个字段必加，example 必须填真实值
- 枚举字段在 description 里注明枚举类名和主要值，或用 `allowableValues` 列出
- 全局 Header（satoken）只在 `application.yml` 配一次，不重复注解

**禁止**：
- description 写 `"string"`、`"null"`、`"测试"` 等无意义占位文字
- 直接在 Entity 实体类上加 `@ApiModelProperty`（暴露数据库字段）
- `@ApiModelProperty` 不写 example（导致 Knife4j 的 Try 功能无法使用）
- Controller 不加 `@Api`，接口不加 `@ApiOperation`（文档空白）

## 配置规范
- `application.yml` — 公共配置
- `application-dev.yml` — 本地开发
- `application-prod.yml` — 生产环境
- 敏感信息用 `${ENV_VAR}` 注入
- **必须加**：`spring.mvc.pathmatch.matching-strategy: ant_path_matcher`

## 测试规范
- JUnit 5 + Mockito 做单元测试
- Service 层覆盖率目标 80%+
- 测试命名：`should_期望行为_when_条件`

### 测试用例设计方法

#### 等价类划分（Equivalence Partitioning）
把输入数据分成若干等价类，每个类取一个代表值测试，避免重复覆盖。
```
示例：用户年龄字段（有效范围 1~150）
有效等价类：[1~150]  → 测试 25（代表值）
无效等价类：<1       → 测试 0
无效等价类：>150     → 测试 200
无效等价类：非数字   → 测试 "abc"
```

#### 边界值分析（Boundary Value Analysis）
测试边界上的值，最容易出 bug：最小值、最小值-1、最大值、最大值+1。
```
示例：分页 pageSize（有效范围 1~100）
边界值：0、1、2、99、100、101
```

#### 判定表（Decision Table）
多条件组合的业务逻辑，列出所有条件组合和预期结果。

#### 状态转换测试（State Transition Testing）
有状态的业务（订单、审批流），测试状态之间的合法/非法转换。

#### 错误推测（Error Guessing）
- null / 空串 / 空集合
- 重复提交（幂等性）
- 并发竞争条件
- 超时 / 网络异常
- 数值溢出 / 精度丢失（金额用 BigDecimal）

### 测试结构（AAA 模式）
```java
@Test
@DisplayName("创建用户 - 邮箱重复应抛异常")
void should_throw_when_email_already_exists() {
    // Arrange
    UserDTO dto = new UserDTO("test@example.com");
    when(userMapper.selectByEmail("test@example.com")).thenReturn(new User());

    // Act
    BizException ex = assertThrows(BizException.class,
        () -> userService.createUser(dto));

    // Assert
    assertEquals("邮箱已存在", ex.getMessage());
}
```

### 必须测试的场景清单
- 正常流程（Happy Path）
- 参数为 null / 空 / 格式错误
- 边界值（最小值 / 最大值 / 超出范围）
- 业务异常（如余额不足、库存为0）
- 幂等性（重复调用同一接口结果一致）
- 权限不足（无权访问应返回 403）
