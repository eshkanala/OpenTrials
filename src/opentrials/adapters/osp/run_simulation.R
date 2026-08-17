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
  jsonlite::write_json(
    response, output_path, auto_unbox = TRUE, pretty = FALSE, na = "null", digits = NA
  )
}

sha256_file <- function(path) {
  if (requireNamespace("openssl", quietly = TRUE)) {
    bytes <- readBin(path, what = "raw", n = file.info(path)$size)
    digest <- openssl::sha256(bytes)
    return(paste(sprintf("%02x", as.integer(digest)), collapse = ""))
  }
  if (requireNamespace("digest", quietly = TRUE)) {
    return(digest::digest(path, algo = "sha256", serialize = FALSE, file = TRUE))
  }
  shasum <- Sys.which("shasum")
  if (nzchar(shasum)) {
    output <- system2(shasum, c("-a", "256", path), stdout = TRUE, stderr = TRUE)
    if (length(output) == 1 && !startsWith(output, "Warning")) {
      return(strsplit(trimws(output), "[[:space:]]+")[[1]][[1]])
    }
  }
  stop(
    "SHA-256 verification requires R package 'openssl'/'digest' or the shasum executable.",
    call. = FALSE
  )
}

verification_failure <- function(message, verification, run_id = NULL) {
  stop(
    structure(
      list(
        message = message,
        call = NULL,
        execution_verification = verification,
        run_id = run_id
      ),
      class = c("execution_verification_error", "error", "condition")
    )
  )
}

empty_execution_verification <- function(expected_hash, expected_container) {
  list(
    model_hash_verification = list(
      expected_pkml_sha256 = if (is.null(expected_hash)) NA_character_ else expected_hash,
      actual_pkml_sha256 = NA_character_,
      verified = NA
    ),
    route_container_verification = list(
      expected_administration_container = if (is.null(expected_container)) NA_character_ else expected_container,
      verified = NA
    ),
    parameter_assignments = list(),
    solver_executed = FALSE
  )
}

validate_assignments <- function(assignments, verification, run_id) {
  if (is.null(assignments)) {
    return(list())
  }
  if (!is.list(assignments)) {
    verification_failure(
      "parameter_assignments must be a list.", verification, run_id
    )
  }
  for (index in seq_along(assignments)) {
    assignment <- assignments[[index]]
    valid <- is.list(assignment) &&
      is.character(assignment$path) && length(assignment$path) == 1 && nzchar(assignment$path) &&
      is.numeric(assignment$value) && length(assignment$value) == 1 && is.finite(assignment$value) &&
      is.character(assignment$unit) && length(assignment$unit) == 1 && nzchar(assignment$unit) &&
      is.character(assignment$source_field) && length(assignment$source_field) == 1 &&
      nzchar(assignment$source_field)
    if (!valid) {
      verification_failure(
        sprintf("parameter_assignments[%d] requires path, finite numeric value, unit, and source_field.", index),
        verification,
        run_id
      )
    }
  }
  assignments
}

values_equivalent <- function(requested, executed) {
  isTRUE(all.equal(requested, executed, tolerance = 1e-8, check.attributes = FALSE))
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

  expected_hash <- payload$expected_pkml_sha256
  expected_container <- payload$expected_administration_container
  verification <- empty_execution_verification(expected_hash, expected_container)
  assignments <- validate_assignments(payload$parameter_assignments, verification, payload$run_id)

  if (!is.null(expected_hash) &&
      (!is.character(expected_hash) || length(expected_hash) != 1 ||
        !grepl("^[0-9A-Fa-f]{64}$", expected_hash))) {
    verification_failure(
      "expected_pkml_sha256 must be a 64-character hexadecimal SHA-256 digest.",
      verification,
      payload$run_id
    )
  }

  if (length(assignments) > 0 && is.null(expected_hash)) {
    verification_failure(
      "Assignments require expected_pkml_sha256.",
      verification,
      payload$run_id
    )
  }

  if (length(assignments) > 0 &&
      (!is.character(expected_container) || length(expected_container) != 1 ||
        !nzchar(expected_container))) {
    verification_failure(
      "Assignments require a non-empty expected_administration_container.",
      verification,
      payload$run_id
    )
  }

  if (!is.null(expected_hash)) {
    actual_hash <- tryCatch(
      sha256_file(payload$pkml_path),
      error = function(error) {
        verification_failure(
          sprintf("Could not calculate input PKML SHA-256: %s", conditionMessage(error)),
          verification,
          payload$run_id
        )
      }
    )
    verification$model_hash_verification$actual_pkml_sha256 <- actual_hash
    verification$model_hash_verification$verified <- identical(
      tolower(actual_hash), tolower(expected_hash)
    )
    if (!isTRUE(verification$model_hash_verification$verified)) {
      verification_failure("Input PKML SHA-256 does not match expected_pkml_sha256.", verification, payload$run_id)
    }
  }

  suppressPackageStartupMessages(library(ospsuite))
  simulation <- loadSimulation(payload$pkml_path)

  if (length(assignments) > 0) {
    paths_in_container <- vapply(
      assignments,
      function(assignment) startsWith(assignment$path, expected_container),
      logical(1)
    )
    verification$route_container_verification$verified <- all(paths_in_container)
    if (!all(paths_in_container)) {
      verification_failure(
        "Every parameter assignment path must start with expected_administration_container.",
        verification,
        payload$run_id
      )
    }

    for (index in seq_along(assignments)) {
      assignment <- assignments[[index]]
      assignment_verification <- list(
        path = assignment$path,
        source_field = assignment$source_field,
        requested = list(value = assignment$value, unit = assignment$unit),
        original = list(value = NA_real_, unit = NA_character_),
        executed = list(value = NA_real_, unit = assignment$unit),
        equivalent = FALSE,
        verified = FALSE
      )
      verification$parameter_assignments[[index]] <- assignment_verification

      tryCatch({
        parameter <- getParameter(assignment$path, simulation)
        verification$parameter_assignments[[index]]$original <- list(
          value = parameter$value,
          unit = parameter$unit
        )
        parameter$setValue(assignment$value, assignment$unit)
        executed_value <- toUnit(parameter, parameter$value, assignment$unit, parameter$unit)
        verification$parameter_assignments[[index]]$executed <- list(
          value = executed_value,
          unit = assignment$unit
        )
        equivalent <- values_equivalent(assignment$value, executed_value)
        verification$parameter_assignments[[index]]$equivalent <- equivalent
        verification$parameter_assignments[[index]]$verified <- equivalent
        if (!equivalent) {
          verification_failure(
            sprintf("Assignment verification failed for parameter path: %s", assignment$path),
            verification,
            payload$run_id
          )
        }
      }, error = function(error) {
        if (inherits(error, "execution_verification_error")) {
          stop(error)
        }
        verification$parameter_assignments[[index]]$error <- conditionMessage(error)
        verification_failure(
          sprintf("Could not apply or verify parameter assignment for path %s: %s", assignment$path, conditionMessage(error)),
          verification,
          payload$run_id
        )
      })
    }
  }

  simulation_results <- runSimulations(simulation)
  verification$solver_executed <- TRUE
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
    execution_verification = verification,
    raw_result_rows = result_rows
  ))
}

tryCatch(
  run_worker(),
  error = function(error) {
    failure_payload <- list(
      status = "FAILED",
      error = conditionMessage(error),
      generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
    )
    if (inherits(error, "execution_verification_error")) {
      failure_payload$run_id <- error$run_id
      failure_payload$execution_verification <- error$execution_verification
    }
    write_response(failure_payload)
    quit(status = 1)
  }
)
