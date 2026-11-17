package com.example.helloworld.controller;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Hello World 接口。
 *
 * <p>该路径不在 SecurityConfig 的放行名单中，因此必须携带合法 Bearer token。
 * 未认证请求在进入本类之前就会被 Security 过滤器链拦截并返回 401。</p>
 */
@RestController
@RequestMapping("/api")
public class HelloController {

    @GetMapping(value = "/hello", produces = MediaType.TEXT_PLAIN_VALUE)
    public ResponseEntity<String> hello() {
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_PLAIN)
                .body("Hello World");
    }
}
