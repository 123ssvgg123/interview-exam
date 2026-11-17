package com.example.helloworld.dto;

/**
 * 统一错误响应体，便于前端/调用方稳定解析。
 *
 * @param status  HTTP 状态码
 * @param error   错误类型短语，如 Unauthorized
 * @param message 可读的错误说明
 * @param path    请求路径
 */
public record ErrorResponse(int status, String error, String message, String path) {
}
