# v1 narration voice: Windows SAPI (System.Speech) -- zero-install, free, local.
# Swappable for ElevenLabs/Piper later; this proves the pipeline end-to-end today.
#   Rate is SAPI's -10..10 scale; -2 is an unrushed pace (default 0 rushes).
param(
    [string]$In  = "$PSScriptRoot\assets\video_zero_narration.txt",
    [string]$Out = "$PSScriptRoot\assets\video_zero_narration.wav",
    [int]$Rate   = -2
)
Add-Type -AssemblyName System.Speech
$syn = New-Object System.Speech.Synthesis.SpeechSynthesizer
$syn.Rate = $Rate
$syn.Volume = 100
$text = [System.IO.File]::ReadAllText($In, [System.Text.Encoding]::UTF8)
$syn.SetOutputToWaveFile($Out)
$syn.Speak($text)
$voice = $syn.Voice.Name
$syn.Dispose()
Write-Output "wrote $Out  (voice: $voice, rate $Rate)"
