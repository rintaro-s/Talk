const API_BASE = "";

const MODE_NAMES = {
  general: "汎用会話",
  interviewer: "面接官",
  ideation: "アイデア出し",
  presentation: "プレゼン",
};

const state = {
  mode: "",
  session: null,
  config: null,
  ws: null,
  speechWs: null,
  recognition: null,
  voskRecorder: null,
  webSpeechAvailable: false,
  micOn: false,
  interimText: "",
  lastResultTime: 0,
  pauseSent: false,
  gapSent: false,
  silenceTimer: null,
  timerSeconds: 0,
  timerId: null,
  transcript: [],
  presentationSlides: [],
};

const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function api(path, options = {}) {
  return fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  }).then(async (res) => {
    if (!res.ok) {
      const err = await res.text();
      throw new Error(err || `HTTP ${res.status}`);
    }
    return res.json();
  });
}

// ---------- setup ----------

function showStep(n) {
  [1, 2, 3].forEach((i) => {
    $(`#step${i}`).classList.toggle("hidden", i !== n);
    $(`#st${i}`).classList.toggle("active", i === n);
    $(`#st${i}`).classList.toggle("done", i < n);
  });
}

function setupWizard() {
  $$(".mode").forEach((el) => {
    el.onclick = () => {
      $$(".mode").forEach((x) => x.classList.remove("selected"));
      el.classList.add("selected");
      state.mode = el.dataset.mode;
      $("#next1").disabled = false;
    };
  });

  $("#next1").onclick = () => {
    const pres = state.mode === "presentation";
    $("#contextTitle").textContent = pres ? "資料を読み込む" : "事前情報を入れる";
    $("#contextLead").textContent = pres
      ? "プレゼンには資料テキストとカンペが必要です。"
      : "会話中の支援に使う前提情報を入れます。空でも開始できます。";
    $("#normalInputs").classList.toggle("hidden", pres);
    $("#presentationInputs").classList.toggle("hidden", !pres);
    showStep(2);
  };

  $("#back1").onclick = () => showStep(1);
  $("#back2").onclick = () => showStep(2);

  $$(".input-tab").forEach((tab) => {
    tab.onclick = () => {
      $$(".input-tab").forEach((x) => x.classList.remove("active"));
      tab.classList.add("active");
      const text = tab.dataset.tab === "text";
      $("#textPane").classList.toggle("hidden", !text);
      $("#filePane").classList.toggle("hidden", text);
    };
  });

  $("#fileInput").onchange = (e) => {
    const f = e.target.files[0];
    $("#filePill").classList.toggle("hidden", !f);
    $("#filePill").textContent = f ? f.name : "";
  };

  $("#presentationFile").onchange = async (e) => {
    const f = e.target.files[0];
    $("#presentationFilePill").classList.toggle("hidden", !f);
    $("#presentationFilePill").textContent = f ? f.name : "";
    if (f) {
      $("#presentationDocument").value = await f.text();
    }
  };

  $("#scriptFile").onchange = async (e) => {
    const f = e.target.files[0];
    $("#scriptFilePill").classList.toggle("hidden", !f);
    $("#scriptFilePill").textContent = f ? f.name : "";
    if (f) {
      $("#presentationScript").value = await f.text();
    }
  };

  $("#next2").onclick = () => {
    if (state.mode === "presentation") {
      const doc = $("#presentationDocument").value.trim();
      const script = $("#presentationScript").value.trim();
      if (!doc || !script) {
        alert("プレゼンには資料テキストとカンペの両方が必要です。");
        return;
      }
      state.presentationSlides = parseSlides(doc);
      $("#reviewContext").textContent = `資料 ${state.presentationSlides.length} 枚 / カンペ ${script.split("\n").filter((l) => l.trim()).length} 行`;
    } else {
      const f = $("#fileInput").files[0];
      const t = $("#contextText").value.trim();
      $("#reviewContext").textContent = f ? f.name : t ? "テキスト入力あり" : "なし";
    }
    $("#reviewMode").textContent = MODE_NAMES[state.mode];
    showStep(3);
  };

  $("#startBtn").onclick = startSession;
}

function parseSlides(text) {
  const raw = text.replace(/\r\n/g, "\n");
  const blocks = raw.split(/^---\s*$/m).map((s) => s.trim()).filter(Boolean);
  if (blocks.length > 1) {
    return blocks.map((body, i) => ({ title: `スライド ${i + 1}`, body }));
  }
  const lines = text.split("\n");
  const slides = [];
  let current = { title: "", body: [] };
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (trimmed.startsWith("#")) {
      if (current.title || current.body.length) {
        slides.push({ title: current.title, body: current.body.join("\n") });
      }
      current = { title: trimmed.replace(/^#+\s*/, ""), body: [] };
    } else {
      current.body.push(trimmed);
    }
  }
  if (current.title || current.body.length) {
    slides.push({ title: current.title, body: current.body.join("\n") });
  }
  if (!slides.length) {
    slides.push({ title: "資料", body: text.trim() });
  }
  return slides;
}

// ---------- session ----------

async function startSession() {
  const title = "";
  const session = await api("/api/session", {
    method: "POST",
    body: { mode: state.mode, title },
  });
  state.session = session;

  const contextText = $("#contextText").value.trim();
  const file = $("#fileInput").files[0];
  if (file) {
    const text = await file.text();
    await api(`/api/session/${session.id}/knowledge`, {
      method: "POST",
      body: { content: text },
    });
  } else if (contextText) {
    await api(`/api/session/${session.id}/knowledge`, {
      method: "POST",
      body: { content: contextText },
    });
  }

  if (state.mode === "presentation") {
    await api(`/api/session/${session.id}/presentation`, {
      method: "POST",
      body: {
        document: $("#presentationDocument").value,
        script: $("#presentationScript").value,
      },
    });
  }

  $("#setup").classList.add("hidden");
  $("#session").classList.remove("hidden");
  $("#modeLabel").textContent = MODE_NAMES[state.mode];

  state.transcript = [];
  renderDashboard();
  connectSocket();
  checkMicPermission();
}

function checkMicPermission() {
  if (navigator.mediaDevices?.getUserMedia) {
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        stream.getTracks().forEach((t) => t.stop());
        $("#sessionState").textContent = "マイク使用可";
      })
      .catch(() => {
        $("#sessionState").textContent = "マイク権限なし";
      });
  }
}

async function endSession() {
  stopMic();
  if (state.ws) state.ws.close();
  state.ws = null;

  $("#session").classList.add("hidden");
  $("#minutesView").classList.remove("hidden");
  $("#minutesBody").innerHTML = "<p class=\"loading\">議事録を生成しています...</p>";

  try {
    const data = await api(`/api/session/${state.session.id}/minutes`, {
      method: "POST",
      body: { regenerate: true },
    });
    $("#minutesBody").textContent = data.minutes || "議事録は空です。";
  } catch (e) {
    $("#minutesBody").innerHTML = `<p>議事録の生成に失敗しました。<br>${escapeHtml(e.message)}</p>`;
  }
}

function resetApp() {
  location.reload();
}

// ---------- websocket ----------

function connectSocket() {
  if (!state.session) return;
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws/session/${state.session.id}`);
  state.ws = ws;

  ws.onopen = () => {
    $("#sessionState").textContent = state.micOn ? "録音中" : "接続済み";
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleWsMessage(msg);
  };

  ws.onclose = () => {
    $("#sessionState").textContent = "接続切断";
  };

  ws.onerror = () => {
    $("#sessionState").textContent = "接続エラー";
  };
}

function handleWsMessage(msg) {
  if (msg.type === "transcript") {
    state.transcript.push({ speaker: msg.speaker, text: msg.text });
    updateMiniTranscript();
  } else if (msg.type === "assist") {
    renderAssist(msg);
  } else if (msg.type === "suggestion") {
    showSuggestion(msg.text);
  } else if (msg.type === "filler") {
    showFiller(msg.text);
  } else if (msg.type === "presentation_nav") {
    renderPresentationNav(msg);
  } else if (msg.type === "error") {
    $("#sessionState").textContent = `エラー：${msg.message}`;
    setLoading(false);
  }
}

// ---------- dashboard rendering ----------

function renderDashboard() {
  const renderer = {
    general: renderGeneral,
    interviewer: renderInterviewer,
    ideation: renderIdeation,
    presentation: renderPresentation,
  }[state.mode] || renderGeneral;

  $("#dashboard").innerHTML = renderer();
  bindDashboardEvents();
}

function bindDashboardEvents() {
  $$(".showTranscript").forEach((btn) => {
    btn.onclick = showFullTranscript;
  });
  $$(".addManual").forEach((btn) => {
    btn.onclick = () => {
      const input = btn.parentElement.querySelector(".manualInput");
      const value = input.value.trim();
      if (!value) return;
      addUtterance("手入力", value);
      input.value = "";
    };
  });
}

function miniTranscript() {
  return `
    <div class="transcript-mini">
      <div class="transcript-head">
        <strong>直近の会話</strong>
        <button class="showTranscript">履歴を見る</button>
      </div>
      <div id="miniTranscriptBody">
        ${renderTranscriptRows(state.transcript.slice(-4))}
        ${state.interimText ? `<div class="transcript-row"><span class="speaker">認識中</span><span>${escapeHtml(state.interimText)}</span></div>` : ""}
      </div>
      <div class="manual">
        <input class="manualInput" placeholder="認識できなかった発言を手入力">
        <button class="btn addManual">追加</button>
      </div>
    </div>
  `;
}

function renderTranscriptRows(rows) {
  if (!rows.length) {
    return `<div class="transcript-row"><span class="speaker"></span><span>まだ会話がありません</span></div>`;
  }
  return rows
    .map(
      (u) => `
      <div class="transcript-row"><span class="speaker">${escapeHtml(u.speaker)}</span><span>${escapeHtml(u.text)}</span></div>
    `
    )
    .join("");
}

function updateMiniTranscript() {
  const body = $("#miniTranscriptBody");
  if (body) {
    body.innerHTML = renderTranscriptRows(state.transcript.slice(-4));
    if (state.interimText) {
      body.innerHTML += `<div class="transcript-row"><span class="speaker">認識中</span><span>${escapeHtml(state.interimText)}</span></div>`;
    }
  }
}

function renderGeneral(data = {}) {
  const ms = data.mode_specific || {};
  const nextTask = ms.next_task || "会話を開始してください";
  const summary = ms.summary || "";
  const decisions = ms.decisions || [];
  const unresolved = ms.unresolved || [];
  const nextActions = ms.next_actions || [];
  const questions = ms.questions || [];

  return `
    <div class="dashboard">
      <div class="primary-zone">
        <div class="block emphasis">
          <div class="block-title">今、次にやること</div>
          <p class="big-copy" id="nextTask">${escapeHtml(nextTask)}</p>
        </div>

        <div class="two-col">
          <div class="block">
            <div class="block-title">決定事項</div>
            <ul class="clean" id="decisions">${decisions.map((d) => `<li>${escapeHtml(d)}</li>`).join("") || "<li>—</li>"}</ul>
          </div>
          <div class="block">
            <div class="block-title">未解決</div>
            <ul class="clean" id="unresolved">${unresolved.map((d) => `<li>${escapeHtml(d)}</li>`).join("") || "<li>—</li>"}</ul>
          </div>
        </div>

        ${miniTranscript()}
      </div>

      <aside class="side-zone">
        <div class="block subtle">
          <div class="block-title">要約</div>
          <p class="mid-copy" id="summary">${escapeHtml(summary || "—")}</p>
        </div>
        <div class="block subtle">
          <div class="block-title">疑問点</div>
          <ul class="clean" id="questions">${questions.map((d) => `<li>${escapeHtml(d)}</li>`).join("") || "<li>—</li>"}</ul>
        </div>
        <div class="block subtle">
          <div class="block-title">次のアクション</div>
          <ul class="clean" id="nextActions">${nextActions.map((d) => `<li>${escapeHtml(d)}</li>`).join("") || "<li>—</li>"}</ul>
        </div>
      </aside>
    </div>
  `;
}

function renderInterviewer(data = {}) {
  const ms = data.mode_specific || {};
  const claim = ms.claim || "候補者の発言を待っています";
  const deepQuestions = ms.deep_questions || [];
  const evalAxes = ms.evaluation_axes || [];
  const contradictions = ms.contradictions || [];
  const observation = ms.observation || "";

  return `
    <div class="dashboard">
      <div class="primary-zone">
        <div class="block emphasis">
          <div class="block-title">候補者の主張</div>
          <p class="big-copy" id="claim">${escapeHtml(claim)}</p>
        </div>

        <div class="block">
          <div class="block-title">今すぐ深掘りする質問</div>
          <div id="deepQuestions">${deepQuestions.map((q, i) => `
            <div class="deep-question"><span class="qnum">${i + 1}</span><div>${escapeHtml(q)}</div></div>
          `).join("") || "<div class=\"deep-question\"><span class=\"qnum\">-</span><div>—</div></div>"}</div>
        </div>

        ${miniTranscript()}
      </div>

      <aside class="side-zone">
        <div class="block subtle">
          <div class="block-title">まだ確認できていない評価軸</div>
          <ul class="clean" id="evalAxes">${evalAxes.map((d) => `<li>${escapeHtml(d)}</li>`).join("") || "<li>—</li>"}</ul>
        </div>
        <div class="block subtle">
          <div class="block-title">曖昧・矛盾</div>
          <ul class="clean" id="contradictions">${contradictions.map((d) => `<li>${escapeHtml(d)}</li>`).join("") || "<li>—</li>"}</ul>
        </div>
        <div class="block subtle">
          <div class="block-title">次の観察ポイント</div>
          <p class="mid-copy" id="observation">${escapeHtml(observation || "—")}</p>
        </div>
      </aside>
    </div>
  `;
}

function renderIdeation(data = {}) {
  const ms = data.mode_specific || {};
  const root = ms.root || "テーマを入力してください";
  const categories = ms.categories || [];
  const similar = ms.similar || "";
  const nextQuestion = ms.next_question || "";

  return `
    <div class="dashboard">
      <div class="primary-zone">
        <div class="idea-board">
          <div class="idea-root" id="ideaRoot">${escapeHtml(root)}</div>
          <div class="idea-columns" id="ideaColumns">
            ${categories.map((cat) => `
              <div class="idea-group">
                <h3>${escapeHtml(cat.name || "その他")}</h3>
                ${(cat.ideas || []).map((idea) => `
                  <div class="idea-node ${idea.note?.includes("関連") ? "related" : ""}">
                    ${escapeHtml(idea.text || "")}
                    ${idea.note ? `<span class="idea-tag">${escapeHtml(idea.note)}</span>` : ""}
                  </div>
                `).join("")}
              </div>
            `).join("") || "<div class=\"idea-group\"><h3>まだアイデアがありません</h3></div>"}
          </div>
        </div>

        <div class="two-col">
          <div class="block subtle">
            <div class="block-title">似ている案</div>
            <p class="mid-copy" id="similar">${escapeHtml(similar || "—")}</p>
          </div>
          <div class="block subtle">
            <div class="block-title">次に広げる問い</div>
            <p class="mid-copy" id="nextQuestion">${escapeHtml(nextQuestion || "—")}</p>
          </div>
        </div>

        ${miniTranscript()}
      </div>

      <aside class="side-zone">
        <div class="block subtle">
          <div class="block-title">自動分類</div>
          <ul class="clean" id="ideaCount">${categories.map((cat) => `<li>${escapeHtml(cat.name)} ${(cat.ideas || []).length}件</li>`).join("") || "<li>—</li>"}</ul>
        </div>
        <div class="block subtle">
          <div class="block-title">評価軸</div>
          <ul class="clean">
            <li>会話中に迷わない</li>
            <li>視線移動が少ない</li>
            <li>判断に直接役立つ</li>
          </ul>
        </div>
      </aside>
    </div>
  `;
}

function renderPresentation(data = {}) {
  const ms = data.mode_specific || {};
  const currentTopic = ms.current_topic || "会話を開始してください";
  const nextScript = ms.next_script || "";
  const missing = ms.missing || [];
  const filler = ms.filler || "";
  const currentSlide = ms.current_slide || "";

  const slide = state.presentationSlides[0] || { title: "資料", body: "" };

  return `
    <div class="dashboard">
      <div class="primary-zone">
        <div class="slide-area">
          <div class="slide-preview">
            <div class="slide-num" id="slideNum">${escapeHtml(currentSlide || slide.title)}</div>
            <h3 id="slideTitle">${escapeHtml(currentTopic || slide.title)}</h3>
            <ul id="slidePoints">${missing.map((m) => `<li>${escapeHtml(m)}</li>`).join("") || "<li>言い漏れはありません</li>"}</ul>
          </div>

          <div>
            <div class="block emphasis">
              <div class="block-title">今、このスライドで話すこと</div>
              <p class="big-copy" id="currentTopic">${escapeHtml(currentTopic)}</p>
            </div>
            <div class="block subtle">
              <div class="block-title">言い漏れ</div>
              <ul class="clean" id="missing">${missing.map((m) => `<li>${escapeHtml(m)}</li>`).join("") || "<li>—</li>"}</ul>
            </div>
          </div>
        </div>

        ${miniTranscript()}
      </div>

      <aside class="side-zone">
        <div class="block subtle">
          <div class="block-title">次に話す一文</div>
          <p class="mid-copy" id="nextScript">${escapeHtml(nextScript || "—")}</p>
        </div>
        <div class="block subtle">
          <div class="block-title">場繋ぎ</div>
          <p class="mid-copy" id="filler">${escapeHtml(filler || "—")}</p>
        </div>
      </aside>
    </div>
  `;
}

function renderAssist(data) {
  setLoading(false);
  const renderer = {
    general: renderGeneral,
    interviewer: renderInterviewer,
    ideation: renderIdeation,
    presentation: renderPresentation,
  }[state.mode] || renderGeneral;

  $("#dashboard").innerHTML = renderer(data);
  bindDashboardEvents();
}

function renderPresentationNav(data) {
  if (data.current_topic && $("#currentTopic")) {
    $("#currentTopic").textContent = data.current_topic;
    $("#slideTitle").textContent = data.current_topic;
  }
  if (data.current_slide && $("#slideNum")) {
    $("#slideNum").textContent = data.current_slide;
  }
  if (data.missing && $("#missing")) {
    $("#missing").innerHTML = data.missing.map((m) => `<li>${escapeHtml(m)}</li>`).join("");
    $("#slidePoints").innerHTML = data.missing.map((m) => `<li>${escapeHtml(m)}</li>`).join("");
  }
  if (data.next_script && $("#nextScript")) {
    $("#nextScript").textContent = data.next_script;
  }
  if (data.filler && $("#filler")) {
    $("#filler").textContent = data.filler;
  }
}

function showSuggestion(text) {
  const el = $("#suggestionText");
  if (el) {
    el.textContent = text;
  } else {
    $("#dialogTitle").textContent = "次の言葉";
    $("#dialogBody").innerHTML = `<p class="mid-copy">${escapeHtml(text)}</p>`;
    $("#dialogBg").classList.remove("hidden");
  }
}

function showFiller(text) {
  $("#dialogTitle").textContent = "場繋ぎ";
  $("#dialogBody").innerHTML = `<p class="mid-copy">${escapeHtml(text)}</p>`;
  $("#dialogBg").classList.remove("hidden");
}

function setLoading(isLoading) {
  $("#recordToggle").disabled = isLoading;
  $("#sessionState").textContent = isLoading ? "考え中" : state.micOn ? "録音中" : "待機中";
}

// ---------- speech ----------

function setupSpeech() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  state.webSpeechAvailable = !!SpeechRecognition;
  if (!state.webSpeechAvailable) {
    console.warn("Web Speech API is not available");
  }
}

function addUtterance(speaker, text) {
  if (!state.ws) return;
  state.ws.send(JSON.stringify({ type: "utterance", speaker, text }));
}

async function toggleRecord() {
  if (state.micOn) {
    stopMic();
  } else {
    await startMic();
  }
}

async function startMic() {
  const provider = state.config?.speech?.provider || "web_speech";
  if (provider === "vosk") {
    await startVoskMic();
  } else {
    startWebSpeechMic();
  }
}

function stopMic() {
  if (state.config?.speech?.provider === "vosk" && state.voskRecorder) {
    state.voskRecorder.stop();
  } else if (state.recognition) {
    try { state.recognition.stop(); } catch (e) {}
  }
  state.micOn = false;
  stopSilenceTimer();
  stopTimer();
  $("#recordToggle").textContent = "録音開始";
  $("#sessionState").textContent = "待機中";
}

function startWebSpeechMic() {
  if (!state.webSpeechAvailable) {
    $("#sessionState").textContent = "Web Speech API非対応";
    return;
  }
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new SpeechRecognition();
  recognition.lang = "ja-JP";
  recognition.continuous = true;
  recognition.interimResults = true;

  recognition.onresult = (event) => {
    let final = "";
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        final += transcript;
      } else {
        interim += transcript;
      }
    }
    state.interimText = interim;
    state.lastResultTime = Date.now();
    state.pauseSent = false;
    state.gapSent = false;
    updateMiniTranscript();
    if (final.trim()) {
      addUtterance("自分", final.trim());
    }
  };

  recognition.onerror = (event) => {
    console.error(event.error);
    if (event.error !== "no-speech") {
      $("#sessionState").textContent = `音声認識エラー：${event.error}`;
    }
    if (state.micOn) {
      try { recognition.start(); } catch (e) {}
    }
  };

  recognition.onend = () => {
    if (state.micOn) {
      try { recognition.start(); } catch (e) {}
    }
  };

  state.recognition = recognition;
  state.micOn = true;
  state.lastResultTime = Date.now();
  state.pauseSent = false;
  state.gapSent = false;
  startSilenceTimer();
  startTimer();
  try { recognition.start(); } catch (e) {}
  $("#recordToggle").textContent = "一時停止";
  $("#sessionState").textContent = "録音中";
}

async function startVoskMic() {
  try {
    state.voskRecorder = new VoskRecorder({
      model: state.config?.speech?.vosk_model || "small",
      onReady: () => {
        state.micOn = true;
        state.lastResultTime = Date.now();
        state.pauseSent = false;
        state.gapSent = false;
        startSilenceTimer();
        startTimer();
        $("#recordToggle").textContent = "一時停止";
        $("#sessionState").textContent = "録音中";
      },
      onPartial: (text) => {
        state.interimText = text;
        state.lastResultTime = Date.now();
        state.pauseSent = false;
        state.gapSent = false;
        updateMiniTranscript();
      },
      onFinal: (text) => {
        if (text.trim()) {
          addUtterance("自分", text.trim());
        }
      },
      onError: (err) => {
        $("#sessionState").textContent = `Voskエラー：${err}`;
        stopMic();
      },
    });
    await state.voskRecorder.start();
  } catch (e) {
    $("#sessionState").textContent = `マイク開始エラー：${e.message}`;
    state.micOn = false;
  }
}

function startSilenceTimer() {
  stopSilenceTimer();
  state.silenceTimer = setInterval(() => {
    if (!state.micOn || !state.ws) return;
    const elapsed = Date.now() - state.lastResultTime;
    if (elapsed > 5000 && !state.gapSent) {
      state.ws.send(JSON.stringify({ type: "gap" }));
      state.gapSent = true;
      state.pauseSent = true;
      $("#sessionState").textContent = "沈黙を検知";
    } else if (elapsed > 3000 && !state.pauseSent) {
      state.ws.send(JSON.stringify({ type: "pause" }));
      state.pauseSent = true;
      $("#sessionState").textContent = "停止を検知";
    }
  }, 500);
}

function stopSilenceTimer() {
  if (state.silenceTimer) {
    clearInterval(state.silenceTimer);
    state.silenceTimer = null;
  }
}

function startTimer() {
  stopTimer();
  state.timerSeconds = 0;
  state.timerId = setInterval(() => {
    state.timerSeconds++;
    const m = String(Math.floor(state.timerSeconds / 60)).padStart(2, "0");
    const s = String(state.timerSeconds % 60).padStart(2, "0");
    $("#timer").textContent = `${m}:${s}`;
  }, 1000);
}

function stopTimer() {
  if (state.timerId) {
    clearInterval(state.timerId);
    state.timerId = null;
  }
}

class VoskRecorder {
  constructor({ model, onReady, onPartial, onFinal, onError }) {
    this.model = model;
    this.onReady = onReady;
    this.onPartial = onPartial;
    this.onFinal = onFinal;
    this.onError = onError;
    this.ws = null;
    this.audioContext = null;
    this.processor = null;
    this.source = null;
    this.stream = null;
  }

  async start() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    this.ws = new WebSocket(`${protocol}//${location.host}/ws/speech/vosk`);

    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = () => reject(new Error("Vosk WebSocket接続エラー"));
    });

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "ready") {
        this.onReady();
      } else if (msg.type === "partial") {
        this.onPartial(msg.text || "");
      } else if (msg.type === "final") {
        this.onFinal(msg.text || "");
      } else if (msg.type === "error") {
        this.onError(msg.message);
      }
    };

    this.ws.send(JSON.stringify({ type: "start", model: this.model }));

    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.audioContext = new AudioContext({ sampleRate: 16000 });
    this.source = this.audioContext.createMediaStreamSource(this.stream);
    this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);

    this.processor.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      const pcm = this.floatTo16BitPCM(input);
      const b64 = this.arrayBufferToBase64(pcm.buffer);
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "audio", data: b64 }));
      }
    };

    this.source.connect(this.processor);
    this.processor.connect(this.audioContext.destination);
  }

  stop() {
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "stop" }));
      setTimeout(() => this.ws.close(), 500);
    }
  }

  floatTo16BitPCM(input) {
    const output = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]));
      output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return output;
  }

  arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }
}

// ---------- dialogs ----------

function setupDialogs() {
  $("#closeDialog").onclick = () => $("#dialogBg").classList.add("hidden");
  $("#settingsBtn").onclick = () => {
    loadSettings();
    $("#settingsBg").classList.remove("hidden");
  };
  $("#closeSettings").onclick = () => $("#settingsBg").classList.add("hidden");
  $("#saveSettings").onclick = saveSettings;
  $("#minutesBtn").onclick = showMinutesDialog;
  $("#endBtn").onclick = endSession;
  $("#restartBtn").onclick = resetApp;
  $("#copyMinutes").onclick = copyMinutes;
  $("#downloadMinutes").onclick = downloadMinutes;
}

async function showMinutesDialog() {
  if (!state.session) return;
  $("#dialogTitle").textContent = "議事録";
  $("#dialogBody").innerHTML = `<p class="loading">生成中...</p>`;
  $("#dialogBg").classList.remove("hidden");
  try {
    const data = await api(`/api/session/${state.session.id}/minutes`, {
      method: "POST",
      body: { regenerate: true },
    });
    $("#dialogBody").innerHTML = `<pre class="mid-copy" style="white-space:pre-wrap;">${escapeHtml(data.minutes)}</pre>`;
  } catch (e) {
    $("#dialogBody").innerHTML = `<p class="mid-copy">議事録の生成に失敗しました。</p>`;
  }
}

function copyMinutes() {
  const text = $("#minutesBody").textContent;
  navigator.clipboard.writeText(text).then(() => {
    const btn = $("#copyMinutes");
    const prev = btn.textContent;
    btn.textContent = "コピー済";
    setTimeout(() => (btn.textContent = prev), 1500);
  });
}

function downloadMinutes() {
  const text = $("#minutesBody").textContent;
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `minutes-${state.session?.id || "talk"}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

function showFullTranscript() {
  $("#dialogTitle").textContent = "会話履歴";
  const rows = state.transcript.map((u) => `
    <div class="transcript-row"><span class="speaker">${escapeHtml(u.speaker)}</span><span>${escapeHtml(u.text)}</span></div>
  `).join("");
  $("#dialogBody").innerHTML = rows || "<p class=\"mid-copy\">まだ会話がありません</p>";
  $("#dialogBg").classList.remove("hidden");
}

// ---------- settings ----------

async function loadSettings() {
  state.config = await api("/api/settings");
  const cfg = state.config;
  $("#settingProvider").value = cfg.provider;
  if (cfg.ollama) {
    $("#settingOllamaEndpoint").value = cfg.ollama.endpoint || "";
    $("#settingOllamaModel").value = cfg.ollama.model || "";
    $("#settingOllamaThink").checked = !!cfg.ollama.think;
  }
  if (cfg.sakura) {
    $("#settingSakuraEndpoint").value = cfg.sakura.endpoint || "";
    $("#settingSakuraModel").value = cfg.sakura.model || "";
    $("#settingSakuraKey").value = cfg.sakura.api_key || "";
  }
  if (cfg.speech) {
    $("#settingSpeechProvider").value = cfg.speech.provider || "web_speech";
    $("#settingVoskModel").value = cfg.speech.vosk_model || "small";
  }
  toggleProviderSettings();
}

function toggleProviderSettings() {
  const provider = $("#settingProvider").value;
  $("#settingsOllama").classList.toggle("hidden", provider !== "ollama");
  $("#settingsSakura").classList.toggle("hidden", provider !== "sakura");
}

async function saveSettings() {
  const body = {
    provider: $("#settingProvider").value,
    ollama: {
      endpoint: $("#settingOllamaEndpoint").value.trim(),
      model: $("#settingOllamaModel").value.trim(),
      think: $("#settingOllamaThink").checked,
    },
    sakura: {
      endpoint: $("#settingSakuraEndpoint").value.trim(),
      model: $("#settingSakuraModel").value.trim(),
      api_key: $("#settingSakuraKey").value.trim(),
    },
    speech: {
      provider: $("#settingSpeechProvider").value,
      vosk_model: $("#settingVoskModel").value,
    },
  };
  await api("/api/settings", { method: "POST", body });
  state.config = body;
  $("#settingsBg").classList.add("hidden");
}

// ---------- init ----------

function init() {
  setupWizard();
  setupDialogs();
  setupSpeech();
  $("#recordToggle").onclick = toggleRecord;
  $("#settingProvider").addEventListener("change", toggleProviderSettings);
}

init();
