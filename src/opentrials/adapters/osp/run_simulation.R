#!/usr/bin/env Rscript

# Minimal, headless OSP worker. It owns R/.NET/ospsuite concerns and communicates
# with Python only through versioned JSON files.

worker_request_schema <- "opentrials.osp.worker-request"
worker_response_schema <- "opentrials.osp.worker-response"
worker_schema_version <- "1.0.0"

arguments <- commandArgs(trailingOnly = TRUE)
argument_value <- function(flag) {
  index <- match(flag, arguments)
  if (is.na(index) || index == length(arguments)) {
    stop(sprintf("Missing required argument %s", flag), call. = FALSE)
  }
  arguments[[index + 1]]
}

input_path <- argument_value("--input")
output_path <- argument_value("--output")

write_response <- function(payload) {
  response <- list(
    schema = worker_response_schema,
    schema_version = worker_schema_version,
    payload = payload
  )
  jsonlite::write_json(response, output_path, auto_unbox = TRUE, pretty = FALSE, na = "null")
}

run_worker <- function() {
  request <- jsonlite::fromJSON(input_path, simplifyVector = FALSE)
  if (!identical(request$schema, worker_request_schema)) {
    stop("Unsupported OSP worker request schema.", call. = FALSE)
  }
  if (!identical(request$schema_version, worker_schema_version)) {
    stop("Unsupported OSP worker request schema version.", call. = FALSE)
  }
  payload <- request$payload
  if (!is.list(payload) || !is.character(payload$run_id) || !nzchar(payload$run_id)) {
    stop("Worker request requires a non-empty run_id.", call. = FALSE)
  }
  if (!is.character(payload$pkml_path) || !nzchar(payload$pkml_path)) {
    stop("Worker request requires a non-empty pkml_path.", call. = FALSE)
  }
  if (!file.exists(payload$pkml_path)) {
    stop(sprintf("PKML file does not exist: %s", payload$pkml_path), call. = FALSE)
  }

  suppressPackageStartupMessages(library(ospsuite))
  simulation <- loadSimulation(payload$pkml_path)
  simulation_results <- runSimulations(simulation)
  if (length(simulation_results) != 1) {
    stop("The v0.1 OSP worker expects exactly one simulation result.", call. = FALSE)
  }

  result_frame <- simulationResultsToDataFrame(simulation_results[[1]])
  if (nrow(result_frame) == 0) {
    stop("OSP simulation completed without output rows.", call. = FALSE)
  }
  result_rows <- lapply(seq_len(nrow(result_frame)), function(index) {
    as.list(result_frame[index, , drop = FALSE])
  })
  individual_count <- if ("IndividualId" %in% names(result_frame)) {
    length(unique(result_frame$IndividualId))
  } else {
    1L
  }

  write_response(list(
    status = "SUCCEEDED",
    run_id = payload$run_id,
    engine_id = "osp",
    generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    r_version = R.version.string,
    ospsuite_version = as.character(utils::packageVersion("ospsuite")),
    simulation_name = simulation$name,
    individual_count = individual_count,
    raw_result_rows = result_rows
  ))
}

tryCatch(
  run_worker(),
  error = function(error) {
    write_response(list(
      status = "FAILED",
      error = conditionMessage(error),
      generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
    ))
    quit(status = 1)
  }
)
