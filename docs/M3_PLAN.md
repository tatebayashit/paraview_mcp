# M3 要件設計・テスト設計

- Status: E-01〜E-06・T-01〜T-03・A-01〜A-04 完了(2026-07-22)。残るは U-01〜U-03(上流還元判断、ユーザー承認待ち)のみ
- 対応マイルストーン: [DESIGN.md](DESIGN.md) §13 M3(UX)
- 前提: M2 完了([M2_PLAN.md](M2_PLAN.md)。unit 96 件+integration 12 件 green、SMOKE 全 6 シナリオ PASS)
- 本書の位置づけ: DESIGN.md が仕様の正。本書は M3 で実施する範囲の確定・要件の実装単位への分解・テスト設計のみを扱い、仕様の詳細は DESIGN.md の節番号で参照する。

## 1. スコープ

M3 のテーマは DESIGN §13 のとおり 3 つ: **(A) instructions チューニング(promptfoo 回帰評価つき)**、**(B) 自動起動の調査と対応可否の決定**、**(C) 上流(LLNL)への還元判断**。

### 1.1 方針: ブリッジ凍結の継続、プロダクトコード変更は最小限

M1 で凍結したブリッジ(`bridge/paraview_mcp_bridge.py`)には引き続き一切手を入れない(M2 §5 #5 と同じく `git diff` 無変更を検収条件とする)。サーバー側も、変更するのは **instructions 文字列(server.py の `INSTRUCTIONS`)とガイダンス文言(bridge_client.py)のみ**で、ツールの引数・返却スキーマ・スニペットは変更しない。M3 は挙動ではなく「LLM への説明の質」を改善するマイルストーンである。

### 1.2 方針: eval 資産の「再利用」の実態は「ハーネスと規約の再利用」

DESIGN §13 は「promptfoo の既存 eval 資産を再利用」とするが、旧資産(コミット `384f9ea` で削除、git 履歴 `384f9ea^:eval/` に残存)を精査した結果、そのまま使えるのは一部に限られる:

| 旧資産 | 再利用可否 | 理由 |
|---|---|---|
| `mcp_eval_client.py`(promptfoo カスタム provider: MCP stdio クライアント+agentic ループ+画像対応) | **△ 骨格を再利用、要改修** | 旧サーバー(`src/paraview_mcp_server.py`)起動・旧モデル ID(`claude-sonnet-4-20250514`、2026-06-15 引退予定)・`temperature: 0`(現行モデルでは 400)を前提としている |
| `eval_claude.yaml`(promptfoo 本体設定) | △ 構成のみ踏襲 | 同上+プロンプト規約(最大 15 回のツールコール、スクリーンショットで検証)は有効 |
| `simple_action_eval.yaml`(アクションレベルのケース) | **× 全面書き直し** | `load_data` / `color_by` / `reset_camera` 等、旧 35 ツール API の名前に結合しており、新 API(5 ツール)には 1 件も適用できない |
| `test_cases.yaml` / `category_specific_eval.yaml` / `data_identification_test_cases.yaml`(タスクレベル) | × ほぼ書き直し | 大半が外部データセット `../SciVisAgentBench-tasks/`(リポジトリ外・非配布)に依存。採点規約(`<1>`/`<0>` センチネル+`llm-rubric`)だけ踏襲する |
| `eval/eval_examples/stream_line/disk.ex2`(サンプルデータ) | ○ 復元して利用 | ファイル読み込み系ケースに使う |

よって M3 の eval 作業は「復元」ではなく「**旧ハーネスの構造・採点規約を踏襲した新規テストスイートの構築**」と定義する。ケースは外部データ非依存(ParaView 組み込みソース中心)で設計し、リポジトリ単体で再現可能にする。

### 1.3 In / Out

| 項目 | M3 | 備考 |
|---|---|---|
| promptfoo eval ハーネス(provider 改修+新ケース+実行手順) | **In** | §3.1。E-01〜E-06 |
| instructions ベースライン測定 → 改稿 → 回帰評価 | **In** | §3.2。T-01〜T-03 |
| 自動起動(`paraview --script=` 等)の実機調査と対応可否の決定 | **In** | §3.3。A-01〜A-04。DESIGN §9.2 の宿題 |
| 上流(LLNL)還元の選択肢整理と判断 | **In**(判断の実施はユーザー承認) | §3.4。U-01〜U-03 |
| 自動起動の**実装**(ブリッジ変更を要する場合) | Out → v1.1 | DESIGN §14(タイマー多重化とセット) |
| eval の CI 組み込み | Out | API キー・費用・実 ParaView が必要。ローカル手動実行のみ(§3.1 E-05) |
| ツール定義・スニペット・ブリッジの変更 | Out | 1.1 |
| pvserver+マクロ登録セグフォの修正 | Out(不可能) | ParaView 側の問題(M1_PLAN §5 #8)。6.1.1→6.0.1 ロールバックでも再現しバージョン非依存と判明済み(M2_PLAN Status) |

### 1.4 本計画で確定させた調整点

1. **eval 実行時のモデル**: 旧設定の `claude-sonnet-4-20250514` は引退間近。既定を `claude-opus-4-8` とし、環境変数(`PARAVIEW_EVAL_MODEL`)で上書き可能にする(コスト優先時は `claude-sonnet-5` を指定)。採点(llm-rubric の grader)も同じ既定に揃える。現行モデルでは `temperature` / `top_p` は送信不可(400)のため provider から削除する。
2. **eval の被験系は standalone ブリッジ**: 実行対象の ParaView は `pvpython --force-offscreen-rendering` + standalone ブリッジを既定とする(integration と同じ構成。GUI 不要・再現性が高い)。実 GUI に対しても同じ設定で流せることは手動確認に留める。GUI 固有経路(タイマー駆動・Qt)の担保は従来どおり SMOKE の担当(§11-3)であり、eval は「instructions の質」の測定に特化する。
3. **英語 README は上流還元と連動**: README.md(英語)は M2 期間に意図的に削除され README_ja.md が正となっている(commit `b7e8e02`)。英語 README の再作成は還元判断が「する」になった場合の作業として §7 に置き、単独では行わない。
4. **instructions と実運用手順の不整合を発見**: bridge_client の接続不可ガイダンスは「Macros → paraview_mcp_bridge を実行せよ」だが、pvserver 接続時の正式手順は Python Shell 貼り付け(セグフォ回避、SMOKE SM-01)。ガイダンス文言に pvserver 時の分岐を追記する(T-02 に含む)。
5. **eval のモデルは OpenRouter / `deepseek/deepseek-v4-flash` に変更**(2026-07-22、ユーザー指示。費用キャップ付きキーを `env/APIkey.env` に用意)。1.4-1 の「anthropic 既定」は破棄し、provider は OpenAI 互換 API(httpx。mcp 経由の推移的依存で venv に既存)で実装。deepseek では `temperature` が有効なため再現性のため 0 を設定する(1.4-1 の temperature 撤去は Anthropic 現行世代固有の事情だった)。
6. **eval モデルは画像入力不可(text→text)**: スクリーンショットの視覚判定はできない。provider が Pillow で画像を解析し「寸法+非背景ピクセル率」のテキストに置換してモデルへ渡す方式に変更(E-03 L2 の「llm-rubric で画像を採点」は取り止め、検証は数値・state ベースに再設計)。視覚品質の担保は従来どおり SMOKE(§11-3)の担当。

## 2. 成果物

```
paraview_mcp/
  src/paraview_mcp/
    server.py                     # INSTRUCTIONS 改稿のみ(T-02)
    bridge_client.py              # ガイダンス文言の pvserver 分岐追記のみ(T-02)
  eval/
    README.md                     # 実行手順・費用目安・ベースライン運用(E-06)
    promptfooconfig.yaml          # promptfoo 設定(旧 eval_claude.yaml の後継)(E-02)
    mcp_eval_client.py            # provider 新実装(OpenRouter 版)(E-01)
    cases/
      tool_level.yaml             # L1: ツール単位 5 ケース(E-03)
      task_level.yaml             # L2: 可視化タスク 4 ケース(E-03)
      instructions_level.yaml     # L3: instructions 感度 6 ケース(E-03)
    data/stream_line/disk.ex2     # git 履歴から復元(E-03)
    data/broken/broken.vtk        # vtk_messages にのみ警告が出る破損フィクスチャ(E-03 L3)
    BASELINE.md                   # ベースライン/改稿後の測定記録(T-01/T-03)
  docs/
    M3_PLAN.md                    # 本書
    M3_AUTOSTART.md               # 自動起動の検証手順・結果・判断(A-04)
    DESIGN.md                     # §9.2 / §13 / §14 の M3 結果反映(A-04, U-02)
  README_ja.md                    # 自動起動に対応する場合の手順追記(A-03)
```

(tests/・bridge/・.github/ は無変更。unit の文言 assert のみ T-02 に追随して更新)

## 3. 要件一覧

### 3.1 eval ハーネス(REQ-E)

| ID | 要件 | 参照 |
|---|---|---|
| E-01 | `mcp_eval_client.py` を改修して復元: MCP stdio でサーバーを子プロセス起動(`uv run paraview-mcp`、`PARAVIEW_MCP_PORT` を fixture 側と一致させる)/ anthropic SDK 現行化(既定 `claude-opus-4-8`、`PARAVIEW_EVAL_MODEL` で上書き、`temperature` 撤去)/ ツールコール上限(既定 15)/ `get_screenshot` の画像を assistant へ返す画像対応は維持。旧版にあった OpenAI provider 分岐は削除(保守しない) | 1.2, 1.4-1 |
| E-02 | `promptfooconfig.yaml`: provider = E-01、`runSerially: true`・`cache: false`・`maxConcurrency: 1`(旧規約踏襲)。promptfoo 本体は `npx promptfoo@latest eval` で実行し依存として恒久化しない。被験系は standalone ブリッジ(起動手順は eval/README.md に記載。integration の conftest と同じ起動列)。**各ケースの冒頭で reset_session を指示**し、ケース間の独立性を保つ(旧資産の運用規約の踏襲) | 1.4-2 |
| E-03 | ケース新規作成(計 12〜15 件、外部データ非依存)。3 層構成: **L1 ツール単位**(bridge_status 応答 / execute_python の最終式評価と state / get_state summary・arrays / reset_session 後に sources 空 / get_screenshot 取得。`<1>`/`<0>` センチネル+contains assert)。**L2 可視化タスク**(Sphere 生成→スクリーンショットで形状確認 / Wavelet→Contour→色付け / disk.ex2 読み込み→配列確認。llm-rubric で画像・手順を採点)。**L3 instructions 感度**(instructions が正しく効いているかを測る: エラー時に vtk_messages を読んで自己修正するか / `Delete(obj); del obj` の両方を行うか / 値が切詰められたら式を絞るか / 長時間処理前に警告+timeout_s 引き上げを行うか / input()・exit() を使わないか)。L3 が instructions チューニングの回帰検出の中核 | 1.2 |
| E-04 | 採点規約: 旧資産の `<1>`/`<0>` センチネル(+ contains / not-contains)と `llm-rubric` を踏襲。rubric は独立採点可能な条件の列挙で書く(曖昧な「良い可視化」判定を避ける) | 1.2 |
| E-05 | 運用規律: CI には載せない(ローカル手動実行)。1 フルランの費用目安(モデル別)と実行時間を eval/README.md に記載し、チューニング反復は L3 のみの部分実行を基本とする。API キーは環境変数(`ANTHROPIC_API_KEY`)からのみ取得し、リポジトリに記録しない | 1.3 |
| E-06 | `eval/README.md`: 前提(pvpython、promptfoo、API キー)→ ブリッジ起動 → eval 実行 → 結果の読み方 → BASELINE.md への記録手順、を番号付きで記載 | — |

### 3.2 instructions チューニング(REQ-T)

| ID | 要件 | 参照 |
|---|---|---|
| T-01 | ベースライン測定: 現行 INSTRUCTIONS のまま E-03 全ケースをフルランし、ケース別 PASS/FAIL・所見を `eval/BASELINE.md` に記録(実施日・モデル・ParaView 版数つき) | §11 |
| T-02 | INSTRUCTIONS 改稿(§7.6 の要旨に沿って全面見直し): (a) M0〜M2 実機で得た知見の反映 — pvserver 接続時はマクロ登録ではなく Python Shell 貼り付けで起動する旨を bridge_client の接続不可ガイダンスにも追記(1.4-4)/ 実行中は GUI がフリーズするのが正常である旨の再確認 (b) ツール使い分け(execute_python の state を毎ターン読む / get_state summary は安価 / reset_session は全消し専用)の明確化 (c) ファイルパスは ParaView 側マシンのパスである旨(WSL/Windows 分離構成) (d) T-01 で観測された失敗モードへの対症を追加。誤字のない簡潔な英語で書く。bridge_client 文言を変えた場合は対応する unit の assert を更新 | §7.6, §10 |
| T-03 | 回帰評価: 改稿後に E-03 をフルランし、**全体 PASS 率がベースラインを下回らないこと**、および T-02(d) で狙った L3 ケースの改善を確認して BASELINE.md に追記。unit(96 件)・integration(12 件)が green のままであることも確認(instructions はツール挙動に影響しないことの担保) | §11 |

### 3.3 自動起動の調査(REQ-A)

DESIGN §9.2 の宿題(「`paraview --script=` 等の起動オプションの互換性を M3 で調査の上、対応可否を決める」)。実装は v1.1(§14)であり、M3 の成果は**調査記録と決定**である。実 GUI 操作を伴うため、M0 スパイク・SMOKE と同様にユーザーの実機協力を要する。

| ID | 要件 | 参照 |
|---|---|---|
| A-01 | 調査対象の候補列挙と一次調査(ドキュメント/ヘルプ): `paraview --script=<file>`(本命)/ マクロ自動配置(`PV_MACRO_PATH` 等。ワンクリック化のみで自動起動ではない)/ その他の起動時実行機構。各機構の「実行タイミング(メインウィンドウ・RenderView 生成の前か後か)」を整理する | §9.2 |
| A-02 | 実機検証マトリクス(ParaView 実機 / WSL2): (a) `--script=` でブリッジを起動したとき `start()` の前提(RenderView の存在)が満たされるか (b) タイマー駆動が機能するか(「bridge active」の出力で判定 — M0 と同じ観点) (c) **起動後に GUI から pvserver へ接続した場合**、ブリッジが生き続けるか(接続切替で view / インタラクタが作り直されタイマーが死ぬ可能性 — DESIGN §12 の既知の制約と同型)。マクロ登録セグフォ(M1_PLAN §5 #8)は「マクロ実行機構」由来と推定されているため、`--script` 経路で同種のクラッシュが出るかも確認する | §4.1, §12 |
| A-03 | 対応可否の決定基準: **ブリッジ・サーバー無変更のまま、README への手順追記だけで安全に提供できる場合のみ v1 で対応**(README_ja.md に起動オプション例を追記)。リトライ・遅延起動などブリッジ変更が必要なら v1.1 送りとし、§14 のタイマー多重化と併せて設計する | 1.1, §14 |
| A-04 | 成果物: `docs/M3_AUTOSTART.md`(候補・検証手順・結果・決定と理由)を作成し、DESIGN.md §9.2 の「M3 で調査の上、対応可否を決める」を決定内容で置き換える(§14 も必要なら追随) | §9.2 |

### 3.4 上流(LLNL)への還元判断(REQ-U)

| ID | 要件 | 参照 |
|---|---|---|
| U-01 | 上流の現状調査: LLNL/paraview_mcp のコミット・Issue/PR の動向、旧方式(コラボレーション同期)の扱いを確認し、還元の選択肢を整理する: (a) Issue/Discussion で再設計の知見を共有(低コスト・非侵襲) (b) PR(全面差し替えになるため受け入れ可能性は低い見込み) (c) 独立フォークとして継続し README で関係を明記(現状維持) | §13 |
| U-02 | 判断: U-01 の選択肢+推奨をユーザーに提示し、**ユーザーの承認を得て**決定・実施する(外部公開を伴うため独断で実施しない)。決定と理由を本書 §5 に記録し、DESIGN §13 M3 に反映する | §13 |
| U-03 | 還元する場合のみ: 英語 README.md の再作成(1.4-3)、LICENSE / NOTICE の最終確認(BSD-3-Clause 維持は S-12 で対応済み) | 1.4-3 |

## 4. テスト設計

M3 の中心的なテストは eval そのもの(E-03/T-01/T-03)である。既存テストへの影響は最小:

- **unit**: INSTRUCTIONS の内容変更は `test_instructions_are_not_empty`(非空・100 文字超)にのみ依存しており改稿で壊れない。bridge_client のガイダンス文言変更(T-02)に対応する文言 assert は同一コミットで更新する。
- **integration**: ツール・スニペット・ブリッジ無変更のため green のまま通ることを T-03 で 1 回確認する(回帰の証明)。
- **eval の位置づけ**: 非決定的(LLM 依存)なため CI 品質ゲートには使わない。「同一条件のベースライン比較」のみを判断材料とし、単発の FAIL はケース自体の曖昧さをまず疑う(rubric を条件列挙に直す — E-04)。
- **自動起動検証(A-02)**: 自動テスト化しない。M0_SPIKE.md と同様に、手順と観測結果を M3_AUTOSTART.md に記録する方式(再現手順の文書化がテストの代替)。

## 5. M3 受け入れ基準

実施したら結果を記入する(M1/M2 と同じ運用)。

| # | 項目 | 期待結果 | 結果 |
|---|---|---|---|
| 1 | eval ハーネス完走 | E-03 全ケースがローカルでエラーなく実行され、promptfoo のレポートが得られる(PASS 率は問わない) | PASS(2026-07-22)。15 ケース(L1×5/L2×4/L3×6)構築。初回フルランでハーネス自体のバグ3件(promptfoo 永続ワーカー内での `asyncio.run()` 再利用による subprocess 不安定化/OpenRouter の HTTP200・`choices`欠落/DeepSeek の空回答)を検出・修正し、以後安定動作を確認。詳細: eval/BASELINE.md |
| 2 | ベースライン記録 | eval/BASELINE.md に現行 instructions の測定結果が記録されている(T-01) | PASS(2026-07-22)。4 回のフルランを実施・突合。真の content 起因の失敗は L3-04(timeout_s 既定値未提示)のみと特定。他はハーネスバグ(修正済み)/grader(deepseek-v4-flash)側の JSON パース不調/OpenRouter のモデレーション誤検知(L3-01)。詳細: eval/BASELINE.md |
| 3 | instructions 改稿と回帰 | 改稿後の全体 PASS 率 ≥ ベースライン、狙った L3 ケースの改善を確認。unit・integration green 維持 | PASS(2026-07-22)。改稿後フルラン **15/15(100%)**(ベースライン実質 14/15 を上回る)。狙った L3-04(timeout_s)は FAIL→PASS。unit 96 件・integration 12 件とも green。改稿内容・回帰評価の詳細・回帰評価中に見つけた eval ケース自体のバグ2件(instructions とは無関係)の記録: eval/BASELINE.md |
| 4 | 自動起動の決定 | A-02 マトリクス実施済み・M3_AUTOSTART.md 記録済み・DESIGN §9.2 が決定内容に更新済み(対応する場合は README 手順も) | PASS(2026-07-22)。A-02 実機検証(ユーザー実施)#1〜#5 全 PASS、特に #4(pvserver 接続済み+`--script`)でセグフォ非再現を確認し 1.2 の最大リスクを解消。決定: `--script=`(位置引数も同様)をブリッジ・サーバー無変更のまま v1 で採用。README_ja.md に手順追記、DESIGN §9.2 を決定内容に更新済み。#6(view 閉鎖後の診断)は自動起動の可否には影響しない申し送り事項として記録(docs/M3_AUTOSTART.md) |
| 5 | 上流還元の判断記録 | 選択肢と推奨の提示 → ユーザー決定 → 本表と DESIGN §13 に記録(実施作業があれば完了) | 未実施 — U-02 はユーザー承認が前提のため、このセッションのスコープ外 |
| 6 | ブリッジ無変更 | `git diff` で bridge/paraview_mcp_bridge.py に変更が無い | PASS(2026-07-22時点)。T-02 で変更したのは server.py の INSTRUCTIONS と bridge_client.py のガイダンス文言のみ。bridge/ 配下は無変更 |

## 6. 実装順序

1. E-01〜E-06(ハーネス復元・改修+新ケース)→ 受け入れ #1
2. T-01(ベースライン測定)→ 受け入れ #2
3. T-02〜T-03(改稿 → 回帰評価。L3 部分実行で反復し、確定時にフルラン)→ 受け入れ #3
4. A-01〜A-04(自動起動調査。実機はユーザー協力。1〜3 と独立に並行可)→ 受け入れ #4
5. U-01〜U-03(上流判断。ユーザー承認後に実施)→ 受け入れ #5
6. DESIGN.md / README_ja.md への結果反映、受け入れ #6 の確認

## 7. 任意項目(M3 のスコープ外だが M3 期間中に判断してよい)

- **Kitware/ParaView への segfault issue 報告**(M2 §7 から継続、ユーザー指示により見送り中): M2 で 6.0.1 でも再現しバージョン非依存と判明したため報告価値は上がっている。gdb バックトレース・最小再現・切り分けは取得済みで報告コストは低いまま。
- **英語 README.md**: U-02 が「還元しない」となった場合でも、外部ユーザー向けに英語版を用意する価値はある。ユーザーの意向次第。
- レシピ集(よくある可視化手順)の MCP リソース/プロンプト化(DESIGN §14)は v1.1 スコープのまま据え置き。
