package com.example.raspbotapp

import android.content.Context
import android.util.Log
import android.view.View
import com.example.raspbotapp.AlarmPolicy.asIntOrNull
import com.example.raspbotapp.AlarmPolicy.asStringOrNull
import com.google.gson.Gson
import com.google.gson.JsonObject
import org.webrtc.DataChannel
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.MediaStreamTrack
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RendererCommon
import org.webrtc.RtpReceiver
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.SurfaceViewRenderer
import org.webrtc.VideoTrack
import java.nio.ByteBuffer
import java.nio.charset.StandardCharsets

class RaspbotWebRtcClient(
    private val context: Context,
    private val videoView: SurfaceViewRenderer,
    private val signalingSender: (String) -> Boolean,
    private val callbacks: Callbacks,
) {
    interface Callbacks {
        fun onStatus(text: String)
        fun onRemoteVideo()
        fun onEnvJson(json: String)
        fun onCommandChannelOpen()
        fun isSignalingConnected(): Boolean
    }

    companion object {
        private const val TAG = "RaspbotWebRtc"
        private var factoryInitialized = false
    }

    private val gson = Gson()
    private var eglBase: EglBase? = null
    private var peerConnectionFactory: PeerConnectionFactory? = null
    private var peerConnection: PeerConnection? = null
    private var envDataChannel: DataChannel? = null
    private var commandDataChannel: DataChannel? = null
    private var ready = false
    private var videoInitialized = false

    fun setup() {
        try {
            val initializationOptions = PeerConnectionFactory.InitializationOptions.builder(context)
                .setFieldTrials("")
                .createInitializationOptions()
            if (!factoryInitialized) {
                PeerConnectionFactory.initialize(initializationOptions)
                factoryInitialized = true
            }

            val egl = eglBase ?: EglBase.create().also { eglBase = it }
            if (peerConnectionFactory == null) {
                val encoderFactory = DefaultVideoEncoderFactory(egl.eglBaseContext, true, true)
                val decoderFactory = DefaultVideoDecoderFactory(egl.eglBaseContext)
                peerConnectionFactory = PeerConnectionFactory.builder()
                    .setVideoEncoderFactory(encoderFactory)
                    .setVideoDecoderFactory(decoderFactory)
                    .createPeerConnectionFactory()
            }

            if (!videoInitialized) {
                videoView.init(egl.eglBaseContext, null)
                videoView.setEnableHardwareScaler(true)
                videoView.setScalingType(RendererCommon.ScalingType.SCALE_ASPECT_FIT)
                videoView.setMirror(false)
                videoInitialized = true
            }
            ready = true
        } catch (e: Exception) {
            Log.e(TAG, "WebRTC init failed", e)
            ready = false
            callbacks.onStatus("视频初始化失败: ${e.message ?: "未知错误"}")
        }
    }

    fun start() {
        val factory = peerConnectionFactory ?: return
        if (!ready) return
        closePeerConnection()
        callbacks.onStatus("WebRTC建链中")

        val iceServers = listOf(
            PeerConnection.IceServer.builder("stun:47.108.164.190:3478").createIceServer(),
            PeerConnection.IceServer.builder("turn:47.108.164.190:3478")
                .setUsername("webrtc_user")
                .setPassword(BuildConfig.RASPBOT_TURN_CREDENTIAL)
                .createIceServer()
        )
        val config = PeerConnection.RTCConfiguration(iceServers).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        }
        peerConnection = factory.createPeerConnection(config, object : PeerConnection.Observer {
            override fun onIceCandidate(candidate: IceCandidate) {
                if (!callbacks.isSignalingConnected()) return
                val iceJson = JsonObject().apply {
                    addProperty("type", RaspbotProtocol.TYPE_WEBRTC_ICE)
                    val candidateObj = JsonObject().apply {
                        addProperty("candidate", candidate.sdp)
                        addProperty("sdpMid", candidate.sdpMid)
                        addProperty("sdpMLineIndex", candidate.sdpMLineIndex)
                    }
                    add("candidate", candidateObj)
                    addProperty("ice", candidate.sdp)
                    addProperty("sdpMid", candidate.sdpMid)
                    addProperty("sdpMLineIndex", candidate.sdpMLineIndex)
                }
                signalingSender(gson.toJson(iceJson))
            }

            override fun onIceCandidatesRemoved(candidates: Array<IceCandidate>) {}
            override fun onSignalingChange(state: PeerConnection.SignalingState) {}
            override fun onIceConnectionReceivingChange(receiving: Boolean) {}
            override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) {}
            override fun onAddStream(stream: MediaStream) {}
            override fun onRemoveStream(stream: MediaStream) {}
            override fun onRenegotiationNeeded() {}

            override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
                Log.d(TAG, "ICE state=$state")
                callbacks.onStatus(
                    when (state) {
                        PeerConnection.IceConnectionState.CONNECTED,
                        PeerConnection.IceConnectionState.COMPLETED -> "WebRTC已连接"
                        PeerConnection.IceConnectionState.FAILED -> "WebRTC失败"
                        PeerConnection.IceConnectionState.DISCONNECTED -> "WebRTC断开"
                        else -> "WebRTC连接中"
                    }
                )
            }

            override fun onDataChannel(channel: DataChannel) {
                registerDataChannel(channel)
            }

            override fun onAddTrack(receiver: RtpReceiver, streams: Array<MediaStream>) {
                val track = receiver.track()
                if (track is VideoTrack) {
                    callbacks.onRemoteVideo()
                    track.addSink(videoView)
                }
            }
        })
        if (peerConnection == null) {
            callbacks.onStatus("WebRTC创建失败")
            Log.e(TAG, "createPeerConnection returned null")
            return
        }

        envDataChannel = peerConnection?.createDataChannel("env", DataChannel.Init())?.also {
            registerDataChannel(it)
        }
        commandDataChannel = peerConnection?.createDataChannel("command", DataChannel.Init())?.also {
            registerDataChannel(it)
        }
        peerConnection?.addTransceiver(
            MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO,
            RtpTransceiver.RtpTransceiverInit(RtpTransceiver.RtpTransceiverDirection.RECV_ONLY)
        )

        val mediaConstraints = MediaConstraints().apply {
            mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveVideo", "true"))
        }
        peerConnection?.createOffer(object : SdpObserver {
            override fun onCreateSuccess(desc: SessionDescription) {
                peerConnection?.setLocalDescription(object : SdpObserver {
                    override fun onSetSuccess() {
                        val offerJson = JsonObject().apply {
                            addProperty("type", RaspbotProtocol.TYPE_WEBRTC_OFFER)
                            addProperty("sdp", desc.description)
                            addProperty("sdpType", desc.type.canonicalForm())
                        }
                        val sent = signalingSender(gson.toJson(offerJson))
                        Log.d(TAG, "WebRTC offer sent=$sent")
                        if (!sent) callbacks.onStatus("Offer发送失败")
                    }

                    override fun onSetFailure(msg: String) {
                        Log.e(TAG, "setLocalDescription failed: $msg")
                        callbacks.onStatus("本地SDP失败")
                    }

                    override fun onCreateSuccess(desc: SessionDescription) {}
                    override fun onCreateFailure(msg: String) {}
                }, desc)
            }

            override fun onSetSuccess() {}
            override fun onCreateFailure(msg: String) {
                Log.e(TAG, "createOffer failed: $msg")
                callbacks.onStatus("Offer创建失败")
            }

            override fun onSetFailure(msg: String) {}
        }, mediaConstraints)
    }

    fun handleAnswer(obj: JsonObject) {
        val sdpRaw = asStringOrNull(obj.get("sdp")) ?: asStringOrNull(obj.get("answer")) ?: return
        val sdp = sdpRaw.replace("\\n", "\n")
        val answer = SessionDescription(SessionDescription.Type.ANSWER, sdp)
        peerConnection?.setRemoteDescription(object : SdpObserver {
            override fun onSetSuccess() {
                Log.d(TAG, "WebRTC remote answer applied")
            }

            override fun onSetFailure(msg: String) {
                Log.e(TAG, "setRemoteDescription failed: $msg")
                callbacks.onStatus("远端SDP失败")
            }

            override fun onCreateSuccess(desc: SessionDescription) {}
            override fun onCreateFailure(msg: String) {}
        }, answer)
    }

    fun handleIce(obj: JsonObject) {
        val candidateObj = if (obj.get("candidate")?.isJsonObject == true) {
            obj.getAsJsonObject("candidate")
        } else {
            null
        }
        val candidateSdp = asStringOrNull(candidateObj?.get("candidate"))
            ?: asStringOrNull(obj.get("candidate"))
            ?: asStringOrNull(obj.get("ice"))
            ?: return
        val sdpMid = asStringOrNull(candidateObj?.get("sdpMid")) ?: asStringOrNull(obj.get("sdpMid"))
        val sdpMLineIndex = asIntOrNull(candidateObj?.get("sdpMLineIndex"))
            ?: asIntOrNull(obj.get("sdpMLineIndex"))
            ?: 0
        peerConnection?.addIceCandidate(IceCandidate(sdpMid, sdpMLineIndex, candidateSdp))
    }

    fun isCommandChannelOpen(): Boolean {
        return commandDataChannel?.state() == DataChannel.State.OPEN
    }

    fun sendCommandJson(json: String): Boolean {
        val channel = commandDataChannel ?: return false
        if (channel.state() != DataChannel.State.OPEN) return false
        channel.send(DataChannel.Buffer(ByteBuffer.wrap(json.toByteArray(StandardCharsets.UTF_8)), false))
        return true
    }

    fun sendText(text: String): Boolean {
        val channel = commandDataChannel ?: return false
        if (channel.state() != DataChannel.State.OPEN) return false
        channel.send(DataChannel.Buffer(ByteBuffer.wrap(text.toByteArray(StandardCharsets.UTF_8)), false))
        return true
    }

    fun close() {
        closePeerConnection()
        if (videoInitialized) {
            videoView.release()
            videoInitialized = false
        }
        eglBase?.release()
        eglBase = null
        peerConnectionFactory?.dispose()
        peerConnectionFactory = null
        ready = false
        videoView.visibility = View.GONE
    }

    private fun registerDataChannel(channel: DataChannel) {
        when (channel.label()) {
            "env" -> envDataChannel = channel
            "command" -> commandDataChannel = channel
        }
        channel.registerObserver(object : DataChannel.Observer {
            override fun onBufferedAmountChange(previousAmount: Long) {}

            override fun onStateChange() {
                if (channel.label() == "command" && channel.state() == DataChannel.State.OPEN) {
                    callbacks.onCommandChannelOpen()
                }
            }

            override fun onMessage(buffer: DataChannel.Buffer) {
                if (buffer.binary) return
                val bytes = ByteArray(buffer.data.remaining())
                buffer.data.get(bytes)
                val text = String(bytes, StandardCharsets.UTF_8)
                if (channel.label() == "env") {
                    callbacks.onEnvJson(text)
                }
            }
        })
    }

    private fun closePeerConnection() {
        envDataChannel?.close()
        commandDataChannel?.close()
        envDataChannel = null
        commandDataChannel = null
        peerConnection?.close()
        peerConnection?.dispose()
        peerConnection = null
        videoView.visibility = View.GONE
    }
}
