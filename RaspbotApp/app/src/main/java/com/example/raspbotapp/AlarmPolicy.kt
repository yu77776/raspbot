package com.example.raspbotapp

import com.google.gson.JsonElement
import com.google.gson.JsonObject
import java.util.Locale

object AlarmPolicy {
    const val DISTANCE_CLOSE_CM = 20f
    const val TEMP_HIGH_C = 32f
    const val TEMP_LOW_C = 15f
    const val LIGHT_LOW_LUX = 50
    const val LIGHT_HIGH_LUX = 900
    const val SMOKE_ALARM_LEVEL = 60
    const val CRY_ALARM_SCORE = 60
    const val ALARM_COOLDOWN_MS = 2 * 60 * 1000L
    const val TEMPERATURE_ALARM_COOLDOWN_MS = 5 * 60 * 1000L

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

    fun cooldownMsFor(message: String): Long {
        return if (alarmKeysFor(message).contains("temperature")) {
            TEMPERATURE_ALARM_COOLDOWN_MS
        } else {
            ALARM_COOLDOWN_MS
        }
    }

    fun notificationIdFor(message: String): Int {
        return when {
            alarmKeysFor(message).contains("temperature") -> 2001
            message.contains("检测到哭声") -> 2002
            message.contains("距离过近") -> 2003
            message.contains("烟雾") -> 2004
            message.contains("悬空") || message.contains("循迹") -> 2005
            message.contains("光照") -> 2006
            message.contains("电池") -> 2007
            else -> 2099
        }
    }

    fun alarmKeysFor(message: String): Set<String> {
        val keys = linkedSetOf<String>()
        message.split('；', ';', '+', ',')
            .map { it.trim() }
            .filter { it.isNotBlank() }
            .forEach { part ->
                when {
                    part.contains("室温偏低")
                        || part.contains("室温偏高")
                        || part.contains("温度过低")
                        || part.contains("温度过高")
                        || part.contains("temp_low")
                        || part.contains("temp_high") -> keys.add("temperature")
                    part.contains("检测到哭声") || part.contains("cry") -> keys.add("cry")
                    part.contains("距离过近") || part.contains("close_distance") -> keys.add("distance")
                    part.contains("烟雾") || part.contains("smoke") -> keys.add("smoke")
                    part.contains("悬空") || part.contains("循迹") || part.contains("cliff") -> keys.add("cliff")
                    part.contains("光照") || part.contains("light") -> keys.add("light")
                    part.contains("电池") || part.contains("battery") || part.contains("volt") -> keys.add("battery")
                    else -> keys.add("other:${part.lowercase(Locale.US)}")
                }
            }
        return if (keys.isEmpty()) setOf("other:${message.lowercase(Locale.US)}") else keys
    }

    fun cooldownMsForAlarmKey(key: String): Long {
        return if (key == "temperature") {
            TEMPERATURE_ALARM_COOLDOWN_MS
        } else {
            ALARM_COOLDOWN_MS
        }
    }

    fun primaryAlarmKeyFor(keys: Set<String>): String {
        val priority = listOf("temperature", "smoke", "cliff", "distance", "cry", "battery", "light")
        return priority.firstOrNull { keys.contains(it) } ?: keys.firstOrNull().orEmpty()
    }

    fun asStringOrNull(value: JsonElement?): String? {
        if (value == null || value.isJsonNull) return null
        return value.asString
    }

    fun asIntOrNull(value: JsonElement?): Int? {
        if (value == null || value.isJsonNull) return null
        return value.asInt
    }

    fun asFloatOrNull(value: JsonElement?): Float? {
        if (value == null || value.isJsonNull) return null
        return value.asFloat
    }

    fun asBooleanOrNull(value: JsonElement?): Boolean? {
        if (value == null || value.isJsonNull) return null
        return value.asBoolean
    }

    fun buildAlertDetails(
        temp: Float?,
        dist: Float?,
        smoke: Int?,
        lux: Int?,
        crying: Boolean?,
        cryScore: Int?,
        batteryStatus: String? = null
    ): String {
        val parts = ArrayList<String>()
        if (dist != null) parts.add("距离 ${dist.toInt()}cm")
        if (temp != null) parts.add("室温 ${String.format("%.1f", temp)}°C")
        if (lux != null) parts.add("光照 ${lux}lux")
        if (smoke != null) parts.add("烟雾 $smoke")
        if (cryScore != null) parts.add("哭声分数 $cryScore")
        else if (crying == true) parts.add("哭声 检测")
        val powerText = buildBatteryDisplay(batteryStatus)
        if (!powerText.isNullOrBlank()) parts.add(powerText)
        return parts.joinToString(" · ")
    }

    fun buildBatteryDisplay(status: String?): String? {
        if (status.isNullOrBlank()) return null
        val normalizedStatus = when {
            status.equals("LOW", ignoreCase = true) -> "偏低"
            status.equals("OK", ignoreCase = true) -> "正常"
            else -> status
        }
        return "电量 $normalizedStatus".trim()
    }

    fun addAuthToken(obj: JsonObject) {
        val token = BuildConfig.RASPBOT_AUTH_TOKEN.trim()
        if (token.isNotBlank()) {
            obj.addProperty("auth_token", token)
        }
    }
}
