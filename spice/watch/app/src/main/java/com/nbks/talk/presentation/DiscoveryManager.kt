package com.nbks.talk.presentation

import android.content.Context
import android.net.wifi.WifiManager
import android.util.Log
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

object TalkAssistConstants {
    const val BROADCAST_PORT = 5000
}

class DiscoveryManager(
    context: Context,
    private val onFound: (server: String, sessionId: String) -> Unit
) {
    private val appContext = context.applicationContext
    private var socket: DatagramSocket? = null
    private var thread: Thread? = null
    private var multicastLock: WifiManager.MulticastLock? = null
    @Volatile
    private var running = false

    fun start() {
        stop()
        running = true
        try {
            val wifi = appContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            multicastLock = wifi?.createMulticastLock("TalkAssist")?.apply {
                setReferenceCounted(true)
                acquire()
            }
        } catch (_: Exception) {
        }
        thread = Thread {
            try {
                val sock = DatagramSocket(TalkAssistConstants.BROADCAST_PORT, InetAddress.getByName("0.0.0.0")).apply {
                    broadcast = true
                    reuseAddress = true
                }
                socket = sock
                Log.d("DiscoveryManager", "listening on port ${TalkAssistConstants.BROADCAST_PORT}")
                val buffer = ByteArray(2048)
                while (running) {
                    val packet = DatagramPacket(buffer, buffer.size)
                    try {
                        sock.receive(packet)
                    } catch (_: Exception) {
                        if (!running) break
                        continue
                    }
                    val msg = String(packet.data, 0, packet.length, Charsets.UTF_8)
                    try {
                        val json = JSONObject(msg)
                        val server = json.optString("server")
                        val sessionId = json.optString("session_id")
                        if (server.isNotEmpty() && sessionId.isNotEmpty()) {
                            Log.d("DiscoveryManager", "found server=$server session=$sessionId")
                            onFound(server, sessionId)
                        }
                    } catch (_: Exception) {
                    }
                }
            } catch (e: Exception) {
                Log.e("DiscoveryManager", "listen error: $e")
            }
        }.apply { start() }
    }

    fun stop() {
        running = false
        try {
            socket?.close()
        } catch (_: Exception) {
        }
        thread?.join(500)
        socket = null
        thread = null
        try {
            multicastLock?.release()
        } catch (_: Exception) {
        }
        multicastLock = null
    }
}
