// `tap` mode: system audio via a Core Audio process tap (macOS 14.2+).
//
// A global stereo tap of everything the system plays is wrapped in a private aggregate device
// whose main sub-device is the current default output; an IO proc on that aggregate device
// receives the tapped audio. This is the approach of Apple's "Capturing system audio with Core
// Audio taps" sample and of open-source tools such as AudioCap / audiotee.
//
// Permission: "System Audio Recording Only" (Privacy & Security > Screen & System Audio Recording),
// attributed to the app that started us (the terminal for `uv tool install` users). When it is
// denied the tap does not fail: it delivers silence. So we preflight it with the private TCC SPI
// (see Permissions.swift) and exit with `permissionDenied` when it reports "denied".

import AudioToolbox
import CoreAudio
import Foundation

@available(macOS 14.2, *)
final class TapCapture {
    private var tapID = AudioObjectID(kAudioObjectUnknown)
    private var aggregateID = AudioObjectID(kAudioObjectUnknown)
    private var procID: AudioDeviceIOProcID?
    private let ioQueue = DispatchQueue(label: "audio-notes-capture.tap-io", qos: .userInteractive)
    private let writer: FrameWriter
    private(set) var outputDevice = AudioObjectID(kAudioObjectUnknown)

    init(writer: FrameWriter) {
        self.writer = writer
    }

    func start() throws {
        outputDevice = try defaultDevice(output: true)
        guard let outputUID = deviceUID(outputDevice) else {
            throw CoreAudioError(call: "default output device UID", status: -1)
        }
        let outputName = deviceName(outputDevice) ?? outputUID

        let description = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
        description.uuid = UUID()
        description.name = "Audio Notes system audio"
        description.isPrivate = true
        description.muteBehavior = .unmuted
        try check(AudioHardwareCreateProcessTap(description, &tapID), "AudioHardwareCreateProcessTap")

        let aggregate: [String: Any] = [
            kAudioAggregateDeviceNameKey: "Audio Notes Tap",
            kAudioAggregateDeviceUIDKey: UUID().uuidString,
            kAudioAggregateDeviceMainSubDeviceKey: outputUID,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outputUID]],
            kAudioAggregateDeviceTapListKey: [[
                kAudioSubTapDriftCompensationKey: true,
                kAudioSubTapUIDKey: description.uuid.uuidString,
            ]],
        ]
        try check(AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &aggregateID),
                  "AudioHardwareCreateAggregateDevice")

        let format: AudioStreamBasicDescription = try readValue(
            tapID, kAudioTapPropertyFormat, initial: AudioStreamBasicDescription())
        guard format.mFormatID == AudioFormatID(kAudioFormatLinearPCM),
              format.mFormatFlags & AudioFormatFlags(kAudioFormatFlagIsFloat) != 0,
              format.mBitsPerChannel == 32, format.mSampleRate > 0 else {
            throw CoreAudioError(call: "unexpected tap format (want 32-bit float PCM)", status: -1)
        }
        // The tap's format reports its own rate (48 kHz here), but the IO proc runs on the
        // aggregate device's clock, i.e. the output device's nominal rate: a 44.1 kHz output
        // delivers 44100 samples/s. Label frames with the aggregate rate or audio plays ~9% fast.
        let deviceRate: Float64 = (try? readValue(aggregateID, kAudioDevicePropertyNominalSampleRate,
                                                  initial: Float64(0))) ?? 0
        let rate = deviceRate > 0 ? deviceRate : format.mSampleRate
        if deviceRate > 0, deviceRate != format.mSampleRate {
            logLine("tap format says \(Int(format.mSampleRate)) Hz; using the device rate \(Int(deviceRate)) Hz")
        }
        let writer = self.writer

        try check(AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateID, ioQueue) { _, inputData, inputTime, _, _ in
            let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inputData))
            let mono = downmix(buffers)
            let time = inputTime.pointee
            let host = time.mFlags.contains(.hostTimeValid) ? HostClock.nanos(time.mHostTime) : 0
            writer.writeSamples(mono, sampleRate: rate, hostNanos: host)
        }, "AudioDeviceCreateIOProcIDWithBlock")
        try check(AudioDeviceStart(aggregateID, procID), "AudioDeviceStart")
        writer.writeReady(sampleRate: rate, deviceName: outputName)
        logLine("system audio tap started on \(outputName) (\(Int(rate)) Hz, \(format.mChannelsPerFrame) ch)")
    }

    func stop() {
        if let procID {
            AudioDeviceStop(aggregateID, procID)
            AudioDeviceDestroyIOProcID(aggregateID, procID)
            self.procID = nil
        }
        if aggregateID != AudioObjectID(kAudioObjectUnknown) {
            AudioHardwareDestroyAggregateDevice(aggregateID)
            aggregateID = AudioObjectID(kAudioObjectUnknown)
        }
        if tapID != AudioObjectID(kAudioObjectUnknown) {
            AudioHardwareDestroyProcessTap(tapID)
            tapID = AudioObjectID(kAudioObjectUnknown)
        }
    }
}

@available(macOS 14.2, *)
func runTap(writer: FrameWriter) -> Never {
    if TCC.audioCaptureStatus() == "denied" {
        finish(.permissionDenied, "system audio recording permission denied")
    }
    let tap = TapCapture(writer: writer)
    addCleanup { tap.stop() }
    do {
        try tap.start()
    } catch {
        tap.stop()
        finish((try? defaultDevice(output: true)) == nil ? .noDevice : .failure, "\(error)")
    }
    exitWhenDefaultDeviceChanges(output: true)
    exitWhenDeviceDies(tap.outputDevice)
    exitWhenSampleRateChanges(tap.outputDevice)
    stopOnParentRequest()
    // An ungranted tap records silence without failing. "denied" exits above; "undetermined" is
    // normal while the first prompt is up, but if it lasts, the prompt was never answered or the
    // responsible app cannot be granted (seen when started from an app bundle without
    // NSAudioCaptureUsageDescription): say so instead of recording silence quietly.
    DispatchQueue.main.asyncAfter(deadline: .now() + 15) {
        let status = TCC.audioCaptureStatus()
        if status != "authorized" && status != "unknown" {
            logLine("warning: system audio recording permission is still \(status); recording silence until it is "
                    + "granted to the app that started Audio Notes")
        }
    }
    dispatchMain()
}
