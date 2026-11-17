package com.example.helloworld.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * 登录请求体。
 *
 * <p>示例：{@code {"username":"test","password":"123456"}}</p>
 */
public record LoginRequest(
        @NotBlank(message = "username 不能为空") String username,
        @NotBlank(message = "password 不能为空") String password) {
}
