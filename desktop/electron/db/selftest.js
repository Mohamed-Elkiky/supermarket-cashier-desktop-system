"use strict";

/**
 * Encrypted-DB self test. Run with:  node electron/db/selftest.js
 *
 * Proves, without any GUI or Electron runtime:
 *   1. keytar stores/reads the 32-byte key in Windows Credential Manager
 *      (the key round-trips from the OS keystore, not from disk).
 *   2. The database opens with that key, and a kv_meta row round-trips.
 *   3. The raw .db file on disk is NOT a plaintext SQLite database
 *      (its header is not "SQLite format 3").
 *   4. The encryption key does not appear anywhere in the db file bytes.
 *
 * Uses a throwaway db file so it never touches the real till database, but the
 * SAME Credential-Manager key the app uses.
 */

const fs = require("fs");
const os = require("os");
const path = require("path");

const db = require("./database");

async function main() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "pos-db-selftest-"));
  const dbFile = path.join(tmpDir, "selftest.db");
  let failed = false;

  const check = (name, cond) => {
    const ok = !!cond;
    console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
    if (!ok) failed = true;
  };

  try {
    await db.init({ dbPath: dbFile, showFirstRunDialog: false });
    console.log(`DB path: ${dbFile}`);

    // 1. keytar round-trip
    const keytar = require("keytar");
    const storedKey = await keytar.getPassword(db.KEYTAR_SERVICE, db.KEYTAR_ACCOUNT);
    check("encryption key present in Windows Credential Manager", db.isValidKeyHex(storedKey));

    // 2. kv_meta round-trip
    const marker = `selftest-${Date.now()}`;
    db.setMeta("selftest_marker", marker);
    check("kv_meta write/read round-trips", db.getMeta("selftest_marker") === marker);

    // Force data to disk, then close so the file is fully flushed.
    db.close();

    // 3. file is encrypted (not a plaintext SQLite header)
    const bytes = fs.readFileSync(dbFile);
    check(
      "db file is NOT a plaintext SQLite database",
      bytes.length > 0 && !db.looksLikePlaintextSqlite(bytes),
    );
    console.log(
      `   first 16 bytes: ${bytes.subarray(0, 16).toString("hex")} ` +
        `(plaintext would start with "53514c69746520666f726d6174203300")`,
    );

    // 4. key must not be sitting in the encrypted file
    const hexHaystack = bytes.toString("latin1");
    check("encryption key does NOT appear in the db file", !hexHaystack.includes(storedKey));

    console.log(
      "\nKey location: Windows Credential Manager " +
        `(service="${db.KEYTAR_SERVICE}", account="${db.KEYTAR_ACCOUNT}"). ` +
        "It is never written to the db file or any other file.",
    );
  } catch (err) {
    failed = true;
    console.error("SELFTEST ERROR:", err && err.stack ? err.stack : err);
  } finally {
    try {
      db.close();
    } catch {
      /* already closed */
    }
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }

  console.log(`\nSELFTEST ${failed ? "FAILED" : "PASSED"}`);
  process.exit(failed ? 1 : 0);
}

main();
