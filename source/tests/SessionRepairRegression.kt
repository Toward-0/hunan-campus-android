package org.esurfing.hunan

private fun eligible(): SessionRepairGate = SessionRepairGate().apply {
    observe(InternetEvidence.PORTAL_REQUIRED, 1_000)
    observe(InternetEvidence.PORTAL_REQUIRED, 11_000)
    observe(InternetEvidence.PORTAL_REQUIRED, 41_000)
}
fun main() {
    val good = eligible()
    check(good.available(41_000) && good.begin(41_000))
    check(!good.begin(41_001) && !good.takeLogin(Long.MAX_VALUE))
    check(good.logoutConfirmed(42_000))
    check(!good.takeLogin(141_999) && good.takeLogin(142_000))
    check(!good.takeLogin(142_001))
    good.complete(); check(!good.available(143_000) && !good.begin(143_000))

    for (evidence in listOf(InternetEvidence.HTTPS_VERIFIED, InternetEvidence.HTTPS_UNREACHABLE, InternetEvidence.NOT_CHECKED)) {
        val interrupted = eligible(); interrupted.observe(evidence, 42_000)
        check(!interrupted.available(42_000) && !interrupted.begin(42_000))
        interrupted.observe(InternetEvidence.PORTAL_REQUIRED, 45_000)
        check(!interrupted.available(90_000))
    }
    check(!eligible().available(641_001))
    check(!eligible().available(40_000))
    val quick = SessionRepairGate()
    repeat(10) { quick.observe(InternetEvidence.PORTAL_REQUIRED, 1_000L + it) }
    check(!quick.begin(1_010))

    val unconfirmed = eligible(); check(unconfirmed.begin(41_000)); unconfirmed.fail()
    check(!unconfirmed.logoutConfirmed(42_000) && !unconfirmed.takeLogin(Long.MAX_VALUE))
    for (afterLogout in listOf(false, true)) {
        val cancelled = eligible(); check(cancelled.begin(41_000))
        if(afterLogout) check(cancelled.logoutConfirmed(42_000))
        cancelled.cancel()
        check(!cancelled.logoutConfirmed(43_000) && !cancelled.takeLogin(Long.MAX_VALUE))
    }
    val changedNetwork = eligible(); changedNetwork.resetEvidence(); check(!changedNetwork.begin(41_000))
    val failedRepair = eligible(); check(failedRepair.begin(41_000)); check(failedRepair.logoutConfirmed(42_000))
    check(failedRepair.takeLogin(142_000)); failedRepair.fail()
    repeat(3) { failedRepair.observe(InternetEvidence.PORTAL_REQUIRED, 150_000L + it * 30_000) }
    check(!failedRepair.available(210_000))
    println("PASS: repair eligibility, stale/ambiguous evidence, confirmed logout, client wait policy, one login, cancellation and failure budget")
}
