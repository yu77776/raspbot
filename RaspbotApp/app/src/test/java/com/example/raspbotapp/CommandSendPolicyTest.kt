package com.example.raspbotapp

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CommandSendPolicyTest {
    @Test
    fun duplicate_motion_command_is_resent_before_car_watchdog_expires() {
        val cmd = """{"action":"forward","speed":80}"""

        assertFalse(
            CommandSendPolicy.shouldSend(
                force = false,
                trackingMode = false,
                speakerVolumeDirty = false,
                commandJson = cmd,
                lastCommandJson = cmd,
                action = "forward",
                speed = 80,
                elapsedSinceLastSendMs = 299,
            )
        )
        assertTrue(
            CommandSendPolicy.shouldSend(
                force = false,
                trackingMode = false,
                speakerVolumeDirty = false,
                commandJson = cmd,
                lastCommandJson = cmd,
                action = "forward",
                speed = 80,
                elapsedSinceLastSendMs = 300,
            )
        )
    }

    @Test
    fun duplicate_stop_command_is_not_resent_by_keepalive_policy() {
        val cmd = """{"action":"stop","speed":0}"""

        assertFalse(
            CommandSendPolicy.shouldSend(
                force = false,
                trackingMode = false,
                speakerVolumeDirty = false,
                commandJson = cmd,
                lastCommandJson = cmd,
                action = "stop",
                speed = 0,
                elapsedSinceLastSendMs = 1000,
            )
        )
    }
}
