package com.example.helloworld.config;

import com.example.helloworld.security.JwtAuthenticationFilter;
import com.example.helloworld.security.RestAccessDeniedHandler;
import com.example.helloworld.security.RestAuthenticationEntryPoint;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.config.annotation.authentication.configuration.AuthenticationConfiguration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * Spring Security 主配置。
 *
 * <p>设计目标：</p>
 * <ul>
 *   <li>无状态（STATELESS）：不用 session，完全依赖 Bearer token；</li>
 *   <li>关闭 formLogin / httpBasic：未认证时不能 302 跳登录页，而是返回 401 JSON；</li>
 *   <li>只有 {@code POST /api/login} 放行，其余接口必须认证。</li>
 * </ul>
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    /** 登录接口，唯一放行的公开端点。 */
    private static final String LOGIN_ENDPOINT = "/api/login";

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http,
                                                   JwtAuthenticationFilter jwtAuthenticationFilter,
                                                   RestAuthenticationEntryPoint authenticationEntryPoint,
                                                   RestAccessDeniedHandler accessDeniedHandler) throws Exception {
        http
                // 纯 token 认证，不存在 Cookie/CSRF 场景
                .csrf(csrf -> csrf.disable())
                // 不创建 HttpSession
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                // 关闭默认的登录页跳转/表单登录/HTTP Basic
                .formLogin(form -> form.disable())
                .httpBasic(basic -> basic.disable())
                .logout(logout -> logout.disable())
                .requestCache(cache -> cache.disable())
                // 未认证 / 无权限时统一返回 JSON，而不是 302
                .exceptionHandling(handling -> handling
                        .authenticationEntryPoint(authenticationEntryPoint)
                        .accessDeniedHandler(accessDeniedHandler))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(LOGIN_ENDPOINT).permitAll()
                        .anyRequest().authenticated())
                // JWT 过滤器放在用户名密码过滤器之前
                .addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    /**
     * 暴露 AuthenticationManager，供 AuthService 主动发起用户名密码认证。
     * 它由 Spring Security 自动装配，内部使用 UserDetailsService + PasswordEncoder。
     */
    @Bean
    public AuthenticationManager authenticationManager(AuthenticationConfiguration configuration) throws Exception {
        return configuration.getAuthenticationManager();
    }
}
