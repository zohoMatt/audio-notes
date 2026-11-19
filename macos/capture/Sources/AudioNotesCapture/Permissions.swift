// `permissions` mode and the permission checks used by `tap` / `mic`.
//
// Microphone: public AVCaptureDevice API.
// System audio recording: there is no public preflight API, and a denied tap just delivers
// silence. Like AudioCap we use the private TCC SPI (TCCAccessPreflight / TCCAccessRequest with
// the service "kTCCServiceAudioCapture"), loaded with dlopen so a missing symbol degrades to
// "unknown" instead of crashing. Not App Store safe; acceptable for a tool distributed outside it.

import AVFoundation
import Darwin
import Foundation

enum Permissions {
    static func microphoneStatus() -> String {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return "authorized"
        case .denied: return "denied"
        case .restricted: return "restricted"
        case .notDetermined: return "undetermined"
        @unknown default: return "unknown"
        }
    }

    static func requestMicrophone(timeout: TimeInterval) -> Bool {
        let done = DispatchSemaphore(value: 0)
        var granted = false
        AVCaptureDevice.requestAccess(for: .audio) { ok in
            granted = ok
            done.signal()
        }
        return done.wait(timeout: .now() + timeout) == .success && granted
    }
}

enum TCC {
    private typealias PreflightFn = @convention(c) (CFString, CFDictionary?) -> Int
    private typealias RequestFn = @convention(c) (CFString, CFDictionary?, @escaping @convention(block) (Bool) -> Void) -> Void

    private static let handle = dlopen("/System/Library/PrivateFrameworks/TCC.framework/Versions/A/TCC", RTLD_NOW)
    private static let service = "kTCCServiceAudioCapture" as CFString

    /// "authorized", "denied", "undetermined" or "unknown" (SPI unavailable).
    static func audioCaptureStatus() -> String {
        guard let lib = handle, let symbol = dlsym(lib, "TCCAccessPreflight") else { return "unknown" }
        let preflight = unsafeBitCast(symbol, to: PreflightFn.self)
        switch preflight(service, nil) {
        case 0: return "authorized"
        case 1: return "denied"
        default: return "undetermined"
        }
    }

    /// Shows the system prompt when undetermined. nil when the SPI is unavailable or timed out.
    static func requestAudioCapture(timeout: TimeInterval) -> Bool? {
        guard let lib = handle, let symbol = dlsym(lib, "TCCAccessRequest") else { return nil }
        let request = unsafeBitCast(symbol, to: RequestFn.self)
        let done = DispatchSemaphore(value: 0)
        var granted = false
        request(service, nil) { ok in
            granted = ok
            done.signal()
        }
        return done.wait(timeout: .now() + timeout) == .success ? granted : nil
    }
}

/// The app macOS credits our permission requests to (TCC's "responsible process"): Terminal for a
/// shell command, Audio Notes for the packaged app, Claude or an IDE when they started us.
enum Responsible {
    private typealias ResponsibleFn = @convention(c) (pid_t) -> pid_t

    /// Executable path of the responsible process, or nil when the private SPI is unavailable.
    static func executablePath() -> String? {
        let rtldDefault = UnsafeMutableRawPointer(bitPattern: -2)  // RTLD_DEFAULT
        guard let symbol = dlsym(rtldDefault, "responsibility_get_pid_responsible_for_pid") else { return nil }
        let pid = unsafeBitCast(symbol, to: ResponsibleFn.self)(getpid())
        guard pid > 0 else { return nil }
        var buffer = [CChar](repeating: 0, count: Int(MAXPATHLEN) * 4)  // PROC_PIDPATHINFO_MAXSIZE
        guard proc_pidpath(pid, &buffer, UInt32(buffer.count)) > 0 else { return nil }
        return String(cString: buffer)
    }

    /// The innermost .app around that executable (its bundle is what TCC records), else its name.
    static func appName() -> String {
        guard let path = executablePath() else { return "the app that started Audio Notes" }
        let parts = (path as NSString).pathComponents
        if let app = parts.last(where: { $0.hasSuffix(".app") }) { return String(app.dropLast(4)) }
        return (path as NSString).lastPathComponent
    }
}

/// `permissions [--request]`: prints {"microphone": status, "system_audio": status, "responsible": app} as JSON.
/// With --request, first asks for whatever is still undetermined (one system prompt each).
func runPermissions(request: Bool) -> Never {
    // Off the main thread: permission callbacks may be delivered on any queue, including main.
    DispatchQueue.global(qos: .userInitiated).async {
        if request {
            if Permissions.microphoneStatus() == "undetermined" {
                _ = Permissions.requestMicrophone(timeout: 300)
            }
            if TCC.audioCaptureStatus() == "undetermined" {
                _ = TCC.requestAudioCapture(timeout: 300)
            }
        }
        printJSON([
            "microphone": Permissions.microphoneStatus(),
            "system_audio": TCC.audioCaptureStatus(),
            "responsible": Responsible.appName(),
        ])
        exit(ExitCode.ok.rawValue)
    }
    dispatchMain()
}
