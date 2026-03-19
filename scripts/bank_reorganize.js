/**
 * Bank Tracker — Reorganize + Webhook
 *
 * Run reorganizeBank() once to migrate existing data into the new schema.
 * The doPost / doGet handlers remain deployed as the live webhook.
 *
 * New Bank Tracker schema (17 columns):
 *   Bank | Account Type | Date Opened | Bonus Amount | Min Deposit |
 *   Days to Qualify | Bonus Deadline | APY | Monthly Fee | Fee Waiver |
 *   Early Closure Penalty | Status | Bonus Received Date | Date Closed |
 *   Re-Eligibility | Notes | Source
 */

// ── One-time migration ─────────────────────────────────────────────────────────

function reorganizeBank() {
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

  // Map old column indices (best-effort)
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

  var iBank      = colIdx(["bank name", "bank", "issuer"]);
  var iAcctType  = colIdx(["account type", "type"]);
  var iBonus     = colIdx(["bonus amount", "account bonus", "bonus"]);
  var iDate      = colIdx(["open date", "opened", "date"]);
  var iMinDep    = colIdx(["required for bonus", "min dep", "minimum dep", "deposit", "required"]);
  var iDays      = colIdx(["days to hold", "days to earn", "required days", "days"]);
  var iAPY       = colIdx(["annualized return", "return rate", "apy"]);
  var iMonthFee  = colIdx(["monthly fee", "monthly"]);
  var iEarlyTerm = colIdx(["early term", "early closure", "early"]);
  var iClosed    = colIdx(["closed?", "closed", "status"]);
  var iCloseDate = colIdx(["closed date", "close date"]);
  var iReElig    = colIdx(["re-elig", "reelig", "eligib", "bonus re"]);
  var iNotes     = colIdx(["note"]);
  var iSource    = colIdx(["source"]);

  // 3. Build or clear "Bank Tracker" tab
  var TAB = "Bank Tracker";
  var dest = ss.getSheetByName(TAB);
  if (dest) {
    dest.clearContents();
    dest.clearFormats();
  } else {
    dest = ss.insertSheet(TAB);
  }

  // 4. Write headers
  var HEADERS = [
    "Bank", "Account Type", "Date Opened", "Bonus Amount", "Min Deposit",
    "Days to Qualify", "Bonus Deadline", "APY", "Monthly Fee", "Fee Waiver",
    "Early Closure Penalty", "Status", "Bonus Received Date", "Date Closed",
    "Re-Eligibility", "Notes", "Source"
  ];

  dest.appendRow(HEADERS);

  var headerRange = dest.getRange(1, 1, 1, HEADERS.length);
  headerRange.setFontWeight("bold");
  headerRange.setBackground("#0d3349");
  headerRange.setFontColor("#ffffff");
  dest.setFrozenRows(1);
  dest.autoResizeColumns(1, HEADERS.length);

  // 5. Migrate existing rows
  for (var r = 0; r < srcRows.length; r++) {
    var row = srcRows[r];
    if (row.every(function(c) { return c === "" || c === null; })) continue;

    var bank      = iBank      >= 0 ? row[iBank]      : "";
    var acctType  = iAcctType  >= 0 ? row[iAcctType]  : "";
    var bonus     = iBonus     >= 0 ? row[iBonus]     : "";
    var date      = iDate      >= 0 ? row[iDate]      : "";
    var minDep    = iMinDep    >= 0 ? row[iMinDep]    : "";
    var days      = iDays      >= 0 ? row[iDays]      : "";
    var apy       = iAPY       >= 0 ? row[iAPY]       : "";
    var monthFee  = iMonthFee  >= 0 ? row[iMonthFee]  : "";
    var earlyTerm = iEarlyTerm >= 0 ? row[iEarlyTerm] : "";
    var closedVal = iClosed    >= 0 ? row[iClosed]    : "";
    var closeDate = iCloseDate >= 0 ? row[iCloseDate] : "";
    var reElig    = iReElig    >= 0 ? row[iReElig]    : "";
    var notes     = iNotes     >= 0 ? row[iNotes]     : "";
    var source    = iSource    >= 0 ? row[iSource]    : "";

    // Derive status from "Closed?" column
    var status = "Active";
    var closedStr = String(closedVal).toLowerCase();
    if (closedStr === "yes" || closedStr === "true" || closedStr === "closed") {
      status = "Closed";
    }

    var newRow = [
      bank,      // Bank
      acctType,  // Account Type
      date,      // Date Opened
      bonus,     // Bonus Amount
      minDep,    // Min Deposit
      days,      // Days to Qualify
      "",        // Bonus Deadline
      apy,       // APY
      monthFee,  // Monthly Fee
      "",        // Fee Waiver
      earlyTerm, // Early Closure Penalty
      status,    // Status
      "",        // Bonus Received Date
      closeDate, // Date Closed
      reElig,    // Re-Eligibility
      notes,     // Notes
      source     // Source
    ];

    dest.appendRow(newRow);
  }

  // 6. Color-code Status column (col 12 = L)
  _applyStatusColors(dest, 12);

  Logger.log("Bank Tracker reorganized. Rows migrated: " + srcRows.length);
  SpreadsheetApp.getUi().alert("✅ Bank Tracker reorganized!\n\n" +
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
    } else if (v.indexOf("closed") !== -1 || v.indexOf("cancel") !== -1) {
      backgrounds.push(["#f8d7da"]); fontColors.push(["#721c24"]);
    } else if (v.indexOf("pending") !== -1) {
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

      var tabNames = ["Bank Tracker"];
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
      hr.setBackground("#0d3349");
      hr.setFontColor("#ffffff");
      sheet.setFrozenRows(1);
    }
  }

  sheet.appendRow(row);

  if (tabName === "Bank Tracker") {
    _applyStatusColors(sheet, 12);
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
