/**
 * CC Tracker — Reorganize + Webhook
 *
 * Run reorganizeCC() once to migrate existing data into the new schema.
 * The doPost / doGet handlers remain deployed as the live webhook.
 *
 * New CC Tracker schema (16 columns):
 *   Bank/Issuer | Card Name | Date Opened | Annual Fee | Annual Fee Date |
 *   Sign-Up Bonus | Min Spend | Spend Deadline | SUB Status | SUB Earned Date |
 *   Card Status | Action By Date | Downgrade To | Re-Eligibility |
 *   Historical Normal SUB | Notes
 */

// ── One-time migration ─────────────────────────────────────────────────────────

function reorganizeCC() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var src = ss.getSheetByName("Sheet1") || ss.getSheets()[0];

  // 1. Backup original data
  var backupName = "Backup - Original";
  if (!ss.getSheetByName(backupName)) {
    src.copyTo(ss).setName(backupName);
    Logger.log("Backed up to: " + backupName);
  }

  // 2. Read existing rows (skip header row 1)
  var srcData = src.getDataRange().getValues();
  var srcHeaders = srcData[0];
  var srcRows = srcData.slice(1);

  // Map old column indices (best-effort, handles various existing layouts)
  function colIdx(candidates) {
    for (var i = 0; i < candidates.length; i++) {
      for (var j = 0; j < srcHeaders.length; j++) {
        if (srcHeaders[j].toString().toLowerCase().indexOf(candidates[i].toLowerCase()) !== -1) {
          return j;
        }
      }
    }
    return -1;
  }

  var iCardOrBank  = colIdx(["card", "bank", "issuer", "name"]);
  var iBonus       = colIdx(["bonus", "sub", "sign"]);
  var iDate        = colIdx(["date", "opened"]);
  var iMinSpend    = colIdx(["min spend", "minimum", "spend req"]);
  var iAnnualFee   = colIdx(["annual fee", "fee"]);
  var iReElig      = colIdx(["re-elig", "reelig", "eligib"]);
  var iStatus      = colIdx(["status"]);
  var iNotes       = colIdx(["note"]);
  var iSource      = colIdx(["source"]);

  // 3. Build or clear the "CC Tracker" tab
  var TAB = "CC Tracker";
  var dest = ss.getSheetByName(TAB);
  if (dest) {
    dest.clearContents();
    dest.clearFormats();
  } else {
    dest = ss.insertSheet(TAB);
  }

  // 4. Write headers
  var HEADERS = [
    "Bank/Issuer", "Card Name", "Date Opened", "Annual Fee", "Annual Fee Date",
    "Sign-Up Bonus", "Min Spend", "Spend Deadline", "SUB Status", "SUB Earned Date",
    "Card Status", "Action By Date", "Downgrade To", "Re-Eligibility",
    "Historical Normal SUB", "Notes"
  ];

  dest.appendRow(HEADERS);

  var headerRange = dest.getRange(1, 1, 1, HEADERS.length);
  headerRange.setFontWeight("bold");
  headerRange.setBackground("#1a1a2e");
  headerRange.setFontColor("#ffffff");
  dest.setFrozenRows(1);

  // Auto-size columns
  dest.autoResizeColumns(1, HEADERS.length);

  // 5. Migrate existing rows
  for (var r = 0; r < srcRows.length; r++) {
    var row = srcRows[r];
    if (row.every(function(c) { return c === "" || c === null; })) continue; // skip blanks

    var cardOrBank = iCardOrBank >= 0 ? row[iCardOrBank] : "";
    var bonus      = iBonus     >= 0 ? row[iBonus]     : "";
    var dateOpened = iDate      >= 0 ? row[iDate]      : "";
    var annualFee  = iAnnualFee >= 0 ? row[iAnnualFee] : "";
    var minSpend   = iMinSpend  >= 0 ? row[iMinSpend]  : "";
    var reElig     = iReElig    >= 0 ? row[iReElig]    : "";
    var status     = iStatus    >= 0 ? row[iStatus]    : "Active";
    var notes      = iNotes     >= 0 ? row[iNotes]     : "";
    // Combine notes + source if both present
    var source     = iSource    >= 0 ? row[iSource]    : "";
    if (source) notes = notes ? notes + " | Source: " + source : "Source: " + source;

    // Try to split "Card / Bank" → Bank/Issuer + Card Name
    var bankIssuer = "";
    var cardName   = String(cardOrBank);
    // Common issuers
    var issuers = ["Chase", "Amex", "American Express", "Citi", "Capital One",
                   "Bank of America", "Wells Fargo", "Barclays", "US Bank",
                   "Discover", "HSBC", "Navy Federal", "Fidelity", "Schwab"];
    for (var k = 0; k < issuers.length; k++) {
      if (cardName.toLowerCase().indexOf(issuers[k].toLowerCase()) !== -1) {
        bankIssuer = issuers[k];
        break;
      }
    }

    var newRow = [
      bankIssuer,    // Bank/Issuer
      cardName,      // Card Name
      dateOpened,    // Date Opened
      annualFee,     // Annual Fee
      "",            // Annual Fee Date
      bonus,         // Sign-Up Bonus
      minSpend,      // Min Spend
      "",            // Spend Deadline
      "",            // SUB Status
      "",            // SUB Earned Date
      status,        // Card Status
      "",            // Action By Date
      "",            // Downgrade To
      reElig,        // Re-Eligibility
      bonus,         // Historical Normal SUB (seed with current bonus as baseline)
      notes          // Notes
    ];

    dest.appendRow(newRow);
  }

  // 6. Color-code Card Status column (col 11 = K)
  _applyStatusColors(dest, 11);

  // 7. Color-code SUB Status column (col 9 = I)
  _applyStatusColors(dest, 9);

  Logger.log("CC Tracker reorganized. Rows migrated: " + srcRows.length);
  SpreadsheetApp.getUi().alert("✅ CC Tracker reorganized!\n\n" +
    srcRows.length + " rows migrated.\nOriginal data backed up to 'Backup - Original'.");
}

function _applyStatusColors(sheet, colNum) {
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return;
  var range = sheet.getRange(2, colNum, lastRow - 1, 1);
  var values = range.getValues();
  var backgrounds = [];
  var fontColors = [];
  for (var i = 0; i < values.length; i++) {
    var v = String(values[i][0]).toLowerCase();
    if (v.indexOf("active") !== -1 || v.indexOf("open") !== -1) {
      backgrounds.push(["#d4edda"]); fontColors.push(["#155724"]);
    } else if (v.indexOf("cancel") !== -1 || v.indexOf("closed") !== -1) {
      backgrounds.push(["#f8d7da"]); fontColors.push(["#721c24"]);
    } else if (v.indexOf("downgrade") !== -1 || v.indexOf("pending") !== -1) {
      backgrounds.push(["#fff3cd"]); fontColors.push(["#856404"]);
    } else if (v.indexOf("received") !== -1 || v.indexOf("earned") !== -1) {
      backgrounds.push(["#cce5ff"]); fontColors.push(["#004085"]);
    } else {
      backgrounds.push(["#ffffff"]); fontColors.push(["#000000"]);
    }
  }
  range.setBackgrounds(backgrounds);
  range.setFontColors(fontColors);
}

// ── POST handler (bot writes data) ────────────────────────────────────────────

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

// ── GET handler (bot reads data) ──────────────────────────────────────────────

function doGet(e) {
  try {
    var action = (e.parameter && e.parameter.action) ? e.parameter.action : "read";

    if (action === "read") {
      var ss = SpreadsheetApp.getActiveSpreadsheet();
      var result = {};

      var tabNames = ["CC Tracker", "Budget"];
      tabNames.forEach(function(name) {
        var sheet = ss.getSheetByName(name);
        if (sheet) {
          var rows = sheet.getDataRange().getValues();
          if (rows.length < 2) { result[name] = []; return; }
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

  if (!sheet) {
    sheet = ss.insertSheet(tabName);
    if (headers && headers.length > 0) {
      sheet.appendRow(headers);
      var hr = sheet.getRange(1, 1, 1, headers.length);
      hr.setFontWeight("bold");
      hr.setBackground("#1a1a2e");
      hr.setFontColor("#ffffff");
      sheet.setFrozenRows(1);
    }
  }

  sheet.appendRow(row);

  // Re-apply status colors after each append
  if (tabName === "CC Tracker") {
    _applyStatusColors(sheet, 11); // Card Status
    _applyStatusColors(sheet, 9);  // SUB Status
  }
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
