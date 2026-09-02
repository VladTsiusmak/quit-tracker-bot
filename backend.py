"""
Бэкенд для трекера отказа от вредных привычек.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "quit_tracker.db"
STATIC_DIR = Path(__file__).parent / "static"

HabitType = Literal["vape", "alcohol"]

app = FastAPI(title="Quit Habits Tracker API")


def init_db():
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS habits
            (
                user_id
                INTEGER
                NOT
                NULL,
                type
                TEXT
                NOT
                NULL,
                quit_date
                TEXT
                NOT
                NULL,
                per_day
                REAL
                NOT
                NULL,
                unit_price
                REAL
                NOT
                NULL,
                unit_size
                REAL
                NOT
                NULL,
                PRIMARY
                KEY
            (
                user_id,
                type
            )
                )
            """
        )
        db.commit()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


class Habit(BaseModel):
    user_id: int
    type: HabitType
    quit_date: str
    per_day: float
    unit_price: float
    unit_size: float


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/habits/{user_id}")
def get_habits(user_id: int):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM habits WHERE user_id = ?", (user_id,)
        ).fetchall()
        return {"habits": [dict(row) for row in rows]}


@app.post("/api/habits")
def save_habit(habit: Habit):
    with get_db() as db:
        db.execute(
            """
            INSERT INTO habits (user_id, type, quit_date, per_day, unit_price, unit_size)
            VALUES (:user_id, :type, :quit_date, :per_day, :unit_price, :unit_size) ON CONFLICT(user_id, type) DO
            UPDATE SET
                quit_date = excluded.quit_date,
                per_day = excluded.per_day,
                unit_price = excluded.unit_price,
                unit_size = excluded.unit_size
            """,
            habit.model_dump(),
        )
        db.commit()
    return {"ok": True}


@app.delete("/api/habits/{user_id}/{habit_type}")
def delete_habit(user_id: int, habit_type: str):
    with get_db() as db:
        db.execute(
            "DELETE FROM habits WHERE user_id = ? AND type = ?", (user_id, habit_type)
        )
        db.commit()
    return {"ok": True}


@app.delete("/api/habits/{user_id}")
def delete_all_habits(user_id: int):
    with get_db() as db:
        db.execute("DELETE FROM habits WHERE user_id = ?", (user_id,))
        db.commit()
    return {"ok": True}


@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
