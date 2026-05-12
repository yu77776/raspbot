package com.example.raspbotapp

import com.google.gson.JsonElement
import com.google.gson.JsonObject
import java.util.Locale

object AlarmPolicy {
    const val DISTANCE_CLOSE_CM = 20f
    const val TEMP_HIGH_C = 32f
    const val TEMP_LOW_C = 18f
    const val LIGHT_LOW_LUX = 50
    const val LIGHT_HIGH_LUX = 900
    const val SMOKE_ALARM_LEVEL = 60
    const val CRY_ALARM_SCORE = 60

    fun buildAlarmMessage(
        obj: JsonObject,
        dist: Float?,
        smoke: Int?,
        temp: Float?,
        lux: Int?,
        crying: Boolean?,
        cryScore: Int?
    ): String {
        val messages = ArrayList<String>()
        val backendAlarm = asStringOrNull(obj.get("alarm")).orEmpty()
        backendAlarm.split('+', ';', ',')
            .map { normalizeAlarmToken(it) }
            .filter { it.isNotBlank() }
            .forEach { if (!messages.contains(it)) messages.add(it) }

        if (dist != null && dist in 0f..DISTANCE_CLOSE_CM) {
            messages.add("距离过近")
        }
        if (smoke != null && smoke > SMOKE_ALARM_LEVEL) {
            messages.add("烟雾异常")
        }
        if (crying == true || (cryScore != null && cryScore >= CRY_ALARM_SCORE)) {
            messages.add("检测到哭声")
        }
        if (temp != null && temp >= TEMP_HIGH_C) {
            messages.add("温度过高")
        } else if (temp != null && temp <= TEMP_LOW_C) {
            messages.add("温度过低")
        }
        if (lux != null && lux <= LIGHT_LOW_LUX) {
            messages.add("光照过低")
        } else if (lux != null && lux >= LIGHT_HIGH_LUX) {
            messages.add("光照过强")
        }

        val track = obj.get("track")
        if (track?.isJsonArray == true) {
            val values = track.asJsonArray.mapNotNull { asIntOrNull(it) }
            if (values.size >= 4 && values.all { it == 0 }) {
                messages.add("底部循迹传感器全空，疑似悬空")
            }
        }

        return messages.distinct().joinToString("；")
    }

    fun normalizeAlarmToken(raw: String): String {
        val token = raw.trim()
        if (token.isBlank()) return ""
        val lower = token.lowercase(Locale.US)
        return when {
            lower == "smoke" || lower.startsWith("smoke") -> "烟雾异常"
            lower == "cry" || lower.startsWith("cry") -> "检测到哭声"
            lower == "close_distance" || lower.contains("dist") || lower.contains("close") -> "距离过近"
            lower.contains("track") || lower.contains("cliff") || lower.contains("suspend") -> "疑似悬空"
            lower.contains("battery") || lower.contains("volt") -> "电池电量低"
            lower == "temp_high" -> "室温偏高，请查看宝宝状态"
            lower == "temp_low" -> "室温偏低，请查看宝宝状态"
            lower == "light_low" -> "光照不足，识别稳定性可能下降"
            lower == "light_high" -> "光照过强，画面可能过曝"
            lower == "light_changed" -> "光照变化明显，小车已保守跟随"
            else -> token
        }
    }

    fun asStringOrNull(value: JsonElement?): String? {
        if (value == null || value.isJsonNull) return null
        return try {
            value.asString
        } catch (_: Exception) {
            null
        }
    }

    fun asIntOrNull(value: JsonElement?): Int? {
        if (value == null || value.isJsonNull) return null
        return try {
            value.asInt
        } catch (_: Exception) {
            null
        }
    }

    fun asFloatOrNull(value: JsonElement?): Float? {
        if (value == null || value.isJsonNull) return null
        return try {
            value.asFloat
        } catch (_: Exception) {
            null
        }
    }

    fun asBooleanOrNull(value: JsonElement?): Boolean? {
        if (value == null || value.isJsonNull) return null
        return try {
            value.asBoolean
        } catch (_: Exception) {
            null
        }
    }
}
