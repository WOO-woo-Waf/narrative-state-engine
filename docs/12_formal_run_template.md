# 正式续写可复用参数模板（只改 3 个变量）

本模板用于“先分析再续写”的正式运行流程，默认开启：

- `--analyze-first`
- `--persist`

你每次只需要改 3 个变量：

1. `InputFile`：输入小说文件名
2. `Instruction`：你的续写指令
3. `Rounds`：续写轮数（`1` 表示只跑一轮）

## PowerShell 模板

在仓库根目录执行：

```powershell
& {
  $ErrorActionPreference = "Stop"
  conda activate novel-create

  # ===== 只改这 3 个变量 =====
  $InputFile = "白丝小师妹，淫堕为魔修胯下的邪媚仙女 作者：Anckon.txt"
  $Instruction = @"
我要的情节是女主角被重塑造了一个身体，过程和前面情节的抽取灵魂差不多，要有相似的情节元素和过程，要一个章节，1万字的具体内容，主角都差不多。
"@
  $Rounds = 3
  # ==========================

  # 固定配置（通常不需要改）
  $NovelDir = "novels_input"
  $OutputDir = "novels_output"
  $Model = "deepseek-v3-2-251201"
  $ChapterNumber = 2
  $AnalysisMaxChunkChars = 1800

  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $StoryId = "story-" + [System.IO.Path]::GetFileNameWithoutExtension($InputFile)

  $currentInput = $InputFile
  for ($i = 1; $i -le $Rounds; $i++) {
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($currentInput)
    $outTxt = "$stem.$stamp.part$i.continued.txt"
    $outState = "$stem.$stamp.part$i.state.json"
    $outAnalysis = "$stem.$stamp.part$i.analysis.json"

    python run_novel_continuation.py `
      --novel-dir $NovelDir `
      --input-file $currentInput `
      --instruction $Instruction `
      --model $Model `
      --story-id $StoryId `
      --chapter-number $ChapterNumber `
      --analyze-first `
      --analysis-max-chunk-chars $AnalysisMaxChunkChars `
      --persist `
      --output-dir $OutputDir `
      --output-file $outTxt `
      --analysis-file $outAnalysis `
      --state-file $outState

    # 下一轮以上一轮正文作为输入
    $currentInput = $outTxt
  }
}
```

## 如何判断跑成功

每轮终端出现以下字段即可：

- `commit_status: CommitStatus.COMMITTED`
- `analysis_output: ...`
- `continuation_output: ...`
- `state_snapshot: ...`

## 输出文件说明

- `*.analysis.json`：分析资产（风格片段、事件样例、story bible）
- `*.continued.txt`：续写正文
- `*.state.json`：完整状态快照（含检索引用、版本号、校验结果）

## 常用建议

- 首次建议 `Rounds=1` 做冒烟，确认指令方向正确后再提高轮数。
- 正式长章节建议分轮生成（例如 `Rounds=3~8`），再人工精修串联。