/* Modified 2026-10-12: stable network detection and recovery; see NOTICE. */
/* Modified 2026-10-10: avoid credential-bearing raw header/URL/error output. */
#include "clients/net/NetClientInternal.h"

#include "states/States.h"

#include "utils/sim/SimEvp.h"

#include "utils/Logger.h"
#include <errno.h>

#ifdef _WIN32
#else
#include <string.h>
#include <stdlib.h>
#endif

#ifdef __OPENWRT__
#include <errno.h>

#ifndef SOL_SOCKET
#define SOL_SOCKET 1
#endif

#ifndef SO_MARK
#define SO_MARK 36
#endif
#endif

char s_school_id[SCHOOL_ID_LENGTH] = {0};
char s_domain[DOMAIN_LENGTH] = {0};
char s_area[AREA_LENGTH] = {0};

/* Resolve relative redirects with libcurl's URL parser and reject truncation. */
static void resolve_url(char* out, size_t out_len, const char* base, const char* ref)
{
    if (!out || !out_len) return;
    out[0] = '\0';
    if (!ref || !ref[0]) return;
    CURLU* parsed = curl_url();
    if (!parsed) return;
    if (base && base[0]) curl_url_set(parsed, CURLUPART_URL, base, 0);
    if (curl_url_set(parsed, CURLUPART_URL, ref, 0) == CURLUE_OK)
    {
        char* resolved = NULL;
        if (curl_url_get(parsed, CURLUPART_URL, &resolved, 0) == CURLUE_OK)
        {
            size_t len = strlen(resolved);
            if (len < out_len) memcpy(out, resolved, len + 1);
            curl_free(resolved);
        }
    }
    curl_url_cleanup(parsed);
}

#ifdef __OPENWRT__
curl_socket_t open_socket_callback(void* client_p, curlsocktype purpose, struct curl_sockaddr* addr)
{
    (void)client_p;
    (void)purpose;
    curl_socket_t sock_fd = socket(addr->family, addr->socktype, addr->protocol);
    if (sock_fd == CURL_SOCKET_BAD)
    {
        LOG_ERROR("创建 socket 失败: %s", strerror(errno));
        return CURL_SOCKET_BAD;
    }

    if (g_prog_status[tl_thread_idx].login_cfg.mark != 0)
    {
        if (setsockopt(sock_fd, SOL_SOCKET, SO_MARK, &g_prog_status[tl_thread_idx].login_cfg.mark, sizeof(g_prog_status[tl_thread_idx].login_cfg.mark)) == -1)
        {
            LOG_ERROR("设置 SO_MARK 失败 (mark = %" PRIu32 " (0x%x)): %s", g_prog_status[tl_thread_idx].login_cfg.mark, g_prog_status[tl_thread_idx].login_cfg.mark, strerror(errno));
        }
        else
        {
            LOG_VERBOSE("设置 SO_MARK = %" PRIu32 " (0x%x)", g_prog_status[tl_thread_idx].login_cfg.mark, g_prog_status[tl_thread_idx].login_cfg.mark);
        }
    }

    return sock_fd;
}
#endif

/* POSTs collect only a numeric business result, not Location/session headers. */
size_t service_header_cb(const void* contents, const size_t size, const size_t nmemb, void* userdata)
{
    const size_t length = size * nmemb;
    curl_resp_t* resp = userdata;
    const char* header = contents;
    if (resp && length >= 11 && strncasecmp(header, "error-code:", 11) == 0)
    {
        const char* start = header + 11;
        const char* end = header + length;
        while (start < end && (*start == ' ' || *start == '\t')) start++;
        while (end > start && (end[-1] == '\r' || end[-1] == '\n' || end[-1] == ' ' || end[-1] == '\t')) end--;
        resp->service_code_present = false;
        size_t count = (size_t)(end - start);
        if (count && count < 32)
        {
            char number[32];
            memcpy(number, start, count); number[count] = '\0';
            char* stop;
            errno = 0;
            long code = strtol(number, &stop, 10);
            if (!errno && stop != number && *stop == '\0')
            {
                resp->service_code = code;
                resp->service_code_present = true;
            }
        }
    }
    return length;
}

size_t header_cb(const void* contents, const size_t size, const size_t nmemb, void* userdata)
{
    service_header_cb(contents, size, nmemb, userdata);
    const size_t real_size = size * nmemb;
    const char* header = contents;

    if (real_size >= 9 && strncmp(header, "schoolid:", 9) == 0 && !s_school_id[0])
    {
        if (s_school_id[0] == '\0')
        {
            LOG_VERBOSE("收到 School-ID 响应头");

            const char* value = header + 9;
            while (*value == ' ') value++;
            const size_t valid_len = strcspn(value, "\r\n");

            size_t copy_len = valid_len;
            if (copy_len >= SCHOOL_ID_LENGTH)
            {
                copy_len = SCHOOL_ID_LENGTH - 1;
                LOG_WARN("School Id 被截断, 原长度: %zu, 缓冲区大小: %d", valid_len, SCHOOL_ID_LENGTH);
            }

            memcpy(s_school_id, value, copy_len);
            s_school_id[copy_len] = '\0';

            LOG_INFO("School Id: %s", s_school_id);
        }
    }

    if (real_size >= 7 && strncmp(header, "domain:", 7) == 0 && !s_domain[0])
    {
        if (s_domain[0] == '\0')
        {
            LOG_VERBOSE("收到 Domain 响应头");

            const char* value = header + 7;
            while (*value == ' ') value++;
            const size_t valid_len = strcspn(value, "\r\n");

            size_t copy_len = valid_len;
            if (copy_len >= DOMAIN_LENGTH)
            {
                copy_len = DOMAIN_LENGTH - 1;
                LOG_WARN("Domain 被截断, 原长度: %zu, 缓冲区大小: %d", valid_len, DOMAIN_LENGTH);
            }

            memcpy(s_domain, value, copy_len);
            s_domain[copy_len] = '\0';

            LOG_INFO("Domain: %s", s_domain);
        }
    }

    if (real_size >= 5 && strncmp(header, "area:", 5) == 0 && !s_area[0])
    {
        if (s_area[0] == '\0')
        {
            LOG_VERBOSE("收到 Area 响应头");

            const char* value = header + 5;
            while (*value == ' ') value++;
            const size_t valid_len = strcspn(value, "\r\n");

            size_t copy_len = valid_len;
            if (copy_len >= AREA_LENGTH)
            {
                copy_len = AREA_LENGTH - 1;
                LOG_WARN("Area 被截断, 原长度: %zu, 缓冲区大小: %d", valid_len, AREA_LENGTH);
            }

            memcpy(s_area, value, copy_len);
            s_area[copy_len] = '\0';

            LOG_INFO("Area: %s", s_area);
        }
    }

    if (real_size >= 9 && strncasecmp(header, "Location:", 9) == 0)
    {
        curl_resp_t* resp = userdata;
        const char* start = header + 9;
        const char* end = header + real_size;
        while (start < end && (*start == ' ' || *start == '\t')) start++;
        while (end > start && (end[-1] == '\r' || end[-1] == '\n' || end[-1] == ' ')) end--;
        size_t len = (size_t)(end - start);
        if (resp) resp->location[0] = '\0';
        if (resp && len > 0 && len < sizeof(resp->location))
        {
            char ref[2048];
            memcpy(ref, start, len);
            ref[len] = '\0';
            resolve_url(resp->location, sizeof(resp->location), s_request_url, ref);
        }
        if (resp && resp->location[0] && g_prog_status &&
            tl_thread_idx >= 0 && tl_thread_idx < g_prog_cnt)
        {
            if (!g_prog_status[tl_thread_idx].last_location_lock)
            {
                LOG_VERBOSE("收到 Location 响应头（不记录原始头）");

                snprintf(g_prog_status[tl_thread_idx].last_location, sizeof(g_prog_status[tl_thread_idx].last_location),
                         "%s", resp->location);

                LOG_VERBOSE("已更新重定向地址（不记录查询参数）");
            }
        }
    }

    return real_size;
}

size_t write_cb(const void* contents, const size_t size, const size_t nmemb, void* userdata)
{
    curl_resp_t* resp = userdata;
    const size_t real_size = size * nmemb;
    char* ptr = realloc(resp->body_data, resp->body_size + real_size + 1);

    if (!ptr) return 0;

    resp->body_data = ptr;
    memcpy(&resp->body_data[resp->body_size], contents, real_size);
    resp->body_size += real_size;
    resp->body_data[resp->body_size] = 0;

    return real_size;
}

char* calc_md5(const char* data)
{
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_len;
    char* md5_str = malloc(33);

    if (!md5_str)
    {
        LOG_ERROR("分配内存失败");
        return NULL;
    }

    EVP_MD_CTX* mdctx = EVP_MD_CTX_new();
    if (!mdctx)
    {
        free(md5_str);
        return NULL;
    }

    const EVP_MD* md = EVP_md5();
    if (EVP_DigestInit_ex(mdctx, md, NULL) != 1)
    {
        EVP_MD_CTX_free(mdctx);
        free(md5_str);
        return NULL;
    }

    if (EVP_DigestUpdate(mdctx, data, strlen(data)) != 1)
    {
        EVP_MD_CTX_free(mdctx);
        free(md5_str);
        return NULL;
    }

    if (EVP_DigestFinal_ex(mdctx, digest, &digest_len) != 1)
    {
        EVP_MD_CTX_free(mdctx);
        free(md5_str);
        return NULL;
    }
    EVP_MD_CTX_free(mdctx);

    for (unsigned int i = 0; i < digest_len; i++) sprintf(&md5_str[i*2], "%02x", (unsigned int)digest[i]);

    return md5_str;
}

network_status_t curl_err_msg_out(const CURLcode curl_code)
{
    switch (curl_code)
    {
    case CURLE_URL_MALFORMAT:
        LOG_ERROR("curl 错误码: 3, 错误信息: URL 格式错误");
        break;
    case CURLE_COULDNT_RESOLVE_HOST:
        LOG_ERROR("curl 错误码: 6, 错误信息: DNS 解析错误");
        break;
    case CURLE_COULDNT_CONNECT:
        LOG_ERROR("curl 错误码: 7, 错误信息: 连接服务器失败");
        break;
    case CURLE_HTTP_RETURNED_ERROR:
        LOG_ERROR("curl 错误码: 22, 错误信息: HTTP 状态码 ≥ 400");
        break;
    case CURLE_WRITE_ERROR:
        LOG_ERROR("curl 错误码: 23, 错误信息: 写入数据失败");
        break;
    case CURLE_OPERATION_TIMEDOUT:
        LOG_ERROR("curl 错误码: 28, 错误信息: 操作超时");
        break;
    case CURLE_ABORTED_BY_CALLBACK:
        LOG_ERROR("curl 错误码: 42, 错误信息: 回调函数中止");
        break;
    case CURLE_GOT_NOTHING:
        LOG_ERROR("curl 错误码: 52, 错误信息: 服务器返回空数据");
        break;
    case CURLE_RECV_ERROR:
        LOG_ERROR("curl 错误码: 56, 错误信息: 接收数据时失败");
        break;
    default:
        LOG_ERROR("未知错误");
    }
    return STATUS_ERROR;
}

void log_curl_error(CURL* curl, const CURLcode code, const char *errbuf, const char *url,
                    const char *func_name, const long connect_timeout, const long operation_timeout)
{
    if (tl_thread_idx == -2 && strcmp(func_name, "get") == 0)
    {
        LOG_WARN("网页状态探测未完成: curl=%d，实际限时=%ld 秒；此结果不触发登出或重新认证",
                 code, operation_timeout);
        return;
    }
    LOG_ERROR("[%s] curl 请求失败: %s", func_name, curl_easy_strerror(code));
    (void)url;
    LOG_INFO("[%s] CURLcode: %d", func_name, code);

    if (errbuf && errbuf[0] != '\0')
    {
        LOG_DEBUG("[%s] libcurl 已提供错误详情（可能含地址参数，已省略）", func_name);
    }

    if (curl)
    {
        double connect_time = 0.0;
        double total_time = 0.0;
        // 获取连接阶段实际耗时 (秒, double 类型)
        curl_easy_getinfo(curl, CURLINFO_CONNECT_TIME, &connect_time);
        // 获取整个请求实际总耗时 (秒, double 类型)
        curl_easy_getinfo(curl, CURLINFO_TOTAL_TIME, &total_time);

        LOG_INFO("[%s] 实际连接耗时: %.3f 秒", func_name, connect_time);
        LOG_INFO("[%s] 实际总耗时:   %.3f 秒", func_name, total_time);
        LOG_INFO("[%s] 连接超时时长: %ld 秒", func_name, connect_timeout);
        LOG_INFO("[%s] 总超时时长:   %ld 秒", func_name, operation_timeout);

        // 特别针对超时错误进行原因分析
        if (code == CURLE_OPERATION_TIMEDOUT)
        {
            // 判断实际连接耗时是否已接近或超过设置的连接超时
            if (connect_timeout > 0 && connect_time >= (double)connect_timeout * 0.9)
            {
                LOG_INFO("[%s] 结论: 连接时间超时 (CURLOPT_CONNECTTIMEOUT = %ld 秒)", func_name, connect_timeout);
            }
            // 否则, 判断总耗时是否已接近或超过设置的总超时
            else if (operation_timeout > 0 && total_time >= (double)operation_timeout * 0.9)
            {
                LOG_INFO("[%s] 结论: 总操作时间超时 (CURLOPT_TIMEOUT = %ld 秒)", func_name, operation_timeout);
            }
            else
            {
                LOG_INFO("[%s] 结论: 超时原因不明确, 实际耗时未明显逼近设定阈值, 请检查网络稳定性或服务器响应", func_name);
            }
        }
    }
}
