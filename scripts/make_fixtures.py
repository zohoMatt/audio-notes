"""Generate small English WAV fixtures with Windows' built-in System.Speech.

Two voices: "Microsoft David Desktop" stands in for `them`, "Microsoft Zira Desktop" for `me`.
Output: tests/fixtures/*.wav (16 kHz mono 16-bit) and tests/fixtures/manifest.json.

NOTE: synthetic TTS speech is much cleaner than real meeting audio (no noise, no
overlap, regular pacing, no disfluencies), so accuracy measured on these files is
optimistic. Use them for plumbing/regression tests, not to judge real-world WER.

Usage: uv run python scripts/make_fixtures.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

# name -> (voice, text, role)
FIXTURES = {
    "them_budget": (
        "Microsoft David Desktop",
        "The quarterly budget review is scheduled for Thursday afternoon.",
        "them",
    ),
    "them_release": (
        "Microsoft David Desktop",
        "We decided to postpone the release until the security audit is finished.",
        "them",
    ),
    "me_followup": (
        "Microsoft Zira Desktop",
        "I will send the updated project proposal to the whole team tomorrow morning.",
        "me",
    ),
    "me_question": (
        "Microsoft Zira Desktop",
        "Can you share the customer feedback summary before our next meeting?",
        "me",
    ),
}

PS_TEMPLATE = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice($env:FX_VOICE)
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($env:FX_PATH, $fmt)
$s.Speak($env:FX_TEXT)
$s.Dispose()
"""


def main() -> int:
    import os

    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, (voice, text, role) in FIXTURES.items():
        path = OUT / f"{name}.wav"
        env = dict(os.environ, FX_VOICE=voice, FX_PATH=str(path), FX_TEXT=text)
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_TEMPLATE],
            check=True,
            env=env,
        )
        manifest[f"{name}.wav"] = {"text": text, "voice": voice, "speaker": role}
        print(f"{path.name}: {path.stat().st_size / 1024:.0f} KiB")
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
