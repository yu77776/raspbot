package com.example.raspbotapp.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
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
        color = Color.parseColor("#4DB6FF")
        style = Paint.Style.STROKE
        strokeWidth = dp(2.4f)
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }

    private val tempPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#FF6B6B")
        style = Paint.Style.STROKE
        strokeWidth = dp(2.4f)
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }

    private val lightPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#F6C945")
        style = Paint.Style.STROKE
        strokeWidth = dp(2.4f)
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        pathEffect = DashPathEffect(floatArrayOf(dp(6f), dp(4f)), 0f)
    }

    private val legendDistancePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = distancePaint.color
        textSize = dp(10f)
    }
    private val legendTempPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = tempPaint.color
        textSize = dp(10f)
    }
    private val legendLightPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = lightPaint.color
        textSize = dp(10f)
    }
    private val noDataPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#50A09888")
        textSize = dp(12f)
        textAlign = Paint.Align.CENTER
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

        val hasData = distanceSeries.size >= 2 || tempSeries.size >= 2 || lightSeries.size >= 2
        if (!hasData) {
            canvas.drawText("等待遥测数据…", left + drawW / 2f, top + drawH / 2f, noDataPaint)
            return
        }

        drawSeries(canvas, distanceSeries, distancePaint, left, top, drawW, drawH, 0f, 200f)
        drawSeries(canvas, tempSeries, tempPaint, left, top, drawW, drawH, 0f, 50f)
        drawSeries(canvas, lightSeries, lightPaint, left, top, drawW, drawH, 0f, 1000f)

        val legendY = h - dp(3f)
        canvas.drawText("距离", left, legendY, legendDistancePaint)
        canvas.drawText("温度", left + dp(42f), legendY, legendTempPaint)
        canvas.drawText("光照", left + dp(86f), legendY, legendLightPaint)
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
