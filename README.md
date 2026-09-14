# Course Planner Agent

An extensible AI course-planning engine that combines Gemini function calling with deterministic graph reasoning.

Instead of relying on a language model to remember course requirements, the agent uses structured course data and Python logic as the source of truth. Gemini handles natural-language questions and tool selection, while prerequisite evaluation, eligibility checks, and course-path planning are computed deterministically.

The included University of Alberta CMPUT dataset acts as a reference implementation. Other institutions can plug in their own structured datasets without changing the core planning engine.

## Why not just ask Gemini?

Course requirements are structured facts, not something a language model should guess from memory.

A general-purpose LLM can use outdated information, misunderstand nested prerequisites, or confidently invent requirements that are not actually in a course catalogue. It also does not automatically know which courses a specific student has completed or is currently taking.

This project separates those responsibilities:

- **Gemini** interprets the student's question and selects the appropriate tool.
- **Python** evaluates prerequisites, corequisites, eligibility, and prerequisite paths deterministically.
- **Structured datasets** provide the course facts.
- **Gemini** turns the verified tool result back into a natural-language answer.

```text
Gemini interprets → Python decides → structured data provides facts → Gemini explains
```

This keeps the flexibility of a conversational interface while making the actual course-planning decisions reproducible and grounded in the selected dataset.

## Features

- Natural-language course planning through Gemini function calling
- Recursive prerequisite and corequisite evaluation
- Nested `AND` / `OR` requirement rules
- Student profiles with completed and current courses
- Eligibility checking
- Missing-requirement explanations
- Reverse dependency lookup
- Deterministic target-course planning
- Alternative prerequisite-path selection
- External requirement reporting
- Course-code normalization
- Dataset validation
- DFS cycle detection
- Kahn topological sorting
- Configurable JSON course datasets
- CLI with profiles, custom datasets, one-off questions, and tool traces
- 33 automated tests

## How it works

```text
                  natural-language question
                           |
                           v
                     +-----------+
                     |  Gemini   |
                     +-----------+
                           |
                    selects a tool
                           |
                           v
              +-------------------------+
              | Deterministic Python    |
              | planning / graph engine |
              +-------------------------+
                 |        |         |
                 v        v         v
            eligibility  rules   path planning
                 \        |        /
                  \       |       /
                   v      v      v
                 structured dataset
                           |
                           v
                     tool result
                           |
                           v
                     +-----------+
                     |  Gemini   |
                     +-----------+
                           |
                           v
                 natural-language answer
```

The language model does not decide whether a prerequisite is satisfied. It chooses which deterministic operation to run and explains the result.

## Example scenarios

The repository includes `examples/student.json`:

```json
{
  "completed_courses": [
    "CMPUT 175",
    "CMPUT 272",
    "MATH 134"
  ],
  "current_courses": [
    "CMPUT 201"
  ]
}
```

### 1. Checking course eligibility

```bash
python -m app.cli \
  --profile examples/student.json \
  --question "Can I take CMPUT 291?" \
  --trace
```

Tool trace:

```text
-> tool: check_eligibility({'course_code': 'CMPUT 291'})
<- result: {"corequisites": {"missing": null, "satisfied": true}, "course": "CMPUT 291", "eligible": true, "known": true, "prerequisites": {"missing": null, "satisfied": true}}

-> tool: get_course_requirements({'course_code': 'CMPUT 291'})
<- result: {"corequisites": {"or": ["CMPUT 201", "CMPUT 275"]}, "course": "CMPUT 291", "known": true, "prerequisites": {"and": [{"or": ["CMPUT 175", "CMPUT 274"]}, "CMPUT 272"]}, "title": "Introduction to File and Database Management", "units": 3}
```

Example response:

```text
Yes, you are eligible to take CMPUT 291.

Prerequisites:
(CMPUT 175 or CMPUT 274) and CMPUT 272 — satisfied

Corequisites:
CMPUT 201 or CMPUT 275 — satisfied
```

The model handles the conversation, but the eligibility result comes from the deterministic rule engine.

### 2. Explaining nested requirements

```bash
python -m app.cli \
  --profile examples/student.json \
  --question "What are the prerequisites and corequisites for CMPUT 267?" \
  --trace
```

Gemini selects `get_course_requirements`, which returns the structured rule tree:

```text
Prerequisites:

(CMPUT 174 OR CMPUT 274 OR ENCMP 100)

AND

(MATH 100 OR MATH 114 OR MATH 117
 OR MATH 134 OR MATH 144 OR MATH 154)
```

The same structure is preserved for corequisites instead of being flattened or guessed by the language model.

Example response:

```text
Prerequisites

1. One of:
   CMPUT 174, CMPUT 274, or ENCMP 100

AND

2. One of:
   MATH 100, MATH 114, MATH 117,
   MATH 134, MATH 144, or MATH 154

Corequisites

1. CMPUT 175 or CMPUT 275
2. CMPUT 272
3. One of MATH 102, MATH 125, MATH 126, or MATH 127
4. One of STAT 151, STAT 161, STAT 181, STAT 235,
   STAT 265, SCI 151, or MATH 181
```

### 3. Planning toward a future course

```bash
python -m app.cli \
  --profile examples/student.json \
  --question "How can I eventually get to CMPUT 469?" \
  --trace
```

The model calls the target-course planner:

```text
-> tool: plan_to_course({'course_code': 'CMPUT 469'})
<- result: {
  "already_completed": false,
  "corequisites": {
    "missing": null,
    "satisfied": true
  },
  "external_requirements": [
    "CMPUT 466"
  ],
  "in_progress": false,
  "known": true,
  "prerequisite_plan": [
    "CMPUT 466",
    "CMPUT 365",
    "CMPUT 204",
    "CMPUT 366"
  ],
  "target": "CMPUT 469"
}
```

The planner works backward through the prerequisite graph while taking the student's completed and current courses into account.

`CMPUT 466` is reported as an external requirement because it is referenced by the UAlberta data but is not included in the current 18-course reference dataset. The engine does not invent prerequisites for courses it cannot expand.

## Target-course planning

Target planning is handled separately from Gemini.

For an `AND` rule, every required branch must be included.

For an `OR` rule, the planner compares the available paths and chooses the one requiring the fewest remaining courses. Ties are resolved deterministically.

Courses already completed or currently in progress are not recommended again.

The planner returns:

- the ordered prerequisite path
- external requirements it cannot recursively expand
- whether the target is already completed
- whether the target is currently in progress
- target corequisite status

The planner does not generate semester schedules or predict when courses will be offered.

## Reference dataset

`datasets/ualberta_cmput.json` contains a curated University of Alberta CMPUT dataset with 18 courses.

The courses were selected to exercise different parts of the engine, including:

- multi-course prerequisite chains
- nested `AND` / `OR` requirements
- corequisites
- alternative paths
- dependencies outside the local dataset

Course records include official catalogue source URLs and verification dates where available.

The dataset is intentionally not a complete University of Alberta course catalogue.

## Repository structure

```text
course-planner-agent/
├── app/
│   ├── agent.py
│   ├── cli.py
│   ├── graph.py
│   ├── planner.py
│   └── profile.py
│
├── datasets/
│   ├── template.json
│   └── ualberta_cmput.json
│
├── examples/
│   └── student.json
│
├── tests/
│   ├── ...
│   └── test_planner.py
│
├── .env.example
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── requirements.txt
```

## Setup

Clone the repository:

```bash
git clone https://github.com/JotsaroopSinghh/course-planner-agent.git
cd course-planner-agent
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```text
GEMINI_API_KEY=your_key_here
```

You can use `.env.example` as a template.

## Usage

Use the included student profile:

```bash
python -m app.cli \
  --profile examples/student.json \
  --question "Can I take CMPUT 291?"
```

Ask what courses are currently available:

```bash
python -m app.cli \
  --profile examples/student.json \
  --question "What can I take next?"
```

Plan toward a target course:

```bash
python -m app.cli \
  --profile examples/student.json \
  --question "How can I eventually get to CMPUT 469?"
```

Enable tool traces:

```bash
python -m app.cli \
  --profile examples/student.json \
  --question "Can I take CMPUT 291?" \
  --trace
```

You can also provide student state directly:

```bash
python -m app.cli \
  --completed "CMPUT 175,CMPUT 272,MATH 134" \
  --current "CMPUT 201" \
  --question "Can I take CMPUT 291?"
```

Run without `--question` to enter interactive mode:

```bash
python -m app.cli --profile examples/student.json
```

## Using another institution's dataset

The planning engine is not tied to UAlberta.

A different dataset can be loaded through the CLI:

```bash
python -m app.cli \
  --dataset datasets/my_university.json \
  --completed "CS 101,MATH 100" \
  --question "What can I take next?"
```

A minimal course might look like:

```json
{
  "CS 201": {
    "title": "Data Structures",
    "units": 3,
    "prereqs": {
      "and": [
        "CS 101",
        {
          "or": [
            "MATH 100",
            "MATH 110"
          ]
        }
      ]
    }
  }
}
```

See `datasets/template.json` for a starting point and `CONTRIBUTING.md` for more information.

## Testing

Run the complete test suite with:

```bash
python -m unittest discover -s tests -v
```

The current suite contains 33 tests covering areas including:

- course-code normalization
- student profiles
- nested prerequisite expressions
- corequisites
- eligibility
- missing requirements
- custom datasets
- reference dataset validation
- cycle detection
- topological ordering
- deterministic target-course planning
- Gemini tool dispatch
- mocked multi-round tool interactions
- CLI behavior

Agent tests mock Gemini interactions, so the deterministic behavior can be tested without making live API requests.

## Current limitations

The v1 rule engine represents course prerequisites and corequisites using course codes and nested `AND` / `OR` expressions.

It does not currently evaluate:

- minimum grade requirements
- year or credit standing
- program or faculty restrictions
- instructor or department permission
- anti-requisites or credit exclusions
- term availability
- timetable conflicts
- degree requirements

Eligibility therefore means that the requirements represented in the currently loaded dataset are satisfied. It is not a guarantee of official registration eligibility.

The bundled UAlberta dataset is also intentionally incomplete. If a referenced course is not present, the planner reports it as an external requirement rather than inventing information.

## Contributing

Contributions are welcome, especially additional datasets and corrections to existing course data.

See `CONTRIBUTING.md`.

## License

MIT