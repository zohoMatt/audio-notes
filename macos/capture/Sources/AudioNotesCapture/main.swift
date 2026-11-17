// audio-notes-capture: macOS capture helper for Audio Notes.
//
//   audio-notes-capture tap                     system audio (process tap) -> framed PCM on stdout
//   audio-notes-capture mic                     default microphone         -> framed PCM on stdout
//   audio-notes-capture list                    audio devices as JSON
//   audio-notes-capture permissions [--request] permission status as JSON (optionally ask first)
//
// Frame format and exit codes: Protocol.swift (mirrored in src/audio_notes/capture/mac_tap.py).

import Foundation

signal(SIGPIPE, SIG_IGN)  // a closed stdout surfaces as EPIPE from write(), handled in FrameWriter

let arguments = Array(CommandLine.arguments.dropFirst())
let writer = FrameWriter()

switch arguments.first {
case "tap":
    if #available(macOS 14.2, *) {
        runTap(writer: writer)
    } else {
        finish(.unsupported, "system audio capture needs macOS 14.2 or later")
    }
case "mic":
    runMic(writer: writer)
case "list":
    runList()
case "permissions":
    runPermissions(request: arguments.dropFirst().contains("--request"))
default:
    logLine("usage: audio-notes-capture tap | mic | list | permissions [--request]")
    exit(ExitCode.usage.rawValue)
}
