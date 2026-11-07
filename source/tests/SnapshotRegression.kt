package org.esurfing.hunan

fun main() {
    val now = 2_000_000L
    val online = SessionSnapshot(phase = Phase.AUTHENTICATED, internetAt = now, internetResult = CheckResult.PASS)
    check(online.display(now).contains("最近外网检测通过"))
    check(online.display(now + 600_001).contains("外网待复核"))
    check(online.display(now - 1).contains("外网待复核"))
    check(online.copy(internetResult = CheckResult.FAIL).display(now).contains("外网异常"))
    val secret = "SENTINEL_password_ticket_url"
    val event = online.copy(status = secret, details = secret, network = secret, protocolCode = secret).event(now)
    check(!event.contains(secret))
    check(!event.contains("password") && !event.contains("ticket") && !event.contains("url"))
    check(online.copy(protocolCode = "-123").event(now).split('\t')[15] == "-123")
    check(online.copy(internetResult = CheckResult.FAIL, internetEvidence = InternetEvidence.PORTAL_REQUIRED).display(now).contains("外网未放行"))
    check(online.copy(internetResult = CheckResult.FAIL, internetEvidence = InternetEvidence.PORTAL_REQUIRED).display(now+600001).contains("待复核"))
    check(RetryPolicy.delaySeconds(1) == 15L && RetryPolicy.delaySeconds(2) == 30L)
    check((3..100).all { RetryPolicy.delaySeconds(it) == null })
    check(DiscoveryRetryPolicy.delaySeconds(1) == 10L && DiscoveryRetryPolicy.delaySeconds(2) == 30L)
    check((3..100).all { DiscoveryRetryPolicy.delaySeconds(it) == null })
    check(DiscoveryRetryPolicy.delaySeconds(0) == null)
    check(IntervalPolicy.select("300") == IntervalDecision(250, 300, IntervalSource.SERVER))
    check(IntervalPolicy.select(null) == IntervalDecision(250, null, IntervalSource.MISSING))
    check(IntervalPolicy.select("oops").source == IntervalSource.INVALID_NUMBER)
    check(IntervalPolicy.select("29").source == IntervalSource.OUT_OF_RANGE)
    check(IntervalPolicy.select("3600").seconds == 3000L)
    check(online.copy(heartbeatAt = now, heartbeatResult = CheckResult.PASS).display(now).contains("PASS（最近结果）"))
    check(online.copy(heartbeatAt = now, heartbeatResult = CheckResult.PASS).display(now+310001).contains("PASS（已过期或未确认）"))
    println("PASS: snapshot freshness, typed export, bounded retries, interval source/boundaries and heartbeat freshness")
}
