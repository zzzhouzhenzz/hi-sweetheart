// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "podcast-bookmark",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "podcast-bookmark", path: "Sources"),
    ]
)
