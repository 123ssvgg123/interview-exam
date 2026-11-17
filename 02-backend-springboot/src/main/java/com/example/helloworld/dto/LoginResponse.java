package com.example.helloworld.dto;

/**
 * 登录成功响应。
 *
 * @param token      JWT 字符串
 * @param tokenType  固定为 "Bearer"
 * @param expiresIn  token 有效期（秒）
 * @param username   认证通过的用户名
 */
public record LoginResponse(String token, String tokenType, long expiresIn, String username) {
}
