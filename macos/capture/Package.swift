// swift-tools-version:5.9
// audio-notes-capture: the macOS capture helper. Built by `swift build -c release` (the wheel's
// hatch hook does this on macOS, see hatch_build.py); the Python side is capture/mac_tap.py.
import PackageDescription

let package = Package(
    name: "AudioNotesCapture",
    platforms: [.macOS(.v14)],  // the process tap itself needs 14.2; checked at run time
    products: [
        .executable(name: "audio-notes-capture", targets: ["AudioNotesCapture"]),
    ],
    targets: [
        .executableTarget(
            name: "AudioNotesCapture",
            path: "Sources/AudioNotesCapture",
            linkerSettings: [
                .linkedFramework("CoreAudio"),
                .linkedFramework("AudioToolbox"),
                .linkedFramework("AVFoundation"),
            ]
        ),
    ]
)
