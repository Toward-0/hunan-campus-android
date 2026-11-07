package org.esurfing.hunan
object SessionState {
    fun snapshot() = SessionSnapshot()
    fun log(message: String) = Unit
}
enum class TracePoint { REQUEST_START, REQUEST_FINISH, CONTROL }
enum class TaskKind { INTERNET, AUTH }
object TimingTrace {
    fun emit(point: TracePoint, generation: Long, kind: TaskKind = TaskKind.AUTH, numeric: Long? = null, error: ErrorKind = ErrorKind.NONE) = Unit
}
