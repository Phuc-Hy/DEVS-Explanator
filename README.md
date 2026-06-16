# DEVS-Explanator

Simulation-Grounded Verification and Causal Feedback for LLM-Generated Infrastructure Policies

Paper accepted at Winter Simulation Conference (WSC) 2026.

## Overview

DEVS-Explanator is a five-layer framework that uses DEVS simulation to verify LLM-generated infrastructure policies and extract causal explanations when constraint violations occur.

```
Layer 1  LLM Policy Generation     generates action schedule Σ via Gemini
Layer 2  DEVS Simulation           executes Σ on a coupled DEVS grid model
Layer 3  Constraint Check          detects RELAY_TRIP and BLACKOUT violations
Layer 4  Causal Trace Extraction   backward chaining over simulation trace → causal graph G
Layer 5  Feedback Generation       formats causal critique → LLM for next iteration
```

The pipeline iterates up to `N_max = 3` times until a valid policy is found.

## Dataset

RTS-GMLC Area 1 (24 buses, 38 branches, 52 generators). Data is not included in this repository. Download from:

https://github.com/GridMod/RTS-GMLC

Place the data under `data/RTS-GMLC/RTS_Data/`.

## Requirements

- Python 3.10+

```
pip install -r requirements.txt
```

PythonPDEVS is installed automatically from https://github.com/capocchi/PythonPDEVS via the requirements file.

## Setup

1. Clone this repository.
2. Create a file `code/.env` with your Gemini API key:

```
GEMINI_API_KEY=your_key_here
```

3. Run preprocessing to build the bus model and prompt:

```
python code/preprocessing/build_bus_model.py
python code/preprocessing/build_prompt_24bus.py
```

## Running the pipeline

Single run:

```
python code/run_pipeline.py
```

100-run experiment:

```
python code/run_experiments.py
```

Results are saved under `code/iterations/` (per iteration) and `code/experiments/` (aggregate).

## Code structure

```
code/
  preprocessing/
    build_bus_model.py       computes PTDF matrix, outputs bus_model.json
    build_prompt_24bus.py    generates structured scenario prompt from bus_model.json
  layer_1/
    policy_generator.py      calls Gemini API, parses and validates action_schedule.json
  layer_2/
    atomic_models.py         ActionScheduler, GeneratorModel, BusModel, BranchModel, TraceCollector
    coupled_model.py         GridModel24 coupled DEVS model
    simulate.py              runs simulation, outputs simulation_trace.json
  layer_3/
    checker.py               constraint predicates, outputs verdict.json
  layer_4/
    extractor.py             Algorithm 1: backward chaining, outputs causal_graph.json
  layer_5/
    feedback.py              rule-based correction table, outputs critique.json
  run_pipeline.py            orchestrator (N_max=3 iterations)
  run_experiments.py         runs pipeline 100 times, outputs experiments/summary.json
```

## Authors

Ho Phuc Hy <sup>1</sup>, Ali Ayadi <sup>2</sup>, and Claudia Frydman <sup>1</sup>

<sup>1</sup> LIS — UMR CNRS 7020 — University of Aix-Marseille, Marseille, France  
<sup>2</sup> ICube — UMR CNRS 7357 — University of Strasbourg, Strasbourg, France
