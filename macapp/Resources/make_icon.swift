// make_icon.swift — generates a custom app icon for Reading Tracker.
// Renders a squircle background, an open book, and a stopwatch dial overlay,
// emitting all sizes required by AppIcon.iconset.
//
// Usage: swift make_icon.swift <output_iconset_dir>

import Foundation
import AppKit

let amber       = NSColor(calibratedRed: 0.99, green: 0.69, blue: 0.21, alpha: 1.0)
let burntOrange = NSColor(calibratedRed: 0.86, green: 0.31, blue: 0.10, alpha: 1.0)
let cream       = NSColor(calibratedRed: 0.99, green: 0.97, blue: 0.92, alpha: 1.0)
let pageInk     = NSColor(calibratedRed: 0.78, green: 0.50, blue: 0.20, alpha: 0.55)
let inkBlue     = NSColor(calibratedRed: 0.15, green: 0.24, blue: 0.50, alpha: 1.0)
let dialFace    = NSColor(calibratedRed: 1.00, green: 0.99, blue: 0.97, alpha: 1.0)

func render(size: Int, to url: URL) {
    let s = CGFloat(size)
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: size, pixelsHigh: size,
        bitsPerSample: 8, samplesPerPixel: 4,
        hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 32
    ) else { fatalError("rep alloc failed at size \(size)") }

    NSGraphicsContext.saveGraphicsState()
    defer { NSGraphicsContext.restoreGraphicsState() }
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    ctx.imageInterpolation = .high
    NSGraphicsContext.current = ctx

    // ---- 1) Squircle background gradient ----
    let bg = NSRect(x: 0, y: 0, width: s, height: s)
    let cornerR = s * 0.225
    let bgPath = NSBezierPath(roundedRect: bg, xRadius: cornerR, yRadius: cornerR)
    NSGraphicsContext.saveGraphicsState()
    bgPath.addClip()
    NSGradient(colors: [amber, burntOrange])!.draw(in: bg, angle: 270)

    // subtle top sheen
    let sheen = NSGradient(colors: [
        NSColor(white: 1, alpha: 0.18),
        NSColor(white: 1, alpha: 0.0)
    ])!
    sheen.draw(in: NSRect(x: 0, y: s*0.55, width: s, height: s*0.45), angle: 270)
    NSGraphicsContext.restoreGraphicsState()

    // ---- 2) Open book ----
    let bookCx = s/2, bookCy = s * 0.43
    let bookW = s * 0.66, bookH = s * 0.46
    let pageGap = s * 0.014
    let leftPage  = NSRect(x: bookCx - bookW/2,    y: bookCy - bookH/2,
                           width:  bookW/2 - pageGap, height: bookH)
    let rightPage = NSRect(x: bookCx + pageGap,    y: bookCy - bookH/2,
                           width:  bookW/2 - pageGap, height: bookH)

    NSGraphicsContext.saveGraphicsState()
    let pageShadow = NSShadow()
    pageShadow.shadowColor = NSColor(white: 0, alpha: 0.30)
    pageShadow.shadowBlurRadius = s * 0.030
    pageShadow.shadowOffset = NSSize(width: 0, height: -s*0.014)
    pageShadow.set()
    cream.setFill()
    NSBezierPath(roundedRect: leftPage,  xRadius: s*0.012, yRadius: s*0.012).fill()
    NSBezierPath(roundedRect: rightPage, xRadius: s*0.012, yRadius: s*0.012).fill()
    NSGraphicsContext.restoreGraphicsState()

    // page text lines
    pageInk.setFill()
    let lineH = s * 0.018
    let lineSpacing = bookH * 0.165
    for i in 0..<4 {
        let y = bookCy + bookH/2 - bookH*0.20 - CGFloat(i)*lineSpacing
        let leftW  = leftPage.width  * (0.74 - CGFloat(i)*0.07)
        let rightW = rightPage.width * (0.74 - CGFloat(i)*0.09)
        NSBezierPath(roundedRect:
            NSRect(x: leftPage.minX + leftPage.width*0.10, y: y, width: leftW, height: lineH),
            xRadius: lineH/2, yRadius: lineH/2).fill()
        NSBezierPath(roundedRect:
            NSRect(x: rightPage.minX + rightPage.width*0.10, y: y, width: rightW, height: lineH),
            xRadius: lineH/2, yRadius: lineH/2).fill()
    }

    // ---- 3) Stopwatch dial overlapping bottom-right of book ----
    let dialCx = s * 0.74, dialCy = s * 0.27
    let dialR  = s * 0.18
    let dialRect = NSRect(x: dialCx - dialR, y: dialCy - dialR, width: dialR*2, height: dialR*2)

    // crown (the little knob on top) — drawn first so it sits behind face
    let crownW = s * 0.05, crownH = s * 0.045
    let crownRect = NSRect(x: dialCx - crownW/2,
                           y: dialCy + dialR - s*0.005,
                           width: crownW, height: crownH)
    inkBlue.setFill()
    NSBezierPath(roundedRect: crownRect, xRadius: s*0.010, yRadius: s*0.010).fill()

    // dial face with shadow
    NSGraphicsContext.saveGraphicsState()
    let dialShadow = NSShadow()
    dialShadow.shadowColor = NSColor(white: 0, alpha: 0.35)
    dialShadow.shadowBlurRadius = s * 0.030
    dialShadow.shadowOffset = NSSize(width: 0, height: -s*0.014)
    dialShadow.set()
    dialFace.setFill()
    NSBezierPath(ovalIn: dialRect).fill()
    NSGraphicsContext.restoreGraphicsState()

    // bezel
    inkBlue.setStroke()
    let bezel = NSBezierPath(ovalIn: dialRect.insetBy(dx: s*0.008, dy: s*0.008))
    bezel.lineWidth = s * 0.013
    bezel.stroke()

    // 4 cardinal tick marks
    let tickInner = dialR * 0.78, tickOuter = dialR * 0.92
    for angleDeg: CGFloat in [0, 90, 180, 270] {
        let a = angleDeg * .pi / 180
        let p = NSBezierPath()
        p.move(to: NSPoint(x: dialCx + cos(a)*tickInner, y: dialCy + sin(a)*tickInner))
        p.line(to: NSPoint(x: dialCx + cos(a)*tickOuter, y: dialCy + sin(a)*tickOuter))
        p.lineWidth = s * 0.013
        p.lineCapStyle = .round
        inkBlue.setStroke()
        p.stroke()
    }

    // accent progress arc from 12 o'clock clockwise to ~4 o'clock
    let arc = NSBezierPath()
    arc.appendArc(withCenter: NSPoint(x: dialCx, y: dialCy),
                  radius: dialR*0.92,
                  startAngle: 90, endAngle: 0, clockwise: true)
    arc.lineWidth = s * 0.030
    arc.lineCapStyle = .round
    burntOrange.setStroke()
    arc.stroke()

    // hand pointing to ~2 o'clock
    let handAngle: CGFloat = 60 * .pi / 180
    let handLen = dialR * 0.72
    let hand = NSBezierPath()
    hand.move(to: NSPoint(x: dialCx, y: dialCy))
    hand.line(to: NSPoint(x: dialCx + cos(handAngle)*handLen,
                          y: dialCy + sin(handAngle)*handLen))
    hand.lineWidth = s * 0.022
    hand.lineCapStyle = .round
    inkBlue.setStroke()
    hand.stroke()

    // hub
    let hubR = s * 0.022
    inkBlue.setFill()
    NSBezierPath(ovalIn: NSRect(x: dialCx-hubR, y: dialCy-hubR,
                                width: hubR*2, height: hubR*2)).fill()

    // ---- 4) Save PNG ----
    guard let png = rep.representation(using: .png, properties: [:]) else {
        fatalError("png encode failed")
    }
    try! png.write(to: url)
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write(Data("usage: swift make_icon.swift <iconset_dir>\n".utf8))
    exit(2)
}
let outDir = URL(fileURLWithPath: args[1])
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

let mappings: [(name: String, size: Int)] = [
    ("icon_16x16.png",       16),
    ("icon_16x16@2x.png",    32),
    ("icon_32x32.png",       32),
    ("icon_32x32@2x.png",    64),
    ("icon_128x128.png",    128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png",    256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png",    512),
    ("icon_512x512@2x.png", 1024),
]
for m in mappings {
    render(size: m.size, to: outDir.appendingPathComponent(m.name))
    print("rendered \(m.name) (\(m.size)px)")
}
