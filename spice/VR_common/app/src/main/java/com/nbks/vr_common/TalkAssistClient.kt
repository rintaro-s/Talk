package com.nbks.vr_common

import android.util.Log
import okhttp3.*
import org.json.JSONObject

class TalkAssistClient(
    private val url: String,
    private val onStatusChange: (String) -> Unit,
    private val onMessage: (JSONObject) -> Unit,
    private val onError: (String) -> Unit
) {
    private val client: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(20, java.util.concurrent.TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null

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
                    onMessage(json)
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

    fun sendPing() {
        webSocket?.send("""{"type":"ping"}""")
    }

    fun close() {
        webSocket?.close(1000, "closed by client")
        webSocket = null
    }
}
