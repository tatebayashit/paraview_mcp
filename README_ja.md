# ParaView MCP

[English](README.md) | 日本語

自然言語で ParaView を操作するための MCP(Model Context Protocol)サーバーです。Claude Code や Codex などの MCP クライアントから、実行中の ParaView に Python コードを送り込み、可視化の作成・操作・スクリーンショットによる確認までを AI に任せることができます。

本リポジトリは [LLNL/paraview_mcp](https://github.com/LLNL/paraview_mcp) のフォークですが、現行 ParaView では非推奨となっている pvserver のコラボレーション同期機能を廃止し、**ParaView 内へ Python コード文字列を送って実行する**方式に置き換えています。

## 対応環境

- **OS**: Windows、WSL(Ubuntu など)、Linux のいずれでも動作します。特定の OS 専用の機能はありません。ParaView が動く環境であれば基本的に問題ありません。
- **ParaView**: 6.1.1 で動作確認済みです(ブリッジ自体は ParaView 5.11+ / Python 3.9+ でも動くように実装しています)。
- **MCP サーバー側**: Python 3.10 以上と [uv](https://docs.astral.sh/uv/)(後述のとおりインストールします)。

ParaView と MCP サーバーを同じ OS 上で動かすのが最も簡単な構成です。Windows の Claude Desktop から WSL 内の ParaView を操作する、といった OS をまたぐ構成も可能です(詳しくは「[複数の OS にまたがる構成](#複数の-os-にまたがる構成)」をご覧ください)。

## 仕組み

```
Claude          ◄─ stdio (MCP) ─►  paraview-mcp サーバー  ◄─ TCP 127.0.0.1:9911 ─►  ParaView 内ブリッジ
(Desktop/Code)                     純 Python・paraview 非依存      (NDJSON)          GUI メインスレッドで exec
```

- **ブリッジ**([bridge/paraview_mcp_bridge.py](bridge/paraview_mcp_bridge.py)): ParaView の組み込み Python 内で動作し、localhost の TCP で受け取ったコードを GUI メインスレッドで実行します。
- **MCP サーバー**(`paraview-mcp`): Python 環境で動作します。
- GUI が pvserver に接続している場合は、GUI が張っている既存セッションをそのまま使用できます。pvserver 側の設定変更は不要です。

## インストール

### 1. ParaView を用意する

まだお持ちでない場合は、[ParaView 公式サイト](https://www.paraview.org/download/)から OS に合ったインストーラーをダウンロードしてインストールしてください。Windows・Linux・macOS それぞれにビルド済みバイナリが用意されています。WSL をお使いの場合は、WSL 内の Linux 環境に Linux 版をインストールするのが簡単です。

### 2. uv をインストールする

このプロジェクトは Python パッケージの管理に [uv](https://docs.astral.sh/uv/) を使っています。uv は Python 本体のインストールから仮想環境の作成、依存パッケージのインストールまで 1 つのコマンドでまとめて面倒を見てくれるツールで、Python の環境構築負荷を軽減できます。

まだ uv をお持ちでない場合は、お使いの OS に応じて以下のいずれかを実行してください。

**Linux / macOS / WSL の場合**(ターミナルで実行):

```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows の場合**(PowerShell で実行):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

インストール後、ターミナル(PowerShell の場合は新しいウィンドウ)を開き直してから、次のコマンドでインストールできたか確認してください。

```shell
uv --version
```

バージョン番号が表示されれば成功です。うまくいかない場合は [uv 公式のインストール手順](https://docs.astral.sh/uv/getting-started/installation/)もあわせてご確認ください。

> お使いの環境に Python 3.10 以上が入っていない場合でも心配ありません。次の手順の `uv sync` を実行すると、uv が必要なバージョンの Python を自動的に取得してくれます。

### 3. このリポジトリを取得してセットアップする

```shell
git clone https://github.com/tatebayashit/paraview_mcp.git
cd paraview_mcp
uv sync
```

`uv sync` は、仮想環境(`.venv`)の作成、必要な Python パッケージのインストールをすべて自動で行います。エラーなく終われば準備完了です。

## 使い方

### 1. ParaView 側: ブリッジを起動する

1. ParaView を起動します(pvserver に接続して使う場合は、先に File → Connect で接続しておいてください)。
2. ブリッジを起動します。
   - **通常(builtin セッション)の場合**: Macros → Import new macro… で `bridge/paraview_mcp_bridge.py` を登録し、そのマクロを実行します。
   - **pvserver に接続している場合**: マクロ登録は使わず、`bridge/paraview_mcp_bridge.py` の中身を View → Python Shell に直接貼り付けて実行してください(理由は後述の「注意事項」をご覧ください)。
3. 次の 2 行が表示されれば成功です(2 行目はタイマー駆動が正しく機能している証拠です)。

```
[paraview-mcp HH:MM:SS] listening on 127.0.0.1:9911
[paraview-mcp HH:MM:SS] bridge active (first tick fired)
```

**自動起動(任意)**: 手順 1〜2 の代わりに、ParaView 起動時に `--script` でブリッジを直接指定して起動することもできます(実機で動作確認済みです。マクロ登録に伴う既知の問題の影響も受けません)。ただし `--state` や `--data`、位置引数によるデータファイル指定とは同時に使えません。

```shell
paraview --script /path/to/bridge/paraview_mcp_bridge.py
# 位置引数でも同じように起動できます
paraview /path/to/bridge/paraview_mcp_bridge.py
```

### 2. MCP クライアント側: サーバーを登録する

Claude Desktop(`claude_desktop_config.json`)の場合:

```json
"mcpServers": {
  "paraview": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/paraview_mcp", "paraview-mcp"]
  }
}
```

Claude Code の場合:

```shell
claude mcp add paraview -- uv run --directory /path/to/paraview_mcp paraview-mcp
```

Windows の Claude Desktop から WSL 内のサーバーを使う場合は、後述の「[複数の OS にまたがる構成](#複数の-os-にまたがる構成)」をご覧ください。

### 提供ツール

| ツール | 内容 |
|---|---|
| `execute_python(code, timeout_s=120, render=True)` | ParaView 内で Python コードを実行します。`paraview.simple` は import 済みで、名前空間は呼び出しをまたいで持続し、末尾の式の値が返ります(IPython と同じ規約)。毎回の応答にパイプライン状態の要約(`state`)が付きます |
| `get_screenshot(max_width=1280, quality=80)` | アクティブな RenderView を JPEG で取得します(base64 転送のためファイル共有は不要です) |
| `bridge_status()` | ブリッジとの疎通・ParaView バージョン・セッション種別(builtin / client-server)を確認します。トラブル時はまずここを確認してください |
| `get_state(detail="summary"\|"arrays"\|"full")` | パイプラインの状態を取得します。`summary` はソース一覧・アクティブ view・時刻、`arrays` は各ソースの point/cell 配列、`full` はさらに bounds・セル数・代表プロパティを含みます |
| `reset_session(clear_pipeline=True, clear_namespace=True)` | パイプライン(全ソース削除)と実行名前空間をリセットします |

### 環境変数

| 変数 | 既定値 | 意味 |
|---|---|---|
| `PARAVIEW_MCP_PORT` | 9911 | ブリッジの待ち受けポート / サーバーの接続先ポート(両側で一致させてください) |
| `PARAVIEW_MCP_HOST` | 127.0.0.1 | サーバー側の接続先ホスト(通常は変更不要です) |
| `PARAVIEW_MCP_TOKEN` | なし | 設定すると、全リクエストで照合される共有シークレットになります(両側に同じ値を設定してください) |
| `PARAVIEW_MCP_LOG` | なし | サーバーのログをファイルにも書き出したい場合のパス |

## 複数の OS にまたがる構成

OS をまたいで使いたい場合(例: Claude Desktop は Windows、ParaView は WSL 内で動かしたい)も対応可能です。代表的な構成として、**MCP サーバーも ParaView と同じ側(WSL 内)に置き、`wsl.exe` 経由で起動する**方法を動作確認済みです。

```json
"mcpServers": {
  "paraview": {
    "command": "wsl.exe",
    "args": ["-d", "Ubuntu", "--", "/home/user/paraview_mcp/.venv/bin/paraview-mcp"]
  }
}
```

これなら通信は WSL の中だけで完結するため、Windows と WSL の間のネットワーク設定を気にする必要がありません。

逆に ParaView を Windows 側、MCP サーバーを WSL 側に置く構成は、WSL のネットワークモード(NAT かミラーモードか、バージョンなど)によって `127.0.0.1` が期待どおりに届くかどうかが変わることがあります。まずは試してみて、もしサーバーがブリッジに接続できない場合は、`PARAVIEW_MCP_HOST` を `127.0.0.1` の代わりに実際の接続先 IP アドレスに指定するか、上記のように片方の OS 側に処理をまとめる方法をお試しください。

ファイルシステムが分かれる構成では、データファイルのパスは **ParaView が動いている側から見たパス**で指定してください(スクリーンショットは base64 で転送されるため、ファイル共有は不要です)。

## ヘッドレス運用(GUI なし)

```shell
pvpython --force-offscreen-rendering bridge/paraview_mcp_bridge.py --standalone [--port 9911]
```

GUI を使わず、「AI が操作し、人間はスクリーンショットで確認する」という最小構成です。CI でもこのモードを使っています。

## セキュリティ上の注意

- 本システムは設計上、任意コードを実行します。MCP クライアント(LLM)が生成した任意の Python コードが、ParaView プロセスの権限で実行されます。コードの静的検証やサンドボックス化は行っていません。ツール実行を承認するときは、十分に内容を確認してください。
- ブリッジはローカルの 127.0.0.1 にのみ接続します。リモート公開はサポートしていません。
- 共有マシンでお使いの場合は、`PARAVIEW_MCP_TOKEN` の設定をおすすめします(localhost 上の他プロセスからの接続対策になります)。

## 注意事項

- コード実行中は ParaView の GUI がフリーズします(メインスレッドで実行しているためで、手動で重いフィルタを適用した場合と同じ挙動です)。OS が「応答なし」と表示しても、強制終了しないでください。
- 実行中のコードをキャンセルすることはできません。
- ブリッジのタイマーを載せた RenderView を閉じると、ブリッジは停止します。`bridge_status` が再実行を案内しますので、その場合はブリッジを起動し直してください。
- vtkOutputWindow を通らない出力(vtkLogger 直行のログ、C++ からの stdout/stderr 直書きなど)は `vtk_messages` には捕捉されません(プロセスのコンソールには残ります)。
- **バグ**: pvserver に接続している状態で**マクロ登録経由**でブリッジを起動すると、ParaView がセグメンテーション違反で終了します。**回避策**: pvserver に接続している場合は、Python Shell への貼り付けでブリッジを起動してください。

## 開発

```shell
uv sync --extra dev
uv run pytest tests/unit         # 96 件、ParaView 不要
uv run pytest tests/integration  # 実 pvpython が必要です(無ければ自動でスキップされます)
uv run ruff check bridge/ src/ tests/
```

- unit CI: [.github/workflows/unit.yml](.github/workflows/unit.yml)(Python 3.10〜3.12)
- integration CI: [.github/workflows/integration.yml](.github/workflows/integration.yml)(conda-forge の ParaView 6.1.1、Xvfb 経由)
- 手動スモークテスト: [docs/SMOKE.md](docs/SMOKE.md)

## 上流プロジェクトについて

本リポジトリは LLNL の ParaView-MCP のフォークであり、BSD-3-Clause ライセンスを維持しています([LICENSE](LICENSE) / [NOTICE](NOTICE))。

[![Video Title](https://img.youtube.com/vi/GvcBnAcIXp4/maxresdefault.jpg)](https://youtu.be/GvcBnAcIXp4)

S. Liu, H. Miao, and P.-T. Bremer, "Paraview-MCP: Autonomous Visualization Agents with Direct Tool Use," in Proc. IEEE VIS 2025 Short Papers, 2025.

```bibtex
@inproceedings{liu2025paraview,
  title={Paraview-MCP: Autonomous Visualization Agents with Direct Tool Use},
  author={Liu, S. and Miao, H. and Bremer, P.-T.},
  booktitle={Proc. IEEE VIS 2025 Short Papers},
  pages={00},
  year={2025},
  organization={IEEE}
}
```

Paraview_MCP was originally created by Shusen Liu (liu42@llnl.gov) and Haichao Miao (miao1@llnl.gov).

LLNL-CODE-2007260
