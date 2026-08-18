#!/usr/bin/env Rscript

# CSV-transport population-execution worker (v0.6-C). Structurally identical
# to run_population_simulation.R -- same request/response envelope, same
# verification logic, same solver call -- except the population table and
# the raw simulation result cross the Python<->R boundary as files rather
# than embedded JSON arrays. A v0.6-C capability probe measured JSON row-list
# construction + toJSON on a 98,200-row N=100 result as ~23s, versus 0.16s
# for exportResultsToCSV producing an 18x-smaller file; this worker exists to
# capture that difference without touching verification semantics at all.
# run_population_simulation.R remains unchanged and available as the
# reference JSON transport.

worker_request_schema <- "opentrials.osp.population-execution-csv-worker-request"
worker_response_schema <- "opentrials.osp.population-execution-csv-worker-response"
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

run_worker <- function() {
  request <- jsonlite::fromJSON(input_path, simplifyVector = FALSE)
  if (!identical(request$schema, worker_request_schema)) {
    stop("Unsupported CSV population execution worker request schema.", call. = FALSE)
  }
  if (!identical(request$schema_version, worker_schema_version)) {
    stop("Unsupported CSV population execution worker request schema version.", call. = FALSE)
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
  if (!is.character(payload$population_csv_path) || !nzchar(payload$population_csv_path)) {
    stop("Worker request requires a non-empty population_csv_path.", call. = FALSE)
  }
  if (!file.exists(payload$population_csv_path)) {
    stop(
      sprintf("Population CSV file does not exist: %s", payload$population_csv_path),
      call. = FALSE
    )
  }
  if (!is.character(payload$result_csv_path) || !nzchar(payload$result_csv_path)) {
    stop("Worker request requires a non-empty result_csv_path.", call. = FALSE)
  }
  if (!is.numeric(payload$expected_population_count) || payload$expected_population_count < 1) {
    stop("Worker request requires a positive expected_population_count.", call. = FALSE)
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
  timing <- list()

  # loadPopulation() reconstructs directly from the CSV file -- proven
  # (v0.6-C capability probe) to produce a population identical, column for
  # column, to populationFromDataFrame() on the same table.
  t_load_start <- Sys.time()
  population <- tryCatch(
    loadPopulation(payload$population_csv_path),
    error = function(error) {
      stop(
        sprintf("Could not load the population CSV file: %s", conditionMessage(error)),
        call. = FALSE
      )
    }
  )
  reconstructed_count <- nrow(populationToDataFrame(population))
  timing$population_load_seconds <- as.numeric(Sys.time() - t_load_start, units = "secs")
  if (reconstructed_count != payload$expected_population_count) {
    stop("Reconstructed population individual count does not match expected_population_count.", call. = FALSE)
  }

  readback_columns <- payload$population_readback_columns
  population_readback <- NULL
  if (!is.null(readback_columns) && length(readback_columns) > 0) {
    readback_columns <- unlist(readback_columns, use.names = FALSE)
    readback_table <- populationToDataFrame(population)
    missing_readback <- setdiff(readback_columns, names(readback_table))
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
    population_readback <- lapply(seq_len(nrow(readback_table)), function(index) {
      as.list(readback_table[index, select_columns, drop = FALSE])
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

  t_solve_start <- Sys.time()
  simulation_results <- runSimulations(simulations = simulation, population = population)
  verification$solver_executed <- TRUE
  timing$solver_seconds <- as.numeric(Sys.time() - t_solve_start, units = "secs")
  if (length(simulation_results) != 1) {
    stop("The population execution worker expects exactly one combined population result.", call. = FALSE)
  }

  # simulationResultsToDataFrame() is cheap (~0.05s at N=100, measured) --
  # kept only to derive result_individual_ids/observed_output_times, never
  # to build the row-list-plus-toJSON payload that dominated runtime before.
  result_frame <- simulationResultsToDataFrame(simulation_results[[1]])
  if (nrow(result_frame) == 0) {
    stop("OSP population simulation completed without output rows.", call. = FALSE)
  }
  if (!"IndividualId" %in% names(result_frame)) {
    stop("OSP population simulation result is missing IndividualId.", call. = FALSE)
  }
  result_individual_ids <- sort(unique(as.integer(result_frame$IndividualId)))
  observed_output_times <- if (schedule_applied) as.list(sort(unique(result_frame$Time))) else NULL

  t_export_start <- Sys.time()
  exportResultsToCSV(simulation_results[[1]], payload$result_csv_path)
  if (!file.exists(payload$result_csv_path)) {
    stop("exportResultsToCSV did not produce the expected result CSV file.", call. = FALSE)
  }
  result_csv_sha256 <- sha256_file(payload$result_csv_path)
  timing$result_export_seconds <- as.numeric(Sys.time() - t_export_start, units = "secs")

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
    result_csv_sha256 = result_csv_sha256,
    timing = timing,
    execution_verification = verification
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
