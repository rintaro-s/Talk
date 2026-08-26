package com.nbks.vr_common

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.nbks.vr_common.ui.theme.VR_commonTheme
import org.json.JSONArray
import org.json.JSONObject

class MainActivity : ComponentActivity() {

    private var client: TalkAssistClient? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            VR_commonTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    TalkAssistVrApp(
                        modifier = Modifier.padding(innerPadding),
                        onConnect = { server, sessionId -> connect(server, sessionId) },
                        onDisconnect = { disconnect() }
                    )
                }
            }
        }
    }

    private fun connect(server: String, sessionId: String) {
        disconnect()
        val url = if (server.endsWith("/")) server.dropLast(1) else server
        val wsUrl = "$url/ws/session/$sessionId?device=vr"
        client = TalkAssistClient(
            url = wsUrl,
            onStatusChange = { status -> AppState.connectionStatus = status },
            onMessage = { json -> handleMessage(json) },
            onError = { msg -> AppState.errorMessage = msg }
        )
        client?.connect()
    }

    private fun handleMessage(json: JSONObject) {
        when (json.optString("type")) {
            "assist" -> {
                AppState.sessionMode = json.optJSONObject("mode_specific")
                AppState.summary = json.optString("summary", "")
                AppState.nextActions = json.optJSONArray("next_actions")
                AppState.questions = json.optJSONArray("questions")
            }
            "transcript" -> {
                val updated = AppState.transcript +
                    "${json.optString("speaker", "?")}: ${json.optString("text", "")}"
                AppState.transcript = if (updated.size > 5) updated.drop(updated.size - 5) else updated
            }
            "presentation_nav" -> {
                AppState.presentationNav = json
            }
            "error" -> {
                AppState.errorMessage = json.optString("message", "エラー")
            }
        }
    }

    private fun disconnect() {
        client?.close()
        client = null
    }

    override fun onDestroy() {
        super.onDestroy()
        disconnect()
    }
}

object AppState {
    var connectionStatus by mutableStateOf("未接続")
    var sessionMode by mutableStateOf<JSONObject?>(null)
    var summary by mutableStateOf("")
    var nextActions by mutableStateOf<JSONArray?>(null)
    var questions by mutableStateOf<JSONArray?>(null)
    var presentationNav by mutableStateOf<JSONObject?>(null)
    var transcript by mutableStateOf(listOf<String>())
    var errorMessage by mutableStateOf("")
}

@Composable
fun TalkAssistVrApp(
    modifier: Modifier = Modifier,
    onConnect: (String, String) -> Unit,
    onDisconnect: () -> Unit
) {
    var server by remember { mutableStateOf("ws://192.168.1.10:8000") }
    var sessionId by remember { mutableStateOf("") }

    Column(modifier = modifier.padding(16.dp)) {
        Text(
            text = "TalkAssist VR",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold
        )

        Spacer(modifier = Modifier.height(12.dp))

        Row(modifier = Modifier.fillMaxWidth()) {
            OutlinedTextField(
                value = server,
                onValueChange = { server = it },
                label = { Text("サーバー") },
                modifier = Modifier.weight(1f)
            )
            Spacer(modifier = Modifier.width(8.dp))
            OutlinedTextField(
                value = sessionId,
                onValueChange = { sessionId = it },
                label = { Text("セッションID") },
                modifier = Modifier.width(180.dp)
            )
        }

        Spacer(modifier = Modifier.height(8.dp))

        Row {
            Button(onClick = { onConnect(server, sessionId) }) {
                Text("接続")
            }
            Spacer(modifier = Modifier.width(8.dp))
            Button(onClick = { onDisconnect() }) {
                Text("切断")
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        Text(text = "状態: ${AppState.connectionStatus}", style = MaterialTheme.typography.bodyMedium)

        if (AppState.errorMessage.isNotEmpty()) {
            Text(
                text = "エラー: ${AppState.errorMessage}",
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium
            )
        }

        Spacer(modifier = Modifier.height(12.dp))

        DashboardSection(modifier = Modifier.weight(1f))
    }
}

@Composable
fun DashboardSection(modifier: Modifier = Modifier) {
    val tiles = mutableListOf<TileData>()

    AppState.sessionMode?.let { modeSpecific ->
        val keys = modeSpecific.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            val value = modeSpecific.opt(key)
            tiles.add(TileData(title = keyToLabel(key), content = formatJsonValue(value)))
        }
    }

    if (AppState.summary.isNotEmpty()) {
        tiles.add(TileData(title = "要約", content = AppState.summary))
    }

    AppState.nextActions?.let { arr ->
        tiles.add(TileData(title = "次のアクション", content = jsonArrayToLines(arr)))
    }

    AppState.questions?.let { arr ->
        tiles.add(TileData(title = "疑問点", content = jsonArrayToLines(arr)))
    }

    AppState.presentationNav?.let { nav ->
        nav.keys().forEach { key ->
            tiles.add(TileData(title = "プレゼン: ${keyToLabel(key)}", content = formatJsonValue(nav.opt(key))))
        }
    }

    if (AppState.transcript.isNotEmpty()) {
        tiles.add(TileData(title = "直近の会話", content = AppState.transcript.joinToString("\n")))
    }

    if (tiles.isEmpty()) {
        Text(text = "接続待ち...", style = MaterialTheme.typography.bodyLarge)
        return
    }

    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = 280.dp),
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(8.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        items(tiles) { tile ->
            TileCard(tile)
        }
    }
}

@Composable
fun TileCard(tile: TileData) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = tile.title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.primary
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = tile.content,
                style = MaterialTheme.typography.bodyMedium
            )
        }
    }
}

data class TileData(val title: String, val content: String)

fun keyToLabel(key: String): String {
    return when (key) {
        "next_task" -> "次にやること"
        "summary" -> "要約"
        "decisions" -> "決定事項"
        "unresolved" -> "未解決"
        "next_actions" -> "次のアクション"
        "questions" -> "疑問点"
        "claim" -> "候補者の主張"
        "deep_questions" -> "深掘り質問"
        "evaluation_axes" -> "評価軸"
        "contradictions" -> "曖昧・矛盾"
        "observation" -> "観察ポイント"
        "root" -> "テーマ"
        "categories" -> "分類"
        "similar" -> "似ている案"
        "next_question" -> "次に広げる問い"
        "current_slide" -> "現在のスライド"
        "current_topic" -> "今話すこと"
        "missing" -> "言い漏れ"
        "next_script" -> "次の一文"
        "filler" -> "場繋ぎ"
        else -> key
    }
}

fun formatJsonValue(value: Any?): String {
    return when (value) {
        null -> "—"
        is String -> value.ifEmpty { "—" }
        is JSONObject -> value.toString(2)
        is JSONArray -> jsonArrayToLines(value)
        else -> value.toString()
    }
}

fun jsonArrayToLines(arr: JSONArray): String {
    val lines = mutableListOf<String>()
    for (i in 0 until arr.length()) {
        val item = arr.opt(i)
        when (item) {
            is JSONObject -> {
                val parts = mutableListOf<String>()
                item.keys().forEach { key ->
                    parts.add("$key: ${item.opt(key)}")
                }
                lines.add("• ${parts.joinToString(", ")}")
            }
            is JSONArray -> lines.add("• ${jsonArrayToLines(item).replace("\n", ", ")}")
            else -> lines.add("• ${item.toString()}")
        }
    }
    return if (lines.isEmpty()) "—" else lines.joinToString("\n")
}
