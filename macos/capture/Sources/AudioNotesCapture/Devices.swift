// Core Audio property helpers, device enumeration (`list` mode) and default-device watching.

import CoreAudio
import Foundation

struct CoreAudioError: Error, CustomStringConvertible {
    let call: String
    let status: OSStatus
    var description: String { "\(call) failed (OSStatus \(status))" }
}

func check(_ status: OSStatus, _ call: String) throws {
    if status != noErr { throw CoreAudioError(call: call, status: status) }
}

let systemObject = AudioObjectID(kAudioObjectSystemObject)

func address(_ selector: AudioObjectPropertySelector,
             _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
}

func readValue<T>(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector,
                  _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal, initial: T) throws -> T {
    var addr = address(selector, scope)
    var value = initial
    var size = UInt32(MemoryLayout<T>.size)
    try check(AudioObjectGetPropertyData(object, &addr, 0, nil, &size, &value), "AudioObjectGetPropertyData")
    return value
}

func readString(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
    var addr = address(selector)
    var value: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(object, &addr, 0, nil, &size, &value) == noErr, let value else { return nil }
    return value.takeRetainedValue() as String
}

func defaultDevice(output: Bool) throws -> AudioObjectID {
    let selector = output ? kAudioHardwarePropertyDefaultOutputDevice : kAudioHardwarePropertyDefaultInputDevice
    let id: AudioObjectID = try readValue(systemObject, selector, initial: AudioObjectID(kAudioObjectUnknown))
    if id == AudioObjectID(kAudioObjectUnknown) {
        throw CoreAudioError(call: output ? "default output device" : "default input device", status: -1)
    }
    return id
}

func deviceName(_ id: AudioObjectID) -> String? { readString(id, kAudioObjectPropertyName) }

func deviceUID(_ id: AudioObjectID) -> String? { readString(id, kAudioDevicePropertyDeviceUID) }

func channelCount(_ id: AudioObjectID, input: Bool) -> Int {
    var addr = address(kAudioDevicePropertyStreamConfiguration,
                       input ? kAudioObjectPropertyScopeInput : kAudioObjectPropertyScopeOutput)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(id, &addr, 0, nil, &size) == noErr, size > 0 else { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, raw) == noErr else { return 0 }
    let list = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    return list.reduce(0) { $0 + Int($1.mNumberChannels) }
}

func allDevices() -> [AudioObjectID] {
    var addr = address(kAudioHardwarePropertyDevices)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(systemObject, &addr, 0, nil, &size) == noErr else { return [] }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.stride)
    guard !ids.isEmpty, AudioObjectGetPropertyData(systemObject, &addr, 0, nil, &size, &ids) == noErr else { return [] }
    return ids
}

/// `list` mode: one JSON object on stdout.
/// {"devices": [{"uid", "name", "inputs", "outputs", "sample_rate", "default_input", "default_output"}]}
func runList() -> Never {
    let defaultIn = try? defaultDevice(output: false)
    let defaultOut = try? defaultDevice(output: true)
    var devices: [[String: Any]] = []
    for id in allDevices() {
        let rate: Float64 = (try? readValue(id, kAudioDevicePropertyNominalSampleRate, initial: Float64(0))) ?? 0
        devices.append([
            "uid": deviceUID(id) ?? "",
            "name": deviceName(id) ?? "Device \(id)",
            "inputs": channelCount(id, input: true),
            "outputs": channelCount(id, input: false),
            "sample_rate": Int(rate),
            "default_input": id == defaultIn,
            "default_output": id == defaultOut,
        ])
    }
    printJSON(["devices": devices])
    exit(ExitCode.ok.rawValue)
}

func printJSON(_ object: Any) {
    guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else {
        finish(.failure, "could not encode JSON")
    }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

/// Exit with `deviceChanged` when the system default input / output device changes. Recorder then
/// re-opens every source on the new defaults (same path as the Windows watchdog).
func exitWhenDefaultDeviceChanges(output: Bool) {
    var addr = address(output ? kAudioHardwarePropertyDefaultOutputDevice : kAudioHardwarePropertyDefaultInputDevice)
    let status = AudioObjectAddPropertyListenerBlock(systemObject, &addr, DispatchQueue.main) { _, _ in
        finish(.deviceChanged, "the default \(output ? "output" : "input") device changed")
    }
    if status != noErr { logLine("could not watch the default device (OSStatus \(status))") }
}

/// Exit with `deviceChanged` when `device`'s nominal sample rate changes (Audio MIDI Setup, or an
/// app switching it): frames are labelled with the rate read at start, so re-open on the new one.
func exitWhenSampleRateChanges(_ device: AudioObjectID) {
    let initial: Float64 = (try? readValue(device, kAudioDevicePropertyNominalSampleRate, initial: Float64(0))) ?? 0
    var addr = address(kAudioDevicePropertyNominalSampleRate)
    let status = AudioObjectAddPropertyListenerBlock(device, &addr, DispatchQueue.main) { _, _ in
        let now: Float64 = (try? readValue(device, kAudioDevicePropertyNominalSampleRate, initial: Float64(0))) ?? 0
        if now != initial {
            finish(.deviceChanged, "the output sample rate changed (\(Int(initial)) -> \(Int(now)) Hz)")
        }
    }
    if status != noErr { logLine("could not watch the sample rate (OSStatus \(status))") }
}

/// Exit with `deviceLost` when `device` disappears (unplugged, Bluetooth disconnected).
func exitWhenDeviceDies(_ device: AudioObjectID) {
    var addr = address(kAudioDevicePropertyDeviceIsAlive)
    let status = AudioObjectAddPropertyListenerBlock(device, &addr, DispatchQueue.main) { _, _ in
        let alive: UInt32 = (try? readValue(device, kAudioDevicePropertyDeviceIsAlive, initial: UInt32(0))) ?? 0
        if alive == 0 { finish(.deviceLost, "the audio device went away") }
    }
    if status != noErr { logLine("could not watch the device (OSStatus \(status))") }
}
