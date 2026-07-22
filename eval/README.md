# paraview-mcp instructions eval(M3)

サーバーの FastMCP `instructions` の品質を測る promptfoo スイート(仕様: [docs/M3_PLAN.md](../docs/M3_PLAN.md) §3.1–3.2)。CI には載せない。ローカル手動実行のみ。

## 構成

- `mcp_eval_client.py` — promptfoo カスタム provider。ケースごとに MCP サーバーを stdio で起動し、OpenRouter の LLM(既定 `deepseek/deepseek-v4-flash`)にツールを渡して agentic ループを回す。最終回答の後ろに `---TOOL TRACE---`(ツール呼び出しの記録)を付けて返すので、assert で「何をしたか」まで検査できる。
- `cases/` — 3 層 15 ケース。L1 ツール単位(決定的 assert)/ L2 可視化タスク / L3 instructions 感度(チューニングの回帰検出の中核)。
- `data/` — `stream_line/disk.ex2`(git 履歴から復元)と `broken/broken.vtk`(vtk_messages にのみ警告が出る破損フィクスチャ)。
- `BASELINE.md` — 測定記録。

制約: eval モデルは画像入力不可(text→text)のため、スクリーンショットは provider が Pillow で解析したテキスト(寸法+非背景ピクセル率)に置き換えて渡す。視覚的な良し悪しの採点はしない(GUI 経路の担保は従来どおり docs/SMOKE.md)。

## 実行手順

前提: `uv sync` 済み・`pvpython` が PATH にあること・Node.js(npx)。

```shell
# 1. API キー(値は表示しないこと)
export OPENROUTER_API_KEY="$(tr -d '[:space:]' < /path/to/APIkey.env)"

# 2. standalone ブリッジを起動(別ターミナル。ポートは既定 9911)
pvpython --force-offscreen-rendering bridge/paraview_mcp_bridge.py --standalone

# 3. eval 実行(リポジトリルートから)
cd eval
export PROMPTFOO_PYTHON="$(cd .. && pwd)/.venv/bin/python"   # venv の python を使わせる
npx -y promptfoo@latest eval -c promptfooconfig.yaml --no-cache -j 1

# 4. 結果の閲覧
npx -y promptfoo@latest view   # ブラウザ UI(任意)
```

- モデル変更: `export PARAVIEW_EVAL_MODEL=...`(provider 側)。grader は `promptfooconfig.yaml` の `defaultTest.options.provider`。
- 単一ケースのデバッグ: `../.venv/bin/python mcp_eval_client.py "質問文"` で promptfoo を介さず 1 件実行できる。
- ケース間の独立性: 各ケースは自分の前提を自分で作る(必要なら reset する)よう書かれているが、確実を期すならブリッジを起動し直すのが最も安全。

## 費用・時間の目安

deepseek-v4-flash で 1 フルラン(15 ケース+rubric 採点)は概ね数十万〜100 万トークン程度 = **数セント〜十数セント**、10〜20 分(直列実行・ツール実行込み)。チューニングの反復は L3 のみの部分実行を基本とする:

```shell
npx -y promptfoo@latest eval -c promptfooconfig.yaml --no-cache -j 1 --filter-pattern "L3-"
```

## 記録の運用

フルランごとに `BASELINE.md` へ 1 行(実施日・instructions 版・モデル・ParaView 版数・PASS/総数・所見)追記し、ケース別の特記事項を下段に書く。instructions 改稿の採否は「全体 PASS 率がベースラインを下回らないこと+狙った L3 ケースの改善」で判断する(M3_PLAN T-03)。

**grader 不調時の再確認**: grader にも軽量モデル(deepseek-v4-flash)を使っているため、llm-rubric の採点が JSON を正しく返さないことがある(`reason` が `"string"` のプレースホルダのまま、または `Could not extract JSON from llm-rubric response`)。このパターンで FAIL になったケースは、まず該当ケースのみ `--filter-pattern` で単体再実行して内容自体を確認してから、真の回帰かどうか判断すること(詳細: `BASELINE.md`)。
