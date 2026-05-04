package com.example.raspbotapp

object CommandSendPolicy {
    const val MOTION_KEEPALIVE_MS = 300L

    private val motionActions = setOf("forward", "backward", "left", "right", "spin_left", "spin_right")

    fun shouldSend(
        force: Boolean,
        trackingMode: Boolean,
        speakerVolumeDirty: Boolean,
        commandJson: String,
        lastCommandJson: String,
        action: String,
        speed: Int,
        elapsedSinceLastSendMs: Long,
    ): Boolean {
        if (force) return true
        if (trackingMode && !speakerVolumeDirty) return false
        if (commandJson != lastCommandJson) return true
        return action in motionActions && speed > 0 && elapsedSinceLastSendMs >= MOTION_KEEPALIVE_MS
    }
}
