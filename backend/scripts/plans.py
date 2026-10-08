"""Shared machinery of the EXPLAIN scripts: record a scenario's SQL, then explain it.

Each scenario calls the same repository or service code the API calls,
records the SQL it sends to PostgreSQL, and then runs ``EXPLAIN (ANALYZE,
BUFFERS)`` on every recorded statement with its real parameters. What is
measured is therefore exactly what the API runs, not a hand-copied
approximation.
"""

import argparse
import statistics
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, event, func, select, text
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models import Order


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    description: str
    run: Callable[[], object]


@dataclass(frozen=True, slots=True)
class Statement:
    sql: str
    parameters: Any


@dataclass(frozen=True, slots=True)
class Measurement:
    scenario: Scenario
    statements: int
    execution_ms: list[float]
    """Per run, summed over the scenario's statements."""
    planning_ms: float
    shared_hit_blocks: int
    shared_read_blocks: int
    outlines: list[list[str]]
    """One plan outline per statement, from the median run."""

    @property
    def median_ms(self) -> float:
        return statistics.median(self.execution_ms)


@contextmanager
def recorded_statements(connection: Connection) -> Iterator[list[Statement]]:
    """Record every statement sent on ``connection`` inside the block."""
    recorded: list[Statement] = []

    def record(
        _conn: Connection,
        _cursor: Any,
        statement: str,
        parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        recorded.append(Statement(statement, parameters))

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield recorded
    finally:
        event.remove(connection, "before_cursor_execute", record)


def measure(session: Session, scenario: Scenario, runs: int) -> Measurement:
    """Run ``scenario`` once to record its SQL, then EXPLAIN ANALYZE that SQL ``runs`` times.

    One unmeasured run comes first, so every measured run finds the same data
    in memory and the numbers describe the plan rather than the disk.
    """
    with recorded_statements(session.connection()) as statements:
        scenario.run()
    connection = session.connection()
    _explain_all(connection, statements)
    results = [_explain_all(connection, statements) for _ in range(runs)]
    totals = [sum(plan["Execution Time"] for plan in result) for result in results]
    median_run = results[sorted(range(runs), key=totals.__getitem__)[(runs - 1) // 2]]
    return Measurement(
        scenario=scenario,
        statements=len(statements),
        execution_ms=totals,
        planning_ms=sum(plan["Planning Time"] for plan in median_run),
        shared_hit_blocks=sum(plan["Plan"].get("Shared Hit Blocks", 0) for plan in median_run),
        shared_read_blocks=sum(plan["Plan"].get("Shared Read Blocks", 0) for plan in median_run),
        outlines=[outline(plan["Plan"]) for plan in median_run],
    )


def _explain_all(connection: Connection, statements: Sequence[Statement]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for statement in statements:
        # psycopg decodes the json column: a list holding one plan document.
        document: list[dict[str, Any]] = connection.exec_driver_sql(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement.sql}", statement.parameters
        ).scalar_one()
        plans.append(document[0])
    return plans


def outline(node: dict[str, Any], depth: int = 0) -> list[str]:
    """A plan as indented one-line nodes: type, index, table, rows and rows filtered out."""
    node_type = node["Node Type"]
    if node.get("Scan Direction") == "Backward":
        node_type += " Backward"
    parts = [node_type]
    if "Index Name" in node:
        parts.append(f"using {node['Index Name']}")
    if "Relation Name" in node:
        parts.append(f"on {node['Relation Name']}")
    details = [f"rows={node['Actual Rows']}"]
    if node.get("Actual Loops", 1) != 1:
        details.append(f"loops={node['Actual Loops']}")
    removed = node.get("Rows Removed by Filter", 0) + node.get("Rows Removed by Join Filter", 0)
    if removed:
        details.append(f"removed by filter={removed}")
    if "Workers Launched" in node:
        details.append(f"workers={node['Workers Launched']}")
    if "Sort Method" in node:
        details.append(f"sort={node['Sort Method']}")
    lines = ["  " * depth + " ".join(parts) + f" ({', '.join(details)})"]
    for child in node.get("Plans", []):
        lines.extend(outline(child, depth + 1))
    return lines


def render(measurement: Measurement) -> str:
    scenario = measurement.scenario
    lines = [
        f"## {scenario.name}: {scenario.description}",
        f"median {measurement.median_ms:.2f} ms, max {max(measurement.execution_ms):.2f} ms "
        f"over {len(measurement.execution_ms)} runs; planning {measurement.planning_ms:.2f} ms; "
        f"buffers hit {measurement.shared_hit_blocks:,}, read {measurement.shared_read_blocks:,}",
    ]
    for number, plan in enumerate(measurement.outlines, start=1):
        if measurement.statements > 1:
            lines.append(f"statement {number}:")
        lines.extend(f"    {line}" for line in plan)
    return "\n".join(lines)


def summary_table(measurements: Sequence[Measurement]) -> str:
    lines = [
        "| Scenario | Statements | Median ms | Max ms | Buffers hit / read |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {m.scenario.name} | {m.statements} | {m.median_ms:.2f} | "
        f"{max(m.execution_ms):.2f} | {m.shared_hit_blocks:,} / {m.shared_read_blocks:,} |"
        for m in measurements
    )
    return "\n".join(lines)


def server_report(session: Session) -> str:
    settings = ", ".join(
        f"{name}={session.scalar(text(f'SHOW {name}'))}"
        for name in ("shared_buffers", "work_mem", "jit", "max_parallel_workers_per_gather")
    )
    indexes = session.scalars(
        text(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
            "AND tablename IN ('customers', 'products', 'orders', 'order_items') ORDER BY 1"
        )
    ).all()
    return (
        f"{session.scalar(text('SELECT version()'))}\n"
        f"{settings}\n"
        f"orders: {session.scalar(select(func.count()).select_from(Order)):,} rows\n"
        f"indexes: {', '.join(indexes)}"
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The options every EXPLAIN script accepts."""
    parser.add_argument("--runs", type=int, default=10, help="measured runs per scenario")
    parser.add_argument("--only", nargs="*", default=None, help="scenario names to run")


def explain(
    build_scenarios: Callable[[Session], list[Scenario]], *, runs: int, only: Sequence[str] | None
) -> None:
    """Measure and print every scenario (or those named in ``only``) on the dev database."""
    app = create_app()
    with app.app_context():
        session = db.session()
        # EXPLAIN ANALYZE executes each statement; this transaction guarantees
        # that nothing measured can write.
        session.execute(text("SET TRANSACTION READ ONLY"))
        try:
            print(server_report(session), end="\n\n")
            selected = [s for s in build_scenarios(session) if only is None or s.name in only]
            measurements = []
            for scenario in selected:
                measurement = measure(session, scenario, runs)
                measurements.append(measurement)
                print(render(measurement), end="\n\n", flush=True)
            print(summary_table(measurements))
        finally:
            session.rollback()
