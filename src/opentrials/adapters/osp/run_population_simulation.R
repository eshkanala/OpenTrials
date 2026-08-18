#!/usr/bin/env Rscript

# Minimal, headless OSP population-execution worker. It reconstructs a
# Population object from the exact table supplied by Python (matching a
# verified, persisted OTPGEN artifact), applies at most one verified
# intervention mutation to the loaded simulation, and runs the whole
# population through PBPK in a single batched runSimulations() call.
# It communicates with Python only through versioned JSON files and performs
# no OpenTrials-specific interpretation of the raw solver output.

worker_request_schema <- "opentrials.osp.population-execution-worker-request"
worker_response_schema <- "opentrials.osp.population-execution-worker-response"
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
    verification_failure("parameter_assignments must be a list.", verification, run_id)
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

# Population rows arrive as a nested list (parsed with simplifyVector = FALSE,
# consistent with the rest of this request). Re-serializing that fragment and
# reparsing it with simplifyDataFrame lets jsonlite infer correct per-column
# types (numeric vs. character) exactly as verified empirically: this is the
# same round trip proven bit-identical to the original in-memory population.
population_data_frame <- function(columns, rows) {
  rows_json <- jsonlite::toJSON(rows, auto_unbox = TRUE, digits = NA, null = "null")
  data_frame <- jsonlite::fromJSON(rows_json, simplifyDataFrame = TRUE)
  if (!is.data.frame(data_frame)) {
    stop("Population rows did not parse into a rectangular table.", call. = FALSE)
  }
  missing_columns <- setdiff(columns, names(data_frame))
  if (length(missing_columns) > 0) {
    stop(
      sprintf("Population table is missing declared columns: %s", paste(missing_columns, collapse = ", ")),
      call. = FALSE
    )
  }
  data_frame[, columns, drop = FALSE]
}

run_worker <- function() {
  request <- jsonlite::fromJSON(input_path, simplifyVector = FALSE)
  if (!identical(request$schema, worker_request_schema)) {
    stop("Unsupported OSP population execution worker request schema.", call. = FALSE)
  }
  if (!identical(request$schema_version, worker_schema_version)) {
    stop("Unsupported OSP population execution worker request schema version.", call. = FALSE)
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
  if (!is.character(expected_hash) || length(expected_hash) != 1 ||
      !grepl("^[0-9A-Fa-f]{64}$", expected_hash)) {
    stop(
      "Population execution requires a 64-character hexadecimal expected_pkml_sha256.",
      call. = FALSE
    )
  }
  if (!is.list(payload$population_columns) && !is.character(payload$population_columns)) {
    stop("Worker request requires population_columns.", call. = FALSE)
  }
  population_columns <- unlist(payload$population_columns, use.names = FALSE)
  if (!is.character(population_columns) || length(population_columns) == 0) {
    stop("Worker request requires at least one population column.", call. = FALSE)
  }
  if (!"IndividualId" %in% population_columns) {
    stop("Population table must include an IndividualId column.", call. = FALSE)
  }
  if (!is.list(payload$population_rows) || length(payload$population_rows) == 0) {
    stop("Worker request requires at least one population row.", call. = FALSE)
  }
  if (!is.numeric(payload$expected_population_count) || payload$expected_population_count < 1) {
    stop("Worker request requires a positive expected_population_count.", call. = FALSE)
  }
  if (length(payload$population_rows) != payload$expected_population_count) {
    stop("Population row count does not match expected_population_count.", call. = FALSE)
  }

  expected_container <- payload$expected_administration_container
  verification <- empty_execution_verification(expected_hash, expected_container)
  assignments <- validate_assignments(payload$parameter_assignments, verification, payload$run_id)
  if (length(assignments) > 0 &&
      (!is.character(expected_container) || length(expected_container) != 1 ||
        !nzchar(expected_container))) {
    verification_failure(
      "Assignments require a non-empty expected_administration_container.",
      verification,
      payload$run_id
    )
  }

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

  suppressPackageStartupMessages(library(ospsuite))

  population_table <- population_data_frame(population_columns, payload$population_rows)
  population <- tryCatch(
    populationFromDataFrame(population_table),
    error = function(error) {
      stop(
        sprintf("Could not reconstruct the population from the supplied table: %s", conditionMessage(error)),
        call. = FALSE
      )
    }
  )
  reconstructed_table <- populationToDataFrame(population)
  reconstructed_count <- nrow(reconstructed_table)
  if (reconstructed_count != payload$expected_population_count) {
    stop("Reconstructed population individual count does not match expected_population_count.", call. = FALSE)
  }

  # Optional read-back of specific population-table columns from the actual
  # reconstructed Population object (not merely the request payload) --
  # lets Python verify a declared physiological-state override was really
  # applied to the population that was executed, rather than trusting the
  # request. Empty/absent by default, so every existing caller is unchanged.
  readback_columns <- payload$population_readback_columns
  population_readback <- NULL
  if (!is.null(readback_columns) && length(readback_columns) > 0) {
    readback_columns <- unlist(readback_columns, use.names = FALSE)
    missing_readback <- setdiff(readback_columns, names(reconstructed_table))
    if (length(missing_readback) > 0) {
      stop(
        sprintf(
          "population_readback_columns not present in the reconstructed population: %s",
          paste(missing_readback, collapse = ", ")
        ),
        call. = FALSE
      )
    }
    select_columns <- c("IndividualId", readback_columns)
    population_readback <- lapply(seq_len(nrow(reconstructed_table)), function(index) {
      as.list(reconstructed_table[index, select_columns, drop = FALSE])
    })
  }

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

  # Optional declared observation schedule: applied only when supplied, so the
  # default solver output grid is completely unchanged for every existing
  # caller. Verified empirically that addOutputInterval() lets the solver's
  # output grid be set exactly (see HANDOFF v0.5-B); Python performs the
  # authoritative accept/reject decision from the observed_output_times this
  # worker reports back, matching the existing raw-evidence-then-verify split.
  output_intervals <- payload$output_intervals
  schedule_applied <- !is.null(output_intervals) && length(output_intervals) > 0
  if (schedule_applied) {
    clearOutputIntervals(simulation)
    for (index in seq_along(output_intervals)) {
      window <- output_intervals[[index]]
      valid <- is.list(window) &&
        is.numeric(window$start_time) && length(window$start_time) == 1 &&
        is.numeric(window$end_time) && length(window$end_time) == 1 &&
        is.numeric(window$resolution) && length(window$resolution) == 1 && window$resolution > 0 &&
        is.character(window$interval_name) && nzchar(window$interval_name)
      if (!valid) {
        stop(
          sprintf(
            "output_intervals[%d] requires start_time, end_time, resolution, interval_name.",
            index
          ),
          call. = FALSE
        )
      }
      addOutputInterval(
        simulation,
        startTime = window$start_time,
        endTime = window$end_time,
        resolution = window$resolution,
        intervalName = window$interval_name
      )
    }
  }

  simulation_results <- runSimulations(simulations = simulation, population = population)
  verification$solver_executed <- TRUE
  if (length(simulation_results) != 1) {
    stop("The population execution worker expects exactly one combined population result.", call. = FALSE)
  }

  result_frame <- simulationResultsToDataFrame(simulation_results[[1]])
  if (nrow(result_frame) == 0) {
    stop("OSP population simulation completed without output rows.", call. = FALSE)
  }
  if (!"IndividualId" %in% names(result_frame)) {
    stop("OSP population simulation result is missing IndividualId.", call. = FALSE)
  }
  result_individual_ids <- sort(unique(as.integer(result_frame$IndividualId)))
  result_rows <- lapply(seq_len(nrow(result_frame)), function(index) {
    as.list(result_frame[index, , drop = FALSE])
  })
  observed_output_times <- if (schedule_applied) as.list(sort(unique(result_frame$Time))) else NULL

  write_response(list(
    status = "SUCCEEDED",
    run_id = payload$run_id,
    engine_id = "osp",
    generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    r_version = R.version.string,
    ospsuite_version = as.character(utils::packageVersion("ospsuite")),
    simulation_name = simulation$name,
    population_count = reconstructed_count,
    result_individual_ids = result_individual_ids,
    output_schedule_applied = schedule_applied,
    observed_output_times = observed_output_times,
    population_readback = population_readback,
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
