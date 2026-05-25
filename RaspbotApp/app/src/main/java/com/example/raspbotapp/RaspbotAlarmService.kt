package com.example.raspbotapp

import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import com.example.raspbotapp.AlarmPolicy.asBooleanOrNull
import com.example.raspbotapp.AlarmPolicy.asFloatOrNull
import com.example.raspbotapp.AlarmPolicy.asIntOrNull
import com.example.raspbotapp.AlarmPolicy.asStringOrNull
import com.example.raspbotapp.AlarmPolicy.addAuthToken
import com.example.raspbotapp.AlarmPolicy.buildAlertDetails
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser

class RaspbotAlarmService : Service() {
    private val gson = Gson()
    private val mainHandler = Handler(Looper.getMainLooper())
    private lateinit var connectionClient: RaspbotConnectionClient

    @Volatile
    private var alive = false
    private var applyingHost = false
    private var lastAlarmSignature = ""
    private var lastAlarmAtMs = 0L

    override fun onCreate() {
        super.onCreate()
        alive = true
        AlarmNotifier.createChannel(this)
        connectionClient = RaspbotConnectionClient(
            mainHandler = mainHandler,
            callbacks = object : RaspbotConnectionClient.Callbacks {
                override fun isAlive(): Boolean = alive
                override fun isApplyingHost(): Boolean = applyingHost
                override fun onConnecting() {
                    updateForegroundStatus("连接中...")
                }
                override fun onOpen() {
                    updateForegroundStatus("后台监护运行中")
                    sendCloudEnvSubscribe()
                }
                override fun onText(text: String) {
                    handleTextMessage(text)
                }
                override fun onVideoFrame(jpeg: ByteArray) = Unit
                override fun onEnvJson(json: String) {
                    handleEnvJson(json)
                }
                override fun onClosed() {
                    updateForegroundStatus("连接断开，正在重连")
                }
                override fun onFailure(message: String) {
                    updateForegroundStatus("连接失败，正在重试")
                }
            }
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(
            AlarmNotifier.FOREGROUND_NOTIFICATION_ID,
            AlarmNotifier.buildMonitorNotification(this, "后台监护启动中")
        )
        connectionClient.reconnect(loadTarget(), dataOnly = true)
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        alive = false
        mainHandler.removeCallbacksAndMessages(null)
        connectionClient.shutdown()
        super.onDestroy()
    }

    private fun handleEnvJson(json: String) {
        try {
            val obj = JsonParser.parseString(json).asJsonObject
            val temp = asFloatOrNull(obj.get("temp_c"))
            val lux = asIntOrNull(obj.get("light_lux"))
            val smoke = asIntOrNull(obj.get("smoke"))
            val dist = asFloatOrNull(obj.get("dist_cm"))
            val crying = asBooleanOrNull(obj.get("crying"))
            val cryScore = asIntOrNull(obj.get("cry_score"))
            val batteryStatus = asStringOrNull(obj.get("battery_status"))
            val alarm = AlarmPolicy.buildAlarmMessage(obj, dist, smoke, temp, lux, crying, cryScore)
            if (alarm.isNullOrBlank()) {
                lastAlarmSignature = ""
                lastAlarmAtMs = 0L
                return
            }
            val nowMs = System.currentTimeMillis()
            lastAlarmSignature = alarm
            val details = buildAlertDetails(temp, dist, smoke, lux, crying, cryScore, batteryStatus)
            val event = AlarmEventStore.appendIfAllowed(this, alarm, details, nowMs)
                ?: return
            lastAlarmAtMs = event.timeMs
            AlarmNotifier.showAlarm(this, alarm)
        } catch (e: Exception) {
            Log.w(TAG, "handleEnvJson error", e)
        }
    }

    private fun handleTextMessage(text: String) {
        try {
            val obj = JsonParser.parseString(text).asJsonObject
            val type = asStringOrNull(obj.get("type")).orEmpty()
            if (type == RaspbotProtocol.TYPE_ENV_UPDATE) {
                val env = obj.get("env")
                if (env != null && env.isJsonObject) {
                    handleEnvJson(env.asJsonObject.toString())
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "handleTextMessage error", e)
        }
    }

    private fun loadTarget(): String {
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_HOST, RaspbotProtocol.CLOUD_CONNECTION_LABEL)
            .apply()
        return RaspbotProtocol.CLOUD_CONNECTION_LABEL
    }

    private fun updateForegroundStatus(text: String) {
        val notification = AlarmNotifier.buildMonitorNotification(this, text)
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
        nm.notify(AlarmNotifier.FOREGROUND_NOTIFICATION_ID, notification)
    }

    private fun sendCloudEnvSubscribe() {
        val obj = JsonObject().apply {
            addProperty("type", RaspbotProtocol.TYPE_ENV_SUBSCRIBE)
            addProperty("data_only", true)
            addAuthToken(this)
        }
        connectionClient.sendSignaling(gson.toJson(obj))
    }

    companion object {
        private const val TAG = "RaspbotAlarmService"
        private const val PREFS_NAME = "raspbot_settings"
        private const val KEY_HOST = "host"
    }
}
