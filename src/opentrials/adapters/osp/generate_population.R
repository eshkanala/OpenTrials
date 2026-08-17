#!/usr/bin/env Rscript

# Minimal headless OSP population-generation worker. It returns the raw OSP
# population table without materializing OpenTrials patients or running PBPK.

worker_request_schema <- "opentrials.osp.population-worker-request"
worker_response_schema <- "opentrials.osp.population-worker-response"
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
    stop("Unsupported OSP population worker request schema.", call. = FALSE)
  }
  if (!identical(request$schema_version, worker_schema_version)) {
    stop("Unsupported OSP population worker request schema version.", call. = FALSE)
  }
  payload <- request$payload
  suppressPackageStartupMessages(library(ospsuite))
  required_fields <- c(
    "population_id",
    "number_of_individuals",
    "requested_seed",
    "reference_population",
    "age_minimum_years",
    "age_maximum_years",
    "proportion_female_percent"
  )
  if (!is.list(payload) || !all(required_fields %in% names(payload))) {
    stop("Population worker request is missing required fully-mapped fields.", call. = FALSE)
  }
  if (!is.character(payload$population_id) || !nzchar(payload$population_id)) {
    stop("Population worker request requires a non-empty population_id.", call. = FALSE)
  }
  if (!is.numeric(payload$number_of_individuals) || payload$number_of_individuals < 1) {
    stop("Population worker request requires a positive number_of_individuals.", call. = FALSE)
  }
  if (!is.numeric(payload$requested_seed)) {
    stop("Population worker request requires a numeric requested_seed.", call. = FALSE)
  }
  if (!payload$reference_population %in% names(HumanPopulation)) {
    stop("Population worker request has an unsupported OSP reference population.", call. = FALSE)
  }
  if (
    !is.numeric(payload$age_minimum_years) || !is.numeric(payload$age_maximum_years) ||
      !is.numeric(payload$proportion_female_percent)
  ) {
    stop("Population worker requires explicit age bounds and female proportion in v0.1-B3b.", call. = FALSE)
  }

  # OSP's population-characteristics seed controls its internal generator.
  characteristics <- createPopulationCharacteristics(
    species = Species$Human,
    population = HumanPopulation[[payload$reference_population]],
    numberOfIndividuals = payload$number_of_individuals,
    proportionOfFemales = payload$proportion_female_percent,
    ageMin = payload$age_minimum_years,
    ageMax = payload$age_maximum_years,
    ageUnit = "year(s)",
    seed = payload$requested_seed
  )
  generated <- createPopulation(populationCharacteristics = characteristics)
  population_table <- populationToDataFrame(generated$population)
  if (nrow(population_table) != payload$number_of_individuals) {
    stop("OSP population generation returned an unexpected individual count.", call. = FALSE)
  }
  rows <- lapply(seq_len(nrow(population_table)), function(index) {
    as.list(population_table[index, , drop = FALSE])
  })

  write_response(list(
    status = "SUCCEEDED",
    population_id = payload$population_id,
    requested_seed = payload$requested_seed,
    engine_seed = generated$seed,
    determinism_level = "STRICT",
    r_version = R.version.string,
    ospsuite_version = as.character(utils::packageVersion("ospsuite")),
    column_names = names(population_table),
    raw_rows = rows
  ))
}

tryCatch(
  run_worker(),
  error = function(error) {
    write_response(list(
      status = "FAILED",
      error = conditionMessage(error)
    ))
    quit(status = 1)
  }
)
