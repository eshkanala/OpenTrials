#!/usr/bin/env Rscript
#
# v0.7-C: one-time conversion of the official Open-Systems-Pharmacology
# Midazolam-Model PK-Sim snapshot into a directly loadable .pkml simulation.
#
# WHY THIS SCRIPT EXISTS
# -----------------------
# ospsuite-R's snapshot-conversion backend (loadProjectFromSnapshot() /
# runSimulationsFromSnapshot(), both ultimately calling into
# PKSim.R.Api via rSharp) is broken on macOS:
#   - runSimulationsFromSnapshot() explicitly refuses to run at all on
#     Darwin (cli::cli_abort("... not supported on macOS.")).
#   - loadProjectFromSnapshot() has no such guard, but its underlying
#     native call segfaults (exit code 139) on macOS Apple Silicon,
#     confirmed by running it directly against the real file this
#     script downloads.
# Neither of these is an OpenTrials bug -- it is an external tooling gap
# in ospsuite's macOS backend. This script is meant to be run once on a
# platform where ospsuite's snapshot machinery is actually supported
# (Windows or Linux), producing a single .pkml file that then gets
# carried back to the macOS development machine the same way
# Aciclovir.pkml already is: as a static, hash-verified simulation file.
#
# WHAT IT DOES
# -------------
#   1. Downloads (or reuses a local copy of) the official, GPLv2-licensed
#      snapshot from the Open-Systems-Pharmacology/Midazolam-Model repo,
#      pinned to tag v1.1, and verifies its SHA-256 against the value
#      already recorded from this project's own download.
#   2. Runs runSimulationsFromSnapshot() against it with exportPKML=TRUE,
#      exportCSV/JSON/XML=FALSE, so the only output is one .pkml per
#      simulation declared in the snapshot (37 simulations: a mix of IV
#      and oral/po protocols -- see CONVERSION.md for the full list).
#   3. Verifies the one target simulation named below actually produced
#      a .pkml, and prints its SHA-256 so it can be recorded in
#      CONVERSION.md's provenance block before the file is carried back.
#
# USAGE
# ------
#   Rscript convert_midazolam_snapshot.R [output_directory]
#
# PREREQUISITES (Windows or Linux only -- this will not work on macOS)
#   - R with the `ospsuite` package installed (tested against the same
#     12.4.4 version pinned elsewhere in this project; any version whose
#     snapshot backend is not macOS-gated should work).
#   - The .NET runtime ospsuite itself requires.
#   - The CRAN `digest` package (install.packages("digest")) -- used only
#     for SHA-256 hashing here, not an ospsuite dependency.
#   - Network access to raw.githubusercontent.com, OR pass a local path
#     to an already-downloaded Midazolam-Model.json as the second
#     argument.

suppressPackageStartupMessages(library(ospsuite))
if (!requireNamespace("digest", quietly = TRUE)) {
  stop("The `digest` package is required for hashing. Install it with: ",
       "install.packages(\"digest\")")
}

SNAPSHOT_URL <- paste0(
  "https://raw.githubusercontent.com/Open-Systems-Pharmacology/",
  "Midazolam-Model/v1.1/Midazolam-Model.json"
)
SNAPSHOT_SOURCE_REPO <- "Open-Systems-Pharmacology/Midazolam-Model"
SNAPSHOT_TAG <- "v1.1"
SNAPSHOT_LICENSE <- "GPL-2.0 (https://github.com/Open-Systems-Pharmacology/Suite/blob/develop/LICENSE)"
# Recorded by downloading this exact URL from the macOS development
# machine on 2026-08-19; re-verified here before conversion so a moved
# tag or a corrupted download is caught rather than silently converted.
EXPECTED_INPUT_SHA256 <- "6565b5654aeb42a5d7fc18a5993cdbf301c705cdd4e1ba49b00bcd042e1cf394"

# The one simulation registered as OpenTrials' second model profile.
# Chosen deliberately to maximize contrast with the existing Aciclovir
# IV profile: an oral (not IV) protocol, CYP3A4/UGT1A4 hepatic+gut
# metabolism (not renal filtration), a tablet formulation (not a
# straight IV bolus/infusion).
TARGET_SIMULATION_NAME <- "po 10 mg (tablet)"

args <- commandArgs(trailingOnly = TRUE)
output_dir <- if (length(args) >= 1) args[[1]] else file.path(getwd(), "midazolam-conversion-output")
local_snapshot_path <- if (length(args) >= 2) args[[2]] else NULL

if (Sys.info()[["sysname"]] == "Darwin") {
  stop(
    "This script must be run on Windows or Linux -- ospsuite's snapshot ",
    "conversion backend does not work on macOS (see the header comment ",
    "and HANDOFF.md's v0.7-C entry for the confirmed platform failure)."
  )
}

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

if (is.null(local_snapshot_path)) {
  local_snapshot_path <- file.path(output_dir, "Midazolam-Model.json")
  cat("Downloading", SNAPSHOT_URL, "\n")
  utils::download.file(SNAPSHOT_URL, local_snapshot_path, mode = "wb", quiet = FALSE)
} else {
  cat("Using local snapshot copy:", local_snapshot_path, "\n")
}

input_hash <- tolower(digest::digest(local_snapshot_path, algo = "sha256", file = TRUE))
cat("Input SHA-256:", input_hash, "\n")
if (!identical(input_hash, EXPECTED_INPUT_SHA256)) {
  stop(
    "Downloaded snapshot hash does not match the pinned value.\n",
    "  expected: ", EXPECTED_INPUT_SHA256, "\n",
    "  actual:   ", input_hash, "\n",
    "This must be resolved (wrong tag, corrupted download, or the ",
    "upstream file changed) before converting -- do not proceed on an ",
    "unverified source file."
  )
}

pkml_output_dir <- file.path(output_dir, "pkml")
dir.create(pkml_output_dir, recursive = TRUE, showWarnings = FALSE)

cat("Running all snapshot simulations with PKML export (this runs all",
    "declared simulations, not just the target one; that is the only",
    "granularity runSimulationsFromSnapshot() exposes) ...\n")
runSimulationsFromSnapshot(
  local_snapshot_path,
  output = pkml_output_dir,
  exportPKML = TRUE,
  exportCSV = FALSE,
  exportJSON = FALSE,
  exportXML = FALSE
)

produced <- list.files(pkml_output_dir, pattern = "\\.pkml$", recursive = TRUE, full.names = TRUE)
cat("\nProduced", length(produced), "PKML file(s):\n")
for (path in produced) cat(" -", path, "\n")

target_candidates <- produced[
  grepl(TARGET_SIMULATION_NAME, basename(produced), fixed = TRUE)
]
if (length(target_candidates) == 0) {
  stop(
    "Could not find an exported PKML matching the target simulation name ",
    "'", TARGET_SIMULATION_NAME, "'. Inspect the file list printed above, ",
    "pick the correct file by hand, and update CONVERSION.md accordingly ",
    "-- do not guess."
  )
}
target_path <- target_candidates[[1]]
target_hash <- tolower(digest::digest(target_path, algo = "sha256", file = TRUE))

cat("\nTarget simulation file:", target_path, "\n")
cat("Target simulation SHA-256:", target_hash, "\n")
cat("\nRecord both this path's file (renamed to Midazolam.pkml) and the\n",
    "SHA-256 above in models/profiles/midazolam/CONVERSION.md's\n",
    "provenance block, then carry the file back to the macOS development\n",
    "machine.\n")

cat("\nospsuite version:", as.character(utils::packageVersion("ospsuite")), "\n")
cat("R version:", R.version.string, "\n")
cat("Platform:", Sys.info()[["sysname"]], Sys.info()[["release"]], "\n")
