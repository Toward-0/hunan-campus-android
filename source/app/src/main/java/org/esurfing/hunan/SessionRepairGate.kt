package org.esurfing.hunan

/** One explicit user repair per service lifetime. No credentials or network I/O. */
class SessionRepairGate {
    enum class Stage { IDLE, LOGOUT, WAITING, LOGIN, COMPLETE, FAILED, CANCELLED }
    @Volatile var stage = Stage.IDLE
        private set
    private var firstPortalAt = -1L
    private var lastEvidenceAt = -1L
    private var portalCount = 0
    private var loginAfter = Long.MAX_VALUE
    companion object { const val WAIT_MS = 100_000L }

    @Synchronized fun observe(evidence: InternetEvidence, now: Long) {
        lastEvidenceAt = now
        if (evidence != InternetEvidence.PORTAL_REQUIRED) {
            firstPortalAt = -1; portalCount = 0
        } else {
            if (firstPortalAt < 0) firstPortalAt = now
            portalCount++
        }
    }
    @Synchronized fun available(now: Long): Boolean = stage == Stage.IDLE &&
        portalCount >= 3 && firstPortalAt >= 0 && now - firstPortalAt >= 30_000 &&
        now - lastEvidenceAt in 0..600_000
    @Synchronized fun resetEvidence() { firstPortalAt = -1; lastEvidenceAt = -1; portalCount = 0 }
    @Synchronized fun begin(now: Long): Boolean {
        if (!available(now)) return false
        stage = Stage.LOGOUT
        return true
    }
    @Synchronized fun logoutConfirmed(now: Long): Boolean {
        if (stage != Stage.LOGOUT) return false
        loginAfter = now + WAIT_MS
        stage = Stage.WAITING
        return true
    }
    @Synchronized fun takeLogin(now: Long): Boolean {
        if (stage != Stage.WAITING || now < loginAfter) return false
        stage = Stage.LOGIN
        return true
    }
    @Synchronized fun complete() { if (stage == Stage.LOGIN) stage = Stage.COMPLETE }
    @Synchronized fun fail() { stage = Stage.FAILED }
    @Synchronized fun cancel() { stage = Stage.CANCELLED }
}
