# API 说明

Base URL：`http://127.0.0.1:8080`

## 1. 登录

- 方法：`POST`
- 路径：`/api/login`
- 认证：不需要
- Content-Type：`application/json`

请求体：

```json
{
  "username": "test",
  "password": "123456"
}
```

成功响应：`200 OK`

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9....",
  "tokenType": "Bearer",
  "expiresIn": 3600,
  "username": "test"
}
```

失败响应：`401 Unauthorized`

```json
{
  "status": 401,
  "error": "Unauthorized",
  "message": "用户名或密码错误",
  "path": "/api/login"
}
```

## 2. Hello World

- 方法：`GET`
- 路径：`/api/hello`
- 认证：需要，请求头 `Authorization: Bearer <token>`
- 成功响应：`200 OK`，`Content-Type: text/plain`，body 为 `Hello World`

未携带 token / token 无效 / token 过期：`401 Unauthorized`

```json
{
  "status": 401,
  "error": "Unauthorized",
  "message": "未认证：请先调用 POST /api/login 获取 token，并通过 Authorization: Bearer <token> 访问",
  "path": "/api/hello"
}
```

## 3. 错误码约定

| HTTP 状态码 | 场景 |
| --- | --- |
| 200 | 请求成功 |
| 400 | 请求体不是合法 JSON，或 username/password 为空 |
| 401 | 未认证、token 无效/过期、用户名或密码错误 |
| 403 | 已认证但权限不足（当前工程无此场景，属兜底） |
