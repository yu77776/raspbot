package com.example.raspbotapp

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.example.raspbotapp.ui.DirectionPadView
import com.example.raspbotapp.ui.SimpleTrendView
import com.example.raspbotapp.AlarmPolicy.asBooleanOrNull
import com.example.raspbotapp.AlarmPolicy.asFloatOrNull
import com.example.raspbotapp.AlarmPolicy.asIntOrNull
import com.example.raspbotapp.AlarmPolicy.asStringOrNull
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import org.webrtc.SurfaceViewRenderer
import java.nio.charset.StandardCharsets
import java.text.SimpleDateFormat
import java.util.ArrayDeque
import java.util.Date
import java.util.Locale
import kotlin.math.abs

class MainActivity : AppCompatActivity() {
    companion object {
        private const val PREFS_NAME = "raspbot_settings"
        private const val KEY_HOST = "host"
        private const val KEY_VOICE_PROMPT = "voice_prompt"
        private const val KEY_TRACKING_MODE = "tracking_mode"
        private const val KEY_SPEAKER_VOLUME = "speaker_volume"

        private const val CMD_SEND_INTERVAL_MS = 100L

        private const val NOTIFICATION_CHANNEL_ID = "raspbot_alarm"
        private const val NOTIFICATION_CHANNEL_NAME = "Raspbot Alarms"
        private const val NOTIFICATION_REQUEST_CODE = 1001

        private const val MAX_ALERT_HISTORY = 40
        private const val TREND_WINDOW_MS = 5 * 60 * 1000L
        private const val TREND_RENDER_POINTS = 72
        private const val TAG = "RaspbotApp"
    }

    private data class TrendSample(val timestampMs: Long, val value: Float)

    private enum class Page {
        HOME, CONTROL, MONITOR, MESSAGE, MINE
    }

    private val gson = Gson()
    private val mainHandler = Handler(Looper.getMainLooper())

    // Pages
    private lateinit var pageHome: ScrollView
    private lateinit var pageControl: ScrollView
    private lateinit var pageMonitor: ScrollView
    private lateinit var pageMessage: ScrollView
    private lateinit var pageMine: ScrollView

    // Nav buttons
    private lateinit var btnTabHome: Button
    private lateinit var btnTabControl: Button
    private lateinit var btnTabMonitor: Button
    private lateinit var btnTabMessage: Button
    private lateinit var btnTabMine: Button
    private lateinit var tvPageTitle: TextView

    // Mode
    private lateinit var btnManualMode: Button
    private lateinit var btnAutoMode: Button

    // Controls
    private lateinit var directionPad: DirectionPadView
    private lateinit var seekSpeed: SeekBar
    private lateinit var seekServo1: SeekBar
    private lateinit var seekServo2: SeekBar
    private lateinit var seekSpeakerVolume: SeekBar
    private lateinit var tvSpeedVal: TextView
    private lateinit var tvServo1: TextView
    private lateinit var tvServo2: TextView
    private lateinit var tvSpeakerVolume: TextView
    private lateinit var btnServoCenter: Button
    private lateinit var btnStop: Button
    private lateinit var btnAudioToggle: Button

    // Mine
    private lateinit var etHost: EditText
    private lateinit var btnApplyHost: Button
    private lateinit var swVoicePrompt: Switch
    private lateinit var swTrackingMode: Switch

    // Video
    private lateinit var commonVideoCard: View
    private lateinit var rtcVideo: SurfaceViewRenderer
    private lateinit var imgVideoFrame: ImageView
    private lateinit var tvVideoStatus: TextView

    // HOME status
    private lateinit var tvConnection: TextView
    private lateinit var tvHostDisplay: TextView
    private lateinit var cardAlertSummary: View
    private lateinit var tvAlertLabel: TextView
    private lateinit var tvAlertCount: TextView
    private lateinit var tvHomeDistance: TextView
    private lateinit var tvHomeTemp: TextView
    private lateinit var tvHomeSmoke: TextView
    private lateinit var tvHomeLight: TextView
    private lateinit var layoutAlarmBanner: LinearLayout
    private lateinit var tvAlarmText: TextView
    private lateinit var tvAlarmCount: TextView

    // MONITOR
    private lateinit var tvTemp: TextView
    private lateinit var tvLightLux: TextView
    private lateinit var tvSmoke: TextView
    private lateinit var tvDistance: TextView
    private lateinit var tvVolume: TextView
    private lateinit var tvCry: TextView
    private lateinit var tvCryScore: TextView
    private lateinit var tvFps: TextView
    private lateinit var trendView: SimpleTrendView

    // MESSAGE
    private lateinit var tvAlertSummary: TextView
    private lateinit var tvAlertHistory: TextView
    private lateinit var btnClearAlertHistory: Button

    private var commandTicker: Runnable? = null
    private var isActivityAlive = true
    private var currentHost = RaspbotProtocol.CLOUD_CONNECTION_LABEL

    // Command state
    private var currentAction = "stop"
    private var servoAngle1 = 90
    private var servoAngle2 = 90
    private var speed = 80
    private var speakerVolume = 80
    private var speakerVolumeDirty = true
    private var audioPlaying = false
    private var trackingMode = false
    private var applyingHost = false

    // Settings
    private var voicePromptEnabled = true

    // Alerts
    private val alertHistory = ArrayDeque<String>()
    private var alertCount = 0
    private var lastAlarmSignature = ""

    // Trends
    private val trendDistance = ArrayDeque<TrendSample>()
    private val trendTemp = ArrayDeque<TrendSample>()
    private val trendLight = ArrayDeque<TrendSample>()

    private lateinit var webRtcClient: RaspbotWebRtcClient
    private lateinit var connectionClient: RaspbotConnectionClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)

        bindViews()
        setupConnectionClients()
        applySystemBars()
        createNotificationChannel()
        requestNotificationPermissionIfNeeded()
        loadSavedSettings()
        setupControls()
        applySettingsToUi()
        showPage(Page.HOME)

        if (currentHost.isBlank()) {
            updateConnectionStatus("请输入连接地址")
        } else {
            reconnectAll()
        }
    }

    override fun onStop() {
        super.onStop()
        sendAction("stop")
    }

    override fun onDestroy() {
        isActivityAlive = false
        sendAction("stop")
        mainHandler.removeCallbacksAndMessages(null)
        stopCommandTicker()

        webRtcClient.close()
        connectionClient.shutdown()

        super.onDestroy()
    }

    private fun bindViews() {
        // Pages
        pageHome = findViewById(R.id.pageHome)
        pageControl = findViewById(R.id.pageControl)
        pageMonitor = findViewById(R.id.pageMonitor)
        pageMessage = findViewById(R.id.pageMessage)
        pageMine = findViewById(R.id.pageMine)

        // Nav
        tvPageTitle = findViewById(R.id.tvPageTitle)
        btnTabHome = findViewById(R.id.btnTabHome)
        btnTabControl = findViewById(R.id.btnTabControl)
        btnTabMonitor = findViewById(R.id.btnTabMonitor)
        btnTabMessage = findViewById(R.id.btnTabMessage)
        btnTabMine = findViewById(R.id.btnTabMine)

        // Mode
        btnManualMode = findViewById(R.id.btnManualMode)
        btnAutoMode = findViewById(R.id.btnAutoMode)

        // Controls
        directionPad = findViewById(R.id.directionPad)
        seekSpeed = findViewById(R.id.seekSpeed)
        seekServo1 = findViewById(R.id.seekServo1)
        seekServo2 = findViewById(R.id.seekServo2)
        seekSpeakerVolume = findViewById(R.id.seekSpeakerVolume)
        tvSpeedVal = findViewById(R.id.tvSpeedVal)
        tvServo1 = findViewById(R.id.tvServo1)
        tvServo2 = findViewById(R.id.tvServo2)
        tvSpeakerVolume = findViewById(R.id.tvSpeakerVolume)
        btnServoCenter = findViewById(R.id.btnServoCenter)
        btnStop = findViewById(R.id.btnStop)
        btnAudioToggle = findViewById(R.id.btnAudioToggle)

        // Mine
        etHost = findViewById(R.id.etHost)
        btnApplyHost = findViewById(R.id.btnApplyHost)
        swVoicePrompt = findViewById(R.id.swVoicePrompt)
        swTrackingMode = findViewById(R.id.swTrackingMode)

        // Video
        commonVideoCard = findViewById(R.id.commonVideoCard)
        rtcVideo = findViewById(R.id.rtcVideo)
        imgVideoFrame = findViewById(R.id.imgVideoFrame)
        tvVideoStatus = findViewById(R.id.tvVideoStatus)

        // HOME
        tvConnection = findViewById(R.id.tvConnection)
        tvHostDisplay = findViewById(R.id.tvHostDisplay)
        cardAlertSummary = findViewById(R.id.cardAlertSummary)
        tvAlertLabel = findViewById(R.id.tvAlertLabel)
        tvAlertCount = findViewById(R.id.tvAlertCount)
        tvHomeDistance = findViewById(R.id.tvHomeDistance)
        tvHomeTemp = findViewById(R.id.tvHomeTemp)
        tvHomeSmoke = findViewById(R.id.tvHomeSmoke)
        tvHomeLight = findViewById(R.id.tvHomeLight)
        layoutAlarmBanner = findViewById(R.id.layoutAlarmBanner)
        tvAlarmText = findViewById(R.id.tvAlarmText)
        tvAlarmCount = findViewById(R.id.tvAlarmCount)

        // MONITOR
        tvTemp = findViewById(R.id.tvTemp)
        tvLightLux = findViewById(R.id.tvLightLux)
        tvSmoke = findViewById(R.id.tvSmoke)
        tvDistance = findViewById(R.id.tvDistance)
        tvVolume = findViewById(R.id.tvVolume)
        tvCry = findViewById(R.id.tvCry)
        tvCryScore = findViewById(R.id.tvCryScore)
        tvFps = findViewById(R.id.tvFps)
        trendView = findViewById(R.id.trendView)

        // MESSAGE
        tvAlertSummary = findViewById(R.id.tvAlertSummary)
        tvAlertHistory = findViewById(R.id.tvAlertHistory)
        btnClearAlertHistory = findViewById(R.id.btnClearAlertHistory)
    }

    private fun setupConnectionClients() {
        connectionClient = RaspbotConnectionClient(
            mainHandler = mainHandler,
            callbacks = object : RaspbotConnectionClient.Callbacks {
                override fun isAlive(): Boolean = isActivityAlive

                override fun isApplyingHost(): Boolean = applyingHost

                override fun onConnecting() {
                    updateConnectionStatus("连接中...")
                    updateVideoStatus("连接中")
                }

                override fun onOpen(usingCloudSignaling: Boolean) {
                    applyingHost = false
                    updateConnectionStatus("● 在线")
                    updateVideoStatus("等待视频流")
                    if (usingCloudSignaling) {
                        mainHandler.post {
                            webRtcClient.setup()
                            webRtcClient.start()
                        }
                    }
                    startCommandTicker()
                }

                override fun onText(text: String) {
                    handleTextMessage(text)
                }

                override fun onVideoFrame(jpeg: ByteArray) {
                    handleVideoFrame(jpeg)
                }

                override fun onEnvJson(json: String) {
                    handleEnvJson(json)
                }

                override fun onClosed() {
                    updateConnectionStatus("已断开")
                    updateVideoStatus("连接断开")
                }

                override fun onFailure(message: String) {
                    updateConnectionStatus("连接失败: $message")
                    updateVideoStatus("无连接")
                }
            }
        )
        webRtcClient = RaspbotWebRtcClient(
            context = this,
            videoView = rtcVideo,
            signalingSender = { text -> connectionClient.sendSignaling(text) },
            callbacks = object : RaspbotWebRtcClient.Callbacks {
                override fun onStatus(text: String) {
                    updateVideoStatus(text)
                }

                override fun onRemoteVideo() {
                    mainHandler.post {
                        imgVideoFrame.visibility = View.GONE
                        rtcVideo.visibility = View.VISIBLE
                        updateVideoStatus("WebRTC视频")
                    }
                }

                override fun onEnvJson(json: String) {
                    handleEnvJson(json)
                }

                override fun onCommandChannelOpen() {
                    sendCommand()
                }

                override fun isSignalingConnected(): Boolean {
                    return connectionClient.isConnected()
                }
            }
        )
    }

    private fun applySystemBars() {
        val root = findViewById<LinearLayout>(R.id.rootLayout)
        window.statusBarColor = Color.parseColor("#0D0D12")
        window.navigationBarColor = Color.parseColor("#12121A")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            root.setOnApplyWindowInsetsListener { view, insets ->
                view.setPadding(
                    view.paddingLeft,
                    insets.systemWindowInsetTop + dpInt(8),
                    view.paddingRight,
                    view.paddingBottom
                )
                insets
            }
            root.requestApplyInsets()
        } else {
            root.setPadding(root.paddingLeft, dpInt(32), root.paddingRight, root.paddingBottom)
        }
    }

    private fun loadSavedSettings() {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        currentHost = normalizeConnectionTarget(prefs.getString(KEY_HOST, RaspbotProtocol.CLOUD_CONNECTION_LABEL).orEmpty())
        voicePromptEnabled = prefs.getBoolean(KEY_VOICE_PROMPT, true)
        trackingMode = prefs.getBoolean(KEY_TRACKING_MODE, false)
        speakerVolume = prefs.getInt(KEY_SPEAKER_VOLUME, 80)
    }

    private fun saveHost(host: String) {
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_HOST, host)
            .apply()
    }

    private fun saveVoicePrompt(value: Boolean) {
        voicePromptEnabled = value
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_VOICE_PROMPT, value)
            .apply()
    }

    private fun saveTrackingMode(value: Boolean) {
        trackingMode = value
        currentAction = "stop"
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_TRACKING_MODE, value)
            .apply()
        sendCommand()
    }

    private fun saveSpeakerVolume(value: Int) {
        speakerVolume = value.coerceIn(0, 100)
        speakerVolumeDirty = true
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putInt(KEY_SPEAKER_VOLUME, speakerVolume)
            .apply()
        sendCommand()
    }

    private fun setupControls() {
        etHost.setText(displayConnectionTarget(currentHost))
        tvHostDisplay.text = displayConnectionTarget(currentHost)
        btnApplyHost.setOnClickListener { applyHostFromInput() }
        etHost.setOnEditorActionListener { _, _, _ ->
            applyHostFromInput()
            true
        }

        // Speed
        seekSpeed.max = 255
        seekSpeed.progress = speed
        tvSpeedVal.text = speed.toString()
        seekSpeed.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                speed = progress
                tvSpeedVal.text = speed.toString()
                if (fromUser) sendCommand()
            }
            override fun onStartTrackingTouch(sb: SeekBar?) = Unit
            override fun onStopTrackingTouch(sb: SeekBar?) { sendCommand() }
        })

        seekSpeakerVolume.max = 100
        seekSpeakerVolume.progress = speakerVolume
        tvSpeakerVolume.text = "$speakerVolume%"
        seekSpeakerVolume.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                speakerVolume = progress.coerceIn(0, 100)
                tvSpeakerVolume.text = "$speakerVolume%"
                if (fromUser) sendCommand()
            }
            override fun onStartTrackingTouch(sb: SeekBar?) = Unit
            override fun onStopTrackingTouch(sb: SeekBar?) { saveSpeakerVolume(speakerVolume) }
        })

        // Camera servo controls
        seekServo1.max = 180
        seekServo2.max = 180
        seekServo1.progress = servoAngle1
        seekServo2.progress = servoAngle2
        tvServo1.text = "${servoAngle1}°"
        tvServo2.text = "${servoAngle2}°"
        seekServo1.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                servoAngle1 = progress
                tvServo1.text = "${servoAngle1}°"
                if (fromUser) sendCommand()
            }
            override fun onStartTrackingTouch(sb: SeekBar?) = Unit
            override fun onStopTrackingTouch(sb: SeekBar?) { sendCommand() }
        })
        seekServo2.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                servoAngle2 = progress
                tvServo2.text = "${servoAngle2}°"
                if (fromUser) sendCommand()
            }
            override fun onStartTrackingTouch(sb: SeekBar?) = Unit
            override fun onStopTrackingTouch(sb: SeekBar?) { sendCommand() }
        })
        btnServoCenter.setOnClickListener {
            servoAngle1 = 90
            servoAngle2 = 90
            seekServo1.progress = servoAngle1
            seekServo2.progress = servoAngle2
            tvServo1.text = "${servoAngle1}°"
            tvServo2.text = "${servoAngle2}°"
            sendCommand()
        }

        // Direction pad
        directionPad.setOnDirectionActionListener { action ->
            sendAction(action)
        }

        // Emergency stop
        btnStop.setOnClickListener { sendAction("stop") }
        btnAudioToggle.setOnClickListener {
            if (audioPlaying) {
                sendAudioCommand(playSong = "", stopAudio = true)
            } else {
                sendAudioCommand(playSong = "default", stopAudio = false)
            }
        }

        // Mode toggle
        btnManualMode.setOnClickListener {
            if (swTrackingMode.isChecked) swTrackingMode.isChecked = false
        }
        btnAutoMode.setOnClickListener {
            if (!swTrackingMode.isChecked) swTrackingMode.isChecked = true
        }

        // Navigation
        btnTabHome.setOnClickListener { showPage(Page.HOME) }
        btnTabControl.setOnClickListener { showPage(Page.CONTROL) }
        btnTabMonitor.setOnClickListener { showPage(Page.MONITOR) }
        btnTabMessage.setOnClickListener { showPage(Page.MESSAGE) }
        btnTabMine.setOnClickListener { showPage(Page.MINE) }
        val openAlerts = View.OnClickListener { showPage(Page.MESSAGE) }
        cardAlertSummary.setOnClickListener(openAlerts)
        tvAlertLabel.setOnClickListener(openAlerts)
        tvAlertCount.setOnClickListener(openAlerts)
        layoutAlarmBanner.setOnClickListener(openAlerts)
        tvAlarmText.setOnClickListener(openAlerts)
        tvAlarmCount.setOnClickListener(openAlerts)

        // Switches
        swVoicePrompt.setOnCheckedChangeListener { _, isChecked ->
            saveVoicePrompt(isChecked)
        }
        swTrackingMode.setOnCheckedChangeListener { _, isChecked ->
            saveTrackingMode(isChecked)
            updateModeButtons()
        }

        // Clear alerts
        btnClearAlertHistory.setOnClickListener {
            alertHistory.clear()
            alertCount = 0
            lastAlarmSignature = ""
            tvAlertHistory.text = "-"
            tvAlertSummary.text = "0"
            tvAlarmCount.text = "0条"
            updateAlertBanner()
        }
    }

    private fun applySettingsToUi() {
        swVoicePrompt.isChecked = voicePromptEnabled
        swTrackingMode.isChecked = trackingMode
        updateModeButtons()
    }

    private fun updateModeButtons() {
        if (trackingMode) {
            btnAutoMode.setBackgroundResource(R.drawable.bg_chip_selected_dark)
            btnAutoMode.setTextColor(Color.parseColor("#F0ECE4"))
            btnManualMode.setBackgroundResource(R.drawable.bg_chip_default)
            btnManualMode.setTextColor(Color.parseColor("#F0ECE4"))
        } else {
            btnManualMode.setBackgroundResource(R.drawable.bg_chip_selected_dark)
            btnManualMode.setTextColor(Color.parseColor("#F0ECE4"))
            btnAutoMode.setBackgroundResource(R.drawable.bg_chip_default)
            btnAutoMode.setTextColor(Color.parseColor("#F0ECE4"))
        }
    }

    private fun showPage(page: Page) {
        pageHome.visibility = if (page == Page.HOME) View.VISIBLE else View.GONE
        pageControl.visibility = if (page == Page.CONTROL) View.VISIBLE else View.GONE
        pageMonitor.visibility = if (page == Page.MONITOR) View.VISIBLE else View.GONE
        pageMessage.visibility = if (page == Page.MESSAGE) View.VISIBLE else View.GONE
        pageMine.visibility = if (page == Page.MINE) View.VISIBLE else View.GONE
        commonVideoCard.visibility = if (page == Page.HOME || page == Page.CONTROL || page == Page.MONITOR) {
            View.VISIBLE
        } else {
            View.GONE
        }

        val titles = mapOf(
            Page.HOME to "首页", Page.CONTROL to "控制",
            Page.MONITOR to "监控", Page.MESSAGE to "消息", Page.MINE to "设置"
        )
        tvPageTitle.text = titles[page] ?: "首页"

        val navButtons = mapOf(
            Page.HOME to btnTabHome, Page.CONTROL to btnTabControl,
            Page.MONITOR to btnTabMonitor, Page.MESSAGE to btnTabMessage,
            Page.MINE to btnTabMine
        )
        for ((p, btn) in navButtons) {
            btn.setTextColor(if (p == page) Color.parseColor("#D4A574") else Color.parseColor("#706858"))
        }
    }

    private fun sendAction(action: String) {
        if (trackingMode && action != "stop") {
            swTrackingMode.isChecked = false
        }
        currentAction = action
        sendCommand()
    }

    private fun sendVoiceCommand(command: String) {
        val msg = JsonObject().apply {
            addProperty("type", RaspbotProtocol.TYPE_APP_VOICE)
            addProperty("source", "app")
            addProperty("text", command)
            addProperty("command", command)
        }
        if (sendTextPayload(gson.toJson(msg))) {
            if (voicePromptEnabled) {
                Toast.makeText(this, "已发送: $command", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun sendAudioCommand(playSong: String, stopAudio: Boolean) {
        val obj = JsonObject().apply {
            addProperty("source", "app")
            addProperty("action", "stop")
            addProperty("servo_angle", servoAngle1)
            addProperty("servo_angle2", servoAngle2)
            addProperty("speed", 0)
            addProperty("left_speed", 0)
            addProperty("right_speed", 0)
            addProperty("audio_volume", speakerVolume)
            if (playSong.isNotBlank()) addProperty("play_song", playSong)
            addProperty("stop_audio", stopAudio)
        }
        sendJsonCommand(gson.toJson(obj))
        audioPlaying = !stopAudio
        updateAudioButton()
        Toast.makeText(this, if (stopAudio) "已停止播放" else "已播放儿歌", Toast.LENGTH_SHORT).show()
    }

    private fun updateAudioButton() {
        if (audioPlaying) {
            btnAudioToggle.text = "停止播放"
            btnAudioToggle.setBackgroundResource(R.drawable.bg_audio_card_active)
            btnAudioToggle.setTextColor(Color.parseColor("#F0ECE4"))
        } else {
            btnAudioToggle.text = "播放儿歌"
            btnAudioToggle.setBackgroundResource(R.drawable.bg_chip_selected_dark)
            btnAudioToggle.setTextColor(Color.parseColor("#F0ECE4"))
        }
    }

    private fun applyHostFromInput() {
        val host = normalizeConnectionTarget(etHost.text.toString())
        currentHost = host
        saveHost(host)
        val display = displayConnectionTarget(host)
        etHost.setText(display)
        tvHostDisplay.text = display
        applyingHost = true
        reconnectAll()
    }

    private fun sendCommand() {
        if (trackingMode && !speakerVolumeDirty) {
            return
        }
        sendJsonCommand(buildJsonCommand())
    }

    private fun sendJsonCommand(cmd: String) {
        val cmdBytes = cmd.toByteArray(StandardCharsets.UTF_8)
        val payload = ByteArray(1 + cmdBytes.size)
        payload[0] = RaspbotProtocol.APP_CMD_PREFIX
        System.arraycopy(cmdBytes, 0, payload, 1, payload.size - 1)

        if (connectionClient.usingCloudSignaling) {
            if (webRtcClient.isCommandChannelOpen()) {
                webRtcClient.sendCommandJson(cmd)
            }
        } else if (connectionClient.isConnected()) {
            connectionClient.sendBinary(payload)
        } else if (webRtcClient.isCommandChannelOpen()) {
            webRtcClient.sendCommandJson(cmd)
        }
    }

    private fun buildJsonCommand(): String {
        val obj = JsonObject()
        if (!trackingMode) {
            obj.addProperty("source", "app")
        }
        obj.addProperty("action", currentAction)
        obj.addProperty("servo_angle", servoAngle1)
        obj.addProperty("servo_angle2", servoAngle2)
        obj.addProperty("speed", speed)
        if (speakerVolumeDirty) {
            obj.addProperty("audio_volume", speakerVolume)
            speakerVolumeDirty = false
        }
        obj.addProperty("tracking_mode", trackingMode)
        obj.addProperty("left_speed", speed)
        obj.addProperty("right_speed", speed)
        return gson.toJson(obj)
    }

    private var sendCommandRunnable: Runnable? = null

    private fun startCommandTicker() {
        stopCommandTicker()
        sendCommandRunnable = object : Runnable {
            override fun run() {
                if (!isActivityAlive) return
                sendCommand()
                mainHandler.postDelayed(this, CMD_SEND_INTERVAL_MS)
            }
        }
        mainHandler.post(sendCommandRunnable!!)
    }

    private fun stopCommandTicker() {
        sendCommandRunnable?.let { mainHandler.removeCallbacks(it) }
        sendCommandRunnable = null
    }

    private fun sendTextPayload(text: String): Boolean {
        if (webRtcClient.sendText(text)) {
            return true
        }
        if (connectionClient.sendText(text)) {
            return true
        }
        return false
    }

    private fun updateConnectionStatus(text: String) {
        mainHandler.post {
            tvConnection.text = text
        }
    }

    private fun reconnectAll() {
        speakerVolumeDirty = true
        webRtcClient.close()
        connectionClient.reconnect(currentHost)
    }

    private fun handleVideoFrame(jpeg: ByteArray) {
        val bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size) ?: return
        mainHandler.post {
            imgVideoFrame.visibility = View.VISIBLE
            rtcVideo.visibility = View.GONE
            imgVideoFrame.setImageBitmap(bitmap)
            tvVideoStatus.text = "视频流"
        }
    }

    private fun updateVideoStatus(text: String) {
        mainHandler.post {
            if (::tvVideoStatus.isInitialized) {
                tvVideoStatus.text = text
            }
        }
    }

    private fun handleTextMessage(text: String) {
        try {
            val obj = JsonParser.parseString(text).asJsonObject
            when (obj.get("type")?.asString) {
                RaspbotProtocol.TYPE_WEBRTC_ANSWER -> {
                    Log.d(TAG, "WebRTC answer received")
                    webRtcClient.handleAnswer(obj)
                }
                RaspbotProtocol.TYPE_WEBRTC_ICE -> {
                    Log.d(TAG, "WebRTC ice received")
                    webRtcClient.handleIce(obj)
                }
                "ping", "join", "joined" -> Unit
                else -> handleEnvJson(text)
            }
        } catch (_: Exception) {
            handleEnvJson(text)
        }
    }

    private fun appendTrendSample(series: ArrayDeque<TrendSample>, value: Float, nowMs: Long) {
        series.addLast(TrendSample(nowMs, value))
        pruneTrendSamples(series, nowMs)
    }

    private fun pruneTrendSamples(series: ArrayDeque<TrendSample>, nowMs: Long) {
        val oldestAllowed = nowMs - TREND_WINDOW_MS
        while (series.isNotEmpty() && series.first().timestampMs < oldestAllowed) {
            series.removeFirst()
        }
    }

    private fun downsampleTrend(series: ArrayDeque<TrendSample>, nowMs: Long): List<Float> {
        pruneTrendSamples(series, nowMs)
        if (series.size <= TREND_RENDER_POINTS) {
            return series.map { it.value }
        }
        val samples = series.toList()
        val bucketSize = (samples.size + TREND_RENDER_POINTS - 1) / TREND_RENDER_POINTS
        val result = ArrayList<Float>(TREND_RENDER_POINTS)
        var index = 0
        while (index < samples.size) {
            val end = minOf(index + bucketSize, samples.size)
            var sum = 0f
            for (i in index until end) sum += samples[i].value
            result.add(sum / (end - index))
            index = end
        }
        return result
    }

    private fun handleEnvJson(json: String) {
        try {
            val obj = JsonParser.parseString(json).asJsonObject
            val nowMs = System.currentTimeMillis()

            // temperature
            val temp = asFloatOrNull(obj.get("temp_c"))
            if (temp != null) {
                mainHandler.post {
                    tvTemp.text = "${String.format("%.1f", temp)}"
                    tvHomeTemp.text = "${temp.toInt()}°"
                }
                appendTrendSample(trendTemp, temp, nowMs)
                mainHandler.post { updateTrendChart() }
            }

            // light
            val lux = asIntOrNull(obj.get("light_lux"))
            if (lux != null) {
                mainHandler.post {
                    tvLightLux.text = lux.toString()
                    tvHomeLight.text = lux.toString()
                }
                appendTrendSample(trendLight, lux.toFloat(), nowMs)
                mainHandler.post { updateTrendChart() }
            }

            // smoke
            val smoke = asIntOrNull(obj.get("smoke"))
            if (smoke != null) {
                mainHandler.post {
                    tvSmoke.text = smoke.toString()
                    tvHomeSmoke.text = if (smoke > AlarmPolicy.SMOKE_ALARM_LEVEL) "异常" else smoke.toString()
                    tvHomeSmoke.setTextColor(if (smoke > AlarmPolicy.SMOKE_ALARM_LEVEL) Color.parseColor("#C9A84A") else Color.parseColor("#F0ECE4"))
                }
            }

            // distance
            val dist = asFloatOrNull(obj.get("dist_cm"))
            if (dist != null) {
                mainHandler.post {
                    tvDistance.text = "${dist.toInt()}cm"
                    tvHomeDistance.text = dist.toInt().toString()
                }
                appendTrendSample(trendDistance, dist, nowMs)
                mainHandler.post { updateTrendChart() }
            }

            // YL-40 AIN3 knob, not speaker dB.
            val volume = asIntOrNull(obj.get("volume"))
            if (volume != null) {
                mainHandler.post { tvVolume.text = "音量 ${volume}%" }
            }

            // crying
            val crying = asBooleanOrNull(obj.get("crying"))
            val cryScore = asIntOrNull(obj.get("cry_score"))
            if (crying != null) {
                mainHandler.post {
                    tvCry.text = if (crying) "检测" else "正常"
                    tvCry.setTextColor(if (crying) Color.parseColor("#D45A5A") else Color.parseColor("#7AB88A"))
                }
            }
            if (cryScore != null) {
                mainHandler.post { tvCryScore.text = "哭声概率 $cryScore%" }
            }

            // fps
            val fps = asIntOrNull(obj.get("fps"))
            if (fps != null) {
                mainHandler.post {
                    tvFps.text = "帧率 ${fps}fps"
                    tvVideoStatus.text = "${fps} fps"
                }
            }

            // alarm
            val alarm = AlarmPolicy.buildAlarmMessage(obj, dist, smoke, temp, lux, crying, cryScore)
            if (!alarm.isNullOrBlank()) {
                recordAlarm(alarm)
            } else {
                lastAlarmSignature = ""
            }

        } catch (_: Exception) { }
    }

    private fun recordAlarm(alarm: String) {
        if (alarm == lastAlarmSignature) return
        lastAlarmSignature = alarm
        val time = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        val entry = "[$time] $alarm"
        alertHistory.addLast(entry)
        if (alertHistory.size > MAX_ALERT_HISTORY) alertHistory.removeFirst()
        alertCount++
        mainHandler.post {
            updateAlertBanner()
            tvAlertSummary.text = alertCount.toString()
            tvAlertHistory.text = alertHistory.joinToString("\n")
            showAlertNotification(alarm)
        }
    }

    private fun updateAlertBanner() {
        if (alertCount > 0) {
            layoutAlarmBanner.visibility = View.VISIBLE
            tvAlarmText.text = "有 $alertCount 条报警"
            tvAlertCount.text = "${alertCount}条"
            tvAlarmCount.text = "${alertCount}条"
            tvAlertCount.setTextColor(Color.parseColor("#D45A5A"))
        } else {
            layoutAlarmBanner.visibility = View.GONE
        }
    }

    private fun updateTrendChart() {
        val nowMs = System.currentTimeMillis()
        trendView.setSeries(
            downsampleTrend(trendDistance, nowMs),
            downsampleTrend(trendTemp, nowMs),
            downsampleTrend(trendLight, nowMs)
        )
    }

    private fun dpInt(value: Int): Int {
        return (value * resources.displayMetrics.density).toInt()
    }

    // Notifications --------------------------------------------------

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                NOTIFICATION_CHANNEL_ID, NOTIFICATION_CHANNEL_NAME,
                NotificationManager.IMPORTANCE_HIGH
            ).apply { description = "Raspbot alarm notifications" }
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
            }
        }
    }

    private fun showAlertNotification(message: String) {
        try {
            val notification = NotificationCompat.Builder(this, NOTIFICATION_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setContentTitle("Raspbot 报警")
                .setContentText(message)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .build()
            if (ActivityCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
                NotificationManagerCompat.from(this).notify(NOTIFICATION_REQUEST_CODE, notification)
            }
        } catch (_: Exception) {}
    }
}
