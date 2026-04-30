package com.example.raspbotapp.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.sqrt

class DirectionPadView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    private val outerPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#08FFFFFF")
        style = Paint.Style.FILL
    }

    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#10FFFFFF")
        style = Paint.Style.STROKE
        strokeWidth = dp(1f)
    }

    private val centerPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#D4A574")
        style = Paint.Style.FILL
    }

    private val knobPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#E8C39A")
        style = Paint.Style.FILL
    }

    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#A09888")
        textAlign = Paint.Align.CENTER
        textSize = dp(11f)
        isFakeBoldText = true
    }

    private var lastAction = "stop"
    private var knobX = 0f
    private var knobY = 0f
    private var callback: ((String) -> Unit)? = null

    fun setOnDirectionActionListener(listener: (String) -> Unit) {
        callback = listener
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val cx = width / 2f
        val cy = height / 2f
        val radius = min(width, height) * 0.48f
        val travelRadius = radius * 0.48f
        val knobRadius = radius * 0.26f

        if (knobX == 0f && knobY == 0f) {
            knobX = cx
            knobY = cy
        }

        canvas.drawCircle(cx, cy, radius, outerPaint)
        canvas.drawCircle(cx, cy, radius, ringPaint)
        canvas.drawCircle(cx, cy, travelRadius, ringPaint)
        canvas.drawLine(cx - radius * 0.72f, cy, cx + radius * 0.72f, cy, ringPaint)
        canvas.drawLine(cx, cy - radius * 0.72f, cx, cy + radius * 0.72f, ringPaint)

        val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            shader = RadialGradient(
                knobX,
                knobY,
                knobRadius * 2.8f,
                Color.parseColor("#33D4A574"),
                Color.TRANSPARENT,
                Shader.TileMode.CLAMP
            )
        }
        canvas.drawCircle(knobX, knobY, knobRadius * 2.8f, glowPaint)
        canvas.drawCircle(knobX, knobY, knobRadius, knobPaint)
        canvas.drawCircle(knobX, knobY, knobRadius * 0.45f, centerPaint)

        canvas.drawText("摇杆", cx, cy + radius * 0.82f, labelPaint)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> {
                parent?.requestDisallowInterceptTouchEvent(true)
                updateKnob(event.x, event.y)
                val action = resolveAction()
                emitAction(action)
                return true
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                parent?.requestDisallowInterceptTouchEvent(false)
                centerKnob()
                emitAction("stop")
                performClick()
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    override fun performClick(): Boolean = super.performClick()

    private fun updateKnob(x: Float, y: Float) {
        val cx = width / 2f
        val cy = height / 2f
        val dx = x - cx
        val dy = y - cy
        val radius = min(width, height) * 0.48f * 0.7f
        val distance = sqrt(dx * dx + dy * dy)
        val scale = if (distance > radius && distance > 0f) radius / distance else 1f
        knobX = cx + dx * scale
        knobY = cy + dy * scale
        invalidate()
    }

    private fun centerKnob() {
        knobX = width / 2f
        knobY = height / 2f
        invalidate()
    }

    private fun resolveAction(): String {
        val cx = width / 2f
        val cy = height / 2f
        val dx = knobX - cx
        val dy = knobY - cy
        val radius = min(width, height) * 0.48f
        val distance = sqrt(dx * dx + dy * dy)

        if (distance < radius * 0.12f) return "stop"
        return if (abs(dy) >= abs(dx) * 0.55f) {
            if (dy > 0) "backward" else "forward"
        } else {
            if (dx > 0) "right" else "left"
        }
    }

    private fun emitAction(action: String) {
        if (action == lastAction) return
        lastAction = action
        callback?.invoke(action)
    }

    private fun dp(value: Float): Float = value * resources.displayMetrics.density
}
