package com.nbks.talk.presentation

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.core.content.ContextCompat
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.AppScaffold
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.wear.compose.ui.tooling.preview.WearPreviewDevices
import androidx.wear.compose.ui.tooling.preview.WearPreviewFontScales
import com.nbks.talk.presentation.theme.TalkTheme
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

class MainActivity : ComponentActivity() {

    private lateinit var audioRecorder: AudioRecorder
    private var client: TalkAssistClient? = null
    private var discovery: DiscoveryManager? = null

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (!isGranted) {
            AppState.errorMessage.value = "マイク権限が必要です"
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)

        audioRecorder = AudioRecorder()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }

        discovery = DiscoveryManager(this) { srv, sid ->
            AppState.discoveredMap[srv] = sid
            AppState.discoveredItems.value = AppState.discoveredMap.toList()
        }
        AppState.isDiscovering.value = true

        setContent {
            TalkTheme {
                WearApp(
                    onConnect = { server, session -> connect(server, session) },
                    onStartRecording = { startRecording() },
                    onStopRecording = { stopRecording() },
                    onDisconnect = { disconnect() },
                    onStartDiscovery = { discovery?.start(); AppState.isDiscovering.value = true },
                    onStopDiscovery = { discovery?.stop(); AppState.isDiscovering.value = false }
                )
            }
        }
    }

    private fun connect(server: String, sessionId: String) {
        disconnect()
        discovery?.stop()
        AppState.isDiscovering.value = false
        val url = if (server.endsWith("/")) server.dropLast(1) else server
        val wsUrl = "$url/ws/session/$sessionId?device=watch"
        client = TalkAssistClient(
            url = wsUrl,
            onStatusChange = { status -> runOnUiThread { AppState.connectionStatus.value = status } },
            onPartial = { text -> runOnUiThread { AppState.partialText.value = text } },
            onFinal = { text -> runOnUiThread { AppState.finalText.value = text } },
            onPresentationNav = { json -> runOnUiThread { AppState.presentationNav.value = json } },
            onError = { msg -> runOnUiThread { AppState.errorMessage.value = msg } }
        )
        client?.connect()
    }

    private fun startRecording() {
        client?.let { c ->
            audioRecorder.start { pcm ->
                c.sendAudio(android.util.Base64.encodeToString(pcm, android.util.Base64.NO_WRAP))
            }
            c.sendStart()
            AppState.isRecording.value = true
        }
    }

    private fun stopRecording() {
        audioRecorder.stop()
        client?.sendStop()
        AppState.isRecording.value = false
    }

    private fun disconnect() {
        stopRecording()
        client?.close()
        client = null
        AppState.connectionStatus.value = "未接続"
    }

    override fun onDestroy() {
        super.onDestroy()
        disconnect()
        discovery?.stop()
    }
}

object AppState {
    val connectionStatus = mutableStateOf("未接続")
    val partialText = mutableStateOf("")
    val finalText = mutableStateOf("")
    val errorMessage = mutableStateOf("")
    val isRecording = mutableStateOf(false)
    val isDiscovering = mutableStateOf(false)
    val discoveredMap = ConcurrentHashMap<String, String>()
    val discoveredItems = mutableStateOf(listOf<Pair<String, String>>())
    val discoveredServer = mutableStateOf("")
    val discoveredSessionId = mutableStateOf("")
    val presentationNav = mutableStateOf<JSONObject?>(null)
}

private fun parseConnectionUrl(input: String): Pair<String, String>? {
    val trimmed = input.trim()
    if (trimmed.isEmpty()) return null
    val regex = Regex("""^(wss?://[^/]+)/ws/session/([a-zA-Z0-9_-]+)""")
    val match = regex.find(trimmed)
    if (match != null) {
        return match.groupValues[1] to match.groupValues[2]
    }
    val parts = trimmed.split("/").filter { it.isNotEmpty() }
    val sessionId = parts.lastOrNull { it.isNotEmpty() }
    val server = trimmed.substringBeforeLast("/ws/session", "")
    if (server.isNotEmpty() && sessionId != null) {
        return server to sessionId
    }
    return null
}

@Composable
fun WearApp(
    onConnect: (String, String) -> Unit,
    onStartRecording: () -> Unit,
    onStopRecording: () -> Unit,
    onDisconnect: () -> Unit,
    onStartDiscovery: () -> Unit,
    onStopDiscovery: () -> Unit
) {
    var server by AppState.discoveredServer
    var sessionId by AppState.discoveredSessionId
    var manualExpanded by remember { mutableStateOf(false) }
    var manualUrl by remember { mutableStateOf("") }

    val connectionStatus by AppState.connectionStatus
    val partialText by AppState.partialText
    val finalText by AppState.finalText
    val errorMessage by AppState.errorMessage
    val isRecording by AppState.isRecording
    val isDiscovering by AppState.isDiscovering
    val discoveredItems by AppState.discoveredItems
    val presentationNav by AppState.presentationNav

    LaunchedEffect(isDiscovering) {
        if (isDiscovering) onStartDiscovery() else onStopDiscovery()
    }

    val isConnected = connectionStatus == "接続済み" || connectionStatus == "認識準備完了"

    AppScaffold {
        val listState = rememberTransformingLazyColumnState()
        val transformationSpec = rememberTransformationSpec()
        ScreenScaffold(scrollState = listState) { contentPadding ->
            TransformingLazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = contentPadding,
                state = listState,
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                item {
                    ListHeader(
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, transformationSpec),
                        transformation = SurfaceTransformation(transformationSpec)
                    ) {
                        Text(text = "TalkAssist")
                    }
                }

                item {
                    StatusLine(connectionStatus, errorMessage)
                }

                if (!isConnected) {
                    item {
                        DiscoverySection(
                            isDiscovering = isDiscovering,
                            discoveredItems = discoveredItems,
                            onToggleDiscovery = {
                                AppState.isDiscovering.value = !isDiscovering
                            },
                            onSelect = { srv, sid ->
                                server = srv
                                sessionId = sid
                                onConnect(srv, sid)
                            },
                            manualExpanded = manualExpanded,
                            onToggleManual = { manualExpanded = !manualExpanded },
                            manualUrl = manualUrl,
                            onManualUrlChange = { manualUrl = it },
                            onManualConnect = {
                                parseConnectionUrl(manualUrl)?.let { (srv, sid) ->
                                    server = srv
                                    sessionId = sid
                                    onConnect(srv, sid)
                                }
                            }
                        )
                    }
                } else {
                    item {
                        RecordingControls(
                            isRecording = isRecording,
                            onToggle = { if (isRecording) onStopRecording() else onStartRecording() },
                            onDisconnect = onDisconnect
                        )
                    }

                    if (partialText.isNotEmpty() || finalText.isNotEmpty()) {
                        item {
                            RecognitionText(partialText, finalText)
                        }
                    }

                    presentationNav?.let { nav ->
                        val currentSlide = nav.optString("current_slide", "")
                        val nextScript = nav.optString("next_script", "")
                        val missingArray = nav.optJSONArray("missing")
                        if (currentSlide.isNotEmpty()) {
                            item { InfoTile("スライド", currentSlide) }
                        }
                        if (nextScript.isNotEmpty()) {
                            item { InfoTile("次", nextScript) }
                        }
                        missingArray?.let { arr ->
                            val missing = (0 until arr.length()).map { arr.optString(it) }.filter { it.isNotEmpty() }
                            if (missing.isNotEmpty()) {
                                item { InfoTile("漏れ", missing.joinToString(", ")) }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun StatusLine(status: String, error: String) {
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp)) {
        Text(
            text = status,
            modifier = Modifier.fillMaxWidth(),
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.primary
        )
        if (error.isNotEmpty()) {
            Text(
                text = error,
                modifier = Modifier.fillMaxWidth(),
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.error
            )
        }
    }
}

@Composable
fun DiscoverySection(
    isDiscovering: Boolean,
    discoveredItems: List<Pair<String, String>>,
    onToggleDiscovery: () -> Unit,
    onSelect: (String, String) -> Unit,
    manualExpanded: Boolean,
    onToggleManual: () -> Unit,
    manualUrl: String,
    onManualUrlChange: (String) -> Unit,
    onManualConnect: () -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
        Button(
            onClick = onToggleDiscovery,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text(if (isDiscovering) "検出を停止" else "サーバーを検出")
        }

        if (isDiscovering && discoveredItems.isEmpty()) {
            Text(
                text = "検出中...",
                modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        discoveredItems.forEachIndexed { index, (srv, sid) ->
            Button(
                onClick = { onSelect(srv, sid) },
                modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)
            ) {
                Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("接続 ${index + 1}", style = MaterialTheme.typography.bodySmall)
                    Text(sid, style = MaterialTheme.typography.bodySmall)
                }
            }
        }

        Button(
            onClick = onToggleManual,
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp)
        ) {
            Text(if (manualExpanded) "手動入力を閉じる" else "手動で接続")
        }

        if (manualExpanded) {
            Spacer(modifier = Modifier.height(4.dp))
            BasicTextField(
                value = manualUrl,
                onValueChange = onManualUrlChange,
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                decorationBox = { innerTextField ->
                    Box(modifier = Modifier.fillMaxWidth()) {
                        if (manualUrl.isEmpty()) {
                            Text(
                                text = "ws://.../ws/session/ID",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                        innerTextField()
                    }
                }
            )
            Button(
                onClick = onManualConnect,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("接続")
            }
        }
    }
}

@Composable
fun RecordingControls(
    isRecording: Boolean,
    onToggle: () -> Unit,
    onDisconnect: () -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
        Button(
            onClick = onToggle,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text(if (isRecording) "録音停止" else "録音開始")
        }
        Button(
            onClick = onDisconnect,
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp)
        ) {
            Text("切断")
        }
    }
}

@Composable
fun RecognitionText(partial: String, final: String) {
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp)) {
        if (partial.isNotEmpty()) {
            Text(
                text = "認識中: $partial",
                modifier = Modifier.fillMaxWidth(),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        if (final.isNotEmpty()) {
            Text(
                text = "確定: $final",
                modifier = Modifier.fillMaxWidth(),
                style = MaterialTheme.typography.bodySmall
            )
        }
    }
}

@Composable
fun InfoTile(title: String, body: String) {
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 2.dp)) {
        Text(
            text = title,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.primary
        )
        Text(
            text = body,
            style = MaterialTheme.typography.bodySmall
        )
    }
}

@WearPreviewDevices
@WearPreviewFontScales
@Composable
fun DefaultPreview() {
    TalkTheme {
        WearApp(
            onConnect = { _, _ -> },
            onStartRecording = {},
            onStopRecording = {},
            onDisconnect = {},
            onStartDiscovery = {},
            onStopDiscovery = {}
        )
    }
}
