package com.example.raspbotapp

import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.annotations.SerializedName
import com.google.gson.reflect.TypeToken
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

data class OssAlarmImage(
    val key: String,
    @SerializedName("date_dir") val dateDir: String,
    @SerializedName("time_str") val timeStr: String,
    @SerializedName("alarm_type") val alarmType: String
)

class OssImageLoader(
    private val signalSender: (String) -> Boolean,
    private val timeoutSec: Long = 15
) {
    companion object {
        private const val TAG = "OssImageLoader"
        const val MAX_IMAGES = 20
    }

    private val gson = Gson()
    private val pending = ConcurrentHashMap<String, PendingRequest>()

    private class PendingRequest(
        val latch: CountDownLatch = CountDownLatch(1),
        val response: AtomicReference<String?> = AtomicReference(null)
    )

    val enabled: Boolean
        get() = true

    fun handleSignalResponse(type: String, payload: JsonObject) {
        val requestId = payload.get("request_id")?.asString ?: return
        val req = pending[requestId] ?: return
        req.response.set(payload.toString())
        req.latch.countDown()
    }

    fun listRecentImages(maxKeys: Int = MAX_IMAGES): List<OssAlarmImage> {
        val requestId = UUID.randomUUID().toString()
        val req = PendingRequest()
        pending[requestId] = req

        val msg = JsonObject().apply {
            addProperty("type", "oss_list")
            addProperty("request_id", requestId)
            addProperty("prefix", "alarms/")
            addProperty("max_keys", maxKeys)
        }
        if (!signalSender(gson.toJson(msg))) {
            pending.remove(requestId)
            return emptyList()
        }
        return try {
            if (!req.latch.await(timeoutSec, TimeUnit.SECONDS)) {
                Log.w(TAG, "listRecentImages timeout")
                return emptyList()
            }
            val json = req.response.get() ?: return emptyList()
            val obj = JsonParser.parseString(json).asJsonObject
            val imagesArray = obj.getAsJsonArray("images") ?: return emptyList()
            val listType = object : TypeToken<List<OssAlarmImage>>() {}.type
            gson.fromJson<List<OssAlarmImage>>(imagesArray, listType).orEmpty()
        } catch (e: Exception) {
            Log.e(TAG, "listRecentImages failed: ${e.message}", e)
            emptyList()
        } finally {
            pending.remove(requestId)
        }
    }

    fun findSnapshotForAlarm(alarmType: String, alarmTimeMs: Long): OssAlarmImage? {
        val images = listRecentImages(40)
        if (images.isEmpty()) return null

        val alarmCal = java.util.Calendar.getInstance(java.util.TimeZone.getTimeZone("GMT+8"))
        alarmCal.timeInMillis = alarmTimeMs
        val alarmSec = alarmCal.get(java.util.Calendar.HOUR_OF_DAY) * 3600L +
                       alarmCal.get(java.util.Calendar.MINUTE) * 60L +
                       alarmCal.get(java.util.Calendar.SECOND)
        val ossToken = alarmToOssToken(alarmType)
        return images
            .filter { it.alarmType.equals(ossToken, ignoreCase = true) ||
                      it.alarmType.contains(ossToken, ignoreCase = true) ||
                      ossToken.contains(it.alarmType, ignoreCase = true) }
            .minByOrNull { img ->
                val imgSec = parseTimeToSeconds(img.timeStr)
                kotlin.math.abs(imgSec - alarmSec)
            }?.takeIf { img ->
                val imgSec = parseTimeToSeconds(img.timeStr)
                kotlin.math.abs(imgSec - alarmSec) <= 10
            }
    }

    fun downloadImage(key: String): ByteArray? {
        val requestId = UUID.randomUUID().toString()
        val req = PendingRequest()
        pending[requestId] = req

        val msg = JsonObject().apply {
            addProperty("type", "oss_download")
            addProperty("request_id", requestId)
            addProperty("key", key)
        }
        if (!signalSender(gson.toJson(msg))) {
            pending.remove(requestId)
            return null
        }
        return try {
            if (!req.latch.await(timeoutSec, TimeUnit.SECONDS)) {
                Log.w(TAG, "downloadImage timeout for $key")
                return null
            }
            val json = req.response.get() ?: return null
            val obj = JsonParser.parseString(json).asJsonObject
            val dataB64 = obj.get("data")?.asString
            if (dataB64.isNullOrEmpty()) {
                Log.w(TAG, "downloadImage empty data for $key err=${obj.get("error")?.asString}")
                return null
            }
            android.util.Base64.decode(dataB64, android.util.Base64.DEFAULT)
        } catch (e: Exception) {
            Log.e(TAG, "downloadImage failed: $key: ${e.message}", e)
            null
        } finally {
            pending.remove(requestId)
        }
    }

    private fun parseTimeToSeconds(timeStr: String): Long {
        return try {
            if (timeStr.length >= 6) {
                val h = timeStr.substring(0, 2).toLong()
                val m = timeStr.substring(2, 4).toLong()
                val s = timeStr.substring(4, 6).toLong()
                h * 3600 + m * 60 + s
            } else 0L
        } catch (_: Exception) { 0L }
    }

    private fun alarmToOssToken(alarmText: String): String {
        return when {
            alarmText.contains("哭") || alarmText.contains("cry") -> "cry"
            alarmText.contains("烟") || alarmText.contains("smoke") -> "smoke"
            alarmText.contains("悬崖") || alarmText.contains("悬空") || alarmText.contains("cliff") -> "cliff"
            alarmText.contains("高温") || alarmText.contains("temp_high") -> "temp_high"
            alarmText.contains("低温") || alarmText.contains("temp_low") -> "temp_low"
            alarmText.contains("距离") || alarmText.contains("close") -> "close_distance"
            else -> alarmText.replace(" ", "_").lowercase().take(12)
        }
    }
}
