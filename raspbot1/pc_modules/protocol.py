"""Shared PC-side wire protocol constants.

Keep these values aligned with docs/protocol.md and the car/app protocol modules.
"""

MSG_VIDEO = 0x01
MSG_COMMAND = 0x02
MSG_ENV = 0x03

TYPE_APP_VOICE = "app_voice"
TYPE_WEBRTC_OFFER = "webrtc_offer"
TYPE_WEBRTC_ANSWER = "webrtc_answer"
TYPE_WEBRTC_ICE = "webrtc_ice"
