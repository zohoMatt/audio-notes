// Wire protocol between this helper and src/audio_notes/capture/mac_tap.py.
// Keep the two in sync: frame layout, magic values and exit codes.
//
// stdout carries binary frames, all little-endian, each a 32-byte header plus a payload:
//
//   offset size  field
//   0      4     magic        "ANCR" = ready, "ANCF" = audio frame
//   4      4     sample_rate  u32, Hz
//   8      4     count        u32: ANCF = number of float32 samples; ANCR = byte length of the UTF-8 device name
//   12     4     flags        u32, reserved (0)
//   16     8     host_ns      u64: host time of the first sample, ns (0 = unknown); 0 for ANCR
//   24     8     sent_ns      u64: host time when the frame was written, ns
//   32     ...   payload      ANCF: count float32 mono samples in [-1, 1]; ANCR: the device name
//
// Exactly one ANCR is written, after capture has started; ANCF frames follow. Python uses
// `sent_ns - host_ns` (both on this process's clock) to back-date a frame from the moment it
// arrives, so the two processes never need a shared clock.
//
// stderr carries human-readable log lines. stdin is never read for data: EOF on stdin means the
// parent wants us to stop (or died), and we exit 0.

import CoreAudio
import Darwin
import Foundation

enum ExitCode: Int32 {
    case ok = 0
    case failure = 1
    case usage = 2
    case deviceChanged = 10  // the default device this mode follows changed: re-open on the new one
    case deviceLost = 11  // the device went away or stopped delivering
    case permissionDenied = 12  // microphone / system audio recording permission denied
    case unsupported = 13  // macOS too old for this mode (process taps need 14.2)
    case noDevice = 14  // no input / output device at all
    // System audio recording is still undetermined after asking: macOS will not grant it to the
    // app we were started from (seen with Claude / IDE-launched processes). The last stderr line
    // names that app ("... cannot be granted to <name>").
    case permissionUnavailable = 15
}

private let exitLock = NSLock()
private var cleanupActions: [() -> Void] = []

/// Runs `action` (in reverse registration order) before the helper exits through `finish`.
func addCleanup(_ action: @escaping () -> Void) {
    exitLock.lock()
    cleanupActions.append(action)
    exitLock.unlock()
}

func logLine(_ message: String) {
    FileHandle.standardError.write(Data(("audio-notes-capture: " + message + "\n").utf8))
}

/// The only way out once capture is running: release Core Audio objects, then exit with `code`.
/// A second caller (another thread) blocks on the lock until the process is gone.
func finish(_ code: ExitCode, _ message: String? = nil) -> Never {
    exitLock.lock()
    if let message { logLine(message) }
    for action in cleanupActions.reversed() { action() }
    exit(code.rawValue)
}

enum HostClock {
    private static let timebase: mach_timebase_info_data_t = {
        var tb = mach_timebase_info_data_t()
        mach_timebase_info(&tb)
        return tb
    }()

    /// mach_absolute_time ticks -> nanoseconds (1:1 on Apple Silicon, 125/3 on Intel).
    static func nanos(_ ticks: UInt64) -> UInt64 {
        let numer = UInt64(timebase.numer), denom = UInt64(max(timebase.denom, 1))
        return ticks / denom * numer + (ticks % denom) * numer / denom
    }

    static func nowNanos() -> UInt64 { nanos(mach_absolute_time()) }
}

final class FrameWriter {
    private let queue = DispatchQueue(label: "audio-notes-capture.writer")

    func writeReady(sampleRate: Double, deviceName: String) {
        let name = Array(deviceName.utf8)
        queue.async {
            var bytes = FrameWriter.header("ANCR", rate: sampleRate, count: UInt32(name.count), host: 0)
            bytes.append(contentsOf: name)
            FrameWriter.writeAll(bytes)
        }
    }

    /// Called from audio threads: only copies and hands off, the blocking write happens on `queue`.
    func writeSamples(_ samples: [Float], sampleRate: Double, hostNanos: UInt64) {
        guard !samples.isEmpty else { return }
        queue.async {
            var bytes = FrameWriter.header("ANCF", rate: sampleRate, count: UInt32(samples.count), host: hostNanos)
            bytes.reserveCapacity(bytes.count + samples.count * 4)
            samples.withUnsafeBytes { bytes.append(contentsOf: $0) }  // float32, native = little-endian
            FrameWriter.writeAll(bytes)
        }
    }

    private static func header(_ magic: String, rate: Double, count: UInt32, host: UInt64) -> [UInt8] {
        var b = [UInt8]()
        b.reserveCapacity(32)
        b.append(contentsOf: Array(magic.utf8))
        func put<T: FixedWidthInteger>(_ value: T) {
            withUnsafeBytes(of: value.littleEndian) { b.append(contentsOf: $0) }
        }
        put(UInt32(max(0, rate.rounded())))
        put(count)
        put(UInt32(0))
        put(host)
        put(HostClock.nowNanos())
        return b
    }

    private static func writeAll(_ bytes: [UInt8]) {
        bytes.withUnsafeBytes { raw in
            guard let base = raw.baseAddress else { return }
            var offset = 0
            while offset < raw.count {
                let n = Darwin.write(STDOUT_FILENO, base + offset, raw.count - offset)
                if n < 0 {
                    if errno == EINTR { continue }
                    finish(.ok)  // the reader is gone (EPIPE): nothing left to do
                }
                offset += n
            }
        }
    }
}

/// Exit cleanly on SIGTERM / SIGINT or when stdin reaches EOF (parent closed it or died).
private var signalSources: [DispatchSourceSignal] = []

func stopOnParentRequest() {
    for sig in [SIGTERM, SIGINT] {
        signal(sig, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
        source.setEventHandler { finish(.ok) }
        source.resume()
        signalSources.append(source)
    }
    Thread.detachNewThread {
        var buffer = [UInt8](repeating: 0, count: 256)
        while true {
            let n = read(STDIN_FILENO, &buffer, buffer.count)
            if n == 0 || (n < 0 && errno != EINTR) { finish(.ok) }
        }
    }
}

/// Average all channels of a Core Audio buffer list (interleaved or not) into one mono buffer.
/// Assumes 32-bit float samples (checked by the caller against the stream format).
func downmix(_ list: UnsafeMutableAudioBufferListPointer) -> [Float] {
    var out: [Float] = []
    var channels = 0
    for buffer in list {
        guard let data = buffer.mData else { continue }
        let ch = max(1, Int(buffer.mNumberChannels))
        let frames = Int(buffer.mDataByteSize) / (MemoryLayout<Float>.size * ch)
        guard frames > 0 else { continue }
        if out.isEmpty { out = [Float](repeating: 0, count: frames) }
        let samples = data.assumingMemoryBound(to: Float.self)
        for i in 0..<min(frames, out.count) {
            var sum: Float = 0
            for c in 0..<ch { sum += samples[i * ch + c] }
            out[i] += sum
        }
        channels += ch
    }
    if channels > 1 {
        let k = 1 / Float(channels)
        for i in out.indices { out[i] *= k }
    }
    return out
}
