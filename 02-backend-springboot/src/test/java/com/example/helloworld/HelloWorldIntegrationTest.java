package com.example.helloworld;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 端到端集成测试：真实启动 Spring 容器，用 MockMvc 走完整的 Security 过滤器链。
 *
 * <p>覆盖题目要求的四个关键场景，并额外覆盖未知用户、被篡改 token、参数校验。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
class HelloWorldIntegrationTest {

    private static final String USERNAME = "test";
    private static final String PASSWORD = "123456";
    private static final MediaType JSON = MediaType.APPLICATION_JSON;

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    @DisplayName("未携带 token 访问 /api/hello -> 401（不能 302 跳登录页）")
    void helloWithoutTokenReturns401() throws Exception {
        mockMvc.perform(get("/api/hello"))
                .andExpect(status().isUnauthorized())
                .andExpect(header().doesNotExist(HttpHeaders.LOCATION))
                .andExpect(jsonPath("$.status").value(401))
                .andExpect(jsonPath("$.path").value("/api/hello"));
    }

    @Test
    @DisplayName("正确用户名密码登录 -> 200 且返回 token")
    void loginWithValidCredentialsReturnsToken() throws Exception {
        MvcResult result = mockMvc.perform(post("/api/login")
                        .contentType(JSON)
                        .content(loginBody(USERNAME, PASSWORD)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.tokenType").value("Bearer"))
                .andExpect(jsonPath("$.username").value(USERNAME))
                .andExpect(jsonPath("$.expiresIn").isNumber())
                .andReturn();

        JsonNode json = objectMapper.readTree(result.getResponse().getContentAsString());
        assertThat(json.path("token").asText()).isNotBlank();
        // JWT 固定三段：header.payload.signature
        assertThat(json.path("token").asText().split("\\.")).hasSize(3);
    }

    @Test
    @DisplayName("携带有效 token 访问 /api/hello -> 200 且 body 恰好为 Hello World")
    void helloWithValidTokenReturnsHelloWorld() throws Exception {
        String token = loginAndGetToken();

        mockMvc.perform(get("/api/hello")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_PLAIN))
                .andExpect(content().string("Hello World"));
    }

    @Test
    @DisplayName("错误密码登录 -> 401")
    void loginWithWrongPasswordReturns401() throws Exception {
        mockMvc.perform(post("/api/login")
                        .contentType(JSON)
                        .content(loginBody(USERNAME, "wrong-password")))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.status").value(401));
    }

    @Test
    @DisplayName("不存在的用户登录 -> 401（不泄露用户是否存在）")
    void loginWithUnknownUserReturns401() throws Exception {
        mockMvc.perform(post("/api/login")
                        .contentType(JSON)
                        .content(loginBody("nobody", PASSWORD)))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("被篡改的 token -> 401")
    void helloWithTamperedTokenReturns401() throws Exception {
        String token = loginAndGetToken();

        mockMvc.perform(get("/api/hello")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + token + "tampered"))
                .andExpect(status().isUnauthorized());

        mockMvc.perform(get("/api/hello")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer not-a-jwt"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("缺少密码字段 -> 400")
    void loginWithMissingPasswordReturns400() throws Exception {
        mockMvc.perform(post("/api/login")
                        .contentType(JSON)
                        .content("{\"username\":\"test\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status").value(400));
    }

    /** 登录并返回 token，供需要认证的用例复用。 */
    private String loginAndGetToken() throws Exception {
        MvcResult result = mockMvc.perform(post("/api/login")
                        .contentType(JSON)
                        .content(loginBody(USERNAME, PASSWORD)))
                .andExpect(status().isOk())
                .andReturn();
        return objectMapper.readTree(result.getResponse().getContentAsString())
                .path("token").asText();
    }

    private String loginBody(String username, String password) throws Exception {
        return objectMapper.writeValueAsString(Map.of("username", username, "password", password));
    }
}
