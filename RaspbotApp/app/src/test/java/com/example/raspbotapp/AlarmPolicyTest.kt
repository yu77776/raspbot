package com.example.raspbotapp

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AlarmPolicyTest {
    @Test
    fun cryDistIsNotMisclassifiedAsDistance() {
        assertEquals("cry_dist", AlarmPolicy.normalizeAlarmToken("cry_dist"))
        assertEquals(setOf("other:cry_dist"), AlarmPolicy.alarmKeysFor("cry_dist"))
    }

    @Test
    fun knownAlarmTokensAreClassifiedExactly() {
        assertEquals("距离过近", AlarmPolicy.normalizeAlarmToken("close_distance"))
        assertEquals("检测到哭声", AlarmPolicy.normalizeAlarmToken("cry"))
        assertTrue(AlarmPolicy.alarmKeysFor("close_distance+cry").contains("distance"))
        assertTrue(AlarmPolicy.alarmKeysFor("close_distance+cry").contains("cry"))
    }
}
