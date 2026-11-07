/* Modified 2026-10-12: transport failure is not authentication evidence. */
#include "clients/net/NetClient.h"
#include "states/States.h"
#include "utils/Logger.h"
#include "utils/UrlParse.h"
#include "utils/PlatformUtils.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const prog_status_t* probe_account(void)
{
    if (!g_prog_status || g_prog_cnt <= 0) return NULL;
    const int idx = tl_thread_idx >= 0 && tl_thread_idx < g_prog_cnt ? tl_thread_idx : 0;
    return &g_prog_status[idx];
}

static bool has_value(const char* url, const char* key)
{
    const char* value;
    size_t length;
    return url_find_query_value(url, key, &value, &length) && length > 0;
}

static bool is_portal(const char* location)
{
    char host[128];
    uint16_t port;
    if (!url_split_host_port(location, host, sizeof(host), &port)) return false;
    const prog_status_t* ps = probe_account();
    /* BAS may supply a new host. Require protocol identity fields to learn it. */
    if (has_value(location, "wlanuserip") &&
        (has_value(location, "mscgip") || has_value(location, "wlanacip"))) return true;
    if (!ps) return false;
    if (ps->runtime_portal[0] && strcmp(host, ps->runtime_portal) == 0 &&
        port == ps->runtime_portal_port) return true;
    return ps->login_cfg.portal[0] && strcmp(host, ps->login_cfg.portal) == 0 &&
        port == ps->login_cfg.portal_port;
}

static void remember_portal(const char* location)
{
    if (!g_prog_status || tl_thread_idx < 0 || tl_thread_idx >= g_prog_cnt) return;
    prog_status_t* ps = &g_prog_status[tl_thread_idx];
    if (strcmp(ps->portal_hint, location) != 0)
        LOG_INFO("已确认校园门户重定向（不记录查询参数）");
    snprintf(ps->portal_hint, sizeof(ps->portal_hint), "%s", location);
    /* Fresh response, even if the previous session locked last_location. */
    snprintf(ps->last_location, sizeof(ps->last_location), "%s", location);
}

typedef struct {
    bool attempted, portal;
    CURLcode code;
    long http;
    double seconds;
} probe_sample_t;

static network_status_t record_probes(network_status_t result, const probe_sample_t samples[3])
{
    static _Thread_local bool seen = false;
    static _Thread_local uint64_t last_time = 0, last_pattern = 0;
    uint64_t pattern = (uint64_t)result;
    for (int i = 0; i < 3; i++)
    {
        pattern = pattern * 131 + samples[i].attempted;
        pattern = pattern * 131 + samples[i].portal;
        pattern = pattern * 131 + samples[i].code;
        pattern = pattern * 131 + samples[i].http;
    }
    uint64_t now = get_cur_tm_ms();
    if (!seen || pattern != last_pattern || now - last_time >= 60000)
    {
        const char* names[] = {"MIUI", "Microsoft", "Cloudflare"};
        LOG_INFO("网络探测汇总: %s", result == STATUS_OK ? "在线证据" :
                 result == STATUS_NEED_AUTH ? "校园门户证据" : "未知（未获得明确在线或门户证据）");
        for (int i = 0; i < 3; i++)
        {
            if (samples[i].attempted)
                LOG_INFO("探测 %s: curl=%d HTTP=%ld 门户=%d 耗时=%.0f 毫秒",
                         names[i], samples[i].code, samples[i].http,
                         samples[i].portal, samples[i].seconds * 1000);
        }
        seen = true; last_time = now; last_pattern = pattern;
    }
    return result;
}

network_status_t check_network_status(const bool connect_only)
{
    (void)connect_only;
    const char* urls[] = {"http://connect.rom.miui.com/generate_204",
                          "http://www.msftconnecttest.com/connecttest.txt",
                          "http://1.1.1.1"};
    char portal[2048] = {0};
    probe_sample_t samples[3] = {0};
    for (size_t i = 0; i < sizeof(urls) / sizeof(urls[0]); i++)
    {
        curl_resp_t resp = get(urls[i], false);
        samples[i].attempted = true;
        samples[i].code = resp.curl_code;
        samples[i].http = resp.http_code;
        samples[i].seconds = resp.elapsed_seconds;
        bool online = false;
        if (resp.curl_code == CURLE_OK)
        {
            if (i == 0 && resp.http_code == HTTP_NO_CONTENT) online = true;
            if (i == 1 && resp.http_code == HTTP_OK && resp.body_data &&
                resp.body_size == strlen("Microsoft Connect Test") &&
                memcmp(resp.body_data, "Microsoft Connect Test", resp.body_size) == 0) online = true;
            if (i == 2 && (resp.http_code == 301 || resp.http_code == 302 ||
                           resp.http_code == 307 || resp.http_code == 308))
            {
                char host[128];
                uint16_t port;
                online = strncmp(resp.location, "https://", 8) == 0 &&
                    url_split_host_port(resp.location, host, sizeof(host), &port) &&
                    port == 443 && (strcmp(host, "1.1.1.1") == 0 ||
                                    strcmp(host, "one.one.one.one") == 0);
            }
            if ((resp.http_code == 301 || resp.http_code == 302 ||
                 resp.http_code == 303 || resp.http_code == 307 || resp.http_code == 308) &&
                is_portal(resp.location))
            {
                online = false;
                samples[i].portal = true;
                snprintf(portal, sizeof(portal), "%s", resp.location);
            }
        }
        free(resp.body_data);
        /* Fallback on unexpected HTTP codes too. One successful independent
         * internet response overrides a single site's captive redirect. */
        if (online) return record_probes(STATUS_OK, samples);
    }
    if (portal[0])
    {
        remember_portal(portal);
        return record_probes(STATUS_NEED_AUTH, samples);
    }
    return record_probes(STATUS_ERROR, samples);
}
