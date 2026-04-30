package com.example.raspbotapp.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.view.View
import kotlin.math.max
import kotlin.math.min

class SimpleTrendView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#10FFFFFF")
        style = Paint.Style.STROKE
        strokeWidth = dp(1f)
    }

    private val distancePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#D4A574")
        style = Paint.Style.STROKE
        strokeWidth = dp(2f)
    }

    private val tempPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#7AB88A")
        style = Paint.Style.STROKE
        strokeWidth = dp(2f)
    }

    private val lightPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#C9A84A")
        style = Paint.Style.STROKE
        strokeWidth = dp(2f)
    }

    private val legendPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#706858")
        textSize = dp(10f)
    }

    private var distanceSeries: List<Float> = emptyList()
    private var tempSeries: List<Float> = emptyList()
    private var lightSeries: List<Float> = emptyList()

    fun setSeries(distance: List<Float>, temp: List<Float>, light: List<Float>) {
        distanceSeries = distance
        tempSeries = temp
        lightSeries = light
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0f || h <= 0f) return

        val left = dp(8f)
        val top = dp(8f)
        val right = w - dp(8f)
        val bottom = h - dp(16f)
        val drawW = right - left
        val drawH = bottom - top
        if (drawW <= 0f || drawH <= 0f) return

        canvas.drawRect(left, top, right, bottom, gridPaint)
        canvas.drawLine(left, top + drawH / 2f, right, top + drawH / 2f, gridPaint)

        val distance = if (distanceSeries.size >= 2) distanceSeries else listOf(42f, 38f, 44f, 31f, 36f, 28f, 34f)
        val temp = if (tempSeries.size >= 2) tempSeries else listOf(25f, 26f, 25.5f, 27f, 26.4f, 26.8f, 26.1f)
        val light = if (lightSeries.size >= 2) lightSeries else listOf(410f, 460f, 430f, 520f, 480f, 500f, 470f)

        drawSeries(canvas, distance, distancePaint, left, top, drawW, drawH, 0f, 200f)
        drawSeries(canvas, temp, tempPaint, left, top, drawW, drawH, 0f, 50f)
        drawSeries(canvas, light, lightPaint, left, top, drawW, drawH, 0f, 1000f)

        val legendY = h - dp(3f)
        canvas.drawText("Dist", left, legendY, legendPaint.apply { color = distancePaint.color })
        canvas.drawText("Temp", left + dp(42f), legendY, legendPaint.apply { color = tempPaint.color })
        canvas.drawText("Light", left + dp(86f), legendY, legendPaint.apply { color = lightPaint.color })
    }

    private fun drawSeries(
        canvas: Canvas,
        series: List<Float>,
        paint: Paint,
        left: Float,
        top: Float,
        drawW: Float,
        drawH: Float,
        minVal: Float,
        maxVal: Float
    ) {
        if (series.size < 2) return

        val span = (maxVal - minVal).takeIf { it > 0.0001f } ?: 1f
        val lastIndex = (series.size - 1).toFloat()
        val path = Path()
        series.forEachIndexed { index, value ->
            val x = left + (index / lastIndex) * drawW
            val clamped = min(max(value, minVal), maxVal)
            val normalized = (clamped - minVal) / span
            val y = top + (1f - normalized) * drawH
            if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        canvas.drawPath(path, paint)
    }

    private fun dp(value: Float): Float = value * resources.displayMetrics.density
}
