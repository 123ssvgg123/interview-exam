package com.example.helloworld.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * 轻量 JWT（HS256）签发与校验工具，只依赖 JDK 自带的 {@link javax.crypto.Mac}，
 * 不引入额外三方 JWT 库，避免依赖下载问题。
 *
 * <p>Token 结构为标准 JWT：{@code base64url(header).base64url(payload).base64url(signature)}，
 * 其中 signature = HMAC-SHA256(header.payload, secret)。</p>
 */
@Component
public class JwtTokenProvider {

    private static final String HMAC_ALGORITHM = "HmacSHA256";
    private static final String HEADER_JSON = "{\"alg\":\"HS256\",\"typ\":\"JWT\"}";
    private static final int MIN_SECRET_BYTES = 32; // HS256 建议 256 bit 以上

    private static final Base64.Encoder BASE64_URL_ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder BASE64_URL_DECODER = Base64.getUrlDecoder();

    private final ObjectMapper objectMapper;
    private final byte[] secret;
    private final long expirationSeconds;

    public JwtTokenProvider(ObjectMapper objectMapper,
                            @Value("${app.jwt.secret}") String secret,
                            @Value("${app.jwt.expiration-seconds:3600}") long expirationSeconds) {
        byte[] secretBytes = secret == null ? new byte[0] : secret.getBytes(StandardCharsets.UTF_8);
        if (secretBytes.length < MIN_SECRET_BYTES) {
            throw new IllegalArgumentException(
                    "app.jwt.secret 至少需要 " + MIN_SECRET_BYTES + " 字节（256 bit），当前为 " + secretBytes.length);
        }
        this.objectMapper = objectMapper;
        this.secret = secretBytes;
        this.expirationSeconds = expirationSeconds;
    }

    public long getExpirationSeconds() {
        return expirationSeconds;
    }

    /**
     * 为指定用户签发 token。
     */
    public String createToken(String username) {
        long nowSeconds = System.currentTimeMillis() / 1000L;

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("sub", username);
        payload.put("iat", nowSeconds);
        payload.put("exp", nowSeconds + expirationSeconds);

        try {
            String headerPart = BASE64_URL_ENCODER.encodeToString(HEADER_JSON.getBytes(StandardCharsets.UTF_8));
            String payloadPart = BASE64_URL_ENCODER.encodeToString(objectMapper.writeValueAsBytes(payload));
            String signingInput = headerPart + "." + payloadPart;
            String signaturePart = BASE64_URL_ENCODER.encodeToString(sign(signingInput));
            return signingInput + "." + signaturePart;
        } catch (Exception ex) {
            throw new IllegalStateException("生成 JWT 失败", ex);
        }
    }

    /**
     * 校验签名与过期时间，成功时返回用户名。
     *
     * <p>任何异常（格式错误、签名不匹配、已过期、payload 缺少字段）都返回
     * {@link Optional#empty()}，由调用方决定返回 401，绝不抛出给容器。</p>
     */
    public Optional<String> parseUsername(String token) {
        if (token == null || token.isBlank()) {
            return Optional.empty();
        }
        String[] parts = token.split("\\.", -1);
        if (parts.length != 3) {
            return Optional.empty();
        }
        try {
            String signingInput = parts[0] + "." + parts[1];
            byte[] expectedSignature = sign(signingInput);
            byte[] actualSignature = BASE64_URL_DECODER.decode(parts[2]);
            // 常量时间比较，避免时序攻击
            if (!MessageDigest.isEqual(expectedSignature, actualSignature)) {
                return Optional.empty();
            }

            Map<?, ?> claims = objectMapper.readValue(BASE64_URL_DECODER.decode(parts[1]), Map.class);
            Object subject = claims.get("sub");
            Object expiration = claims.get("exp");
            if (!(subject instanceof String username) || username.isBlank() || !(expiration instanceof Number exp)) {
                return Optional.empty();
            }
            if (exp.longValue() <= System.currentTimeMillis() / 1000L) {
                return Optional.empty();
            }
            return Optional.of(username);
        } catch (Exception ex) {
            // 非法 Base64 / 非法 JSON / 算法异常等一律视为无效 token
            return Optional.empty();
        }
    }

    private byte[] sign(String data) throws Exception {
        Mac mac = Mac.getInstance(HMAC_ALGORITHM);
        mac.init(new SecretKeySpec(secret, HMAC_ALGORITHM));
        return mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
    }
}
