# Contributing

Contributions are welcome, especially if you want to add a new course dataset, improve an existing one, or fix something in the planner.

## Adding a dataset

The easiest way to add support for another university or department is to copy `datasets/template.json` and use it as a starting point.

Course requirements can be written using course codes and nested `and` / `or` rules.

For example:

```json
{
  "CS 201": {
    "title": "Data Structures",
    "units": 3,
    "prereqs": {
      "and": [
        "CS 101",
        {"or": ["MATH 100", "MATH 110"]}
      ]
    }
  }
}
```

You can also add a `coreqs` field if the course has corequisites.

For real course data, adding the official catalogue URL and the date you checked it is helpful:

```json
"source": "https://example.edu/catalogue/cs201",
"verified": "YYYY-MM-DD"
```

These fields are recommended for traceability, but the core planner does not require them.

## Testing a custom dataset

You can try a dataset without changing the application code:

```bash
python -m app.cli \
  --dataset datasets/my_university.json \
  --completed "CS 101,MATH 100" \
  --question "What can I take next?"
```

## Running tests

Before submitting changes, run:

```bash
python -m unittest discover -s tests -v
```

## Current limitations

The current rule engine handles:

- course prerequisites
- corequisites
- nested `and` rules
- nested `or` rules

It does not currently model things like minimum grades, year standing, program restrictions, instructor permission, anti-requisites, or scheduling constraints.

If a university has one of those requirements, it is better to leave it out than represent it incorrectly as a normal prerequisite.
