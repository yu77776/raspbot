package com.example.raspbotapp

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import com.example.raspbotapp.ui.DirectionPadView
import com.example.raspbotapp.ui.SimpleTrendView
import com.example.raspbotapp.AlarmPolicy.asBooleanOrNull
import com.example.raspbotapp.AlarmPolicy.asFloatOrNull
import com.example.raspbotapp.AlarmPolicy.asIntOrNull
import com.example.raspbotapp.AlarmPolicy.asStringOrNull
import com.example.raspbotapp.AlarmPolicy.addAuthToken
import com.example.raspbotapp.AlarmPolicy.buildAlertDetails
import com.example.raspbotapp.AlarmPolicy.buildBatteryDisplay
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import org.webrtc.SurfaceViewRenderer
import java.util.ArrayDeque
import java.util.concurrent.Executors
import kotlin.math.abs

class MainActivity : AppCompatActivity() {
    companion object {
        private const val PREFS_NAME = "raspbot_settings"
        private const val KEY_HOST = "host"
        private const val KEY_VOICE_PROMPT = "voice_prompt"
        private const val KEY_TRACKING_MODE = "tracking_mode"
        private const val KEY_SPEAKER_VOLUME = "speaker_volume"

        private const val CMD_SEND_INTERVAL_MS = 100L

        private const val TREND_WINDOW_MS = 5 * 60 * 1000L
        private const val TREND_RENDER_POINTS = 72
        private const val TAG = "RaspbotApp"

        private const val PLAY_SONG_NEXT = "__next__"
        private const val PLAY_SONG_PREV = "__prev__"
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
    private lateinit var layoutAutoTrackingPanel: LinearLayout
    private lateinit var layoutManualControls: LinearLayout
    private lateinit var tvTrackingModeStatus: TextView

    // Controls
    private lateinit var directionPad: DirectionPadView
    private lateinit var seekSpeed: SeekBar
    private lateinit var seekServo1: SeekBar
    private lateinit var seekServo2: SeekBar
    private lateinit var seekSpeakerVolume: SeekBar
    private lateinit var tvSpeedVal: TextView
    private lateinit var tvServo1: TextView
    private lateinit var tvServo2: TextView
    private lateinit var tvManualDistance: TextView
    private lateinit var tvSpeakerVolume: TextView
    private lateinit var btnServoCenter: Button
    private lateinit var btnStop: Button
    private lateinit var btnAudioToggle: Button
    private lateinit var btnAudioPrev: Button
    private lateinit var btnAudioNext: Button

    // Mine
    private lateinit var swVoicePrompt: Switch
    private lateinit var swTrackingMode: Switch

    // Video
    private lateinit var commonVideoCard: View
    private lateinit var rtcVideo: SurfaceViewRenderer
    private lateinit var imgVideoFrame: ImageView
    private lateinit var tvVideoStatus: TextView
    private lateinit var btnVideoReconnect: ImageButton

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
    private lateinit var tvCareSummary: TextView
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
    private lateinit var tvBattery: TextView
    private lateinit var trendView: SimpleTrendView

    // MESSAGE
    private lateinit var tvAlertSummary: TextView
    private lateinit var layoutAlarmCardList: LinearLayout
    private lateinit var btnClearAlertHistory: Button

    private lateinit var ossImageLoader: OssImageLoader

    private val executor = Executors.newFixedThreadPool(2)

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
    private var speakerVolumeDragging = false
    private var speakerVolumeNeedsInitialCarSync = true
    private var audioPlaying = false
    private var trackingMode = true
    private var applyingHost = false
    private var videoFrameReceived = false

    // Settings
    private var voicePromptEnabled = true

    // Alerts
    private val alarmEvents = mutableListOf<AlarmEvent>()
    private var expandedCardIndex = -1
    private var alertCount = 0
    private var unreadAlertCount = 0
    private var lastAlarmSignature = ""
    private var lastAlarmAtMs = 0L
    private var lastRecordedAlarmAtMs = 0L
    private var latestAlarmText = ""

    // Trends
    private val trendDistance = ArrayDeque<TrendSample>()
    private val trendTemp = ArrayDeque<TrendSample>()
    private val trendLight = ArrayDeque<TrendSample>()
    private val trendSmoke = ArrayDeque<TrendSample>()
    private val trendLock = Any()

    // Cached env display values to skip redundant UI posts
    @Volatile private var lastDispTemp: Float = Float.NaN
    @Volatile private var lastDispLux: Int = -1
    @Volatile private var lastDispSmoke: Int = -1
    @Volatile private var lastDispDist: Int = -1
    @Volatile private var lastDispVolume: Int = -1
    @Volatile private var lastDispCrying: Boolean? = null
    @Volatile private var lastDispFps: Int = -1
    @Volatile private var lastDispBattery: String = ""
    @Volatile private var lastSafetySummary: String = ""
    @Volatile private var lastSafetyCryScore: Int? = null
    @Volatile private var lastCareSummary: String = ""
    @Volatile private var lastCareHasAlarm: Boolean = false

    private lateinit var webRtcClient: RaspbotWebRtcClient
    private lateinit var connectionClient: RaspbotConnectionClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)

        bindViews()
        tvConnection.text = "未连接"
        tvVideoStatus.text = "未连接"
        setupConnectionClients()
        ossImageLoader = OssImageLoader(signalSender = { json -> connectionClient.sendSignaling(json) })
        applySystemBars()
        AlarmNotifier.createChannel(this)
        requestNotificationPermissionIfNeeded()
        loadSavedSettings()
        setupControls()
        applySettingsToUi()
        loadAlertHistory()
        showPage(Page.HOME)

        if (currentHost.isBlank()) {
            updateConnectionStatus("请输入连接地址")
        } else {
            reconnectAll()
        }
    }

    override fun onStart() {
        super.onStart()
        stopService(Intent(this, RaspbotAlarmService::class.java))
        loadAlertHistory()
    }

    override fun onStop() {
        super.onStop()
        sendAction("stop")
        startBackgroundAlarmService()
    }

    override fun onDestroy() {
        isActivityAlive = false
        sendAction("stop")
        mainHandler.removeCallbacksAndMessages(null)
        stopCommandTicker()

        webRtcClient.close()
        connectionClient.shutdown()
        executor.shutdownNow()

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
        layoutAutoTrackingPanel = findViewById(R.id.layoutAutoTrackingPanel)
        layoutManualControls = findViewById(R.id.layoutManualControls)
        tvTrackingModeStatus = findViewById(R.id.tvTrackingModeStatus)

        // Controls
        directionPad = findViewById(R.id.directionPad)
        seekSpeed = findViewById(R.id.seekSpeed)
        seekServo1 = findViewById(R.id.seekServo1)
        seekServo2 = findViewById(R.id.seekServo2)
        seekSpeakerVolume = findViewById(R.id.seekSpeakerVolume)
        tvSpeedVal = findViewById(R.id.tvSpeedVal)
        tvServo1 = findViewById(R.id.tvServo1)
        tvServo2 = findViewById(R.id.tvServo2)
        tvManualDistance = findViewById(R.id.tvManualDistance)
        tvSpeakerVolume = findViewById(R.id.tvSpeakerVolume)
        btnServoCenter = findViewById(R.id.btnServoCenter)
        btnStop = findViewById(R.id.btnStop)
        btnAudioToggle = findViewById(R.id.btnAudioToggle)
        btnAudioPrev = findViewById(R.id.btnAudioPrev)
        btnAudioNext = findViewById(R.id.btnAudioNext)

        // Mine
        swVoicePrompt = findViewById(R.id.swVoicePrompt)
        swTrackingMode = findViewById(R.id.swTrackingMode)

        // Video
        commonVideoCard = findViewById(R.id.commonVideoCard)
        rtcVideo = findViewById(R.id.rtcVideo)
        imgVideoFrame = findViewById(R.id.imgVideoFrame)
        tvVideoStatus = findViewById(R.id.tvVideoStatus)
        btnVideoReconnect = findViewById(R.id.btnVideoReconnect)

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
        tvCareSummary = findViewById(R.id.tvCareSummary)
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
        tvBattery = findViewById(R.id.tvBattery)
        trendView = findViewById(R.id.trendView)

        // MESSAGE
        tvAlertSummary = findViewById(R.id.tvAlertSummary)
        layoutAlarmCardList = findViewById(R.id.layoutAlarmCardList)
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

                override fun onOpen() {
                    applyingHost = false
                    videoFrameReceived = false
                    updateConnectionStatus("信令已连接")
                    updateVideoStatus("等待视频流")
                    mainHandler.post {
                        webRtcClient.setup()
                        webRtcClient.start()
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
                    if (!videoFrameReceived) {
                        videoFrameReceived = true
                        updateConnectionStatus("● 在线")
                    }
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
                    sendCommand(force = true)
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
        currentHost = RaspbotProtocol.CLOUD_CONNECTION_LABEL
        voicePromptEnabled = prefs.getBoolean(KEY_VOICE_PROMPT, true)
        trackingMode = prefs.getBoolean(KEY_TRACKING_MODE, true)
        speakerVolume = prefs.getInt(KEY_SPEAKER_VOLUME, 80)
        prefs.edit().putString(KEY_HOST, currentHost).apply()
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
        syncTrackingModeUi()
        sendCommand(force = true)
    }

    private fun saveSpeakerVolume(value: Int) {
        speakerVolume = value.coerceIn(0, 100)
        speakerVolumeDirty = true
        updateSpeakerVolumeUi()
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putInt(KEY_SPEAKER_VOLUME, speakerVolume)
            .apply()
        sendCommand()
    }

    private fun syncSpeakerVolumeFromCar(value: Int) {
        if (!speakerVolumeNeedsInitialCarSync) return
        if (speakerVolumeDragging) return
        val newVolume = value.coerceIn(0, 100)
        speakerVolumeNeedsInitialCarSync = false
        if (newVolume == speakerVolume) return
        speakerVolume = newVolume
        speakerVolumeDirty = false
        updateSpeakerVolumeUi()
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putInt(KEY_SPEAKER_VOLUME, newVolume)
            .apply()
    }

    private fun updateSpeakerVolumeUi() {
        if (::seekSpeakerVolume.isInitialized && seekSpeakerVolume.progress != speakerVolume) {
            seekSpeakerVolume.progress = speakerVolume
        }
        if (::tvSpeakerVolume.isInitialized) {
            tvSpeakerVolume.text = "$speakerVolume%"
        }
        if (::tvVolume.isInitialized) {
            tvVolume.text = "音量 ${speakerVolume}%"
        }
    }

    private fun setupControls() {
        tvHostDisplay.text = RaspbotProtocol.CLOUD_CONNECTION_LABEL
        btnVideoReconnect.setOnClickListener {
            reconnectVideoManually()
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
        updateSpeakerVolumeUi()
        seekSpeakerVolume.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                speakerVolume = progress.coerceIn(0, 100)
                updateSpeakerVolumeUi()
                if (fromUser) {
                    speakerVolumeDirty = true
                    speakerVolumeNeedsInitialCarSync = false
                    sendCommand()
                }
            }
            override fun onStartTrackingTouch(sb: SeekBar?) {
                speakerVolumeDragging = true
            }
            override fun onStopTrackingTouch(sb: SeekBar?) {
                speakerVolumeDragging = false
                saveSpeakerVolume(speakerVolume)
            }
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
        btnAudioPrev.setOnClickListener { sendAudioCommand(playSong = PLAY_SONG_PREV, stopAudio = false) }
        btnAudioNext.setOnClickListener { sendAudioCommand(playSong = PLAY_SONG_NEXT, stopAudio = false) }

        // Mode toggle
        btnManualMode.setOnClickListener {
            saveTrackingMode(false)
        }
        btnAutoMode.setOnClickListener {
            saveTrackingMode(true)
        }

        // Navigation
        btnTabHome.setOnClickListener { showPage(Page.HOME) }
        btnTabControl.setOnClickListener { showPage(Page.CONTROL) }
        btnTabMonitor.setOnClickListener { showPage(Page.MONITOR) }
        btnTabMessage.setOnClickListener { showPage(Page.MESSAGE) }
        btnTabMine.setOnClickListener { showPage(Page.MINE) }
        val openAlerts = View.OnClickListener {
            acknowledgeHomeAlerts()
            showPage(Page.MESSAGE)
        }
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
            if (isChecked != trackingMode) {
                saveTrackingMode(isChecked)
            }
        }

        // Clear alerts
        btnClearAlertHistory.setOnClickListener {
            alarmEvents.clear()
            expandedCardIndex = -1
            alertCount = 0
            unreadAlertCount = 0
            AlarmEventStore.clear(this)
            lastAlarmSignature = ""
            lastAlarmAtMs = 0L
            lastRecordedAlarmAtMs = 0L
            latestAlarmText = ""
            layoutAlarmCardList.removeAllViews()
            tvAlertSummary.text = "0"
            tvAlarmCount.text = "0条"
            tvAlertCount.text = "0"
            tvAlertCount.setTextColor(Color.parseColor("#706858"))
            updateCareSummary(null, null, null, null, null)
            updateAlertBanner()
        }
    }

    private fun loadAlertHistory() {
        val events = AlarmEventStore.load(this)
        alarmEvents.clear()
        alarmEvents.addAll(events)
        alertCount = events.size
        unreadAlertCount = 0
        layoutAlarmCardList.removeAllViews()
        tvAlertSummary.text = alertCount.toString()
        if (events.isEmpty()) {
            latestAlarmText = ""
            lastAlarmAtMs = 0L
            lastRecordedAlarmAtMs = 0L
        } else {
            val latest = events.last()
            latestAlarmText = latest.alarm
            lastAlarmAtMs = latest.timeMs
            lastRecordedAlarmAtMs = latest.timeMs
        }
        for (event in events) {
            addAlarmCard(event)
        }
        updateAlertBanner()
    }

    private fun addAlarmCard(event: AlarmEvent) {
        val card = layoutInflater.inflate(R.layout.alarm_card_item, layoutAlarmCardList, false)
        val headerRow = card.findViewById<LinearLayout>(R.id.cardHeader)
        val dotView = card.findViewById<View>(R.id.dotAlarmType)
        val titleView = card.findViewById<TextView>(R.id.tvCardAlarmTitle)
        val timeView = card.findViewById<TextView>(R.id.tvCardAlarmTime)
        val detailArea = card.findViewById<LinearLayout>(R.id.cardDetail)
        val imgSnapshot = card.findViewById<ImageView>(R.id.imgCardSnapshot)
        val snapshotHint = card.findViewById<TextView>(R.id.tvCardSnapshotHint)
        val detailsView = card.findViewById<TextView>(R.id.tvCardDetails)

        val alarmColor = alarmTypeColor(event.alarm)
        dotView.background = android.graphics.drawable.GradientDrawable().apply {
            shape = android.graphics.drawable.GradientDrawable.OVAL
            setColor(alarmColor)
        }
        titleView.text = event.alarm
        timeView.text = event.timeText
        detailsView.text = event.details.ifBlank { "已记录报警" }

        card.tag = CardViewHolder(event, dotView, titleView, timeView, detailArea, imgSnapshot, snapshotHint, detailsView)
        headerRow.setOnClickListener { toggleCard(card) }
        layoutAlarmCardList.addView(card, 0)
    }

    private data class CardViewHolder(
        val event: AlarmEvent,
        val dotView: View,
        val titleView: TextView,
        val timeView: TextView,
        val detailArea: LinearLayout,
        val imgSnapshot: ImageView,
        val snapshotHint: TextView,
        val detailsView: TextView
    )

    private fun toggleCard(card: View) {
        val index = layoutAlarmCardList.indexOfChild(card)
        if (index < 0 || index >= layoutAlarmCardList.childCount) return
        val holder = card.tag as? CardViewHolder ?: return

        if (expandedCardIndex == index) {
            // Collapse
            holder.detailArea.visibility = View.GONE
            expandedCardIndex = -1
            return
        }
        // Collapse previously expanded card
        if (expandedCardIndex >= 0 && expandedCardIndex < layoutAlarmCardList.childCount) {
            val prevCard = layoutAlarmCardList.getChildAt(expandedCardIndex)
            val prevHolder = prevCard?.tag as? CardViewHolder
            prevHolder?.detailArea?.visibility = View.GONE
        }
        // Expand this card
        expandedCardIndex = index
        holder.detailArea.visibility = View.VISIBLE
        // Try to load cloud snapshot
        val snapshotKey = holder.event.snapshotKey
        if (snapshotKey != null && holder.imgSnapshot.drawable == null) {
            loadCardSnapshot(holder, snapshotKey)
        } else if (snapshotKey != null) {
            holder.imgSnapshot.visibility = View.VISIBLE
            holder.snapshotHint.visibility = View.GONE
        } else {
            // No preset key — search OSS by alarm type + time
            holder.snapshotHint.visibility = View.VISIBLE
            holder.snapshotHint.text = "正在查找云端快照..."
            try {
                executor.execute {
                    try {
                        val matched = ossImageLoader.findSnapshotForAlarm(
                            holder.event.alarm, holder.event.timeMs
                        )
                        mainHandler.post {
                            if (matched != null) {
                                loadCardSnapshot(holder, matched.key)
                            } else {
                                holder.snapshotHint.text = "暂无云端快照"
                            }
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "findSnapshotForAlarm failed", e)
                        mainHandler.post { holder.snapshotHint.text = "快照查找失败" }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "executor submit failed", e)
                holder.snapshotHint.text = "暂无云端快照"
            }
        }
    }

    private fun loadCardSnapshot(holder: CardViewHolder, key: String) {
        holder.snapshotHint.visibility = View.VISIBLE
        holder.snapshotHint.text = "云端快照加载中..."
        try {
            executor.execute {
                try {
                    val data = ossImageLoader.downloadImage(key)
                    mainHandler.post {
                        if (data != null) {
                            val bmp = BitmapFactory.decodeByteArray(data, 0, data.size)
                            holder.imgSnapshot.setImageBitmap(bmp)
                            holder.imgSnapshot.visibility = View.VISIBLE
                            holder.snapshotHint.visibility = View.GONE
                        } else {
                            holder.snapshotHint.text = "暂无云端快照"
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "downloadImage failed", e)
                    mainHandler.post { holder.snapshotHint.text = "快照加载失败" }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "executor submit failed", e)
            holder.snapshotHint.text = "暂无云端快照"
        }
    }

    private fun alarmTypeColor(alarm: String): Int {
        return when {
            alarm.contains("哭声") || alarm.contains("cry") -> Color.parseColor("#D45A5A")
            alarm.contains("烟雾") || alarm.contains("smoke") -> Color.parseColor("#D4844A")
            alarm.contains("悬崖") || alarm.contains("cliff") -> Color.parseColor("#D45A5A")
            alarm.contains("高温") || alarm.contains("temp_high") -> Color.parseColor("#D4844A")
            alarm.contains("低温") || alarm.contains("temp_low") -> Color.parseColor("#5A8AD4")
            alarm.contains("距离") || alarm.contains("close") -> Color.parseColor("#C9A84A")
            else -> Color.parseColor("#A09888")
        }
    }

    private fun applySettingsToUi() {
        swVoicePrompt.isChecked = voicePromptEnabled
        syncTrackingModeUi()
    }

    private fun syncTrackingModeUi() {
        if (::swTrackingMode.isInitialized && swTrackingMode.isChecked != trackingMode) {
            swTrackingMode.isChecked = trackingMode
        }
        updateModeButtons()
    }

    private fun updateModeButtons() {
        if (trackingMode) {
            btnAutoMode.setBackgroundResource(R.drawable.bg_chip_selected_dark)
            btnAutoMode.setTextColor(Color.parseColor("#F0ECE4"))
            btnManualMode.setBackgroundResource(R.drawable.bg_chip_default)
            btnManualMode.setTextColor(Color.parseColor("#A09888"))
        } else {
            btnManualMode.setBackgroundResource(R.drawable.bg_chip_selected_dark)
            btnManualMode.setTextColor(Color.parseColor("#F0ECE4"))
            btnAutoMode.setBackgroundResource(R.drawable.bg_chip_default)
            btnAutoMode.setTextColor(Color.parseColor("#A09888"))
        }
        layoutAutoTrackingPanel.visibility = if (trackingMode) View.VISIBLE else View.GONE
        layoutManualControls.visibility = if (trackingMode) View.GONE else View.VISIBLE
        updateControlStatusText()
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
            saveTrackingMode(false)
            Toast.makeText(this, "已切换到手动控制", Toast.LENGTH_SHORT).show()
        }
        currentAction = action
        sendCommand(force = true)
    }

    private fun sendAudioCommand(playSong: String, stopAudio: Boolean) {
        val obj = JsonObject().apply {
            addAuthToken(this)
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
        val sent = sendJsonCommand(gson.toJson(obj))
        audioPlaying = !stopAudio
        updateAudioButton()
        val text = if (!sent) {
            "控制通道未连接"
        } else when {
            stopAudio -> "已停止播放"
            playSong == PLAY_SONG_NEXT -> "已切到下一首"
            playSong == PLAY_SONG_PREV -> "已切到上一首"
            else -> "已播放儿歌"
        }
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show()
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

    private var lastSentCommandJson: String = ""
    private var lastSentCommandAtMs: Long = 0L

    private fun sendCommand(force: Boolean = false) {
        val hadSpeakerVolumeDirty = speakerVolumeDirty
        val cmd = buildJsonCommand(includeSpeakerVolume = hadSpeakerVolumeDirty)
        val nowMs = SystemClock.elapsedRealtime()
        if (!CommandSendPolicy.shouldSend(
                force = force,
                trackingMode = trackingMode,
                speakerVolumeDirty = hadSpeakerVolumeDirty,
                commandJson = cmd,
                lastCommandJson = lastSentCommandJson,
                action = currentAction,
                speed = speed,
                elapsedSinceLastSendMs = nowMs - lastSentCommandAtMs,
            )
        ) {
            return
        }
        if (sendJsonCommand(cmd)) {
            lastSentCommandJson = cmd
            lastSentCommandAtMs = nowMs
            if (hadSpeakerVolumeDirty) {
                speakerVolumeDirty = false
            }
        }
    }

    private fun sendJsonCommand(cmd: String): Boolean {
        return if (webRtcClient.isCommandChannelOpen()) {
            webRtcClient.sendCommandJson(cmd)
        } else {
            false
        }
    }

    private fun buildJsonCommand(includeSpeakerVolume: Boolean): String {
        val obj = JsonObject()
        addAuthToken(obj)
        obj.addProperty("source", if (trackingMode) "app_auto" else "app")
        obj.addProperty("action", currentAction)
        obj.addProperty("servo_angle", servoAngle1)
        obj.addProperty("servo_angle2", servoAngle2)
        obj.addProperty("speed", speed)
        if (includeSpeakerVolume) {
            obj.addProperty("audio_volume", speakerVolume)
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

    private fun updateConnectionStatus(text: String) {
        mainHandler.post {
            tvConnection.text = text
        }
    }

    private fun reconnectAll() {
        stopService(Intent(this, RaspbotAlarmService::class.java))
        speakerVolumeDirty = true
        speakerVolumeNeedsInitialCarSync = true
        currentHost = RaspbotProtocol.CLOUD_CONNECTION_LABEL
        imgVideoFrame.visibility = View.VISIBLE
        rtcVideo.visibility = View.GONE
        webRtcClient.close()
        connectionClient.reconnect(currentHost)
    }

    private fun reconnectVideoManually() {
        Toast.makeText(this, "正在重新连接视频", Toast.LENGTH_SHORT).show()
        updateConnectionStatus("重新连接中...")
        updateVideoStatus("重新连接中")
        reconnectAll()
    }

    private fun handleVideoFrame(jpeg: ByteArray) {
        val bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size) ?: return
        if (!videoFrameReceived) {
            videoFrameReceived = true
            updateConnectionStatus("● 在线")
        }
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
                "oss_list_result", "oss_download_result" -> {
                    val type = obj.get("type").asString
                    ossImageLoader.handleSignalResponse(type, obj)
                }
                "ping", "join", "joined" -> Unit
                else -> handleEnvJson(text)
            }
        } catch (_: Exception) {
            handleEnvJson(text)
        }
    }

    private fun appendTrendSample(series: ArrayDeque<TrendSample>, value: Float, nowMs: Long) {
        synchronized(trendLock) {
            series.addLast(TrendSample(nowMs, value))
            pruneTrendSamples(series, nowMs)
        }
    }

    private fun pruneTrendSamples(series: ArrayDeque<TrendSample>, nowMs: Long) {
        val oldestAllowed = nowMs - TREND_WINDOW_MS
        while (series.isNotEmpty() && series.first().timestampMs < oldestAllowed) {
            series.removeFirst()
        }
    }

    private fun downsampleTrend(series: ArrayDeque<TrendSample>, nowMs: Long): List<Float> {
        val samples = synchronized(trendLock) {
            pruneTrendSamples(series, nowMs)
            series.toList()
        }
        if (samples.size <= TREND_RENDER_POINTS) {
            return samples.map { it.value }
        }
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
            var trendChanged = false

            // temperature
            val temp = asFloatOrNull(obj.get("temp_c"))
            if (temp != null) {
                if (temp != lastDispTemp) {
                    lastDispTemp = temp
                    mainHandler.post {
                        tvTemp.text = "${String.format("%.1f", temp)}"
                        tvHomeTemp.text = "${temp.toInt()}°"
                    }
                }
                appendTrendSample(trendTemp, temp, nowMs)
                trendChanged = true
            }

            // light
            val lux = asIntOrNull(obj.get("light_lux"))
            if (lux != null) {
                if (lux != lastDispLux) {
                    lastDispLux = lux
                    mainHandler.post {
                        tvLightLux.text = lux.toString()
                        tvHomeLight.text = lux.toString()
                    }
                }
                appendTrendSample(trendLight, lux.toFloat(), nowMs)
                trendChanged = true
            }

            // smoke
            val smoke = asIntOrNull(obj.get("smoke"))
            if (smoke != null) {
                if (smoke != lastDispSmoke) {
                    lastDispSmoke = smoke
                    mainHandler.post {
                        tvSmoke.text = smoke.toString()
                        tvHomeSmoke.text = if (smoke > AlarmPolicy.SMOKE_ALARM_LEVEL) "异常" else smoke.toString()
                        tvHomeSmoke.setTextColor(if (smoke > AlarmPolicy.SMOKE_ALARM_LEVEL) Color.parseColor("#C9A84A") else Color.parseColor("#F0ECE4"))
                    }
                }
                appendTrendSample(trendSmoke, smoke.toFloat(), nowMs)
                trendChanged = true
            }

            // distance
            val dist = asFloatOrNull(obj.get("dist_cm"))
            if (dist != null) {
                val distInt = dist.toInt()
                if (distInt != lastDispDist) {
                    lastDispDist = distInt
                    mainHandler.post {
                        tvDistance.text = "${distInt}cm"
                        tvHomeDistance.text = distInt.toString()
                        updateManualDistance(distInt)
                    }
                }
                appendTrendSample(trendDistance, dist, nowMs)
                trendChanged = true
            }

            if (trendChanged) {
                mainHandler.post { updateTrendChart() }
            }

            // Car-side applied speaker volume.
            val volume = asIntOrNull(obj.get("volume"))
            if (volume != null && volume != lastDispVolume) {
                lastDispVolume = volume
                mainHandler.post {
                    syncSpeakerVolumeFromCar(volume)
                    updateSpeakerVolumeUi()
                }
            }

            // crying
            val crying = asBooleanOrNull(obj.get("crying"))
            val cryScore = asIntOrNull(obj.get("cry_score"))
            if (cryScore != null) {
                mainHandler.post {
                    tvCryScore.text = if (crying == true) {
                        "持续哭声 分数$cryScore"
                    } else {
                        "哭声分数 $cryScore"
                    }
                }
            }

            val batteryStatus = asStringOrNull(obj.get("battery_status"))
            val batteryDisplay = buildBatteryDisplay(batteryStatus)
            if (batteryDisplay != null && batteryDisplay != lastDispBattery) {
                lastDispBattery = batteryDisplay
                mainHandler.post {
                    tvBattery.text = batteryDisplay
                    tvBattery.setTextColor(
                        if (batteryStatus.equals("LOW", ignoreCase = true)) Color.parseColor("#D45A5A")
                        else Color.parseColor("#A09888")
                    )
                }
            }

            // fps
            val fps = asIntOrNull(obj.get("fps"))
            if (fps != null && fps != lastDispFps) {
                lastDispFps = fps
                mainHandler.post {
                    tvFps.text = "帧率 ${fps}fps"
                    tvVideoStatus.text = "${fps} fps"
                }
            }

            // alarm
            val alarm = AlarmPolicy.buildAlarmMessage(obj)
            updateSafetyStatus(alarm, crying, cryScore)
            if (!alarm.isNullOrBlank()) {
                recordAlarm(alarm, temp, dist, smoke, lux, crying, cryScore, batteryStatus)
            } else {
                lastAlarmSignature = ""
            }
            updateCareSummary(alarm, dist, temp, crying, cryScore)

        } catch (e: Exception) {
            Log.w(TAG, "handleEnvJson error", e)
        }
    }

    private fun updateSafetyStatus(alarm: String?, crying: Boolean?, cryScore: Int?) {
        val summary = if (alarm.isNullOrBlank()) "正常" else alarm
        if (summary == lastSafetySummary && crying == lastDispCrying && cryScore == lastSafetyCryScore) return
        lastSafetySummary = summary
        lastDispCrying = crying
        lastSafetyCryScore = cryScore
        val isAlarm = !alarm.isNullOrBlank()
        mainHandler.post {
            tvCry.text = summary
            tvCry.setTextColor(if (isAlarm) Color.parseColor("#D45A5A") else Color.parseColor("#7AB88A"))
            tvCryScore.text = when {
                crying == true && cryScore != null -> "持续哭声 分数$cryScore"
                cryScore != null -> "哭声分数 $cryScore"
                isAlarm -> "请查看报警详情"
                else -> "安全状态正常"
            }
            updateControlStatusText()
        }
    }

    private fun updateControlStatusText() {
        val safety = lastSafetySummary
        tvTrackingModeStatus.text = when {
            safety.isNotBlank() && safety != "正常" -> "安全警报：$safety"
            trackingMode -> "自动追踪运行中｜安全状态正常"
            else -> "手动控制｜安全状态正常"
        }
        tvTrackingModeStatus.setTextColor(
            if (safety.isNotBlank() && safety != "正常") Color.parseColor("#D45A5A")
            else Color.parseColor("#F0ECE4")
        )
    }

    private fun updateManualDistance(distCm: Int) {
        tvManualDistance.text = "${distCm}cm"
        tvManualDistance.setTextColor(
            when {
                distCm <= 5 -> Color.parseColor("#D45A5A")
                distCm <= 20 -> Color.parseColor("#C9A84A")
                else -> Color.parseColor("#F0ECE4")
            }
        )
    }

    private fun recordAlarm(
        alarm: String,
        temp: Float?,
        dist: Float?,
        smoke: Int?,
        lux: Int?,
        crying: Boolean?,
        cryScore: Int?,
        batteryStatus: String?
    ) {
        val nowMs = System.currentTimeMillis()
        lastAlarmSignature = alarm
        latestAlarmText = alarm
        val details = buildAlertDetails(temp, dist, smoke, lux, crying, cryScore, batteryStatus)
        val event = AlarmEventStore.appendIfAllowed(
            this, alarm, details, nowMs,
            temp = temp, dist = dist, smoke = smoke, lux = lux,
            crying = crying, cryScore = cryScore
        ) ?: return
        lastAlarmAtMs = nowMs
        lastRecordedAlarmAtMs = nowMs
        alarmEvents.add(0, event)
        if (alarmEvents.size > AlarmEventStore.MAX_ALERT_HISTORY) {
            alarmEvents.removeAt(alarmEvents.size - 1)
        }
        alertCount = alarmEvents.size
        unreadAlertCount++
        mainHandler.post {
            updateAlertBanner()
            tvAlertSummary.text = alertCount.toString()
            addAlarmCard(event)
            showAlertNotification(alarm)
        }
    }

    private fun updateCareSummary(
        alarm: String?,
        dist: Float?,
        temp: Float?,
        crying: Boolean?,
        cryScore: Int?
    ) {
        if (!::tvCareSummary.isInitialized) return
        val summary = buildCareSummary(alarm, dist, temp, crying, cryScore)
        val hasAlarm = !alarm.isNullOrBlank()
        if (summary == lastCareSummary && hasAlarm == lastCareHasAlarm) return
        lastCareSummary = summary
        lastCareHasAlarm = hasAlarm
        mainHandler.post {
            tvCareSummary.text = summary
            tvCareSummary.setTextColor(if (hasAlarm) Color.parseColor("#C9A84A") else Color.parseColor("#F0ECE4"))
        }
    }

    private fun buildCareSummary(
        alarm: String?,
        dist: Float?,
        temp: Float?,
        crying: Boolean?,
        cryScore: Int?
    ): String {
        if (!alarm.isNullOrBlank()) {
            return when {
                alarm.contains("检测到哭声") -> "检测到哭声，已启动安抚提醒"
                alarm.contains("室温偏高") -> "室温偏高，建议查看宝宝状态"
                alarm.contains("室温偏低") -> "室温偏低，建议查看宝宝状态"
                alarm.contains("光照不足") -> "光照不足，小车已保守跟随"
                alarm.contains("光照过强") -> "光照过强，小车已保守跟随"
                alarm.contains("光照变化") -> "光照变化明显，小车已暂停车身跟随"
                alarm.contains("距离过近") -> "距离偏近，小车会给宝宝留出空间"
                alarm.contains("电池") -> "小车供电偏低，建议检查电源"
                else -> alarm
            }
        }
        if (dist == null && temp == null && crying == null && cryScore == null) {
            return "等待小车环境数据"
        }
        val parts = ArrayList<String>()
        if (dist != null) parts.add("距离 ${dist.toInt()}cm")
        if (temp != null) parts.add("室温 ${String.format("%.1f", temp)}°C")
        if (crying == true || (cryScore != null && cryScore >= AlarmPolicy.CRY_ALARM_SCORE)) {
            parts.add("哭声需关注")
        } else if (cryScore != null && cryScore >= 40) {
            parts.add("宝宝可能有些烦躁")
        } else {
            parts.add("宝宝状态正常")
        }
        if (lastAlarmAtMs > 0 && System.currentTimeMillis() - lastAlarmAtMs < TREND_WINDOW_MS) {
            parts.add("5分钟内有提醒")
        } else {
            parts.add("5分钟内无报警")
        }
        return parts.joinToString("，")
    }

    private fun updateAlertBanner() {
        if (unreadAlertCount > 0) {
            layoutAlarmBanner.visibility = View.VISIBLE
            tvAlarmText.text = "有 $unreadAlertCount 条新报警"
            tvAlertCount.text = "${unreadAlertCount}条"
            tvAlarmCount.text = "${unreadAlertCount}条"
            tvAlertCount.setTextColor(Color.parseColor("#D45A5A"))
        } else {
            layoutAlarmBanner.visibility = View.GONE
            tvAlertCount.text = "0"
            tvAlarmCount.text = "0条"
            tvAlertCount.setTextColor(Color.parseColor("#706858"))
        }
    }

    private fun acknowledgeHomeAlerts() {
        if (unreadAlertCount <= 0) return
        unreadAlertCount = 0
        updateAlertBanner()
    }

    private fun updateTrendChart() {
        val nowMs = System.currentTimeMillis()
        trendView.setSeries(
            downsampleTrend(trendDistance, nowMs),
            downsampleTrend(trendTemp, nowMs),
            downsampleTrend(trendLight, nowMs),
            downsampleTrend(trendSmoke, nowMs)
        )
    }

    private fun dpInt(value: Int): Int {
        return (value * resources.displayMetrics.density).toInt()
    }

    // Notifications --------------------------------------------------

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
            }
        }
    }

    private fun showAlertNotification(message: String) {
        try {
            AlarmNotifier.showAlarm(this, message)
        } catch (_: Exception) {}
    }

    private fun startBackgroundAlarmService() {
        val intent = Intent(this, RaspbotAlarmService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }
}
