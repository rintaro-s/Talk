package com.nbks.talk.presentation

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text as M3Text
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.wear.compose.ui.tooling.preview.WearPreviewDevices
import androidx.wear.compose.ui.tooling.preview.WearPreviewFontScales
import com.nbks.talk.R
import com.nbks.talk.presentation.theme.TalkTheme

class MainActivity : ComponentActivity() {

    private lateinit var audioRecorder: AudioRecorder
    private var client: TalkAssistClient? = null

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (!isGranted) {
            // 権限がない場合は何もできない
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        audioRecorder = AudioRecorder()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }

        setContent {
            TalkTheme {
                WearApp(
                    onConnect = { server, session -> connect(server, session) },
                    onStartRecording = { startRecording() },
                    onStopRecording = { stopRecording() },
                    onDisconnect = { disconnect() }
                )
            }
        }
    }

    private fun connect(server: String, sessionId: String) {
        disconnect()
        val url = if (server.endsWith("/")) server.dropLast(1) else server
        val wsUrl = "$url/ws/session/$sessionId?device=watch"
        client = TalkAssistClient(
            url = wsUrl,
            onStatusChange = { status -> runOnUiThread { AppState.connectionStatus.value = status } },
            onPartial = { text -> runOnUiThread { AppState.partialText.value = text } },
            onFinal = { text -> runOnUiThread { AppState.finalText.value = text } },
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
    }

    override fun onDestroy() {
        super.onDestroy()
        disconnect()
    }
}

object AppState {
    val connectionStatus = mutableStateOf("未接続")
    val partialText = mutableStateOf("")
    val finalText = mutableStateOf("")
    val errorMessage = mutableStateOf("")
    val isRecording = mutableStateOf(false)
}

@Composable
fun WearApp(
    onConnect: (String, String) -> Unit,
    onStartRecording: () -> Unit,
    onStopRecording: () -> Unit,
    onDisconnect: () -> Unit
) {
    var server by remember { mutableStateOf("ws://192.168.1.10:8000") }
    var sessionId by remember { mutableStateOf("") }

    val connectionStatus by AppState.connectionStatus
    val partialText by AppState.partialText
    val finalText by AppState.finalText
    val errorMessage by AppState.errorMessage
    val isRecording by AppState.isRecording

    AppScaffold {
        val listState = rememberTransformingLazyColumnState()
        val transformationSpec = rememberTransformationSpec()
        ScreenScaffold(scrollState = listState) { contentPadding ->
            TransformingLazyColumn(contentPadding = contentPadding, state = listState) {
                item {
                    ListHeader(
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, transformationSpec),
                        transformation = SurfaceTransformation(transformationSpec)
                    ) {
                        Text(text = "TalkAssist")
                    }
                }

                item {
                    OutlinedTextField(
                        value = server,
                        onValueChange = { server = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { M3Text("サーバー") }
                    )
                }

                item {
                    OutlinedTextField(
                        value = sessionId,
                        onValueChange = { sessionId = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { M3Text("セッションID") }
                    )
                }

                item {
                    Button(
                        onClick = { onConnect(server, sessionId) },
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, transformationSpec),
                        transformation = SurfaceTransformation(transformationSpec)
                    ) {
                        Text("接続")
                    }
                }

                item {
                    Button(
                        onClick = { if (isRecording) onStopRecording() else onStartRecording() },
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, transformationSpec),
                        transformation = SurfaceTransformation(transformationSpec)
                    ) {
                        Text(if (isRecording) "録音停止" else "録音開始")
                    }
                }

                item {
                    Button(
                        onClick = { onDisconnect() },
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, transformationSpec),
                        transformation = SurfaceTransformation(transformationSpec)
                    ) {
                        Text("切断")
                    }
                }

                item {
                    Text(
                        text = "状態: $connectionStatus",
                        modifier = Modifier.fillMaxWidth(),
                        style = MaterialTheme.typography.bodySmall,
                        textAlign = TextAlign.Center
                    )
                }

                if (partialText.isNotEmpty()) {
                    item {
                        Text(
                            text = "認識中: $partialText",
                            modifier = Modifier.fillMaxWidth(),
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }

                if (finalText.isNotEmpty()) {
                    item {
                        Text(
                            text = "確定: $finalText",
                            modifier = Modifier.fillMaxWidth(),
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }

                if (errorMessage.isNotEmpty()) {
                    item {
                        Text(
                            text = "エラー: $errorMessage",
                            modifier = Modifier.fillMaxWidth(),
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
        }
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
            onDisconnect = {}
        )
    }
}
