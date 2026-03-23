import Foundation
import SQLite3

// MARK: - Constants

let podcastsDBPath = NSHomeDirectory()
    + "/Library/Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite"
let coreDataEpoch = Date(timeIntervalSinceReferenceDate: 0) // 2001-01-01

// MARK: - iTunes Lookup

struct PodcastInfo {
    let collectionId: Int
    let title: String
    let author: String
    let feedUrl: String
    let artworkUrl: String
    let webPageUrl: String
}

func lookupPodcast(storeId: Int) -> PodcastInfo? {
    let urlStr = "https://itunes.apple.com/lookup?id=\(storeId)&entity=podcast"
    guard let url = URL(string: urlStr) else { return nil }

    let sem = DispatchSemaphore(value: 0)
    var result: PodcastInfo?

    let task = URLSession.shared.dataTask(with: url) { data, _, error in
        defer { sem.signal() }
        guard let data = data, error == nil else { return }
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let results = json["results"] as? [[String: Any]],
              let item = results.first else { return }

        let collectionId = item["collectionId"] as? Int ?? storeId
        let title = item["collectionName"] as? String ?? "Unknown"
        let author = item["artistName"] as? String ?? ""
        let feedUrl = item["feedUrl"] as? String ?? ""
        // Convert 600x600 artwork to template format
        let artworkRaw = item["artworkUrl600"] as? String ?? ""
        let artworkTemplate = artworkRaw
            .replacingOccurrences(of: "600x600bb", with: "{w}x{h}bb.{f}")
        let webPageUrl = item["collectionViewUrl"] as? String ?? ""

        result = PodcastInfo(
            collectionId: collectionId,
            title: title,
            author: author,
            feedUrl: feedUrl,
            artworkUrl: artworkTemplate,
            webPageUrl: webPageUrl
        )
    }
    task.resume()
    sem.wait()
    return result
}

// MARK: - URL Parsing

func extractStoreId(from urlString: String) -> Int? {
    // Match patterns like:
    //   podcasts.apple.com/us/podcast/name/id1234567890
    //   podcasts.apple.com/us/podcast/id1234567890
    let pattern = #"podcasts\.apple\.com/.+?/id(\d+)"#
    guard let regex = try? NSRegularExpression(pattern: pattern),
          let match = regex.firstMatch(
              in: urlString,
              range: NSRange(urlString.startIndex..., in: urlString)
          ) else { return nil }

    if let range = Range(match.range(at: 1), in: urlString) {
        return Int(urlString[range])
    }
    return nil
}

// MARK: - SQLite Operations

// No-op stub for CoreData's custom SQLite function used in triggers.
// Without this, INSERTs fail because the triggers reference this function.
private let noopFunc: @convention(c) (
    OpaquePointer?, Int32, UnsafeMutablePointer<OpaquePointer?>?
) -> Void = { context, argc, argv in
    sqlite3_result_null(context)
}

func openDB() -> OpaquePointer? {
    var db: OpaquePointer?
    if sqlite3_open(podcastsDBPath, &db) != SQLITE_OK {
        fputs("Error: cannot open Podcasts database at \(podcastsDBPath)\n", stderr)
        return nil
    }
    // Register the CoreData trigger function as a no-op
    sqlite3_create_function(
        db, "NSCoreDataDATriggerUpdatedAffectedObjectValue",
        -1, SQLITE_UTF8, nil, noopFunc, nil, nil
    )
    return db
}

func podcastExists(db: OpaquePointer, storeId: Int) -> Bool {
    let sql = "SELECT Z_PK FROM ZMTPODCAST WHERE ZSTORECOLLECTIONID = ?"
    var stmt: OpaquePointer?
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return false }
    defer { sqlite3_finalize(stmt) }
    sqlite3_bind_int64(stmt, 1, Int64(storeId))
    return sqlite3_step(stmt) == SQLITE_ROW
}

func nextPrimaryKey(db: OpaquePointer) -> Int {
    let sql = "SELECT Z_MAX FROM Z_PRIMARYKEY WHERE Z_NAME = 'MTPodcast'"
    var stmt: OpaquePointer?
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return 1 }
    defer { sqlite3_finalize(stmt) }
    if sqlite3_step(stmt) == SQLITE_ROW {
        return Int(sqlite3_column_int64(stmt, 0)) + 1
    }
    return 1
}

func incrementPrimaryKey(db: OpaquePointer, newMax: Int) -> Bool {
    let sql = "UPDATE Z_PRIMARYKEY SET Z_MAX = ? WHERE Z_NAME = 'MTPodcast'"
    var stmt: OpaquePointer?
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return false }
    defer { sqlite3_finalize(stmt) }
    sqlite3_bind_int64(stmt, 1, Int64(newMax))
    return sqlite3_step(stmt) == SQLITE_DONE
}

func insertPodcast(db: OpaquePointer, info: PodcastInfo) -> Bool {
    let pk = nextPrimaryKey(db: db)
    let uuid = UUID().uuidString
    let addedDate = Date().timeIntervalSinceReferenceDate

    let sql = """
        INSERT INTO ZMTPODCAST (
            Z_PK, Z_ENT, Z_OPT,
            ZSUBSCRIBED, ZSTORECOLLECTIONID,
            ZADDEDDATE, ZMODIFIEDDATE,
            ZTITLE, ZAUTHOR, ZFEEDURL, ZUUID,
            ZWEBPAGEURL, ZARTWORKTEMPLATEURL,
            ZAUTODOWNLOAD, ZAUTODOWNLOADENABLED, ZDELETEPLAYEDEPISODES,
            ZHIDDEN, ZNOTIFICATIONS, ZORPHANEDFROMCLOUD,
            ZFLAGS, ZOFFERTYPES
        ) VALUES (
            ?, 9, 1,
            0, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            0, 0, 0,
            0, 0, 0,
            0, 0
        )
        """
    var stmt: OpaquePointer?
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
        fputs("Error preparing INSERT: \(String(cString: sqlite3_errmsg(db)))\n", stderr)
        return false
    }
    defer { sqlite3_finalize(stmt) }

    sqlite3_bind_int64(stmt, 1, Int64(pk))
    sqlite3_bind_int64(stmt, 2, Int64(info.collectionId))
    sqlite3_bind_double(stmt, 3, addedDate)
    sqlite3_bind_double(stmt, 4, addedDate)
    sqlite3_bind_text(stmt, 5, (info.title as NSString).utf8String, -1, nil)
    sqlite3_bind_text(stmt, 6, (info.author as NSString).utf8String, -1, nil)
    sqlite3_bind_text(stmt, 7, (info.feedUrl as NSString).utf8String, -1, nil)
    sqlite3_bind_text(stmt, 8, (uuid as NSString).utf8String, -1, nil)
    sqlite3_bind_text(stmt, 9, (info.webPageUrl as NSString).utf8String, -1, nil)
    sqlite3_bind_text(stmt, 10, (info.artworkUrl as NSString).utf8String, -1, nil)

    guard sqlite3_step(stmt) == SQLITE_DONE else {
        fputs("Error inserting: \(String(cString: sqlite3_errmsg(db)))\n", stderr)
        return false
    }

    guard incrementPrimaryKey(db: db, newMax: pk) else {
        fputs("Warning: failed to update Z_PRIMARYKEY counter\n", stderr)
        return false
    }

    return true
}

// MARK: - Main

func main() {
    let args = CommandLine.arguments
    guard args.count >= 2 else {
        fputs("Usage: podcast-bookmark <podcasts.apple.com URL>\n", stderr)
        fputs("       podcast-bookmark --check <podcasts.apple.com URL>\n", stderr)
        exit(1)
    }

    let checkOnly = args.contains("--check")
    let urlArg = args.last!

    guard let storeId = extractStoreId(from: urlArg) else {
        fputs("Error: cannot extract podcast ID from URL: \(urlArg)\n", stderr)
        exit(1)
    }

    guard let db = openDB() else { exit(1) }
    defer { sqlite3_close(db) }

    if podcastExists(db: db, storeId: storeId) {
        print("{\"status\":\"exists\",\"store_id\":\(storeId)}")
        exit(0)
    }

    if checkOnly {
        print("{\"status\":\"not_found\",\"store_id\":\(storeId)}")
        exit(0)
    }

    fputs("Looking up podcast \(storeId)...\n", stderr)
    guard let info = lookupPodcast(storeId: storeId) else {
        fputs("Error: iTunes lookup failed for ID \(storeId)\n", stderr)
        exit(1)
    }

    fputs("Bookmarking: \(info.title) by \(info.author)\n", stderr)
    guard insertPodcast(db: db, info: info) else {
        fputs("Error: failed to insert podcast into database\n", stderr)
        exit(1)
    }

    let jsonOutput = """
        {"status":"bookmarked","store_id":\(storeId),"title":"\(info.title.replacingOccurrences(of: "\"", with: "\\\""))"}
        """
    print(jsonOutput.trimmingCharacters(in: .whitespaces))
    exit(0)
}

main()
