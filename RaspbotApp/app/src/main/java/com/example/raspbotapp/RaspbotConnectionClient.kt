package com.example.raspbotapp

import android.os.Handler
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import java.net.Proxy
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit

class RaspbotConnectionClient(
    private val mainHandler: Handler,
    private val callbacks: Callbacks,
    private val reconnectMs: Long = 3000L,
) {
    interface Callbacks {
        fun isAlive(): Boolean
        fun isApplyingHost(): Boolean
        fun onConnecting()
        fun onOpen(usingCloudSignaling: Boolean)
        fun onText(text: String)
        fun onVideoFrame(jpeg: ByteArray)
        fun onEnvJson(json: String)
        fun onClosed()
        fun onFailure(message: String)
    }

    companion object {
        private const val TAG = "RaspbotConnection"
    }

    private val wsClient = OkHttpClient.Builder()
        .proxy(Proxy.NO_PROXY)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private var reconnectRunnable: Runnable? = null
    private var connected = false
    var usingCloudSignaling = true
        private set

    fun connect(target: String) {
        reconnectRunnable?.let { mainHandler.removeCallbacks(it) }
        val url = buildConnectionUrl(target)
        usingCloudSignaling = isCloudSignalingUrl(url)
        callbacks.onConnecting()
        val request = Request.Builder().url(url).build()
        webSocket = wsClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: okhttp3.Response) {
                connected = true
                callbacks.onOpen(usingCloudSignaling)
            }

            override fun onMessage(ws: WebSocket, text: String) {
                callbacks.onText(text)
            }

            override fun onMessage(ws: WebSocket, bytes: ByteString) {
                val data = bytes.toByteArray()
                if (data.isEmpty() || data.size <= 1) return
                when (data[0].toInt()) {
                    RaspbotProtocol.CAR_VIDEO_PREFIX -> callbacks.onVideoFrame(data.copyOfRange(1, data.size))
                    RaspbotProtocol.CAR_DATA_PREFIX -> {
                        val json = String(data.copyOfRange(1, data.size), StandardCharsets.UTF_8)
                        callbacks.onEnvJson(json)
                    }
                }
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                connected = false
                Log.d(TAG, "WebSocket closed code=$code reason=$reason")
                callbacks.onClosed()
                scheduleReconnect(target)
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: okhttp3.Response?) {
                connected = false
                Log.w(TAG, "WebSocket failure url=$url message=${t.message}", t)
                if (!callbacks.isApplyingHost()) {
                    callbacks.onFailure(t.message ?: "网络错误")
                    scheduleReconnect(target)
                }
            }
        })
    }

    fun reconnect(target: String) {
        reconnectRunnable?.let { mainHandler.removeCallbacks(it) }
        connected = false
        webSocket?.close(1000, "Reconnecting")
        webSocket = null
        connect(target)
    }

    fun sendBinary(payload: ByteArray): Boolean {
        if (!connected) return false
        return webSocket?.send(payload.toByteString()) == true
    }

    fun sendText(text: String): Boolean {
        if (!connected || usingCloudSignaling) return false
        return webSocket?.send(text) == true
    }

    fun sendSignaling(text: String): Boolean {
        return webSocket?.send(text) == true
    }

    fun isConnected(): Boolean = connected

    fun close(reason: String = "Closed") {
        reconnectRunnable?.let { mainHandler.removeCallbacks(it) }
        reconnectRunnable = null
        connected = false
        webSocket?.close(1000, reason)
        webSocket = null
    }

    fun shutdown() {
        close("Activity destroyed")
        wsClient.dispatcher.cancelAll()
        wsClient.connectionPool.evictAll()
        wsClient.dispatcher.executorService.shutdown()
    }

    private fun scheduleReconnect(target: String) {
        if (!callbacks.isAlive() || callbacks.isApplyingHost()) return
        val r = Runnable { connect(target) }
        reconnectRunnable = r
        mainHandler.postDelayed(r, reconnectMs)
    }
}

fun buildConnectionUrl(input: String): String {
    val value = input.trim()
    if (isCloudConnectionTarget(value)) return RaspbotProtocol.DEFAULT_SIGNALING_URL
    if (value.startsWith("ws://") || value.startsWith("wss://")) return value
    return "ws://$value:${RaspbotProtocol.LOCAL_WS_PORT}"
}

fun isCloudSignalingUrl(url: String): Boolean {
    return url.contains(":8765") || url.contains("/pc_room")
}

fun normalizeConnectionTarget(input: String): String {
    val value = input.trim()
    return if (isCloudConnectionTarget(value)) RaspbotProtocol.CLOUD_CONNECTION_LABEL else value
}

fun displayConnectionTarget(input: String): String {
    return if (isCloudConnectionTarget(input)) RaspbotProtocol.CLOUD_CONNECTION_LABEL else input.trim()
}

fun isCloudConnectionTarget(input: String): Boolean {
    val value = input.trim()
    if (value.isBlank()) return true
    return value.equals(RaspbotProtocol.CLOUD_CONNECTION_LABEL, ignoreCase = true)
            || value.equals("cloud", ignoreCase = true)
            || value.equals("default", ignoreCase = true)
            || value == RaspbotProtocol.DEFAULT_SIGNALING_URL
            || value == "47.108.164.190"
            || value == "47.108.164.190:8765"
            || value == "47.108.164.190/pc_room"
}
