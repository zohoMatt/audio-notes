"""Debug: print the audio devices the capture layer sees."""

import json

from audio_notes.capture.win_wasapi import list_devices

if __name__ == "__main__":
    print(json.dumps(list_devices(), indent=2, ensure_ascii=False))
