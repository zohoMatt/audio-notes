// `mic` mode: the default input device through AVAudioEngine.

import AVFoundation
import CoreAudio
import Foundation

final class MicCapture {
    private let engine = AVAudioEngine()
    private let writer: FrameWriter
    private var observer: NSObjectProtocol?

    init(writer: FrameWriter) {
        self.writer = writer
    }

    func start() throws {
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            finish(.noDevice, "no input device")
        }
        let rate = format.sampleRate
        let writer = self.writer
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, when in
            let frames = Int(buffer.frameLength)
            guard frames > 0, let data = buffer.floatChannelData else { return }
            let channels = Int(buffer.format.channelCount)
            var mono = [Float](repeating: 0, count: frames)
            if buffer.format.isInterleaved {
                let samples = data[0]
                for i in 0..<frames {
                    var sum: Float = 0
                    for c in 0..<channels { sum += samples[i * channels + c] }
                    mono[i] = sum
                }
            } else {
                for c in 0..<channels {
                    let samples = data[c]
                    for i in 0..<frames { mono[i] += samples[i] }
                }
            }
            if channels > 1 {
                let k = 1 / Float(channels)
                for i in 0..<frames { mono[i] *= k }
            }
            let host = when.isHostTimeValid ? HostClock.nanos(when.hostTime) : 0
            writer.writeSamples(mono, sampleRate: rate, hostNanos: host)
        }
        observer = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main
        ) { _ in
            finish(.deviceChanged, "the audio input configuration changed")
        }
        engine.prepare()
        try engine.start()
        let name = (try? defaultDevice(output: false)).flatMap(deviceName) ?? "default input"
        writer.writeReady(sampleRate: rate, deviceName: name)
        logLine("microphone capture started on \(name) (\(Int(rate)) Hz, \(format.channelCount) ch)")
    }

    func stop() {
        if let observer { NotificationCenter.default.removeObserver(observer) }
        observer = nil
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
    }
}

func runMic(writer: FrameWriter) -> Never {
    stopOnParentRequest()
    DispatchQueue.main.async {
        switch Permissions.microphoneStatus() {
        case "authorized":
            startMic(writer: writer)
        case "undetermined":
            // Shows the system prompt (attributed to the app that started us, e.g. Terminal).
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                DispatchQueue.main.async {
                    if granted {
                        startMic(writer: writer)
                    } else {
                        finish(.permissionDenied, "microphone permission denied")
                    }
                }
            }
        default:
            finish(.permissionDenied, "microphone permission denied")
        }
    }
    dispatchMain()
}

private func startMic(writer: FrameWriter) {
    let mic = MicCapture(writer: writer)
    addCleanup { mic.stop() }
    do {
        try mic.start()
    } catch {
        finish(.failure, "could not start the microphone: \(error)")
    }
    exitWhenDefaultDeviceChanges(output: false)
}
