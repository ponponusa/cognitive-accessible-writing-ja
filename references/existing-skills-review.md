# 既存スキルの簡易レビュー

調査日: 2026-09-08

## 参照範囲とライセンス

この文書は、既存の取り組みと本スキルの設計範囲を比較するための記録です。
参照した版を以下に固定します。ライセンス欄は各参考元のものであり、本リポジトリの MIT 表記で上書きするものではありません。

| 対象 | 参照した版の本文 | 参考元のライセンス | 本草案で参考にした範囲 |
|---|---|---|---|
| attention-kind | [2714c965](https://github.com/alexgreensh/attention-span/blob/2714c965e6be1fa2597510e66651e63bc67cb448/skills/attention-kind/SKILL.md) | [AGPL-3.0](https://github.com/alexgreensh/attention-span/blob/2714c965e6be1fa2597510e66651e63bc67cb448/LICENSE) | 結論の位置、詳しさの選択、重要情報の保持についての比較 |
| cognitive-a11y | [a02cf6e2](https://github.com/KyaniteLabs/tastecheck/blob/a02cf6e29704a55003604ff204547e83c6ac015c/skills/cognitive-a11y/SKILL.md) | [MIT](https://github.com/KyaniteLabs/tastecheck/blob/a02cf6e29704a55003604ff204547e83c6ac015c/LICENSE) | 文章とUIの対象範囲、読み手の負担を観察する方針の比較 |
| information-accessibility-practice | [a6c1f76f](https://github.com/Nagi-Inaba/information-accessibility-skill/blob/a6c1f76f17d3c5dd62d3bc7e036a65547b4b629d/codex/skills/information-accessibility-practice/SKILL.md) | [MIT](https://github.com/Nagi-Inaba/information-accessibility-skill/blob/a6c1f76f17d3c5dd62d3bc7e036a65547b4b629d/LICENSE) | 情報への参加過程と、機械検査・人による評価の役割の比較 |

一般的な文章原則の根拠は [研究上の根拠と限界](evidence-basis.md) に示します。
参考元の本文・具体例を転載するための一覧ではありません。転載や翻訳を追加する場合は、その版の利用条件を確認します。

公開前レビューでは、参考元の具体例と類似していた変換例を、資料室の貸出条件を題材とする新しい例に差し替えました。
条件の上限、日数の数え始め、対象外の図書、休室日の扱いを照合する目的で作成しています。

## attention-kind

強み:

- 最初の一文に要点を置く
- 情報の欠落と埋没を別の失敗として扱う
- 深い説明を求められた場合は、短文化を解除する
- 数値、条件、警告を削らない

本草案で補う点:

- 太字や矢印の固定様式を必須にしない
- 日本語の文法上の曖昧さへ対応する
- 括弧の役割別変換を追加する
- 設定可能なプロファイルと実験計画を追加する

Repository: `alexgreensh/attention-span`

## cognitive-a11y

強み:

- 利用時にどこで操作や理解が進みにくくなるかを観察する方針を明記する
- 平易さ、予測可能性、低い記憶負荷を扱う
- UI、フォーム、オンボーディングなど文章以外も扱う
- W3C COGA を根拠として示す

本草案で補う点:

- AIが生成した日本語文章の後処理へ範囲を絞る
- 意味台帳を用いた意味保存を追加する
- 括弧を独立した検証変数にする
- 読解時間、理解度、条件見落としを測る評価手順を同梱する

Repository: `KyaniteLabs/tastecheck`, skill: `cognitive-a11y`

## information-accessibility-practice

強み:

- 情報への到達、受領、理解、参加、継続を一連の流れとして扱う
- AIによる検査と人間による適合判定を分ける
- 文書、Web、イベントなど広い対象を扱う

本草案で補う点:

- 監査スキルではなく、文章変換スキルとして実行規則を具体化する
- 日本語の低中断プロファイルを提供する

Repository: `Nagi-Inaba/information-accessibility-skill`

## 総評

既存スキルは十分に利用価値があります。  
新規作成の理由は「既存に何もない」からではありません。

新規作成の主な価値は次の四点です。

1. 日本語固有の問題へ対応する
2. 読み手が希望する順序、詳しさ、表現に合わせて設定する
3. 読みやすさと意味保存を同時に検査する
4. 括弧処理を含む各規則の効果を個別に検証する
