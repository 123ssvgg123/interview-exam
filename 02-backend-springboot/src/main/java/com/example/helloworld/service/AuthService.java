package com.example.helloworld.service;

import com.example.helloworld.dto.LoginRequest;
import com.example.helloworld.dto.LoginResponse;
import com.example.helloworld.security.JwtTokenProvider;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Service;

/**
 * 认证业务层：负责“校验用户名密码 + 签发 token”。
 *
 * <p>密码校验完全交给 {@link AuthenticationManager}（内部为 DaoAuthenticationProvider +
 * BCryptPasswordEncoder），本类不接触明文密码比较。</p>
 */
@Service
public class AuthService {

    private final AuthenticationManager authenticationManager;
    private final JwtTokenProvider jwtTokenProvider;

    public AuthService(AuthenticationManager authenticationManager, JwtTokenProvider jwtTokenProvider) {
        this.authenticationManager = authenticationManager;
        this.jwtTokenProvider = jwtTokenProvider;
    }

    /**
     * 登录。凭证错误时 {@link org.springframework.security.core.AuthenticationException}
     * 会向上抛出，由 GlobalExceptionHandler 统一转换为 401。
     */
    public LoginResponse login(LoginRequest request) {
        Authentication authentication = authenticationManager.authenticate(
                new UsernamePasswordAuthenticationToken(request.username(), request.password()));

        String username = authentication.getName();
        String token = jwtTokenProvider.createToken(username);
        return new LoginResponse(token, "Bearer", jwtTokenProvider.getExpirationSeconds(), username);
    }
}
