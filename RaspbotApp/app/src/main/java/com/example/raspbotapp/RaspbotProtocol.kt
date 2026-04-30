package com.example.raspbotapp

object RaspbotProtocol {
    const val CLOUD_CONNECTION_LABEL = "云端"
    const val DEFAULT_SIGNALING_URL = "ws://47.108.164.190:8765/pc_room"
    const val LOCAL_WS_PORT = 7000

    const val APP_CMD_PREFIX: Byte = 0x02
    const val CAR_VIDEO_PREFIX = 0x01
    const val CAR_DATA_PREFIX = 0x03

    const val TYPE_APP_VOICE = "app_voice"
    const val TYPE_WEBRTC_OFFER = "webrtc_offer"
    const val TYPE_WEBRTC_ANSWER = "webrtc_answer"
    const val TYPE_WEBRTC_ICE = "webrtc_ice"
}
