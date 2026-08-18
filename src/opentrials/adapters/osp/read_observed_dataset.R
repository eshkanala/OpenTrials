#!/usr/bin/env Rscript

# Minimal, headless OSP worker for reading one bundled observed-data PKML
# ("DataSet" building block, as produced by ospsuite's saveDataSetToPKML())
# and reporting its fields as JSON. This is a read-only inspection worker --
# it never executes a simulation and never mutates the source file.

worker_request_schema <- "opentrials.osp.observed-dataset-worker-request"
worker_response_schema <- "opentrials.osp.observed-dataset-worker-response"
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
  jsonlite::write_json(
    response, output_path, auto_unbox = TRUE, pretty = FALSE, na = "null", digits = NA
  )
}

null_to_na <- function(value) {
  if (is.null(value) || length(value) == 0) NA_character_ else as.character(value)
}

run_worker <- function() {
  request <- jsonlite::fromJSON(input_path, simplifyVector = FALSE)
  if (!identical(request$schema, worker_request_schema)) {
    stop("Unsupported observed-dataset worker request schema.", call. = FALSE)
  }
  if (!identical(request$schema_version, worker_schema_version)) {
    stop("Unsupported observed-dataset worker request schema version.", call. = FALSE)
  }
  payload <- request$payload
  if (!is.character(payload$pkml_path) || !nzchar(payload$pkml_path)) {
    stop("Worker request requires a non-empty pkml_path.", call. = FALSE)
  }
  if (!file.exists(payload$pkml_path)) {
    stop(sprintf("PKML file does not exist: %s", payload$pkml_path), call. = FALSE)
  }

  suppressPackageStartupMessages(library(ospsuite))
  dataset <- loadDataSetFromPKML(payload$pkml_path)

  error_type <- tryCatch(as.character(dataset$yErrorType), error = function(e) NA_character_)
  metadata <- dataset$metaData
  if (!is.list(metadata)) {
    metadata <- list()
  }

  write_response(list(
    status = "SUCCEEDED",
    generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    r_version = R.version.string,
    ospsuite_version = as.character(utils::packageVersion("ospsuite")),
    name = null_to_na(dataset$name),
    x_unit = null_to_na(dataset$xUnit),
    y_unit = null_to_na(dataset$yUnit),
    x_dimension = null_to_na(dataset$xDimension),
    y_dimension = null_to_na(dataset$yDimension),
    y_error_unit = null_to_na(dataset$yErrorUnit),
    y_error_type = if (is.na(error_type) || !nzchar(error_type)) NA_character_ else error_type,
    mol_weight = if (is.null(dataset$molWeight)) NA_real_ else dataset$molWeight,
    metadata = metadata,
    x_values = as.list(dataset$xValues),
    y_values = as.list(dataset$yValues),
    y_error_values = if (is.null(dataset$yErrorValues)) list() else as.list(dataset$yErrorValues)
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
