# M3 自動起動調査(A-01〜A-04)

- Status: A-01(候補列挙・一次調査)完了(2026-07-22)。A-02(実機検証)完了(2026-07-22、ユーザー実施)。#1〜#5 は PASS、#6 は既知の制約どおりの挙動を確認。A-03/A-04(決定・文書化)は次段。
- 対応要件: [M3_PLAN.md](M3_PLAN.md) §3.3(DESIGN §9.2 の宿題)
- 目的: 「GUI 起動時にブリッジも自動起動する」手段の互換性を調査し、v1 で対応するか(README 追記のみで安全に提供できるか)を決める。実装が必要な場合は v1.1(DESIGN §14)へ送る。

## 1. A-01: 候補の列挙と一次調査

### 1.1 候補一覧

| # | 機構 | 自動起動になるか | 一次評価 |
|---|---|---|---|
| 1 | `paraview --script=<file.py>` | ○(起動時に Python スクリプトを実行) | **本命**。下記 1.2 |
| 2 | 位置引数に `.py` を渡す(`paraview bridge.py`) | ○(#1 と同一機構。`.py` は script として扱われる) | #1 の別表記。挙動は同じはず |
| 3 | Python プラグインの自動ロード(`PV_PLUGIN_PATH` + Plugin Manager の Auto Load) | ○(プラグインロード時に任意コードが走る) | 予備候補。ロードは起動シーケンスの早期で、RenderView 生成**前**の可能性が高い。`start()` の前提(RenderView 存在)を満たさない懸念。要検証だが優先度低 |
| 4 | `PV_MACRO_PATH`(マクロ検索パスの追加) | ×(登録のみ。実行は手動クリック) | 自動起動ではないが「Import new macro 不要でワンクリック化」にはなる。ただしマクロ実行機構は pvserver 接続時のセグフォ(M1_PLAN §5 #8、6.0.1/6.1.1 両方で再現)の当事者であり、これ経由の起動は推奨できない |
| 5 | `--state <file.pvsm/.py>` | △(state ロードに Python を混ぜる変則) | 不採用。state ファイルはユーザーの資産であり、ブリッジ起動を混ぜるのは筋が悪い |

### 1.2 `--script` の一次調査結果(ドキュメント・ソース・ローカル `--help`)

**実行タイミング(好条件)**: ParaView の実装(`Qt/ApplicationComponents/pqCommandLineOptionsBehavior.cxx`、master)では、コマンドライン処理は起動後 `pqTimer::singleShot(100, ...)` で遅延実行される。つまりスクリプト実行時点で:

- メインウィンドウは生成・表示済み、イベントループは稼働中
- アクティブなサーバー接続は確立済み
- 処理順は「サーバー接続 → プラグイン → data → state → **script** → Live/Catalyst → test script」で、script は最後発

既定の builtin セッションでは起動時に RenderView が 1 つ作られるため、`start()` の前提(RenderView の存在、DESIGN §4.1)は満たされる見込みが高い。タイマー登録(`GetInteractor()` + `CreateRepeatingTimer`)も M0 で検証済みの経路と同じものが使えるはずである。**ただしこれは推定であり、A-02 の実機確認が必須**(M0 の教訓: Shell 貼り付けで PASS してもマクロ経由でセグフォした前例がある。実行経路が変われば結果は変わり得る)。

**制約(--help、ParaView 6.0.1 実機で確認)**: `--script` は `--state` / `--data` / 位置引数と**排他**。つまり「データファイルを開きながらブリッジも自動起動」という起動はできない(データは起動後に GUI か AI 経由で開くことになる)。

**懸念(A-02 で検証する)**:

1. `--script` の実行経路がマクロ実行機構(`pqPythonMacroSupervisor`)と同じ Python 実行基盤を通るかは未確認。pvserver 接続時のセグフォ(マクロ経由でのみ発生、Shell 貼り付けでは発生しない)が `--script` 経路で再現するかが最大のリスク。ただし自動起動の主用途は「GUI 起動直後」= builtin セッションであり、pvserver へは起動後に接続する運用が普通なので、「--script 実行時点で pvserver 接続済み」という組み合わせ自体が起きにくい(`paraview --server-url=... --script=...` のような同時指定をサポート対象にするかも A-02 で判断)。
2. 起動後に GUI から pvserver へ接続を切り替えた場合、既存 view が破棄されタイマーが死ぬ可能性(DESIGN §12 の「view が閉じられるとブリッジ停止」と同型)。この場合の案内は既存の §10 のフロー(ping 無応答 → 再実行の案内)がそのまま使えるが、「自動起動したのに接続を変えたら死ぬ」は UX として明記が必要。

### 1.3 A-01 時点の見立て

`--script` はブリッジ・サーバー無変更で使える可能性が高く、**成立すれば README への 1 行(起動コマンド例)追記だけで v1 提供できる**(M3_PLAN A-03 の基準内)。プラグイン自動ロード(#3)はタイミング懸念とセットアップの煩雑さから、#1 が失敗した場合の次善候補に留める。

## 2. A-02: 実機検証マトリクス(実施済み、2026-07-22、ユーザー実施)

ParaView 実機(WSL2)で実施。`BRIDGE=/home/tateb/paraview_mcp/.claude/worktrees/project-overview-m3-planning-5c6cb0/bridge/paraview_mcp_bridge.py`。

| # | 手順 | 確認点 | 結果 |
|---|---|---|---|
| 1 | `paraview --script $BRIDGE` で起動 | Python Shell / 端末に `listening` と **`bridge active`**(最初の tick の証拠)が出るか。`bridge_status` が builtin で応答するか | **PASS**。正常起動を確認 |
| 2 | #1 の状態で execute_python / get_screenshot / get_state を一巡 | SMOKE ①相当が通るか | **PASS** |
| 3 | #1 の後、GUI から pvserver へ接続 | クラッシュしないか / ブリッジ(タイマー)が生存するか | **PASS**。クラッシュなし |
| 4 | pvserver 接続済み状態を作ってから `--server-url=cs://host:port --script=$BRIDGE` で起動 | マクロ+pvserver で起きたセグフォ(M1_PLAN §5 #8)がこの経路でも起きるか | **PASS**。セグフォ再現せず — 1.2 の懸念1(`--script` がマクロ実行機構と同じ経路を通るか)は否定的に解消。`--script` は当該セグフォの影響を受けない |
| 5 | `paraview $BRIDGE`(位置引数) | #1 と同じ挙動か | **PASS**。正常起動を確認 |
| 6 | #1 実行後にブリッジを載せた view を閉じる | 既知の制約(§12)どおりサーバー側診断が機能するか | **要観察**。view を閉じた直後に `run_smoke.py` を実行すると PASS 表示になるが、ParaView 側では見た目上何も起きない(想定していた「ping 無応答」による明示的な診断とは異なる挙動)。その後、新規に Render View を開いて再度 `run_smoke.py` を実行すると球体が表示され正常動作する。**症状の性質(smoke script 側が view 消失を検知しないケースがあるのか、新規 view への自動追従なのか)は未特定** — 1.2 の懸念2の一種だが、想定と異なる形で現れた。A-03 の README 注記に反映しつつ、v1.1 以降で `run_smoke.py`/診断側の追加確認が要る可能性を残す |

## 3. A-03/A-04: 決定

**決定: `--script=`(および同等の位置引数形式)を v1 の自動起動手段として採用し、README への手順追記のみで提供する。** ブリッジ・サーバーへの変更は不要(A-03 の基準を満たす)。

根拠: A-02 #1〜#5 が全て PASS。特に #4(pvserver 接続済み状態から `--server-url=... --script=$BRIDGE` で起動)でセグフォが再現しなかったことにより、1.2 の最大リスク(`--script` がマクロ実行機構 `pqPythonMacroSupervisor` と同じ経路を通り、pvserver 接続時にクラッシュするのではないか)は否定的に解消した。`--script` はマクロ登録セグフォ(M1_PLAN §5 #8)の影響を受けない独立した経路である。

#6(view を閉じた後の挙動)は既知の制約(§12: view 消失でブリッジのタイマーが死ぬ)そのものを否定するものではないが、想定していた「ping 無応答」という明確な症状ではなく「診断側(run_smoke.py)が PASS 表示のまま実態を検知しない」という異なる形で現れた。これは自動起動の可否を左右する問題ではない(view を閉じた後に新しい view を開けば正常に戻ることを確認済み)ため、決定はブロックしないが、README の注意書きと、余力があれば `run_smoke.py` 側の検知精度の見直しを申し送り事項とする。

### 実施した反映

- README_ja.md: 「自動起動(任意)」として `paraview --script=<bridge のフルパス>` の起動例を追記(手順 1 の代替)。
- DESIGN.md §9.2: 「M3 で調査の上、対応可否を決める」を本決定内容への参照に置き換え。
- 申し送り(v1 スコープ外、任意): `run_smoke.py` が「ブリッジを載せた view が閉じられた」状況を PASS のまま見逃す経路があるかどうかの追加調査。現状は実害(自動起動の可否)に影響しないため v1.1 以降の任意項目とする。

## 参考

- ParaView 6.0.1 `paraview --help`(ローカル実機、2026-07-22): `--script TEXT Excludes: --state --data filenames — Python script to execute when the application starts.`
- [pqCommandLineOptionsBehavior.cxx(Kitware GitLab, master)](https://gitlab.kitware.com/paraview/paraview/-/blob/master/Qt/ApplicationComponents/pqCommandLineOptionsBehavior.cxx) — 処理順・100ms シングルショットの根拠
- [Command Line Arguments — ParaView Documentation](https://docs.paraview.org/en/latest/UsersGuide/commandLineArguments.html)
