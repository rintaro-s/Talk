package com.nbks.talk.presentation

import android.util.Log
import kotlinx.coroutines.*
import okhttp3.*
import org.json.JSONObject

class TalkAssistClient(
    private val url: String,
    private val onStatusChange: (String) -> Unit,
    private val onPartial: (String) -> Unit,
    private val onFinal: (String) -> Unit,
    private val onPresentationNav: (JSONObject) -> Unit,
    private val onError: (String) -> Unit
) {
    private val client: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(20, java.util.concurrent.TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    fun connect() {
        close()
        val request = Request.Builder().url(url).build()
        onStatusChange("接続中...")
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                onStatusChange("接続済み")
            }

            override fun onMessage(ws: WebSocket, text: String) {
                try {
                    val json = JSONObject(text)
                    when (json.optString("type")) {
                        "ready" -> onStatusChange("認識準備完了")
                        "partial" -> onPartial(json.optString("text", ""))
                        "final" -> onFinal(json.optString("text", ""))
                        "transcript" -> onStatusChange("${json.optString("speaker")}: 送信済み")
                        "presentation_nav" -> onPresentationNav(json)
                        "error" -> onError(json.optString("message", "不明なエラー"))
                        "pong" -> { /* no-op */ }
                    }
                } catch (e: Exception) {
                    Log.w("TalkAssistClient", "parse error: $e")
                }
            }

            override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                onStatusChange("切断中")
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                onStatusChange("未接続")
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                onStatusChange("接続エラー")
                onError(t.message ?: "WebSocket error")
            }
        })
    }

    fun sendStart(model: String = "small") {
        val json = JSONObject().apply {
            put("type", "start")
            put("model", model)
        }
        webSocket?.send(json.toString())
    }

    fun sendAudio(base64Pcm: String) {
        val json = JSONObject().apply {
            put("type", "audio")
            put("data", base64Pcm)
        }
        webSocket?.send(json.toString())
    }

    fun sendStop() {
        val json = JSONObject().apply {
            put("type", "stop")
        }
        webSocket?.send(json.toString())
    }

    fun close() {
        webSocket?.close(1000, "closed by client")
        webSocket = null
    }
}
