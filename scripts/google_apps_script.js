/**
 * Executive AI Assistant — Google Sheets Web Hook
 *
 * SETUP (one time, ~2 min):
 * 1. Open your Google Sheet → Extensions → Apps Script
 * 2. Delete any existing code, paste this entire file
 * 3. Click Deploy → New Deployment
 *    - Type: Web App
 *    - Execute as: Me
 *    - Who has access: Anyone
 * 4. Click Deploy → copy the Web App URL
 * 5. Add to .env:  GOOGLE_SHEETS_WEBHOOK_URL=<paste URL here>
 *
 * That's it — the bot will now write directly to your sheet.
 */

// ── POST handler (bot writes data) ──────────────────────────────────────────

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var action = data.action;

    if (action === "append") {
      appendRow(data.tab, data.row, data.headers);
      return ok("Row appended to " + data.tab);
    }

    return error("Unknown action: " + action);
  } catch (err) {
    return error(err.toString());
  }
}

// ── GET handler (bot reads data) ─────────────────────────────────────────────

function doGet(e) {
  try {
    var action = e.parameter.action || "read";

    if (action === "read") {
      var ss = SpreadsheetApp.getActiveSpreadsheet();
      var result = {};

      var tabNames = ["CC Bonuses", "Bank Bonuses", "Budget"];
      tabNames.forEach(function(name) {
        var sheet = ss.getSheetByName(name);
        if (sheet) {
          var rows = sheet.getDataRange().getValues();
          var headers = rows[0];
          result[name] = rows.slice(1).map(function(row) {
            var obj = {};
            headers.forEach(function(h, i) { obj[h] = row[i]; });
            return obj;
          });
        }
      });

      return ContentService
        .createTextOutput(JSON.stringify(result))
        .setMimeType(ContentService.MimeType.JSON);
    }

    return error("Unknown action");
  } catch (err) {
    return error(err.toString());
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function appendRow(tabName, row, headers) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(tabName);

  // Create tab with headers if it doesn't exist
  if (!sheet) {
    sheet = ss.insertSheet(tabName);
    if (headers && headers.length > 0) {
      sheet.appendRow(headers);
      // Bold the header row
      sheet.getRange(1, 1, 1, headers.length).setFontWeight("bold");
      // Freeze header row
      sheet.setFrozenRows(1);
    }
  }

  sheet.appendRow(row);
}

function ok(msg) {
  return ContentService
    .createTextOutput(JSON.stringify({ status: "ok", message: msg }))
    .setMimeType(ContentService.MimeType.JSON);
}

function error(msg) {
  return ContentService
    .createTextOutput(JSON.stringify({ status: "error", message: msg }))
    .setMimeType(ContentService.MimeType.JSON);
}
