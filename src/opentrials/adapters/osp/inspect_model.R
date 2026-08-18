#!/usr/bin/env Rscript

# Read-only, generic PKML inspection worker for `opentrials model inspect`.
# Reports what ospsuite itself can discover about a simulation file --
# molecule names, administration event containers and their mutable
# parameter paths, candidate observable output paths, a total mutable
# parameter count, and a population-compatibility heuristic. Discovery
# only: this worker makes no claim about which of these facts constitute
# a verified, usable OpenTrials capability -- that judgment belongs to a
# researcher reviewing `opentrials model init`'s generated scaffold, never
# to this script.

worker_request_schema <- "opentrials.osp.model-inspection-worker-request"
worker_response_schema <- "opentrials.osp.model-inspection-worker-response"
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

# Candidate administration-parameter roles this project has previously
# verified matter (see models/profiles/aciclovir_iv.py's own dose/
# administration-time/infusion-duration paths, discovered this same way).
# Any other leaf name is still reported, just not classified into a role.
ROLE_SUFFIXES <- list(
  dose = "Dose",
  start_time = "Start time",
  infusion_duration = "Infusion time"
)

run_worker <- function() {
  request <- jsonlite::fromJSON(input_path, simplifyVector = FALSE)
  if (!identical(request$schema, worker_request_schema)) {
    stop("Unsupported model inspection worker request schema.", call. = FALSE)
  }
  if (!identical(request$schema_version, worker_schema_version)) {
    stop("Unsupported model inspection worker request schema version.", call. = FALSE)
  }
  payload <- request$payload
  if (!is.character(payload$pkml_path) || !nzchar(payload$pkml_path)) {
    stop("Worker request requires a non-empty pkml_path.", call. = FALSE)
  }
  if (!file.exists(payload$pkml_path)) {
    stop(sprintf("PKML file does not exist: %s", payload$pkml_path), call. = FALSE)
  }

  suppressPackageStartupMessages(library(ospsuite))
  simulation <- loadSimulation(payload$pkml_path)

  all_paths <- getAllParameterPathsIn(simulation)
  molecule_paths <- tryCatch(getAllMoleculePathsIn(simulation), error = function(e) character(0))
  molecule_names <- unique(vapply(
    strsplit(molecule_paths, "|", fixed = TRUE),
    function(parts) parts[[length(parts)]],
    character(1)
  ))

  event_paths <- Filter(function(p) startsWith(p, "Events|"), all_paths)
  container_names <- unique(sub("^(Events\\|[^|]+\\|).*$", "\\1", event_paths))
  administrations <- lapply(container_names, function(container) {
    own_paths <- Filter(function(p) startsWith(p, container), event_paths)
    leaf_names <- vapply(
      strsplit(own_paths, "|", fixed = TRUE),
      function(parts) parts[[length(parts)]],
      character(1)
    )
    roles <- list()
    for (role in names(ROLE_SUFFIXES)) {
      matches <- own_paths[leaf_names == ROLE_SUFFIXES[[role]]]
      if (length(matches) > 0) {
        roles[[role]] <- matches[[1]]
      }
    }
    list(container = container, parameter_paths = own_paths, roles = roles)
  })

  output_paths <- tryCatch(getAllObserverPathsIn(simulation), error = function(e) character(0))
  # Administration-internal bookkeeping observers (dose-container running
  # totals) are not candidate PK outputs -- excluded so this list stays
  # focused on organism-level observable quantities.
  output_paths <- Filter(function(p) !startsWith(p, "Events|"), output_paths)

  population_support <- any(grepl("^Organism\\|Age$", all_paths))

  write_response(list(
    status = "SUCCEEDED",
    generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    r_version = R.version.string,
    ospsuite_version = as.character(utils::packageVersion("ospsuite")),
    name = simulation$name,
    molecule_names = as.list(molecule_names),
    administrations = administrations,
    output_paths = as.list(output_paths),
    mutable_parameter_count = length(all_paths),
    population_support_detected = population_support
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
