package com.example.raspbotapp

import android.content.Context
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class AlarmEvent(
    val timeMs: Long,
    val timeText: String,
    val alarm: String,
    val details: String,
    val entry: String,
    val snapshotKey: String? = null,
    val temp: Float? = null,
    val dist: Float? = null,
    val smoke: Int? = null,
    val lux: Int? = null,
    val crying: Boolean? = null,
    val cryScore: Int? = null
)

object AlarmEventStore {
    private const val PREFS_NAME = "raspbot_settings"
    private const val KEY_ALERT_EVENTS = "alert_events"
    private const val KEY_LAST_ALARM_TIMES = "last_alarm_times"
    const val MAX_ALERT_HISTORY = 40

    private val gson = Gson()
    private val eventListType = object : TypeToken<List<AlarmEvent>>() {}.type
    private val alarmTimesType = object : TypeToken<Map<String, Long>>() {}.type
    private val storeLock = Any()

    fun load(context: Context): List<AlarmEvent> {
        synchronized(storeLock) {
            val events = loadUnsafe(context)
            return compactEventsLocked(context, events)
        }
    }

    // Unsynchronized load — only call from within storeLock
    private fun loadUnsafe(context: Context): List<AlarmEvent> {
        val json = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_ALERT_EVENTS, null)
            ?: return emptyList()
        return runCatching {
            gson.fromJson<List<AlarmEvent>>(json, eventListType).orEmpty()
        }.getOrElse { emptyList() }
    }

    fun append(
        context: Context,
        alarm: String,
        details: String,
        timeMs: Long = System.currentTimeMillis(),
        snapshotKey: String? = null,
        temp: Float? = null,
        dist: Float? = null,
        smoke: Int? = null,
        lux: Int? = null,
        crying: Boolean? = null,
        cryScore: Int? = null
    ): AlarmEvent {
        synchronized(storeLock) {
            val time = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date(timeMs))
            val entry = if (details.isBlank()) {
                "[$time] $alarm"
            } else {
                "[$time] $alarm\n$details"
            }
            val event = AlarmEvent(
                timeMs = timeMs,
                timeText = time,
                alarm = alarm,
                details = details,
                entry = entry,
                snapshotKey = snapshotKey,
                temp = temp,
                dist = dist,
                smoke = smoke,
                lux = lux,
                crying = crying,
                cryScore = cryScore
            )
            val events = loadUnsafe(context).toMutableList()
            events.add(event)
            while (events.size > MAX_ALERT_HISTORY) {
                events.removeAt(0)
            }
            save(context, events)
            return event
        }
    }

    fun appendIfAllowed(
        context: Context,
        alarm: String,
        details: String,
        timeMs: Long = System.currentTimeMillis(),
        snapshotKey: String? = null,
        temp: Float? = null,
        dist: Float? = null,
        smoke: Int? = null,
        lux: Int? = null,
        crying: Boolean? = null,
        cryScore: Int? = null
    ): AlarmEvent? {
        synchronized(storeLock) {
            val keys = AlarmPolicy.alarmKeysFor(alarm)
            val lastTimes = loadLastAlarmTimes(context).toMutableMap()
            val primaryKey = AlarmPolicy.primaryAlarmKeyFor(keys)
            val allowed = run {
                val lastTime = lastTimes[primaryKey] ?: 0L
                timeMs - lastTime >= AlarmPolicy.cooldownMsForAlarmKey(primaryKey)
            }
            if (!allowed) return null
            keys.forEach { lastTimes[it] = timeMs }
            lastTimes[primaryKey] = timeMs
            saveLastAlarmTimes(context, lastTimes)
            return append(
                context, alarm, details, timeMs, snapshotKey,
                temp = temp, dist = dist, smoke = smoke, lux = lux,
                crying = crying, cryScore = cryScore
            )
        }
    }

    fun clear(context: Context) {
        synchronized(storeLock) {
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .remove(KEY_ALERT_EVENTS)
                .remove(KEY_LAST_ALARM_TIMES)
                .apply()
        }
    }

    private fun save(context: Context, events: List<AlarmEvent>) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_ALERT_EVENTS, gson.toJson(events))
            .apply()
    }

    private fun compactEventsLocked(context: Context, events: List<AlarmEvent>): List<AlarmEvent> {
        val lastTimes = mutableMapOf<String, Long>()
        val compacted = ArrayList<AlarmEvent>()
        for (event in events) {
            val keys = AlarmPolicy.alarmKeysFor(event.alarm)
            val primaryKey = AlarmPolicy.primaryAlarmKeyFor(keys)
            val allowed = run {
                val lastTime = lastTimes[primaryKey] ?: 0L
                event.timeMs - lastTime >= AlarmPolicy.cooldownMsForAlarmKey(primaryKey)
            }
            if (!allowed) continue
            keys.forEach { lastTimes[it] = event.timeMs }
            lastTimes[primaryKey] = event.timeMs
            compacted.add(event)
        }
        val bounded = compacted.takeLast(MAX_ALERT_HISTORY)
        if (bounded.size != events.size) {
            save(context, bounded)
        }
        saveLastAlarmTimes(context, lastTimes)
        return bounded
    }

    private fun loadLastAlarmTimes(context: Context): Map<String, Long> {
        val json = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_LAST_ALARM_TIMES, null)
            ?: return emptyMap()
        return runCatching {
            gson.fromJson<Map<String, Long>>(json, alarmTimesType).orEmpty()
        }.getOrElse { emptyMap() }
    }

    private fun saveLastAlarmTimes(context: Context, lastTimes: Map<String, Long>) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_LAST_ALARM_TIMES, gson.toJson(lastTimes))
            .apply()
    }
}
