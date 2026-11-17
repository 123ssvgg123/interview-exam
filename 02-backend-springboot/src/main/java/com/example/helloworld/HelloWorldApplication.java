package com.example.helloworld;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 应用入口。
 *
 * <p>演示 Spring Boot 3.2.0 + Spring Security + 自实现 HS256 JWT 的最小工程：
 * 登录换取 token，再凭 token 访问受保护的 Hello World 接口。</p>
 */
@SpringBootApplication
public class HelloWorldApplication {

    public static void main(String[] args) {
        SpringApplication.run(HelloWorldApplication.class, args);
    }
}
