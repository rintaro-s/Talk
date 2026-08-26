# 会話補助アプリ

ローカル LLM を使った、4 シナリオに特化した会話補助ツール。音声入力または手入力で会話を取り込み、リアルタイムで次の言葉、要約、議事録などを生成する。

## できること

### 4 つのモード

- **汎用会話**：要約、決定事項、未解決事項、次のアクション、疑問点の提示
- **面接官**：候補者の主張整理、深掘り質問、評価軸、曖昧さ・矛盾の指摘
- **アイデア出し**：アイデアの自動分類・ツリー化、類似案の指摘、次に広げる問い
- **プレゼン**：資料とカンペを事前読み込み、現在のトピック、言い漏れ、次の文書、場繋ぎ生成

### 共通機能

- 音声認識（Web Speech API または Vosk）
- 3 秒停止で「次の言葉」、5 秒沈黙で「場繋ぎ」を生成
- モードごとに事前情報（ポートフォリオ、議題など）を読み込み
- 議事録の生成・コピー・ダウンロード
- 会話履歴は補助的に表示し、必要時のみダイアログで確認

## 画面の流れ

1. **モード選択**：4 つのモードから選択
2. **事前情報入力**：
   - 汎用会話 / 面接官 / アイデア出し：テキストまたは txt/md ファイル
   - プレゼン：資料テキスト（必須）＋ カンペ（必須）。`---` 区切りまたは `# 見出し` でスライドを自動分割。txt/md ファイルから読み込み可能
3. **会話中**：録音ボタンで音声入力開始。モード別ダッシュボードがリアルタイム更新
4. **議事録**：「終了」ボタンで議事録生成画面に遷移。コピー・ダウンロード・最初からが可能

## アーキテクチャ

```
┌─────────────────┐      WebSocket       ┌─────────────────┐
│  ブラウザ        │◄────────────────────►│                 │
│  (UI + マイク)   │                      │  TalkAssist     │
└─────────────────┘                      │  サーバー        │
                                         │  FastAPI        │
┌─────────────────┐      WebSocket       │                 │
│  Wear OS watch  │  (PCM audio / Vosk)  │  LLM (Ollama)   │
│  (マイク送信)    │◄────────────────────►│                 │
└─────────────────┘                      └─────────────────┘

┌─────────────────┐      WebSocket       
│  Quest 2        │  (assist 表示のみ)   
│  (VR_common)    │◄────────────────────►
└─────────────────┘                      
```

## スタック

| 層 | 技術 |
|----|------|
| バックエンド | Python 3.12, FastAPI, uvicorn, aiohttp |
| LLM 接続 | Ollama（既定）, さくらのAI Engine（OpenAI 互換） |
| 音声認識 | Web Speech API（ブラウザ）, Vosk（オプション） |
| フロントエンド | バニラ HTML/CSS/JS |
| 通信 | WebSocket, REST API |
| データ保存 | JSON ファイル（`data/` 以下） |
| Wear OS アプリ | Kotlin, Jetpack Compose for Wear OS, AudioRecord, OkHttp |
| Quest 2 クライアント | Kotlin, Jetpack Compose, OkHttp |

## 要件

- Python 3.12
- Ollama（既定の LLM として使用）
- Android SDK（Wear OS / Quest 2 アプリをビルドする場合）
- ブラウザのマイク許可（Web Speech API を使う場合）

## インストール

### 1. リポジトリをクローンまたは配置

```bash
cd /mnt/github/Talk
```

### 2. Python 仮想環境を作成

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

既に `.venv` が存在する場合は、この手順をスキップしてもよい。

### 3. Ollama をインストールし、モデルをダウンロード

```bash
# Ollama が未インストールの場合は https://ollama.com/ からインストール
ollama pull qwen3.5:9b
```

既定モデルは `qwen3.5:9b`。`config.py` またはブラウザの設定画面から変更可能。

### 4. Vosk モデルを配置（オプション）

Vosk を使う場合、初回接続時に自動ダウンロードされる。手動で配置する場合は `data/vosk_models/` に以下のいずれかを展開する。

- `vosk-model-small-ja-0.22`（軽量）
- `vosk-model-ja-0.22`（高精度）

## 起動

```bash
cd /mnt/github/Talk
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

ブラウザで `http://<サーバーIP>:8000` を開く。同一 LAN 内の他のデバイスからアクセスする場合は、`localhost` ではなくサーバーの IP アドレスを使用する。

## 設定

ブラウザ右上の「設定」ボタンから変更可能。

### LLM

- **Ollama（既定）**
  - エンドポイント：`http://localhost:11434`
  - モデル：`qwen3.5:9b`
  - Think：`false`（既定。`true` にすると応答が遅くなる）
- **さくらのAI Engine**
  - エンドポイント：`https://api.ai.sakura.ad.jp/v1/responses`
  - API キーを入力

### 音声認識

- **Web Speech API（既定）**：ブラウザ標準。Chrome / Edge 推奨。
- **Vosk**：ローカル音声認識。初回接続時にモデルをダウンロードする。`small` または `ja` を選択。

## 使い方

1. ブラウザでサイトを開く
2. モードを選択し、「次へ」
3. 事前情報を入力（プレゼンの場合は資料テキストとカンペが必須）
4. 「会話を開始」
5. 「録音開始」ボタンを押して会話を始める
6. ダッシュボードがリアルタイム更新される
7. 「終了」ボタンで議事録生成画面に遷移

## 外部デバイス接続

ブラウザで会話を開始すると、画面上部に「外部デバイス接続」用の以下情報が表示される。

- サーバーアドレス：例 `ws://192.168.1.10:8000`
- セッション ID：例 `a1b2c3d4`

同一 LAN 内の Watch / VR クライアントからこれらを入力して接続する。

### spice/watch（Wear OS マイクアプリ）

Wear OS デバイスのマイクで拾った音声を TalkAssist サーバーに送信し、ブラウザ版と同じセッションの発言として扱う。

#### 機能

- マイクから 16 kHz / mono / 16 bit PCM で録音
- OkHttp WebSocket でサーバーにリアルタイム送信
- 接続状態と認識中テキストの表示

#### 接続先

```
ws://<サーバーIP>:8000/ws/session/<セッションID>?device=watch
```

#### ビルド手順

1. Android Studio で `spice/watch` を開く
2. `local.properties` に SDK パスが正しく設定されていることを確認
3. Wear OS 実機またはエミュレータを接続
4. 以下を実行するか、Android Studio の「Run」を押す

```bash
cd spice/watch
./gradlew assembleDebug
# または実機にインストール
./gradlew installDebug
```

#### 権限

- `RECORD_AUDIO`：マイク録音に必要
- `INTERNET`：サーバー通信に必要
- `WAKE_LOCK`：Wear OS 用に既定で追加

初回起動時にマイク権限を許可する必要がある。

#### 使い方

1. アプリを起動
2. サーバーアドレスに `ws://<サーバーIP>:8000` を入力
3. セッション ID をブラウザからコピーして入力
4. 「接続」をタップ
5. 「録音開始」をタップして発話
6. 「録音停止」をタップして確定

### spice/vr_common（Meta Quest 2 表示クライアント）

Meta Quest 2 上で動作する Android アプリ。VR 専用の 3D 処理は不要で、Quest 2 の 2D アプリ実行環境で会話支援情報をタイル表示する。

#### 機能

- `/ws/session/{id}?device=vr` に接続
- `assist` メッセージを受信し、タイル（カード）として表示
- 入力・操作はなし。表示のみ更新される

#### 接続先

```
ws://<サーバーIP>:8000/ws/session/<セッションID>?device=vr
```

#### ビルド手順

1. Android Studio で `spice/VR_common` を開く
2. `local.properties` に SDK パスが正しく設定されていることを確認
3. 以下を実行

```bash
cd spice/VR_common
./gradlew assembleDebug
```

4. 生成された APK を Quest 2 にサイドロード

```bash
adb install app/build/outputs/apk/debug/app-debug.apk
```

#### Quest 2 へのインストール

1. Quest 2 で開発者モードを有効化
2. PC と Quest 2 を USB 接続
3. `adb devices` で認識を確認
4. `adb install app/build/outputs/apk/debug/app-debug.apk`
5. Quest 2 の「不明来源」またはアプリライブラリから起動

#### 使い方

1. アプリを起動
2. サーバーアドレスに `ws://<サーバーIP>:8000` を入力
3. セッション ID をブラウザからコピーして入力
4. 「接続」をタップ
5. ブラウザで会話が進むと、タイルが自動更新される

## WebSocket プロトコル

### セッション接続

```
/ws/session/{session_id}?device={browser|watch|vr}
```

### ブラウザ / VR 向けメッセージ

| 種別 | 方向 | 内容 |
|------|------|------|
| `utterance` | client → server | `{"speaker":"自分","text":"..."}` |
| `pause` | client → server | 3 秒沈黙を検知。server は `suggestion` を返す |
| `gap` | client → server | 5 秒沈黙を検知。server は `filler` を返す |
| `assist` | client → server | 最新状態で `assist` を再計算して返す |
| `transcript` | server → client | 発言が追加された通知 |
| `assist` | server → client | モード別支援情報、要約、次アクションなど |
| `suggestion` | server → client | 次に話すべき一文 |
| `filler` | server → client | 場繋ぎの一文 |
| `presentation_nav` | server → client | プレゼンモード用ナビゲーション |
| `ping` / `pong` | 両方向 | 接続維持 |

### watch 向けメッセージ

| 種別 | 方向 | 内容 |
|------|------|------|
| `start` | client → server | `{"model":"small"}`。Vosk 認識開始 |
| `audio` | client → server | `{"data":"<base64 PCM>"}` |
| `stop` | client → server | 認識終了。server は `final` を返し、確定テキストを発言に追加 |
| `ready` | server → client | 認識器準備完了 |
| `partial` | server → client | 認識中のテキスト |
| `final` | server → client | 確定したテキスト |
| `transcript` | server → client | 確定テキストがセッションに追加された通知 |
| `assist` | server → client | セッション更新後の支援情報 |

## ファイル構成

```
/mnt/github/Talk
├── main.py              # FastAPI サーバー、WebSocket エンドポイント
├── agents.py            # LLM エージェント
├── modes.py             # モード定義とプロンプト
├── llm.py               # LLM クライアント（Ollama / さくら）
├── speech.py            # Vosk 音声認識
├── transcript.py        # セッション・発言・ナレッジの保存
├── config.py            # 設定ファイル管理
├── static/              # ブラウザ UI
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── spice/
│   ├── watch/           # Wear OS マイクアプリ
│   └── VR_common/       # Quest 2 表示クライアント
└── data/                # 実行時データ
    ├── sessions/        # セッション JSON
    ├── knowledge/       # モード別ナレッジ
    └── vosk_models/     # Vosk モデル
```

## トラブルシューティング

### ブラウザで `{ "message": "TalkAssist" }` しか表示されない

`/` ルートが `static/index.html` を返すように設定されていることを確認。`main.py` の `root()` ハンドラが `FileResponse` を返しているか確認する。

### LLM からの応答が遅い / 思考文が混入する

- Ollama 設定で `Think` を `false` にする
- GPU が使われているか `ollama ps` で確認

### Web Speech API が使えない

- Chrome / Edge を使用
- `https://` または `localhost` でアクセス
- マイク権限を許可

### Vosk モデルがダウンロードされない

- ネットワーク接続を確認
- `data/vosk_models/` の権限を確認
- 手動でモデルをダウンロードして展開

### watch / vr_common が接続できない

- サーバーアドレスが `ws://` または `wss://` で始まっているか確認
- サーバーが `0.0.0.0` でリッスンしているか確認
- 同一 LAN 内にあるか確認
- ファイアウォールでポート 8000 が開いているか確認

### Quest 2 にインストールできない

- 開発者モードが有効か確認
- `adb devices` で Quest 2 が認識されるか確認
- APK が実際に生成されているか確認

## 注意

- Vosk を使う場合、初回起動時に選択したモデル（`vosk-model-small-ja-0.22` または `vosk-model-ja-0.22`）を自動ダウンロードする
- ブラウザのマイク許可が必要
- プレゼン資料の pptx/pdf はサーバー側で解析しない。テキストに変換して貼り付けるか、txt/md ファイルを読み込む
- Quest 2 上では通常の Android アプリとして動作する。VR 空間内の立体配置は行わない
