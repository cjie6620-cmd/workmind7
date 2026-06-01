# ===== Spring Boot 后端规范（微服务架构） =====

> 适用场景：多服务拆分、需要服务注册/发现、网关、分布式事务、消息队列等

## 技术栈（必须遵守）

| 组件 | 版本 | 说明 |
|------|------|------|
| Java | 1.8 | 不用 17+ |
| Spring Boot | 2.7.18 | Java 8 最后稳定版 |
| Spring Cloud | 2021.0.5 | 与 Boot 2.7 对齐 |
| Spring Cloud Alibaba | 2021.0.5.0 | Nacos + Sentinel |
| Nacos Server | 2.2.3 | 服务注册 / 配置中心 |
| MyBatis-Plus | 3.5.5 | 不用 4.0+（要 Java 17） |
| MySQL Connector | 8.0.33 | `mysql:mysql-connector-java`，不用 8.2.0+（改名且要 Java 11） |
| Druid | 1.2.21 | `druid-spring-boot-starter`，不用 `boot-3-starter` |
| Redis | Lettuce（BOM 管理） | `spring-boot-starter-data-redis` |
| Elasticsearch | 7.17.x（BOM 管理） | 按需引入，不用 8.x |
| XXL-Job | 2.4.1 | 分布式任务调度 |
| RocketMQ | 2.2.3 | 不用 2.3.0+（偏向 Boot 3） |
| Knife4j | 4.3.0 | `knife4j-openapi2-spring-boot-starter`，不用 `openapi3-jakarta` |
| MapStruct | 1.5.5.Final | 必须配合 `lombok-mapstruct-binding:0.2.0` |
| Lombok | 1.18.36 | |
| Hutool | 5.8.33 | 不用 6.x（要 Java 17） |
| Sa-Token | 1.37.0 | 认证授权，不用 1.38.0+（要 Java 17） |
| Sentinel | 1.8.6（BOM 管理） | 限流 / 熔断 |

## 避坑清单

- MySQL Connector 必须用 `mysql:mysql-connector-java:8.0.33`，8.2.0+ 改名且要 Java 11
- Knife4j 必须用 `openapi2-spring-boot-starter`，不是 `openapi3-jakarta`
- Druid 必须用 `druid-spring-boot-starter`，不是 `druid-spring-boot-3-starter`
- MyBatis-Plus 3.5.5 止步，4.0+ 要 Java 17
- Sa-Token 必须用 1.37.0 + `sa-token-spring-boot-starter`，1.38.0+ 要 Java 17
- MapStruct + Lombok 必须加 `lombok-mapstruct-binding:0.2.0`，否则编译字段丢失
- `application.yml` 必须加 `spring.mvc.pathmatch.matching-strategy: ant_path_matcher`
- Nacos Server 版本必须与客户端对齐（2.2.3），版本不匹配会注册失败

## 开发命令
- `./mvnw spring-boot:run` — 启动单个服务
- `./mvnw test` — 运行单元测试
- `./mvnw clean package` — 打包
- `docker compose -f docker/docker-compose.yml up -d` — 启动 Nacos / MySQL / Redis 等基础设施

## 项目结构（多模块微服务）

```
club/                            # 根项目（聚合）
├── club-gateway/                # 网关服务（Spring Cloud Gateway）
├── club-auth/                   # 认证服务（Sa-Token + OAuth2）
├── club-system/                 # 系统管理服务（用户、角色、菜单）
├── club-activity/               # 活动管理服务（业务核心）
├── club-common/                 # 公共模块（被所有服务依赖）
│   ├── club-common-core/        # R.java、BaseEntity、常量、工具类
│   ├── club-common-redis/       # Redis 配置与工具
│   ├── club-common-mybatis/     # MyBatis-Plus 公共配置
│   ├── club-common-security/    # Sa-Token 公共配置
│   └── club-common-log/         # @Log 操作日志
└── pom.xml                      # 父 POM（统一版本管理）
```

### 单个服务内部结构
```
club-system/
├── src/main/java/.../system/
│   ├── controller/              # Controller 层
│   ├── service/                 # Service 接口
│   │   └── impl/                # Service 实现
│   ├── mapper/                  # Mapper（MyBatis-Plus）
│   ├── domain/
│   │   ├── entity/              # 数据库实体
│   │   ├── dto/                 # 入参对象
│   │   └── vo/                  # 返回视图对象
│   ├── feign/                   # Feign 调用其他服务（可选）
│   └── enums/                   # 业务枚举
└── src/main/resources/
    ├── application.yml
    ├── bootstrap.yml            # Nacos 配置中心
    └── mapper/                  # MyBatis XML
```

## 服务间调用规范
- 同步调用：OpenFeign（`@FeignClient`）
- 异步通信：RocketMQ（解耦、削峰）
- Feign 接口定义放在调用方，返回值用 `R<T>` 包装
- Feign 降级必须配置 Sentinel fallback

## 分布式事务
- 强一致性：Seata AT 模式（小事务，跨 2~3 个服务）
- 最终一致性：RocketMQ 事务消息（大流量场景）
- 禁止跨服务直接调数据库，必须走 Feign 或 MQ

## 分层规范（与单体一致，参考 RuoYi/eladmin 模式）

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

## 全局异常处理（放在 club-common-core）

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
- 自定义校验注解放 `club-common-core/annotation/`

## 代码注入规范
- **优先构造器注入**，`@RequiredArgsConstructor`（final 字段）
- 禁止 `@Autowired` 字段注入

## 安全规范
- 使用 Sa-Token 1.37.0（`sa-token-spring-boot-starter`，不用 `sa-token-spring-boot3-starter`）
- 网关统一鉴权（`SaReactorFilter`），业务服务只做权限校验
- Token 存 Redis，支持登录/注销/权限校验/路由拦截
- 方法级权限：`@SaCheckPermission` / `@SaCheckRole`
- 敏感信息用 Nacos 配置中心或环境变量，禁止硬编码
- 生产环境关闭 Knife4j

## 网关规范（club-gateway）
- 路由转发：按服务名自动路由（`lb://club-system/api/**`）
- 统一鉴权：`SaReactorFilter` 在网关层拦截
- 限流：Sentinel 网关限流规则
- 跨域：网关统一配置 CORS，业务服务不重复配置
- 日志：记录所有请求的 traceId，方便跨服务排查

## 日志规范
- 使用 `@Slf4j`，禁止 `System.out.println`
- 操作日志：`@Log` 注解 + AOP（谁在什么时间做了什么）
- 异常日志：`log.error("描述", e)`，必须带完整堆栈
- 生产环境用 JSON 格式日志
- **分布式日志**：所有请求带 traceId（Sleuth/Zipkin），跨服务可追踪

## 事务规范
- `@Transactional` 加在 Service 实现方法上
- 只读查询加 `readOnly = true`
- 业务异常需指定 `rollbackFor = Exception.class`
- 禁止在 Controller 层加事务
- 跨服务事务用 Seata AT 或 RocketMQ 事务消息

## 接口规范
- RESTful：`GET /api/users/{id}`、`POST`、`PUT`、`DELETE`
- 分页：`pageNum` + `pageSize`，返回 `PageResult<T>`（含 total、list）
- 批量：`POST /api/users/batch`
- 服务内部调用：Feign 接口，返回 `R<T>`

## 配置规范
- 公共配置放 Nacos 配置中心（`bootstrap.yml` 指定 `server-addr`）
- `application.yml` — 服务自身配置
- 敏感信息用 Nacos 加密配置或环境变量
- **必须加**：`spring.mvc.pathmatch.matching-strategy: ant_path_matcher`
- 每个服务配置 `spring.application.name`，与 Nacos 注册名一致

## 测试规范
- JUnit 5 + Mockito 做单元测试
- Service 层覆盖率目标 80%+
- 测试命名：`should_期望行为_when_条件`

### 测试用例设计方法

#### 等价类划分（Equivalence Partitioning）
把输入数据分成若干等价类，每个类取一个代表值测试，避免重复覆盖。

#### 边界值分析（Boundary Value Analysis）
测试边界上的值：最小值、最小值-1、最大值、最大值+1。

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
- **服务调用超时 / 降级**（微服务特有）
- **MQ 消息丢失 / 重复消费**（微服务特有）

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
- Feign 调用超时 / 降级生效
- MQ 消息发送与消费链路验证
