# bcuse-J

[English](README.md) | 日本語

ブラウザのページとデスクトップアプリのウィンドウを、1つのエージェントループで操作します。各操作は、
観測した候補の表から選ばれます。選ぶのは、有限個の選択肢から選ぶ Decision モデル(Azure Microsoft
Decision 1 または OpenAI Decisions)か、LLM です。

## 使い分け

| 操作するもの | 使うもの |
| --- | --- |
| Webページだけ | [browser-use](https://github.com/geekjapan/browser-use) の `Agent`(LLM)か `DecisionAgent`(Decision)。最速の Decision ループが必要なら [jev-ultrafast](https://github.com/geekjapan/jev-ultrafast) |
| デスクトップアプリだけ | [cua-J](https://github.com/geekjapan/cua-J) と Cua Driver |
| 1つのタスクでWebページとデスクトップアプリの両方 | bcuse-J |

bcuse-J が役に立つのは最後の行だけです。geekjapan の browser-use フォーク(コミット `76e5847` に固定)と、
インストール済みの `cua-driver` を使います。どちらのコードもコピーしていません。

## 方策(誰が操作を選ぶか)

| `--policy` | 選ぶもの | 入力欄に入れる文字 |
| --- | --- | --- |
| `azure` | Microsoft Decision 1 | 任意の補助LLM(`TEXT_MODEL`) |
| `openai` | OpenAI Decisions | 任意の補助LLM(`TEXT_MODEL`) |
| `llm` | OpenAI 互換の任意のチャットモデル。同じ候補表から選ぶ | 同じモデルが同じ返答で書く |
| `generative` | browser-use の通常の `Agent`。デスクトップ操作をツールとして追加 | 同じモデル |

最初の3つは同じループと同じ安全確認を共有します。フラグを1つ替えるだけで、同じタスクで比べられます。
`generative` は、ページ遷移、情報抽出、タブ操作など browser-use の全機能を使えます。デスクトップ操作には、
ほかの方策と同じ「画面が変わっていないか」の確認がかかります。

## 導入

bcuse は2つの部品に分かれています。片方だけでも、両方でも導入できます。

- **モジュール。** `bcuse` コマンドと Python パッケージ `bcuse` です。自分でタスクを実行したり、自分のコードから
  bcuse を呼んだりするときに導入します。
- **エージェントスキル。** Claude Code、Codex、Cursor などのコーディングエージェントに、bcuse をいつ、どう使うかを
  教えます。スキルは `uvx` 経由でモジュールを実行するので、前提条件と認証情報はモジュールと同じです。

### 手順1. 前提条件を入れる

| 必要なもの | 使う場面 | 入れ方 |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | すべて | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python 3.12 以上 | すべて | `uv python install 3.12` |
| Google Chrome か Chromium | ブラウザのタスク | 通常どおりインストール |
| Cua Driver(macOS) | デスクトップのタスク | `/bin/bash -c "$(curl -fsSL https://cua.ai/driver/install.sh)"` |
| Node.js | エージェントスキルだけ | `npx` に必要 |

デスクトップのタスクを使う場合は、CuaDriver.app に macOS の「アクセシビリティ」と「画面収録」の権限を一度与えます。

```bash
cua-driver permissions grant    # macOS の権限ダイアログが開きます
cua-driver permissions status   # 両方が "granted" になれば完了
```

### 手順2. モジュールを入れる

目的に合う行を選んでください。

| やりたいこと | 導入コマンド | 次に実行するもの |
| --- | --- | --- |
| 入れずに試す | 不要 | `uvx --from git+https://github.com/geekjapan/bcuse-J bcuse --help` |
| `bcuse` コマンドを使えるようにする | `uv tool install git+https://github.com/geekjapan/bcuse-J` | `bcuse --help` |
| 自分のプロジェクトでライブラリとして使う | `uv add git+https://github.com/geekjapan/bcuse-J` | `from bcuse.agent import Agent` |
| bcuse 自体を改造する | `git clone https://github.com/geekjapan/bcuse-J && cd bcuse-J && uv sync` | `uv run pytest` |

### 手順3. 認証情報を設定する

設定ファイルのひな形を取得し、使う方策の項目だけを埋めます。

```bash
curl -fsSL https://raw.githubusercontent.com/geekjapan/bcuse-J/main/.env.example -o .env
```

| 方策 | 環境変数 |
| --- | --- |
| `azure` | `AZURE_ENDPOINT`、および `AZURE_API_KEY` か `AZURE_ENTRA_TOKEN` |
| `openai` | `OPENAI_API_KEY` |
| `llm`、`generative` | `LLM_MODEL`、`LLM_API_KEY`。OpenAI 以外の接続先なら `LLM_BASE_URL` も |
| `azure` と `openai` の文字入力 | `TEXT_MODEL`、`TEXT_MODEL_API_KEY`。必要なら `TEXT_MODEL_BASE_URL` |

文字入力用の変数がないと、Decision の方策は入力欄に文字を入れられません。`.env` はバージョン管理に入れないでください。
`uvx` と `uv run` では `--env-file .env` で読み込みます。`uv tool install` で入れた `bcuse` コマンドでは、
`set -a; source .env; set +a` などで先に環境変数として読み込んでください。

### 手順4. エージェントスキルを入れる

```bash
npx skills add geekjapan/bcuse-J
```

どのエージェント向けに入れるか、このプロジェクト用かユーザー全体用かを聞かれます。質問を省くには、引数で指定します。
次の例は、Claude Code 向けにユーザー全体へ入れます。入る場所は `~/.claude/skills/bcuse/SKILL.md` です。

```bash
npx skills add geekjapan/bcuse-J -g -a claude-code -y
```

| やりたいこと | コマンド |
| --- | --- |
| 入れる前に中身を確かめる | `npx skills add geekjapan/bcuse-J --list` |
| 更新する | `npx skills update bcuse` |
| 削除する | `npx skills remove bcuse` |

スキルはエージェントに次のことを指示します。前提条件を確かめること、認証情報は環境変数からだけ読むこと、成功と報告する前に
実際の結果を確かめることです。Cua Driver のインストール、権限の付与、`.env` の作成はしません。手順1と手順3を先に済ませてください。

## 実行

次の例は、手順2で入れた `bcuse` コマンドを使います。`uvx` で実行する場合は、`bcuse` を
`uvx --env-file .env --from git+https://github.com/geekjapan/bcuse-J bcuse` に置き換えてください。

```bash
# ブラウザだけ。Azure Decision 1 で選ぶ
bcuse --policy azure \
  --url https://example.com/form --task 'Enter Ada as name and save.'

# 1つのタスクでブラウザとデスクトップの両方。LLM で選ぶ
bcuse --policy llm \
  --url https://example.com/order --desktop-pid "$(pgrep -x Orders | head -1)" --desktop-title 'Orders' \
  --task 'Copy the order number from the page into the Orders window and save.'
```

終了コードが0になるのは、モデルが完了(DONE)を宣言したときだけです。これはモデルの申告にすぎません。
実際のページやアプリを確かめてから信用してください。

## ライブラリとして使う

```python
from bcuse.agent import Agent
from bcuse.browser import BrowserSurface
from bcuse.desktop import DesktopSurface, open_driver
from bcuse.policy import DecisionPolicy, LLMPolicy

async with open_driver() as driver:
	desktop = await DesktopSurface.for_window(driver, pid, 'Orders')
	agent = Agent(task, DecisionPolicy(decision_client, text_llm), [BrowserSurface(session, task), desktop])
	result = await agent.run(max_steps=20, outcome_verifier=check_the_real_outcome)
```

`result.status` は `model_done`、`blocked`、`max_steps`、`stale_state`、`action_error` のいずれかです。
`result.verified` を設定するのは、渡した `outcome_verifier` だけです。

## 1ステップの流れと安全確認

1. 操作中の面を観測します。ブラウザ側は browser-use の DOM から候補を作ります。デスクトップ側は
   `cua-driver mcp` で1つのウィンドウのアクセシビリティツリーを読みます。
2. 操作ごとに、観測した候補だけを提示します(`click`、`input`、`select`)。ほかに `scroll_*`、`wait`、
   `switch_to_<面>`、`DONE`、`BLOCKED` を提示します。モデルがセレクタ、座標、トークン、コードを送ることはありません。
3. もう一度観測します。観測のフィンガープリントが変わっていれば、何も実行せず `stale_state` で止まります。
4. 1回だけ実行します。失敗すると `action_error` で止まり、再試行はしません。デスクトップ操作はバックグラウンド配信だけを使い、
   前面への切り替えに頼ることはありません。

パスワード、トークン、支払い情報と判定した欄は入力候補に出さず、その値もモデルに見せません。メニューバーの項目は、
デスクトップのクリック候補に出しません。Decision へのリクエストは28KB未満に収め、ページやウィンドウの文字は収まるように
切り詰めます。Decision へのリクエストを再試行するのは HTTP 503 と 529 のときだけです。予測には副作用がないからです。
429 のときはすぐに止まります。

## 制限

- 1回の実行で扱うデスクトップのウィンドウは1つです。デスクトップでのスクロール、メニュー、キーボードショートカットの操作はありません。
- デスクトップの文字入力は `set_value` だけを使います。キー入力でないと変更を検知しないアプリもあります。
- デスクトップのフィンガープリントには要素の位置も含まれます。そのため、選択から実行までの間にウィンドウを動かすと
  `stale_state` になります。アクセシビリティツリーに現れない変化では、フィンガープリントは変わりません。
- browser-use は `data:` URL のページから候補を拾いません。テスト用のページは HTTP で配信してください。
- ループ型の方策はページ遷移ができません。作業するページでブラウザを開始するか、`generative` を使ってください。
- フィンガープリントの確認は、観測から実行までの競合を狭めますが、なくすことはできません。
- ブラウザ操作は browser-use の `Tools` を通るため、`Tools` 独自の代替処理が働きます。選んだ欄への入力に失敗すると、
  その欄をクリックし直してフォーカスのある要素に入力します。チェックボックスをクリックしても状態が変わらないと、
  JavaScript でもう一度クリックします。入力した文字は INFO レベルでログに出ます。元の `DecisionAgent` も同じ挙動です
  (`browser_use/browser/watchdogs/default_action_watchdog.py`)。
- デスクトップの秘密情報の判定には、ロール、Cua Driver が返す場合は `AXSecureTextField` サブロール、ラベル中の語を使います。
  Cua Driver 0.30 は要素のサブロールを返さないようです。そのため、ラベルに手がかりのない macOS のパスワード欄は、
  入力候補に出る可能性があります。秘密情報を入力する場面では使わないでください。

## 検証

```bash
uv run ruff check . && uv run pytest
```

テストはオフラインで動き、APIキーは不要です。実物のヘッドレス Chromium を、ループ型の3つの方策と `generative`
モードのすべてで操作します。モデルの代わりに台本どおりに答える偽物を使い、Azure と OpenAI の実際の通信形式を通します。
デスクトップのテストは、cua-J で記録した Cua Driver の応答を再生するもので、実際の入力は発生させません。

実機スクリプトが2つあります。どちらも CuaDriver.app の権限が必要で、有料の呼び出しはしません。操作するのは、cua-J の隔離された
AppKit テストアプリとローカルのページだけです。

- `scripts/probe_desktop.py` は、デスクトップ側を実際のドライバーで確かめます。対象は、観測、フィンガープリント、
  クリック、`set_value`、古い操作トークンをドライバーが拒否することです。
- `scripts/smoke_cross.py` は、実物の Chromium のページとテストアプリをまたぐ1つのタスクを、台本どおりの選択で実行します。
  結果は両方のアプリ自身の状態で確かめます。

テストアプリは、このリポジトリの隣に置いた [cua-J](https://github.com/geekjapan/cua-J) のチェックアウトでビルドしたものを使います
(`libs/cua-driver/tests/fixtures/build/macos.sh --only appkit`)。別の場所にある場合は、`CUA_APPKIT_APP` に `.app` の場所を指定してください。

どちらも macOS 27.0.1、cua-driver 0.30.4 で通過しました。実際の Decision や LLM の接続先に対する実行は、検証に含まれていません。

## ライセンス

MIT です。[LICENSE](LICENSE) を参照してください。記録済みのデスクトップ用フィクスチャは cua-J 由来で、その著作権表示は
[tests/fixtures/README.md](tests/fixtures/README.md) にあります。
