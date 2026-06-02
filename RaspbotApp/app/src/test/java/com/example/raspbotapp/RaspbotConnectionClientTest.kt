package com.example.raspbotapp

import org.junit.Assert.assertTrue
import org.junit.Test

class RaspbotConnectionClientTest {
    @Test
    fun connection_url_is_cloud_signaling_only() {
        val url = buildConnectionUrl(dataOnly = true)

        assertTrue(url.startsWith(RaspbotProtocol.DEFAULT_SIGNALING_URL))
        assertTrue(url.contains("data_only=1"))
    }
}
