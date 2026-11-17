package com.example.helloworld.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.provisioning.InMemoryUserDetailsManager;

/**
 * 用户与密码编码器配置。
 *
 * <p>演示工程使用内存用户；真实项目应改为数据库/JPA 实现
 * {@link UserDetailsService}。这里的关键点是：内存中保存的是
 * {@link BCryptPasswordEncoder} 生成的哈希，登录时由
 * {@code DaoAuthenticationProvider} 做 BCrypt 比对，
 * 绝不能用 {@code password.equals(...)} 做明文比较。</p>
 */
@Configuration
public class UserConfig {

    /** 演示账号的用户名，与 README、测试保持一致。 */
    public static final String DEMO_USERNAME = "test";

    /** 演示账号的初始明文密码，仅在启动时用于生成 BCrypt 哈希，不参与运行时比较。 */
    public static final String DEMO_RAW_PASSWORD = "123456";

    @Bean
    public PasswordEncoder passwordEncoder() {
        // strength = 10（默认），每次 encode 结果不同（随机盐），但 matches 可正确校验
        return new BCryptPasswordEncoder();
    }

    @Bean
    public UserDetailsService userDetailsService(PasswordEncoder passwordEncoder) {
        UserDetails testUser = User.withUsername(DEMO_USERNAME)
                .password(passwordEncoder.encode(DEMO_RAW_PASSWORD))
                .roles("USER")
                .build();
        return new InMemoryUserDetailsManager(testUser);
    }
}
