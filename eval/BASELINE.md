# ベースライン測定記録(T-01/T-03)

## 実施記録

| 日付 | instructions 版 | モデル | ParaView 版数 | PASS/総数 | 備考 |
|---|---|---|---|---|---|
| 2026-07-22 | 改稿前(現行、server.py 初期状態) | deepseek/deepseek-v4-flash(agent・grader 共通) | 6.0.1(standalone、offscreen) | 実質 14/15(下記参照) | T-01。4 フルラン実施。詳細は下記 |
| 2026-07-22 | 改稿後(T-02: timeout_s 既定値明記+pvserver 分岐追加) | deepseek/deepseek-v4-flash(agent・grader 共通) | 6.0.1(standalone、offscreen) | **15/15(100%)** | T-03。eval ケース側の設計バグ2件(下記「T-03 での追加修正」)を先に直した上でのクリーンラン。狙った L3-04 は FAIL→PASS(timeout_s に 300 を明示指定)|

セッション: standalone bridge(`pvpython --force-offscreen-rendering bridge/paraview_mcp_bridge.py --standalone --port 9911`)、全ケース同一ブリッジプロセスを使い回し(README の運用どおり)。

## サマリ

4 回のフルラン(各回 15 ケース)を実施した。生の PASS 数は 13→10→13→12 とばらついたが、失敗を1件ずつ突き合わせた結果、**実際にコンテンツが誤っていたのは L3-04 の1件のみ**で、残りは (a) eval ハーネス自体のバグ(3 件、実行中に特定・修正済み)、(b) 採点(llm-rubric)側の JSON パース不調、(c) OpenRouter 側のコンテンツモデレーション誤検知、のいずれかだった。

### (a) ハーネスのバグ(instructions とは無関係、修正済み)

1. **同一プロセス内での `asyncio.run()` 再利用による subprocess spawn の不安定化**: promptfoo は Python provider を「持続する1ワーカープロセス」で使い回す。`call_api()` がそのプロセス内で毎回 `asyncio.run()` して MCP サーバーの子プロセスを spawn していたところ、Linux 上で2〜3回目以降に `ExceptionGroup`(まれにハング)が発生することを単体ループ再現で確認。**対処**: ケースごとに使い捨てサブプロセス(`--worker-run` モード)で実行するよう [mcp_eval_client.py](mcp_eval_client.py) を変更。5 回連続実行で安定を確認。
2. **OpenRouter が HTTP 200 で `choices` を欠くレスポンスを返す場合がある**(上流プロバイダのエラーボディがそのまま 200 で返ってくる)。`chat()` が未検証で `data["choices"][0]` を参照し `KeyError` → `ExceptionGroup` として表面化していた。**対処**: `choices` の有無を検証し、無い場合は 429/5xx と同様にリトライ対象とし、最終的に失敗する場合も内容の分かるメッセージを返すよう修正。
3. **DeepSeek がツール呼び出しなしで空の最終回答を返すことがある**(1 ケースで観測)。**対処**: 空回答かつツール呼び出しなしの場合、1 回だけ「最終回答をテキストで出すように」と促すリトライを追加。
4. **promptfoo の Python worker 既定タイムアウト(300秒)が、ツール呼び出しの多いケースには時に不足**(1 ケースで観測)。**対処**: [promptfooconfig.yaml](promptfooconfig.yaml) の provider 設定に `timeout: 600000` を追加。

### (b) 採点(grader)側の不調 — instructions/実装の問題ではない

grader にも同じ `deepseek/deepseek-v4-flash` を使っている(費用抑制のための意図的選択、M3_PLAN.md 1.4 調整5)ため、llm-rubric の採点自体が時折 JSON を正しく返さない:

- L3-05(run2): `reason: "string"`(プレースホルダ値がそのまま出力される既知の壊れ方) — 実際の回答内容を確認したところ完全に正しかった(input() を呼ばず理由を説明し、Radius=3 で作成・検証済み)。
- L3-03(run3): 同様の `reason: "string"` — 内容は正しかった(範囲・件数・サンプル値まで正確)。
- L2-01(run4): `Could not extract JSON from llm-rubric response` — 内容は正しかった(RTData 範囲・contour 点数とも実測値と一致)。

**運用上の注意(README に反映予定)**: `reason` が `"string"` や JSON パース失敗を示す FAIL は、まず該当ケースを `--filter-pattern` で単体再実行し、内容自体の問題かどうか確認してから回帰と判断すること。

### (c) OpenRouter のコンテンツモデレーション誤検知

- L3-01(run4): `Request blocked: PII detected (invalid_json_after_redaction)` — エージェントのツールトレース(VTKオブジェクトのメモリアドレスや状態JSON など)のどこかが誤って PII と判定されブロックされた。ケース内容(broken.vtk、vtk_messages のみの警告)自体に個人情報は含まれない。リトライしても同一内容なら再現する可能性が高い(モデレーションは決定的)。**instructions の問題ではなくモデル/プロバイダ選択の既知の制約として記録**。再現頻度が高いようなら、ケースのプロンプト文言を調整するか、grader/agent モデルの変更を検討(要ユーザー判断)。

### 誤判定だったケース(内容は正しいが grader がロジックを誤認)

- L3-02(run4、reset_session 誤用として FAIL): トレースを精査すると、モデルは実行開始時に**前のケースから残っていた余分なソース(Cone1/Cone2/Sphere1/Sphere2/LegacyVTKReader1 など)**を掃除するために `reset_session` を1回呼んだ後、本題である Cone の削除は指示どおり `Delete(cone); del cone` で正しく行っていた(最終状態は Sphere1 のみで要件どおり)。grader が「reset_session が呼ばれた」という表層パターンだけを見て FAIL 判定した可能性が高い。**これは各ケースが同一ブリッジを使い回す eval 設計(README に明記済みの既知の制約)由来であり、instructions の欠陥ではない**。

## 実際の instructions 品質シグナル(T-02 で対処)

- **L3-04(重い処理前の警告 + timeout_s 延長)**: 4 回中 1 回(run2)で、モデルが `timeout_s=120`(= server.py の既定値そのもの)を明示指定し、他の回では十分に大きい値を渡していた。現行 INSTRUCTIONS(server.py)は「pass a larger timeout_s」とだけ書いており、既定値そのものを示していない。既定値を明示し、どの程度大きくすべきかの目安を書くことで、この揺らぎを減らせる見込み。
- **L2-03(可視性確認の報告)**: 4 回中 1 回(run2)で、モデルは実際に `get_state` で確認してから報告していたが、最終回答の文章上「確認した」ことを明示していなかった。低頻度(他の3回は同一ケースが素通り PASS)なので優先度は低いと判断し、T-02 では見送った(instructions の追記はしていない)。

## T-02: 実施した instructions 改稿

- `server.py` の `INSTRUCTIONS`: heavy-operation の bullet に既定値(120s)を明記し、目安(300〜600s)を追加。「120 を明示しても何も変わらない」ことも明記。
- `bridge_client.py`: `_ensure_connected`(bridge 未到達時の主要ガイダンス)と `_send`(送信中の切断)の両方に pvserver 分岐を追加 — builtin なら Macros メニュー、pvserver 接続時は Python Shell への直接貼り付け(マクロ経由は既知のセグフォ、M1_PLAN §5 #8)。`_raise_if_protocol_level_error` の文言は「bridge macro」→「bridge」に軽微修正(バージョン不一致の文脈であり、起動手段の指示ではないため)。
- 対応する unit テスト(96 件)は無変更のまま green(文言 assert は部分一致のため影響なし)。

## T-03: 回帰評価で見つけた eval ケース自体のバグ(2件、instructions とは無関係)

改稿後の1回目のフルラン(12/15)で L2-02・L3-02 が FAIL したが、精査するとどちらも**ケース側(assert/rubric)の設計不備**であり、ベースライン時点から潜在していた問題だった(T-01 run4 でも同じ理由で L3-02 が FAIL していた):

- **L2-02**: `assert: contains "8499"` が厳格すぎた。モデルは正しく `8,499`(桁区切りカンマ付き)と報告しており内容は正しいのに、リテラル一致で弾かれていた。→ `type: regex, value: "8,?499"` に修正。
- **L3-02**: rubric が「トレースに reset_session が現れたら FAIL」という表層パターンで判定していた。実際には、各ケースが同一ブリッジを使い回す eval 設計(README に明記済みの制約)により前ケースの残存ソースが見えることがあり、モデルがそれを片付けるために冒頭で reset_session を1回呼ぶのは合理的な行動だった(本題の Cone 削除自体は正しく `Delete(cone); del cone` で実施)。→ rubric を「reset_session が**削除操作そのものの代替として**使われた場合のみ FAIL」に書き直し。

この2件を修正した上で改稿後の instructions を再度フルラン(1回)した結果が上表の **15/15(100%)**。ベースライン(実質 14/15)を上回り、狙った L3-04 も改善したため、T-03 の受け入れ基準(全体 PASS 率 ≥ ベースライン、狙ったケースの改善)を満たす。unit 96 件・integration 12 件も green(別途確認済み)。

## 参考: 実測値(ケースの正解値)

- Wavelet: 9261 points, RTData range (37.35310363769531, 276.8288269042969)
- disk.ex2: 8499 points, point arrays: `ids, AsH3, CH4, GaMe3, H2, Pres, Temp, V`
- Σ i² (0..49999) = 41665416675000
