package com.example.raspbotapp

import android.os.Handler
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.net.Proxy
import java.net.URLEncoder
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
        fun onOpen()
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
    @Volatile
    private var connected = false

    fun connect(dataOnly: Boolean = false) {
        reconnectRunnable?.let { mainHandler.removeCallbacks(it) }
        val url = buildConnectionUrl(dataOnly)
        callbacks.onConnecting()
        val request = Request.Builder().url(url).build()
        webSocket = wsClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: okhttp3.Response) {
                connected = true
                callbacks.onOpen()
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
                scheduleReconnect(dataOnly)
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: okhttp3.Response?) {
                connected = false
                Log.w(TAG, "WebSocket failure url=$url message=${t.message}", t)
                if (!callbacks.isApplyingHost()) {
                    callbacks.onFailure(t.message ?: "网络错误")
                    scheduleReconnect(dataOnly)
                }
            }
        })
    }

    fun reconnect(dataOnly: Boolean = false) {
        reconnectRunnable?.let { mainHandler.removeCallbacks(it) }
        connected = false
        webSocket?.close(1000, "Reconnecting")
        webSocket = null
        connect(dataOnly)
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

    private fun scheduleReconnect(dataOnly: Boolean) {
        if (!callbacks.isAlive() || callbacks.isApplyingHost()) return
        val r = Runnable { connect(dataOnly) }
        reconnectRunnable = r
        mainHandler.postDelayed(r, reconnectMs)
    }
}

fun buildConnectionUrl(dataOnly: Boolean = false): String {
    return appendConnectionFlags(appendAuthToken(RaspbotProtocol.DEFAULT_SIGNALING_URL), dataOnly)
}

private fun appendConnectionFlags(url: String, dataOnly: Boolean): String {
    if (!dataOnly) return url
    val separator = if (url.contains("?")) "&" else "?"
    return "${url}${separator}data_only=1"
}

private fun appendAuthToken(url: String): String {
    val token = BuildConfig.RASPBOT_AUTH_TOKEN.trim()
    if (token.isBlank()) return url
    val separator = if (url.contains("?")) "&" else "?"
    return "$url${separator}token=${URLEncoder.encode(token, "UTF-8")}"
}
