# Spring Boot 3.2.0 + Spring Security + JWT Hello World

一个可直接运行的 Spring Boot 3.2.0 示例工程：`GET /api/hello` 必须经过 Spring Security 认证，认证通过后返回纯文本 `Hello World`；`POST /api/login` 使用用户名密码换取 JWT。未认证访问返回 **401**，不会 302 跳转登录页。

---

## 一、题目

> Implement a project using SpringBoot 3.2.0. With a GET method HelloWorld API that requires SpringSecurity authentication, which returns a string saying "Hello World". And a username-password login API (could use username test and password 123456). Submit a GitHub link.

对应实现：

| 题目要求 | 本工程实现 |
| --- | --- |
| Spring Boot 3.2.0 | `pom.xml` 的 parent 精确锁定 `spring-boot-starter-parent:3.2.0` |
| GET HelloWorld，需 Spring Security 认证 | `GET /api/hello`，未带 token 返回 401 JSON，带合法 token 返回 `Hello World` |
| 用户名密码登录 | `POST /api/login`，演示账号 `test / 123456` |
| 返回 token | 登录成功返回 HS256 JWT（`tokenType: Bearer`，有效期 3600 秒） |
| 认证方式 | `Authorization: Bearer <token>` |

---

## 二、技术选型

| 组件 | 版本 / 说明 |
| --- | --- |
| Spring Boot | **3.2.0**（parent 精确指定） |
| Java | 编译目标 Java 17；本机用 JDK 21.0.6 运行（Spring Boot 3.2 支持 17+） |
| Spring Security | 6.2.x（由 Boot 3.2.0 BOM 管理），无状态 JWT 认证 |
| 密码编码 | `BCryptPasswordEncoder`（Spring Security 自带），内存中只存 BCrypt 哈希 |
| JWT | **自实现 HS256**，仅用 JDK 的 `javax.crypto.Mac`，不引入 jjwt 等第三方库，避免依赖下载风险 |
| 参数校验 | `spring-boot-starter-validation`（Jakarta Validation） |
| 测试 | JUnit 5 + `spring-boot-starter-test` + MockMvc + AssertJ |
| 构建 | Maven 3.9.9（`spring-boot-maven-plugin` 打可执行 fat jar） |

设计要点：

- **无状态**：`SessionCreationPolicy.STATELESS`，不创建 `HttpSession`，完全依赖 Bearer token。
- **不跳登录页**：显式关闭 `formLogin` / `httpBasic`，并用自定义 `AuthenticationEntryPoint` 输出 401 JSON，响应中不带 `Location` 头。
- **密码不落地明文比较**：启动时把 `123456` 用 BCrypt 编码后放入 `InMemoryUserDetailsManager`，登录时由 `DaoAuthenticationProvider` 调 `PasswordEncoder.matches` 校验。
- **分层**：`controller` / `service` / `security` / `config` / `dto` / `exception` 各司其职。

---

## 三、接口说明

Base URL：`http://127.0.0.1:8080`

| 方法 | 路径 | 是否需要认证 | 请求 | 成功响应 | 失败响应 |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/login` | 否 | JSON `{"username":"test","password":"123456"}` | `200` + JSON（含 token） | `400` 参数非法；`401` 用户名或密码错误 |
| `GET` | `/api/hello` | 是，`Authorization: Bearer <token>` | 无 | `200`，`Content-Type: text/plain`，body 恰好为 `Hello World` | `401` 未带 / 无效 / 过期 token |

### 3.1 登录 `POST /api/login`

请求头：`Content-Type: application/json`

```json
{
  "username": "test",
  "password": "123456"
}
```

成功响应 `200 OK`：

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9....",
  "tokenType": "Bearer",
  "expiresIn": 3600,
  "username": "test"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `token` | string | HS256 JWT，三段式 `header.payload.signature` |
| `tokenType` | string | 固定 `Bearer`，放在 `Authorization` 头中 |
| `expiresIn` | number | 有效期（秒），默认 3600 |
| `username` | string | 登录用户名 |

### 3.2 Hello World `GET /api/hello`

请求头：`Authorization: Bearer <token>`

成功响应 `200 OK`：

```text
Content-Type: text/plain
Content-Length: 11

Hello World
```

未认证 / token 无效 / token 过期：`401 Unauthorized`，JSON 错误体（`Location` 为空，不会 302）：

```json
{
  "status": 401,
  "error": "Unauthorized",
  "message": "未认证：请先调用 POST /api/login 获取 token，并通过 Authorization: Bearer <token> 访问",
  "path": "/api/hello"
}
```

### 3.3 错误响应格式

所有错误统一为：

```json
{
  "status": 401,
  "error": "Unauthorized",
  "message": "具体原因",
  "path": "/api/login"
}
```

| HTTP 状态码 | 场景 |
| --- | --- |
| `200` | 请求成功 |
| `400` | 请求体不是合法 JSON，或 `username` / `password` 为空 |
| `401` | 未认证、token 无效/过期、用户名或密码错误 |
| `403` | 已认证但权限不足（兜底，当前无此业务场景） |

更细的接口文档见 [`docs/api.md`](docs/api.md)。

---

## 四、如何运行

### 4.1 环境要求

- JDK 17 或以上（本工程用 JDK 21.0.6 实测）
- Maven 3.6.3 或以上（实测 3.9.9）

### 4.2 标准命令

```bash
# 1. 跑测试 + 打包（推荐第一次执行）
mvn clean package

# 2. 只打包，跳过测试
mvn -q -DskipTests package

# 3. 只跑测试
mvn test

# 4. 启动 jar（默认 8080 端口）
java -jar target/springboot-helloworld-security-1.0.0.jar
```

启动后可另开一个终端调用接口；停止服务用 `Ctrl+C`。

改端口：

```bash
java -jar target/springboot-helloworld-security-1.0.0.jar --server.port=9090
```

### 4.3 本机（Windows 笔试题环境）复现命令

本环境 `mvn`、`java` 不在 PATH，且 Maven 本地仓库被沙箱限制在工作区，实际使用的命令如下（README 中所有结果均由这组命令产生）：

```powershell
$env:JAVA_HOME = 'C:\Program Files\Microsoft\jdk-21.0.6.7-hotspot'
$env:Path = "$env:JAVA_HOME\bin;$env:Path"

# mvn test
& 'D:\dsh-workplace\tools\apache-maven-3.9.9\bin\mvn.cmd' '-s' 'D:\dsh-workplace\tools\maven-settings.xml' '-Dmaven.repo.local=D:\dsh-workplace\.m2' '-B' '-ntp' 'test'

# 打包（跳过测试）
& 'D:\dsh-workplace\tools\apache-maven-3.9.9\bin\mvn.cmd' '-s' 'D:\dsh-workplace\tools\maven-settings.xml' '-Dmaven.repo.local=D:\dsh-workplace\.m2' '-q' '-DskipTests' 'package'

# 启动
& "$env:JAVA_HOME\bin\java.exe" -jar 'target\springboot-helloworld-security-1.0.0.jar'
```

> 注意：PowerShell 必须把整个 `-Dmaven.repo.local=...` 用单引号包成一个参数，否则会被拆成 `.repo.local=D` 之类的片段（首次构建就踩过这个坑）。

---

## 五、调用示例

### 5.1 PowerShell（`Invoke-RestMethod`）

```powershell
$base = 'http://127.0.0.1:8080'

# 1) 登录，拿到 token
$login = Invoke-RestMethod -Uri "$base/api/login" -Method Post `
    -ContentType 'application/json' `
    -Body '{"username":"test","password":"123456"}'
$login | ConvertTo-Json

# 2) 带 token 调用 /api/hello，返回字符串 Hello World
$hello = Invoke-RestMethod -Uri "$base/api/hello" `
    -Headers @{ Authorization = "Bearer $($login.token)" }
$hello
```

> **PowerShell 5.1 注意**：`Invoke-WebRequest` / `Invoke-RestMethod` 遇到 401 会直接抛异常，且 5.1 没有 `-SkipHttpErrorCheck`；从 `$_.Exception.Response` 读取 body 也可能为空。想查看 401 的完整响应，建议用 `curl.exe`（见 5.2）或 `System.Net.Http.HttpClient`。本 README 的 401 响应就是用 `curl.exe` / `HttpClient` 抓的。

### 5.2 curl

Windows 10/11 自带 `curl.exe`，Linux/macOS 的 `curl` 用法相同。

```bash
# 1) 登录
curl -i -X POST http://127.0.0.1:8080/api/login -H "Content-Type: application/json" -d '{"username":"test","password":"123456"}'

# 2) 带 token 访问（把 <token> 换成上一步返回值）
curl -i http://127.0.0.1:8080/api/hello -H "Authorization: Bearer <token>"

# 3) 未认证访问，预期 401
curl -i http://127.0.0.1:8080/api/hello

# 4) 错误密码，预期 401
curl -i -X POST http://127.0.0.1:8080/api/login -H "Content-Type: application/json" -d '{"username":"test","password":"wrong"}'
```

bash 下一行拿到 token：

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8080/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"123456"}' \
  | sed -E 's/.*"token":"([^"]+)".*/\1/')
curl -i http://127.0.0.1:8080/api/hello -H "Authorization: Bearer $TOKEN"
```

---

## 六、测试结果

### 6.1 `mvn test`（真实输出末尾）

```text
[INFO] Tests run: 7, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 3.444 s -- in com.example.helloworld.HelloWorldIntegrationTest
[INFO]
[INFO] Results:
[INFO]
[INFO] Tests run: 7, Failures: 0, Errors: 0, Skipped: 0
[INFO]
[INFO] ------------------------------------------------------------------------
[INFO] BUILD SUCCESS
[INFO] ------------------------------------------------------------------------
[INFO] Total time:  5.580 s
[INFO] Finished at: 2026-11-17T10:58:04+08:00
[INFO] ------------------------------------------------------------------------
```

### 6.2 测试用例（7 个，全部通过）

测试类：`src/test/java/com/example/helloworld/HelloWorldIntegrationTest.java`，使用 `@SpringBootTest` + `@AutoConfigureMockMvc`，走完整的 Spring Security 过滤器链。

| # | 用例 | 场景 | 期望 | 结果 |
| --- | --- | --- | --- | --- |
| 1 | `helloWithoutTokenReturns401` | 不带 token 访问 `/api/hello` | 401，且无 `Location` 头 | ✅ |
| 2 | `loginWithValidCredentialsReturnsToken` | `test/123456` 登录 | 200，返回三段式 token | ✅ |
| 3 | `helloWithValidTokenReturnsHelloWorld` | 带合法 token 访问 `/api/hello` | 200，`text/plain`，body 为 `Hello World` | ✅ |
| 4 | `loginWithWrongPasswordReturns401` | 错误密码登录 | 401 | ✅ |
| 5 | `loginWithUnknownUserReturns401` | 不存在的用户登录 | 401（不泄露用户是否存在） | ✅ |
| 6 | `helloWithTamperedTokenReturns401` | 篡改 token / 非 JWT 字符串 | 401 | ✅ |
| 7 | `loginWithMissingPasswordReturns400` | 缺少 `password` 字段 | 400 | ✅ |

> 关于 `src/test/resources/mockito-extensions/org.mockito.plugins.MockMaker`：在受限 Windows 沙箱里，Mockito 5 默认的 inline mock maker 需要自 attach 到当前 JVM（依赖外部进程/命名管道），会报 `Could not self-attach to current VM using external process`。本工程测试并未使用 Mockito，因此显式指定 `mock-maker-subclass` 规避该环境限制；普通开发机上加不加都能跑。

### 6.3 打包

```text
mvn -q -DskipTests package   -> 退出码 0
（-q 静默模式不打印 BUILD SUCCESS；非静默执行 package 时为 BUILD SUCCESS）
产物：target/springboot-helloworld-security-1.0.0.jar（24,375,485 字节）
```

---

## 七、本地验证（jar 端到端，真实响应）

启动：

```powershell
& "$env:JAVA_HOME\bin\java.exe" -jar 'target\springboot-helloworld-security-1.0.0.jar'
```

### 7.1 未认证访问 `/api/hello`（预期 401，且不跳转）

```text
$ curl.exe -s -i http://127.0.0.1:8080/api/hello
HTTP/1.1 401
Vary: Origin
Vary: Access-Control-Request-Method
Vary: Access-Control-Request-Headers
X-Content-Type-Options: nosniff
X-XSS-Protection: 0
Cache-Control: no-cache, no-store, max-age=0, must-revalidate
Pragma: no-cache
Expires: 0
X-Frame-Options: DENY
Content-Type: application/json;charset=UTF-8
Content-Length: 172
Date: Tue, 17 Nov 2026 02:58:23 GMT

{"status":401,"error":"Unauthorized","message":"未认证：请先调用 POST /api/login 获取 token，并通过 Authorization: Bearer <token> 访问","path":"/api/hello"}
```

### 7.2 登录获取 token

```text
PS> $login = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/login" -Method Post -ContentType 'application/json' -Body '{"username":"test","password":"123456"}'
PS> $login | ConvertTo-Json -Compress
{"token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0IiwiaWF0IjoxNzk0ODg0MzAzLCJleHAiOjE3OTQ4ODc5MDN9.5F7cnsdrqJtAkKupwUEUEhKtUXtQZPz4DoUj1JNtR1s","tokenType":"Bearer","expiresIn":3600,"username":"test"}
```

token 长度 145，结构为标准 JWT 三段式。

### 7.3 带 token 访问 `/api/hello`（预期 200，`Hello World`）

```text
$ curl.exe -s -i -H "Authorization: Bearer <TOKEN>" http://127.0.0.1:8080/api/hello
HTTP/1.1 200
Vary: Origin
Vary: Access-Control-Request-Method
Vary: Access-Control-Request-Headers
X-Content-Type-Options: nosniff
X-XSS-Protection: 0
Cache-Control: no-cache, no-store, max-age=0, must-revalidate
Pragma: no-cache
Expires: 0
X-Frame-Options: DENY
Content-Type: text/plain
Content-Length: 11
Date: Tue, 17 Nov 2026 02:58:23 GMT

Hello World
```

同样的调用用 `Invoke-RestMethod`：

```text
PS> $hello = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/hello" -Headers @{Authorization="Bearer $($login.token)"}
PS> $hello
Hello World
PS> $hello.GetType().Name
String
```

### 7.4 错误密码登录（预期 401）

```text
STATUS=401
BODY={"status":401,"error":"Unauthorized","message":"用户名或密码错误","path":"/api/login"}
```

### 7.5 无效 token（预期 401）

```text
GET /api/hello，Authorization: Bearer not-a-jwt
STATUS=401
BODY={"status":401,"error":"Unauthorized","message":"未认证：请先调用 POST /api/login 获取 token，并通过 Authorization: Bearer <token> 访问","path":"/api/hello"}
```

验证结束后已通过 `Stop-Process` 结束进程，8080 端口释放。

---

## 八、项目结构

```text
02-backend-springboot
├── pom.xml                      # parent: spring-boot-starter-parent 3.2.0
├── README.md
├── .gitignore                   # 忽略 target/、IDE 文件、日志等
├── docs
│   └── api.md                   # 更详细的接口文档
└── src
    ├── main
    │   ├── java/com/example/helloworld
    │   │   ├── HelloWorldApplication.java          # 启动类
    │   │   ├── config
    │   │   │   ├── SecurityConfig.java             # SecurityFilterChain：无状态、401 入口、放行 /api/login
    │   │   │   └── UserConfig.java                 # BCryptPasswordEncoder + 内存用户 test/123456
    │   │   ├── controller
    │   │   │   ├── AuthController.java             # POST /api/login
    │   │   │   └── HelloController.java            # GET /api/hello -> "Hello World"
    │   │   ├── dto
    │   │   │   ├── LoginRequest.java               # username/password + @NotBlank
    │   │   │   ├── LoginResponse.java              # token/tokenType/expiresIn/username
    │   │   │   └── ErrorResponse.java              # 统一错误体
    │   │   ├── exception
    │   │   │   └── GlobalExceptionHandler.java     # 认证失败 401、参数校验 400、JSON 解析 400
    │   │   ├── security
    │   │   │   ├── JwtTokenProvider.java           # HS256 签发/校验（JDK Mac，自实现）
    │   │   │   ├── JwtAuthenticationFilter.java    # 解析 Bearer token，写入 SecurityContext
    │   │   │   ├── RestAuthenticationEntryPoint.java # 未认证 -> 401 JSON（不 302）
    │   │   │   └── RestAccessDeniedHandler.java    # 无权限 -> 403 JSON（兜底）
    │   │   └── service
    │   │       └── AuthService.java                # 调用 AuthenticationManager 认证并签发 token
    │   └── resources
    │       └── application.yml                     # 端口、JWT secret、有效期
    └── test
        ├── java/com/example/helloworld/HelloWorldIntegrationTest.java
        └── resources/mockito-extensions/org.mockito.plugins.MockMaker
```

---

## 九、关键实现说明

### 9.1 为什么未认证是 401 而不是 302

Spring Security 默认在未配置 `formLogin` 时可能返回 403，配置了 `formLogin` 则会 302 到 `/login`。本工程：

1. `formLogin(...).disable()`、`httpBasic(...).disable()`；
2. 通过 `exceptionHandling().authenticationEntryPoint(RestAuthenticationEntryPoint)` 指定未认证处理器；
3. 该处理器直接 `response.setStatus(401)` 并写 JSON，不设置 `Location`。

测试用例 1 同时断言了 `status().isUnauthorized()` 与 `header().doesNotExist("Location")`。

### 9.2 认证链路

```text
POST /api/login
  -> AuthController
  -> AuthService
  -> AuthenticationManager (DaoAuthenticationProvider)
  -> UserDetailsService (InMemoryUserDetailsManager)
  -> BCryptPasswordEncoder.matches(raw, hash)
  -> 成功：JwtTokenProvider.createToken(username)
  -> 失败：AuthenticationException -> GlobalExceptionHandler -> 401

GET /api/hello
  -> JwtAuthenticationFilter（解析 Bearer token，验签 + 校验 exp）
  -> SecurityContextHolder 写入 Authentication
  -> AuthorizationFilter：anyRequest().authenticated() 通过
  -> HelloController 返回 text/plain "Hello World"
```

### 9.3 JWT 细节

- 算法：HS256，`signature = HMAC-SHA256(header.payload, secret)`；
- Base64 URL 编码、无 padding；
- 校验使用 `MessageDigest.isEqual` 做常量时间比较，降低时序攻击风险；
- 显式校验 `exp`，过期即视为无效；
- 任何格式错误、Base64 错误、JSON 错误、签名不匹配都返回 `Optional.empty()`，由过滤器保持匿名，最终统一 401，不会把异常抛给容器。

### 9.4 密码存储

`application.yml` 中没有任何明文密码用于运行时比较；`UserConfig` 启动时执行：

```java
passwordEncoder.encode(DEMO_RAW_PASSWORD)  // BCrypt，随机盐
```

放入 `InMemoryUserDetailsManager`。登录比对由 Spring Security 的 `DaoAuthenticationProvider` 完成。

---

## 十、开发环境备注（Windows / 受限沙箱）

实际开发中遇到并已解决的问题，供复现参考：

1. **PowerShell 5.1 的 401 处理**
   - 无 `-SkipHttpErrorCheck`，`Invoke-WebRequest` 遇 401 抛异常；
   - 从 `$_.Exception.Response` 读 body 可能为空；
   - 解决：查状态码用 `curl.exe -i`，或用 `System.Net.Http.HttpClient` 读取真实 body。

2. **PowerShell 参数被拆分**
   - `-Dmaven.repo.local='D:\...'` 会被拆坏，报 `No plugin found for prefix '.repo.local=D'`；
   - 解决：整个参数加单引号 `'-Dmaven.repo.local=D:\dsh-workplace\.m2'`。

3. **Mockito inline mock maker 无法 self-attach**
   - 报错：`Could not initialize inline Byte Buddy mock maker ... Could not self-attach to current VM using external process`；
   - 解决：`src/test/resources/mockito-extensions/org.mockito.plugins.MockMaker` 写入 `mock-maker-subclass`。

4. **依赖下载**
   - 本沙箱 PowerShell 的 HTTPS 不可用（schannel `SEC_E_NO_CREDENTIALS`），不能用它下载依赖；
   - Maven 使用 Java 自带 TLS，配合 `settings.xml` 的阿里云镜像 `https://maven.aliyun.com/repository/public`（`mirrorOf=*`）可正常拉取。

5. **端口就绪判断**
   - 应用启动期间用 HTTP 探测会因连接被拒/401 抛异常；
   - 解决：用 `System.Net.Sockets.TcpClient` 循环探测 8080 端口，连通后再发请求。

---

## 十一、已知限制

- 用户存储在内存中（单账号 `test/123456`），应用重启即重置；生产环境应改为数据库 + `UserDetailsService` 实现。
- JWT secret 写在 `application.yml` 中仅供演示，生产环境应通过环境变量或密钥管理服务注入，并定期轮换。
- 未实现 refresh token、登出黑名单、限流、审计日志等生产能力。
- 无数据库、无注册接口，符合笔试题“最小可运行示例”的定位。

---

## 十二、提交说明

本目录是多题目仓库 `interview-exam/` 的一个子目录，可直接作为独立项目使用（`.gitignore` 已排除 `target/`、IDE 文件与日志）。仓库根目录的 `README.md` 里有六道题的索引与逐题运行方式。
