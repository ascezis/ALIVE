"""Load the ALIVE exercise catalog into a local SQLite database."""

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


BACKEND = Path(__file__).resolve().parent
DEFAULT_SOURCE = BACKEND.parent / "src" / "lfk-spec.json"
DEFAULT_DATABASE = BACKEND / "data" / "lfk.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS lfk_imports (
    id INTEGER PRIMARY KEY,
    checksum TEXT NOT NULL UNIQUE,
    spec_version TEXT NOT NULL,
    content_status TEXT NOT NULL,
    source_json TEXT NOT NULL CHECK (json_valid(source_json)),
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lfk_exercises (
    import_id INTEGER NOT NULL REFERENCES lfk_imports(id),
    exercise_id TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('reps', 'timer')),
    exercise_json TEXT NOT NULL CHECK (json_valid(exercise_json)),
    PRIMARY KEY (import_id, exercise_id)
);

CREATE TABLE IF NOT EXISTS lfk_programs (
    import_id INTEGER NOT NULL REFERENCES lfk_imports(id),
    program_id TEXT NOT NULL,
    version TEXT NOT NULL,
    title TEXT NOT NULL,
    estimated_minutes INTEGER NOT NULL CHECK (estimated_minutes >= 0),
    program_json TEXT NOT NULL CHECK (json_valid(program_json)),
    PRIMARY KEY (import_id, program_id, version)
);

CREATE TABLE IF NOT EXISTS lfk_program_exercises (
    import_id INTEGER NOT NULL,
    program_id TEXT NOT NULL,
    program_version TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position > 0),
    exercise_id TEXT NOT NULL,
    advisory TEXT,
    PRIMARY KEY (import_id, program_id, program_version, position),
    FOREIGN KEY (import_id, program_id, program_version)
        REFERENCES lfk_programs(import_id, program_id, version),
    FOREIGN KEY (import_id, exercise_id)
        REFERENCES lfk_exercises(import_id, exercise_id)
);
"""


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def import_catalog(source: Path, database: Path) -> tuple[int, bool]:
    source_text = source.read_text(encoding="utf-8-sig")
    spec = json.loads(source_text)
    checksum = sha256(encode(spec).encode("utf-8")).hexdigest()
    meta = spec["meta"]
    exercises = spec["exercise_library"]
    programs = spec["programs"]

    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
        existing = db.execute(
            "SELECT id FROM lfk_imports WHERE checksum = ?", (checksum,),
        ).fetchone()
        if existing:
            return existing[0], False

        cursor = db.execute(
            """INSERT INTO lfk_imports (checksum, spec_version, content_status, source_json)
               VALUES (?, ?, ?, ?)""",
            (checksum, meta["spec_version"], meta["content_status"], source_text),
        )
        import_id = cursor.lastrowid
        db.executemany(
            """INSERT INTO lfk_exercises (import_id, exercise_id, title, kind, exercise_json)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (import_id, item["id"], item["title"], item["kind"], encode(item))
                for item in exercises
            ],
        )
        for program in programs:
            program_key = (import_id, program["id"], program["version"])
            db.execute(
                """INSERT INTO lfk_programs
                   (import_id, program_id, version, title, estimated_minutes, program_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (*program_key, program["title"], program["estimated_minutes"], encode(program)),
            )
            advisories = program.get("item_advisories", {})
            unknown = advisories.keys() - set(program["items"])
            if unknown:
                raise ValueError(f"Advisories refer to exercises outside {program['id']}: {', '.join(sorted(unknown))}")
            db.executemany(
                """INSERT INTO lfk_program_exercises
                   (import_id, program_id, program_version, position, exercise_id, advisory)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (*program_key, position, exercise_id, advisories.get(exercise_id))
                    for position, exercise_id in enumerate(program["items"], start=1)
                ],
            )
        return import_id, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="source JSON spec")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE, help="target SQLite file")
    args = parser.parse_args()

    try:
        import_id, created = import_catalog(args.source, args.database)
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Import failed: {error}\n")

    action = "Imported" if created else "Already imported"
    print(f"{action}: catalog {import_id} in {args.database.resolve()}")


if __name__ == "__main__":
    main()
